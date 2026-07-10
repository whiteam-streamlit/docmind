# RAG tecnico — demo (tabelle & grafici)

Mini-progetto per testare l'**ingestion multimodale** di documenti tecnici:
estrae e *interpreta* tabelle e grafici usando un LLM con visione, li indicizza
insieme al testo, e risponde alle domande citando le fonti.

## Idea in una riga
Un text-splitter normale spezza le tabelle e ignora i grafici.
Qui ogni pagina viene **renderizzata in immagine** e passata a Claude (visione),
che ne estrae tabelle (in Markdown) e figure con una **interpretazione**.
L'interpretazione difficile si fa **una volta sola in ingestion**, con tutto il
contesto della pagina a disposizione.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # e inserisci la tua ANTHROPIC_API_KEY
```
> Il primo avvio scarica il modello di embedding locale (~80 MB).

## Uso
Da riga di comando:
```bash
python ingest.py mio_documento.pdf      # crea ./store/
python -c "import rag; print(rag.answer('qual e il valore massimo di X?')[0])"
```
Oppure con interfaccia:
```bash
streamlit run app.py
```

## Come e' fatto
- **ingest.py** — pipeline: testo nativo + visione per tabelle/figure -> chunk -> embedding -> store
- **rag.py** — embedding locali, store su disco, retrieval coseno, risposta con Claude
- **app.py** — UI di test; mostra i chunk recuperati (tipo + score) per debug

## Come si debugga
Nell'app ogni risposta mostra i chunk recuperati. Guarda lo **score** e il **tipo**:
- il chunk giusto NON c'e' tra i risultati -> problema di **retrieval** (chunking/ricerca)
- il chunk giusto c'e' ma la risposta e' sbagliata -> problema di **generazione** (prompt)

## Limiti volutamente lasciati semplici (i prossimi passi reali)
- **Embedding locali** (`all-MiniLM`): per produzione passa a Voyage o OpenAI — basta
  cambiare la funzione `embed()` in `rag.py`.
- **Solo ricerca semantica**: aggiungi ricerca keyword/BM25 (hybrid) per sigle e codici.
- **Niente store strutturato (SQL)** per i numeri: per domande di calcolo
  ("massimo", "media", "confronto anni") l'approccio robusto e' estrarre le tabelle
  in SQLite e usare text-to-SQL. Qui i numeri li "legge" il modello -> ok per test,
  fragile su tabelle grandi.
- **Re-ranking** assente: con piu' documenti, recupera top-k alto e riordina con un cross-encoder.
- **Costo**: l'ingestion chiama il modello una volta per pagina. Su molti PDF, valuta
  di processare solo le pagine che contengono tabelle/figure.

## Glossario di dominio (il pezzo che fa la differenza sul settore)
Per documenti molto verticali, aggiungi al `SYSTEM` di `rag.py` (o a un chunk sempre
recuperato) un glossario di sigle/unita'/convenzioni del settore: e' cio' che permette
al modello di *interpretare* cio' che il documento da' per scontato.
