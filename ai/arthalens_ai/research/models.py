"""List the Gemini models your API key can use for content generation.

    docker compose exec ai-worker python -m arthalens_ai.research.models

Model ids change over time, so ArthaLens never hard-codes one: pick an id from this list and
set GEMINI_MODEL in .env.
"""

import os
import sys


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        print("GEMINI_API_KEY is not set in .env", file=sys.stderr)
        return 1
    from google import genai

    client = genai.Client(api_key=key)
    names = sorted(
        (m.name or "").removeprefix("models/")
        for m in client.models.list()
        if "generateContent" in (getattr(m, "supported_actions", None) or [])
    )
    for name in names:
        print(name)
    return 0 if names else 1


if __name__ == "__main__":
    sys.exit(main())
