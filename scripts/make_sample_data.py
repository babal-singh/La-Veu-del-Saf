"""Genera un data/saf.xlsx sintètic amb les 7 taules del dataset SAF.

Les dades reprodueixen les trampes del domini:
  - Fitness amb torns de 75 min i forats a 10:00 i 15:00.
  - Mètrica persones vs pista (PADEL amb mitja pista = 0,5).
  - Blocs de club/escola > 4 h (principalment caps de setmana).
  - Caiguda d'agost (~1/3 del volum d'octubre).
  - Activitats dirigides amb sobrevenda ocasional.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from saf import config as C

OUT = Path(__file__).resolve().parent.parent / "data" / "saf.xlsx"

random.seed(42)
np.random.seed(42)


def _date_range(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ---------------------------------------------------------------- Espais
def make_espais() -> pd.DataFrame:
    rows: list[tuple] = []
    # Fitness: 1 sala gran, mètrica persones
    rows.append(("FITNESS", "fitness", "sala fitness", "Sala de fitness", 121, "persones"))
    # Piscina: vas + 4 carrers, persones
    rows.append(("PISCINA_VAS", "piscina", "vas principal 25m",
                 "Piscina - vas principal", 80, "persones"))
    for i in range(1, 5):
        rows.append((f"PISCINA_CARRER{i}", "piscina", f"carrer {i}",
                     f"Piscina - carrer {i}", 8, "persones"))
    # Pàdel: 8 pistes
    for i in range(1, 9):
        rows.append((f"PADEL_{i}", "padel", f"pista {i}",
                     f"Pista de pàdel {i}", 4, "pista"))
    # Tennis: 6 pistes
    for i in range(1, 7):
        rows.append((f"TENNIS_{i}", "tennis", f"pista {i}",
                     f"Pista de tennis {i}", 4, "pista"))
    # Squash: 3 pistes
    for i in range(1, 4):
        rows.append((f"SQUASH_{i}", "squash", f"pista {i}",
                     f"Pista de squash {i}", 2, "pista"))
    # Poliesportiu
    rows.append(("POLI_1", "poliesportiu", "pista central",
                 "Poliesportiu - pista central", 40, "pista"))
    # Sales per activitats dirigides (persones)
    noms_act = ["zumba", "ioga", "pilates", "spinning", "body pump", "crossfit",
                "tonificació", "estiraments", "aeròbic", "circuit"]
    for i in range(1, 15):
        act = noms_act[(i - 1) % len(noms_act)]
        rows.append((f"SALA_{i}", "sales", f"sala {i}",
                     f"Sala {i} ({act})", 20 + i * 2, "persones"))
    # 3 sales polivalents extra (fins a 41)
    for i in range(15, 18):
        rows.append((f"SALA_{i}", "sales", f"sala {i}",
                     f"Sala {i} (polivalent)", 20, "persones"))
    return pd.DataFrame(rows, columns=C.COLS_ESPAIS)


# ---------------------------------------------------------------- Recursos
def make_recursos(espais: pd.DataFrame) -> pd.DataFrame:
    rows = [(e["Codi de l'espai"], e["Nom complet de l'espai"])
            for _, e in espais.iterrows()]
    return pd.DataFrame(rows, columns=["Codi de l'espai", "Recurs"])


# --------------------------------------------------------------- Reserves
def _slot_units(rng: random.Random, lo: int, hi: int) -> int:
    return rng.randint(lo, hi)


def make_reserves(espais: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    info = {
        e["Codi de l'espai"]: (float(e["Aforament màxim (persones)"]),
                               e["Es compta per persones o per pista"])
        for _, e in espais.iterrows()
    }

    for dt in _date_range(C.DATA_INICI, C.DATA_FI):
        dow = dt.weekday()
        dia = C.DIES[dow]
        obre, tanca = C.HORARI[dia]
        open_min = obre.hour * 60 + obre.minute
        close_min = tanca.hour * 60 + tanca.minute
        mes = dt.month
        month_factor = 0.35 if mes == 8 else (1.15 if mes == 10 else 1.0)

        # Fitness (11 torns, 75 min)
        for hour in [7, 8, 9, 11, 12, 13, 14, 16, 17, 18, 19]:
            start = hour * 60
            end = start + C.DURADA_TORN_FITNESS
            if end > close_min:
                continue
            if hour >= 17:
                p = 0.85
            elif hour <= 9:
                p = 0.55
            elif 11 <= hour <= 14:
                p = 0.30
            else:
                p = 0.45
            if random.random() < p * month_factor:
                rows.append(_row(dt, dia, mes, start, end,
                                 "FITNESS", "Sala de fitness", "Sala fitness",
                                 "persones", info["FITNESS"][0],
                                 _slot_units(random, 15, 121),
                                 mitja="No", dirigida="No", bloc="No", fora="No"))

        # Piscina
        for codi in ("PISCINA_VAS", "PISCINA_CARRER1", "PISCINA_CARRER2",
                     "PISCINA_CARRER3", "PISCINA_CARRER4"):
            for start in range(open_min, close_min, 60):
                if random.random() < 0.35 * month_factor:
                    units = random.randint(1, int(info[codi][0]))
                    rows.append(_row(dt, dia, mes, start, start + 60,
                                     codi, "Piscina", "Vas",
                                     "persones", info[codi][0], units,
                                     mitja="No", dirigida="No", bloc="No", fora="No"))

        # Pàdel, tennis, squash (60 min, amb mitja pista ocasional)
        for codi, inst, nom in _pistes(info):
            for start in range(open_min, close_min, 60):
                hour = start // 60
                if 17 <= hour <= 20:
                    p = 0.55
                elif 7 <= hour <= 9:
                    p = 0.30
                else:
                    p = 0.25
                if random.random() < p * month_factor:
                    mitja = "Sí" if random.random() < 0.15 else "No"
                    dur = 60
                    bloc = "No"
                    if dia in ("ds", "dg") and random.random() < 0.08:
                        dur = random.choice([270, 300, 360])
                        bloc = "Sí"
                    end = min(start + dur, close_min)
                    if end <= start:
                        continue
                    rows.append(_row(dt, dia, mes, start, end,
                                     codi, inst, nom,
                                     "pista", info[codi][0], 0.5 if mitja == "Sí" else 1.0,
                                     mitja=mitja, dirigida="No", bloc=bloc, fora="No"))

        # Poliesportiu: ús regular + bloc de club dissabte
        for start in range(open_min, close_min, 60):
            if random.random() < 0.25 * month_factor:
                rows.append(_row(dt, dia, mes, start, start + 60,
                                 "POLI_1", "poliesportiu", "Pista central",
                                 "pista", info["POLI_1"][0], 1.0,
                                 mitja="No", dirigida="No", bloc="No", fora="No"))
        if dia == "ds" and random.random() < 0.5:
            rows.append(_row(dt, dia, mes, 9 * 60, 13 * 60 + 30,
                             "POLI_1", "poliesportiu", "Pista central",
                             "pista", info["POLI_1"][0], 1.0,
                             mitja="No", dirigida="No", bloc="Sí", fora="No"))

        # Sales (activitats dirigides)
        for i in range(1, 18):
            codi = f"SALA_{i}"
            for start in range(open_min, close_min, 60):
                if random.random() < 0.30 * month_factor:
                    dirigida = "Sí" if random.random() < 0.7 else "No"
                    rows.append(_row(dt, dia, mes, start, start + 60,
                                     codi, "sales", f"sala {i}",
                                     "persones", info[codi][0],
                                     random.randint(5, int(info[codi][0])),
                                     mitja="No", dirigida=dirigida, bloc="No", fora="No"))

    # Fora d'horari (2% mostres)
    n_out = max(50, len(rows) // 50)
    for _ in range(n_out):
        dt = random.choice(list(_date_range(C.DATA_INICI, C.DATA_FI)))
        dow = dt.weekday()
        dia = C.DIES[dow]
        mes = dt.month
        codi, inst, nom = random.choice(list(_pistes(info)))
        h = random.choice([5, 6, 21, 22])
        start = h * 60
        rows.append(_row(dt, dia, mes, start, start + 60,
                         codi, inst, nom, "pista", info[codi][0], 1.0,
                         mitja="No", dirigida="No", bloc="No", fora="Sí"))

    return pd.DataFrame(rows, columns=C.COLS_RESERVES)


def _pistes(info: dict):
    for codi, (_, metrica) in info.items():
        if codi.startswith("PADEL"):
            yield codi, "padel", f"Pista de pàdel {codi.split('_')[1]}"
        elif codi.startswith("TENNIS"):
            yield codi, "tennis", f"Pista de tennis {codi.split('_')[1]}"
        elif codi.startswith("SQUASH"):
            yield codi, "squash", f"Pista de squash {codi.split('_')[1]}"


def _row(dt, dia, mes, start_min, end_min, codi, inst, nom_recurs,
         metrica, aforament, units, mitja, dirigida, bloc, fora) -> dict:
    dur = end_min - start_min
    return {
        "Data d'ús de la reserva": dt.isoformat(),
        "Dia de la setmana": dia,
        "Mes (número)": mes,
        "Hora d'inici": f"{start_min // 60:02d}:{start_min % 60:02d}",
        "Hora de finalització": f"{end_min // 60:02d}:{end_min % 60:02d}",
        "Durada (minuts)": dur,
        "Codi de l'espai": codi,
        "Nom de l'espai a l'inventari": nom_recurs,
        "Recurs reservat (nom original)": f"{nom_recurs} ({units} u.)",
        "Es compta per persones o per pista": metrica,
        "Aforament màxim de l'espai": aforament,
        "Reserva d'una part de l'espai (mitja pista)": mitja,
        "Reserva per a una activitat dirigida": dirigida,
        "Reserva de més de 4 hores (bloc de club o escola)": bloc,
        "Reserva fora de l'horari d'obertura": fora,
    }


# ----------------------------------------------------------- Activitats
def make_activitats() -> pd.DataFrame:
    rows: list[dict] = []
    noms = ["Zumba", "Ioga", "Pilates", "Spinning", "Body Pump", "Crossfit",
            "Tonificació", "Estiraments", "Aeròbic", "Circuito"]
    sales = [f"SALA_{i}" for i in range(1, 18)]
    for i in range(5000):
        nom = random.choice(noms)
        tipus = "regular" if random.random() < 0.9 else "especial"
        codi = f"ACT_{i:05d}"
        sala_codi = random.choice(sales)
        sala_nom = f"Sala {sala_codi.split('_')[1]}"
        h = random.choice([7, 8, 9, 10, 17, 18, 19, 20])
        places = random.randint(15, 40)
        if random.random() < 0.04:
            inscrites = random.randint(places + 1, places + 5)
        else:
            inscrites = random.randint(0, places)
        pct = round(inscrites / places * 100, 1)
        over = "Sí" if inscrites > places else "No"
        inscripcio = date(2026, random.randint(3, 9), random.randint(1, 28))
        rows.append({
            "Nom de l'activitat": nom,
            "Tipus d'activitat (regular o especial)": tipus,
            "Codi de l'activitat": codi,
            "Sala on es fa": sala_nom,
            "Codi de l'espai": sala_codi,
            "Hora d'inici": f"{h:02d}:00",
            "Hora de finalització": f"{h:02d}:50",
            "Places de la classe": places,
            "Persones inscrites a la classe": inscrites,
            "Percentatge d'ocupació de la classe": pct,
            "Més inscrits que places": over,
            "Data d'inscripció (no és el dia de la classe)": inscripcio.isoformat(),
        })
    return pd.DataFrame(rows, columns=C.COLS_ACTIVITATS)


# ----------------------------------------------------------- Franges
def make_franges(reserves: pd.DataFrame) -> pd.DataFrame:
    g = (
        reserves.groupby(
            ["Data d'ús de la reserva", "Dia de la setmana", "Mes (número)",
             "Hora d'inici", "Codi de l'espai"],
            dropna=False,
        )
        .size()
        .reset_index(name="Recompte")
    )
    return g


# ----------------------------------------------------------- Horari + Fonts
def make_horari() -> pd.DataFrame:
    rows = [
        (dia, f"{C.HORARI[dia][0]:%H:%M}", f"{C.HORARI[dia][1]:%H:%M}")
        for dia in C.DIES
    ]
    return pd.DataFrame(rows, columns=["Dia de la setmana", "Obertura", "Tancament"])


def make_fonts() -> pd.DataFrame:
    rows = [
        ("Reserves", "reserves_2026.xlsx · full · 2026-04-01 → 2026-10-31"),
        ("Activitats dirigides", "activitats_2026.xlsx · full · inscripcions"),
        ("Espais", "inventari_espais.xlsx · full · 41 espais"),
        ("Recursos", "recursos.xlsx · mapping raw → codi"),
        ("Horari", "horari_saf.xlsx · 7 dies"),
        ("Reserves per franja", "agregat de Reserves per hora"),
        ("Fonts", "aquesta taula"),
        ("Notes", "dades sintètiques generades per a demo"),
    ]
    return pd.DataFrame(rows, columns=["Font", "Descripció"])


# ----------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="Sobreescriu si ja existeix")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"Ja existeix {out}. Fes servir --force per sobreescriure.")
        return

    print("Generant Espais…")
    espais = make_espais()
    print("Generant Recursos…")
    recursos = make_recursos(espais)
    print("Generant Reserves…")
    reserves = make_reserves(espais)
    print("Generant Activitats dirigides…")
    activitats = make_activitats()
    print("Generant Reserves per franja…")
    franges = make_franges(reserves)
    print("Generant Horari i Fonts…")
    horari = make_horari()
    fonts = make_fonts()

    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        reserves.to_excel(w, sheet_name="Reserves", index=False)
        activitats.to_excel(w, sheet_name="Activitats dirigides", index=False)
        espais.to_excel(w, sheet_name="Espais", index=False)
        recursos.to_excel(w, sheet_name="Recursos", index=False)
        franges.to_excel(w, sheet_name="Reserves per franja", index=False)
        horari.to_excel(w, sheet_name="Horari", index=False)
        fonts.to_excel(w, sheet_name="Fonts", index=False)

    print(f"\nFet. Escrit a {out}")
    print(f"  · Reserves:    {len(reserves):>7,} files")
    print(f"  · Activitats:  {len(activitats):>7,} files")
    print(f"  · Espais:      {len(espais):>7,} files")
    print(f"  · Recursos:    {len(recursos):>7,} files")
    print(f"  · Franges:     {len(franges):>7,} files")


if __name__ == "__main__":
    main()
