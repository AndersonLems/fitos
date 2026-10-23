// npm install --prefix /tmp/fitos-browser playwright
// NODE_PATH=/tmp/fitos-browser/node_modules node scripts/ui_review.cjs
// Use a disposable SQLite database on FITOS_REVIEW_URL, never production data.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = process.env.FITOS_REVIEW_URL || "http://127.0.0.1:8502";
const reference = process.env.FITOS_REFERENCE_URL || "http://127.0.0.1:5173";
const output = process.env.FITOS_SCREENSHOTS || "/tmp/fitos-review";
const routes = [
  "",
  "treinos",
  "biblioteca",
  "plano-alimentar",
  "mercado",
  "despensa",
  "evolucao",
  "personal-ia",
  "perfil",
  "configuracoes",
];
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage();
    const results = [];
    for (const [size, width, height] of [
      ["desktop", 1440, 1100],
      ["mobile", 390, 844],
    ]) {
      await page.setViewportSize({ width, height });
      for (const route of routes) {
        await page.goto(`${root}/${route}`);
        await page.locator(".fx-head").waitFor();
        await page.waitForTimeout(700);
        assert.equal(
          await page.locator('[data-testid="stException"]').count(),
          0,
          route,
        );
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          ),
          false,
          `${route} overflow`,
        );
        if (size === "mobile") {
          assert.equal(await page.locator(".fx-mobile-nav").isVisible(), true);
          assert.equal(await page.locator(".fx-mobile-nav a").count(), 5);
        }
        await page.screenshot({
          path: path.join(output, `fitos-${route || "dashboard"}-${size}.png`),
          fullPage: true,
        });
        results.push({
          route: route || "/",
          size,
          exceptions: 0,
          overflow: false,
        });
      }
      await page.goto(reference);
      await page.getByRole("heading", { name: /Bom dia/ }).waitFor();
      await page.waitForTimeout(700);
      await page.screenshot({
        path: path.join(output, `reference-${size}.png`),
        fullPage: true,
      });
    }
    fs.writeFileSync(
      path.join(output, "browser-results.json"),
      JSON.stringify(results, null, 2),
    );
    console.log(
      `Passed ${results.length} page/viewport checks. Screenshots: ${output}`,
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
