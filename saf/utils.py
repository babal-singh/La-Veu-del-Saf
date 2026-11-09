"""Utilitats pures: normalització, format català, parsing d'hores i números."""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import time
from typing import Iterable


# ---------------------------------------------------------------- text
def normalitza(text) -> str:
    """Minúscules, sense accents, sense puntuació redundant."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("·", " ").replace("’", "'")
    s = re.sub(r"[^a-z0-9:' ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- format
def fmt_num(x, decimals: int = 0) -> str:
    """1.234,5 — format català. None/NaN → 'n/d'."""
    if x is None:
        return "n/d"
    try:
        if isinstance(x, float) and math.isnan(x):
            return "n/d"
    except TypeError:
        pass
    s = f"{float(x):,.{decimals}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_valor(x, decimals: int = 1) -> str:
    """Com fmt_num però sense forçar decimals si el valor és enter."""
    if x is None:
        return "n/d"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/d"
    if v == int(v):
        return fmt_num(v, 0)
    return fmt_num(v, decimals)


def fmt_pct(x, decimals: int = 1) -> str:
    return f"{fmt_num(x, decimals)} %"


def minuts_a_hhmm(m: float) -> str:
    m = int(round(m))
    return f"{m // 60:02d}:{m % 60:02d}"


# ---------------------------------------------------------------- hores
def hora_en_minuts(hora) -> int | None:
    """'18:00' | '18h' | '18' | '9.30' | time(18,0) → minuts des de mitjanit."""
    if hora is None:
        return None
    if isinstance(hora, time):
        return hora.hour * 60 + hora.minute
    if isinstance(hora, (int, float)) and not isinstance(hora, bool):
        v = float(hora)
        return int(v * 60) if v <= 24 else int(v)
    m = re.search(r"(\d{1,2})\s*[:.h ]\s*(\d{2})?", str(hora).strip())
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2)) if m.group(2) else 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h * 60 + mi


# ---------------------------------------------------------------- números
_NUM_TOKEN = re.compile(r"\d[\d.,]*\d|\d")


def _parse_num(tok: str) -> float | None:
    """Parseja un token numèric (català o anglès)."""
    if not tok:
        return None
    tok = tok.strip(".,")
    if not tok:
        return None
    has_comma = "," in tok
    has_dot = "." in tok
    try:
        if has_comma and has_dot:
            if tok.rfind(",") > tok.rfind("."):
                return float(tok.replace(".", "").replace(",", "."))
            return float(tok.replace(",", ""))
        if has_comma:
            parts = tok.split(",")
            if (len(parts) == 2 and len(parts[1]) == 3
                    and parts[0].isdigit() and len(parts[0]) <= 3 and parts[0] != "0"):
                # ambigu: preferim decimal català
                return float(tok.replace(",", "."))
            return float(tok.replace(",", "."))
        if has_dot:
            parts = tok.split(".")
            if (len(parts) == 2 and len(parts[1]) == 3
                    and parts[0].isdigit() and len(parts[0]) <= 3 and parts[0] != "0"):
                # 1.234 → 1234 (milers català)
                return float(tok.replace(".", ""))
            return float(tok)
        return float(tok)
    except ValueError:
        return None


def xifres_en_text(text: str) -> set[float]:
    """Conjunt de valors numèrics d'un text (normalitzats a float)."""
    out: set[float] = set()
    for tok in _NUM_TOKEN.findall(text or ""):
        v = _parse_num(tok)
        if v is not None:
            out.add(round(v, 6))
    return out


def afegeix_enters(valors: Iterable[float]) -> set[float]:
    """Amplia el conjunt permès amb la part entera de cada valor."""
    out = set(valors)
    for v in valors:
        try:
            out.add(float(int(v)))
        except (ValueError, OverflowError):
            continue
    return out
