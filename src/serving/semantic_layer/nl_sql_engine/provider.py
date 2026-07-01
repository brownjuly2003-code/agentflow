"""LLM provider protocol + the GraceKelly Sonnet-5 provider.

Vendored from the NL_SQL portfolio engine (``nl_sql.llm.providers.base`` +
``nl_sql.llm.providers.gracekelly``) for AgentFlow ADR 0008. AgentFlow routes
NL->SQL generation through **Claude Sonnet 5 via GraceKelly**, never Mistral and
never a direct model SDK: GraceKelly owns model selection/execution behind its
``/api/v1/orchestrate`` endpoint (ADR 0006 §Decision — "no direct model SDK in
AgentFlow").

Transport is ``httpx`` — AgentFlow's standard HTTP client (a core dependency,
and the same one ``nl_engine._llm_translate`` already uses for this exact
GraceKelly call). Latency is ~20-40s per call over the browser path, so this
provider serves evaluation runs and one-off probes, not an interactive surface.
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

import httpx
from pydantic import BaseModel

from src.serving.semantic_layer.nl_sql_engine._sql_envelope import strip_ansi, unwrap_sql_json


class GenerateRequest(BaseModel):
    prompt: str
    system: str | None = None
    temperature: float = 0.0
    max_tokens: int = 2048


class GenerateResponse(BaseModel):
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class ProviderError(RuntimeError):
    """Raised when a provider call fails for a reason we surface to the caller."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, req: GenerateRequest) -> GenerateResponse: ...


class GraceKellyProvider:
    """LLMProvider that proxies generate() to a local GraceKelly orchestrate API.

    Posts to ``${base_url}/api/v1/orchestrate`` with ``{prompt, model}`` and reads
    ``output_text`` — the contract AgentFlow's serving layer already standardised
    on. The default model ``claude-sonnet-5`` resolves through GraceKelly's live
    catalog to "Claude Sonnet 5.0".
    """

    name: str = "gracekelly"

    def __init__(
        self,
        *,
        model: str = "claude-sonnet-5",
        base_url: str = "http://127.0.0.1:8011",
        timeout_seconds: float = 180.0,
    ) -> None:
        if not model.strip():
            raise ProviderError("GraceKellyProvider requires non-empty model")
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def generate(self, req: GenerateRequest) -> GenerateResponse:
        prompt = req.prompt
        if req.system:
            prompt = f"{req.system}\n\n{prompt}"

        t0 = time.perf_counter()
        try:
            response = httpx.post(
                f"{self._base_url}/api/v1/orchestrate",
                json={"prompt": prompt, "model": self.model},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"GraceKelly /api/v1/orchestrate returned {exc.response.status_code}: "
                f"{exc.response.text[:400]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"GraceKelly unreachable at {self._base_url}: {exc!r}. "
                "Start it with `python -m uvicorn gracekelly.main:create_app "
                "--factory --host 127.0.0.1 --port 8011`."
            ) from exc

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        try:
            parsed = response.json()
        except ValueError as exc:
            raise ProviderError("GraceKelly returned a non-JSON body") from exc

        failure = parsed.get("failure_message") or parsed.get("failure_code")
        if failure and not parsed.get("output_text"):
            raise ProviderError(f"GraceKelly orchestrate failed: {failure}")

        answer = strip_ansi(str(parsed.get("output_text") or ""))
        answer = unwrap_sql_json(answer)

        model_field = parsed.get("model")
        model_id = model_field.get("id") if isinstance(model_field, dict) else model_field
        # Browser path does not surface token counts; use a word-count proxy so
        # eval reports show something plausible without faking billing units.
        approx_in = max(1, len(prompt.split()))
        approx_out = max(1, len(answer.split()))
        return GenerateResponse(
            text=answer,
            model=str(model_id or self.model),
            input_tokens=approx_in,
            output_tokens=approx_out,
            latency_ms=elapsed_ms,
        )
