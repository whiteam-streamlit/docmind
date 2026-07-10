"""
ingest.py — ingestion MULTIMODALE di documenti tecnici.

Per ogni pagina del PDF:
  1) estrae il testo nativo -> chunk testuali (paragrafi/sezioni) -> store/text/
  2) rasterizza la pagina e la passa a Claude (visione) per estrarre:
       - GRAPH  : grafici -> punti dati per curva/serie + curve fitting
       - TABLE  : tabelle -> Markdown + interpretazione
       - FORMULA: equazioni matematiche -> LaTeX + variabili
     -> store/structured/

Store separati:
  store/structured/  chunk strutturati (visione)
  store/text/        chunk testuali (paragrafi/sezioni, nessuna API)
  store/images/      PNG pagine per anteprima
  store/corrections.json  correzioni manuali (non toccato dall'ingestion)

Uso:
  python ingest.py documento.pdf
  python ingest.py file1.pdf file2.pdf
  python ingest.py ./cartella/
  python ingest.py ./cartella/*.pdf
  python ingest.py --workers 8 documento.pdf   # parallelismo esplicito
"""
import sys, os, json, base64, re, math, threading
import fitz  # PyMuPDF
import anthropic
import numpy as np
from scipy.optimize import curve_fit
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
load_dotenv()
from rag import embed, save_store, GEN_MODEL, STORE_DIR, TEXT_STORE_DIR

DPI = 250          # risoluzione alta per leggibilita' di assi e valori
MAX_WORKERS = 5    # chiamate API vision in parallelo (default)

VISION_PROMPT = """Analizza questa pagina di un documento tecnico.
Restituisci SOLO un oggetto JSON valido (niente testo prima o dopo, niente ```):

{
  "page_summary": "1-2 frasi su cosa tratta la pagina",
  "tables": [
    {
      "description": "1 riga: cosa rappresenta la tabella, variabili e unita'",
      "markdown": "tabella in Markdown",
      "interpretation": "valori notevoli, anomalie, relazioni tra le colonne",
      "bbox": [5, 30, 95, 70]
    }
  ],
  "figures": [
    {
      "description": "1 riga: tipo di grafico e grandezze sugli assi",
      "caption": "didascalia/titolo del grafico, se presente",
      "interpretation": "assi, unita', andamento generale",
      "data_points": {},
      "bbox": [5, 10, 95, 60]
    }
  ],
  "formulas": [
    {
      "description": "1 riga: cosa calcola questa formula",
      "latex": "formula in notazione LaTeX",
      "variables": {"simbolo": "nome e unita' di misura"},
      "bbox": [10, 45, 90, 55]
    }
  ]
}

Regole per bbox:
- Coordinate percentuali (0-100) della posizione dell'elemento nella pagina.
- Formato: [x_sinistra, y_alto, x_destra, y_basso], angolo in alto-sinistra = [0,0].
- Esempio: un grafico che occupa la meta' destra della pagina = [50, 10, 98, 90].
- Includi sempre il titolo/didascalia nell'area del bbox.

Regole per data_points (grafici):
- SEMPRE oggetto JSON {}, mai stringa.
- Una chiave per ogni curva/serie/prodotto. Valore: lista di coppie [x, y] leggibili.
- Esempio: {"manzo": [[0,20],[-5,30]], "pollame": [[0,5],[-5,8]]}
- ATTENZIONE SCALA: se l'asse Y e' LOGARITMICO, leggi i valori sulla scala log
  (es. se il tick e' 10 e la curva e' a meta' strada verso 100, il valore e' ~30-35,
  non 55). Indica il tipo di scala nell'interpretation.
- Stima i valori se non perfettamente leggibili, ma sii conservativo (meglio un range
  che un punto singolo impreciso). Se illeggibili, usa {}.

Regole per formulas:
- Estrai TUTTE le formule matematiche presenti.
- latex: usa sintassi LaTeX standard (es. "COP = \\frac{Q_L}{W_{net}}")
- variables: dizionario {simbolo: "descrizione [unita']"}
- Se nessuna formula e' presente, usa lista vuota [].

IMPORTANTE — figures include SOLO grafici con dati quantitativi (curve, istogrammi,
diagrammi, nomogrammi). Fotografie di impianti, macchinari, luoghi o persone NON sono
figure: ignorale e non inserirle in figures. Se una pagina contiene solo fotografie,
figures deve essere [].

Priorita': grafici con dati, tabelle, formule. Se non ce ne sono, usa liste vuote."""


# --- lock per print thread-safe ---------------------------------------------
_lock = threading.Lock()

def _log(*args, **kwargs):
    with _lock:
        print(*args, **kwargs)


# --- utilita' ----------------------------------------------------------------

def page_to_png_b64(page):
    pix = page.get_pixmap(dpi=DPI)
    return base64.b64encode(pix.tobytes("png")).decode()


def parse_json(text):
    """Parsing robusto: gestisce fence, JSON malformato, campi mancanti."""
    _empty = {"page_summary": "", "tables": [], "figures": [], "formulas": []}
    text = text.strip()
    for prefix in ("```json", "```"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.rstrip("`").strip()

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return _empty
    raw = m.group(0)

    # tentativo 1: JSON standard
    try:
        result = json.loads(raw)
        result.setdefault("formulas", [])
        return result
    except json.JSONDecodeError:
        pass

    # tentativo 2: rimuovo data_points problematici
    try:
        cleaned = re.sub(
            r'"data_points"\s*:\s*\{[^}]*\}',
            '"data_points": {}',
            raw, flags=re.DOTALL
        )
        result = json.loads(cleaned)
        result.setdefault("formulas", [])
        return result
    except json.JSONDecodeError:
        pass

    # tentativo 3: rimuovo bbox non numerici (es. [x0_pct, y0_pct, ...])
    try:
        cleaned = re.sub(r'"bbox"\s*:\s*\[[^\]]*\]', '"bbox": null', raw)
        cleaned = re.sub(
            r'"data_points"\s*:\s*\{[^}]*\}',
            '"data_points": {}',
            cleaned, flags=re.DOTALL
        )
        result = json.loads(cleaned)
        result.setdefault("formulas", [])
        return result
    except json.JSONDecodeError:
        pass

    _log("  [WARN] JSON non parsabile, uso fallback.")
    return _empty


def analyze_page(client, png_b64):
    msg = client.messages.create(
        model=GEN_MODEL,
        max_tokens=3000,
        messages=[{"role": "user", "content": [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/png", "data": png_b64}},
            {"type": "text", "text": VISION_PROMPT},
        ]}],
    )
    return parse_json(msg.content[0].text)


def fit_curve(xy_points):
    """Fitta i punti con y = a * exp(b * x).
    Ritorna dict con formula, parametri, R² oppure None se fallisce."""
    if len(xy_points) < 3:
        return None
    try:
        xs = np.array([p[0] for p in xy_points], dtype=float)
        ys = np.array([p[1] for p in xy_points], dtype=float)
        if np.any(ys <= 0):
            return None

        def exp_func(x, a, b):
            return a * np.exp(b * x)

        popt, _ = curve_fit(exp_func, xs, ys, p0=[float(ys[0]), -0.05], maxfev=10000)
        a, b = float(popt[0]), float(popt[1])

        y_pred = exp_func(xs, a, b)
        ss_res = np.sum((ys - y_pred) ** 2)
        ss_tot = np.sum((ys - np.mean(ys)) ** 2)
        r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        return {
            "model": "y = a * exp(b * x)",
            "a": round(a, 4),
            "b": round(b, 4),
            "r2": round(r2, 4),
            "formula_str": f"y = {a:.3g} * exp({b:.4f} * x)  [R²={r2:.3f}]",
        }
    except Exception:
        return None


# --- chunking testuale -------------------------------------------------------

def split_text_chunks(page_text: str, source: str, book: str, page: int) -> list:
    """Divide il testo nativo di una pagina in chunk per paragrafo/sezione.
    Rileva heading (riga corta, eventualmente numerata) e li fonde col paragrafo
    seguente. Restituisce lista di dict con type='text'."""
    if not page_text or len(page_text.strip()) < 30:
        return []

    MIN_LEN = 60   # scarta frammenti troppo corti

    def is_heading(line: str) -> bool:
        line = line.strip()
        if not line or len(line) > 100:
            return False
        # "1.", "1.1", "1.2.3 Titolo", "Capitolo 3", "TITOLO IN MAIUSCOLO"
        if re.match(r'^\d+(\.\d+)*\.?\s+\S', line):
            return True
        if re.match(r'^(capitolo|cap\.?|appendice|sezione)\s*\d', line, re.I):
            return True
        if line.isupper() and len(line) >= 4 and not re.search(r'\d{5,}', line):
            return True
        return False

    # split per blocchi separati da riga vuota
    raw_blocks = re.split(r'\n{2,}', page_text.strip())

    chunks   = []
    pending  = ""   # heading in attesa del prossimo blocco

    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split('\n')
        # blocco di una sola riga corta → possibile heading
        if len(lines) == 1 and is_heading(lines[0]):
            if pending:
                # heading precedente senza corpo: emetti da solo se abbastanza lungo
                if len(pending) >= MIN_LEN:
                    chunks.append(_text_chunk(pending, source, book, page))
            pending = lines[0].strip()
            continue

        # blocco normale: prepend heading pendente se esiste
        content = (pending + "\n" + block).strip() if pending else block
        pending = ""
        if len(content) >= MIN_LEN:
            chunks.append(_text_chunk(content, source, book, page))

    # heading rimasto senza corpo
    if pending and len(pending) >= MIN_LEN:
        chunks.append(_text_chunk(pending, source, book, page))

    return chunks


def _text_chunk(content: str, source: str, book: str, page: int) -> dict:
    first_line = content.split('\n')[0].strip()
    return {
        "type":        "text",
        "source":      source,
        "book":        book,
        "page":        page,
        "content":     content,
        "description": first_line[:100],
    }


# --- elaborazione singola pagina (eseguita nei thread) ----------------------

def _process_page(client, png_b64, page_context, page_num, total_pages, source, book, img_path):
    """Analizza una pagina; ritorna (page_num, chunks, log_lines).
    Funzione thread-safe: non stampa direttamente."""
    logs = [f"  pagina {page_num}/{total_pages} ..."]
    vis = analyze_page(client, png_b64)
    chunks = []
    found_any = False

    def _valid_bbox(b):
        """Valida bbox [x0,y0,x1,y1] in percentuale 0-100."""
        try:
            if not isinstance(b, (list, tuple)) or len(b) != 4:
                return None
            b = [float(v) for v in b]
            if b[0] < b[2] and b[1] < b[3] and all(0 <= v <= 100 for v in b):
                return b
        except Exception:
            pass
        return None

    # TABELLE
    for t in vis.get("tables", []):
        desc = t.get("description", "")
        content = (
            f"TABLE — {desc}\n"
            f"{t.get('interpretation', '')}\n\n"
            f"{t.get('markdown', '')}"
        )
        chunks.append({
            "type": "table", "source": source, "book": book, "page": page_num,
            "content": content, "page_context": page_context,
            "description": desc, "page_image": img_path,
            "element_bbox": _valid_bbox(t.get("bbox")),
        })
        found_any = True
        logs.append(f"    → TABLE: {desc[:80]}")

    # GRAFICI
    for fig in vis.get("figures", []):
        desc        = fig.get("description", "")
        caption     = fig.get("caption", "")
        interp      = fig.get("interpretation", "")
        data_points = fig.get("data_points", {})
        bbox        = _valid_bbox(fig.get("bbox"))

        content = f"GRAPH — {desc}\n{caption}\n{interp}"
        if data_points:
            content += f"\nDati: {json.dumps(data_points, ensure_ascii=False)}"
        chunks.append({
            "type": "figure", "source": source, "book": book, "page": page_num,
            "content": content, "page_context": page_context,
            "description": desc, "page_image": img_path,
            "element_bbox": bbox,
        })
        found_any = True
        logs.append(f"    → GRAPH: {desc[:80]}")

        if isinstance(data_points, dict):
            for entity, values in data_points.items():
                name = entity.rstrip("_0123456789")
                fit  = fit_curve(values)
                lines = [f"{name}", f"Valori campionati (x, y): {values}"]
                if fit:
                    lines.append(f"Fit curva: {fit['formula_str']}")
                    val0 = fit["a"] * math.exp(fit["b"] * 0)
                    lines.append(
                        f"  -> a 0 unita' di x: y ~= {val0:.1f}  "
                        f"(usa la formula per qualsiasi valore di x)"
                    )
                lines.append(f"Da: {caption or desc}")
                chunks.append({
                    "type": "figure_data", "source": source, "book": book, "page": page_num,
                    "content": "\n".join(lines),
                    "page_context": page_context,
                    "description": f"{name} — {desc}",
                    "fit": fit, "page_image": img_path,
                    "element_bbox": bbox,
                })

    # FORMULE
    for fm in vis.get("formulas", []):
        desc   = fm.get("description", "")
        latex  = fm.get("latex", "")
        varmap = fm.get("variables", {})
        var_str = "; ".join(f"{k} = {v}" for k, v in varmap.items()) if varmap else ""
        content = (
            f"FORMULA — {desc}\n"
            f"LaTeX: {latex}\n"
            f"Variabili: {var_str}"
        )
        chunks.append({
            "type": "formula", "source": source, "book": book, "page": page_num,
            "content": content, "page_context": page_context,
            "description": desc, "latex": latex, "page_image": img_path,
            "element_bbox": _valid_bbox(fm.get("bbox")),
        })
        found_any = True
        logs.append(f"    → FORMULA: {desc[:80]}")

    if not found_any:
        logs.append("    (nessun elemento strutturato trovato)")

    return page_num, chunks, logs


# --- testo da embeddare: description + content --------------------------------

def _embed_text(c: dict) -> str:
    """Testo usato per l'embedding: antepone la description al content
    in modo che termini come 'manzo', 'tabella COP', ecc. pesino di più."""
    desc    = (c.get("description") or "").strip()
    content = (c.get("content")     or "").strip()
    if desc and not content.startswith(desc):
        return f"{desc}\n{content}"
    return content


# --- funzione pubblica di ingestion -----------------------------------------

def ingest(pdf_path, max_workers=MAX_WORKERS):
    """Indicizza un singolo PDF con pagine processate in parallelo.
    max_workers = numero di chiamate API vision simultanee."""
    client = anthropic.Anthropic()
    doc    = fitz.open(pdf_path)
    source = os.path.basename(pdf_path)
    # book = nome della cartella che contiene il PDF (es. "Manuale refrigerazione")
    book   = os.path.basename(os.path.dirname(os.path.abspath(pdf_path)))
    total  = len(doc)

    # cartelle output
    img_dir  = os.path.join("store", "images")
    os.makedirs(img_dir, exist_ok=True)
    safe_src = re.sub(r'[^\w\-.]', '_', source)

    _log(f"  Rasterizzazione {total} pagine a {DPI} DPI...")
    pages_data = []
    for i, page in enumerate(doc):
        png_b64 = page_to_png_b64(page)
        # salva il PNG su disco per l'anteprima visiva
        img_path = os.path.join(img_dir, f"{safe_src}_p{i+1:04d}.png")
        with open(img_path, "wb") as fimg:
            fimg.write(base64.b64decode(png_b64))
        pages_data.append((i + 1, png_b64, page.get_text().strip(), img_path))

    _log(f"  Analisi visione ({min(max_workers, total)} thread paralleli)...")
    results = {}  # page_num -> list[chunk]

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(_process_page, client, png_b64, ctx, pnum, total, source, book, img_path): pnum
            for pnum, png_b64, ctx, img_path in pages_data
        }
        for future in as_completed(futures):
            pnum, chunks, logs = future.result()
            results[pnum] = chunks
            for line in logs:
                _log(line, flush=True)

    # ricostruisce in ordine di pagina
    all_chunks = []
    for pnum in sorted(results):
        all_chunks.extend(results[pnum])

    _log(f"\nElementi strutturati: {len(all_chunks)}")
    for typ in ("table", "figure", "figure_data", "formula"):
        n = sum(1 for c in all_chunks if c["type"] == typ)
        if n:
            _log(f"  {typ:12}: {n}")

    # --- store strutturati ---
    _log("Calcolo embedding strutturati...")
    vectors = embed([_embed_text(c) for c in all_chunks])
    save_store(all_chunks, vectors, store_dir=STORE_DIR)
    _log(f"Store strutturati salvato in {STORE_DIR}/")

    # --- chunk testuali (da page_context, nessuna API) ---
    _log("Chunking testo nativo...")
    text_chunks = []
    for pnum, _png, ctx, _img in pages_data:
        text_chunks.extend(split_text_chunks(ctx, source, book, pnum))
    _log(f"Chunk testuali: {len(text_chunks)}")
    if text_chunks:
        _log("Calcolo embedding testo...")
        t_vectors = embed([_embed_text(c) for c in text_chunks])
        save_store(text_chunks, t_vectors, store_dir=TEXT_STORE_DIR)
        _log(f"Store testo salvato in {TEXT_STORE_DIR}/")

    return all_chunks


# --- collect PDF paths -------------------------------------------------------

def collect_pdfs(paths):
    """Espande cartelle e glob in una lista ordinata di file PDF."""
    import glob as _glob
    pdfs = []
    for p in paths:
        p = p.strip("'\"")
        if os.path.isdir(p):
            found = sorted(_glob.glob(os.path.join(p, "**", "*.pdf"), recursive=True))
            pdfs.extend(found)
        elif "*" in p or "?" in p:
            pdfs.extend(sorted(_glob.glob(p, recursive=True)))
        elif p.lower().endswith(".pdf") and os.path.isfile(p):
            pdfs.append(p)
        else:
            print(f"  [SKIP] non trovato o non PDF: {p}")
    return pdfs


# --- entry point -------------------------------------------------------------

if __name__ == "__main__":
    # opzione --workers N
    workers = MAX_WORKERS
    args = sys.argv[1:]
    if "--workers" in args:
        idx = args.index("--workers")
        workers = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    if not args:
        print("Uso:")
        print("  python ingest.py documento.pdf")
        print("  python ingest.py file1.pdf file2.pdf file3.pdf")
        print("  python ingest.py ./cartella/")
        print("  python ingest.py ./cartella/*.pdf")
        print("  python ingest.py --workers 8 documento.pdf")
        sys.exit(1)

    pdfs = collect_pdfs(args)
    if not pdfs:
        print("Nessun PDF trovato.")
        sys.exit(1)

    print(f"PDF da indicizzare: {len(pdfs)}  |  workers: {workers}")
    for p in pdfs:
        print(f"  {p}")
    print()

    all_chunks = []
    for idx, pdf_path in enumerate(pdfs, 1):
        print(f"[{idx}/{len(pdfs)}] {pdf_path}")
        chunks = ingest(pdf_path, max_workers=workers)
        all_chunks.extend(chunks)

    if len(pdfs) > 1:
        print(f"\nTotale chunk strutturati (tutti i PDF): {len(all_chunks)}")
        for typ in ("table", "figure", "figure_data", "formula"):
            n = sum(1 for c in all_chunks if c["type"] == typ)
            if n:
                print(f"  {typ:12}: {n}")
        print("Ricalcolo embedding strutturati unificato...")
        vectors = embed([c["content"] for c in all_chunks])
        save_store(all_chunks, vectors, store_dir=STORE_DIR)
        print(f"Store strutturati unificato salvato in {STORE_DIR}/")
