# Pregunta-li al SAF · UAB The Hack! 2026

Assistent conversacional determinista per al **Servei d'Activitat Física (SAF)** de la UAB.
Cobreix horaris, aforaments, ocupació instantània, franges de baixa afluència i
activitats dirigides, del **2026-04-01 al 2026-10-31**.

## Arrencada ràpida

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1) Dades: genera un saf.xlsx sintètic amb les 7 taules (Espais, Reserves, Activitats…)
python scripts/make_sample_data.py

# 2) Exporta la clau del DCC UAB (la del vostre equip)
export UTH_KEY=uth-...

# 3) Engega la interfície
streamlit run app.py
