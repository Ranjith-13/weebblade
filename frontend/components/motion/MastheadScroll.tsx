"use client";

import { useRef } from "react";
import { EASE, FULL, gsap, useGSAP } from "./gsap-init";

/* PARALLAX + SCROLL-LINKED + SCROLL PROGRESS, on the masthead.
 *
 * Three things happen here, and each has a reason:
 *
 * 1. ENTRANCE. "Summer" and "2026" rise in on load with a small stagger. The
 *    masthead is above the fold, so a scroll trigger would never fire for it.
 *    This is the one moment the page announces itself.
 *
 * 2. PARALLAX ON SCROLL. The masthead travels upward more slowly than the page
 *    (scrub-linked, not time-linked). On a printed almanac the masthead is on
 *    the paper; here the small speed difference is what makes the catalogue
 *    below feel like it is sliding over the cover rather than with it.
 *
 * 3. SCROLL-LINKED FADE. It dims as it leaves, so the eye is handed to the
 *    digest rather than competing with it.
 *
 * Everything is transform and opacity, so no layout is triggered and CLS stays
 * at zero. `scrub: true` ties progress to scroll position exactly, which means
 * dragging the scrollbar backwards plays it in reverse: that is the difference
 * between scroll-LINKED and a scroll-triggered animation that merely fires.
 */
export function MastheadScroll({ children }: { children: React.ReactNode }) {
  const scope = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();

      mm.add(FULL, () => {
        const lines = scope.current?.querySelectorAll("[data-mast-line]");
        const meta = scope.current?.querySelectorAll("[data-mast-meta]");

        if (lines?.length) {
          gsap.from(lines, {
            yPercent: 108,
            autoAlpha: 0,
            duration: 0.95,
            ease: EASE,
            stagger: 0.08,
          });
        }
        if (meta?.length) {
          gsap.from(meta, {
            y: 12,
            autoAlpha: 0,
            duration: 0.7,
            delay: 0.35,
            ease: EASE,
          });
        }

        // The parallax itself. Deliberately gentle: 12% of the scrolled
        // distance. Large parallax on a text masthead reads as a broken sticky
        // header, not as depth.
        gsap.to(scope.current, {
          yPercent: -12,
          autoAlpha: 0.25,
          ease: "none",
          scrollTrigger: {
            trigger: scope.current,
            start: "top top",
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
    <div ref={scope} className="[will-change:transform]">
      {children}
    </div>
  );
}
