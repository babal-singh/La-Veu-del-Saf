"""python -m saf.cli "Quina ocupació té el fitness a les 18:00?" """
from __future__ import annotations

import sys

from .data import carrega
from .motor import Motor


def main() -> None:
    if len(sys.argv) < 2:
        print('Ús: python -m saf.cli "la teva pregunta"')
        raise SystemExit(1)
    d = carrega()
    m = Motor(d)
    r = m.respon(" ".join(sys.argv[1:]))
    print(f"\n>> {r.text}\n")
    print(f"[tool={r.tool} via={r.via} reformulat={r.reformulat} rebutjat={r.rebutjat}]")
    for f in r.fonts:
        print(f"  · font: {f}")
    if r.taula is not None and not r.taula.empty:
        print(r.taula.head(12).to_string(index=False))


if __name__ == "__main__":
    main()
