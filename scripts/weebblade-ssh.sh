#!/usr/bin/env bash
# Opens SSH to the WeebBlade EC2 box for this machine's current public IP only,
# for exactly as long as the session lasts, then closes it again.
#
# Why this exists: the security group has no standing SSH rule for a home
# address because residential IPs rotate (confirmed the hard way - the pinned
# one changed within a few hours, which broke direct SSH while leaving the site
# and CI/CD deploys untouched). This is the same authorize/revoke pattern
# .github/workflows/deploy.yml already uses for GitHub's runners, just driven
# from a laptop instead.
#
# Uses the weebblade-ci-sg IAM profile, which can only touch ingress rules on
# this one security group - deliberately not the Terraform credentials, which
# have full EC2 access.
#
# Usage:
#   ./scripts/weebblade-ssh.sh                    # interactive shell
#   ./scripts/weebblade-ssh.sh 'docker ps'        # run one command and exit
set -euo pipefail

SG_ID="${WEEBBLADE_SG_ID:-sg-029497100335e0355}"
AWS_PROFILE_NAME="${WEEBBLADE_AWS_PROFILE:-weebblade-ci-sg}"
REGION="${AWS_DEFAULT_REGION:-ap-south-2}"
HOST="${WEEBBLADE_HOST:-weebblade.duckdns.org}"
USER_NAME="${WEEBBLADE_USER:-ubuntu}"
KEY="${WEEBBLADE_KEY:-}"

# Resolve the AWS CLI. On Windows/Git Bash a pip-installed CLI is `aws.cmd` and
# often isn't on PATH as plain `aws`, so fall back rather than failing with a
# confusing "command not found".
AWS_BIN="${WEEBBLADE_AWS_BIN:-}"
if [[ -z "$AWS_BIN" ]]; then
  for candidate in \
      aws \
      aws.cmd \
      "$HOME"/AppData/Roaming/Python/Python*/Scripts/aws.cmd \
      "/c/Program Files/Amazon/AWSCLIV2/aws.exe"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      AWS_BIN="$candidate"; break
    fi
    # -f not -x: Windows .cmd/.exe files aren't execute-flagged under Git Bash,
    # so an -x test silently rejects a perfectly working CLI.
    if [[ -f "$candidate" ]]; then
      AWS_BIN="$candidate"; break
    fi
  done
  if [[ -z "$AWS_BIN" ]]; then
    echo "AWS CLI not found. Install it, or set WEEBBLADE_AWS_BIN to its path." >&2
    exit 1
  fi
fi

aws_sg() {
  "$AWS_BIN" --profile "$AWS_PROFILE_NAME" --region "$REGION" "$@"
}

# Resolve the SSH key the same way. The key is per-machine and there is no single
# right name for it: the machine that created the EC2 instance has the original
# weebblade-key.pem, while any machine added later to authorized_keys has a
# locally-generated key under whatever name its owner chose. Guessing one path
# and failing with ssh's opaque "no such identity" is worse than looking.
if [[ -z "$KEY" ]]; then
  for candidate in \
      "$HOME/.ssh/weebblade-key.pem" \
      "$HOME/.ssh/weebblade" \
      "$HOME/.ssh/weebblade.pem" \
      "$HOME/.ssh/id_ed25519_weebblade"; do
    if [[ -f "$candidate" ]]; then
      KEY="$candidate"; break
    fi
  done
fi
if [[ -z "$KEY" || ! -f "$KEY" ]]; then
  echo "No SSH key found. Looked for weebblade-key.pem / weebblade / weebblade.pem" >&2
  echo "under ~/.ssh. Set WEEBBLADE_KEY to your key's path, e.g.:" >&2
  echo "  export WEEBBLADE_KEY=\"\$HOME/.ssh/weebblade\"        # bash/zsh" >&2
  echo "  set -Ux WEEBBLADE_KEY \"\$HOME/.ssh/weebblade\"       # fish" >&2
  exit 1
fi

MY_IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
if [[ -z "$MY_IP" ]]; then
  echo "Could not determine this machine's public IP." >&2
  exit 1
fi
CIDR="${MY_IP}/32"

# Revoke on any exit path - normal, error, or Ctrl-C - so a dropped connection
# never leaves the port open. Failure to revoke is reported loudly rather than
# swallowed: a leftover rule is the one outcome worth knowing about.
cleanup() {
  if ! aws_sg ec2 revoke-security-group-ingress \
      --group-id "$SG_ID" --protocol tcp --port 22 --cidr "$CIDR" >/dev/null 2>&1; then
    echo "WARNING: could not revoke SSH access for $CIDR - check the security group." >&2
  else
    echo "Closed SSH for $CIDR."
  fi
}
trap cleanup EXIT

echo "Opening SSH for $CIDR ..."
if ! aws_sg ec2 authorize-security-group-ingress \
    --group-id "$SG_ID" --protocol tcp --port 22 --cidr "$CIDR" >/dev/null 2>&1; then
  # Most likely already authorised from an earlier run that failed to clean up;
  # the connection below will confirm whether access actually works.
  echo "Note: authorize returned an error (rule may already exist); continuing." >&2
fi

# Brief pause - security group changes take a moment to take effect, and an
# immediate connect can still be refused.
sleep 3

if [[ $# -gt 0 ]]; then
  ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "${USER_NAME}@${HOST}" "$@"
else
  ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "${USER_NAME}@${HOST}"
fi
