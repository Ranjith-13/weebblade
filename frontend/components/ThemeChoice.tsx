"use client";

import { useSyncExternalStore } from "react";
import { THEME_KEY } from "@/lib/types";

/* System / Light / Dark, and System is the default on purpose.
 *
 * Most readers have already told their operating system what they want, and a
 * site that asks again is a site that did not listen the first time. So the
 * stored value is a three-state choice rather than a boolean: picking "System"
 * is a real answer, not the absence of one, and it is what an untouched browser
 * uses.
 *
 * WHY data-theme AND a media query, rather than one or the other. The media
 * query in globals.css answers for everyone who never touches this, including
 * anyone with JavaScript off. The attribute, set by the blocking script in
 * app/layout.tsx before first paint, is the reader overriding it. The CSS is
 * written so the attribute wins both ways: [data-theme="dark"] turns dark on
 * under a light system, and :not([data-theme="light"]) lets it be turned off
 * under a dark one.
 *
 * It renders with nothing marked current until it has mounted, for the reason
 * components/Airing.tsx renders nothing clock-dependent during SSR: the server
 * cannot know what is in this reader's localStorage, and guessing produces a
 * hydration mismatch. One frame with no marker is better than a wrong one.
 *
 * And it is an external store rather than useState + useEffect, which is the
 * same correction Airing.tsx carries: the set-state-in-effect lint rule objects
 * to the latter, rightly. localStorage IS external state, so reading it through
 * useSyncExternalStore is not a workaround, it is the accurate description.
 * Subscribing to `storage` as well means two tabs agree.
 */
const CHOICES = ["system", "light", "dark"] as const;
type Choice = (typeof CHOICES)[number];

function apply(choice: Choice) {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

/* The store. `storage` fires in OTHER tabs, so a local change dispatches its own
   event to notify this one. */
const CHANGED = "weebblade-theme-changed";

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener(CHANGED, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGED, onChange);
  };
}

function getSnapshot(): Choice {
  try {
    const stored = localStorage.getItem(THEME_KEY) as Choice | null;
    return stored && CHOICES.includes(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

// Null on the server: nothing is marked current until this has mounted.
const getServerSnapshot = () => null;

/* WHAT THE READER IS ACTUALLY LOOKING AT, which is a different question from
   what they chose. "System" is a choice whose answer lives in the OS, so the
   header toggle has to resolve it to decide which way it flips. Subscribing to
   the media query as well means that a reader on System who changes their OS
   theme sees the toggle's label change under them, rather than it offering to
   switch to the mode they are already in. */
function subscribeEffective(onChange: () => void) {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const stop = subscribe(onChange);
  mq.addEventListener("change", onChange);
  return () => {
    stop();
    mq.removeEventListener("change", onChange);
  };
}

function getEffective(): "light" | "dark" {
  const chosen = getSnapshot();
  if (chosen !== "system") return chosen;
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** One button that flips between light and dark, for the masthead.
 *
 *  Deliberately NOT a third copy of the three-state control. The header is
 *  where someone reaches when the page is too bright to read right now, and
 *  that is a one-tap question; "System" belongs where a preference is set
 *  rather than where it is corrected. The footer keeps all three, and picking
 *  System there puts this back under the OS's control.
 *
 *  The label names what pressing it will DO, not what is currently on, because
 *  a button labelled with the current state is ambiguous about which one it
 *  means. Fixed width so the word changing cannot reflow the masthead.
 *
 *  IT CARRIES THE CHIP BORDER, and that is not decoration. Set in plain .meta
 *  beside the wordmark it printed "WeebBlade  Dark", which reads as the name of
 *  an edition rather than as a thing to press - the one word is a noun in the
 *  wrong company. The bordered chip is this site's existing idiom for a
 *  pressable control (the footer's three, every facet row on /browse), so it
 *  says "button" without a drop shadow, a radius or an icon, none of which
 *  DESIGN.md allows. */
export function ThemeToggle() {
  const effective = useSyncExternalStore(subscribeEffective, getEffective, getServerSnapshot);
  const next = effective === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={() => pick(next)}
      /* aria-label rather than the visible word alone: "Dark" on its own does
         not say whether it is a state or an action. */
      aria-label={effective ? `Switch to the ${next} theme` : "Switch theme"}
      className="mb-[0.55rem] inline-flex min-w-[4.25rem] items-center justify-center border border-rule px-2 py-1.5 text-[0.7rem] capitalize text-ink-soft transition-colors duration-150 hover:border-flag hover:text-flag"
    >
      {/* Nothing until it has mounted, for the same reason the three-state
          control marks nothing: the server cannot know. The width is held so
          the word arriving does not move the masthead beside it. */}
      {effective ? next : "\u00a0"}
    </button>
  );
}

function pick(next: Choice) {
  apply(next);
  try {
    if (next === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, next);
  } catch {
    // Private mode, or storage blocked. The choice still applies for this page;
    // it simply will not be remembered, which is a better outcome than a
    // control that throws when clicked.
  }
  window.dispatchEvent(new Event(CHANGED));
}

export function ThemeChoice() {
  const choice = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  return (
    <div className="meta flex items-baseline gap-x-3">
      <span>Theme</span>
      {/* A row of links in everything but behaviour, matching the filter chips
          on /browse: a hairline border, no radius, the flag marking the current
          one. Fixed width per item so marking one cannot reflow the row. */}
      <div role="group" aria-label="Colour theme" className="flex">
        {CHOICES.map((value) => {
          const current = choice === value;
          return (
            <button
              key={value}
              type="button"
              onClick={() => pick(value)}
              aria-pressed={current}
              className={[
                "min-w-[4.25rem] border border-rule px-2 py-1.5 text-[0.7rem] capitalize",
                "-ml-px first:ml-0 transition-colors duration-150",
                current
                  ? "border-flag bg-flag font-semibold text-paper"
                  : "text-ink-soft hover:text-flag",
              ].join(" ")}
            >
              {value}
            </button>
          );
        })}
      </div>
    </div>
  );
}
