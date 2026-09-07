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
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
