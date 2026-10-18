"""Run ingestion from the command line.

    python -m arthalens_ai.ingestion.cli discover            # synthetic fixtures
    python -m arthalens_ai.ingestion.cli import FILE.json    # one manual import

In Docker: docker compose exec ai python -m arthalens_ai.ingestion.cli discover
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from arthalens_ai.ingestion.fetch import FetchPolicy, GuardedFetcher
from arthalens_ai.ingestion.pipeline import IngestionPipeline, RunReport
from arthalens_ai.ingestion.providers.files import FileImportProvider
from arthalens_ai.ingestion.repository import PostgresIngestionRepository
from arthalens_ai.ingestion.searchport import SearchPort
from arthalens_ai.ingestion.settings import SEBI_DOMAINS, IngestionSettings
from arthalens_ai.policy.exclusion import load_policy


async def _run(provider: FileImportProvider, settings: IngestionSettings) -> RunReport:
    policy = load_policy()
    repo = await PostgresIngestionRepository.connect(settings.database_url.get_secret_value())
    try:
        port = SearchPort({provider.name: provider}, policy)
        return await IngestionPipeline(port, repo, policy).run(provider.name)
    finally:
        await repo.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arthalens-ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover", help="ingest the synthetic fixtures")
    imp = sub.add_parser("import", help="ingest one arthalens.ipo-import.v1 file")
    imp.add_argument("file", type=Path)
    args = parser.parse_args(argv)

    settings = IngestionSettings()  # values come from the environment
    logging.basicConfig(level=settings.log_level.upper(), format="%(levelname)s %(message)s")

    if args.command == "discover":
        provider = FileImportProvider.fixtures(settings.fixtures_dir)
    else:
        fetcher = GuardedFetcher(FetchPolicy(SEBI_DOMAINS)) if settings.sebi_fetch_enabled else None
        provider = FileImportProvider.manual(args.file, fetcher)

    report = asyncio.run(_run(provider, settings))
    print(json.dumps({"run_id": str(report.run_id), "status": report.status, **report.counts}))
    for error in report.errors:
        print(f"error: {error}", file=sys.stderr)
    return 0 if report.status == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
