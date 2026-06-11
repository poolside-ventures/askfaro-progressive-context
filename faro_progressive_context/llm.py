"""LLM client — bring-your-own OpenAI-compatible endpoint.

The package never hardcodes a provider or model id; the caller supplies the
endpoint + model. Descriptor generation is a server-side batch step, so a
strong-but-efficient "Flash-class" model is the intended tier — but that is a
deployment choice, expressed entirely through config, not baked in here.
"""

from __future__ import annotations

import json
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, prompt: str, *, system: str | None = None) -> str:
        ...


class OpenAICompatibleClient:
    """Minimal /chat/completions client. Requires the `llm` extra (httpx)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        temperature: float = 0.0,
        timeout: float = 120.0,
        max_retries: int = 3,
        max_tokens: int | None = 4096,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens

    def complete(self, prompt: str, *, system: str | None = None, response_format: dict | None = None) -> str:
        try:
            import httpx  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "OpenAICompatibleClient needs httpx. Install the 'llm' extra: "
                "pip install 'faro-progressive-context[llm]'"
            ) from exc
        if not self.api_key:
            raise RuntimeError(
                "no API key — pass api_key to OpenAICompatibleClient (e.g. from your provider's "
                "key env var). The build cannot call the model without it."
            )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body: dict = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if self.max_tokens:
            body["max_tokens"] = self.max_tokens
        if response_format:
            body["response_format"] = response_format

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise  # client errors won't fix themselves
        raise RuntimeError(f"LLM call failed after {self.max_retries} attempts: {last_exc}") from last_exc


def _first_json_object(text: str) -> str | None:
    """Return the first balanced {...} object, ignoring braces inside strings.
    Handles replies with leading prose or trailing 'Extra data'."""
    depth = 0
    start = None
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return text[start : i + 1]
    return None


def parse_json_object(raw: str) -> dict:
    """Best-effort extraction of a JSON object from a model reply (handles
    ```json fences, leading prose, and trailing 'Extra data')."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass
    obj = _first_json_object(text)
    if obj is not None:
        import re

        return json.loads(re.sub(r"[\x00-\x1f]+", " ", obj), strict=False)
    raise json.JSONDecodeError("no JSON object found", text, 0)
