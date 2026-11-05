// Captura as páginas principais do painel para docs/img (figura 7 do README e do LinkedIn).
// Requer a API em :8000 e o painel em :5173:  node frontend/scripts/capture-screens.mjs
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const out = resolve(import.meta.dirname, "../../docs/img");
mkdirSync(out, { recursive: true });
const base = process.env.PAINEL_URL ?? "http://localhost:5173";
const pages = [
  ["07_painel_hoje", "/", "O que o sistema faria hoje."],
  ["07_painel_pesquisa", "/#/pesquisa", "O que sobreviveu ao teste."],
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
for (const [name, path, heading] of pages) {
  await page.goto(base + path);
  await page.getByRole("heading", { name: new RegExp(heading) }).first().waitFor({ timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${out}/${name}.png` });
  console.log(`${out}/${name}.png`);
}
await browser.close();
