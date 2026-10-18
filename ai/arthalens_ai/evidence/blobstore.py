"""Write-once, content-addressed storage for raw source bytes (source snapshots).

Keys are derived from the SHA-256 of the bytes, so a stored snapshot can't be silently
replaced: writing different bytes under an existing key is impossible, and every read
re-verifies the hash. Bytes are kept for reproducibility and are never served by the API
(see ADR-0015 on SEBI material). Production swaps this for object storage (Milestone 11).
"""

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

_SHA = re.compile(r"^[0-9a-f]{64}$")


class BlobIntegrityError(Exception):
    """Stored bytes no longer match their hash."""


class BlobStore(Protocol):
    def put(self, sha256: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...


def blob_key(sha256: str) -> str:
    if not _SHA.match(sha256):
        raise ValueError("not a SHA-256 hex digest")
    return f"sha256/{sha256[:2]}/{sha256}"


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        match = re.fullmatch(r"sha256/([0-9a-f]{2})/([0-9a-f]{64})", key)
        if not match or match.group(2)[:2] != match.group(1):
            raise ValueError(f"malformed blob key: {key!r}")
        return self._root / key

    def put(self, sha256: str, data: bytes) -> str:
        if hashlib.sha256(data).hexdigest() != sha256:
            raise BlobIntegrityError("bytes do not match the declared hash")
        key = blob_key(sha256)
        path = self._path(key)
        if path.exists():
            return key  # write-once: identical bytes are already there
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.chmod(tmp, 0o440)
            os.replace(tmp, path)  # atomic: readers never see a partial file
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return key

    def get(self, key: str) -> bytes:
        data = self._path(key).read_bytes()
        if hashlib.sha256(data).hexdigest() != key.rsplit("/", 1)[1]:
            raise BlobIntegrityError(f"stored bytes for {key} have been altered")
        return data
