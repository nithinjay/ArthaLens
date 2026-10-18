"""Providers that read ``arthalens.ipo-import.v1`` files.

- ``fixtures``: every ``*.json`` in a directory of SYNTHETIC test data. Refuses any file not
  marked ``"synthetic": true``, so fixtures can never pass as real data (brief section 26.16).
- ``manual``: one import file prepared by a person, typically from documents they downloaded
  in a browser (the route for NSE/BSE material, whose terms forbid automated collection).
  Documents may instead be fetched live, only through the guarded fetcher.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from arthalens_ai.contracts.ipo import RetrievalMethod
from arthalens_ai.ingestion.fetch import FetchError, GuardedFetcher
from arthalens_ai.ingestion.models import Candidate, ImportDocument, IpoImport, LoadedDocument
from arthalens_ai.ingestion.text import extract_text

MAX_LOCAL_FILE_BYTES = 50 * 1024 * 1024


class ImportFileError(ValueError):
    pass


def read_import(path: Path) -> IpoImport:
    return IpoImport.model_validate_json(path.read_bytes())


class FileImportProvider:
    def __init__(
        self,
        name: str,
        paths: list[Path],
        *,
        require_synthetic: bool,
        fetcher: GuardedFetcher | None = None,
        clock: type[datetime] = datetime,
    ) -> None:
        self.name = name
        self._paths = paths
        self._require_synthetic = require_synthetic
        self._fetcher = fetcher
        self._clock = clock

    @classmethod
    def fixtures(cls, directory: Path) -> "FileImportProvider":
        return cls("fixtures", sorted(directory.glob("*.json")), require_synthetic=True)

    @classmethod
    def manual(cls, path: Path, fetcher: GuardedFetcher | None) -> "FileImportProvider":
        return cls("manual", [path], require_synthetic=False, fetcher=fetcher)

    @property
    def retrieval_method(self) -> RetrievalMethod:
        return "mock_fixture" if self._require_synthetic else "manual_import"

    def candidates(self) -> list[Candidate]:
        found = []
        for path in self._paths:
            data = read_import(path)
            if self._require_synthetic and not data.synthetic:
                raise ImportFileError(f"{path.name}: fixtures must be marked synthetic")
            found.append(Candidate(provider=self.name, origin=path.resolve(), data=data))
        return found

    async def load_documents(self, candidate: Candidate) -> list[LoadedDocument]:
        return [await self._load(candidate, spec) for spec in candidate.data.documents]

    async def _load(self, candidate: Candidate, spec: ImportDocument) -> LoadedDocument:
        method: RetrievalMethod = self.retrieval_method
        if spec.fetch:
            if self._fetcher is None:
                raise FetchError("fetch_disabled", "live fetching is not enabled for this provider")
            fetched = await self._fetcher.fetch(spec.url)
            if fetched.mime_type != spec.mime_type:
                raise FetchError(
                    "mime_mismatch", f"expected {spec.mime_type}, got {fetched.mime_type}"
                )
            content, method = fetched.content, "live_fetch"
        else:
            content = self._read_local(candidate.origin, spec.file or "")
        return LoadedDocument(
            ref=spec.ref,
            spec=spec,
            sha256=hashlib.sha256(content).hexdigest(),
            byte_size=len(content),
            text=extract_text(content, spec.mime_type),
            retrieved_at=self._clock.now(UTC),
            retrieval_method=method,
            provider=self.name,
            is_synthetic=candidate.data.synthetic,
        )

    @staticmethod
    def _read_local(origin: Path, relative: str) -> bytes:
        base = origin.parent.resolve()
        target = (base / relative).resolve()
        # No path traversal out of the import's own directory.
        if not target.is_relative_to(base):
            raise ImportFileError(f"document path escapes the import directory: {relative!r}")
        if target.stat().st_size > MAX_LOCAL_FILE_BYTES:
            raise ImportFileError(f"document too large: {relative!r}")
        return target.read_bytes()
