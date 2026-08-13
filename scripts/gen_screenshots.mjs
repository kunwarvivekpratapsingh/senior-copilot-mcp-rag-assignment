/**
 * Capture the GUI screenshots the submission guidelines require (§18).
 *
 *   node scripts/gen_screenshots.mjs            # against http://localhost:5173
 *   GUI_URL=http://localhost:5173 node scripts/gen_screenshots.mjs
 *
 * Requires a running stack (`docker compose up -d`) and puppeteer. It is a
 * script rather than a committed set of hand-taken images so the screenshots can be
 * regenerated when the UI changes, and so nobody has to trust that the picture in the
 * README still resembles the product.
 *
 * Captures, in order:
 *   01 empty state            — the GUI before anything is asked
 *   02 tool discovery         — both servers, 17 tools, expanded JSON schema
 *   03 answer with citations  — the acceptance scenario, citation chips in the answer
 *   04 execution timeline     — per-step server, tool, duration, status
 *   05 rag evidence           — retrieved passages with scores
 *   06 write confirmation     — the dialog that gates create_issue
 */

import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";

const require = createRequire(
  "file:///C:/Users/kunwa/AppData/Roaming/npm/node_modules/@mermaid-js/mermaid-cli/"
);
const puppeteer = require("puppeteer");

const URL = process.env.GUI_URL ?? "http://localhost:5173";
const OUT = "docs/screenshots";

const SCENARIO =
  "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the " +
  "last 90 days, identify likely contributing factors, retrieve the relevant " +
  "operating procedure, and provide recommended actions with source evidence.";

const WRITE_REQUEST =
  "Create a GitHub issue for the recurring alarms on Boiler Feed Pump 101";

const shot = async (page, name) => {
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log(`  ${OUT}/${name}.png`);
};

/** Click the tab whose label starts with `label`. */
const openTab = (page, label) =>
  page.evaluate((l) => {
    const tab = [...document.querySelectorAll("[role=tab]")].find((t) =>
      t.textContent.startsWith(l)
    );
    tab?.click();
  }, label);

/** Ask a question and wait for the run to finish (the meta line only renders at the end). */
const ask = async (page, question) => {
  await page.evaluate((q) => {
    const box = document.querySelector("textarea");
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value"
    ).set;
    setter.call(box, q);
    box.dispatchEvent(new Event("input", { bubbles: true }));
  }, question);
  await page.click("button[type=submit]");
  await page.waitForFunction(
    () => document.querySelector(".meta") || document.querySelector("[role=dialog]"),
    { timeout: 60000 }
  );
};

const main = async () => {
  await mkdir(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    headless: "new",
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });

  console.log(`Capturing ${URL} …`);
  await page.goto(URL, { waitUntil: "networkidle0" });
  await page.waitForSelector(".pill-ok", { timeout: 20000 }); // servers connected
  await shot(page, "01-empty-state");

  await openTab(page, "Tools");
  await page.evaluate(() => {
    const t = [...document.querySelectorAll(".tool-head")].find((b) =>
      b.textContent.includes("search_assets")
    );
    t?.click();
  });
  await shot(page, "02-tool-discovery");

  await ask(page, SCENARIO);
  await shot(page, "03-answer-with-citations");

  await openTab(page, "Execution");
  await shot(page, "04-execution-timeline");

  await openTab(page, "Evidence");
  await shot(page, "05-rag-evidence");

  await ask(page, WRITE_REQUEST);
  await page.waitForSelector("[role=dialog]", { timeout: 30000 });
  await shot(page, "06-write-confirmation");

  await browser.close();
  console.log("Done.");
};

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
