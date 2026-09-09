"use client";

import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";

/* One registration point for the whole app. GSAP plugins must be registered
 * exactly once, and doing it per-component causes duplicate registration
 * warnings in dev where Fast Refresh re-runs module bodies.
 *
 * GSAP is the only animation library here on purpose. Mixing it with Motion or
 * Framer means two libraries competing for the same frames on the same
 * elements, and the resulting jank is very hard to attribute. GSAP wins for
 * this site specifically because it is the only one that does real pinning and
 * scrub-linked scroll properly, which is two of the four effects below. */
gsap.registerPlugin(ScrollTrigger, useGSAP);

export { gsap, ScrollTrigger, useGSAP };

/** Standard easing for entrances. Matches the --ease-print token in
 *  globals.css so JS-driven motion and CSS transitions agree. */
export const EASE = "power3.out";

/** Everything animated here is decoration over content that is already
 *  readable. Under reduced-motion we do not "animate faster" — we skip the
 *  animation entirely and leave the final state, which is what the setting
 *  actually asks for. */
export const REDUCED = "(prefers-reduced-motion: reduce)";
export const FULL = "(prefers-reduced-motion: no-preference)";
