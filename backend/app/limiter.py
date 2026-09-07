from slowapi import Limiter
from slowapi.util import get_remote_address

# get_remote_address reads request.client.host - only reflects the real client IP
# because uvicorn is run with --proxy-headers (see Dockerfile), which parses
# X-Forwarded-For from Caddy. 60/minute default is generous for normal use, tight
# enough to blunt casual scraping/abuse; /search gets a stricter limit of its own
# since it runs the embedding model on every call.
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
