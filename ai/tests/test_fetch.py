"""SSRF guard (threat model T-20). No real network: fake DNS + mock HTTP transport."""

import asyncio
from collections.abc import Callable

import httpx2 as httpx
import pytest

from arthalens_ai.ingestion.fetch import (
    FetchError,
    FetchPolicy,
    GuardedFetcher,
    check_peer,
    is_public_address,
)

DOC_IP = "203.0.113.10"  # TEST-NET-3 documentation range: not globally routable
GLOBAL_IP = "8.8.8.8"
POLICY = FetchPolicy(allowed_domains=("sebi.gov.in",), max_bytes=1000, max_redirects=2)
PDF = b"%PDF-1.7 synthetic"


def resolver_for(mapping: dict[str, list[str]]):  # type: ignore[no-untyped-def]
    async def resolve(host: str, port: int) -> list[str]:
        return mapping.get(host, [GLOBAL_IP])

    return resolve


def fetcher(
    handler: Callable[[httpx.Request], httpx.Response],
    dns: dict[str, list[str]] | None = None,
    policy: FetchPolicy = POLICY,
) -> GuardedFetcher:
    return GuardedFetcher(
        policy=policy,
        resolver=resolver_for(dns or {}),
        transport=httpx.MockTransport(handler),
        verify_peer=False,  # mock transport has no socket; check_peer is tested separately
    )


def site(routes: dict[str, httpx.Response]) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt" and str(request.url) not in routes:
            return httpx.Response(404)
        return routes.get(str(request.url), httpx.Response(404))

    return handle


def ok_pdf() -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "application/pdf"}, content=PDF)


URL = "https://www.sebi.gov.in/filings/rhp.pdf"


def fetch(f: GuardedFetcher, url: str = URL) -> bytes:
    return asyncio.run(f.fetch(url)).content


def code_of(f: GuardedFetcher, url: str = URL) -> str:
    with pytest.raises(FetchError) as info:
        asyncio.run(f.fetch(url))
    return info.value.code


def test_fetches_allowed_document() -> None:
    assert fetch(fetcher(site({URL: ok_pdf()}))) == PDF


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://www.sebi.gov.in/rhp.pdf", "scheme_not_allowed"),
        ("file:///etc/passwd", "scheme_not_allowed"),
        ("https://user:pw@www.sebi.gov.in/rhp.pdf", "credentials_in_url"),
        ("https://www.sebi.gov.in:8443/rhp.pdf", "port_not_allowed"),
        ("https://203.0.113.5/rhp.pdf", "ip_literal"),
        ("https://[::1]/rhp.pdf", "ip_literal"),
        ("https://www.nseindia.com/rhp.pdf", "domain_not_allowed"),
        ("https://sebi.gov.in.evil.example/rhp.pdf", "domain_not_allowed"),
        ("https://evilsebi.gov.in/rhp.pdf", "domain_not_allowed"),
    ],
)
def test_rejects_bad_urls(url: str, code: str) -> None:
    assert code_of(fetcher(site({})), url) == code


@pytest.mark.parametrize(
    "ips",
    [
        ["127.0.0.1"],
        ["10.0.0.5"],
        ["192.168.1.1"],
        ["169.254.169.254"],  # cloud metadata endpoint
        ["0.0.0.0"],
        ["::1"],
        ["fd00::1"],
        ["::ffff:127.0.0.1"],  # IPv4-mapped loopback
        [GLOBAL_IP, "10.0.0.5"],  # one bad answer poisons the lookup
    ],
)
def test_blocks_non_public_dns_answers(ips: list[str]) -> None:
    f = fetcher(site({URL: ok_pdf()}), dns={"www.sebi.gov.in": ips})
    assert code_of(f) == "blocked_address"


def test_follows_redirect_within_allow_list() -> None:
    target = "https://www.sebi.gov.in/final.pdf"
    redirect = httpx.Response(302, headers={"location": "/final.pdf"})
    assert fetch(fetcher(site({URL: redirect, target: ok_pdf()}))) == PDF


def test_rejects_redirect_off_allow_list() -> None:
    redirect = httpx.Response(302, headers={"location": "https://evil.example/x.pdf"})
    assert code_of(fetcher(site({URL: redirect}))) == "domain_not_allowed"


def test_rejects_redirect_to_internal_host() -> None:
    target = "https://internal.sebi.gov.in/x.pdf"
    redirect = httpx.Response(302, headers={"location": target})
    f = fetcher(site({URL: redirect, target: ok_pdf()}), dns={"internal.sebi.gov.in": ["10.1.2.3"]})
    assert code_of(f) == "blocked_address"


def test_stops_redirect_loops() -> None:
    loop = httpx.Response(302, headers={"location": URL})
    assert code_of(fetcher(site({URL: loop}))) == "too_many_redirects"


def test_rejects_disallowed_content_type() -> None:
    exe = httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"MZ")
    assert code_of(fetcher(site({URL: exe}))) == "mime_not_allowed"


def test_rejects_oversized_body() -> None:
    big = httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"x" * 1001)
    assert code_of(fetcher(site({URL: big}))) == "too_large"


def test_rejects_non_200() -> None:
    assert code_of(fetcher(site({URL: httpx.Response(500)}))) == "http_status"


def test_respects_robots_disallow() -> None:
    robots = httpx.Response(200, text="User-agent: *\nDisallow: /filings/\n")
    routes = {"https://www.sebi.gov.in/robots.txt": robots, URL: ok_pdf()}
    assert code_of(fetcher(site(routes))) == "robots_disallowed"


def test_robots_allow_permits_fetch() -> None:
    robots = httpx.Response(200, text="User-agent: *\nDisallow: /js\n")
    routes = {"https://www.sebi.gov.in/robots.txt": robots, URL: ok_pdf()}
    assert fetch(fetcher(site(routes))) == PDF


def test_robots_forbidden_means_disallow_all() -> None:
    routes = {"https://www.sebi.gov.in/robots.txt": httpx.Response(403), URL: ok_pdf()}
    assert code_of(fetcher(site(routes))) == "robots_disallowed"


def test_sends_identifying_user_agent() -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return ok_pdf() if request.url.path != "/robots.txt" else httpx.Response(404)

    fetch(fetcher(handle))
    assert all(ua.startswith("ArthaLensResearchBot/") for ua in seen)


class _Stream:
    def __init__(self, addr: tuple[str, int] | None) -> None:
        self.addr = addr

    def get_extra_info(self, key: str) -> object:
        return self.addr if key == "server_addr" else None


def test_check_peer_accepts_vetted_address() -> None:
    check_peer({"network_stream": _Stream((GLOBAL_IP, 443))}, [GLOBAL_IP])


@pytest.mark.parametrize(
    ("ext", "code"),
    [
        ({}, "peer_unknown"),
        ({"network_stream": _Stream(None)}, "peer_unknown"),
        ({"network_stream": _Stream(("10.0.0.9", 443))}, "peer_mismatch"),  # DNS rebinding
        ({"network_stream": _Stream(("1.1.1.1", 443))}, "peer_mismatch"),  # not the vetted IP
    ],
)
def test_check_peer_rejects(ext: dict[str, object], code: str) -> None:
    with pytest.raises(FetchError) as info:
        check_peer(ext, [GLOBAL_IP])
    assert info.value.code == code


def test_documentation_ranges_are_not_public() -> None:
    assert not is_public_address(DOC_IP)
    assert is_public_address(GLOBAL_IP)
