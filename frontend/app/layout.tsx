import type { Metadata } from "next";
import { Archivo, Bodoni_Moda } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";
import { NavList, PrimaryNav } from "@/components/nav/PrimaryNav";
import { Provenance, PROVENANCE_FALLBACK } from "@/components/Provenance";
import { SeasonIndex } from "@/components/SeasonIndex";
import { ThemeChoice, ThemeToggle } from "@/components/ThemeChoice";
import { WarmupPing } from "@/components/WarmupPing";
import { SITE_URL, THEME_KEY } from "@/lib/types";
import "./globals.css";

/* Bodoni Moda for the masthead. A didone: the historical face of printed
 * almanacs and broadsheet mastheads, and its extreme thick/thin contrast is
 * the typographic echo of the halftone screen the whole design runs on.
 * Display sizes only, where a didone has presence; never at body size, where
 * its hairlines would break up.
 *
 * Deliberately not Fraunces and not Instrument Serif. Those are the two
 * display serifs every generated "editorial" site reaches for, and swapping
 * one for the other is not a decision. Archivo carries everything else: a
 * grotesque that survives 10px metadata without turning to mush. */
const bodoni = Bodoni_Moda({
  subsets: ["latin"],
  variable: "--font-bodoni",
  display: "swap",
});

const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-archivo",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "WeebBlade: a seasonal anime almanac",
    template: "%s | WeebBlade",
  },
  description:
    "A weekly almanac of the current anime season, built on a real data pipeline: multi-source ingestion, PySpark processing, a DuckDB warehouse, an LLM-written digest and embedding-based semantic search.",
  openGraph: {
    title: "WeebBlade: a seasonal anime almanac",
    description:
      "A weekly almanac of the current anime season, assembled by a real data pipeline.",
    type: "website",
  },
  /* summary_large_image, not the default summary. A title page renders its own
   * card now (app/anime/[key]/opengraph-image.tsx) - the show's artwork, its
   * name, and whether there is a score - and at `summary` that card unfurls as
   * a thumbnail beside a line of text, which is the one shape it was not drawn
   * for. X falls back to og:image when no twitter:image is given, so declaring
   * the card shape is the whole of what is needed here. */
  twitter: {
    card: "summary_large_image",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${bodoni.variable} ${archivo.variable}`}>
      <head>
        {/* BEFORE FIRST PAINT, AND IT HAS TO BE INLINE AND BLOCKING.
            A stored theme lives in localStorage, which the server cannot read,
            so without this the page paints in the system's answer and then
            snaps to the reader's on hydration - a white flash on every single
            navigation for anyone who chose dark under a light OS. That is the
            one bug this whole control is capable of causing, and it is a worse
            experience than having no control at all.

            Reading localStorage can throw outright in a private window with
            site data blocked, so the whole thing is wrapped: a failure here
            must cost the preference, never the page. "system" simply removes
            the attribute and lets the media query answer. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem(${JSON.stringify(THEME_KEY)});if(t==="dark"||t==="light")document.documentElement.setAttribute("data-theme",t)}catch(e){}`,
          }}
        />
      </head>
      <body className="flex min-h-dvh flex-col">
        <WarmupPing />
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:border focus:border-ink focus:bg-paper focus:px-3 focus:py-2 focus:text-sm"
        >
          Skip to content
        </a>

        {/* The nav reads the pathname to mark the current section, and on a
            route with an unknown param (a title, a dated digest) that suspends
            during prerender. The fallback is the same nav with nothing marked,
            so the header never waits on the page below it. */}
        <header id="site-header" className="border-b-2 border-ink">
          <div className="mx-auto flex max-w-[1340px] flex-wrap items-end justify-between gap-x-8 px-5 sm:px-7">
            {/* The toggle rides with the wordmark, NOT with the nav, and that
                is a measurement rather than a preference. The five nav items
                already take 352px of a 390px line; putting a sixth control
                beside them pushed the header past the viewport and gave this
                site its first horizontal scrollbar. On the wordmark side there
                is room at every width, and when the header wraps on a phone the
                two travel together. */}
            <div className="flex items-end gap-x-4">
              <Link
                href="/"
                className="inline-block pt-3.5 pb-2.5 font-display text-[1.55rem] font-black leading-none tracking-[-0.02em] sm:pb-3 sm:text-[1.75rem]"
              >
                WeebBlade
              </Link>
              <ThemeToggle />
            </div>
            <Suspense fallback={<NavList active={null} />}>
              <PrimaryNav />
            </Suspense>
          </div>
        </header>

        <Suspense fallback={null}>
          <SeasonIndex />
        </Suspense>

        <main id="main" className="flex-1">
          {children}
        </main>

        {/* The footer states what is actually true today rather than what the
            architecture allows — and reads it from the data, because the version
            that stated it in prose went stale the moment MAL joined and told
            every visitor for days that this was a one-source site. */}
        <footer className="mt-20 border-t border-rule">
          <div className="mx-auto flex max-w-[1340px] flex-wrap items-baseline justify-between gap-x-8 gap-y-2 px-5 py-7 sm:px-7">
            <Suspense fallback={<p className="meta">{PROVENANCE_FALLBACK}</p>}>
              <Provenance className="meta" />
            </Suspense>
            {/* In the footer rather than the masthead: the five nav items
                already fill 352px of a 390px line, and a theme is a preference
                a reader sets once, not a section they navigate to. */}
            <ThemeChoice />
            <a
              href="https://github.com/Ranjith-13/weebblade"
              className="meta inline-block py-2 underline decoration-rule underline-offset-4 transition-colors hover:text-flag"
              target="_blank"
              rel="noreferrer"
            >
              Source and pipeline
            </a>
          </div>
        </footer>
      </body>
    </html>
  );
}
