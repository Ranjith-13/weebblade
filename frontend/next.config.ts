import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enables the `use cache` directive used throughout lib/api.ts. Every catalogue
  // read is cached server-side, which matters here beyond plain performance: the
  // upstream API rate-limits per client IP, and all visitors share this app's
  // egress IPs. Without caching, one shared 60/min budget would be spent on
  // behalf of everyone. The pipeline only publishes weekly, so hour-scale caching
  // costs nothing in freshness.
  cacheComponents: true,

  images: {
    // Poster hosts, one per ingestion source. Configured before AniList and MAL
    // were serving data, so that their rows would not arrive as silently broken
    // images. cdn.myanimelist.net is MAL's own, reached through its official
    // API; the Jikan mirror that also served it was discontinued 1 Oct 2026.
    remotePatterns: [
      { protocol: "https", hostname: "media.kitsu.app" },
      { protocol: "https", hostname: "s4.anilist.co" },
      { protocol: "https", hostname: "cdn.myanimelist.net" },
      // YouTube poster frames for the trailer facade in components/Trailer.tsx.
      // i.ytimg.com is the thumbnail CDN; no YouTube script is loaded unless the
      // visitor actually presses play.
      { protocol: "https", hostname: "i.ytimg.com" },
    ],
  },
};

export default nextConfig;
