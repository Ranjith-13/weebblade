#!/usr/bin/env bash
# Runs the test suite against the DuckDB the SERVICE runs, not the one this
# machine can install.
#
# WHY THIS EXISTS
#
# airflow/requirements.txt pins duckdb==1.1.3, and the published warehouse is
# written by it: a file written by a newer DuckDB is a file the API cannot open.
# But 1.1.3 ships no wheel for Python 3.14, which is what this machine has, so
# local runs used 1.5.6 and CI used 1.1.3 - and the two do not always agree.
#
# That gap cost three round trips through CI in a single day:
#
#   * two index tests assumed the order anime_media_latest returns rows in.
#     1.5.6 returned them in key order and 1.1.3 did not, so the tests passed
#     here and failed there.
#   * a memory test provoked a real exhaustion with a sort too big for a 16MB
#     limit. 1.5.6 raises OutOfMemoryException; 1.1.3 completes the same query
#     in twelve seconds. Again green locally, red in CI.
#
# Each took a push, a wait and a log read to learn something an interpreter on
# this machine could have said in twenty-five seconds.
#
# HOW IT GETS 1.1.3
#
# Any CPython 3.10 to 3.13 will do - those are the versions duckdb 1.1.3 ships
# manylinux wheels for. If one is on PATH it is used. If not, and pacman is
# available, the distro's own python313 package is fetched and unpacked into
# .venv-pinned/toolchain WITHOUT root: it is the same bits pacman would install,
# just not into /usr. An unpacked CPython needs to be told where its library and
# standard library are, which is what the LD_LIBRARY_PATH and PYTHONHOME below
# are for, and why running the suite goes through this script rather than
# calling the venv's python directly.
#
# NOT A REPLACEMENT FOR CI, which installs requirements-dev.txt in full on the
# Python the pipeline uses. This installs what the tests need to exercise DuckDB
# and the API, which is the part that drifts. Three tests skip for want of the
# embedding backends; CI runs those.
#
#   scripts/pinned-tests.sh setup     build or rebuild the environment
#   scripts/pinned-tests.sh           run the whole suite
#   scripts/pinned-tests.sh tests/test_backend_db.py -q     pass pytest any args
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_DIR=".venv-pinned"
TOOLCHAIN="$ENV_DIR/toolchain"
VENV="$ENV_DIR/venv"

# Kept beside the versions they mirror. Everything the suite imports that is not
# stdlib; the heavy optional ones (torch, pyspark, sentence-transformers) are
# deliberately absent - see the note above about what this is not.
PINNED=(
  duckdb==1.1.3 pyarrow==23.0.1 "pandas>=2.2.3" numpy requests==2.34.2
  fastapi==0.141.1 httpx==0.28.1 slowapi==0.1.9 pytest==8.3.4
)

py_ok() {  # a CPython duckdb 1.1.3 has a wheel for
  "$1" -c 'import sys; raise SystemExit(0 if (3,10) <= sys.version_info < (3,14) else 1)' 2>/dev/null
}

find_python() {
  for v in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$v" >/dev/null && py_ok "$v"; then command -v "$v"; return; fi
  done
  if [ -x "$TOOLCHAIN/usr/bin/python3.13" ]; then echo "$TOOLCHAIN/usr/bin/python3.13"; return; fi
  return 1
}

fetch_toolchain() {
  command -v pacman >/dev/null || {
    echo "No CPython 3.10-3.13 on PATH and no pacman to fetch one." >&2
    echo "Install any of python3.10 .. python3.13 and re-run: duckdb 1.1.3" >&2
    echo "publishes manylinux wheels for exactly those." >&2
    exit 1
  }
  local url
  url="$(pacman -Sp python313 2>/dev/null | head -1)"
  [ -n "$url" ] || { echo "pacman could not resolve python313" >&2; exit 1; }
  echo "Fetching $url"
  mkdir -p "$TOOLCHAIN"
  curl -sSL -o "$ENV_DIR/python313.pkg.tar.zst" "$url"
  tar -I zstd -xf "$ENV_DIR/python313.pkg.tar.zst" -C "$TOOLCHAIN"
  rm -f "$ENV_DIR/python313.pkg.tar.zst"
}

setup() {
  mkdir -p "$ENV_DIR"
  local py
  py="$(find_python)" || { fetch_toolchain; py="$TOOLCHAIN/usr/bin/python3.13"; }
  echo "Using $py"
  rm -rf "$VENV"
  make_venv "$py"
  with_runtime "$VENV/bin/python" -m pip install -q --upgrade pip
  with_runtime "$VENV/bin/python" -m pip install -q "${PINNED[@]}"
  echo -n "duckdb now local: "
  with_runtime "$VENV/bin/python" -c 'import duckdb, sys; print(duckdb.__version__, "on CPython", sys.version.split()[0])'
}

# An unpacked CPython cannot find its shared library unaided, so everything
# that runs one goes through here.
with_runtime() {
  if [ -d "$TOOLCHAIN/usr/lib" ]; then
    LD_LIBRARY_PATH="$PWD/$TOOLCHAIN/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$@"
  else
    "$@"
  fi
}

# PYTHONHOME ON TOP, AND ONLY FOR THIS ONE CALL. An unpacked interpreter needs
# telling where its standard library is before it can build a venv. The venv it
# builds then carries its own, and leaving PYTHONHOME set afterwards points
# every later call back at the toolchain's site-packages - where none of the
# pinned dependencies are installed.
make_venv() {
  if [ -d "$TOOLCHAIN/usr/lib" ]; then
    PYTHONHOME="$PWD/$TOOLCHAIN/usr" with_runtime "$1" -m venv "$VENV"
  else
    "$1" -m venv "$VENV"
  fi
}

if [ "${1:-}" = "setup" ]; then
  setup
  exit 0
fi

[ -x "$VENV/bin/python" ] || { echo "No environment yet - run: scripts/pinned-tests.sh setup" >&2; exit 1; }
with_runtime "$VENV/bin/python" -m pytest "${@:-tests/}"
