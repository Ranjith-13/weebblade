import type { Metadata } from "next";
import { Instrument_Serif, Inter } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const display = Instrument_Serif({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const body = Inter({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "WeebBlade — Seasonal Anime Trend Tracker",
    template: "%s — WeebBlade",
  },
  description:
    "A seasonal anime trend tracker built on a real data pipeline: multi-source ingestion, PySpark processing, a DuckDB warehouse, an LLM-written weekly digest and embedding-based semantic search.",
};

const NAV = [
  { href: "/browse", label: "Browse" },
  { href: "/search", label: "Search" },
  { href: "/digest", label: "Digest" },
] as const;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body className="min-h-dvh flex flex-col">
        <header className="border-b border-rule">
          <div className="mx-auto flex max-w-[1400px] items-baseline justify-between px-6 py-5">
            <Link href="/" className="label !text-ink !tracking-[0.22em] font-medium">
              WeebBlade
            </Link>
            <nav className="flex gap-7">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="label hover:!text-ink transition-colors"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>

        <main className="flex-1">{children}</main>

        <footer className="border-t border-rule mt-24">
          <div className="mx-auto max-w-[1400px] px-6 py-8 flex flex-wrap gap-x-8 gap-y-2 justify-between">
            <p className="label">
              Data from AniList · Jikan · Kitsu — refreshed weekly
            </p>
            <a
              href="https://github.com/Ranjith-13/weebblade"
              className="label hover:!text-ink transition-colors"
              target="_blank"
              rel="noreferrer"
            >
              Source
            </a>
          </div>
        </footer>
      </body>
    </html>
  );
}
