"use client";

import { useRef } from "react";
import { gsap, useGSAP } from "./gsap-init";

/* PARALLAX, on the detail page's key art.
 *
 * The artwork drifts slightly slower than the synopsis column beside it. On a
 * page that is one image and one block of text, this is the cheapest way to
 * stop the two columns reading as a single flat slab, and it is the closest
 * thing to depth that suits a design built on flat printed ink.
 *
 * The image is inside a fixed 3:4 frame with `overflow-hidden`, and the drift
 * is applied to the image INSIDE that frame, not to the frame. So the plate's
 * outline never moves, nothing reflows, and the layout cannot shift. The image
 * is scaled to 112% so there is real material to travel through and no edge is
 * ever exposed.
 *
 * Desktop only. On a phone the two columns are stacked, so there is no second
 * column to move against and the effect would be motion for its own sake.
 */
export function ParallaxPoster({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const scope = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();

      mm.add("(min-width: 768px) and (prefers-reduced-motion: no-preference)", () => {
        const art = scope.current?.querySelector("img");
        if (!art) return;

        gsap.set(art, { scale: 1.12 });
        gsap.to(art, {
          yPercent: -7,
          ease: "none",
          scrollTrigger: {
            trigger: scope.current,
            start: "top bottom",
            end: "bottom top",
            scrub: true,
          },
        });
      });

      return () => mm.revert();
    },
    { scope },
  );

  return (
    <div ref={scope} className={className}>
      {children}
    </div>
  );
}
