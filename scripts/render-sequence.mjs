#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { chromium } from "@playwright/test";

function fail(message) {
  console.error(message);
  process.exitCode = 1;
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

async function resolveJson(value, requestDirectory) {
  if (typeof value === "string") return readJson(path.resolve(requestDirectory, value));
  return value;
}

function safeFrameId(value) {
  const id = String(value ?? "").toLowerCase();
  if (!/^[a-z0-9][a-z0-9._-]{1,95}$/.test(id)) {
    throw new Error(`Invalid frame id: ${value}`);
  }
  return id;
}

async function main() {
  const requestPath = process.argv[2];
  if (!requestPath) throw new Error("Usage: node scripts/render-sequence.mjs <request.json>");

  const absoluteRequestPath = path.resolve(requestPath);
  const requestDirectory = path.dirname(absoluteRequestPath);
  const request = await readJson(absoluteRequestPath);
  const profile = await resolveJson(request.profile, requestDirectory);
  const outputDirectory = path.resolve(requestDirectory, request.outputDirectory ?? "rendered-sequence");
  const baseUrl = request.baseUrl ?? "http://127.0.0.1:4173";
  const frames = Array.isArray(request.frames) ? request.frames : [];
  if (!profile || !frames.length) throw new Error("Request requires profile and at least one frame");

  await fs.mkdir(outputDirectory, { recursive: true });
  const browser = await chromium.launch({
    headless: request.headless !== false,
    args: [
      "--use-angle=swiftshader",
      "--use-gl=angle",
      "--enable-unsafe-swiftshader",
      "--disable-gpu-sandbox"
    ]
  });

  const page = await browser.newPage({
    viewport: request.viewport ?? { width: 1440, height: 1000 },
    deviceScaleFactor: request.deviceScaleFactor ?? 1
  });
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(message.text());
  });

  try {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Physical reference renderer" }).click();
    await page.waitForFunction(() => Boolean(window.__OPTGC_RESEARCH__));
    await page.evaluate(async (value) => window.__OPTGC_RESEARCH__.setProfile(value), profile);

    const canvas = page.locator(".research-renderer__canvas");
    await canvas.waitFor({ state: "visible" });
    const results = [];

    for (const frame of frames) {
      const id = safeFrameId(frame.id);
      const state = frame.state ?? {};
      const snapshot = await page.evaluate(async (value) => {
        window.__OPTGC_RESEARCH__.setState(value);
        await window.__OPTGC_RESEARCH__.render();
        return window.__OPTGC_RESEARCH__.snapshot();
      }, state);

      const imagePath = path.join(outputDirectory, `${id}.png`);
      if (frame.clip) {
        const canvasBox = await canvas.boundingBox();
        if (!canvasBox) throw new Error("Unable to resolve renderer canvas bounds");
        await page.screenshot({
          path: imagePath,
          clip: {
            x: canvasBox.x + Number(frame.clip.x ?? 0),
            y: canvasBox.y + Number(frame.clip.y ?? 0),
            width: Number(frame.clip.width),
            height: Number(frame.clip.height)
          }
        });
      } else {
        await canvas.screenshot({ path: imagePath });
      }

      const statePath = path.join(outputDirectory, `${id}.json`);
      await fs.writeFile(statePath, `${JSON.stringify(snapshot, null, 2)}\n`);
      results.push({ id, image: path.basename(imagePath), state: path.basename(statePath) });
    }

    const manifest = {
      schemaVersion: "1.0.0",
      generatedAt: new Date().toISOString(),
      baseUrl,
      profileCardId: profile.card?.id ?? "unknown",
      viewport: request.viewport ?? { width: 1440, height: 1000 },
      deviceScaleFactor: request.deviceScaleFactor ?? 1,
      frames: results,
      runtimeErrors
    };
    await fs.writeFile(
      path.join(outputDirectory, "render-sequence.json"),
      `${JSON.stringify(manifest, null, 2)}\n`
    );

    if (runtimeErrors.length) {
      throw new Error(`Renderer emitted runtime errors: ${runtimeErrors.join(" | ")}`);
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => fail(error.stack || error.message));
