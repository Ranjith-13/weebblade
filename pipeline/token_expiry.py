"""When the credential the live API reads its own warehouse with runs out.

The repository is private, so the API cannot fetch the published warehouse
without a GitHub token, and GitHub caps a fine-grained token at one year. This
is therefore not a risk, it is an appointment: on 2027-10-13 the API stops being
able to see new releases.

WHAT THAT LOOKS LIKE IF NOBODY IS TOLD

Nothing, for a while. The container keeps serving the warehouse it last
downloaded, so the site stays up and the catalogue quietly stops advancing -
the weekly run publishing into a release nothing reads. Then the container
restarts for any reason at all, finds nothing on disk and no way to get it, and
answers 503 to everything. A year from now, with no note anywhere, that is a
genuinely horrible thing to diagnose: the pipeline is green, the deploy is
green, and the site is down.

backend/app/warehouse.py already names it once it has happened - a 401 logs
"GITHUB_TOKEN is expired, revoked or wrong". This is the other half: saying so
before, while it is still a two-minute job.

WHY THE DATE IS WRITTEN HERE RATHER THAN ASKED FOR

GitHub does send a GitHub-Authentication-Token-Expiration header, which is the
obvious thing to read, and it is documented as unreliable for fine-grained
tokens - returning the server's own clock, or a minute from now. A warning that
fires falsely gets muted, and then the real one is muted with it. A date that
somebody typed is worse engineering and better behaviour.

Keep this in step with the token. If it is regenerated, the new date goes here
and in README.md's deploying table, and nowhere else.
"""

from __future__ import annotations

import logging
import os
import urllib.request
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# The fine-grained token in the API's environment, Contents: read on this
# repository only. Created 2026-10-13 at GitHub's one-year maximum.
TOKEN_EXPIRES = date(2027, 10, 13)

# Thirty days, because the weekly run is what carries this: a month's warning is
# four or five reminders, which is enough to be heard and few enough not to be
# filtered. A daily warning for a month is how an alert becomes furniture.
WARN_WITHIN = timedelta(days=30)


def days_left(today: date) -> int:
    """Negative once it has expired, which is a state worth being able to say."""
    return (TOKEN_EXPIRES - today).days


def message(today: date) -> str | None:
    """What to say, or None when there is nothing worth saying yet.

    Deliberately includes what to do. An alert that says only "the token expires
    in 9 days" sends its reader looking for the instructions; this one carries
    them, because the person reading it may be a year from having thought about
    any of this.
    """
    left = days_left(today)
    if left > WARN_WITHIN.days:
        return None

    what_to_do = (
        "Regenerate at github.com/settings/personal-access-tokens "
        "(fine-grained, Contents: read, this repository only), update GITHUB_TOKEN "
        "in the API's environment, then update TOKEN_EXPIRES in "
        "pipeline/token_expiry.py and the date in README.md."
    )
    if left < 0:
        return (
            f"The API's GitHub token expired {-left} days ago, on {TOKEN_EXPIRES}. "
            "It is serving whatever warehouse it last downloaded and will answer 503 "
            f"to everything after its next restart. {what_to_do}"
        )
    if left == 0:
        return (
            f"The API's GitHub token expires today, {TOKEN_EXPIRES}. After that it "
            f"cannot fetch new warehouses. {what_to_do}"
        )
    return (
        f"The API's GitHub token expires in {left} days, on {TOKEN_EXPIRES}. When it "
        "does, the catalogue stops advancing and the site 503s after the next "
        f"restart. {what_to_do}"
    )


def warn(today: date | None = None) -> str | None:
    """Push the warning where this project's other alerts go, and return it.

    Returns the message whether or not it could be sent, because the run log is
    also a place somebody reads. Never raises: a notification is not worth
    failing a pipeline run over, which is the same rule run_checks.notify works
    to.
    """
    text = message(today or date.today())
    if text is None:
        return None

    logger.warning("%s", text)

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return text

    request = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=text.encode("utf-8"),
        headers={
            "Title": "WeebBlade: the API's GitHub token is running out",
            "Tags": "key",
            "User-Agent": "weebblade-token-expiry",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            pass
    except OSError:
        logger.warning("Could not send the token-expiry notification", exc_info=True)
    return text


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    said = warn()
    print(said or f"Token good for {days_left(date.today())} more days ({TOKEN_EXPIRES}).")
