#!/usr/bin/env bash
# Pulls the pipeline's state off GitHub, onto this machine.
#
# WHAT CHANGED, AND WHY THIS IS NOT THE SCRIPT IT WAS
#
# It used to open a security-group rule, SSH to an EC2 instance, and copy back
# the archives the server wrote to its own EBS volume. That instance has been
# stopped since 2026-10-07, and the pipeline now runs on GitHub Actions, which
# publishes its state as a release asset after every run (pipeline/state.py). So
# the thing worth copying is no longer on a server.
#
# The reason to copy it at all has not changed and is the whole point: a year of
# ingested history should not live in one company's account. It lived on an EBS
# volume and here; now it lives in GitHub releases and here.
#
# WHAT IT TAKES
#
#   state-<date>.tar.gz      processed/, identity/, raw/, digests/ - what a run
#                            needs to carry on, and everything that cannot be
#                            rebuilt (a digest is what a model wrote about one
#                            week; asking again next week writes something else).
#   warehouse-<date>.duckdb  the materialised catalogue and vectors, when a
#                            weekly run published one. Derived, so losing it
#                            costs a rebuild rather than data.
#
# It leaves the server-era archives (data-*.tar.gz, postgres-*.sql.gz) alone.
# They cover something the release state does not - Airflow's own metadata DB -
# and pruning by date would quietly delete the last copy of them.
#
# Deliberately writes OUTSIDE the repo. A backup that lands inside a working
# tree eventually gets committed.
#
# RESTORING
#
#   tar -xzf ~/weebblade-backups/state-YYYY-MM-DD.tar.gz -C /some/where
#
# That expands to processed/, identity/, raw/ and digests/. The parquet under processed/
# is the source of truth and is fully portable; rebuild a warehouse from it
# anywhere, which takes about a second:
#
#   python -c "from pathlib import Path; from processing.duckdb_catalog import \
#     refresh_catalog; print(refresh_catalog(Path('DIR'), Path('DIR/new.duckdb')))"
#
# then `python -m ai.search.build_index --db-path DIR/new.duckdb` if search
# needs to answer. The warehouse-<date>.duckdb here is the materialised one and
# carries no absolute paths, so unlike the server-era copies it can be opened
# anywhere as it is.
#
# THE FILE THIS MOST NEEDS TO PROTECT: identity/registry.parquet. It maps every
# source key ever seen to a stable title identity, and it is state rather than
# derivation - no rerun can rebuild it, because identities are minted once and
# remembered (processing/identity.py explains why no stateless scheme works).
# Lose it and the pipeline still runs, but it mints a fresh identity for every
# title, and every stored reference to one - a shared link, a franchise edge -
# points at nothing.
#
# Usage:
#   ./scripts/weebblade-backup.sh            # pull the newest, verify, prune
set -euo pipefail

DEST="${WEEBBLADE_BACKUP_DIR:-$HOME/weebblade-backups}"
REPO="${WEEBBLADE_REPO:-Ranjith-13/weebblade}"
KEEP_DAYS="${WEEBBLADE_BACKUP_KEEP_DAYS:-14}"
NETWORK_WAIT="${WEEBBLADE_NETWORK_WAIT:-300}"
CUTOFF="$(date -d "$KEEP_DAYS days ago" +%F)"

fail() { echo "weebblade-backup: $*" >&2; exit 1; }
note() { echo "weebblade-backup: $*"; }

# A timer that fires at boot or on resume can beat the network up. The unit
# cannot wait on network-online.target - that is a system target, and a user
# unit does not wait on it - which is how the 2026-09-14 run failed. So wait
# here, and name the problem rather than reporting "nothing found".
waited=0
until getent hosts api.github.com >/dev/null 2>&1; do
  [ "$waited" -ge "$NETWORK_WAIT" ] && fail "no DNS for api.github.com after ${NETWORK_WAIT}s - the network is not up"
  sleep 10
  waited=$((waited + 10))
done

# gh authenticates through the keyring here, which is unlocked only while there
# is a desktop session. The timer is a user unit without lingering, so it fires
# only in one anyway - but when this does fail it must say so, rather than
# producing an empty backup that looks like success.
gh auth status >/dev/null 2>&1 || fail "gh is not authenticated (keyring locked, or no session) - nothing pulled"

mkdir -p "$DEST"

tag="$(gh release list --repo "$REPO" --limit 100 --json tagName,createdAt \
  --jq 'map(select(.tagName | startswith("state-"))) | sort_by(.createdAt) | reverse | .[0].tagName // empty')"
[ -n "$tag" ] || fail "no state release published yet in $REPO"
date_of="${tag#state-}"
state_local="$DEST/state-$date_of.tar.gz"

if [ -f "$state_local" ] && tar tzf "$state_local" >/dev/null 2>&1; then
  note "already holding a good copy of $tag"
else
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  gh release download "$tag" --repo "$REPO" --pattern "state.tar.gz" --dir "$tmp" \
    || fail "could not download state.tar.gz from $tag"
  # Verified before it replaces anything. A truncated download that silently
  # becomes the newest backup is worse than no backup, because it looks fine.
  tar tzf "$tmp/state.tar.gz" >/dev/null 2>&1 \
    || fail "the archive from $tag is corrupt - keeping what was already here"
  mv "$tmp/state.tar.gz" "$state_local"
  note "pulled $tag ($(du -h "$state_local" | cut -f1))"

  # Only the weekly run publishes one, so its absence is ordinary.
  if gh release download "$tag" --repo "$REPO" --pattern "warehouse.duckdb" --dir "$tmp" >/dev/null 2>&1; then
    mv "$tmp/warehouse.duckdb" "$DEST/warehouse-$date_of.duckdb"
    note "pulled the warehouse too ($(du -h "$DEST/warehouse-$date_of.duckdb" | cut -f1))"
  fi
fi

# Only what this script writes: the server-era archives are a different scheme
# covering different things, and are not ours to delete.
pruned=0
for f in "$DEST"/state-*.tar.gz "$DEST"/warehouse-*.duckdb; do
  [ -e "$f" ] || continue
  when="$(basename "$f" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1 || true)"
  [ -n "$when" ] || continue
  if [[ "$when" < "$CUTOFF" ]]; then
    rm -f "$f"
    pruned=$((pruned + 1))
  fi
done
[ "$pruned" -eq 0 ] || note "pruned $pruned copy(ies) older than $KEEP_DAYS days"

note "holding $(ls -1 "$DEST"/state-*.tar.gz 2>/dev/null | wc -l) state archive(s) in $DEST"
