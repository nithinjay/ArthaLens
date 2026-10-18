"""Jio IPO exclusion matcher (ADR-0008).

Rules:              packages/policy/exclusions.v1.json
Expected behaviour: packages/policy/exclusion-vectors.v1.json

packages/policy/src/exclusion.ts implements the same algorithm; both must pass the same vectors.
Change the algorithm in both places at once.

Decisions fail closed: anything that merely *looks like* an excluded name is quarantined, which
blocks every workflow just like an exclusion does.
"""

import os
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Decision = Literal["allowed", "excluded", "quarantined"]
Reason = Literal["identifier", "token", "alias", "embedded", "confusable"]
Scope = Literal["ipo", "stock"]

_IDENTIFIER_KINDS = ("isin", "cin", "nse_symbol", "bse_code")

# Look-alike characters, applied only in the confusable pass (after lower-casing).
CONFUSABLES: dict[str, str] = {
    "0": "o",
    "1": "i",
    "l": "i",
    "|": "i",
    "!": "i",
    "3": "e",
    "5": "s",
    "\u0131": "i",  # dotless i
    "\u0458": "j",  # Cyrillic je
    "\u0456": "i",  # Cyrillic i
    "\u0457": "i",  # Cyrillic yi
    "\u04cf": "i",  # Cyrillic palochka
    "\u043e": "o",  # Cyrillic o
    "\u03bf": "o",  # Greek omicron
    "\u03b9": "i",  # Greek iota
    "\u0269": "i",  # Latin iota
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Identifiers(_Strict):
    isin: tuple[str, ...] = ()
    cin: tuple[str, ...] = ()
    nse_symbol: tuple[str, ...] = ()
    bse_code: tuple[str, ...] = ()


class RuleMatch(_Strict):
    tokens: tuple[str, ...]
    aliases: tuple[str, ...]
    identifiers: Identifiers


class ExclusionRule(_Strict):
    rule_id: str
    scope: tuple[Scope, ...]
    reason: str
    user_message: str
    match: RuleMatch


class AllowEntry(_Strict):
    normalized_name: str
    rule_id: str
    justification: str


class ExclusionPolicy(_Strict):
    version: Literal[1]
    updated: str
    rules: tuple[ExclusionRule, ...] = Field(min_length=1)
    allow: tuple[AllowEntry, ...] = ()


class EntityRef(_Strict):
    name: str
    identifiers: Identifiers = Identifiers()


class ExclusionResult(_Strict):
    decision: Decision
    reason: Reason | None
    rule_id: str | None
    policy_version: int
    user_message: str | None  # safe to show to users; None when allowed

    @property
    def blocked(self) -> bool:
        return self.decision != "allowed"


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    # Drop invisible format characters: zero-width spaces/joiners, soft hyphen, BOM, bidi marks.
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return text.lower()


def _clean(folded: str) -> str:
    alnum = "".join(ch if unicodedata.category(ch)[0] in "LN" else " " for ch in folded)
    return " ".join(alnum.split())


def normalize_name(text: str) -> str:
    """Canonical form used for matching and for allow-list entries."""
    return _clean(_fold(text))


def _confusable_form(text: str) -> str:
    return _clean("".join(CONFUSABLES.get(ch, ch) for ch in _fold(text)))


def _contains_sequence(tokens: list[str], seq: list[str]) -> bool:
    n = len(seq)
    if not 0 < n <= len(tokens):
        return False
    return any(tokens[i : i + n] == seq for i in range(len(tokens) - n + 1))


def _identifier_hit(rule: ExclusionRule, ids: Identifiers) -> bool:
    for kind in _IDENTIFIER_KINDS:
        wanted = {v.upper() for v in getattr(rule.match.identifiers, kind)}
        if any(v.strip().upper() in wanted for v in getattr(ids, kind)):
            return True
    return False


def evaluate(policy: ExclusionPolicy, entity: EntityRef, scope: Scope = "ipo") -> ExclusionResult:
    normalized = normalize_name(entity.name)
    tokens = normalized.split(" ") if normalized else []
    compact = normalized.replace(" ", "")
    confusable_compact = _confusable_form(entity.name).replace(" ", "")

    for rule in policy.rules:
        if scope not in rule.scope:
            continue

        def hit(decision: Decision, reason: Reason, rule: ExclusionRule = rule) -> ExclusionResult:
            return ExclusionResult(
                decision=decision,
                reason=reason,
                rule_id=rule.rule_id,
                policy_version=policy.version,
                user_message=rule.user_message,
            )

        # Identifiers are unambiguous, so they win even over an allow entry.
        if _identifier_hit(rule, entity.identifiers):
            return hit("excluded", "identifier")

        if any(a.rule_id == rule.rule_id and a.normalized_name == normalized for a in policy.allow):
            continue

        rule_tokens = [normalize_name(t) for t in rule.match.tokens]
        if any(t in rule_tokens for t in tokens):
            return hit("excluded", "token")
        for alias in rule.match.aliases:
            if _contains_sequence(tokens, normalize_name(alias).split(" ")):
                return hit("excluded", "alias")
        if any(t in compact for t in rule_tokens):
            return hit("quarantined", "embedded")
        if any(t in confusable_compact for t in rule_tokens):
            return hit("quarantined", "confusable")

    return ExclusionResult(
        decision="allowed",
        reason=None,
        rule_id=None,
        policy_version=policy.version,
        user_message=None,
    )


def policy_dir() -> Path:
    """packages/policy in the repo; /app/policy in the container (POLICY_DIR)."""
    configured = os.environ.get("POLICY_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "packages" / "policy"


@lru_cache(maxsize=1)
def load_policy(path: Path | None = None) -> ExclusionPolicy:
    """Load and validate the policy. A missing or malformed file raises: fail closed."""
    file = path or policy_dir() / "exclusions.v1.json"
    return ExclusionPolicy.model_validate_json(file.read_text(encoding="utf-8"))
