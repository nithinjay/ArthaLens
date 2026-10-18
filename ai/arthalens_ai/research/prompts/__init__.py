"""Versioned prompts. A prompt's version is recorded on every section result."""

import hashlib
from functools import cache
from pathlib import Path

from arthalens_ai.research.contracts import SectionId

PROMPT_DIR = Path(__file__).parent
COMMON = "common.v1"
SECTION_PROMPTS: dict[SectionId, str] = {"A": "A.v1", "E": "E.v1", "F": "F.v1", "J": "J.v1"}


@cache
def _read(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def system_prompt(section: SectionId) -> tuple[str, str]:
    """Return (system prompt, version id). The id names both files and hashes their text, so an
    edit without a version bump is still visible in stored results."""
    name = SECTION_PROMPTS[section]
    text = f"{_read(COMMON)}\n\n{_read(name)}"
    digest = hashlib.sha256(text.encode()).hexdigest()[:8]
    return text, f"{COMMON}+{name}@{digest}"
