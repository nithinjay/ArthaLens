import json
from pathlib import Path

from arthalens_ai.contracts import EXPORTED_MODELS
from arthalens_ai.contracts.export import export

COMMITTED = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "schemas"


def test_export_writes_one_file_per_model(tmp_path: Path) -> None:
    written = export(tmp_path)
    assert sorted(p.stem for p in written) == sorted(EXPORTED_MODELS)


def test_committed_schemas_match_models(tmp_path: Path) -> None:
    """Drift guard: regenerate with `pnpm contracts:gen` if this fails."""
    for path in export(tmp_path):
        committed = COMMITTED / path.name
        assert committed.exists(), f"missing {committed}; run pnpm contracts:gen"
        assert json.loads(committed.read_text()) == json.loads(path.read_text())
