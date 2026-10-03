"""Thin client for an OpenAI-compatible gateway, with an audit trail of every call."""

from __future__ import annotations

import json
import re
import time
from typing import Protocol

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AgentCall


class LLMError(RuntimeError):
    pass


class JSONCompleter(Protocol):
    model: str

    def complete_json(self, system: str, user: str) -> dict: ...


class OpenAIGatewayClient:
    def __init__(self) -> None:
        from openai import OpenAI

        s = get_settings()
        if not s.llm_configured:
            raise LLMError("OPENAI_API_KEY is not set; configure the OpenAI gateway in .env")
        headers = json.loads(s.openai_default_headers) if s.openai_default_headers.strip() else None
        self._client = OpenAI(
            api_key=s.openai_api_key,
            base_url=s.openai_base_url or None,
            default_headers=headers,
            timeout=s.openai_timeout_seconds,
        )
        self.model = s.openai_model
        self._temperature = s.temperature
        self._json_mode = True

    def complete_json(self, system: str, user: str) -> dict:
        from openai import BadRequestError

        kwargs: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        if self._json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except BadRequestError as exc:
            # Some gateways/models reject response_format or temperature; retry plainly once.
            if "response_format" in kwargs or "temperature" in kwargs:
                kwargs.pop("response_format", None)
                kwargs.pop("temperature", None)
                self._json_mode = False
                resp = self._client.chat.completions.create(**kwargs)
            else:
                raise LLMError(str(exc)) from exc
        content = resp.choices[0].message.content or ""
        return parse_json(content)


def parse_json(content: str) -> dict:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("model did not return a JSON object")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"model returned invalid JSON: {exc}") from exc


_override: JSONCompleter | None = None


def set_llm_override(client: JSONCompleter | None) -> None:
    """Used by tests to substitute a fake model."""
    global _override
    _override = client


def get_llm() -> JSONCompleter:
    return _override or OpenAIGatewayClient()


def audited_call(db: Session, llm: JSONCompleter, purpose: str, system: str, user: str) -> dict:
    started = time.perf_counter()
    record = AgentCall(purpose=purpose, model=llm.model, request={"system": system, "user": user})
    try:
        result = llm.complete_json(system, user)
        record.response = json.dumps(result)
        return result
    except Exception as exc:
        record.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        record.duration_ms = int((time.perf_counter() - started) * 1000)
        db.add(record)
        db.commit()
