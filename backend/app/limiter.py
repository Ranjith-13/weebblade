import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

# HOW MANY PROXIES SIT BETWEEN A READER AND THIS PROCESS.
#
# One: Render's edge. It was Caddy on the server before, also one. The number
# matters because X-Forwarded-For is a list that each proxy APPENDS its peer to,
# so counting from the right is counting back through hops we trust, and
# counting from the left is reading whatever the client typed.
TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))


def client_address(request: Request) -> str:
    """The address the nearest trusted proxy actually saw, not the one claimed.

    THE LEFTMOST ENTRY OF X-Forwarded-For IS ATTACKER-CONTROLLED, and reading it
    is how a rate limit keyed on "client IP" becomes no rate limit at all. A
    reader sends `X-Forwarded-For: 1.2.3.4`, Render appends the address it saw,
    and the header arrives as `1.2.3.4, <real>`. uvicorn 0.34.0's
    ProxyHeadersMiddleware takes the FIRST entry - verified against the pinned
    version, not assumed - so request.client.host became 1.2.3.4 and
    get_remote_address keyed the limit on a value the caller chose. A different
    one per request is an unlimited budget.

    That mattered most on /search, which is capped at 20/minute precisely
    because it runs the embedding model on every call, on a container with 0.1
    CPU and 512 MB that peaks at 406 of them serving an ordinary page.

    So the entry TRUSTED_PROXY_HOPS from the right is used instead: with one
    proxy that is the address Render saw its peer at, which is the reader. A
    client can prepend anything it likes to the left of that and move nothing.
    Shorter than the hop count means a proxy did not append what it should have;
    the leftmost is then the least-wrong answer and is used rather than raising
    on a request that has done nothing wrong.

    Falls back to the socket peer where there is no header at all, which is what
    a direct local run looks like.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        hops = [part.strip() for part in forwarded.split(",") if part.strip()]
        if hops:
            return hops[-TRUSTED_PROXY_HOPS] if len(hops) >= TRUSTED_PROXY_HOPS else hops[0]
    return get_remote_address(request)


# 60/minute default is generous for normal use, tight enough to blunt casual
# scraping; /search gets a stricter limit of its own since it runs the embedding
# model on every call.
limiter = Limiter(key_func=client_address, default_limits=["60/minute"])
