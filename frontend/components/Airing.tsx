"use client";

import { useSyncExternalStore } from "react";
import { countdown, jstDayKey } from "@/lib/types";

/* Countdowns to AniList's airdates, in the reader's own time.
 *
 * The airdate itself - "Monday 14 September, 20:57 JST" - is rendered on the
 * server, because it is a fact and the same for everyone. What is added here is
 * what depends on the reader: how long until it airs, and when that is where
 * they are. Neither can be rendered on the server: the answer depends on `now`,
 * which is baked at cache time there, and on a timezone the server never sees.
 */

/* One clock for the whole page, ticking by the minute.
 *
 * A store rather than a timer per component: the schedule has a hundred rows,
 * and a hundred intervals re-rendering out of step would be both wasteful and
 * visibly ragged. The store polls every 15 seconds and notifies only when the
 * minute changes, so every countdown on the page moves together.
 *
 * The server snapshot is null, which is how a component knows it is being
 * rendered without a clock - during SSR and hydration - and must render what
 * does not depend on one. */
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | null = null;
let minute: number | null = null;

const currentMinute = () => Math.floor(Date.now() / 60_000);

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (timer === null) {
    minute = currentMinute();
    timer = setInterval(() => {
      const next = currentMinute();
      if (next !== minute) {
        minute = next;
        listeners.forEach((l) => l());
      }
    }, 15_000);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };
}

// Stable between ticks, which useSyncExternalStore requires: a fresh Date.now()
// on every call would loop forever.
const getSnapshot = () => (minute ??= currentMinute());
const getServerSnapshot = () => null;

/** Milliseconds now, to the minute, or null where there is no clock yet. */
function useNow(): number | null {
  const m = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return m === null ? null : m * 60_000;
}

function localTime(ms: number, withDate: boolean): string {
  return new Date(ms).toLocaleString(undefined, {
    weekday: "short",
    ...(withDate ? { day: "numeric", month: "short" } : {}),
    hour: "2-digit",
    minute: "2-digit",
  });
}

export type Airdate = {
  episode: number | null;
  airing_at: string;
  /** Rendered on the server, in Japan's time: see jstAirdate. */
  label: string;
};

/** A title's next episode: which, when in Japan, and how long from now.
 *
 *  Handed several episodes, soonest first, because the page is cached for up to
 *  an hour and the first may have aired since. Until the clock is known the
 *  first stands, so the server's markup and the first client render agree; then
 *  it moves to the first one still ahead. */
export function EpisodeCountdown({ episodes, total }: { episodes: Airdate[]; total: number | null }) {
  const now = useNow();
  const next = now === null ? episodes[0] : episodes.find((e) => Date.parse(e.airing_at) > now);
  const shown = next ?? episodes[episodes.length - 1];
  const name =
    shown.episode === null ? "The next episode" : `Episode ${shown.episode}${total ? ` of ${total}` : ""}`;

  return (
    <>
      <p className="text-[0.9rem]">
        {name} {next ? "airs" : "aired"} <span className="font-semibold">{shown.label}</span>
      </p>
      {/* One line held for the countdown, which arrives after mount; without
          it the caveat below jumps down a line. 1.5em is one .meta line. */}
      <p className="meta tnum mt-1 min-h-[1.5em]">
        {now !== null && next && (
          <>
            in {countdown(Date.parse(next.airing_at) - now)}, {localTime(Date.parse(next.airing_at), true)} your
            time
          </>
        )}
      </p>
    </>
  );
}

/** When a schedule row's episode airs where the reader is: weekday and time. */
export function LocalTime({ at }: { at: string }) {
  const now = useNow();
  if (now === null) return null;
  return <span className="tnum">{localTime(Date.parse(at), false)}</span>;
}

/** How long until a schedule row's episode airs, or that it has. */
export function Countdown({ at }: { at: string }) {
  const now = useNow();
  if (now === null) return null;
  const when = Date.parse(at);
  return when > now ? <span className="whitespace-nowrap text-ink">in {countdown(when - now, true)}</span> : <>Aired</>;
}

/* Marks the column for today in Japan.
 *
 * Server-rendered "today" would be wrong twice over: baked at cache time, and
 * `cacheLife('hours')` lets that cache outlive the day it describes. On the
 * shared clock, it moves at midnight in Tokyo with the page open.
 *
 * Present in every column and hidden in all but today's, so revealing it after
 * mount changes no widths: arriving from nothing, it pushed the day's count
 * aside, a layout shift on every load. */
export function TodayMarker({ dayKey }: { dayKey: string }) {
  const now = useNow();
  const today = now !== null && jstDayKey(new Date(now).toISOString()) === dayKey;
  return <span className={today ? "text-flag" : "invisible"}>Today in Japan</span>;
}
