"""The warning before the API loses its credentials.

The repository is private, so the token is what lets the live API read its own
warehouse, and GitHub caps a fine-grained one at a year. This is an appointment
rather than a risk, and the failure it leads to is quiet: the catalogue stops
advancing while the site stays up, then everything 503s after a restart.
"""

from datetime import date, timedelta

import pytest

from pipeline import token_expiry
from pipeline.token_expiry import TOKEN_EXPIRES, days_left, message, warn


class _Sent:
    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)

        class _Response:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_):
                return False

        return _Response()


def test_nothing_is_said_while_the_token_has_months_left():
    """A warning that arrives early enough to ignore is one that gets ignored.
    Thirty days is four or five weekly reminders - enough to be heard, few
    enough not to become furniture."""
    assert message(TOKEN_EXPIRES - timedelta(days=31)) is None
    assert message(TOKEN_EXPIRES - timedelta(days=200)) is None


def test_the_warning_starts_thirty_days_out_and_counts_down():
    assert "30 days" in message(TOKEN_EXPIRES - timedelta(days=30))
    assert "9 days" in message(TOKEN_EXPIRES - timedelta(days=9))
    assert "expires today" in message(TOKEN_EXPIRES)


def test_an_expired_token_says_so_rather_than_counting_down_past_zero():
    """The state nobody plans for. "expires in -3 days" is the kind of line that
    makes a reader doubt the alert instead of the token."""
    said = message(TOKEN_EXPIRES + timedelta(days=3))

    assert "expired 3 days ago" in said
    assert "503" in said


@pytest.mark.parametrize("when", [
    TOKEN_EXPIRES - timedelta(days=30),
    TOKEN_EXPIRES,
    TOKEN_EXPIRES + timedelta(days=3),
])
def test_every_warning_carries_the_instructions(when):
    """The person reading this may be a year from having thought about any of
    it. An alert that only states the problem sends them hunting."""
    said = message(when)

    assert "personal-access-tokens" in said
    assert "TOKEN_EXPIRES in pipeline/token_expiry.py" in said


def test_days_left_goes_negative_rather_than_clamping():
    assert days_left(TOKEN_EXPIRES - timedelta(days=5)) == 5
    assert days_left(TOKEN_EXPIRES) == 0
    assert days_left(TOKEN_EXPIRES + timedelta(days=5)) == -5


def test_it_is_pushed_where_the_other_alerts_go(monkeypatch):
    sent = _Sent()
    monkeypatch.setattr(token_expiry.urllib.request, "urlopen", sent)
    monkeypatch.setenv("NTFY_TOPIC", "a-topic")

    said = warn(TOKEN_EXPIRES - timedelta(days=7))

    assert "7 days" in said
    [request] = sent.requests
    assert request.full_url == "https://ntfy.sh/a-topic"
    assert b"7 days" in request.data


def test_nothing_is_pushed_when_there_is_nothing_to_say(monkeypatch):
    sent = _Sent()
    monkeypatch.setattr(token_expiry.urllib.request, "urlopen", sent)
    monkeypatch.setenv("NTFY_TOPIC", "a-topic")

    assert warn(TOKEN_EXPIRES - timedelta(days=90)) is None
    assert sent.requests == []


def test_the_message_survives_having_nowhere_to_send_it(monkeypatch):
    """Two cases that must not swallow the warning: no topic configured, and a
    topic that cannot be reached. The run log is also somewhere a person reads,
    and a pipeline must not fail over a notification."""
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert "7 days" in warn(TOKEN_EXPIRES - timedelta(days=7))

    def down(request, timeout=None):
        raise OSError("no route")

    monkeypatch.setattr(token_expiry.urllib.request, "urlopen", down)
    monkeypatch.setenv("NTFY_TOPIC", "a-topic")
    assert "7 days" in warn(TOKEN_EXPIRES - timedelta(days=7))


def test_the_date_matches_what_the_readme_tells_a_reader():
    """Two places name this date and they must not drift: this module decides,
    README.md's deploying table is what somebody actually reads. A regenerated
    token has to update both."""
    readme = (TOKEN_EXPIRES.isoformat() in open("README.md", encoding="utf-8").read())

    assert readme, f"README.md does not mention {TOKEN_EXPIRES}"
    assert TOKEN_EXPIRES > date(2026, 10, 13), "the date should be in the future when set"
