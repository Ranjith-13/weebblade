"use client";

import { useRef } from "react";
import { EASE, FULL, gsap, useGSAP } from "./gsap-init";

/* PLATES COMING INTO REGISTER.
 *
 * What this replaces and why. Every grid here used to arrive with
 * `gsap.from({ y, autoAlpha: 0 })` - slide up, fade in - which is the most
 * common scroll effect on the web and says nothing about this product. It had a
 * concrete cost too: autoAlpha 0 means the resting state is INVISIBLE until a
 * scroll trigger fires, so a full-page capture of the home page showed the
 * entire catalogue as blank paper, and a fast scroller sees the same thing for
 * a few hundred milliseconds.
 *
 * The replacement is the one gesture this design can claim. Offset printing's
 * signature artifact is misregistration: colour plates landing a hair off true
 * and being pulled into register. So a plate arrives a few pixels out, with the
 * ink not yet fully taken, and settles. The grid reads as a sheet coming off a
 * press rather than as a web page scrolling.
 *
 * WHY THE HALFTONE IS NOT WHAT MOVES, which was the obvious idea and is wrong:
 * the screen means "no score upstream" and nothing else. Running it as an
 * entrance would make it mean "not arrived yet" as well, and DESIGN.md is
 * explicit that the moment it stops meaning one thing the whole system becomes
 * ornament. The artwork registers; the screen stays exactly as honest as it was.
 *
 * It never starts from invisible. Opacity bottoms out at 0.35, so a reader who
 * scrolls fast sees dim plates rather than empty paper, and a screenshot taken
 * mid-animation shows the catalogue. Transform and opacity only, so this cannot
 * trigger layout and CLS stays at 0.
 */
export function RegisterReveal({
  children,
  selector = ":scope > *",
  stagger = 0.03,
  duration = 0.55,
  start = "top 92%",
  className,
}: {
  children: React.ReactNode;
  /** What comes into register. Defaults to direct children of the wrapper. */
  selector?: string;
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

      mm.add(FULL, () => {
        gsap.from(targets, {
          // Off-register by a few pixels on both axes, the way a misaligned
          // plate actually sits. Not a slide: the distance is small enough to
          // read as a correction rather than as travel.
          x: -7,
          y: 5,
          opacity: 0.35,
          duration,
          ease: EASE,
          // "start" rather than a grid-aware order on purpose: the DOM order is
          // the reading order, and a press lays ink down in one pass.
          stagger: { each: stagger, from: "start" },
          scrollTrigger: { trigger: scope.current, start, once: true },
        });
      });

      // No reduced-motion branch, as everywhere else here: the resting state is
      // already the final state, so the right answer is to do nothing at all.
      return () => mm.revert();
    },
    { scope, dependencies: [selector, stagger, duration, start] },
  );

  return (
    <div ref={scope} className={className}>
      {children}
    </div>
  );
}
