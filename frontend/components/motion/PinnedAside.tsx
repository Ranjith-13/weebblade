"use client";

import { useRef } from "react";
import { gsap, ScrollTrigger, useGSAP } from "./gsap-init";

/* PIN.
 *
 * Holds the "How to read this" key in place while the plate grid scrolls past
 * it. This is the one pin on the site and it is functional rather than
 * decorative: the key is what tells you that a full-colour plate means the
 * pipeline has a score and a screened-back one means it does not. Letting it
 * scroll away while you are still looking at plates is the version that makes
 * less sense.
 *
 * DESKTOP ONLY. Pinning inside a narrow single-column layout means the key
 * would occupy the viewport while the grid slides underneath it, which is worse
 * than letting it scroll. Below 1024px this renders its children and nothing
 * else happens.
 *
 * `pinSpacing: false` because the sibling grid is taller than the pinned block:
 * the section's own height should drive the scroll distance, not a spacer GSAP
 * inserts.
 */
export function PinnedAside({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const scope = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();

      // Pin only when there is a real second column AND the user has not asked
      // for reduced motion. A pin changes how scrolling behaves, which is
      // exactly what that setting is about.
      mm.add("(min-width: 1024px) and (prefers-reduced-motion: no-preference)", () => {
        if (!scope.current || !inner.current) return;

        const trigger = ScrollTrigger.create({
          trigger: scope.current,
          start: "top 96px",
          endTrigger: scope.current.parentElement ?? undefined,
          end: "bottom bottom",
          pin: inner.current,
          pinSpacing: false,
        });

        return () => trigger.kill();
      });

      return () => mm.revert();
    },
    { scope },
  );

  return (
    <div ref={scope} className={className}>
      <div ref={inner}>{children}</div>
    </div>
  );
}
