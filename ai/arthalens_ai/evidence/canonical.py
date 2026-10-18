"""Stable source identifiers.

A document's ``source_key`` names *where* it came from, independent of *what* it contained on
a given day. Versions of the same source share a key; the content hash tells them apart.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


def source_key(url: str) -> str:
    """Canonical form of a URL: lower-case scheme and host, no default port, no fragment,
    no tracking parameters, remaining query parameters sorted."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise ValueError(f"unsupported URL scheme: {scheme!r}")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("URL has no host")
    port = parts.port
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    )
    return urlunsplit((scheme, netloc, parts.path or "/", urlencode(query), ""))


def upload_source_key(tenant_id: UUID, sha256: str) -> str:
    """Key for a tenant's private upload. Includes the tenant, so it never collides with
    another tenant's upload or with a public source."""
    return f"upload:{tenant_id}:{sha256}"
