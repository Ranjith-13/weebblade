import type { Metadata } from "next";
import { Archivo, Bodoni_Moda } from "next/font/google";
import Link from "next/link";
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
  metadataBase: new URL("https://weebblade.duckdns.org"),
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
};

const NAV = [
  { href: "/browse", label: "The season" },
  { href: "/search", label: "Search" },
  { href: "/digest", label: "Digest" },
] as const;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${bodoni.variable} ${archivo.variable}`}>
      <body className="flex min-h-dvh flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:border focus:border-ink focus:bg-paper focus:px-3 focus:py-2 focus:text-sm"
        >
          Skip to content
        </a>

        <header className="border-b-2 border-ink">
          <div className="mx-auto flex max-w-[1340px] flex-wrap items-baseline justify-between gap-x-8 gap-y-2 px-5 py-3 sm:px-7">
            <Link
              href="/"
              className="inline-block py-1.5 font-display text-[1.4rem] font-black leading-none tracking-[-0.02em]"
            >
              WeebBlade
            </Link>
            <nav aria-label="Primary">
              <ul className="flex gap-6">
                {NAV.map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className="inline-block border-b-2 border-transparent py-2 text-[0.8rem] transition-colors duration-150 hover:border-flag hover:text-flag"
                    >
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          </div>
        </header>

        <main id="main" className="flex-1">
          {children}
        </main>

        {/* The footer states what is actually true today rather than what the
            architecture allows. Two of the three ingestion sources are down
            upstream, so claiming three would be a lie the UI tells for us. */}
        <footer className="mt-20 border-t border-rule">
          <div className="mx-auto flex max-w-[1340px] flex-wrap items-baseline justify-between gap-x-8 gap-y-2 px-5 py-7 sm:px-7">
            <p className="meta">
              Assembled weekly from Kitsu. AniList and Jikan are down upstream.
            </p>
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
