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
RUN pip install --no-cache-dir -r /requirements.txt
