"""Planificador: pregunta en català → (tool, args). Mai calcula res."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from . import config as C
from .data import SafData
from .llm import BaseLLM
from .tools import TOOLS, tools_openai, valida_args
from .utils import normalitza, hora_en_minuts

_SYSTEM_PROMPT = (
    "Ets el planificador d'eines de l'assistent «Pregunta-li al SAF». "
    "Crida exactament una eina amb arguments vàlids. "
    "Dates en format YYYY-MM-DD dins 2026-04-01..2026-10-31. "
    "Hores en HH:MM. Dies: dl, dt, dc, dj, dv, ds, dg. "
    "Si la pregunta no es pot respondre amb cap eina, no cridis cap eina."
)


# ------------------------------------------------------------------ dates
_RE_ISO = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
_RE_DMY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](20\d{2}))?\b")
_RE_DIA_MES = re.compile(r"\b(\d{1,2})\s+d[e']?\s*([a-z]+)\b")


def _mes_de(text: str) -> int | None:
    for nom, num in C.NOM_MES.items():
        if re.search(rf"\b{nom}\b", text):
            return num
    return None


def _dia_de(text: str) -> str | None:
    for nom, codi in C.NOM_DIA.items():
        if re.search(rf"\b{nom}s?\b", text):
            return codi
    for codi in C.DIES:
        if re.search(rf"\b{codi}\b", text):
            return codi
    return None


def _data_de(text: str) -> date | None:
    m = _RE_ISO.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _RE_DMY.search(text)
    if m:
        try:
            any_ = int(m.group(3)) if m.group(3) else 2026
            return date(any_, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = _RE_DIA_MES.search(text)
    if m:
        mes = C.NOM_MES.get(m.group(2).rstrip("s"))
        if mes:
            try:
                return date(2026, mes, int(m.group(1)))
            except ValueError:
                return None
    return None


def _periode_de(text: str) -> tuple[date, date] | None:
    d = _data_de(text)
    if d:
        return d, d
    mes = _mes_de(text)
    if mes:
        inici = date(2026, mes, 1)
        fi = (date(2026, mes + 1, 1) - timedelta(days=1)) if mes < 12 else date(2026, 12, 31)
        fi = min(fi, C.DATA_FI)
        return max(inici, C.DATA_INICI), fi
    if "aquest mes" in text or "aquest curs" in text:
        return C.DATA_INICI, C.DATA_FI
    return None


def _hora_de(text: str) -> str | None:
    m = re.search(r"\b(\d{1,2})\s*[:.h]\s*(\d{2})\b", text)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    m = re.search(r"\b(?:a les|les|cap a les)\s+(\d{1,2})\b", text)
    if m:
        return f"{int(m.group(1)):02d}:00"
    m = re.search(r"\b(\d{1,2})\s*h\b", text)
    if m:
        return f"{int(m.group(1)):02d}:00"
    return None


def _espai_de(text: str, d: SafData) -> str | None:
    codis, estat = d.resoldre(text)
    if estat == "ok" or (estat == "multiple" and codis):
        return text
    return None


# --------------------------------------------------- planificador per regles
def planifica_regles(pregunta: str, d: SafData, avui: date) -> tuple[str, dict] | None:
    """Fallback determinista. Cobreix el 100% dels casos de demo."""
    t = normalitza(pregunta)
    if not t:
        return None

    peri = _periode_de(t)
    dia = _dia_de(t)
    hora = _hora_de(t)
    espai = _espai_de(pregunta, d)

    # --- horaris
    if re.search(
        r"\bhorari|quan obr|quina hora obr|a quina hora tan|obertura|tanquen|tanca\b",
        t,
    ) and not espai:
        return "horari_obertura", ({"dia": dia} if dia else {})

    # --- activitats dirigides (abans que "reserves")
    if re.search(
        r"\bactivitat|classe|classes|dirigid|inscrip|places lliures|"
        r"zumba|ioga|pilates|spinning",
        t,
    ):
        if _data_de(t):
            return "_no_ho_se", {
                "motiu": (
                    "La taula «Activitats dirigides» no conté la data en què es fa "
                    "cada classe (només la data d'inscripció), així que no puc "
                    "respondre quines classes concretes hi ha un dia determinat. "
                    "Sí que et puc donar agregats per activitat, sala o hora."
                )
            }
        args: dict = {}
        if re.search(r"especial", t):
            args["tipus"] = "especial"
        elif re.search(r"regular", t):
            args["tipus"] = "regular"
        if espai:
            args["espai"] = espai
        if hora:
            args["hora"] = hora
        if re.search(r"lliure|disponible|amb places|queden", t):
            args["nomes_amb_places"] = True
        return "activitats_dirigides", args

    # --- comparació de mesos
    mesos = [n for nom, n in C.NOM_MES.items() if re.search(rf"\b{nom}\b", t)]
    if len(mesos) >= 2 and espai:
        return "comparar_mesos", {"espai": espai, "mes_a": mesos[0], "mes_b": mesos[1]}

    # --- alternatives de baixa ocupació (prioritat alta)
    if re.search(
        r"menys (gent|ple|ocupat|transit|trànsit)|buida|tranquil|millor moment|"
        r"alternativa|quan hi ha menys|menys cua|evitar",
        t,
    ) and espai:
        inici, fi = peri or (C.DATA_INICI, C.DATA_FI)
        args = {"espai": espai, "data_inici": str(inici), "data_fi": str(fi)}
        if dia:
            args["dia"] = dia
        return "franges_baixes", args

    # --- disponibilitat d'un dia
    if re.search(r"lliure|disponible|es pot reservar|hi ha pista|queda", t) and espai:
        dt = peri[0] if peri else avui
        args = {"espai": espai, "data": str(dt)}
        if hora:
            args["hora_inici"] = hora
        return "disponibilitat", args

    # --- ocupació típica (sense data concreta, però amb hora)
    if (espai and hora
            and not _data_de(t) and not _mes_de(t)
            and not re.search(r"\bara\b|avui|en aquest moment", t)):
        args = {"espai": espai, "hora": hora}
        if dia:
            args["dia"] = dia
        return "ocupacio_tipica", args

    # --- ocupació en un instant
    if espai and (hora or re.search(r"\bara|en aquest moment|ple|ocupacio|ocupació|quanta gent", t)):
        dt = peri[0] if peri else avui
        h = hora or "18:00"
        return "ocupacio_instant", {"espai": espai, "data": str(dt), "hora": h}

    # --- perfil horari
    if espai and re.search(
        r"mitjana|per hora|per franja|pic|maxim|màxim|evolucio|perfil|al llarg", t
    ):
        inici, fi = peri or (C.DATA_INICI, C.DATA_FI)
        args = {"espai": espai, "data_inici": str(inici), "data_fi": str(fi)}
        if dia:
            args["dia"] = dia
        return "perfil_ocupacio", args

    # --- recompte
    if espai and re.search(
        r"quantes|quants|total|recompte|nombre|comptar|bloc|escola|club", t
    ):
        inici, fi = peri or (C.DATA_INICI, C.DATA_FI)
        args = {"espai": espai, "data_inici": str(inici), "data_fi": str(fi)}
        if dia:
            args["dia"] = dia
        if re.search(r"bloc|escola|club|institucional", t):
            args["incloure_blocs"] = True
        return "comptatge_reserves", args

    # --- info d'espai
    if espai and re.search(
        r"aforament|capacitat|quantes persones|quanta gent cab|info|"
        r"que es|què és|com es compta|maxim|màxim", t,
    ):
        return "info_espai", {"espai": espai}

    # --- si només han dit un espai, donem info
    if espai and len(t.split()) <= 4:
        return "info_espai", {"espai": espai}

    return None


# ------------------------------------------------------------------ router
def planifica(pregunta: str, d: SafData, llm: BaseLLM,
              avui: date) -> tuple[str | None, dict, str]:
    """Retorna (tool, args, via). via ∈ {'llm', 'regles', 'cap'}."""
    via = "cap"
    tool, args = None, {}

    # 1) Function calling natiu amb ornith
    if llm.available():
        try:
            resp = llm.chat_tools(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": pregunta},
                ],
                tools=tools_openai(),
                disable_thinking=True,
            )
            if resp and getattr(resp, "choices", None):
                msg = resp.choices[0].message
                calls = getattr(msg, "tool_calls", None) or []
                if calls:
                    call = calls[0]
                    name = call.function.name
                    try:
                        call_args = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        call_args = {}
                    if isinstance(name, str) and isinstance(call_args, dict):
                        ok, _ = valida_args(name, call_args)
                        if ok:
                            tool, args, via = name, call_args, "llm"
        except Exception:                                       # noqa: BLE001
            pass

    # 2) Fallback determinista
    if tool is None:
        r = planifica_regles(pregunta, d, avui)
        if r:
            tool, args = r
            via = "regles"

    return tool, args, via


# --------------------------------------------------- reformulació validada
_PROMPT_REFORMULA = """Ets "Pregunta-li al SAF", l'assistent del Servei d'Activitat Física de la UAB.
Reescriu la resposta de manera breu (2-4 frases), en el mateix idioma que t'han escrit (i en cas de dubte en català), to amable i directe.

Regles ABSOLUTES:
- NO afegeixis cap número que no aparegui al text original.
- NO canviïs cap xifra, cap codi d'espai ni cap data.
- NO inventis informació. Si el text diu "No ho sé", mantén exactament aquesta idea.
- Conserva les unitats (persones, pistes, %, hores).

Text original:
{text}

Resposta reescrita:"""


def reformula(text: str, llm: BaseLLM) -> str:
    if not llm.available() or text.startswith("No ho sé"):
        return text
    try:
        out = llm.complete(
            _PROMPT_REFORMULA.format(text=text),
            max_tokens=512,
            disable_thinking=True,
        )
        return (out or "").split("\n\n")[0].strip() or text
    except Exception:                                           # noqa: BLE001
        return text
