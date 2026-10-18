"""ModelPort (ADR-0003): the only way research code calls a language model.

- ``FakeModelPort``: deterministic, offline. Builds claims by quoting evidence sentences that
  mention the section's keywords. Used by every development test (brief: mock providers for
  deterministic tests). Its reports are labelled with the model name ``fake-deterministic``.
- ``GeminiModelPort``: google-genai with a JSON response schema, temperature 0, a timeout and
  bounded retries for transient errors only. The model id must be configured explicitly.
"""

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from arthalens_ai.research.contracts import (
    ClaimType,
    DraftCitation,
    DraftClaim,
    PlannedPassage,
    SectionDraft,
)

logger = logging.getLogger(__name__)


class ModelError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code  # timeout | invalid_output | provider_error | budget | not_configured


@dataclass(frozen=True)
class PriorClaim:
    """A claim from another section, offered to the summary."""

    section: str
    text: str
    citations: tuple[DraftCitation, ...]


@dataclass(frozen=True)
class ModelRequest:
    purpose: str  # section id, for logs and the fake
    system: str
    user: str  # rendered evidence block + task; data only
    claim_type: ClaimType
    keywords: tuple[str, ...] = ()
    passages: tuple[PlannedPassage, ...] = ()
    prior_claims: tuple[PriorClaim, ...] = ()
    max_output_tokens: int = 4096
    timeout_s: float = 120.0


@dataclass(frozen=True)
class ModelResult:
    draft: SectionDraft
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    # Only when prices are configured; never a guessed cost.
    estimated_cost_usd: float | None = None


class ModelPort(Protocol):
    provider: str
    model: str

    async def generate(self, request: ModelRequest) -> ModelResult: ...


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# --- Fake ---------------------------------------------------------------------------------

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class FakeModelPort:
    """Deterministic stand-in. ``fail`` maps a purpose to an error code to simulate."""

    fail: dict[str, str] = field(default_factory=dict)
    max_claims: int = 6
    delay_s: float = 0.0
    provider: str = "fake"
    model: str = "fake-deterministic"

    async def generate(self, request: ModelRequest) -> ModelResult:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if request.purpose in self.fail:
            code = self.fail[request.purpose]
            raise ModelError(code, f"simulated {code} for section {request.purpose}")
        draft = self._summary(request) if request.prior_claims else self._extract(request)
        return self._result(request, draft)

    def _extract(self, request: ModelRequest) -> SectionDraft:
        patterns = [re.compile(rf"\b{re.escape(k)}", re.IGNORECASE) for k in request.keywords]
        claims: list[DraftClaim] = []
        for p in request.passages:
            for sentence in _SENTENCE.split(p.text):
                s = " ".join(sentence.split())
                if len(s) < 25 or len(s) > 900 or not any(pt.search(s) for pt in patterns):
                    continue
                if s.upper().startswith("SYNTHETIC TEST DOCUMENT"):
                    continue
                claims.append(
                    DraftClaim(
                        text=s,
                        claim_type=request.claim_type,
                        citations=[DraftCitation(label=p.label, quote=s)],
                    )
                )
                if len(claims) >= self.max_claims:
                    return SectionDraft(claims=claims, missing=[])
        missing = [] if claims else ["No sentence in the evidence addresses this section."]
        return SectionDraft(claims=claims, missing=missing)

    def _summary(self, request: ModelRequest) -> SectionDraft:
        firsts: dict[str, PriorClaim] = {}
        for c in request.prior_claims:
            firsts.setdefault(c.section, c)
        claims = [
            DraftClaim(
                text=f"Section {section}: {c.text}",
                claim_type="summary",
                citations=list(c.citations[:1]),
            )
            for section, c in sorted(firsts.items())
        ]
        return SectionDraft(claims=claims, missing=[])

    def _result(self, request: ModelRequest, draft: SectionDraft) -> ModelResult:
        return ModelResult(
            draft=draft,
            model=self.model,
            provider=self.provider,
            input_tokens=estimate_tokens(request.system + request.user),
            output_tokens=estimate_tokens(draft.model_dump_json()),
            latency_ms=0,
        )


# --- Gemini -------------------------------------------------------------------------------

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass
class GeminiModelPort:
    api_key: str
    model: str
    # USD per million tokens (input, output), from configuration. None: cost not estimated.
    prices_per_mtok: tuple[float, float] | None = None
    max_retries: int = 2
    base_backoff_s: float = 1.0
    provider: str = "gemini"

    def __post_init__(self) -> None:
        if not self.model:
            raise ModelError("not_configured", "GEMINI_MODEL must be set explicitly")
        from google import genai

        self._client = genai.Client(api_key=self.api_key)

    async def generate(self, request: ModelRequest) -> ModelResult:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=request.system,
            response_mime_type="application/json",
            response_schema=SectionDraft,
            temperature=0.0,
            max_output_tokens=request.max_output_tokens,
        )
        attempt = 0
        while True:
            started = time.monotonic()
            try:
                async with asyncio.timeout(request.timeout_s):
                    response = await self._client.aio.models.generate_content(
                        model=self.model, contents=request.user, config=config
                    )
                break
            except TimeoutError as exc:
                raise ModelError("timeout", f"no response within {request.timeout_s}s") from exc
            except errors.APIError as exc:
                retryable = getattr(exc, "code", None) in _RETRYABLE_STATUS
                if not retryable or attempt >= self.max_retries:
                    raise ModelError("provider_error", f"HTTP {getattr(exc, 'code', '?')}") from exc
                attempt += 1
                delay = self.base_backoff_s * 2 ** (attempt - 1) * (1 + random.random())  # noqa: S311
                logger.warning(
                    "gemini transient error %s; retry %d in %.1fs", exc.code, attempt, delay
                )
                await asyncio.sleep(delay)
        latency_ms = round((time.monotonic() - started) * 1000)
        draft = _parse(response.text or "")
        usage = response.usage_metadata
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        cost = None
        if self.prices_per_mtok:
            price_in, price_out = self.prices_per_mtok
            cost = round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 6)
        return ModelResult(
            draft=draft,
            model=self.model,
            provider=self.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=cost,
        )


def _parse(text: str) -> SectionDraft:
    """Model output is untrusted (T-37): it must match the schema exactly."""
    try:
        return SectionDraft.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ModelError(
            "invalid_output", "response did not match the SectionDraft schema"
        ) from exc
