"""Constants de domini del SAF. Cap número màgic fora d'aquí."""
from __future__ import annotations

import os
from datetime import date, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SAF_XLSX = Path(os.getenv("SAF_XLSX", str(BASE_DIR / "data" / "saf.xlsx")))

# ---------------------------------------------------------------- calendari
DATA_INICI = date(2026, 4, 1)
DATA_FI = date(2026, 10, 31)

DIES = ["dl", "dt", "dc", "dj", "dv", "ds", "dg"]
DIA_NOM = {
    "dl": "dilluns", "dt": "dimarts", "dc": "dimecres", "dj": "dijous",
    "dv": "divendres", "ds": "dissabte", "dg": "diumenge",
}
DIA_INDEX = {d: i for i, d in enumerate(DIES)}
NOM_DIA = {v: k for k, v in DIA_NOM.items()}

MES_NOM = {4: "abril", 5: "maig", 6: "juny", 7: "juliol",
           8: "agost", 9: "setembre", 10: "octubre"}
NOM_MES = {v: k for k, v in MES_NOM.items()}

# ---------------------------------------------------------------- horaris
HORARI: dict[str, tuple[time, time]] = {
    "dl": (time(7, 0), time(21, 0)),
    "dt": (time(7, 0), time(21, 0)),
    "dc": (time(7, 0), time(21, 0)),
    "dj": (time(7, 0), time(21, 0)),
    "dv": (time(7, 0), time(21, 0)),
    "ds": (time(8, 0), time(20, 0)),
    "dg": (time(9, 0), time(14, 0)),
}

# ------------------------------------------------- trampa 1: torns de fitness
FRANGES_FITNESS = ["07:00", "08:00", "09:00", "11:00", "12:00", "13:00",
                   "14:00", "16:00", "17:00", "18:00", "19:00"]
FORATS_FITNESS = {"10:00", "15:00"}          # canvi de torn: NO és baixa demanda
DURADA_TORN_FITNESS = 75
PREFIX_FITNESS = "FITNESS"

# ------------------------------------------- trampa 3: blocs de club/escola
LLINDAR_BLOC_MINUTS = 240

# ------------------------------------------ trampa 5: llindars d'ocupació
LLINDAR_BAIXA = 25.0
LLINDAR_ALTA = 70.0

# ---------------------------------------------------------------- columnes
COLS_RESERVES = [
    "Data d'ús de la reserva", "Dia de la setmana", "Mes (número)",
    "Hora d'inici", "Hora de finalització", "Durada (minuts)",
    "Codi de l'espai", "Nom de l'espai a l'inventari",
    "Recurs reservat (nom original)", "Es compta per persones o per pista",
    "Aforament màxim de l'espai",
    "Reserva d'una part de l'espai (mitja pista)",
    "Reserva per a una activitat dirigida",
    "Reserva de més de 4 hores (bloc de club o escola)",
    "Reserva fora de l'horari d'obertura",
]
COLS_ACTIVITATS = [
    "Nom de l'activitat", "Tipus d'activitat (regular o especial)",
    "Codi de l'activitat", "Sala on es fa", "Codi de l'espai",
    "Hora d'inici", "Hora de finalització", "Places de la classe",
    "Persones inscrites a la classe", "Percentatge d'ocupació de la classe",
    "Més inscrits que places", "Data d'inscripció (no és el dia de la classe)",
]
COLS_ESPAIS = [
    "Codi de l'espai", "Instal·lació", "Subespai (pista, carrer, sala...)",
    "Nom complet de l'espai", "Aforament màxim (persones)",
    "Es compta per persones o per pista",
]

# Àlies de domini → prefixos de codi (resolts contra l'inventari real)
ALIASOS: dict[str, list[str]] = {
    "fitness": ["FITNESS"], "sala fitness": ["FITNESS"],
    "musculacio": ["FITNESS"], "gimnas": ["FITNESS"], "gimnàs": ["FITNESS"],
    "piscina": ["PISCINA"], "vas": ["PISCINA"], "carrers": ["PISCINA"],
    "padel": ["PADEL"], "tennis": ["TENNIS"], "squash": ["SQUASH"],
    "poliesportiu": ["POLI"], "poli": ["POLI"],
    "sala": ["SALA"], "sales": ["SALA"],
}

# ---------------------------------------------------------------- LLM DCC
UTH_KEY = os.getenv("UTH_KEY", "")
UTH_BASE_URL = os.getenv("UTH_BASE_URL", "https://dcc-llm-gw.uab.cat/uabthehack/v1").rstrip("/")
UTH_MODEL = os.getenv("UTH_MODEL", "ornith")
