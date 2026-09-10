#!/usr/bin/env bash
# Pulls the server's nightly backups onto this machine.
#
# Why this exists: the server already backs itself up (~/backup.sh, 02:00 daily,
# 7-day retention), but everything it writes lives on the same EBS volume as the
# data it is protecting. That covers a bad deploy or an accidental delete. It
# covers nothing about losing the instance, and the instance cannot be rebuilt
# from code - infra/terraform carries prevent_destroy precisely because the box
# was provisioned by hand.
#
# So the whole system's survival rests on one volume in one availability zone.
# The entire dataset is ~21 MB. This is the cheapest risk reduction available in
# the project and it stays that way whether or not S3 ever happens: a copy on a
# different machine, in a different country, is off-instance by any definition.
#
# S3 would be better (it does not need a laptop to be awake) and is the intended
# end state, but neither weebblade-ci-sg nor weebblade-terraform has any S3
# permission, so it needs an IAM policy that only the account owner can add.
# Waiting for that is not a reason to hold zero off-instance copies today.
#
# Usage:
#   ./scripts/weebblade-backup.sh            # pull, verify, prune
#   ./scripts/weebblade-backup.sh --verify   # verify what is already local, pull nothing
#
# Deliberately writes OUTSIDE the repo. A backup that lands inside a working tree
# eventually gets committed, and this contains the warehouse and a Postgres dump.
#
# RESTORING - verified end to end on 2026-09-10, not assumed:
#
#   tar -xzf ~/weebblade-backups/data-YYYY-MM-DD.tar.gz -C /some/where
#
# The archive expands to data/{processed,raw,chroma,digests} plus warehouse.duckdb.
#
# Do NOT trust the restored warehouse.duckdb anywhere other than a host that mounts
# the data directory at /data. DuckDB bakes the absolute parquet path into each
# view at CREATE VIEW time (processing/duckdb_catalog.py says so, and it is why the
# compose file mounts /data rather than /opt/airflow/data), so a warehouse restored
# to any other path has views that all resolve to nothing. It fails by returning
# no rows, not by erroring, which is the worst way for it to fail.
#
# The parquet under data/processed is the actual source of truth and it is fully
# portable. Rebuild the warehouse from it anywhere:
#
#   python -c "from pathlib import Path; from processing.duckdb_catalog import \
#     refresh_catalog; print(refresh_catalog(Path('DIR/data'), Path('DIR/new.duckdb')))"
#
# That path was exercised on a machine that has never run the pipeline: 475 rows
# across both seasons came back intact, scores included.
#
# The Chroma index and the digests are derived too - rebuildable from the warehouse
# via ai.search.build_index and ai.digest.generate - so losing them costs a rerun,
# not data.
#
# ONE EXCEPTION, and it is the file this backup most needs to protect:
# data/identity/registry.parquet. It maps every source key ever seen to a stable
# title identity, and it is state rather than derivation - no rerun can rebuild
# it, because identities are minted once and remembered (processing/identity.py
# explains why no stateless scheme works). Restore it with everything else. If
# it is lost, the pipeline still runs, but it mints a fresh identity for every
# title and every stored reference to one - a shared link, a franchise edge, a
# watchlist entry - stops resolving at once.
set -euo pipefail

DEST="${WEEBBLADE_BACKUP_DIR:-$HOME/weebblade-backups}"
KEEP="${WEEBBLADE_BACKUP_KEEP:-14}"
REMOTE_DIR="${WEEBBLADE_REMOTE_BACKUP_DIR:-~/backups}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH="$SCRIPT_DIR/weebblade-ssh.sh"

log() { echo "[$(date +%H:%M:%S)] $*" >&2; }
fail() { echo "ERROR: $*" >&2; exit 1; }

# A gzip file that does not pass this is not a backup, it is a file. Checked on
# every pull rather than at restore time, because a corrupt archive discovered
# during a restore is discovered at the worst possible moment.
verify_archive() {
  local f="$1"
  gzip -t "$f" 2>/dev/null || return 1
  tar -tzf "$f" >/dev/null 2>&1 || return 1
  return 0
}

verify_all() {
  local ok=0 bad=0
  shopt -s nullglob
  for f in "$DEST"/*.tar.gz; do
    if verify_archive "$f"; then ok=$((ok + 1)); else bad=$((bad + 1)); echo "  CORRUPT: $f" >&2; fi
  done
  for f in "$DEST"/*.sql.gz; do
    if gzip -t "$f" 2>/dev/null; then ok=$((ok + 1)); else bad=$((bad + 1)); echo "  CORRUPT: $f" >&2; fi
  done
  shopt -u nullglob
  log "verified: $ok intact, $bad corrupt"
  [[ "$bad" -eq 0 ]] || fail "$bad corrupt archive(s) in $DEST"
}

if [[ "${1:-}" == "--verify" ]]; then
  [[ -d "$DEST" ]] || fail "no local backup directory at $DEST"
  verify_all
  exit 0
fi

mkdir -p "$DEST"

# One SSH session to list, rather than one per file: each invocation of
# weebblade-ssh.sh opens and closes a security-group rule, which takes seconds
# and churns the group's audit trail.
log "listing remote backups"
REMOTE_FILES="$("$SSH" "ls -1 $REMOTE_DIR/*.gz 2>/dev/null" || true)"
[[ -n "$REMOTE_FILES" ]] || fail "no backups found in $REMOTE_DIR on the server"

pulled=0 skipped=0
while IFS= read -r remote_path; do
  [[ -n "$remote_path" ]] || continue
  name="$(basename "$remote_path")"
  local_path="$DEST/$name"

  # Backups are immutable once written - a given date's archive never changes -
  # so an existing verified copy is skipped rather than re-downloaded.
  if [[ -f "$local_path" ]] && { [[ "$name" == *.sql.gz ]] && gzip -t "$local_path" 2>/dev/null || verify_archive "$local_path"; }; then
    skipped=$((skipped + 1))
    continue
  fi

  log "pulling $name"
  # Stream through the existing helper rather than scp, so the security-group
  # authorize/revoke and key resolution stay in exactly one place. Writes to a
  # .part file first: an interrupted transfer must never look like a good backup.
  # </dev/null is load-bearing: ssh reads stdin, and stdin here is the list of
  # files this loop is iterating. Without it the first transfer swallows every
  # remaining line and the run "succeeds" having fetched exactly one file.
  if ! "$SSH" "cat '$remote_path'" < /dev/null > "$local_path.part"; then
    rm -f "$local_path.part"
    fail "transfer failed for $name"
  fi

  if [[ "$name" == *.sql.gz ]]; then
    gzip -t "$local_path.part" 2>/dev/null || { rm -f "$local_path.part"; fail "$name arrived corrupt"; }
  else
    verify_archive "$local_path.part" || { rm -f "$local_path.part"; fail "$name arrived corrupt"; }
  fi

  mv "$local_path.part" "$local_path"
  pulled=$((pulled + 1))
done <<< "$REMOTE_FILES"

log "pulled $pulled, skipped $skipped already present"

# Keep more history locally than the server does (7 days). The point of a second
# location is to survive mistakes noticed late, and a week is not long for that.
deleted=0
shopt -s nullglob
for f in $(ls -1t "$DEST"/*.gz 2>/dev/null | tail -n +$((KEEP + 1))); do
  rm -f "$f"; deleted=$((deleted + 1))
done
shopt -u nullglob
[[ "$deleted" -eq 0 ]] || log "pruned $deleted beyond the newest $KEEP"

verify_all
log "backup directory: $DEST ($(du -sh "$DEST" | cut -f1))"
