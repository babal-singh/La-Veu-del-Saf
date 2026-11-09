# Ask the SAF · UAB The Hack! 2026

A deterministic conversational assistant for the UAB **Servei d'Activitat Física (SAF)**.
It answers questions about opening hours, capacities, live occupancy, low-traffic time
slots and group activities, covering **2026-04-01 to 2026-10-31** with traceability to the source.

Demo: https://youtu.be/bL_MfDehktQ


## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1) Data: generate a synthetic saf.xlsx with the 7 tables (Spaces, Bookings, Activities, ...)
python scripts/make_sample_data.py

# 2) Export your team's UAB DCC key
export UTH_KEY=uth-...

# 3) Launch the interface
streamlit run app.py
```



**No data used by the chatbot is uploaded to this repository.** The repo contains only
source code: the workbook the assistant reads (`data/saf.xlsx`) and anything else under
`data/` is generated or supplied locally.
## Layout

```
app.py                      Streamlit interface
saf/router.py               Intent routing
saf/tools.py                Deterministic query functions over the tables
saf/data.py                 Workbook loading and normalisation
saf/llm.py                  Gateway client for natural-language phrasing
saf/motor.py                Answer assembly
saf/config.py               Settings and date range
scripts/make_sample_data.py Synthetic dataset generator
```
