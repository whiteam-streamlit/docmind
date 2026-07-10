"""
rag.py — nucleo del sistema RAG su elementi strutturati e testo.

Store separati:
  store/structured/  — chunk strutturati (table, figure, figure_data, formula)
  store/text/        — chunk testuali per paragrafo/sezione
  store/corrections.json — correzioni manuali (condiviso, sopravvive alla re-indicizzazione)

Modalita' di retrieval:
  "structured" — solo elementi strutturati (default)
  "combined"   — strutturati + testo
"""
import os, json
from datetime import datetime
import numpy as np
import anthropic
from dotenv import load_dotenv
load_dotenv()
GEN_MODEL        = "claude-sonnet-4-6"
EMBED_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
STORE_DIR        = "store/structured"
TEXT_STORE_DIR   = "store/text"
CORRECTIONS_FILE = "store/corrections.json"

RETRIEVAL_TYPES  = {"table", "figure", "figure_data", "formula"}

_embedder = None
def embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer  # import lazy
        _embedder = SentenceTransformer(EMBED_MODEL_NAME)
    return _embedder

def embed(texts):
    """Embedding normalizzati (coseno = dot product)."""
    return np.asarray(
        embedder().encode(texts, normalize_embeddings=True, show_progress_bar=False),
        dtype=np.float32,
    )

# ---------- store su disco ---------------------------------------------------

def save_store(chunks, vectors, store_dir=STORE_DIR):
    os.makedirs(store_dir, exist_ok=True)
    with open(os.path.join(store_dir, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    np.save(os.path.join(store_dir, "embeddings.npy"), vectors)

_store_cache: dict = {}

def load_store(store_dir=STORE_DIR):
    """Carica store da disco; usa cache in-memory finché il file non cambia."""
    json_path = os.path.join(store_dir, "chunks.json")
    mtime = os.path.getmtime(json_path)
    key = (store_dir, mtime)
    if key not in _store_cache:
        with open(json_path, encoding="utf-8") as f:
            chunks = json.load(f)
        vectors = np.load(os.path.join(store_dir, "embeddings.npy"))
        # mantieni solo la versione più recente per store_dir
        for k in [k for k in _store_cache if k[0] == store_dir]:
            del _store_cache[k]
        _store_cache[key] = (chunks, vectors)
    return _store_cache[key]

def store_exists(store_dir):
    return os.path.exists(os.path.join(store_dir, "chunks.json"))

# ---------- retrieval --------------------------------------------------------

def retrieve(query, chunks, vectors, k=5):
    """Top-k chunk strutturati per similarita' coseno."""
    q = embed([query])[0]
    scores = vectors @ q
    eligible = [
        (i, float(scores[i]))
        for i in range(len(chunks))
        if chunks[i].get("type") in RETRIEVAL_TYPES
    ]
    eligible.sort(key=lambda x: -x[1])
    return [(chunks[i], s) for i, s in eligible[:k]]

def retrieve_text(query, chunks, vectors, k=5):
    """Top-k chunk testuali per similarita' coseno."""
    q = embed([query])[0]
    scores = vectors @ q
    eligible = [
        (i, float(scores[i]))
        for i in range(len(chunks))
        if chunks[i].get("type") == "text"
    ]
    eligible.sort(key=lambda x: -x[1])
    return [(chunks[i], s) for i, s in eligible[:k]]

# ---------- correzioni -------------------------------------------------------

CORRECTION_THRESHOLD = 0.82

def save_correction(query: str, correction: str):
    """Salva una correzione in store/corrections.json."""
    os.makedirs("store", exist_ok=True)
    corrections = load_corrections()
    corrections.append({
        "query":      query,
        "correction": correction,
        "timestamp":  datetime.now().isoformat(timespec="seconds"),
    })
    with open(CORRECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(corrections, f, ensure_ascii=False, indent=2)

def load_corrections():
    if not os.path.exists(CORRECTIONS_FILE):
        return []
    with open(CORRECTIONS_FILE, encoding="utf-8") as f:
        return json.load(f)

def find_relevant_corrections(query: str, corrections: list,
                               threshold=CORRECTION_THRESHOLD):
    if not corrections:
        return []
    q_vec     = embed([query])[0]
    past_vecs = embed([c["query"] for c in corrections])
    scores    = past_vecs @ q_vec
    return [corrections[i] for i, s in enumerate(scores) if float(s) >= threshold]

# ---------- generazione ------------------------------------------------------

SYSTEM_STRUCTURED = (
    "Sei un assistente tecnico specializzato nell'analisi di dati strutturati "
    "(grafici, tabelle, formule matematiche). "
    "Rispondi SOLO usando il CONTESTO fornito (GRAPH, TABLE, FORMULA). "
    "Se l'informazione non e' presente nel contesto, dillo chiaramente senza inventare. "
    "Cita sempre la fonte nel formato (doc, p.N). "
    "Per i dati numerici riporta il valore esatto dal contesto. "
    "Se nel contesto trovi una FORMULA e la domanda richiede un calcolo, "
    "esegui il calcolo sostituendo i valori forniti nelle variabili e mostra i passaggi."
)

SYSTEM_COMBINED = (
    "Sei un assistente tecnico specializzato in documenti tecnici. "
    "Il contesto include sia ELEMENTI STRUTTURATI (GRAPH, TABLE, FORMULA) "
    "sia TESTO estratto dal documento. "
    "Dai priorita' agli elementi strutturati per dati numerici e formule. "
    "Usa il testo per contesto e spiegazioni qualitative. "
    "Se l'informazione non e' presente nel contesto, dillo chiaramente senza inventare. "
    "Cita sempre la fonte nel formato (doc, p.N). "
    "Se nel contesto trovi una FORMULA e la domanda richiede un calcolo, "
    "esegui il calcolo sostituendo i valori forniti nelle variabili e mostra i passaggi."
)

def answer(query, store_dir=STORE_DIR, text_store_dir=TEXT_STORE_DIR,
           k=15, mode="structured"):
    """
    mode = 'structured' : solo elementi strutturati
    mode = 'combined'   : strutturati + chunk testuali
    Ritorna (testo_risposta, structured_hits, corrections_applied, text_hits)
    """
    chunks, vectors = load_store(store_dir)
    hits = retrieve(query, chunks, vectors, k=k)

    parts = []

    # correzioni con priorita' assoluta
    corrections = load_corrections()
    relevant    = find_relevant_corrections(query, corrections)
    for corr in relevant:
        parts.append(
            f"[CORREZIONE VERIFICATA — query originale: '{corr['query']}']\n"
            f"{corr['correction']}\n"
            f"ISTRUZIONE: usa questo dato corretto in risposta a qualsiasi domanda simile."
        )

    # elementi strutturati
    for h, _ in hits:
        block = f"[{h['type'].upper()} | {h['source']} p.{h['page']}]\n{h['content']}"
        ctx = h.get("page_context", "").strip()
        if ctx:
            block += f"\n[Testo pagina]: {ctx[:400]}"
        parts.append(block)

    # testo (solo in modalita' combined)
    text_hits = []
    if mode == "combined" and store_exists(text_store_dir):
        t_chunks, t_vectors = load_store(text_store_dir)
        text_hits = retrieve_text(query, t_chunks, t_vectors, k=k)
        for h, _ in text_hits:
            parts.append(f"[TEXT | {h['source']} p.{h['page']}]\n{h['content']}")

    context = "\n\n---\n\n".join(parts)
    system  = SYSTEM_COMBINED if mode == "combined" else SYSTEM_STRUCTURED

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=GEN_MODEL,
        max_tokens=1500,
        system=system,
        messages=[{"role": "user",
                   "content": f"CONTESTO:\n{context}\n\nDOMANDA: {query}"}],
    )
    return msg.content[0].text, hits, relevant, text_hits
