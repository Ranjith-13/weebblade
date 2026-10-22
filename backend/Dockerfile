# The API, as one self-contained image.
#
# BUILT FROM THE REPOSITORY ROOT, not from backend/. The app imports
# ai.search.query to answer /search, so the image needs ai/ as well as
# backend/app/ - and a build context of backend/ cannot see a sibling. On the
# server this was papered over by a bind mount (./ai:/app/ai in
# docker-compose.yml); an image that has to run somewhere nobody configured
# needs the code actually in it. compose passes the same context now, so the two
# build the same thing.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    DATA_DIR=/data \
    FASTEMBED_CACHE_PATH=/opt/fastembed

# libstdc++6, because onnxruntime needs it and python:3.12-slim may not have it.
# Verified rather than guessed: every shared object in the cp312 onnxruntime
# wheel declares libstdc++.so.6 and libgcc_s.so.1 and nothing else outside libc
# (no libgomp, despite that being the usual story). CPython links libgcc_s but
# it is C, so it has no reason to pull libstdc++ - and the slim image's build
# stage purges g++. "Probably already there" is not something to find out from a
# crash loop on a build server, and this costs about 2 MB.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .

# No torch here any more, and that is the point of this image fitting where it
# now runs. It used to install the CPU wheel explicitly to stop PyPI's default
# CUDA build filling the disk; the API embeds one query at a time through ONNX
# instead (ai/search/embed.get_query_embedder), which is 406 MB resident against
# 868 and needs neither torch nor the workaround.
RUN pip install --no-cache-dir -r requirements.txt

# The model's weights, baked in rather than fetched on first use. 90 MB, and it
# buys two things: a cold start that does not wait on Hugging Face, and a
# service that keeps working when Hugging Face is down - which for a container
# that is rebuilt from this image every time it wakes would otherwise be a
# dependency on every single wake-up.
RUN python -c "from fastembed import TextEmbedding; \
    TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2')"

COPY backend/app ./app
COPY ai ./ai

# Non-root, and /data writable by it: the warehouse is downloaded into /data at
# startup now (backend/app/warehouse.py) rather than mounted, so this process
# genuinely needs to write there - the one place it writes anything.
RUN useradd --create-home --uid 10001 weebblade \
    && mkdir -p /data \
    && chown -R weebblade:weebblade /data /opt/fastembed
USER weebblade

EXPOSE 8000

# $PORT because the host picks it: Render injects one (10000 by default) and a
# service that ignores it never passes a health check. 8000 when nothing says
# otherwise, which is what compose and every local run expect.
#
# --proxy-headers/--forwarded-allow-ips: this process is never reachable
# directly - behind Caddy on the server, behind Render's proxy now - so the
# peer is always that proxy and trusting its X-Forwarded-For is what makes
# rate limiting see real client addresses instead of one internal IP.
#
# WHICH PEER TO TRUST IS NOT WHICH ENTRY TO READ, and this comment used to
# stop at the first. X-Forwarded-For is a list every proxy APPENDS to, so the
# address Render saw is at the END and anything to the left of it is whatever
# the caller typed. uvicorn 0.34.0 rewrites scope["client"] from the FIRST
# entry - verified against the pinned version - so request.client.host was
# attacker-controlled, and a limit keyed on it was no limit at all.
#
# The limiter no longer reads it: backend/app/limiter.client_address counts
# TRUSTED_PROXY_HOPS back from the right instead. These flags stay because
# anything else reading request.client.host still wants the proxy parsed.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
