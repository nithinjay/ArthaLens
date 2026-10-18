import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from arthalens_ai.policy.exclusion import (
    AllowEntry,
    EntityRef,
    Identifiers,
    evaluate,
    load_policy,
    normalize_name,
    policy_dir,
)

pytestmark = pytest.mark.policy

POLICY = load_policy()
VECTORS = json.loads((policy_dir() / "exclusion-vectors.v1.json").read_text(encoding="utf-8"))


def test_vectors_target_current_policy_version() -> None:
    assert VECTORS["policy_version"] == POLICY.version


@pytest.mark.parametrize("vector", VECTORS["vectors"], ids=lambda v: repr(v["name"]))
def test_shared_vector(vector: dict[str, str | None]) -> None:
    """Same truth table as packages/policy/test/exclusion.test.ts."""
    result = evaluate(POLICY, EntityRef(name=str(vector["name"])))
    assert (result.decision, result.reason) == (vector["decision"], vector["reason"])


def test_identifier_match_beats_harmless_name() -> None:
    rule = POLICY.rules[0]
    with_ids = POLICY.model_copy(
        update={
            "rules": (
                rule.model_copy(
                    update={
                        "match": rule.match.model_copy(
                            update={"identifiers": Identifiers(isin=("INE000TEST01",))}
                        )
                    }
                ),
            )
        }
    )
    entity = EntityRef(name="Harmless Name Ltd", identifiers=Identifiers(isin=("ine000test01 ",)))
    result = evaluate(with_ids, entity)
    assert (result.decision, result.reason, result.rule_id) == (
        "excluded",
        "identifier",
        "EXCL-JIO-001",
    )


def test_blocked_results_carry_user_message() -> None:
    assert "excluded from ArthaLens" in (evaluate(POLICY, EntityRef(name="Jio")).user_message or "")
    assert evaluate(POLICY, EntityRef(name="Synthetic Alpha Foods")).user_message is None


def test_allow_entry_only_unblocks_that_name() -> None:
    allowing = POLICY.model_copy(
        update={
            "allow": (
                AllowEntry(
                    normalized_name="rajio technologies", rule_id="EXCL-JIO-001", justification="t"
                ),
            )
        }
    )
    assert evaluate(allowing, EntityRef(name="Rajio Technologies")).decision == "allowed"
    assert evaluate(allowing, EntityRef(name="Jio Platforms")).decision == "excluded"


def test_ipo_rule_does_not_apply_to_stock_scope() -> None:
    assert evaluate(POLICY, EntityRef(name="Jio Financial Services"), "stock").decision == "allowed"


def test_normalize_name() -> None:
    assert normalize_name("  \uff2a\uff49\uff4f\u200b-Platforms, LTD. ") == "jio platforms ltd"


@pytest.mark.parametrize(
    "content",
    ["", "{}", '{"version": 1, "updated": "x", "rules": []}', '{"version": 2, "rules": []}'],
)
def test_malformed_policy_fails_closed(tmp_path: Path, content: str) -> None:
    load_policy.cache_clear()
    bad = tmp_path / "bad.json"
    bad.write_text(content)
    with pytest.raises(ValidationError):
        load_policy(bad)
    load_policy.cache_clear()


def test_missing_policy_fails_closed(tmp_path: Path) -> None:
    load_policy.cache_clear()
    with pytest.raises(FileNotFoundError):
        load_policy(tmp_path / "nope.json")
    load_policy.cache_clear()
