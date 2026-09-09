"use client";

import Image from "next/image";
import { useState } from "react";

/* A click-to-load trailer facade.
 *
 * Embedding YouTube's iframe directly costs roughly half a megabyte of third
 * party JavaScript per page view, sets cookies before the visitor has asked for
 * anything, and does it whether or not they ever press play. This renders the
 * poster frame instead and only mounts the iframe on click, which is the
 * difference between the trailer costing nothing and costing more than the rest
 * of the site combined.
 *
 * ~57% of the season has a trailer, so every caller has to handle its absence;
 * this component simply is not rendered in that case.
 */
export function Trailer({ videoId, title }: { videoId: string; title: string }) {
  const [playing, setPlaying] = useState(false);

  if (playing) {
    return (
      <div className="relative aspect-video w-full border border-ink bg-ink">
        <iframe
          className="absolute inset-0 h-full w-full"
          src={`https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1`}
          title={`Trailer: ${title}`}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setPlaying(true)}
      aria-label={`Play trailer for ${title}`}
      className="group relative block aspect-video w-full overflow-hidden border border-ink bg-plate"
    >
      {/* hqdefault exists for every video; maxres does not, and a missing
          maxres renders as a grey placeholder rather than failing loudly. */}
      <Image
        src={`https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`}
        alt=""
        fill
        sizes="(max-width: 768px) 92vw, 30rem"
        className="object-cover transition-transform duration-500 group-hover:scale-[1.03]"
      />
      <span className="absolute inset-0 bg-ink/25 transition-colors group-hover:bg-ink/10" />
      <span className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 border border-paper bg-flag px-4 py-2 text-paper">
        {/* A triangle, not an icon-library import: it is one shape, and pulling a
            dependency in for it would cost more than it saves. */}
        <span
          aria-hidden
          className="block h-0 w-0 border-y-[6px] border-l-[10px] border-y-transparent border-l-paper"
        />
        <span className="text-[0.8rem] font-semibold">Trailer</span>
      </span>
    </button>
  );
}
