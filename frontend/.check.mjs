import { chromium } from "@playwright/test";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });

await p.goto("http://127.0.0.1:3200/schedule", { waitUntil: "networkidle" });
await p.waitForTimeout(4000);
const today = await p.evaluate(() => {
  const all = [...document.querySelectorAll("*")].filter(e => e.textContent?.trim() === "Today in Japan");
  return all.map(e => ({ cls: e.className, vis: getComputedStyle(e).visibility,
                         display: getComputedStyle(e).display, w: Math.round(e.getBoundingClientRect().width) }));
});
console.log("'Today in Japan' markers:", JSON.stringify(today));

await p.goto("http://127.0.0.1:3200/browse", { waitUntil: "networkidle" });
const href = await p.locator('main a[href^="/anime/"]').first().getAttribute("href");
await p.goto("http://127.0.0.1:3200" + href, { waitUntil: "networkidle" });
await p.waitForTimeout(2500);
const stamps = await p.evaluate(() => {
  const s = [...document.querySelectorAll(".stamp")];
  return { count: s.length, texts: s.map(e => e.textContent.trim()).slice(0, 20) };
});
console.log("title page .stamp count:", stamps.count);
console.log("  ", stamps.texts.join(" | "));
await p.close();

const m = await b.newPage({ viewport: { width: 390, height: 844 } });
await m.goto("http://127.0.0.1:3200/browse", { waitUntil: "networkidle" });
await m.waitForTimeout(1500);
const opened = await m.evaluate(() => {
  const d = document.querySelector("details"); if (d) d.open = true;
  return new Promise(r => setTimeout(() => {
    const small = [...document.querySelectorAll("a,button")]
      .map(e => ({ t: e.textContent.trim().slice(0,18), r: e.getBoundingClientRect() }))
      .filter(x => x.r.width > 0 && (x.r.width < 24 || x.r.height < 24))
      .map(x => `${x.t} ${Math.round(x.r.width)}x${Math.round(x.r.height)}`);
    return { under24: small.slice(0, 10), total: small.length };
  }, 400));
});
console.log("390 tap targets under 24px:", opened.total, opened.under24.join(" | "));
await b.close();
