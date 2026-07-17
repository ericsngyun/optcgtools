/**
 * Visual regression: compiled CSS output rendered through HoloCard versus the
 * physical research renderer at seven matched canonical poses.
 *
 * The CSS tier is a stylized approximation of the physically based renderer,
 * so tolerances are deliberately generous and documented in
 * docs/operations/css-profile-compiler.md. Hard assertions only guard gross
 * failures: blank output, unresponsive layers, or a full-card rainbow.
 * Measured per-pose differences are attached to the test report and written
 * next to a pose-grid contact sheet under test-results/.
 */

import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { compileCardProfile } from "../scripts/lib/profile-compiler.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..");
const FIXTURE_PROFILE = path.join(
  REPO_ROOT,
  "examples/profiles/OP01-120.synthetic.example.json"
);
const PUBLIC_DIR = path.join(REPO_ROOT, "public");
const SERVE_PREFIX = "/__compiled__";
const OUTPUT_DIR = path.join(REPO_ROOT, "test-results", "profile-compiler-visual");

// Detail-tier tilt for the fixture: min(maxTiltDeg=11, 16) = 11deg.
// CSS pointer x drives yaw (rotateY), pointer y drives pitch (rotateX);
// research tiltYDeg is yaw, tiltXDeg is pitch with the opposite sign
// convention (three.js +x rotation tips the card top toward the camera).
const TILT = 11;
// presentationMode "flat" renders the true front face: the rounded cardstock
// body occludes the front artwork under the software-GL test environment.
// A low light elevation keeps the specular response on the card face so the
// physical reference is comparable with the pointer-driven CSS glare.
const LIGHT = {
  lightAzimuthDeg: 0,
  lightElevationDeg: 15,
  lightDistance: 3.2,
  exposure: 1.15,
  presentationMode: "flat"
};

const POSES = [
  {
    id: "neutral",
    css: { x: 50, y: 50, opacity: 0 },
    research: { tiltXDeg: 0, tiltYDeg: 0, ...LIGHT }
  },
  {
    id: "tilt-left",
    css: { x: 10, y: 50, opacity: 1 },
    research: { tiltXDeg: 0, tiltYDeg: -TILT * 0.8, ...LIGHT }
  },
  {
    id: "tilt-right",
    css: { x: 90, y: 50, opacity: 1 },
    research: { tiltXDeg: 0, tiltYDeg: TILT * 0.8, ...LIGHT }
  },
  {
    id: "tilt-top",
    css: { x: 50, y: 10, opacity: 1 },
    research: { tiltXDeg: -TILT * 0.8, tiltYDeg: 0, ...LIGHT }
  },
  {
    id: "tilt-bottom",
    css: { x: 50, y: 90, opacity: 1 },
    research: { tiltXDeg: TILT * 0.8, tiltYDeg: 0, ...LIGHT }
  },
  {
    id: "glare-center",
    css: { x: 50, y: 50, opacity: 1 },
    research: { tiltXDeg: 0, tiltYDeg: 0, ...LIGHT, lightDistance: 1.8 }
  },
  {
    id: "glare-edge",
    css: { x: 85, y: 15, opacity: 1 },
    research: {
      tiltXDeg: 0,
      tiltYDeg: 0,
      ...LIGHT,
      lightAzimuthDeg: 20,
      lightElevationDeg: 30,
      lightDistance: 2.6
    }
  }
];

// Documented generous tolerances — the CSS tier is an approximation.
const TOLERANCES = {
  maxMeanAbsDiff: 0.45,
  minActiveCssStd: 0.01,
  maxHighSatFraction: 0.85,
  minPoseResponse: 0.004
};

const CONTENT_TYPES = {
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml"
};

async function serveCompiled(page, outDir) {
  await page.route(`**${SERVE_PREFIX}/**`, async (route) => {
    const url = new URL(route.request().url());
    const relative = url.pathname.slice(SERVE_PREFIX.length).replace(/^\/+/, "");
    const file = path.resolve(outDir, relative);
    if (!file.startsWith(path.resolve(outDir) + path.sep)) {
      await route.fulfill({ status: 403, body: "forbidden" });
      return;
    }
    try {
      await route.fulfill({
        status: 200,
        body: await fs.readFile(file),
        contentType: CONTENT_TYPES[path.extname(file)] ?? "application/octet-stream"
      });
    } catch {
      await route.fulfill({ status: 404, body: "not found" });
    }
  });
}

test("compiled CSS approximates the research renderer at seven canonical poses", async ({
  page
}, testInfo) => {
  test.setTimeout(240_000);

  const outDir = await fs.mkdtemp(path.join(os.tmpdir(), "profile-compiler-visual-"));
  const { manifest } = await compileCardProfile({
    profilePath: FIXTURE_PROFILE,
    inputDir: PUBLIC_DIR,
    outDir
  });
  const profile = JSON.parse(await fs.readFile(FIXTURE_PROFILE, "utf8"));

  await serveCompiled(page, outDir);
  await page.setViewportSize({ width: 1360, height: 960 });
  await page.goto("/");

  // --- Research renderer captures ------------------------------------------
  await page.getByRole("button", { name: "Physical reference renderer" }).click();
  await page.waitForFunction(() => Boolean(window.__OPTGC_RESEARCH__));
  await expect(page.locator(".research-status")).toContainText(/ready|profile-ready/i, {
    timeout: 30_000
  });
  await page.evaluate(async (value) => window.__OPTGC_RESEARCH__.setProfile(value), profile);

  const canvas = page.locator(".research-renderer__canvas");
  await canvas.waitFor({ state: "visible" });

  const researchShots = {};
  for (const pose of POSES) {
    await page.evaluate(async (state) => {
      window.__OPTGC_RESEARCH__.setState(state);
      await window.__OPTGC_RESEARCH__.render();
    }, pose.research);
    researchShots[pose.id] = (await canvas.screenshot()).toString("base64");
  }

  // --- Compiled CSS captures through HoloCard -------------------------------
  await page.evaluate(
    async ({ manifest: value, base }) => {
      const { default: CardProxy } = await import("/src/lib/components/CardProxy.svelte");
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = `${base}/card.css`;
      await new Promise((resolve, reject) => {
        link.onload = resolve;
        link.onerror = () => reject(new Error("compiled card.css failed to load"));
        document.head.appendChild(link);
      });
      const host = document.createElement("div");
      host.id = "compiled-host";
      host.style.cssText =
        "position:fixed;inset:0;z-index:9999;background:#0c0c12;display:grid;place-items:center;";
      document.body.appendChild(host);
      window.__COMPILED_CARD__ = new CardProxy({
        target: host,
        props: {
          manifest: value,
          manifestBase: base,
          tier: "detail",
          staticPose: { x: 50, y: 50, opacity: 0 }
        }
      });
    },
    { manifest, base: SERVE_PREFIX }
  );

  const card = page.locator("#compiled-host .card");
  await expect(card).toBeVisible();

  const cssShots = {};
  for (const pose of POSES) {
    await page.evaluate(async (value) => {
      window.__COMPILED_CARD__.$set({ staticPose: value });
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }, pose.css);
    cssShots[pose.id] = (await card.screenshot()).toString("base64");
  }

  // --- Compare in-page (canvas pixel metrics, no extra dependencies) --------
  const comparison = await page.evaluate(
    async ({ poses, cssShots: css, researchShots: research, width, height }) => {
      const decode = async (base64) => {
        const image = new Image();
        image.src = `data:image/png;base64,${base64}`;
        await image.decode();
        return image;
      };
      const draw = (image, crop) => {
        const canvasEl = document.createElement("canvas");
        canvasEl.width = width;
        canvasEl.height = height;
        const context = canvasEl.getContext("2d", { willReadFrequently: true });
        if (crop) {
          context.drawImage(
            image,
            crop.x,
            crop.y,
            crop.width,
            crop.height,
            0,
            0,
            width,
            height
          );
        } else {
          context.drawImage(image, 0, 0, width, height);
        }
        return { canvasEl, data: context.getImageData(0, 0, width, height).data };
      };
      const luminance = (data, index) =>
        (0.2126 * data[index] + 0.7152 * data[index + 1] + 0.0722 * data[index + 2]) / 255;
      const contentBounds = (image) => {
        const probe = document.createElement("canvas");
        probe.width = image.naturalWidth;
        probe.height = image.naturalHeight;
        const context = probe.getContext("2d", { willReadFrequently: true });
        context.drawImage(image, 0, 0);
        const { data } = context.getImageData(0, 0, probe.width, probe.height);
        const corner = luminance(data, 0);
        let minX = probe.width;
        let minY = probe.height;
        let maxX = 0;
        let maxY = 0;
        for (let y = 0; y < probe.height; y += 2) {
          for (let x = 0; x < probe.width; x += 2) {
            const index = (y * probe.width + x) * 4;
            if (Math.abs(luminance(data, index) - corner) > 0.08) {
              if (x < minX) minX = x;
              if (x > maxX) maxX = x;
              if (y < minY) minY = y;
              if (y > maxY) maxY = y;
            }
          }
        }
        if (maxX <= minX || maxY <= minY) {
          return { x: 0, y: 0, width: probe.width, height: probe.height };
        }
        return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
      };
      const stats = (data) => {
        let sum = 0;
        let sumSquares = 0;
        let highSat = 0;
        const pixels = data.length / 4;
        for (let index = 0; index < data.length; index += 4) {
          const value = luminance(data, index);
          sum += value;
          sumSquares += value * value;
          const max = Math.max(data[index], data[index + 1], data[index + 2]);
          const min = Math.min(data[index], data[index + 1], data[index + 2]);
          if (max > 40 && (max - min) / max > 0.5) highSat += 1;
        }
        const mean = sum / pixels;
        return {
          mean,
          std: Math.sqrt(Math.max(0, sumSquares / pixels - mean * mean)),
          highSatFraction: highSat / pixels
        };
      };
      const meanAbsDiff = (a, b) => {
        let sum = 0;
        for (let index = 0; index < a.length; index += 4) {
          sum += Math.abs(luminance(a, index) - luminance(b, index));
        }
        return sum / (a.length / 4);
      };
      const diffImage = (a, b) => {
        const canvasEl = document.createElement("canvas");
        canvasEl.width = width;
        canvasEl.height = height;
        const context = canvasEl.getContext("2d");
        const output = context.createImageData(width, height);
        for (let index = 0; index < a.length; index += 4) {
          const value = Math.round(
            Math.abs(luminance(a, index) - luminance(b, index)) * 255
          );
          output.data[index] = value;
          output.data[index + 1] = value;
          output.data[index + 2] = value;
          output.data[index + 3] = 255;
        }
        context.putImageData(output, 0, 0);
        return canvasEl;
      };

      const rows = [];
      const cssData = {};
      for (const pose of poses) {
        const cssImage = await decode(css[pose.id]);
        const researchImage = await decode(research[pose.id]);
        const cssDrawn = draw(cssImage);
        const researchDrawn = draw(researchImage, contentBounds(researchImage));
        cssData[pose.id] = cssDrawn.data;
        const diffCanvas = diffImage(cssDrawn.data, researchDrawn.data);
        rows.push({
          id: pose.id,
          metrics: {
            meanAbsDiff: meanAbsDiff(cssDrawn.data, researchDrawn.data),
            css: stats(cssDrawn.data),
            research: stats(researchDrawn.data)
          },
          canvases: [cssDrawn.canvasEl, researchDrawn.canvasEl, diffCanvas]
        });
      }

      const leftRight = meanAbsDiff(cssData["tilt-left"], cssData["tilt-right"]);
      const neutralGlare = meanAbsDiff(cssData.neutral, cssData["glare-center"]);

      // Pose-grid contact sheet: rows = poses, columns = css | research | diff.
      const margin = 24;
      const labelHeight = 18;
      const sheet = document.createElement("canvas");
      sheet.width = margin + 3 * (width + margin);
      sheet.height = margin + rows.length * (height + labelHeight + margin);
      const sheetContext = sheet.getContext("2d");
      sheetContext.fillStyle = "#101018";
      sheetContext.fillRect(0, 0, sheet.width, sheet.height);
      sheetContext.fillStyle = "#e8e8f0";
      sheetContext.font = "13px monospace";
      rows.forEach((row, rowIndex) => {
        const top = margin + rowIndex * (height + labelHeight + margin);
        sheetContext.fillText(
          `${row.id} — css | research | diff (meanAbsDiff ${row.metrics.meanAbsDiff.toFixed(3)})`,
          margin,
          top + 13
        );
        row.canvases.forEach((canvasEl, columnIndex) => {
          sheetContext.drawImage(
            canvasEl,
            margin + columnIndex * (width + margin),
            top + labelHeight
          );
        });
      });

      return {
        poses: rows.map(({ id, metrics }) => ({ id, metrics })),
        leftRight,
        neutralGlare,
        contactSheet: sheet.toDataURL("image/png").split(",")[1]
      };
    },
    { poses: POSES, cssShots, researchShots, width: 240, height: 336 }
  );

  // --- Persist evidence ------------------------------------------------------
  await fs.mkdir(OUTPUT_DIR, { recursive: true });
  await fs.writeFile(
    path.join(OUTPUT_DIR, "contact-sheet.png"),
    Buffer.from(comparison.contactSheet, "base64")
  );
  const metricsReport = {
    fixture: manifest.profile.id,
    tolerances: TOLERANCES,
    poses: comparison.poses,
    leftRightResponse: comparison.leftRight,
    neutralGlareResponse: comparison.neutralGlare
  };
  await fs.writeFile(
    path.join(OUTPUT_DIR, "pose-metrics.json"),
    `${JSON.stringify(metricsReport, null, 2)}\n`
  );
  await testInfo.attach("pose-metrics", {
    body: JSON.stringify(metricsReport, null, 2),
    contentType: "application/json"
  });
  await testInfo.attach("contact-sheet", {
    body: Buffer.from(comparison.contactSheet, "base64"),
    contentType: "image/png"
  });

  // --- Gross-failure assertions (generous, documented) -----------------------
  for (const pose of comparison.poses) {
    expect(
      pose.metrics.meanAbsDiff,
      `${pose.id}: CSS diverges grossly from the research renderer`
    ).toBeLessThan(TOLERANCES.maxMeanAbsDiff);
    expect(
      pose.metrics.css.std,
      `${pose.id}: CSS output is blank/uniform`
    ).toBeGreaterThan(TOLERANCES.minActiveCssStd);
    expect(
      pose.metrics.css.highSatFraction,
      `${pose.id}: full-card rainbow detected`
    ).toBeLessThan(TOLERANCES.maxHighSatFraction);
  }
  expect(
    comparison.leftRight,
    "foil layers do not respond to pose (left vs right identical)"
  ).toBeGreaterThan(TOLERANCES.minPoseResponse);
  expect(
    comparison.neutralGlare,
    "glare/foil layers do not activate (neutral vs glare-center identical)"
  ).toBeGreaterThan(TOLERANCES.minPoseResponse);
});
