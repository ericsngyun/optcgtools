import { expect, test } from "@playwright/test";

test("physical renderer initializes and exposes material channels", async ({ page }) => {
  const pageErrors = [];
  const consoleErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Holo Material Lab" })).toBeVisible();
  await page.getByRole("button", { name: "Physical reference renderer" }).click();

  const canvas = page.locator(".research-renderer__canvas");
  await expect(canvas).toBeVisible();
  await expect(page.locator(".research-status")).toContainText(/ready|profile-ready/i);
  await expect(page.locator(".research-error")).toHaveCount(0);

  const bounds = await canvas.boundingBox();
  expect(bounds?.width ?? 0).toBeGreaterThan(300);
  expect(bounds?.height ?? 0).toBeGreaterThan(300);

  const foilCheckbox = page.getByLabel("foil", { exact: true });
  await expect(foilCheckbox).toBeChecked();
  await foilCheckbox.uncheck();
  await expect(foilCheckbox).not.toBeChecked();
  await foilCheckbox.check();

  await page.getByRole("button", { name: "Solo", exact: true }).first().click();
  await expect(page.getByLabel("albedo", { exact: true })).toBeChecked();
  await expect(page.getByLabel("metallic", { exact: true })).not.toBeChecked();
  await page.getByRole("button", { name: "Restore" }).click();
  await expect(page.getByLabel("metallic", { exact: true })).toBeChecked();

  expect(pageErrors, `page errors: ${pageErrors.join(" | ")}`).toEqual([]);
  expect(consoleErrors, `console errors: ${consoleErrors.join(" | ")}`).toEqual([]);
});

test("CSS delivery renderer remains available", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".card.interactive")).toBeVisible();
  await expect(page.getByLabel("Material profile")).toHaveValue("sp-etched");
});
