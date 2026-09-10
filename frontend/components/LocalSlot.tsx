"use client";

import { useSyncExternalStore } from "react";
import { nextAiring } from "@/lib/types";

/* The viewer's own day and time for a broadcast slot.
 *
 * The schedule's columns are Japan's, because the slot is a fact and the same
 * for everyone. This is the other half: what that slot means where the reader
 * actually is. It matters more here than anywhere else on the site, because
 * these shows air after midnight in Tokyo — a Monday 01:30 JST broadcast is
 * Sunday morning in London and Sunday afternoon on the US west coast. A
 * schedule that only said "Monday" would be wrong for most of its readers.
 */

/* Whether we are past hydration, as a subscription rather than an effect.
 *
 * The obvious version — useState(false) plus a setState in useEffect — is what
 * this replaced. It works, but it is a cascading render on every row of a
 * 65-row page, and eslint's react-hooks/set-state-in-effect rightly objects.
 * The reader's timezone IS an external system, which is exactly what
 * useSyncExternalStore is for: the server snapshot is false, the client's is
 * true, and the value is then computed during render where it belongs.
 *
 * subscribe returns a no-op unsubscribe because this never changes after mount;
 * a reader who crosses a timezone mid-session gets the old one until navigation,
 * which is a trade worth making for not holding 65 listeners open.
 */
const neverChanges = () => () => {};

/* Frozen at the first client read, deliberately.
 *
 * getSnapshot has to be stable — React compares it with Object.is on every
 * render, so returning a fresh Date.now() each time is an infinite loop. Caching
 * it also means all 65 rows convert against one instant instead of drifting
 * apart mid-page.
 *
 * "Now" is needed at all only because of DST: a fixed JST slot lands on a
 * different local hour in summer than in winter, so a timezone conversion cannot
 * be computed from the slot alone. Freezing it for the life of the page is
 * harmless — nothing here is displayed at finer than minute resolution. */
let clientNow: number | null = null;
const getClientNow = () => (clientNow ??= Date.now());
const getServerNow = () => null;

function useNow(): number | null {
  return useSyncExternalStore(neverChanges, getClientNow, getServerNow);
}

export function LocalSlot({
  broadcastDay,
  broadcastTime,
}: {
  broadcastDay: string | null;
  broadcastTime: string | null;
}) {
  const now = useNow();
  if (now === null) return null;

  const when = nextAiring(broadcastDay, broadcastTime, new Date(now));
  if (!when) return null;

  // Weekday plus time, not a date: this is a recurring slot, and printing a
  // specific date would claim more certainty than a weekly pattern carries.
  return (
    <span className="tnum">
      {when.toLocaleString(undefined, {
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
      })}
    </span>
  );
}

const JST_WEEKDAYS = [
  "sunday",
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
];

/* Marks the column the reader is currently in, in Japan.
 *
 * Server-rendered "today" would be wrong twice over: baked at cache time, and
 * `cacheLife('hours')` lets that cache outlive the day it describes. */
export function TodayMarker({ day }: { day: string }) {
  const now = useNow();
  if (now === null) return null;

  const jstNow = new Date(now + 9 * 60 * 60 * 1000);
  if (JST_WEEKDAYS[jstNow.getUTCDay()] !== day) return null;

  return <span className="text-flag">Today in Japan</span>;
}
