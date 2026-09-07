FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

# sentence-transformers pulls torch as a dependency; PyPI's default wheel is the
# CUDA/GPU build - several GB of unnecessary nvidia-* packages on this CPU-only box
# (see PROGRESS.md for the disk-exhaustion incident this caused in the Airflow
# image). Install the CPU wheel explicitly first so sentence-transformers finds an
# already-satisfied torch instead of pulling the GPU one in.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
# --proxy-headers/--forwarded-allow-ips: this container is never reachable except
# through Caddy (no port published to the host, only `expose`), so trusting
# X-Forwarded-For from any peer here is safe - it's always Caddy. Without this,
# request.client.host (and therefore rate limiting, see main.py) would see every
# request as coming from Caddy's own container IP instead of the real client.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
