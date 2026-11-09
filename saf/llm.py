"""Client del LLM del DCC UAB (ornith). Degradació elegant si no hi ha clau."""
from __future__ import annotations

import json
import os
from typing import Any


class BaseLLM:
    """Interfície comuna. Si `available()` és False, el motor va en mode regles."""

    name = "cap"

    def available(self) -> bool:
        return False

    def complete(self, prompt: str, max_tokens: int = 2048,
                 json_mode: bool = False, disable_thinking: bool = False) -> str:
        return ""

    def chat_tools(self, messages: list[dict], tools: list[dict],
                   disable_thinking: bool = True) -> Any:
        return None

    @staticmethod
    def extreu_json(text: str) -> dict | None:
        """Retorna el primer objecte JSON equilibrat del text, o None."""
        if not text:
            return None
        inici = text.find("{")
        while inici != -1:
            depth = 0
            for i, ch in enumerate(text[inici:], start=inici):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[inici:i + 1])
                            if isinstance(obj, dict):
                                return obj
                        except json.JSONDecodeError:
                            break
            inici = text.find("{", inici + 1)
        return None


class DCCLLM(BaseLLM):
    """Model `ornith` servit a https://dcc-llm-gw.uab.cat/uabthehack/v1.

    Requereix `UTH_KEY` (clau de l'equip, comença per uth-). L'API és compatible
    amb OpenAI, així que fem servir el SDK oficial.
    """

    name = "ornith (DCC UAB)"

    def __init__(self):
        self.key = (os.getenv("UTH_KEY") or "").strip()
        self.base_url = os.getenv(
            "UTH_BASE_URL", "https://dcc-llm-gw.uab.cat/uabthehack/v1"
        ).rstrip("/")
        self.model = os.getenv("UTH_MODEL", "ornith")
        self._client = None

    def available(self) -> bool:
        return bool(self.key)

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(base_url=self.base_url, api_key=self.key)
        return self._client

    def complete(self, prompt: str, max_tokens: int = 2048,
                 json_mode: bool = False, disable_thinking: bool = False) -> str:
        if not self.available():
            return ""
        try:
            client = self._get_client()
            kwargs: dict = dict(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                # El PDF avisa: max_tokens petit → resposta buida perquè el model raona.
                max_tokens=max_tokens,
            )
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if disable_thinking:
                kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            r = client.chat.completions.create(**kwargs)
            return (r.choices[0].message.content or "").strip()
        except Exception:                                       # noqa: BLE001
            return ""

    def chat_tools(self, messages: list[dict], tools: list[dict],
                   disable_thinking: bool = True) -> Any:
        """Function calling natiu amb l'esquema OpenAI."""
        if not self.available():
            return None
        try:
            client = self._get_client()
            kwargs: dict = dict(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=2048,
            )
            if disable_thinking:
                kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            return client.chat.completions.create(**kwargs)
        except Exception:                                       # noqa: BLE001
            return None


class NullLLM(BaseLLM):
    name = "mode regles (sense LLM)"


def get_llm() -> BaseLLM:
    """Selecció per variable d'entorn SAF_LLM = auto | none | regles."""
    mode = (os.getenv("SAF_LLM") or "auto").lower()
    if mode in ("none", "regles", "rules"):
        return NullLLM()
    m = DCCLLM()
    return m if m.available() else NullLLM()
