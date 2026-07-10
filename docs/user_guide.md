# docmind — Guida utente

---

## Come si usa

### Fare una domanda

1. Apri il tab **Domande**.
2. Scegli la modalità di ricerca:
   - **Solo strutturati** — per dati numerici precisi (grafici, tabelle, formule)
   - **Strutturati + testo** — per domande qualitative o descrittive
3. Digita la domanda nel campo di testo e premi **Invio**.
4. La risposta include sempre la fonte (documento e pagina) e, se disponibile, il calcolo passo per passo.

> **Domande efficaci**
> Sii specifico: includi grandezza, unità e condizioni.
> - *"Quanto dura la conservazione del manzo a 0°C?"*
> - *"Qual è il COP tipoco del ciclo frigorifero a −20°C / +40°C?"*
> - *"Qual è la portata del compressore a −10°C di evaporazione?"*

> **Domande vaghe restituiscono risposte generiche.**
> Evita "dimmi tutto sul compressore" o "spiega la refrigerazione".

---

### Correggere una risposta sbagliata

Se la risposta è imprecisa o errata, puoi salvare la versione corretta.
Verrà applicata automaticamente alle domande future simili.

1. Sotto la risposta, apri il pannello **"✏️ Risposta non corretta? Inserisci la versione giusta"**.
2. Scrivi la correzione in modo preciso, indicando il valore corretto.
   Esempio: *"La conservazione del manzo a 0°C è 30 giorni, non 20."*
3. Clicca **Salva correzione**.

Le correzioni sono permanenti e sopravvivono alla re-indicizzazione dei documenti.
Usale solo per dati certi e verificati.

---

### Esplorare gli elementi estratti

Il tab **🗂 Elementi indicizzati** mostra tutto ciò che docmind ha estratto,
organizzato per libro e capitolo.

1. Clicca su **📚 Nome libro** per espanderlo.
2. Clicca su **📖 Nome capitolo** per vedere gli elementi.
3. Ogni elemento mostra tipo, pagina e descrizione.
4. Espandi **🖼 Pagina originale** per vedere la pagina del documento da cui è stato estratto.

Usa questo tab per verificare cosa sa docmind prima di fare domande.
Se un dato non compare tra gli elementi, docmind non potrà rispondere su quello.

---

### Tipi di elemento

| Tipo | Cosa contiene | Esempio |
|------|--------------|---------|
| 📈 **GRAPH** | Dati numerici da grafici e curve, con formula di regressione | Curva di conservazione alimenti vs temperatura |
| 📋 **TABLE** | Contenuto di tabelle | Temperature raccomandate di stoccaggio |
| ∑ **FORMULA** | Equazioni con variabili e unità | Formula del COP, equazione di Carnot |

---

### Interpretare la risposta

La risposta riporta sempre:
- **Il dato trovato** — valore numerico con unità di misura
- **La fonte** — nome del documento e numero di pagina
- **Il calcolo** — se hai chiesto di applicare una formula, i passaggi sono mostrati passo per passo

Sotto la risposta trovi la sezione **Fonti recuperate**: mostra quali parti del documento
sono state usate e il loro score di pertinenza (0–1).
Uno score vicino a **1.0** indica un match molto preciso;
uno score **< 0.55** indica che il sistema non ha trovato dati specifici
e la risposta potrebbe essere meno affidabile.

---

## FAQ

**La risposta dice "informazione non presente nel contesto". Perché?**

Significa che nei documenti indicizzati non è stato trovato nessun dato pertinente.
Possibili cause: il dato non è nei PDF caricati, oppure è espresso con termini diversi
dalla tua domanda. Prova a riformulare con termini più tecnici o sinonimi.

---

**La risposta cita un valore errato. Come lo correggo?**

Usa la funzione di correzione sotto la risposta (vedi sezione sopra).
Scrivi il valore corretto con precisione e salvalo.

---

**Posso chiedere di calcolare qualcosa con una formula?**

Sì. Se la formula è presente nei documenti, docmind la applica ai valori che fornisci.
Esempio: *"Calcola il COP con evaporazione −15°C e condensazione +35°C."*

---

**Qual è la differenza tra le due modalità di ricerca?**

*Solo strutturati* usa esclusivamente dati da grafici, tabelle e formule — più preciso
per domande numeriche. *Strutturati + testo* aggiunge anche i paragrafi testuali —
utile per domande qualitative ("come funziona…", "quali sono le cause di…").

---

**docmind usa Internet o fonti esterne?**

No. Risponde esclusivamente sulla base dei documenti indicizzati.
Se un'informazione non è nei PDF caricati, lo dichiarerà esplicitamente.

---

**Le correzioni si perdono se i documenti vengono re-indicizzati?**

No. Le correzioni sono salvate separatamente e rimangono attive indipendentemente
dalla re-indicizzazione.

---

**docmind può sbagliare?**

Sì. La lettura visiva delle pagine e l'interpretazione del linguaggio naturale
possono introdurre imprecisioni. Verifica sempre i valori critici sul documento
originale. In caso di errore, usa la funzione di correzione.
