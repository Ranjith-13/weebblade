"use client";

import { useEffect, useState } from "react";
import { nextAiring } from "@/lib/types";

/* The derived half of the broadcast slot.
 *
 * The slot itself ("Saturdays 23:00 JST") is rendered on the server, because it
 * is a fact and it is the same for everyone. This adds what the slot implies:
 * when it next comes round, in the reader's own timezone.
 *
 * Client-only, and deliberately empty on first render. The answer depends on
 * `now`, which differs between the server and the reader's machine, so
 * rendering it during SSR would either hydrate mismatched or bake in the
 * server's clock. Mounting first and filling in after is the honest version.
 *
 * PRESENTED AS A SLOT, NOT AN AIRDATE. MAL has no next-episode date; this is the
 * regular weekly slot projected forward, and a broadcast that slips will not be
 * reflected here. The wording says "next slot" for that reason, and the caveat
 * is on the page rather than buried in a tooltip.
 *
 * The fallback now: a title AniList has an airdate for shows EpisodeCountdown
 * (components/Airing.tsx) instead.
 */
export function NextAiring({
  broadcastDay,
  broadcastTime,
}: {
  broadcastDay: string | null;
  broadcastTime: string | null;
}) {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    const when = nextAiring(broadcastDay, broadcastTime);
    if (!when) return;

    const render = () => {
      const ms = when.getTime() - Date.now();
      if (ms <= 0) return setText(null);

      const minutes = Math.floor(ms / 60000);
      const hours = Math.floor(minutes / 60);
      const days = Math.floor(hours / 24);

      const away =
        days >= 1
          ? `${days} day${days === 1 ? "" : "s"}`
          : hours >= 1
            ? `${hours} hour${hours === 1 ? "" : "s"}`
            : `${minutes} minute${minutes === 1 ? "" : "s"}`;

      // The reader's own timezone, not JST: the slot line above already states
      // JST, so repeating it here would be noise, and a local time is what
      // someone actually plans around.
      const local = when.toLocaleString(undefined, {
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });

      setText(`next slot in ${away}, ${local} your time`);
    };

    render();
    // A minute is enough: nothing here is displayed at second resolution, and a
    // per-second tick would re-render the page 60 times more often for nothing.
    const timer = setInterval(render, 60_000);
    return () => clearInterval(timer);
  }, [broadcastDay, broadcastTime]);

  if (!text) return null;
  return <span className="tnum text-ink-soft">{text}</span>;
}
