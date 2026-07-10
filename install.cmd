pip install -r requirements.txt
cp .env.example .env        # metti la tua ANTHROPIC_API_KEY
python ingest.py tuo_documento.pdf
streamlit run app.py