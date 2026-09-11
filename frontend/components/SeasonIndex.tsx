import { Suspense } from "react";
import { getSeasons } from "@/lib/api";
import { SeasonIndexLive, SeasonIndexPanel } from "./SeasonIndexPanel";

/* Every season the warehouse holds, as one index that any page can open.
 *
 * The seasons were always there - ten of them after the first backfill - but the only
 * way to reach one was a chip row inside /browse's filter block. The front page
 * named one season in 90px type and never mentioned the rest, and the header
 * linked to "The season", singular. So the concept existed and was invisible.
 *
 * The URL is only known on the client (a layout gets no searchParams), so the
 * index prerenders with nothing marked current and the live version replaces it
 * once the route resolves. Both are the same component, so nothing shifts. */
export async function SeasonIndex() {
  const seasons = await getSeasons();
  return (
    <Suspense fallback={<SeasonIndexPanel seasons={seasons} activeKey={null} />}>
      <SeasonIndexLive seasons={seasons} />
    </Suspense>
  );
}
