"""Write JSON Schemas for all exported contracts.

Usage: python -m arthalens_ai.contracts.export <output-dir>
"""

import json
import sys
from pathlib import Path

from arthalens_ai.contracts import EXPORTED_MODELS


def export(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in sorted(EXPORTED_MODELS.items()):
        schema = model.model_json_schema(mode="serialization")
        schema["$id"] = f"https://arthalens.local/schemas/{name}.json"
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m arthalens_ai.contracts.export <output-dir>")
    for path in export(Path(sys.argv[1])):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
