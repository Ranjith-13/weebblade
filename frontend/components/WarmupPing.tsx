"use client";

import { useEffect } from "react";
import { API_BASE } from "@/lib/types";

export function WarmupPing() {
  useEffect(() => {
    // Non-blocking fire-and-forget ping to the Render API. If the free
    // container is asleep, this initiates container boot while the visitor
    // is reading the page, before they even click Search.
    if (typeof window !== "undefined" && API_BASE) {
      try {
        fetch(`${API_BASE}/health`, { mode: "no-cors" }).catch(() => {});
      } catch {
        // Ignore network errors on warmup ping
      }
    }
  }, []);

  return null;
}
