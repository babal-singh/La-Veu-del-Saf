"""Eines deterministes. CAP LLM. Tota xifra surt d'aquí."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

import numpy as np
import pandas as pd

from . import config as C
from .data import SafData, R, A, E
from .utils import (
    normalitza, fmt_num, fmt_valor, fmt_pct, minuts_a_hhmm,
    hora_en_minuts, xifres_en_text,
)


# ------------------------------------------------------------------ resultat
@dataclass
class Resultat:
    tool: str
    args: dict
    ok: bool
    text: str
    fonts: list[str] = field(default_factory=list)
    dades: dict = field(default_factory=dict)
    taula: pd.DataFrame | None = None

    def xifres(self) -> set[float]:
        """Totes les xifres permeses a la reformulació."""
        out = xifres_en_text(self.text)
        for v in self.dades.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.add(round(float(v), 6))
            elif isinstance(v, str):
                out |= xifres_en_text(v)
        return out


def _no_ho_se(motiu: str, tool: str = "cap", args: dict | None = None) -> Resultat:
    return Resultat(
        tool=tool, args=args or {}, ok=False,
        text=f"No ho sé. {motiu}",
        fonts=[f"Abast del dataset: {C.DATA_INICI} → {C.DATA_FI}"],
    )


# ---------------------------------------------------------------- filtres
def _reserves(d: SafData, codis: list[str], inici: date, fi: date,
              dia: str | None = None) -> pd.DataFrame:
    m = (d.reserves[R["codi"]].isin(codis)
         & (d.reserves["_data"] >= pd.Timestamp(inici))
         & (d.reserves["_data"] <= pd.Timestamp(fi)))
    if dia:
        m &= d.reserves["_dia"] == dia
    return d.reserves.loc[m]


def _noms(d: SafData, codis: list[str]) -> str:
    if len(codis) == 1:
        row = d.info_espai(codis[0])
        return f"{codis[0]} ({row[E['nom']] if row is not None else '—'})"
    return (f"el conjunt de {len(codis)} espais "
            f"({', '.join(codis[:6])}{'…' if len(codis) > 6 else ''})")


def _max_concurrent(df: pd.DataFrame) -> float:
    """Màxim d'unitats simultànies observades (sweep line vectoritzada)."""
    if df.empty:
        return 0.0
    off = df["_data"].map(pd.Timestamp.toordinal).astype(float) * 1440
    ev = pd.concat([
        pd.DataFrame({"t": off + df["_inici"], "d": df["_unitats"]}),
        pd.DataFrame({"t": off + df["_fi"], "d": -df["_unitats"]}),
    ]).sort_values("t", kind="mergesort")
    return float(max(ev["d"].cumsum().max(), 0.0))


def _franges_candidates() -> list[int]:
    """07:00 → 20:00 cada hora (l'horari més ampli possible)."""
    return list(range(7 * 60, 21 * 60, 60))


def _matriu_ocupacio(df: pd.DataFrame, franges: list[int]) -> pd.DataFrame:
    """Files = dates, columnes = franges; NaN si la franja cau fora d'horari."""
    if df.empty:
        return pd.DataFrame(columns=[minuts_a_hhmm(m) for m in franges])

    dates = pd.Index(sorted(df["_data"].unique()))
    idx = dates.get_indexer(df["_data"])
    starts = df["_inici"].to_numpy(float)
    ends = df["_fi"].to_numpy(float)
    units = df["_unitats"].to_numpy(float)

    mat = np.zeros((len(dates), len(franges)))
    for j, m in enumerate(franges):
        sel = (starts <= m) & (ends > m)
        if sel.any():
            np.add.at(mat[:, j], idx[sel], units[sel])

    for i, dt in enumerate(dates):
        dia = C.DIES[pd.Timestamp(dt).weekday()]
        obre, tanca = C.HORARI[dia]
        m0, m1 = obre.hour * 60 + obre.minute, tanca.hour * 60 + tanca.minute
        for j, m in enumerate(franges):
            if not (m0 <= m < m1):
                mat[i, j] = np.nan

    return pd.DataFrame(mat, index=dates,
                        columns=[minuts_a_hhmm(m) for m in franges])


# =============================================================== EINES
def t_horari_obertura(d: SafData, dia: str | None = None, **_) -> Resultat:
    dies = [dia] if dia else C.DIES
    linies = [f"{C.DIA_NOM[k]}: {C.HORARI[k][0]:%H:%M}–{C.HORARI[k][1]:%H:%M}"
              for k in dies]
    return Resultat(
        tool="horari_obertura", args={"dia": dia}, ok=True,
        text="Horari d'obertura del SAF: " + "; ".join(linies) + ".",
        fonts=["Horari (7 files)"],
        dades={"n_dies": len(dies)},
        taula=pd.DataFrame({
            "Dia": [C.DIA_NOM[k] for k in dies],
            "Obertura": [C.HORARI[k][0].strftime("%H:%M") for k in dies],
            "Tancament": [C.HORARI[k][1].strftime("%H:%M") for k in dies],
        }),
    )


def t_info_espai(d: SafData, espai: str, **_) -> Resultat:
    codis, _ = d.resoldre(espai)
    if not codis:
        return _no_ho_se(
            f"No tinc cap espai que coincideixi amb «{espai}» a la taula Espais.",
            "info_espai", {"espai": espai},
        )

    files = []
    for codi in codis:
        row = d.info_espai(codi)
        if row is None:
            continue
        sub = d.reserves[d.reserves[R["codi"]] == codi]
        files.append({
            "Codi": codi,
            "Espai": row[E["nom"]],
            "Instal·lació": row[E["inst"]],
            "Mètrica": row[E["metrica"]],
            "Aforament": row[E["aforament"]],
            "Màx. observat": _max_concurrent(sub),
            "Reserves": int(len(sub)),
        })
    taula = pd.DataFrame(files)

    if len(taula) == 1:
        r = taula.iloc[0]
        metrica = str(r["Mètrica"]).lower()
        unitat = "persones" if "person" in metrica else "pistes"
        text = (
            f"{r['Codi']} — {r['Espai']} (instal·lació: {r['Instal·lació']}). "
            f"Aforament màxim: {fmt_num(r['Aforament'])} {unitat}. "
            f"Es compta per {metrica}. "
            f"Màxim simultani observat al dataset: {fmt_valor(r['Màx. observat'])}. "
            f"Total de reserves registrades: {fmt_num(r['Reserves'])}."
        )
    else:
        text = (
            f"He trobat {len(taula)} espais per a «{espai}»: "
            + "; ".join(
                f"{x['Codi']} ({fmt_num(x['Aforament'])} "
                f"{'persones' if 'person' in str(x['Mètrica']).lower() else 'pistes'})"
                for _, x in taula.iterrows()
            ) + "."
        )

    return Resultat(
        "info_espai", {"espai": espai}, True, text,
        [f"Espais · {len(codis)} codi(s)",
         f"Reserves · {int(taula['Reserves'].sum())} files"],
        {"n_espais": len(codis)}, taula,
    )


def t_ocupacio_instant(d: SafData, espai: str, data: str, hora: str, **_) -> Resultat:
    codis, _ = d.resoldre(espai)
    if not codis:
        return _no_ho_se(
            f"No reconec l'espai «{espai}».",
            "ocupacio_instant", {"espai": espai, "data": data, "hora": hora},
        )
    try:
        dt = pd.Timestamp(data).normalize()
    except Exception:
        return _no_ho_se(f"La data «{data}» no és vàlida (format YYYY-MM-DD).")
    if not (pd.Timestamp(C.DATA_INICI) <= dt <= pd.Timestamp(C.DATA_FI)):
        return _no_ho_se(
            f"La data {dt.date()} queda fora del dataset "
            f"({C.DATA_INICI} → {C.DATA_FI})."
        )

    m = hora_en_minuts(hora)
    if m is None:
        return _no_ho_se(f"L'hora «{hora}» no és vàlida (format HH:MM).")

    dia = C.DIES[dt.weekday()]
    obre, tanca = C.HORARI[dia]
    m0, m1 = obre.hour * 60 + obre.minute, tanca.hour * 60 + tanca.minute

    sub = d.reserves[(d.reserves[R["codi"]].isin(codis))
                     & (d.reserves["_data"] == dt)]
    actius = sub[(sub["_inici"] <= m) & (sub["_fi"] > m)]
    ocupacio = float(actius["_unitats"].sum())
    aforament = d.aforament_total(codis)
    metrica = d.metrica(codis)
    pct = (ocupacio / aforament * 100) if aforament > 0 else float("nan")

    notes: list[str] = []
    if not (m0 <= m < m1):
        notes.append(
            f"fora de l'horari d'obertura "
            f"({obre:%H:%M}–{tanca:%H:%M} el {C.DIA_NOM[dia]})"
        )
    if d.es_fitness(codis) and minuts_a_hhmm(m) in C.FORATS_FITNESS:
        notes.append(
            "és un forat de canvi de torn del fitness (10:00 i 15:00), "
            "no és baixa demanda"
        )
    if actius["_bloc"].any():
        notes.append(
            f"inclou {int(actius['_bloc'].sum())} reserva(es) de bloc "
            f"de club/escola (>4 h)"
        )

    unitat = "persones" if metrica == "persones" else "pistes ocupades"
    text = (
        f"El {C.DIA_NOM[dia]} {dt.date()} a les {minuts_a_hhmm(m)}, "
        f"{_noms(d, codis)} té {fmt_valor(ocupacio)} {unitat} "
        f"({fmt_pct(pct) if not math.isnan(pct) else 'sense aforament definit'} "
        f"de {fmt_num(aforament)}). "
        f"Reserves actives en aquell instant: {len(actius)}."
    )
    if notes:
        text += " Nota: " + "; ".join(notes) + "."

    return Resultat(
        "ocupacio_instant",
        {"espai": espai, "data": str(dt.date()), "hora": minuts_a_hhmm(m)},
        True, text,
        [f"Reserves · {len(sub)} files del {dt.date()}",
         f"Espais · {', '.join(codis)}"],
        {"ocupacio": ocupacio, "aforament": aforament, "pct": pct,
         "n_reserves": len(actius)},
        actius[[R["inici"], R["fi"], R["recurs"], R["dur"]]].head(20),
    )


def t_ocupacio_tipica(d: SafData, espai: str, hora: str, dia: str | None = None,
                      data_inici: str | None = None, data_fi: str | None = None,
                      **_) -> Resultat:
    """Ocupació mitjana (mediana, min, max) en una hora i dia de la setmana."""
    codis, _ = d.resoldre(espai)
    if not codis:
        return _no_ho_se(
            f"No reconec l'espai «{espai}».",
            "ocupacio_tipica", {"espai": espai, "hora": hora, "dia": dia},
        )
    m = hora_en_minuts(hora)
    if m is None:
        return _no_ho_se(f"L'hora «{hora}» no és vàlida.")

    ini = pd.Timestamp(data_inici or C.DATA_INICI)
    fi = pd.Timestamp(data_fi or C.DATA_FI)
    mask = (d.reserves[R["codi"]].isin(codis)
            & (d.reserves["_data"] >= ini)
            & (d.reserves["_data"] <= fi))
    if dia:
        mask &= d.reserves["_dia"] == dia
    sub = d.reserves.loc[mask]
    if sub.empty:
        return _no_ho_se(
            f"No hi ha cap reserva de {_noms(d, codis)} per als filtres indicats.",
            "ocupacio_tipica", {"espai": espai, "hora": hora, "dia": dia},
        )

    dates = sorted(sub["_data"].unique())
    active = sub[(sub["_inici"] <= m) & (sub["_fi"] > m)]
    per_date = (active.groupby("_data")["_unitats"].sum()
                .reindex(dates, fill_value=0.0))

    aforament = d.aforament_total(codis)
    metrica = d.metrica(codis)
    unitat = "persones" if metrica == "persones" else "pistes"

    mitjana = float(per_date.mean())
    mediana = float(per_date.median())
    maxim = float(per_date.max())
    minim = float(per_date.min())
    n_dies = len(per_date)

    dia_str = f" els {C.DIA_NOM[dia]}" if dia else ""
    text = (
        f"Ocupació típica de {_noms(d, codis)}{dia_str} a les {minuts_a_hhmm(m)}: "
        f"mitjana {fmt_valor(mitjana)} {unitat} "
        f"(mediana {fmt_valor(mediana)}, mínim {fmt_valor(minim)}, "
        f"màxim {fmt_valor(maxim)}) sobre {n_dies} dies "
        f"({ini.date()} → {fi.date()}). "
        f"Aforament de referència: {fmt_valor(aforament)}."
    )
    if aforament > 0:
        text += f" Ocupació mitjana: {fmt_pct(mitjana / aforament * 100)}."
    if d.es_fitness(codis) and minuts_a_hhmm(m) in C.FORATS_FITNESS:
        text += (" Nota: aquesta hora és un canvi de torn del fitness "
                 "(10:00 i 15:00); no és una franja de baixa demanda.")

    taula = pd.DataFrame({
        "Data": [str(pd.Timestamp(t).date()) for t in per_date.index],
        "Ocupació": per_date.values.round(2),
    })

    return Resultat(
        "ocupacio_tipica",
        {"espai": espai, "hora": minuts_a_hhmm(m), "dia": dia},
        True, text,
        [f"Reserves · {len(sub)} files filtrades",
         f"Espais · {', '.join(codis)}"],
        {"mitjana": mitjana, "mediana": mediana, "maxim": maxim,
         "minim": minim, "n_dies": n_dies, "aforament": aforament},
        taula.head(30),
    )


def t_perfil_ocupacio(d: SafData, espai: str, data_inici: str, data_fi: str,
                      dia: str | None = None, **_) -> Resultat:
    codis, _ = d.resoldre(espai)
    if not codis:
        return _no_ho_se(
            f"No reconec l'espai «{espai}».",
            "perfil_ocupacio", {"espai": espai},
        )
    ini, fi = pd.Timestamp(data_inici), pd.Timestamp(data_fi)
    sub = _reserves(d, codis, ini.date(), fi.date(), dia)
    if sub.empty:
        return _no_ho_se(
            f"No hi ha cap reserva de {_noms(d, codis)} entre "
            f"{ini.date()} i {fi.date()}"
            + (f" en {C.DIA_NOM[dia]}" if dia else "") + ".",
            "perfil_ocupacio", {"espai": espai},
        )

    franges = _franges_candidates()
    mat = _matriu_ocupacio(sub, franges)
    perfil = pd.DataFrame({
        "Franja": mat.columns,
        "Mitjana": mat.mean(axis=0, skipna=True).values,
        "Màxim": mat.max(axis=0, skipna=True).values,
        "Dies": mat.notna().sum(axis=0).values,
    }).dropna(subset=["Mitjana"])

    if perfil.empty:
        return _no_ho_se("No hi ha prou dades per construir un perfil horari.")

    aforament = d.aforament_total(codis)
    metrica = d.metrica(codis)
    unitat = "persones" if metrica == "persones" else "pistes"
    pic = perfil.loc[perfil["Mitjana"].idxmax()]
    vall = perfil.loc[perfil["Mitjana"].idxmin()]
    global_mitja = float(perfil["Mitjana"].mean())

    notes = ""
    if d.es_fitness(codis):
        marcats = perfil[perfil["Franja"].isin(C.FORATS_FITNESS)]
        if not marcats.empty:
            notes = (f" Els forats de torn ({', '.join(sorted(C.FORATS_FITNESS))}) "
                     f"tenen una mitjana de {fmt_valor(marcats['Mitjana'].mean())} "
                     f"— no indiquen baixa demanda.")

    text = (
        f"Perfil de {_noms(d, codis)} entre {ini.date()} i {fi.date()}"
        + (f" ({C.DIA_NOM[dia]})" if dia else "")
        + f": mitjana global {fmt_valor(global_mitja)} {unitat} per franja. "
        f"Pic: {pic['Franja']} amb {fmt_valor(pic['Mitjana'])} {unitat} de mitjana "
        f"(màxim {fmt_valor(pic['Màxim'])}; {int(pic['Dies'])} dies). "
        f"Vall: {vall['Franja']} amb {fmt_valor(vall['Mitjana'])} {unitat}. "
        f"Aforament de referència: {fmt_num(aforament)}." + notes
    )

    return Resultat(
        "perfil_ocupacio",
        {"espai": espai, "data_inici": str(ini.date()),
         "data_fi": str(fi.date()), "dia": dia},
        True, text,
        [f"Reserves · {len(sub)} files filtrades",
         f"Espais · {', '.join(codis)}"],
        {"mitjana_global": global_mitja, "aforament": aforament,
         "n_dies": int(mat.shape[0])},
        perfil.round(2),
    )


def t_franges_baixes(d: SafData, espai: str, data_inici: str, data_fi: str,
                     dia: str | None = None, top_n: int = 3, **_) -> Resultat:
    base = t_perfil_ocupacio(d, espai, data_inici, data_fi, dia)
    if not base.ok or base.taula is None:
        return base

    codis, _ = d.resoldre(espai)
    perfil = base.taula.copy()
    if d.es_fitness(codis):
        perfil = perfil[~perfil["Franja"].isin(C.FORATS_FITNESS)]
    perfil = perfil[perfil["Dies"] >= 3]
    if perfil.empty:
        return _no_ho_se("No hi ha prou dies amb dades per comparar franges.")

    perfil = perfil.sort_values("Mitjana").head(int(top_n))
    global_m = float(base.dades["mitjana_global"])
    metrica = d.metrica(codis)
    unitat = "persones" if metrica == "persones" else "pistes"

    llista = "; ".join(
        f"{r['Franja']} ({fmt_valor(r['Mitjana'])} {unitat}, "
        f"−{fmt_valor(global_m - r['Mitjana'])} respecte la mitjana)"
        for _, r in perfil.iterrows()
    )

    text = (
        f"Les franges amb menys ocupació de {_noms(d, codis)} entre "
        f"{data_inici} i {data_fi}"
        + (f" ({C.DIA_NOM[dia]})" if dia else "")
        + f" són: {llista}. "
        f"Mitjana global de referència: {fmt_valor(global_m)} {unitat} per franja."
    )

    return Resultat(
        "franges_baixes", base.args, True, text, base.fonts,
        {**base.dades, "top_n": len(perfil)}, perfil.round(2),
    )


def t_disponibilitat(d: SafData, espai: str, data: str,
                     hora_inici: str | None = None, hora_fi: str | None = None,
                     **_) -> Resultat:
    codis, _ = d.resoldre(espai)
    if not codis:
        return _no_ho_se(
            f"No reconec l'espai «{espai}».",
            "disponibilitat", {"espai": espai, "data": data},
        )
    dt = pd.Timestamp(data).normalize()
    if not (pd.Timestamp(C.DATA_INICI) <= dt <= pd.Timestamp(C.DATA_FI)):
        return _no_ho_se(f"La data {dt.date()} queda fora del dataset.")

    dia = C.DIES[dt.weekday()]
    obre, tanca = C.HORARI[dia]
    m0 = hora_en_minuts(hora_inici) if hora_inici else obre.hour * 60 + obre.minute
    m1 = hora_en_minuts(hora_fi) if hora_fi else tanca.hour * 60 + tanca.minute
    if m0 is None or m1 is None or m1 <= m0:
        return _no_ho_se("Les hores indicades no són vàlides.")

    sub = d.reserves[(d.reserves[R["codi"]].isin(codis))
                     & (d.reserves["_data"] == dt)]
    files = []
    for m in range(m0, m1, 60):
        act = sub[(sub["_inici"] <= m) & (sub["_fi"] > m)]
        files.append({
            "Franja": minuts_a_hhmm(m),
            "Ocupació": float(act["_unitats"].sum()),
            "Reserves": int(len(act)),
        })
    taula = pd.DataFrame(files)
    if taula.empty:
        return _no_ho_se("La franja demanada no conté cap hora sencera.")

    aforament = d.aforament_total(codis)
    metrica = d.metrica(codis)
    unitat = "persones" if metrica == "persones" else "pistes"
    lliures = taula[taula["Ocupació"] == 0]["Franja"].tolist()
    max_obs = _max_concurrent(sub)
    places = max(aforament, max_obs)

    if lliures:
        text = (
            f"El {C.DIA_NOM[dia]} {dt.date()}, {_noms(d, codis)} està lliure a les "
            f"{', '.join(lliures)} (0 {unitat} en aquell instant). "
            f"La resta de franges tenen ocupació. "
            f"Capacitat de referència: {fmt_valor(places)} {unitat}."
        )
    else:
        ocupades = taula.sort_values("Ocupació", ascending=False).head(3)
        text = (
            f"El {C.DIA_NOM[dia]} {dt.date()}, {_noms(d, codis)} no té cap franja "
            f"lliure entre {minuts_a_hhmm(m0)} i {minuts_a_hhmm(m1)}. "
            f"Les menys ocupades: "
            + ", ".join(
                f"{r['Franja']} ({fmt_valor(r['Ocupació'])} {unitat})"
                for _, r in ocupades.iterrows()
            ) + "."
        )

    return Resultat(
        "disponibilitat",
        {"espai": espai, "data": str(dt.date())},
        True, text,
        [f"Reserves · {len(sub)} files del {dt.date()}",
         "Horari · obertura/tancament"],
        {"aforament": places, "n_franges": len(taula)}, taula,
    )


def t_comptatge_reserves(d: SafData, espai: str, data_inici: str, data_fi: str,
                         dia: str | None = None, incloure_blocs: bool = False,
                         **_) -> Resultat:
    codis, _ = d.resoldre(espai)
    if not codis:
        return _no_ho_se(
            f"No reconec l'espai «{espai}».",
            "comptatge_reserves", {"espai": espai},
        )
    ini, fi = pd.Timestamp(data_inici), pd.Timestamp(data_fi)
    sub = _reserves(d, codis, ini.date(), fi.date(), dia)
    if sub.empty:
        return _no_ho_se(
            f"No hi ha cap reserva de {_noms(d, codis)} entre "
            f"{ini.date()} i {fi.date()}.",
            "comptatge_reserves", {"espai": espai},
        )

    total = len(sub)
    blocs = int(sub["_bloc"].sum())
    fora = int(sub["_fora_horari"].sum())
    dirigides = int(sub["_dirigida"].sum())
    base = sub if incloure_blocs else sub[~sub["_bloc"]]
    n_base = len(base)

    text = (
        f"Entre {ini.date()} i {fi.date()}"
        + (f" ({C.DIA_NOM[dia]})" if dia else "")
        + f", {_noms(d, codis)} té {fmt_num(total)} reserves registrades. "
        f"D'aquestes, {fmt_num(blocs)} són blocs de club/escola de més de 4 hores, "
        f"{fmt_num(fora)} són fora d'horari d'obertura i {fmt_num(dirigides)} "
        f"estan vinculades a activitat dirigida. "
        f"Reserves individuals (sense blocs): {fmt_num(n_base)}."
    )
    if blocs and not incloure_blocs:
        text += " Els blocs institucionals s'han exclòs del recompte individual."

    return Resultat(
        "comptatge_reserves",
        {"espai": espai, "data_inici": str(ini.date()),
         "data_fi": str(fi.date()), "dia": dia,
         "incloure_blocs": incloure_blocs},
        True, text,
        [f"Reserves · {total} files filtrades"],
        {"total": total, "blocs": blocs, "fora_horari": fora,
         "dirigides": dirigides, "individuals": n_base},
        sub.head(25)[[R["data"], R["inici"], R["fi"], R["recurs"], R["dur"]]],
    )


def t_comparar_mesos(d: SafData, espai: str, mes_a: int, mes_b: int, **_) -> Resultat:
    codis, _ = d.resoldre(espai)
    if not codis:
        return _no_ho_se(
            f"No reconec l'espai «{espai}».",
            "comparar_mesos", {"espai": espai},
        )
    try:
        ma, mb = int(mes_a), int(mes_b)
    except Exception:
        return _no_ho_se("Els mesos han de ser números entre 4 i 10.")
    if ma not in C.MES_NOM or mb not in C.MES_NOM:
        return _no_ho_se("El dataset només cobreix els mesos 4 (abril) a 10 (octubre).")

    files = []
    for mes in (ma, mb):
        sub = d.reserves[(d.reserves[R["codi"]].isin(codis))
                         & (d.reserves["_mes"] == mes)]
        dies = sub["_data"].nunique()
        files.append({
            "Mes": C.MES_NOM[mes],
            "Reserves": len(sub),
            "Dies amb dades": int(dies),
            "Reserves/dia": (len(sub) / dies) if dies else 0.0,
        })
    taula = pd.DataFrame(files)
    a, b = taula.iloc[0], taula.iloc[1]
    ratio = (b["Reserves"] / a["Reserves"]) if a["Reserves"] else float("nan")

    text = (
        f"{_noms(d, codis)}: {fmt_num(a['Reserves'])} reserves el {a['Mes']} "
        f"({fmt_valor(a['Reserves/dia'])} per dia) vs "
        f"{fmt_num(b['Reserves'])} el {b['Mes']} "
        f"({fmt_valor(b['Reserves/dia'])} per dia). "
        f"Ratio {b['Mes']}/{a['Mes']}: {fmt_valor(ratio, 2)}×. "
    )
    if 8 in (ma, mb):
        text += ("Atenció a l'efecte estacional: l'agost cau aproximadament a un terç "
                 "del volum d'octubre, així que la comparació no reflecteix demanda real.")

    return Resultat(
        "comparar_mesos",
        {"espai": espai, "mes_a": ma, "mes_b": mb},
        True, text,
        [f"Reserves · mesos {ma} i {mb}"],
        {"reserves_a": int(a["Reserves"]), "reserves_b": int(b["Reserves"]),
         "ratio": ratio},
        taula,
    )


def t_activitats_dirigides(d: SafData, nom: str | None = None,
                           espai: str | None = None, tipus: str | None = None,
                           hora: str | None = None,
                           nomes_amb_places: bool = False, **_) -> Resultat:
    if d.activitats.empty:
        return _no_ho_se("La taula Activitats dirigides és buida.")
    df = d.activitats

    if nom:
        n = normalitza(nom)
        df = df[df[A["nom"]].astype(str).map(lambda x: n in normalitza(x))]
    if espai:
        codis, _ = d.resoldre(espai)
        if codis:
            df = df[df[A["codi_espai"]].isin(codis)]
        else:
            df = df[df[A["sala"]].astype(str).map(lambda x: normalitza(espai) in normalitza(x))]
    if tipus:
        df = df[df[A["tipus"]].astype(str).str.lower().str.startswith(normalitza(tipus)[:4])]
    if hora:
        m = hora_en_minuts(hora)
        if m is not None:
            df = df[df["_inici"] == m]
    if nomes_amb_places:
        df = df[df[A["inscrites"]] < df[A["places"]]]

    if df.empty:
        return _no_ho_se(
            "No hi ha cap activitat dirigida que compleixi aquests criteris. "
            "Nota: la taula Activitats dirigides no conté la data de la classe "
            "(només la data d'inscripció), així que no puc filtrar per dia concret.",
            "activitats_dirigides", {},
        )

    agr = (
        df.groupby(A["nom"], dropna=False)
        .agg(
            Places=(A["places"], "sum"),
            Inscrites=(A["inscrites"], "sum"),
            Ocupacio=(A["pct"], "mean"),
            Sessions=(A["nom"], "size"),
            Sala=(A["sala"], "first"),
        )
        .reset_index()
        .sort_values("Inscrites", ascending=False)
    )

    top = agr.head(8)
    n_over = int(df["_over"].sum())
    total_places = float(agr["Places"].sum())
    total_insc = float(agr["Inscrites"].sum())
    ocup_global = (total_insc / total_places * 100) if total_places else float("nan")

    detall = "; ".join(
        f"{r[A['nom']]} ({fmt_num(r['Inscrites'])}/{fmt_num(r['Places'])} places, "
        f"{fmt_pct(r['Ocupacio'])})"
        for _, r in top.iterrows()
    )

    text = (
        f"Activitats dirigides que coincideixen: {len(agr)} activitats, "
        f"{fmt_num(len(df))} registres. "
        f"Ocupació mitjana global: {fmt_pct(ocup_global)} "
        f"({fmt_num(total_insc)} inscripcions sobre {fmt_num(total_places)} places). "
        f"Les més demandades: {detall}. "
    )
    if n_over:
        text += (f"Hi ha {fmt_num(n_over)} registres marcats com a "
                 f"«més inscrits que places» (sobrevenda).")

    return Resultat(
        "activitats_dirigides",
        {"nom": nom, "espai": espai, "tipus": tipus,
         "hora": hora, "nomes_amb_places": nomes_amb_places},
        True, text,
        [f"Activitats dirigides · {len(df)} files filtrades"],
        {"n_activitats": len(agr), "ocupacio_global": ocup_global,
         "n_overbooking": n_over},
        agr.round(2),
    )


# =============================================================== REGISTRE
TOOLS: dict[str, tuple[Callable, dict]] = {
    "horari_obertura": (t_horari_obertura, {
        "description": "Retorna l'horari d'obertura del SAF per dia de la setmana.",
        "params": {"dia": {"type": "string", "enum": C.DIES, "required": False}},
    }),
    "info_espai": (t_info_espai, {
        "description": "Aforament, instal·lació, mètrica de recompte i codi d'un espai.",
        "params": {"espai": {"type": "string", "required": True}},
    }),
    "ocupacio_instant": (t_ocupacio_instant, {
        "description": "Ocupació exacta d'un espai en una data i hora concretes.",
        "params": {
            "espai": {"type": "string", "required": True},
            "data": {"type": "string", "required": True},
            "hora": {"type": "string", "required": True},
        },
    }),
    "ocupacio_tipica": (t_ocupacio_tipica, {
        "description": ("Ocupació mitjana (mediana, mínim, màxim) d'un espai "
                        "en una hora i dia de la setmana, al llarg d'un període."),
        "params": {
            "espai": {"type": "string", "required": True},
            "hora": {"type": "string", "required": True},
            "dia": {"type": "string", "enum": C.DIES, "required": False},
            "data_inici": {"type": "string", "required": False},
            "data_fi": {"type": "string", "required": False},
        },
    }),
    "perfil_ocupacio": (t_perfil_ocupacio, {
        "description": "Perfil mitjà per franja horària, amb pic i vall.",
        "params": {
            "espai": {"type": "string", "required": True},
            "data_inici": {"type": "string", "required": True},
            "data_fi": {"type": "string", "required": True},
            "dia": {"type": "string", "enum": C.DIES, "required": False},
        },
    }),
    "franges_baixes": (t_franges_baixes, {
        "description": "Alternatives de baixa ocupació ordenades de menys a més trànsit.",
        "params": {
            "espai": {"type": "string", "required": True},
            "data_inici": {"type": "string", "required": True},
            "data_fi": {"type": "string", "required": True},
            "dia": {"type": "string", "enum": C.DIES, "required": False},
            "top_n": {"type": "integer", "required": False},
        },
    }),
    "disponibilitat": (t_disponibilitat, {
        "description": "Franges lliures d'un espai en un dia concret.",
        "params": {
            "espai": {"type": "string", "required": True},
            "data": {"type": "string", "required": True},
            "hora_inici": {"type": "string", "required": False},
            "hora_fi": {"type": "string", "required": False},
        },
    }),
    "comptatge_reserves": (t_comptatge_reserves, {
        "description": "Recompte de reserves amb desglossament de blocs i fora d'horari.",
        "params": {
            "espai": {"type": "string", "required": True},
            "data_inici": {"type": "string", "required": True},
            "data_fi": {"type": "string", "required": True},
            "dia": {"type": "string", "enum": C.DIES, "required": False},
            "incloure_blocs": {"type": "boolean", "required": False},
        },
    }),
    "comparar_mesos": (t_comparar_mesos, {
        "description": "Compara el volum de reserves entre dos mesos (4–10).",
        "params": {
            "espai": {"type": "string", "required": True},
            "mes_a": {"type": "integer", "required": True},
            "mes_b": {"type": "integer", "required": True},
        },
    }),
    "activitats_dirigides": (t_activitats_dirigides, {
        "description": "Consulta agregada d'activitats dirigides: places, inscripcions, ocupació.",
        "params": {
            "nom": {"type": "string", "required": False},
            "espai": {"type": "string", "required": False},
            "tipus": {"type": "string", "enum": ["regular", "especial"], "required": False},
            "hora": {"type": "string", "required": False},
            "nomes_amb_places": {"type": "boolean", "required": False},
        },
    }),
}


def tools_openai() -> list[dict]:
    """Converteix TOOLS al format OpenAI `tools`."""
    out = []
    for nom, (_, spec) in TOOLS.items():
        props: dict[str, Any] = {}
        required: list[str] = []
        for k, v in spec["params"].items():
            props[k] = {"type": v.get("type", "string")}
            if "enum" in v:
                props[k]["enum"] = v["enum"]
            if v.get("required"):
                required.append(k)
        out.append({
            "type": "function",
            "function": {
                "name": nom,
                "description": spec["description"],
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        })
    return out


def valida_args(nom: str, args: dict) -> tuple[bool, list[str]]:
    if nom not in TOOLS:
        return False, [f"eina desconeguda: {nom}"]
    spec = TOOLS[nom][1]["params"]
    faltes = [k for k, v in spec.items() if v.get("required") and k not in args]
    for k, v in args.items():
        if k in spec and "enum" in spec[k] and v not in spec[k]["enum"]:
            faltes.append(f"valor no permès per a {k}: {v}")
    return (not faltes), faltes


def executa(nom: str, args: dict, d: SafData) -> Resultat:
    if nom == "_no_ho_se":
        return _no_ho_se(args.get("motiu", ""), "_no_ho_se")
    if nom not in TOOLS:
        return _no_ho_se(f"No tinc cap eina anomenada «{nom}».")
    try:
        return TOOLS[nom][0](d, **args)
    except TypeError as e:
        return _no_ho_se(f"Arguments incorrectes per a l'eina {nom}: {e}.", nom, args)
    except Exception as e:                                     # noqa: BLE001
        return _no_ho_se(
            f"S'ha produït un error consultant les dades "
            f"({type(e).__name__}: {e}).",
            nom, args,
        )
