import { NextResponse, type NextRequest } from "next/server";
import { API_BASE } from "@/lib/types";

/* Old title addresses, /anime/{source}/{source_id}, permanently redirected to the
 * title's identity address, /anime/{wb_id}.
 *
 * Title pages used to be addressed by whichever source won the title's merge.
 * That address moved whenever the winner did, so it could not be kept; links
 * made with it are still out there. The API resolves any source key a title was
 * ever made of, including one that since lost its merge, so every such link can
 * be sent to the one address that will not move again.
 *
 * Here rather than in a page because a page streams, and a redirect thrown
 * mid-stream becomes a client-side meta refresh with a 200. This runs before
 * rendering, so the answer is a real 308 that browsers and crawlers both follow.
 *
 * A key the API does not know falls through: nothing lives at this depth any
 * more, so the site's own 404 page answers. So does a title with no identity,
 * which only a warehouse from before identities could return. An API that
 * cannot be reached is not the same as a title that does not exist, and says so. */
export async function proxy(request: NextRequest) {
  const [, , source, sourceId] = request.nextUrl.pathname.split("/");

  let res: Response;
  try {
    res = await fetch(
      `${API_BASE}/anime/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`,
      { headers: { Accept: "application/json" } },
    );
  } catch {
    return new NextResponse("The catalogue could not be reached. Try again shortly.", { status: 503 });
  }

  if (res.status === 404) return NextResponse.next();
  if (!res.ok) {
    return new NextResponse("The catalogue could not be reached. Try again shortly.", { status: 503 });
  }

  const { wb_id } = (await res.json()) as { wb_id?: string | null };
  if (!wb_id) return NextResponse.next();
  return NextResponse.redirect(new URL(`/anime/${wb_id}`, request.url), 308);
}

export const config = {
  matcher: "/anime/:source/:sourceId",
};
