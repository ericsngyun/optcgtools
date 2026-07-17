import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import {
  INTERNAL_PROTOTYPE_BANNER,
  PROTOTYPE_REPORT_KEYS,
  SYNTHETIC_NOTICE,
  classifyProfileState,
  compileCardProfile,
  cssVariablesFor,
  validateAssetUri,
  validatePrototypeReport,
  validatePublicationReport
} from "../scripts/lib/profile-compiler.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..");
const FIXTURE_PROFILE = path.join(
  REPO_ROOT,
  "examples/profiles/OP01-120.synthetic.example.json"
);
const PUBLIC_DIR = path.join(REPO_ROOT, "public");
const SERVE_PREFIX = "/__compiled__";

test("state gating: synthetic and prototype compile, unreviewed refuses", () => {
  const synthetic = classifyProfileState({
    provenance: { sourceType: "synthetic", reviewStatus: "unreviewed" }
  });
  expect(synthetic.state).toBe("synthetic");
  expect(synthetic.notice).toBe(SYNTHETIC_NOTICE);

  const prototype = classifyProfileState({
    lane: "reference",
    classification: { confidence: "reference-derived" },
    provenance: {
      sourceType: "public-reference-synthesis",
      reviewStatus: "unreviewed",
      referenceBundleId: "bundle-1"
    }
  });
  expect(prototype.state).toBe("internal-reference-prototype");
  expect(prototype.visibility).toBe("private-nonpublishable");
  expect(prototype.notice).toBe(INTERNAL_PROTOTYPE_BANNER);

  expect(() =>
    classifyProfileState({
      provenance: { sourceType: "controlled-capture", reviewStatus: "unreviewed" }
    })
  ).toThrow(/not compilable/);

  // Lane laundering by omission: reference-synthesis provenance without
  // lane: "reference" must refuse, even when approved.
  expect(() =>
    classifyProfileState({
      classification: { confidence: "production-validated" },
      provenance: { sourceType: "public-reference-synthesis", reviewStatus: "approved" }
    })
  ).toThrow(/must declare lane: 'reference'/);

  // Reference lane demands the reference vocabulary and a bundle id.
  expect(() =>
    classifyProfileState({
      lane: "reference",
      classification: { confidence: "not-a-state" },
      provenance: { sourceType: "controlled-capture", reviewStatus: "unreviewed" }
    })
  ).toThrow(/reference-lane profile is not compilable/);
});

test("publication attestation must be strictly shaped, passing, and hash-bound", () => {
  const digest = "a".repeat(64);
  const fullReport = (overrides = {}) => ({
    passed: true,
    state: "production-approved",
    errors: [],
    warnings: [],
    profile_digest: digest,
    ledger_head_digest: "b".repeat(64),
    checked_assets: { albedo: "c".repeat(64) },
    ...overrides
  });

  expect(validatePublicationReport(fullReport(), digest).ok).toBe(true);
  expect(validatePublicationReport(fullReport({ passed: false }), digest).ok).toBe(false);
  expect(
    validatePublicationReport(fullReport({ profile_digest: "d".repeat(64) }), digest).ok
  ).toBe(false);
  // Forged minimal report: passed + digest alone is not proof the gate ran.
  expect(validatePublicationReport({ passed: true, profile_digest: digest }, digest).ok).toBe(
    false
  );
  expect(validatePublicationReport(fullReport({ errors: "gate failed" }), digest).ok).toBe(
    false
  );
  expect(
    validatePublicationReport(fullReport({ ledger_head_digest: undefined }), digest).ok
  ).toBe(false);
  expect(validatePublicationReport(fullReport({ state: "unreviewed" }), digest).ok).toBe(false);
});

test("prototype attestation validation is strict, typed, and identity-bound", () => {
  const digest = "a".repeat(64);
  const profile = {
    card: { id: "TEST-001" },
    provenance: { referenceBundleId: "test-001-fixture-en-b001" }
  };
  const fullReport = (overrides = {}) => ({
    schema_version: "1.0.0",
    report_type: "prototype-attestation",
    passed: true,
    profile_digest: digest,
    ledger_head_digest: "b".repeat(64),
    lane: "reference",
    state: "internal-reference-prototype",
    profile_id: "test-001-fixture-v1",
    revision: 1,
    reference_bundle_id: "test-001-fixture-en-b001",
    source_quality_tier: "B",
    bundle_tier_record_digest: "c".repeat(64),
    evidence_packet: "docs/agent-ops/evidence-packets/synthetic.json",
    evidence_packet_digest: "d".repeat(64),
    adversarial_review: "review/critic-verdict.md",
    metrics_present: true,
    rights_status: "restricted-research",
    technical_reviewer: "Eric Yun",
    input_hashes: ["a".repeat(64)],
    verifier_version: "optcg-promote/1.1.0",
    ...overrides
  });

  expect(PROTOTYPE_REPORT_KEYS).toHaveLength(20);
  expect(validatePrototypeReport(fullReport(), digest, profile).ok).toBe(true);

  const rejects = (overrides) =>
    expect(validatePrototypeReport(fullReport(overrides), digest, profile).ok).toBe(false);
  // Forged minimal report (missing fields).
  expect(
    validatePrototypeReport({ passed: true, profile_digest: digest }, digest, profile).ok
  ).toBe(false);
  rejects({ profile_digest: "e".repeat(64) }); // stale digest
  rejects({ profile_id: "other-card-v1" }); // wrong identity
  rejects({ reference_bundle_id: "some-other-bundle" }); // wrong bundle
  rejects({ ledger_head_digest: "not-hex" });
  rejects({ rights_status: "unknown" });
  rejects({ adversarial_review: "" });
  rejects({ technical_reviewer: "" });
  rejects({ bundle_tier_record_digest: null }); // tier B without binding
  rejects({ source_quality_tier: "A" }); // tier A must carry null
  rejects({ extra: "forged" }); // unknown field

  // A check-publish-shaped report must not pass as a prototype attestation,
  // and a prototype attestation must not pass the production validator.
  const checkPublishShaped = {
    passed: true,
    state: "production-approved",
    errors: [],
    warnings: [],
    profile_digest: digest,
    ledger_head_digest: "b".repeat(64),
    checked_assets: { albedo: "c".repeat(64) }
  };
  expect(validatePrototypeReport(checkPublishShaped, digest, profile).ok).toBe(false);
  expect(validatePublicationReport(fullReport(), digest).ok).toBe(false);
});

test("private asset URIs are refused", () => {
  expect(validateAssetUri("private-media/frame.png").ok).toBe(false);
  expect(validateAssetUri("public-reference-bundles/b1/x.png").ok).toBe(false);
  expect(validateAssetUri("raw-captures/session/frame.png").ok).toBe(false);
  expect(validateAssetUri("https://example.com/x.png").ok).toBe(false);
  expect(validateAssetUri("data:image/png;base64,AAAA").ok).toBe(false);
  expect(validateAssetUri("mailto:someone@example.com").ok).toBe(false);
  expect(validateAssetUri("http:evil.png").ok).toBe(false);
  expect(validateAssetUri("../escape.png").ok).toBe(false);
  expect(validateAssetUri("/img/masks/ok.svg").ok).toBe(true);
});

test("css variable mapping is deterministic and complete", () => {
  const profile = {
    classification: { family: "manga-gold-metallic" },
    renderer: {
      foilStrength: 0.7,
      metallicStrength: 0.4,
      glossStrength: 0.6,
      textureStrength: 0.2,
      clearcoat: 1,
      clearcoatRoughness: 0.1,
      iridescenceThicknessMinNm: 100,
      iridescenceThicknessMaxNm: 500,
      anisotropyRotationRad: 0
    }
  };
  const channels = ["foilMask", "metallicMask", "glossMask", "textureMask", "suppressionMask"];
  const a = cssVariablesFor(profile, channels);
  const b = cssVariablesFor(profile, channels);
  expect(a).toEqual(b);
  expect(Object.keys(a)).toHaveLength(12);
  expect(a["--metallic-warmth"]).toBe("0.85");
  expect(a["--ink-suppression"]).toBe("0.85");
});

async function compileFixture() {
  const outDir = await fs.mkdtemp(path.join(os.tmpdir(), "profile-compiler-web-"));
  const result = await compileCardProfile({
    profilePath: FIXTURE_PROFILE,
    inputDir: PUBLIC_DIR,
    outDir
  });
  return { outDir, result };
}

const CONTENT_TYPES = {
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png"
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
      const body = await fs.readFile(file);
      await route.fulfill({
        status: 200,
        body,
        contentType: CONTENT_TYPES[path.extname(file)] ?? "application/octet-stream"
      });
    } catch {
      await route.fulfill({ status: 404, body: "not found" });
    }
  });
}

async function mountCompiledCard(page, manifest, { tier, staticPose }) {
  await page.evaluate(
    async ({ manifest: value, base, tier: requestedTier, staticPose: pose }) => {
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
          tier: requestedTier,
          staticPose: pose
        }
      });
    },
    { manifest, base: SERVE_PREFIX, tier, staticPose }
  );
}

test("compiled manifest renders through HoloCard with tier behavior", async ({ page }) => {
  const { outDir, result } = await compileFixture();
  await serveCompiled(page, outDir);
  await page.goto("/");

  await mountCompiledCard(page, result.manifest, {
    tier: "detail",
    staticPose: { x: 65, y: 40, opacity: 1 }
  });

  const card = page.locator("#compiled-host .card");
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute("data-card-profile", result.manifest.profile.id);
  await expect(card).toHaveAttribute("data-card-tier", "detail");
  await expect(card).toHaveAttribute("data-finish", "compiled");

  // Detail tier: independent layers visible with distinct masks.
  const layerVisibility = await card.evaluate((element) => {
    const layer = (name) =>
      getComputedStyle(element.querySelector(`.card__${name}`)).display !== "none";
    return {
      foilBase: layer("foil-base"),
      shine: layer("shine"),
      etch: layer("etch"),
      glare: layer("glare")
    };
  });
  expect(layerVisibility).toEqual({ foilBase: true, shine: true, etch: true, glare: true });

  const maskImages = await card.evaluate((element) => {
    const image = (name) => {
      const style = getComputedStyle(element.querySelector(`.card__${name}`));
      return style.maskImage || style.webkitMaskImage || "none";
    };
    return [image("shine"), image("foil-base"), image("glare")];
  });
  for (const image of maskImages) expect(image).toContain("__compiled__");

  // Grid tier: single simplified foil layer + glare only.
  await page.evaluate((tier) => window.__COMPILED_CARD__.$set({ tier }), "grid");
  await expect(card).toHaveAttribute("data-card-tier", "grid");
  const gridVisibility = await card.evaluate((element) => {
    const layer = (name) =>
      getComputedStyle(element.querySelector(`.card__${name}`)).display !== "none";
    return {
      foilBase: layer("foil-base"),
      shine: layer("shine"),
      etch: layer("etch"),
      glare: layer("glare")
    };
  });
  expect(gridVisibility).toEqual({ foilBase: false, shine: true, etch: false, glare: true });
});

test("grid tier suspends offscreen via IntersectionObserver", async ({ page }) => {
  const { outDir, result } = await compileFixture();
  await serveCompiled(page, outDir);
  await page.goto("/");
  await mountCompiledCard(page, result.manifest, {
    tier: "grid",
    staticPose: { x: 50, y: 50, opacity: 1 }
  });

  const card = page.locator("#compiled-host .card");
  await expect(card).toBeVisible();
  await expect(card).not.toHaveAttribute("data-suspended", "true");

  await page.evaluate(() => {
    const host = document.getElementById("compiled-host");
    host.style.inset = "auto";
    host.style.top = "-300vh";
    host.style.left = "0";
    host.style.width = "500px";
    host.style.height = "700px";
  });
  await expect(card).toHaveAttribute("data-suspended", "true");

  await page.evaluate(() => {
    const host = document.getElementById("compiled-host");
    host.style.top = "0";
  });
  await expect(card).not.toHaveAttribute("data-suspended", "true");
});

test("prefers-reduced-motion collapses compiled output to the static fallback", async ({
  page
}) => {
  const { outDir, result } = await compileFixture();
  await serveCompiled(page, outDir);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await mountCompiledCard(page, result.manifest, {
    tier: "detail",
    staticPose: { x: 70, y: 30, opacity: 1 }
  });

  const card = page.locator("#compiled-host .card");
  await expect(card).toBeVisible();
  const state = await card.evaluate((element) => {
    const layer = (name) =>
      getComputedStyle(element.querySelector(`.card__${name}`)).display !== "none";
    return {
      shine: layer("shine"),
      glare: layer("glare"),
      etch: layer("etch"),
      image: layer("image"),
      rotatorTransform: getComputedStyle(element.querySelector(".card__rotator")).transform
    };
  });
  expect(state.shine).toBe(false);
  expect(state.glare).toBe(false);
  expect(state.etch).toBe(false);
  expect(state.image).toBe(true);
  expect(state.rotatorTransform).toBe("none");
});
