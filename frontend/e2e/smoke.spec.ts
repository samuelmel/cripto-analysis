import { expect, test } from "@playwright/test";

test("navegação principal no desktop", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "O que o sistema faria hoje." })).toBeVisible();
  await expect(page.getByText("Dados defasados").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /NEAR/ }).first()).toBeVisible();

  const nav = page.locator("aside");
  await nav.getByRole("link", { name: "Carteiras" }).click();
  await expect(page.getByRole("heading", { name: /Capital simulado/ })).toBeVisible();
  await expect(page.getByText("Sem patrimônio publicado").first()).toBeVisible();

  await nav.getByRole("link", { name: "Pesquisa" }).click();
  await expect(page.getByRole("heading", { name: "O que sobreviveu ao teste." })).toBeVisible();
  await expect(page.getByText("1 promissor · 0 validado")).toBeVisible();

  await nav.getByRole("link", { name: "Ativos e mercado" }).click();
  await expect(page.getByRole("heading", { name: "Contexto antes da lista." })).toBeVisible();

  await page.goto("/#/mercado/BTC");
  await expect(page.getByRole("heading", { name: "Bitcoin" })).toBeVisible();
  await expect(page.getByText("3348 candles no histórico")).toBeVisible();

  await page.goto("/#/metodologia");
  await expect(page.getByRole("heading", { name: "O que este painel pode afirmar." })).toBeVisible();
  await expect(page.getByText("Somente leitura").first()).toBeVisible();

  expect(errors).toEqual([]);
});

test("navegação inferior no celular, sem overflow", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "O que o sistema faria hoje." })).toBeVisible();

  const nav = page.getByRole("navigation", { name: "Navegação principal" });
  await expect(nav.getByRole("link", { name: "Carteiras" })).toBeVisible();
  await nav.getByRole("link", { name: "Carteiras" }).click();
  await expect(page.getByRole("heading", { name: /Capital simulado/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "DCA fixo", exact: true })).toBeVisible();
  await expect(page.getByRole("table").first()).toBeVisible();

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
