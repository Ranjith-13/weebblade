from __future__ import annotations

import logging
from pathlib import Path

# chromadb 0.5.23 has a known bug where a startup telemetry ping still fires even
# with anonymized_telemetry=False (the check happens after the capture call), and
# that ping fails loudly on this posthog version ("capture() takes 1 positional
# argument but 3 were given"). Harmless - it's not search functionality - but noisy
# enough to silence directly since disabling telemetry via Settings doesn't stop it.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


def get_chroma_client(chroma_dir: Path):
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(
        path=str(chroma_dir), settings=Settings(anonymized_telemetry=False)
    )
