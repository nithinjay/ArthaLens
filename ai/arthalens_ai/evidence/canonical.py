"""Stable source identifiers.

A document's ``source_key`` names *where* it came from, independent of *what* it contained on
a given day. Versions of the same source share a key; the content hash tells them apart.
"""

from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


def source_key(url: str) -> str:
    """Canonical form of a URL: lower-case scheme and host, no default port, no fragment,
    no tracking parameters, remaining query parameters sorted.

    Must match the SQL function ``canonical_source_key`` (migration 20261018000002), which
    backfilled older documents; shared vectors in the integration tests check both. Query
    pairs are compared as raw ``k=v`` strings, never decoded and re-encoded.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise ValueError(f"unsupported URL scheme: {scheme!r}")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("URL has no host")
    port = parts.port
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    pairs = sorted(
        pair
        for pair in parts.query.split("&")
        if pair and not _is_tracking(pair.split("=", 1)[0].lower())
    )
    return urlunsplit((scheme, netloc, parts.path or "/", "&".join(pairs), ""))


def _is_tracking(key: str) -> bool:
    return key.startswith("utm_") or key in _TRACKING_PARAMS


def tenant_source_key(tenant_id: UUID, url: str) -> str:
    """Key for a tenant's private copy of a URL. Tenant documents never share a key with
    the public chain of the same URL, so they can't collide with it or reveal themselves
    through it (enforced by the evidence_documents_key_namespace constraint)."""
    return f"tenant:{tenant_id}:{source_key(url)}"


def upload_source_key(tenant_id: UUID, sha256: str) -> str:
    """Key for a tenant's private upload. Includes the tenant, so it never collides with
    another tenant's upload or with a public source."""
    return f"upload:{tenant_id}:{sha256}"
