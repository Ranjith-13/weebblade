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

export function ThemeChoice() {
  const choice = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  function pick(next: Choice) {
    apply(next);
    try {
      if (next === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, next);
    } catch {
      // Private mode, or storage blocked. The choice still applies for this
      // page; it simply will not be remembered, which is a better outcome than
      // a control that throws when clicked.
    }
    window.dispatchEvent(new Event(CHANGED));
  }

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
