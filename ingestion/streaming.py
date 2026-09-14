"""Where to watch: streaming links, and what to call the service behind each."""

from __future__ import annotations

from urllib.parse import urlparse

# Streaming host -> display name. Kitsu gives a bare URL and no provider label, so
# the mapping lives at ingest rather than in the UI: the name is data about the row,
# and deriving it once keeps every consumer (API, frontend, any future export)
# agreeing on what to call a service.
#
# Shared by every source that has links, and applied to the URL, never to a
# source's own label. AniList calls Prime Video "Amazon Prime Video" and Disney+
# "Disney Plus"; named by its labels, the same service would be two chips in the
# browse filter, and the one a reader picked would hide the other's titles.
STREAMING_SERVICES = {
    "crunchyroll.com": "Crunchyroll",
    "netflix.com": "Netflix",
    "hulu.com": "Hulu",
    "primevideo.com": "Prime Video",
    "amazon.com": "Prime Video",
    "disneyplus.com": "Disney+",
    "hidive.com": "HIDIVE",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "bilibili.tv": "Bilibili",
    "iq.com": "iQIYI",
    "tubitv.com": "Tubi",
    "retrocrush.tv": "RetroCrush",
    "midnightpulp.com": "Midnight Pulp",
    "vrv.co": "VRV",
    "funimation.com": "Funimation",
}


def is_usable_link(url: object) -> bool:
    """Reject anything that is not an absolute http(s) URL.

    Kitsu's streaming records are user-maintained and contain junk: the live season
    carries a link whose entire url field is the string "a". Rendering that as a
    clickable "Unknown" is worse than not showing it, so it is dropped at ingest
    rather than pushed to every consumer to defend against.
    """
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def service_name(url: str) -> str:
    """Map a streaming URL to a provider name, falling back to the bare host.

    The fallback matters: Kitsu carries long-tail regional services this map will
    never cover, and showing "anime-onegai.com" is more useful than dropping the
    link or labelling it "Other".
    """
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for domain, name in STREAMING_SERVICES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or "Unknown"
