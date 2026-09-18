"""A custom endpoint is a URL the server will fetch on a stranger's say-so.

That is server-side request forgery in its purest form. The address bar
of every cloud box holds credentials at 169.254.169.254; this stack's own
Redis answers on redis:6379 with no password. So the rule is not "does
the URL look public" — a hostname can resolve to anything, and can
resolve differently the second time — but: resolve it, refuse if any
answer is not a public address, and then connect to *exactly the address
that was checked*. The check and the connection cannot be separated, or
the gap between them is the attack (DNS rebinding).

Three layers, each with its own tests here:

1. `validate_endpoint` — the URL rules and the resolve-and-check.
2. `PinnedBackend` — the network layer that resolves, checks, and dials
   the checked IP. This is what makes the check mean something.
3. `GuardedTransport` — no redirects (a 302 to an internal address is
   the other classic), and a cap on how much of a response is read.
"""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock, patch

import pytest

from evalbench.core.endpoint import (
    EndpointError,
    PinnedBackend,
    is_public_ip,
    validate_endpoint,
)

PUBLIC = "93.184.216.34"


def _resolver(*ips: str):
    """A stand-in for getaddrinfo that answers with these addresses."""

    def fake(host, port, *a, **k):
        out = []
        for ip in ips:
            fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
            out.append((fam, socket.SOCK_STREAM, 6, "", (ip, port)))
        return out

    return fake


# ── 1. the address rules ─────────────────────────────────────────


class TestWhichAddressesArePublic:
    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1", "127.255.255.254",          # loopback
            "10.0.0.5", "172.16.0.1", "172.31.255.1", "192.168.1.1",  # RFC 1918
            "169.254.169.254",                        # link-local: cloud metadata
            "100.64.0.1",                             # CGNAT (RFC 6598)
            "0.0.0.0", "0.1.2.3",                     # "this" network
            "224.0.0.1", "255.255.255.255",           # multicast / broadcast
            "::1", "::",                              # v6 loopback / unspecified
            "fc00::1", "fd12:3456::1",                # v6 unique local
            "fe80::1",                                # v6 link-local
            "::ffff:10.0.0.1", "::ffff:127.0.0.1",    # v4 hidden inside v6
        ],
    )
    def test_internal_addresses_are_not_public(self, ip):
        assert is_public_ip(ip) is False

    @pytest.mark.parametrize("ip", [PUBLIC, "8.8.8.8", "2606:4700::1111"])
    def test_ordinary_internet_addresses_are(self, ip):
        assert is_public_ip(ip) is True


class TestTheUrlRules:
    def test_a_public_https_url_is_accepted_and_normalised(self):
        with patch("socket.getaddrinfo", _resolver(PUBLIC)):
            ep = validate_endpoint("https://api.example.com/v1/")
        assert ep.url == "https://api.example.com/v1"
        assert ep.host == "api.example.com"
        assert ep.ips == (PUBLIC,)

    def test_plain_http_is_refused(self):
        with pytest.raises(EndpointError, match="https"):
            validate_endpoint("http://api.example.com/v1")

    @pytest.mark.parametrize("url", ["ftp://x.example/v1", "file:///etc/passwd", "not a url", ""])
    def test_things_that_are_not_https_urls_are_refused(self, url):
        with pytest.raises(EndpointError):
            validate_endpoint(url)

    def test_credentials_in_the_url_are_refused(self):
        """`https://api.groq.com@10.0.0.1/` reads as Groq and connects to
        10.0.0.1. Userinfo has no honest use in a base URL."""
        with pytest.raises(EndpointError, match="credentials"):
            validate_endpoint("https://api.groq.com@10.0.0.1/v1")

    def test_a_query_string_or_fragment_is_refused(self):
        with pytest.raises(EndpointError):
            validate_endpoint("https://api.example.com/v1?x=1")
        with pytest.raises(EndpointError):
            validate_endpoint("https://api.example.com/v1#frag")

    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/v1",
            "https://10.0.0.5:8000/v1",
            "https://192.168.1.10/v1",
            "https://169.254.169.254/latest/meta-data",
            "https://[::1]/v1",
            "https://[fc00::1]/v1",
            "https://[::ffff:10.0.0.1]/v1",
            "https://0.0.0.0/v1",
        ],
    )
    def test_a_literal_internal_address_is_refused(self, url):
        with pytest.raises(EndpointError, match="not a public"):
            validate_endpoint(url)

    def test_a_name_that_resolves_to_an_internal_address_is_refused(self):
        """The string looks fine. The DNS answer is the attack."""
        with patch("socket.getaddrinfo", _resolver("10.0.0.5")):
            with pytest.raises(EndpointError, match="not a public") as e:
                validate_endpoint("https://internal.example.com/v1")
        # The refusal must not say *what* it resolved to. On a public
        # deployment that is a DNS oracle for the internal network:
        # submit `redis`, `mongo`, `vault`, read back their addresses.
        assert "10.0.0.5" not in str(e.value)

    def test_one_internal_answer_among_public_ones_is_enough_to_refuse(self):
        """A name with mixed answers is a name whose owner controls which
        one the connection gets. Refuse the lot."""
        with patch("socket.getaddrinfo", _resolver(PUBLIC, "127.0.0.1")):
            with pytest.raises(EndpointError, match="not a public"):
                validate_endpoint("https://mixed.example.com/v1")

    def test_a_name_that_does_not_resolve_says_so(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("nope")):
            with pytest.raises(EndpointError, match="resolve"):
                validate_endpoint("https://no-such-host.invalid/v1")

    def test_localhost_by_any_spelling_is_refused(self):
        with patch("socket.getaddrinfo", _resolver("127.0.0.1")):
            with pytest.raises(EndpointError):
                validate_endpoint("https://localhost/v1")
            with pytest.raises(EndpointError):
                validate_endpoint("https://LOCALHOST./v1")


class TestTheSelfHostedEscapeHatch:
    """An operator running EvalBench on their own machine may want it to
    talk to a vLLM on the LAN over plain http. That is their network and
    their call — behind a setting that defaults off and is documented as
    never-on-a-public-deployment."""

    def test_private_and_http_are_allowed_only_with_the_flag(self):
        with patch("socket.getaddrinfo", _resolver("127.0.0.1")):
            ep = validate_endpoint("http://localhost:8000/v1", allow_private=True)
        assert ep.url == "http://localhost:8000/v1"
        assert ep.ips == ("127.0.0.1",)
        with patch("socket.getaddrinfo", _resolver("10.0.0.5")):
            ep = validate_endpoint("http://10.0.0.5:8000/v1", allow_private=True)
        assert ep.ips == ("10.0.0.5",)

    def test_the_flag_does_not_open_anything_else(self):
        with pytest.raises(EndpointError):
            validate_endpoint("ftp://10.0.0.5/v1", allow_private=True)
        with pytest.raises(EndpointError, match="credentials"):
            validate_endpoint("http://a:b@10.0.0.5/v1", allow_private=True)


# ── 2. the pin ───────────────────────────────────────────────────


class TestThePinnedConnection:
    """The check happens *inside* connect, and the dial goes to the IP
    that passed. There is no window in which the name is resolved a
    second time by something that does not check."""

    @pytest.mark.asyncio
    async def test_it_dials_the_address_it_checked(self):
        backend = PinnedBackend()
        dialed = []

        async def fake_connect(host, port, **kw):
            dialed.append((host, port))
            return "stream"

        with patch("socket.getaddrinfo", _resolver(PUBLIC)), patch.object(
            PinnedBackend, "_dial", staticmethod(fake_connect)
        ):
            stream = await backend.connect_tcp("api.example.com", 443)
        assert stream == "stream"
        # Not the name — the checked address.
        assert dialed == [(PUBLIC, 443)]

    @pytest.mark.asyncio
    async def test_it_refuses_before_dialing_when_the_name_has_moved(self):
        """Validated at submission as public; by the time the worker
        connects, the record points inside. The dial must not happen."""
        backend = PinnedBackend()
        dial = AsyncMock()
        with patch("socket.getaddrinfo", _resolver("169.254.169.254")), patch.object(
            PinnedBackend, "_dial", staticmethod(dial)
        ):
            with pytest.raises(EndpointError, match="not a public"):
                await backend.connect_tcp("rebound.example.com", 443)
        dial.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_escape_hatch_reaches_the_pin_too(self):
        backend = PinnedBackend(allow_private=True)
        dialed = []

        async def fake_connect(host, port, **kw):
            dialed.append(host)
            return "stream"

        with patch("socket.getaddrinfo", _resolver("127.0.0.1")), patch.object(
            PinnedBackend, "_dial", staticmethod(fake_connect)
        ):
            await backend.connect_tcp("localhost", 8000)
        assert dialed == ["127.0.0.1"]

    @pytest.mark.asyncio
    async def test_when_one_checked_address_does_not_answer_the_next_is_tried(self):
        """A dual-stack name answers IPv6 first. On a host with no IPv6
        route that dial fails; the v4 answers would have worked. Every
        address passed the check, so any of them is safe to dial."""
        import httpcore

        backend = PinnedBackend()
        dialed = []

        async def flaky(host, port, **kw):
            dialed.append(host)
            if host == "2606:4700::1111":
                raise httpcore.ConnectError("no route")
            return "stream"

        with patch("socket.getaddrinfo", _resolver("2606:4700::1111", PUBLIC)), patch.object(
            PinnedBackend, "_dial", staticmethod(flaky)
        ):
            stream = await backend.connect_tcp("api.example.com", 443)
        assert stream == "stream"
        assert dialed == ["2606:4700::1111", PUBLIC]

    @pytest.mark.asyncio
    async def test_when_no_checked_address_answers_the_last_error_is_raised(self):
        import httpcore

        backend = PinnedBackend()

        async def dead(host, port, **kw):
            raise httpcore.ConnectError(f"{host} unreachable")

        with patch("socket.getaddrinfo", _resolver("8.8.8.8", PUBLIC)), patch.object(
            PinnedBackend, "_dial", staticmethod(dead)
        ):
            with pytest.raises(httpcore.ConnectError, match=PUBLIC):
                await backend.connect_tcp("api.example.com", 443)

    @pytest.mark.asyncio
    async def test_unix_sockets_are_not_a_way_around_it(self):
        backend = PinnedBackend()
        with pytest.raises(EndpointError):
            await backend.connect_unix_socket("/var/run/docker.sock")


# ── 3. the transport ─────────────────────────────────────────────


class TestTheGuardedTransport:
    def test_the_provider_client_does_not_follow_redirects(self):
        """A public host that answers 302 Location: http://10.0.0.1/ is
        the other half of every SSRF write-up. httpx defaults to not
        following; this pins that down so nobody turns it on for
        convenience later."""
        from evalbench.core.providers import get_provider

        with patch("socket.getaddrinfo", _resolver(PUBLIC)):
            p = get_provider("custom", base_url="https://api.example.com/v1")
        assert p._client.follow_redirects is False

    def test_the_provider_client_uses_the_pinned_backend(self):
        from evalbench.core.endpoint import GuardedTransport
        from evalbench.core.providers import get_provider

        with patch("socket.getaddrinfo", _resolver(PUBLIC)):
            p = get_provider("custom", base_url="https://api.example.com/v1")
        assert isinstance(p._client._transport, GuardedTransport)
        assert isinstance(p._client._transport._pool._network_backend, PinnedBackend)

    @pytest.mark.asyncio
    async def test_a_response_past_the_cap_is_cut_off(self):
        """A chat completion is a few kilobytes. An endpoint that streams
        gigabytes is not a chat endpoint, and the worker must not try to
        hold it in memory to find that out."""
        from evalbench.core.endpoint import MAX_RESPONSE_BYTES, GuardedTransport

        chunk = b"x" * 1024

        async def big():
            for _ in range(MAX_RESPONSE_BYTES // 1024 + 2):
                yield chunk

        t = GuardedTransport()
        stream = t._capped(big())
        got = 0
        with pytest.raises(EndpointError, match="too large"):
            async for part in stream:
                got += len(part)
        assert got <= MAX_RESPONSE_BYTES


# ── never with our key ───────────────────────────────────────────


class TestNeverWithOurKey:
    """The server's provider keys are for the providers they belong to.
    A custom endpoint gets the caller's key or none — an endpoint that
    receives whatever Authorization header we send would otherwise be a
    one-line key exfiltration."""

    def test_no_key_means_no_authorization_header(self, monkeypatch):
        from evalbench.core.providers import get_provider

        monkeypatch.setenv("GROQ_API_KEY", "gsk_ours")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_ours")
        with patch("socket.getaddrinfo", _resolver(PUBLIC)):
            p = get_provider("custom", base_url="https://api.example.com/v1")
        assert "authorization" not in {k.lower() for k in p._client.headers}

    def test_the_callers_key_is_sent_as_a_bearer(self):
        from evalbench.core.providers import get_provider

        with patch("socket.getaddrinfo", _resolver(PUBLIC)):
            p = get_provider(
                "custom", base_url="https://api.example.com/v1", api_key="theirs"
            )
        assert p._client.headers["authorization"] == "Bearer theirs"

    def test_custom_without_a_url_is_an_error_not_a_default(self):
        from evalbench.core.providers import get_provider

        with pytest.raises(ValueError, match="base_url"):
            get_provider("custom")

    def test_custom_is_never_configured_on_the_server_side(self):
        """`configured_providers` answers "can this server run it on its
        own key". For custom the answer is no by construction: there is
        no server key for a URL nobody has seen yet."""
        from evalbench.core.providers import available_providers, configured_providers

        assert "custom" in available_providers()
        assert "custom" not in configured_providers()
