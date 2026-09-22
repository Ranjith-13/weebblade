#!/usr/bin/env bash
# Runs the tests that need a real SparkSession against the code in THIS working
# tree, on the server, before it is pushed.
#
# Why this exists: the merge (processing/consolidate.py) is a window function
# over every column, which is exactly the kind of thing that looks right and
# behaves differently at runtime, so tests/test_consolidate_merge.py asks for a
# real Spark. PySpark needs a JVM, there isn't one on the laptop, and the server
# has one inside the Airflow image. Every change to the merge has to clear this
# suite first - twice in two days it caught a test fixture that did not look
# like real data, and once a merge that silently did nothing.
#
# It runs in a THROWAWAY container from the same image, not in the running
# scheduler: production is left exactly as it was, and pytest - which is a test
# dependency and deliberately not in the image - is installed into the copy that
# is about to be deleted. A previous session installed it into the live
# scheduler by hand, which worked until the next rebuild and told nobody.
#
# Usage:
#   ./scripts/weebblade-spark-tests.sh                       # the merge suite
#   ./scripts/weebblade-spark-tests.sh tests/test_matching.py -k premiere
set -euo pipefail

cd "$(dirname "$0")/.."
SSH="./scripts/weebblade-ssh.sh"
IMAGE="${WEEBBLADE_AIRFLOW_IMAGE:-weebblade-airflow:2.10.4}"
REMOTE="/tmp/weebblade-spark-tests"
TARGET=("${@:-tests/test_consolidate_merge.py}")

echo "Sending processing/, ingestion/, ai/ and tests/ to the server..."
# The whole tree the tests import, not just the file under test: these modules
# import each other, and a suite run against half this tree and half the
# deployed one proves nothing about either.
tar czf - processing ingestion ai tests | $SSH "
  set -e
  rm -rf $REMOTE && mkdir -p $REMOTE
  tar xzf - -C $REMOTE
  chmod -R a+rX $REMOTE
"

echo "Running ${TARGET[*]} in a throwaway container..."
# python -m pytest, not bare pytest: -m puts the working directory first on
# sys.path, ahead of the image's PYTHONPATH=/opt/airflow, so the suite tests the
# code just copied rather than what is deployed. No cache provider: the mount is
# read-only to the container's user and a cache it cannot write is a warning per
# test file.
$SSH "sudo docker run --rm -v $REMOTE:/work -w /work -e PYTHONPATH=/work $IMAGE \
  bash -c 'pip install --quiet pytest >/dev/null 2>&1; python -m pytest ${TARGET[*]} -q -p no:cacheprovider'"

echo "Cleaning up..."
$SSH "rm -rf $REMOTE"
