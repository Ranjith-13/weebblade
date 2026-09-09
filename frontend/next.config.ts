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
    // Poster hosts, one per ingestion source. Kitsu is the only one serving data
    // today (AniList and Jikan are both down upstream), but rows from the other
    // two will carry their own hosts once those recover - configured now so that
    // doesn't surface later as silently broken images.
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
