"use client";

import { useRef } from "react";
import { EASE, FULL, gsap, useGSAP } from "./gsap-init";

/* SCROLL TRIGGER — the workhorse.
 *
 * Wraps server-rendered content and staggers its children in as the block
 * enters the viewport. This is a client island around server children, so
 * PlateGrid and friends stay server components: nothing about the data layer
 * moves to the browser, only the animation does.
 *
 * WHY THIS IS MOTIVATED (and not just "it looked cool"):
 * The catalogue is 142 near-identical 3:4 plates. Landing all of them at once
 * gives the eye no order to follow, which is exactly the "uniform grid where
 * everything has equal weight" problem the audit flagged. A short stagger
 * along the reading direction gives the grid a first, a second, a third, and
 * turns a wall into a sequence.
 *
 * PROGRESSIVE ENHANCEMENT: this uses gsap.from(), so the DOM's resting state is
 * the FINAL state. If JS never runs, or fails, or the browser blocks it, the
 * content is fully visible with no styling to undo. useGSAP runs in a layout
 * effect, so the start state is applied before paint and there is no flash.
 */
export function ScrollReveal({
  children,
  selector = ":scope > *",
  y = 18,
  stagger = 0.045,
  duration = 0.62,
  start = "top 88%",
  className,
}: {
  children: React.ReactNode;
  /** What to stagger. Defaults to direct children of the wrapper. */
  selector?: string;
  y?: number;
  stagger?: number;
  duration?: number;
  start?: string;
  className?: string;
}) {
  const scope = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const targets = scope.current?.querySelectorAll(selector);
      if (!targets || targets.length === 0) return;

      const mm = gsap.matchMedia();

      // Full motion. Transform and opacity only, so this never triggers layout
      // and cannot contribute to CLS.
      mm.add(FULL, () => {
        gsap.from(targets, {
          y,
          autoAlpha: 0,
          duration,
          ease: EASE,
          stagger: { each: stagger, from: "start" },
          scrollTrigger: {
            trigger: scope.current,
            start,
            once: true,
          },
        });
      });

      // Reduced motion: no `mm.add(REDUCED, ...)` branch at all. The element's
      // resting state is already correct, so doing nothing is the right answer.
      return () => mm.revert();
    },
    { scope, dependencies: [selector, y, stagger, duration, start] },
  );

  return (
    <div ref={scope} className={className}>
      {children}
    </div>
  );
}
