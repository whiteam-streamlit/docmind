"""
app.py — interfaccia Streamlit per easyingest.

  streamlit run app.py

Tab 1 – Elementi indicizzati (dryrun):
         Gerarchia  Libro (cartella) → Capitolo (file PDF) → Elementi strutturati
         Nessuna chiamata API: legge solo store/chunks.json.
Tab 2 – Domande: Q&A con debug dei chunk recuperati.
"""
import os, json, re, tempfile
from collections import defaultdict, OrderedDict
from dotenv import load_dotenv
import streamlit as st
# ingest importato in modo lazy (dentro il bottone) per non rallentare il caricamento
import rag
from rag import STORE_DIR, TEXT_STORE_DIR

load_dotenv()
st.set_page_config(page_title="Ingest — RAG tecnico", layout="wide")
st.title("Ingest — RAG su grafici, tabelle e formule")

if not os.getenv("ANTHROPIC_API_KEY"):
    st.error("Manca ANTHROPIC_API_KEY (mettila in un file .env).")
    st.stop()

# --- precarica il modello embedding una volta sola (mostra spinner) ----------
@st.cache_resource(show_spinner="Caricamento modello embedding…")
def _load_embedder():
    rag.embedder()
    return True

_load_embedder()

# --- Funzioni cache a livello modulo (NON dentro with-block) -----------------
@st.cache_data(show_spinner=False)
def _store_counts(store_dir):
    p = os.path.join(store_dir, "chunks.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    counts = {}
    for c in data:
        counts[c["type"]] = counts.get(c["type"], 0) + 1
    return counts


# --- Sidebar: ingestion -------------------------------------------------------
with st.sidebar:
    st.header("Ingestion")
    pdf = st.file_uploader("Carica un PDF tecnico", type="pdf")
    if pdf and st.button("Indicizza"):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf.read())
            path = f.name
        with st.spinner("Analisi pagine con visione (può richiedere un po')..."):
            import ingest as _ingest
            _ingest.ingest(path)
        _store_counts.clear()   # invalida cache conteggi
        _load_chunks.clear()    # invalida cache dryrun
        st.success("Indicizzazione completata.")
        st.rerun()

    sc = _store_counts(STORE_DIR)
    if sc:
        st.caption("Strutturati:")
        for t, n in sorted(sc.items()):
            st.caption(f"  {t}: {n}")

    tc = _store_counts(TEXT_STORE_DIR)
    if tc:
        st.caption("Testo:")
        for t, n in sorted(tc.items()):
            st.caption(f"  {t}: {n}")


# ============================================================
#  Utilità condivise
# ============================================================

TYPE_BADGE = {
    "table":       "📋 TABLE",
    "figure":      "📈 GRAPH",
    "figure_data": "📊 DATA",
    "formula":     "∑ FORMULA",
}
DISPLAY_TYPES = {"table", "figure", "formula"}


@st.cache_data(show_spinner=False)
def _load_chunks(store_dir):
    p = os.path.join(store_dir, "chunks.json")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def fmt_source(source: str) -> str:
    """'01 - Titolo capitolo.pdf' → '01 · Titolo capitolo'"""
    name = re.sub(r'\.pdf$', '', source, flags=re.I)
    m = re.match(r'^(\d+)\s*-\s*(.+)', name)
    return f"{m.group(1)} · {m.group(2).strip()}" if m else name


def render_chunk_preview(c: dict):
    typ      = c.get("type")
    content  = c.get("content", "")
    img_path = c.get("page_image")

    # --- pagina originale in expander collassato ---
    if img_path and os.path.exists(img_path):
        with st.expander("🖼 Pagina originale", expanded=False):
            st.image(img_path,
                     caption=f"p.{c.get('page','')} — {c.get('source','')}",
                     width="stretch")
        st.divider()

    # --- dati estratti ---
    if typ == "table":
        md_match = re.search(r"\|.+", content, re.DOTALL)
        if md_match:
            pre = content[:md_match.start()].strip()
            if pre:
                st.caption(pre)
            st.markdown(md_match.group(0))
        else:
            st.text(content)

    elif typ == "figure":
        data_match = re.search(r"Dati: (\{.+\})", content, re.DOTALL)
        pre = content[:data_match.start()].strip() if data_match else content
        st.caption(pre)
        if data_match:
            try:
                dp = json.loads(data_match.group(1))
                for series, pts in dp.items():
                    if pts:
                        st.markdown(
                            f"**{series}**: " +
                            ", ".join(f"({p[0]}, {p[1]})" for p in pts)
                        )
            except Exception:
                st.text(data_match.group(1))

    elif typ == "formula":
        latex = c.get("latex", "")
        if latex:
            try:
                st.latex(latex)
            except Exception:
                st.code(latex, language=None)
        var_match = re.search(r"Variabili: (.+)", content)
        if var_match and var_match.group(1).strip():
            st.caption("Variabili: " + var_match.group(1))

    else:
        st.text(content[:400])


# --- Tabs --------------------------------------------------------------------
tab_dry, tab_qa, tab_help = st.tabs(["🗂 Elementi indicizzati", "💬 Domande", "📖 Guida"])


# ===== TAB 1: dryrun  ========================================================
with tab_dry:
    chunks = _load_chunks(STORE_DIR)
    if not chunks:
        st.info("Nessuno store trovato. Indicizza un PDF dalla barra laterale.")
    else:

        # gerarchia: libro (cartella) → capitolo (PDF) → chunk
        tree: dict[str, dict[str, list]] = {}
        for c in chunks:
            if c.get("type") not in DISPLAY_TYPES:
                continue
            src  = c.get("source", "—")
            book = c.get("book") or src
            tree.setdefault(book, {}).setdefault(src, []).append(c)

        tree = OrderedDict(sorted(tree.items(), key=lambda kv: kv[0].lower()))
        for book in tree:
            tree[book] = OrderedDict(sorted(tree[book].items(), key=lambda kv: kv[0].lower()))

        total_el = sum(len(v) for bk in tree.values() for v in bk.values())
        st.caption(f"{total_el} elementi strutturati · {len(tree)} libro/i")
        st.divider()

        for book, chapters in tree.items():
            n_el = sum(len(v) for v in chapters.values())
            with st.expander(
                f"📚 **{book}**  —  {n_el} elementi · {len(chapters)} capitoli",
                expanded=False,
            ):
                for src, src_chunks in chapters.items():
                    with st.expander(
                        f"📖 {fmt_source(src)}  —  {len(src_chunks)} elementi",
                        expanded=False,
                    ):
                        for c in src_chunks:
                            badge = TYPE_BADGE.get(c["type"], c["type"].upper())
                            desc  = (c.get("description") or c.get("content", ""))[:80]
                            with st.container(border=True):
                                st.markdown(
                                    f"**p.{c['page']}** &nbsp; {badge} &nbsp;—&nbsp; {desc}",
                                    unsafe_allow_html=True,
                                )
                                render_chunk_preview(c)


# ===== TAB 2: Q&A ============================================================
with tab_qa:
    st.header("Domande")

    _qa_json       = os.path.join(STORE_DIR, "chunks.json")
    _text_json     = os.path.join(TEXT_STORE_DIR, "chunks.json")
    text_available = os.path.exists(_text_json)

    mode_label = st.radio(
        "Modalità ricerca",
        options=["Solo strutturati", "Strutturati + testo"],
        horizontal=True,
        disabled=not text_available,
        help="" if text_available else "Disponibile dopo re-indicizzazione.",
    )
    mode = "combined" if mode_label == "Strutturati + testo" else "structured"

    if not os.path.exists(_qa_json):
        st.warning("Prima indicizza un PDF dalla barra laterale.")
    else:
        q = st.text_input("Fai una domanda sul documento")
        if q:
            text, hits, applied_corrections, text_hits = rag.answer(q, k=15, mode=mode)

            st.markdown("### Risposta")
            if applied_corrections:
                st.info(f"ℹ️ Risposta basata su {len(applied_corrections)} correzione/i verificata/e.")
            st.write(text)

            # --- widget correzione ---
            with st.expander("✏️ Risposta non corretta? Inserisci la versione giusta"):
                correction_text = st.text_area(
                    "Correzione:",
                    placeholder="Es: La durata di conservazione del manzo a 0°C è circa 35 giorni, non 20.",
                    key=f"corr_input_{q}",
                )
                if st.button("Salva correzione", key=f"corr_save_{q}"):
                    if correction_text.strip():
                        rag.save_correction(q, correction_text.strip())
                        st.success("Correzione salvata. Sarà usata nelle risposte future.")
                    else:
                        st.warning("Inserisci il testo della correzione prima di salvare.")

            # --- debug fonti ---
            st.markdown("### Fonti recuperate (debug)")
            if hits:
                st.caption("Elementi strutturati")
                for h, score in hits:
                    with st.expander(f"[{h['type']}] {h['source']} p.{h['page']} — score {score:.3f}"):
                        st.text(h["content"])
            if text_hits:
                st.caption("Testo")
                for h, score in text_hits:
                    with st.expander(f"[text] {h['source']} p.{h['page']} — score {score:.3f}"):
                        st.text(h["content"])


# ===== TAB 3: Guida ===========================================================
with tab_help:
    _guide_candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "user_guide.md"),
        os.path.join(os.getcwd(), "docs", "user_guide.md"),
        "docs/user_guide.md",
    ]
    _guide_path = next((p for p in _guide_candidates if os.path.exists(p)), None)
    if _guide_path:
        with open(_guide_path, encoding="utf-8") as _f:
            _md = _f.read()
        st.markdown(_md)
    else:
        st.warning("File docs/user_guide.md non trovato. Cercato in: " +
                   ", ".join(_guide_candidates))
