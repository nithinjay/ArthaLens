"""SSRF-guarded document fetcher: the only code in ArthaLens that downloads from the internet.

Threat model T-20. Every request, including each redirect hop and robots.txt, must:
- use https on the default port, with no credentials in the URL;
- target an allow-listed domain (exact host or a subdomain of it);
- resolve only to public IP addresses (no loopback, private, link-local, metadata, reserved);
- actually connect to one of those addresses (DNS-rebinding check on the peer address);
- be permitted by the site's robots.txt for our user agent;
- return an allowed content type within the size limit.
"""

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx2 as httpx

logger = logging.getLogger(__name__)

USER_AGENT = "ArthaLensResearchBot/0.1 (educational research; single-document fetches)"

Resolver = Callable[[str, int], Awaitable[list[str]]]


class FetchError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class FetchPolicy:
    allowed_domains: tuple[str, ...]
    allowed_mime_types: frozenset[str] = frozenset({"application/pdf", "text/html", "text/plain"})
    max_bytes: int = 50 * 1024 * 1024
    timeout_s: float = 30.0
    max_redirects: int = 3
    respect_robots: bool = True


@dataclass(frozen=True)
class FetchedDocument:
    url: str  # final URL after redirects
    mime_type: str
    content: bytes


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_public_address(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in allowed)


def check_url(url: str, policy: FetchPolicy) -> str:
    """Validate a URL against the policy and return its host."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise FetchError("scheme_not_allowed", "only https URLs are fetched")
    if parts.username or parts.password:
        raise FetchError("credentials_in_url", "URLs with credentials are rejected")
    if parts.port not in (None, 443):
        raise FetchError("port_not_allowed", "only the default https port is allowed")
    host = (parts.hostname or "").lower()
    try:
        ipaddress.ip_address(host)
        raise FetchError("ip_literal", "URLs must use a hostname, not an IP address")
    except ValueError:
        pass
    if not host or not host_allowed(host, policy.allowed_domains):
        raise FetchError("domain_not_allowed", f"{host or '(none)'} is not on the allow-list")
    return host


def check_peer(extensions: dict[str, Any], resolved: list[str]) -> None:
    """After connecting, confirm we reached one of the vetted addresses (DNS rebinding)."""
    stream = extensions.get("network_stream")
    peer = stream.get_extra_info("server_addr") if stream is not None else None
    if not peer:
        raise FetchError("peer_unknown", "could not confirm the connected address")
    ip = str(peer[0])
    if ip not in resolved or not is_public_address(ip):
        raise FetchError("peer_mismatch", "connected address was not the vetted one")


@dataclass
class GuardedFetcher:
    policy: FetchPolicy
    resolver: Resolver = system_resolver
    transport: httpx.AsyncBaseTransport | None = None
    # Peer verification needs a real socket; tests using a mock transport turn it off.
    verify_peer: bool = True
    _robots: dict[str, "RobotsRules"] = field(default_factory=dict)

    async def fetch(self, url: str) -> FetchedDocument:
        async with httpx.AsyncClient(
            transport=self.transport,
            follow_redirects=False,
            timeout=self.policy.timeout_s,
            headers={"user-agent": USER_AGENT},
            trust_env=False,  # never route through an environment-configured proxy
        ) as client:
            current = url
            for _hop in range(self.policy.max_redirects + 1):
                host = check_url(current, self.policy)
                resolved = await self._vet_dns(host)
                if self.policy.respect_robots:
                    await self._check_robots(client, current, host, resolved)
                response = await self._get(client, current, resolved)
                if response.is_redirect:
                    location = response.headers.get("location")
                    await response.aclose()
                    if not location:
                        raise FetchError("bad_redirect", "redirect without a Location header")
                    current = urljoin(current, location)
                    continue
                return await self._read(response, current)
        raise FetchError("too_many_redirects", f"more than {self.policy.max_redirects} redirects")

    async def _vet_dns(self, host: str) -> list[str]:
        try:
            resolved = await self.resolver(host, 443)
        except OSError as exc:
            raise FetchError("dns_failed", type(exc).__name__) from exc
        if not resolved:
            raise FetchError("dns_failed", "no addresses")
        blocked = [ip for ip in resolved if not is_public_address(ip)]
        if blocked:
            # Any non-public answer poisons the whole lookup.
            raise FetchError("blocked_address", f"{host} resolves to a non-public address")
        return resolved

    async def _get(
        self, client: httpx.AsyncClient, url: str, resolved: list[str]
    ) -> httpx.Response:
        try:
            request = client.build_request("GET", url)
            response = await client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise FetchError("network_error", type(exc).__name__) from exc
        if self.verify_peer:
            try:
                check_peer(response.extensions, resolved)
            except FetchError:
                await response.aclose()
                raise
        return response

    async def _read(self, response: httpx.Response, url: str) -> FetchedDocument:
        try:
            if response.status_code != 200:
                raise FetchError("http_status", f"HTTP {response.status_code}")
            mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if mime not in self.policy.allowed_mime_types:
                raise FetchError("mime_not_allowed", mime or "(none)")
            declared = int(response.headers.get("content-length", "0") or 0)
            if declared > self.policy.max_bytes:
                raise FetchError("too_large", f"{declared} bytes")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > self.policy.max_bytes:
                    raise FetchError("too_large", f"more than {self.policy.max_bytes} bytes")
                chunks.append(chunk)
            return FetchedDocument(url=url, mime_type=mime, content=b"".join(chunks))
        finally:
            await response.aclose()

    async def _check_robots(
        self, client: httpx.AsyncClient, url: str, host: str, resolved: list[str]
    ) -> None:
        rules = self._robots.get(host)
        if rules is None:
            rules = await self._load_robots(client, host, resolved)
            self._robots[host] = rules
        if not rules.allows(url):
            raise FetchError("robots_disallowed", f"robots.txt disallows {urlsplit(url).path}")

    async def _load_robots(
        self, client: httpx.AsyncClient, host: str, resolved: list[str]
    ) -> "RobotsRules":
        response = await self._get(client, f"https://{host}/robots.txt", resolved)
        try:
            if response.status_code == 200:
                raw = (await response.aread())[: 512 * 1024]
                parser = RobotFileParser()
                parser.parse(raw.decode("utf-8", errors="replace").splitlines())
                return RobotsRules(parser=parser)
            if response.status_code in (401, 403):
                return RobotsRules(parser=None, default_allow=False)
            return RobotsRules(parser=None, default_allow=True)  # none published: unrestricted
        finally:
            await response.aclose()


@dataclass(frozen=True)
class RobotsRules:
    parser: RobotFileParser | None
    default_allow: bool = True

    def allows(self, url: str) -> bool:
        if self.parser is None:
            return self.default_allow
        return self.parser.can_fetch(USER_AGENT, url)
