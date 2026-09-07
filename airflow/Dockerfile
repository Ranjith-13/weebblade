FROM apache/airflow:2.10.4-python3.12

# PySpark needs a JVM. The base image runs as a non-root 'airflow' user by default,
# so switch to root for the apt install and back afterward.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/default-java
USER airflow

COPY requirements.txt /requirements.txt

# sentence-transformers pulls in torch as a dependency, and PyPI's default torch
# wheel is the CUDA/GPU build - several GB of nvidia-* CUDA libraries that are
# useless on this CPU-only box and were the actual cause of "no space left on
# device" mid-build. Installing the CPU-only wheel first satisfies that dependency
# before sentence-transformers gets a chance to pull the GPU one in.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /requirements.txt
