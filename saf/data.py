"""Càrrega, neteja i indexació del dataset SAF. Cap càlcul de negoci aquí."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from . import config as C
from .utils import normalitza, hora_en_minuts

# --- noms canònics de columnes ---------------------------------------------
R = dict(
    data="Data d'ús de la reserva", dia="Dia de la setmana", mes="Mes (número)",
    inici="Hora d'inici", fi="Hora de finalització", dur="Durada (minuts)",
    codi="Codi de l'espai", nom="Nom de l'espai a l'inventari",
    recurs="Recurs reservat (nom original)",
    metrica="Es compta per persones o per pista",
    aforament="Aforament màxim de l'espai",
    mitja="Reserva d'una part de l'espai (mitja pista)",
    dirigida="Reserva per a una activitat dirigida",
    bloc="Reserva de més de 4 hores (bloc de club o escola)",
    fora="Reserva fora de l'horari d'obertura",
)
A = dict(
    nom="Nom de l'activitat", tipus="Tipus d'activitat (regular o especial)",
    codi="Codi de l'activitat", sala="Sala on es fa", codi_espai="Codi de l'espai",
    inici="Hora d'inici", fi="Hora de finalització", places="Places de la classe",
    inscrites="Persones inscrites a la classe",
    pct="Percentatge d'ocupació de la classe", over="Més inscrits que places",
    inscripcio="Data d'inscripció (no és el dia de la classe)",
)
E = dict(
    codi="Codi de l'espai", inst="Instal·lació", sub="Subespai (pista, carrer, sala...)",
    nom="Nom complet de l'espai", aforament="Aforament màxim (persones)",
    metrica="Es compta per persones o per pista",
)


# --------------------------------------------------------------- helpers io
def _align(df: pd.DataFrame, canon: list[str]) -> pd.DataFrame:
    """Alinea columnes reals (amb accents/variants) als noms canònics."""
    mapa = {normalitza(c): c for c in canon}
    ren = {}
    for col in df.columns:
        k = normalitza(col)
        if k in mapa:
            ren[col] = mapa[k]
    df = df.rename(columns=ren)
    for c in canon:
        if c not in df.columns:
            df[c] = np.nan
    return df[canon]


def _troba_full(xl: pd.ExcelFile, candidats: Iterable[str]) -> str | None:
    norm = {normalitza(s): s for s in xl.sheet_names}
    for c in candidats:
        if normalitza(c) in norm:
            return norm[normalitza(c)]
    for s in xl.sheet_names:
        ns = normalitza(s)
        if any(normalitza(c) in ns for c in candidats):
            return s
    return None


def _a_minuts(serie: pd.Series) -> pd.Series:
    """Hora → minuts des de mitjanit. Accepta str, time, Timestamp."""
    if pd.api.types.is_datetime64_any_dtype(serie):
        return (serie.dt.hour * 60 + serie.dt.minute).astype(float)

    def _one(v):
        if isinstance(v, time):
            return v.hour * 60 + v.minute
        if hasattr(v, "hour") and hasattr(v, "minute"):
            return v.hour * 60 + v.minute
        if isinstance(v, str):
            return hora_en_minuts(v)
        return hora_en_minuts(v) if not pd.isna(v) else np.nan

    return serie.map(_one).astype(float)


def _si(serie: pd.Series) -> pd.Series:
    return serie.astype(str).str.strip().str.lower().str.startswith(("s", "y", "1"))


# ------------------------------------------------------------------ contenidor
@dataclass
class SafData:
    reserves: pd.DataFrame
    activitats: pd.DataFrame
    espais: pd.DataFrame
    recursos: pd.DataFrame
    franges: pd.DataFrame
    horari: pd.DataFrame
    fonts: pd.DataFrame
    index_espais: dict[str, set[str]]

    # -------------------------------------------------- resolució d'espais
    def resoldre(self, text: str) -> tuple[list[str], str]:
        """Text lliure → (llista de codis, estat). estat ∈ ok|multiple|unknown."""
        t = normalitza(text)
        if not t:
            return [], "unknown"
        codis_tots = set(self.espais[E["codi"]].astype(str))

        if t in self.index_espais:
            c = self.index_espais[t]
            return sorted(c), ("ok" if len(c) == 1 else "multiple")

        hits = [(a, c) for a, c in self.index_espais.items() if len(a) >= 4 and a in t]
        if hits:
            hits.sort(key=lambda kv: -len(kv[0]))
            millor = hits[0][0]
            codis = set()
            for a, c in hits:
                if a in millor or millor in a:
                    codis |= c
            return sorted(codis), ("ok" if len(codis) == 1 else "multiple")

        import difflib
        prop = difflib.get_close_matches(t, list(self.index_espais), n=2, cutoff=0.84)
        if prop:
            codis = set().union(*(self.index_espais[p] for p in prop))
            return sorted(codis), ("ok" if len(codis) == 1 else "multiple")

        for codi in codis_tots:
            if normalitza(codi) == t:
                return [codi], "ok"
        return [], "unknown"

    def info_espai(self, codi: str) -> pd.Series | None:
        m = self.espais[self.espais[E["codi"]].astype(str) == str(codi)]
        return None if m.empty else m.iloc[0]

    def es_fitness(self, codis: Iterable[str]) -> bool:
        return any(str(c).upper().startswith(C.PREFIX_FITNESS) for c in codis)

    def aforament_total(self, codis: Iterable[str]) -> float:
        m = self.espais[self.espais[E["codi"]].astype(str).isin(list(codis))]
        return float(pd.to_numeric(m[E["aforament"]], errors="coerce").fillna(0).sum())

    def metrica(self, codis: Iterable[str]) -> str:
        m = self.espais[self.espais[E["codi"]].astype(str).isin(list(codis))]
        vals = set(m[E["metrica"]].astype(str).str.lower().str.strip())
        return "persones" if any("person" in v for v in vals) else "pista"


# --------------------------------------------------------------------- càrrega
def _build_index(espais: pd.DataFrame) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = {}
    for _, row in espais.iterrows():
        codi = str(row[E["codi"]])
        cand = [codi, row[E["nom"]], row[E["sub"]],
                f'{row[E["inst"]]} {row[E["sub"]]}']
        for c in cand:
            if isinstance(c, str):
                k = normalitza(c)
                if len(k) >= 3:
                    idx.setdefault(k, set()).add(codi)

    codis_tots = list(espais[E["codi"]].astype(str))
    for alias, prefixos in C.ALIASOS.items():
        trobats = {c for c in codis_tots
                   if any(c.upper().startswith(p.upper()) for p in prefixos)}
        if trobats:
            idx.setdefault(normalitza(alias), set()).update(trobats)
    return idx


def carrega(ruta: Path | str | None = None) -> SafData:
    ruta = Path(ruta or C.SAF_XLSX)
    if not ruta.exists():
        raise FileNotFoundError(
            f"No trobo {ruta}. Executa `python scripts/make_sample_data.py` "
            f"o defineix SAF_XLSX=/ruta/al/saf.xlsx"
        )

    xl = pd.ExcelFile(ruta)

    def _llegeix(candidats, canon):
        s = _troba_full(xl, candidats)
        if s is None:
            return pd.DataFrame(columns=canon)
        return _align(pd.read_excel(xl, sheet_name=s), canon)

    espais = _llegeix(["Espais", "Espacios", "Espai"], C.COLS_ESPAIS)
    reserves = _llegeix(["Reserves", "Reservas", "Reserva"], C.COLS_RESERVES)
    activitats = _llegeix(["Activitats dirigides", "Activitats", "Actividades"], C.COLS_ACTIVITATS)
    recursos = _llegeix(["Recursos"], ["Codi de l'espai", "Recurs"])
    franges = _llegeix(["Reserves per franja", "Franges"], [])
    horari = _llegeix(["Horari", "Horario"], ["Dia de la setmana"])
    fonts = _llegeix(["Fonts", "Fuentes"], ["Font"])

    espais[E["codi"]] = espais[E["codi"]].astype(str).str.strip()

    # ---------------------------------------------------------- neteja reserves
    if not reserves.empty:
        reserves[R["codi"]] = reserves[R["codi"]].astype(str).str.strip()
        reserves["_data"] = pd.to_datetime(
            reserves[R["data"]], errors="coerce", dayfirst=True).dt.normalize()
        reserves["_inici"] = _a_minuts(reserves[R["inici"]])
        reserves["_fi"] = _a_minuts(reserves[R["fi"]])
        reserves["_dia"] = reserves[R["dia"]].astype(str).str.strip().str.lower()
        reserves["_mes"] = pd.to_numeric(reserves[R["mes"]], errors="coerce").astype("Int64")
        reserves["_aforament"] = pd.to_numeric(reserves[R["aforament"]], errors="coerce")

        metrica = reserves[R["metrica"]].astype(str).str.lower()
        reserves["_es_pista"] = metrica.str.contains("pista")
        reserves["_mitja_pista"] = _si(reserves[R["mitja"]])
        reserves["_bloc"] = _si(reserves[R["bloc"]]) | (
            pd.to_numeric(reserves[R["dur"]], errors="coerce") > C.LLINDAR_BLOC_MINUTS)
        reserves["_fora_horari"] = _si(reserves[R["fora"]])
        reserves["_dirigida"] = _si(reserves[R["dirigida"]])

        # trampa 2: unitats reals (persones vs pista, amb mitja pista = 0,5)
        reserves["_unitats"] = 1.0
        reserves.loc[reserves["_es_pista"] & reserves["_mitja_pista"], "_unitats"] = 0.5

        reserves = reserves.dropna(subset=["_data", "_inici", "_fi"])
        reserves = reserves[reserves["_fi"] > reserves["_inici"]]

    # -------------------------------------------------------- neteja activitats
    if not activitats.empty:
        activitats[A["codi_espai"]] = activitats[A["codi_espai"]].astype(str).str.strip()
        for col in (A["places"], A["inscrites"], A["pct"]):
            activitats[col] = pd.to_numeric(activitats[col], errors="coerce")
        activitats["_inici"] = _a_minuts(activitats[A["inici"]])
        activitats["_over"] = _si(activitats[A["over"]])

    espais[E["aforament"]] = pd.to_numeric(espais[E["aforament"]], errors="coerce")

    return SafData(
        reserves=reserves, activitats=activitats, espais=espais,
        recursos=recursos, franges=franges, horari=horari, fonts=fonts,
        index_espais=_build_index(espais),
    )
