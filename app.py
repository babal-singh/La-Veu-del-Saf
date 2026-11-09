"""Pregunta-li al SAF — interfície de xat (Streamlit)."""
from __future__ import annotations

import json
import os

import streamlit as st

from saf import config as C
from saf.data import carrega
from saf.llm import get_llm
from saf.motor import Motor

st.set_page_config(
    page_title="Pregunta-li al SAF · UAB The Hack! 2026",
    page_icon="🏃",
    layout="wide",
)

EXEMPLES = [
    "Quin horari té el SAF el diumenge?",
    "Quina ocupació té el fitness els dimecres a les 18:00?",
    "A quina hora hi ha menys gent al fitness?",
    "El 12 de maig, quines franges estan lliures al tennis?",
    "Quantes reserves hi ha hagut a la piscina l'octubre?",
    "Compara les reserves del fitness a l'agost i a l'octubre",
    "Quines activitats dirigides tenen menys ocupació?",
    "Quines classes de zumba hi ha el 12 de maig?",
]


# ------------------------------------------------------------------ càrrega
@st.cache_resource(show_spinner="Carregant el dataset SAF…")
def _dades():
    return carrega()


@st.cache_resource(show_spinner="Inicialitzant el motor…")
def _motor():
    return Motor(_dades(), get_llm())


d = _dades()
motor = _motor()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("🏃 Pregunta-li al SAF")
    st.caption("Servei d'Activitat Física · UAB · 40è aniversari")

    if motor.llm.available():
        st.markdown(f"**Model:** {motor.llm.name}")
        st.markdown("**Estat:** 🟢 LLM actiu (function calling)")
    else:
        st.markdown("**Model:** cap")
        st.markdown("**Estat:** 🟡 mode regles (sense `UTH_KEY`)")
        st.caption("Exporta `UTH_KEY=uth-...` i reinicia per activar l'ornith del DCC UAB.")

    st.divider()
    st.markdown("**Dataset**")
    st.markdown(
        f"- Reserves: **{len(d.reserves):,}** files\n"
        f"- Activitats dirigides: **{len(d.activitats):,}** files\n"
        f"- Espais: **{len(d.espais)}**\n"
        f"- Recursos: **{len(d.recursos)}**\n"
        f"- Franges: **{len(d.franges):,}**\n"
        f"- Període: **{C.DATA_INICI} → {C.DATA_FI}**"
    )

    st.divider()
    avui = st.date_input(
        "Data de referència per a «ara» / «avui»",
        value=C.DATA_FI,
        min_value=C.DATA_INICI,
        max_value=C.DATA_FI,
    )
    motor.avui = avui

    st.divider()
    st.markdown("**Preguntes d'exemple**")
    for q in EXEMPLES:
        if st.button(q, use_container_width=True, key=f"ex_{hash(q)}"):
            st.session_state["_pendent"] = q

    st.divider()
    if st.button("Esborra la conversa", use_container_width=True):
        st.session_state.missatges = []
        st.rerun()

    with st.expander("Configuració del model"):
        st.code(
            f"SAF_LLM={os.getenv('SAF_LLM', 'auto')}\n"
            f"UTH_BASE_URL={os.getenv('UTH_BASE_URL', 'https://dcc-llm-gw.uab.cat/uabthehack/v1')}\n"
            f"UTH_MODEL={os.getenv('UTH_MODEL', 'ornith')}\n"
            f"UTH_KEY={'✓ definit' if os.getenv('UTH_KEY') else '✗ no definit'}\n"
            f"SAF_XLSX={os.getenv('SAF_XLSX', str(C.SAF_XLSX))}",
            language="bash",
        )

# ------------------------------------------------------------------ xat
st.title("Pregunta-li al SAF")
st.caption(
    "Consultes sobre horaris, aforaments, ocupació i franges de baixa afluència. "
    "Totes les xifres provenen del dataset operatiu del SAF (2026-04-01 → 2026-10-31)."
)

if "missatges" not in st.session_state:
    st.session_state.missatges = []

for msg in st.session_state.missatges:
    with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "🏃"):
        st.markdown(msg["content"])
        if msg.get("meta"):
            m = msg["meta"]
            with st.expander("🔎 Traçabilitat de la resposta"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Eina", m["tool"] or "—")
                c2.metric("Via de planificació", m["via"])
                c3.metric(
                    "Reformulació LLM",
                    "sí" if m["reformulat"] else ("rebutjada" if m["rebutjat"] else "no"),
                )
                st.code(m["args_pretty"], language="json")
                st.markdown("**Fonts citades**")
                for f in m["fonts"]:
                    st.markdown(f"- {f}")
                if m.get("taula") is not None and not m["taula"].empty:
                    st.dataframe(m["taula"], use_container_width=True)

entrada = st.chat_input("Escriu la teva pregunta sobre el SAF…")
if st.session_state.get("_pendent"):
    entrada = st.session_state.pop("_pendent")

if entrada:
    st.session_state.missatges.append({"role": "user", "content": entrada})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(entrada)

    with st.chat_message("assistant", avatar="🏃"):
        with st.spinner("Consultant el dataset…"):
            r = motor.respon(entrada)
        st.markdown(r.text)
        with st.expander("🔎 Traçabilitat de la resposta"):
            c1, c2, c3 = st.columns(3)
            c1.metric("Eina", r.tool or "—")
            c2.metric("Via de planificació", r.via)
            c3.metric(
                "Reformulació LLM",
                "sí" if r.reformulat else ("rebutjada" if r.rebutjat else "no"),
            )
            st.code(json.dumps(r.args, ensure_ascii=False, indent=2), language="json")
            st.markdown("**Fonts citades**")
            for f in r.fonts:
                st.markdown(f"- {f}")
            if r.taula is not None and not r.taula.empty:
                st.dataframe(r.taula, use_container_width=True)

    st.session_state.missatges.append(
        {
            "role": "assistant",
            "content": r.text,
            "meta": {
                "tool": r.tool,
                "via": r.via,
                "reformulat": r.reformulat,
                "rebutjat": r.rebutjat,
                "fonts": r.fonts,
                "taula": r.taula,
                "args_pretty": json.dumps(r.args, ensure_ascii=False, indent=2),
            },
        }
    )
