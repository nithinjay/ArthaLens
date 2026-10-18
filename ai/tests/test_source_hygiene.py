"""Keep matcher and parser source ASCII-only.

Look-alike or invisible characters typed literally into exclusion or parsing code are
impossible to review by eye (a Cyrillic 'o' looks exactly like a Latin one). Write them as
\\uXXXX escapes instead.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUARDED = [
    REPO / "ai" / "arthalens_ai" / "policy",
    REPO / "ai" / "arthalens_ai" / "domain",
    REPO / "ai" / "arthalens_ai" / "ingestion",
    REPO / "packages" / "policy" / "src",
    REPO / "packages" / "policy" / "test",
]
FILES = sorted(p for d in GUARDED for p in d.rglob("*") if p.suffix in {".py", ".ts"})


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(REPO)))
def test_source_is_ascii(path: Path) -> None:
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        bad = [f"U+{ord(c):04X}" for c in line if ord(c) > 127]
        assert not bad, f"{path.name}:{lineno} contains {bad}; use \\uXXXX escapes"
