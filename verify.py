"""
verify.py — verifica rapida dello store e del retrieval RAG.

Uso:
  python verify.py              # overview store + test query default
  python verify.py "domanda"    # test con query custom
"""
import sys, os, json
import rag

# ── 1. overview store ──────────────────────────────────────────────────────────

def overview(store_dir, label):
    p = os.path.join(store_dir, "chunks.json")
    if not os.path.exists(p):
        print(f"[{label}] store NON trovato ({store_dir})")
        return []
    chunks = json.load(open(p, encoding="utf-8"))
    counts = {}
    for c in chunks:
        counts[c["type"]] = counts.get(c["type"], 0) + 1
    print(f"[{label}] {len(chunks)} chunk totali  ({store_dir})")
    for t, n in sorted(counts.items()):
        print(f"  {t:15}: {n}")
    return chunks


print("=" * 60)
print("STORE OVERVIEW")
print("=" * 60)
s_chunks = overview(rag.STORE_DIR,      "strutturati")
t_chunks = overview(rag.TEXT_STORE_DIR, "testo      ")
print()

# ── 2. ricerca per keyword ─────────────────────────────────────────────────────

KEYWORDS = ["manzo", "conserv", "aliment", "carne", "beef", "storage", "giorni", "shelf"]

def keyword_search(chunks, label):
    found = [
        c for c in chunks
        if any(k in c.get("content", "").lower() for k in KEYWORDS)
    ]
    print(f"[{label}] chunk con keyword alimentari: {len(found)}")
    for c in found[:5]:
        print(f"  [{c['type']}] {c['source']} p.{c['page']}")
        print(f"    {c['content'][:120].replace(chr(10), ' ')}")
    if not found:
        print("  ATTENZIONE: nessun chunk trovato — potrebbe servire re-indicizzazione")
    print()

print("=" * 60)
print("KEYWORD SEARCH (alimenti / conservazione)")
print("=" * 60)
keyword_search(s_chunks, "strutturati")
keyword_search(t_chunks, "testo      ")

# ── 3. retrieval coseno ────────────────────────────────────────────────────────

QUERY = sys.argv[1] if len(sys.argv) > 1 else "tempo di conservazione manzo a 0 gradi"

print("=" * 60)
print(f"RETRIEVAL  query: '{QUERY}'")
print("=" * 60)

if s_chunks:
    _, s_vecs = rag.load_store(rag.STORE_DIR)
    hits = rag.retrieve(QUERY, s_chunks, s_vecs, k=10)
    print(f"Top-{len(hits)} chunk strutturati:")
    for h, score in hits:
        print(f"  score={score:.3f}  [{h['type']}]  {h['source']} p.{h['page']}")
        print(f"    {h['content'][:100].replace(chr(10), ' ')}")
    print()
    # mostra anche score del chunk manzo specifico
    import numpy as np
    q_vec = rag.embed([QUERY])[0]
    manzo_chunks = [c for c in s_chunks if "manzo" in c.get("content","").lower()
                    and c.get("type") == "figure_data"]
    if manzo_chunks:
        print(f"Score chunk 'manzo' (figure_data):")
        for c in manzo_chunks:
            idx = s_chunks.index(c)
            score = float(s_vecs[idx] @ q_vec)
            print(f"  score={score:.3f}  p.{c['page']}  {c['content'][:80].replace(chr(10),' ')}")
        print()
else:
    print("  store strutturati vuoto, skip retrieval\n")

# ── 4. risposta RAG ────────────────────────────────────────────────────────────

print("=" * 60)
print("RISPOSTA RAG")
print("=" * 60)
try:
    text, hits, corrections, text_hits = rag.answer(QUERY)
    print(text)
    if corrections:
        print(f"\n[{len(corrections)} correzione/i applicata/e]")
except Exception as e:
    print(f"ERRORE: {e}")
