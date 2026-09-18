"""A custom endpoint: an OpenAI-compatible URL the caller names, called safely.

The feature is small — "point EvalBench at my own model server" — and
the hole it opens is not. The worker would make HTTP requests to any
address a stranger typed. On a cloud box, ``http://169.254.169.254/``
answers with the instance's credentials; on this stack, ``redis:6379``
answers with no password at all. That is server-side request forgery,
and it has three well-known ways in, each closed here:

1. **The URL itself.** Only https, only a host, no credentials in the
   URL (``https://api.groq.com@10.0.0.1/`` reads as Groq and dials
   10.0.0.1), and every address the host resolves to must be public.
   :func:`validate_endpoint` — run at submission so the answer is a 400
   with the reason, not a dead run.

2. **DNS rebinding.** A hostname can resolve to 93.184.216.34 when it is
   checked and to 127.0.0.1 when it is dialled; the attacker controls
   the record and the TTL. Checking first and connecting later is a
   race the attacker wins. So the check is *inside* the connect:
   :class:`PinnedBackend` resolves, refuses, and dials the address it
   just approved. There is no second resolution.

3. **Redirects.** A public host answering ``302 Location: http://10.0.0.1``
   is the other half of every SSRF write-up. The client never follows
   one. And a chat completion is a few kilobytes, so
   :class:`GuardedTransport` stops reading a response past a cap rather
   than hold a hostile gigabyte in memory to find out it was not JSON.

None of this is on the path for the built-in presets, whose URLs are
constants in this repository. It is only for the URL nobody has seen.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import anyio
import httpcore
import httpx
from httpcore._backends.anyio import AnyIOBackend

# A chat completion is kilobytes. This is generous by three orders of
# magnitude and still small enough to fail fast.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# A model server that does not answer the handshake in this long is
# not going to; the request timeout is for the generation itself.
CONNECT_TIMEOUT = 10.0


class EndpointError(ValueError):
    """The URL was refused. The message says why, in the caller's terms."""


@dataclass(frozen=True)
class Endpoint:
    url: str              # normalised: lower-case host, no trailing slash
    host: str
    ips: tuple[str, ...]  # what it resolved to when checked


# Everything that is not the public internet. The stdlib flags
# (`is_private`, `is_loopback`, …) are applied as well, but their exact
# coverage has changed between Python versions — CGNAT space in
# particular — and a check that depends on the interpreter's minor
# version is not a check. These are spelled out.
_NOT_PUBLIC_V4 = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",          # "this" network
        "10.0.0.0/8",         # RFC 1918
        "100.64.0.0/10",      # carrier-grade NAT, RFC 6598
        "127.0.0.0/8",        # loopback
        "169.254.0.0/16",     # link-local — cloud metadata lives here
        "172.16.0.0/12",      # RFC 1918
        "192.0.0.0/24",       # IETF protocol assignments
        "192.0.2.0/24",       # documentation
        "192.168.0.0/16",     # RFC 1918
        "198.18.0.0/15",      # benchmarking
        "198.51.100.0/24",    # documentation
        "203.0.113.0/24",     # documentation
        "224.0.0.0/4",        # multicast
        "240.0.0.0/4",        # reserved, includes broadcast
    )
)
_NOT_PUBLIC_V6 = tuple(
    ipaddress.ip_network(n)
    for n in (
        "::/128",             # unspecified
        "::1/128",            # loopback
        "64:ff9b::/96",       # NAT64 — a v4 address in disguise
        "2001:db8::/32",      # documentation
        "fc00::/7",           # unique local
        "fe80::/10",          # link-local
        "ff00::/8",           # multicast
    )
)


def is_public_ip(ip: str) -> bool:
    """True only for an address on the public internet."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        # ::ffff:10.0.0.1 is 10.0.0.1 wearing a hat.
        if addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
    nets = _NOT_PUBLIC_V4 if addr.version == 4 else _NOT_PUBLIC_V6
    if any(addr in n for n in nets):
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def resolve(host: str) -> tuple[str, ...]:
    """Every address ``host`` resolves to right now, in answer order."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise EndpointError(f"Could not resolve '{host}': {e}.") from e
    ips: list[str] = []
    for *_, sockaddr in infos:
        ip = str(sockaddr[0])
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise EndpointError(f"Could not resolve '{host}'.")
    return tuple(ips)


def check_addresses(
    host: str, ips: Iterable[str], *, allow_private: bool = False
) -> None:
    """Refuse unless every address is public.

    Every address, not the first: a name with one public and one internal
    answer is a name whose owner decides which one the connection gets.
    """
    if allow_private:
        return
    bare = host.lower().rstrip(".")
    if bare == "localhost" or bare.endswith(".localhost"):
        raise EndpointError(
            f"'{host}' is not a public address. EvalBench only calls "
            "endpoints on the public internet."
        )
    for ip in ips:
        if not is_public_ip(ip):
            # Not the address it resolved to: on a public deployment that
            # would let anyone map the internal network by name, one
            # request at a time.
            where = "" if ip == host else " (it resolves to a private address)"
            raise EndpointError(
                f"'{host}' is not a public address{where}. EvalBench only "
                "calls endpoints on the public internet."
            )


def validate_endpoint(url: str, *, allow_private: bool = False) -> Endpoint:
    """Check a base URL and return it normalised, with what it resolved to.

    ``allow_private`` is the self-hosted escape hatch: an operator whose
    EvalBench runs on their own machine may point it at a vLLM on the
    LAN over plain http. It is their network. It is never right on a
    public deployment, and the setting behind it says so.
    """
    raw = (url or "").strip()
    if not raw:
        raise EndpointError("No endpoint URL was given.")
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise EndpointError(
            "The endpoint must be an https:// URL, for example "
            "https://my-gateway.example.com/v1."
        )
    if scheme == "http" and not allow_private:
        raise EndpointError(
            "The endpoint must use https. Plain http is only allowed for a "
            "private endpoint on a self-hosted instance "
            "(ALLOW_PRIVATE_ENDPOINTS=true)."
        )
    if parts.username is not None or parts.password is not None:
        raise EndpointError(
            "The endpoint URL must not contain credentials. Put the key in "
            "the API key field instead."
        )
    if parts.query or parts.fragment:
        raise EndpointError(
            "The endpoint is a base URL — no query string or #fragment. "
            "EvalBench appends /chat/completions to it."
        )
    host = parts.hostname
    if not host:
        raise EndpointError("The endpoint URL has no host.")
    try:
        _ = parts.port  # raises on ':abc' or out-of-range
    except ValueError as e:
        raise EndpointError("The endpoint URL has an invalid port.") from e

    ips = resolve(host)
    check_addresses(host, ips, allow_private=allow_private)

    normalised = urlunsplit(
        (scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", "")
    )
    return Endpoint(url=normalised, host=host, ips=ips)


class PinnedBackend(AnyIOBackend):
    """httpcore's network layer, with the check inside the dial.

    httpcore hands this the *hostname*; ordinarily anyio resolves it and
    connects to whatever comes back. Here the name is resolved once,
    every answer is checked, and the socket is opened to the checked
    address — so a record that changed between submission and now is
    refused, not followed. TLS still verifies against the hostname:
    httpcore starts it on the returned stream with the original name.
    """

    def __init__(self, allow_private: bool = False) -> None:
        self.allow_private = allow_private

    async def _dial(self, host: str, port: int, **kw):
        # The real connect, to an address literal. Separate so a test
        # can prove what was dialled without opening a socket.
        return await AnyIOBackend.connect_tcp(self, host, port, **kw)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        ips = await anyio.to_thread.run_sync(resolve, host)
        check_addresses(host, ips, allow_private=self.allow_private)
        # Every address passed, so any of them is safe to dial. Try them
        # in answer order: a dual-stack name lists IPv6 first, and on a
        # host with no IPv6 route that one fails where the v4 would not.
        last: Exception | None = None
        for ip in ips:
            try:
                return await self._dial(
                    ip, port,
                    timeout=timeout, local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout, OSError) as e:
                last = e
        assert last is not None
        raise last

    async def connect_unix_socket(self, path: str, timeout=None, socket_options=None):
        raise EndpointError("Unix sockets are not endpoints.")


class _CappedStream(httpx.AsyncByteStream):
    def __init__(self, inner: AsyncIterable[bytes], cap: int) -> None:
        self._inner = inner
        self._cap = cap

    async def __aiter__(self) -> AsyncIterator[bytes]:
        seen = 0
        async for part in self._inner:
            seen += len(part)
            if seen > self._cap:
                raise EndpointError(
                    f"The endpoint's response is too large (over "
                    f"{self._cap // (1024 * 1024)} MB). A chat completion "
                    "is a few kilobytes; this is not one."
                )
            yield part

    async def aclose(self) -> None:
        if hasattr(self._inner, "aclose"):
            await self._inner.aclose()


class GuardedTransport(httpx.AsyncHTTPTransport):
    """httpx's transport over :class:`PinnedBackend`, with a response cap.

    Built with the same pool settings httpx would use, minus proxies —
    an ``HTTP_PROXY`` in the environment would otherwise route the
    connection around the pin.
    """

    def __init__(
        self,
        *,
        allow_private: bool = False,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        limits: httpx.Limits = httpx.Limits(max_connections=8, max_keepalive_connections=4),
    ) -> None:
        super().__init__(verify=True)
        self.max_response_bytes = max_response_bytes
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True),
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=True,
            http2=False,
            network_backend=PinnedBackend(allow_private=allow_private),
        )

    def _capped(self, stream: AsyncIterable[bytes]) -> _CappedStream:
        return _CappedStream(stream, self.max_response_bytes)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        resp = await super().handle_async_request(request)
        return httpx.Response(
            status_code=resp.status_code,
            headers=resp.headers,
            stream=self._capped(resp.stream),
            extensions=resp.extensions,
        )
