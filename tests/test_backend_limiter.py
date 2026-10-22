"""Who the rate limiter thinks you are.

THE LEFTMOST ENTRY OF X-Forwarded-For IS ATTACKER-CONTROLLED. Each proxy
appends the peer it received from, so a header arriving as "1.2.3.4, 203.0.113.9"
means the caller claimed 1.2.3.4 and the proxy saw 203.0.113.9. Reading the
first entry keys the limit on a value the caller chose, and a different one per
request is an unlimited budget.

That is not hypothetical here: uvicorn 0.34.0's ProxyHeadersMiddleware takes
the first entry, verified against the pinned version, and the API runs it with
--forwarded-allow-ips='*'. get_remote_address reads what that middleware wrote,
so the limit was keyed on a spoofable value until this file existed.

It matters most on /search, capped at 20/minute precisely because it runs the
embedding model on every call, on a container with 0.1 CPU and 512 MB that
peaks at 406 of them serving an ordinary page.
"""

import pytest

from backend.app import limiter as mod


class _Request:
    """Enough of a Starlette request for the key function."""

    def __init__(self, headers=None, peer="10.0.0.1"):
        self.headers = headers or {}
        self.client = type("Client", (), {"host": peer})()


def test_a_claimed_address_does_not_move_the_key():
    """The whole point. The caller prepends what it likes; the proxy appends
    what it saw, and that is what counts."""
    real = mod.client_address(_Request({"x-forwarded-for": "203.0.113.9"}))
    spoofed = mod.client_address(_Request({"x-forwarded-for": "1.2.3.4, 203.0.113.9"}))

    assert real == spoofed == "203.0.113.9"


@pytest.mark.parametrize("claimed", ["9.9.9.9, 8.8.8.8", "::1", "not-an-address", " , ,"])
def test_no_prefix_changes_who_you_are(claimed):
    """Varied junk, because an attacker varies it: the budget is per key, so the
    attack is not one clever value but a different one every request."""
    header = f"{claimed}, 203.0.113.9" if claimed.strip(" ,") else "203.0.113.9"

    assert mod.client_address(_Request({"x-forwarded-for": header})) == "203.0.113.9"


def test_without_the_header_the_socket_peer_is_used():
    """A direct local run has no proxy in front of it and no header to read."""
    assert mod.client_address(_Request({}, peer="192.0.2.7")) == "192.0.2.7"


def test_a_header_shorter_than_the_hop_count_is_not_an_error(monkeypatch):
    """A proxy that did not append what it should have leaves a request that has
    done nothing wrong. The leftmost is then the least-wrong answer; refusing to
    serve it would turn a misconfiguration into an outage."""
    monkeypatch.setattr(mod, "TRUSTED_PROXY_HOPS", 3)

    assert mod.client_address(_Request({"x-forwarded-for": "203.0.113.9"})) == "203.0.113.9"


def test_the_hop_count_is_the_number_of_proxies_in_front(monkeypatch):
    """Two proxies means the reader is two from the right. Configurable because
    it is a fact about deployment, not about this code: Render is one hop, and a
    second one in front would silently bucket every reader together."""
    monkeypatch.setattr(mod, "TRUSTED_PROXY_HOPS", 2)
    header = {"x-forwarded-for": "1.2.3.4, 203.0.113.9, 10.1.1.1"}

    assert mod.client_address(_Request(header)) == "203.0.113.9"


def test_the_limiter_uses_this_and_not_the_rewritten_peer():
    """get_remote_address reads what ProxyHeadersMiddleware wrote, which is the
    spoofable first entry. Wiring is the whole fix, so it is asserted."""
    assert mod.limiter._key_func is mod.client_address
