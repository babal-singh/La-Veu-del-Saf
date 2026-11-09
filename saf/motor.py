"""Motor: pregunta → resposta traçable. El LLM mai toca les dades."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from . import config as C
from .data import SafData
from .llm import BaseLLM, get_llm
from .router import planifica, reformula
from .tools import Resultat, executa
from .utils import afegeix_enters, xifres_en_text


@dataclass
class Resposta:
    text: str
    tool: str | None
    args: dict
    via: str
    fonts: list[str] = field(default_factory=list)
    taula: pd.DataFrame | None = None
    reformulat: bool = False
    rebutjat: bool = False
    ok: bool = True


class Motor:
    def __init__(self, dades: SafData, llm: BaseLLM | None = None,
                 avui: date | None = None):
        self.d = dades
        self.llm = llm or get_llm()
        self.avui = avui or C.DATA_FI

    # ----------------------------------------------------- guard de xifres
    @staticmethod
    def _guard(text_llm: str, permesos: set[float]) -> bool:
        """True si el text reformulat no introdueix cap xifra nova."""
        permesos = afegeix_enters(permesos)
        noves = xifres_en_text(text_llm) - permesos
        return not noves

    # ------------------------------------------------------------ resposta
    def respon(self, pregunta: str) -> Resposta:
        tool, args, via = planifica(pregunta, self.d, self.llm, self.avui)

        if tool is None:
            return Resposta(
                text=(
                    "No ho sé. No he pogut identificar cap consulta sobre horaris, "
                    "aforaments, ocupació, disponibilitat o activitats dirigides del SAF "
                    f"amb les dades disponibles ({C.DATA_INICI} → {C.DATA_FI}). "
                    "Prova, per exemple: «Quina ocupació té el fitness els dimecres "
                    "a les 18:00?»"
                ),
                tool=None, args={}, via="cap", ok=False,
                fonts=[f"Abast: {C.DATA_INICI} → {C.DATA_FI}"],
            )

        res: Resultat = executa(tool, args, self.d)
        base = res.text

        if not res.ok:
            return Resposta(base, tool, args, via, res.fonts, res.taula, ok=False)

        # ---- reformulació opcional, sempre sotmesa al guard
        reformulat, rebutjat = False, False
        if self.llm.available():
            cand = reformula(base, self.llm)
            if cand and cand != base and self._guard(cand, res.xifres()):
                base = cand
                reformulat = True
            elif cand and cand != base:
                rebutjat = True

        return Resposta(
            base, tool, args, via, res.fonts, res.taula,
            reformulat=reformulat, rebutjat=rebutjat, ok=True,
        )
