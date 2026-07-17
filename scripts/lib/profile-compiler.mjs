/**
 * Card material-profile → CSS delivery compiler.
 *
 * Pure data flow: a card-material-profile JSON plus the asset files it
 * declares go in; deterministic card.css + card-manifest.json + copied
 * assets come out. The compiler NEVER creates or infers material maps and
 * NEVER contains card-specific constants (enforced by a source-scan test).
 *
 * State gating (see docs/operations/css-profile-compiler.md):
 *  - synthetic fixtures compile with a "synthetic — not an accurate card"
 *    notice;
 *  - reference-lane profiles compile as INTERNAL REFERENCE PROTOTYPE output
 *    marked private/non-publishable;
 *  - approved production profiles require a publication-gate attestation
 *    (the JSON report emitted by `optcg-review check-publish`) that passed
 *    and is bound to the same profile sha256 — the gate is consumed as
 *    proof, never reimplemented;
 *  - every other state is refused.
 */

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

import { validateResearchProfile } from "../../src/lib/research/profile.js";

export const COMPILER_OUTPUT_SCHEMA_VERSION = "1.0.0";
export const GENERATOR_ID = "compile-card-profile@1";

export const SYNTHETIC_NOTICE = "synthetic — not an accurate card";
export const INTERNAL_PROTOTYPE_BANNER =
  "INTERNAL REFERENCE PROTOTYPE — PRIVATE, NON-PUBLISHABLE";

/** Path segments that may never appear in a compiled asset reference. */
export const FORBIDDEN_ASSET_PATH_SEGMENTS = Object.freeze([
  "private-media",
  "public-reference-bundles",
  "raw-captures",
  "private-references",
  "marketplace-references"
]);

/**
 * Confidence/source vocabularies mirrored from the profile schema conditional
 * and src/optcg_material/review.py. The compiler enforces the same lane
 * discipline so a profile cannot launder its lane by omission.
 */
export const PHYSICAL_PUBLISHABLE_CONFIDENCE = Object.freeze([
  "capture-validated",
  "production-validated"
]);
export const REFERENCE_PUBLISHABLE_CONFIDENCE = Object.freeze([
  "reference-derived",
  "source-supported simulation",
  "visually fitted across real-card references"
]);
export const PHYSICAL_SOURCE_TYPES = Object.freeze([
  "controlled-capture",
  "video-sweep",
  "licensed-photo",
  "marketplace-reference",
  "synthetic"
]);
export const REFERENCE_SOURCE_TYPE = "public-reference-synthesis";

/** Material channels the CSS tiers can route, in canonical order. */
export const CSS_CHANNELS = Object.freeze([
  "albedo",
  "foilMask",
  "metallicMask",
  "glossMask",
  "textureMask",
  "suppressionMask",
  "cardBack"
]);

/** Channels the CSS approximation cannot reproduce → WebGL handoff. */
export const WEBGL_ONLY_CHANNELS = Object.freeze([
  "normalMap",
  "directionMap",
  "gltf"
]);

const ALL_CHANNELS = Object.freeze([...CSS_CHANNELS, ...WEBGL_ONLY_CHANNELS, "regionMask"]);

const DYNAMIC_CHANNELS = Object.freeze([
  "foilMask",
  "metallicMask",
  "glossMask",
  "textureMask",
  "suppressionMask"
]);

/**
 * Finish-family render hints. Families are schema-level enums shared by many
 * cards — these are material-family presets, not card-specific constants.
 */
export const FAMILY_RENDER_HINTS = Object.freeze({
  "rare-holo-standard": { metallicWarmth: 0.5 },
  "sr-foil-basic": { metallicWarmth: 0.5 },
  "sr-textured": { metallicWarmth: 0.55 },
  "alt-art-coated": { metallicWarmth: 0.45 },
  "alt-art-textured": { metallicWarmth: 0.55 },
  "manga-prismatic-panel": { metallicWarmth: 0.55 },
  "manga-gold-metallic": { metallicWarmth: 0.85 },
  "sp-gold-ornamental": { metallicWarmth: 0.8 },
  "sp-manga-scene": { metallicWarmth: 0.6 },
  "sp-color-field": { metallicWarmth: 0.5 },
  "leader-parallel-textured": { metallicWarmth: 0.55 },
  "treasure-rare": { metallicWarmth: 0.7 },
  unknown: { metallicWarmth: 0.5 }
});

export class CompileRefusal extends Error {
  constructor(message) {
    super(message);
    this.name = "CompileRefusal";
  }
}

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

function finite(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

/** Deterministic short number formatting (max 4 decimals, no float jitter). */
export function formatNumber(value) {
  const rounded = Math.round(value * 10000) / 10000;
  return Object.is(rounded, -0) ? "0" : String(rounded);
}

export function sha256Hex(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

/** Canonical JSON: recursively sorted keys, 2-space indent, trailing newline. */
export function canonicalJson(value) {
  return `${JSON.stringify(sortValue(value), null, 2)}\n`;
}

function sortValue(value) {
  if (Array.isArray(value)) return value.map(sortValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, sortValue(value[key])])
    );
  }
  return value;
}

/**
 * Classify the compilable state of a profile.
 * Returns { state, visibility, notice } or throws CompileRefusal.
 */
export function classifyProfileState(profile) {
  const lane = profile.lane ?? "physical";
  const sourceType = profile.provenance?.sourceType;
  const reviewStatus = profile.provenance?.reviewStatus;
  const confidence = profile.classification?.confidence;

  // Lane may not be laundered by omission (mirrors the schema conditional and
  // review.py): reference-synthesis provenance forces the reference lane.
  if (sourceType === REFERENCE_SOURCE_TYPE && lane !== "reference") {
    throw new CompileRefusal(
      `profile with provenance.sourceType '${REFERENCE_SOURCE_TYPE}' must declare ` +
        "lane: 'reference'; it may not be classified as a physical profile"
    );
  }

  if (lane === "reference") {
    // Reference-lane compilation is internal preview output only (ADR-0002)
    // and must satisfy the reference-lane schema conditional exactly.
    const problems = [];
    if (sourceType !== REFERENCE_SOURCE_TYPE) {
      problems.push(
        `provenance.sourceType must be '${REFERENCE_SOURCE_TYPE}' (got '${sourceType}')`
      );
    }
    if (!REFERENCE_PUBLISHABLE_CONFIDENCE.includes(confidence)) {
      problems.push(
        `classification.confidence '${confidence}' is not a reference-lane label ` +
          `(allowed: ${REFERENCE_PUBLISHABLE_CONFIDENCE.join(", ")})`
      );
    }
    if (
      typeof profile.provenance?.referenceBundleId !== "string" ||
      profile.provenance.referenceBundleId.length === 0
    ) {
      problems.push("provenance.referenceBundleId is required for reference-lane profiles");
    }
    if (problems.length > 0) {
      throw new CompileRefusal(
        `reference-lane profile is not compilable: ${problems.join("; ")}`
      );
    }
    return {
      state: "internal-reference-prototype",
      visibility: "private-nonpublishable",
      notice: INTERNAL_PROTOTYPE_BANNER,
      requiresPublicationReport: false
    };
  }

  if (sourceType === "synthetic") {
    return {
      state: "synthetic",
      visibility: "synthetic-fixture",
      notice: SYNTHETIC_NOTICE,
      requiresPublicationReport: false
    };
  }

  if (
    reviewStatus === "approved" &&
    PHYSICAL_PUBLISHABLE_CONFIDENCE.includes(confidence) &&
    PHYSICAL_SOURCE_TYPES.includes(sourceType)
  ) {
    return {
      state: "production",
      visibility: "public",
      notice: null,
      requiresPublicationReport: true
    };
  }

  throw new CompileRefusal(
    "profile state is not compilable: " +
      `lane='${lane}', sourceType='${sourceType}', reviewStatus='${reviewStatus}', ` +
      `confidence='${confidence}'. Compilable states: synthetic fixture ` +
      "(provenance.sourceType='synthetic'), reference lane (internal prototype, " +
      "private output, reference labels + bundle id required), or approved " +
      "production (reviewStatus='approved', physical publishable confidence, " +
      "physical sourceType, plus a passing publication-gate report)."
  );
}

const SHA256_HEX = /^[0-9a-f]{64}$/;

/**
 * Validate a publication-gate attestation (the JSON report written by
 * `optcg-review check-publish --report`, serialized from review.py's
 * PublicationReport model: passed, state, errors, warnings, profile_digest,
 * ledger_head_digest, checked_assets). The compiler does not reimplement the
 * gate; it requires strictly-shaped proof the gate passed for the exact
 * profile bytes. Any missing or mistyped field is a rejection.
 */
const PUBLICATION_REPORT_ALLOWED_KEYS = new Set([
  "passed",
  "errors",
  "warnings",
  "state",
  "ledger_head_digest",
  "checked_assets",
  "profile_digest",
]);

export function validatePublicationReport(report, profileSha256) {
  const errors = [];
  if (!report || typeof report !== "object" || Array.isArray(report)) {
    errors.push("publication report must be a JSON object");
    return { ok: false, errors };
  }

  // Strict shape (independent re-review finding): unknown keys are refused so
  // a forged report cannot smuggle context past the gate consumer.
  for (const key of Object.keys(report)) {
    if (!PUBLICATION_REPORT_ALLOWED_KEYS.has(key)) {
      errors.push(`publication report contains unknown field '${key}'`);
    }
  }

  if (report.passed !== true) {
    errors.push("publication report did not pass (passed must be boolean true)");
  }
  if (!Array.isArray(report.errors)) {
    errors.push("publication report errors must be an array");
  } else if (report.errors.length > 0) {
    errors.push(`publication report recorded gate errors: ${report.errors.join("; ")}`);
  }
  if (!Array.isArray(report.warnings)) {
    errors.push("publication report warnings must be an array");
  }
  if (report.state !== "production-approved") {
    errors.push(
      `publication report state must be 'production-approved' (got '${report.state}')`
    );
  }
  if (typeof report.ledger_head_digest !== "string" ||
      !SHA256_HEX.test(report.ledger_head_digest.toLowerCase())) {
    errors.push("publication report ledger_head_digest must be a sha256 hex digest");
  }
  const checked = report.checked_assets;
  if (!checked || typeof checked !== "object" || Array.isArray(checked)) {
    errors.push("publication report checked_assets must be an object");
  } else {
    const entries = Object.entries(checked);
    if (entries.length === 0) {
      errors.push(
        "publication report checked_assets is empty; the gate must have hashed " +
          "the profile's local assets"
      );
    }
    for (const [name, digest] of entries) {
      if (typeof digest !== "string" || !SHA256_HEX.test(digest.toLowerCase())) {
        errors.push(`publication report checked asset '${name}' lacks a sha256 hex digest`);
      }
    }
  }
  if (typeof report.profile_digest !== "string" ||
      !SHA256_HEX.test(report.profile_digest.toLowerCase())) {
    errors.push("publication report is missing a profile_digest sha256 binding");
  } else if (report.profile_digest.toLowerCase() !== profileSha256.toLowerCase()) {
    errors.push(
      "publication report is bound to a different profile: " +
        `report=${report.profile_digest.toLowerCase()}, candidate=${profileSha256}`
    );
  }
  return { ok: errors.length === 0, errors };
}

/** Reject unsafe or private asset URIs before any path resolution. */
export function validateAssetUri(uri) {
  if (typeof uri !== "string" || uri.length === 0) {
    return { ok: false, reason: "asset uri must be a non-empty string" };
  }
  // Any URI scheme (remote, data:, mailto:, scheme without slashes) is
  // refused: the compiler only accepts plain paths inside the input directory.
  if (/^[a-z][a-z0-9+.-]*:/i.test(uri) || uri.startsWith("//")) {
    return {
      ok: false,
      reason: "asset URIs with a scheme (or protocol-relative //) are refused; " +
        "only plain paths inside the input directory can be compiled"
    };
  }
  if (uri.includes("\\") || uri.startsWith("~")) {
    return { ok: false, reason: "asset uri uses a disallowed path form" };
  }
  const segments = uri.split("/").filter(Boolean);
  if (segments.includes("..")) {
    return { ok: false, reason: "asset uri may not traverse parent directories" };
  }
  const forbidden = segments.find((segment) =>
    FORBIDDEN_ASSET_PATH_SEGMENTS.includes(segment)
  );
  if (forbidden) {
    return { ok: false, reason: `asset uri references a private source area: ${forbidden}/` };
  }
  return { ok: true, reason: null };
}

/**
 * Resolve an asset uri under the input directory. Web-root URIs ("/img/x")
 * resolve inside inputDir; the resolved path must stay inside inputDir.
 */
export function resolveAssetPath(uri, inputDir) {
  const validation = validateAssetUri(uri);
  if (!validation.ok) {
    throw new CompileRefusal(`refused asset '${uri}': ${validation.reason}`);
  }
  const root = path.resolve(inputDir);
  const relative = uri.replace(/^\/+/, "");
  const resolved = path.resolve(root, relative);
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    throw new CompileRefusal(
      `refused asset '${uri}': resolves outside the input directory ${root}`
    );
  }
  return resolved;
}

function safeExtension(uri) {
  const ext = path.posix.extname(uri).toLowerCase();
  return /^\.[a-z0-9]{1,8}$/.test(ext) ? ext : ".bin";
}

/** Deterministic output name for a copied asset. */
export function assetOutputName(channel, sha256, uri) {
  return `${channel}-${sha256.slice(0, 16)}${safeExtension(uri)}`;
}

/**
 * Map bounded renderer parameters onto the documented CSS variable set.
 * Every formula is documented in docs/operations/css-profile-compiler.md.
 */
export function cssVariablesFor(profile, channels) {
  const renderer = profile.renderer ?? {};
  const family = profile.classification?.family ?? "unknown";
  const hints = FAMILY_RENDER_HINTS[family] ?? FAMILY_RENDER_HINTS.unknown;

  const foilStrength = clamp(finite(renderer.foilStrength, 0), 0, 2);
  const metallicStrength = clamp(finite(renderer.metallicStrength, 0), 0, 2);
  const glossStrength = clamp(finite(renderer.glossStrength, 0), 0, 2);
  const textureStrength = clamp(finite(renderer.textureStrength, 0), 0, 2);
  const clearcoat = clamp(finite(renderer.clearcoat, 0), 0, 1);
  const clearcoatRoughness = clamp(finite(renderer.clearcoatRoughness, 0.2), 0, 1);
  const rotationDeg = (finite(renderer.anisotropyRotationRad, 0) * 180) / Math.PI;
  const thicknessMin = clamp(finite(renderer.iridescenceThicknessMinNm, 0), 0, 2000);
  const thicknessMax = clamp(finite(renderer.iridescenceThicknessMaxNm, 0), 0, 2000);
  const thicknessSpan = Math.max(0, thicknessMax - thicknessMin);

  const bandAngle = ((117 + rotationDeg) % 360 + 360) % 360;
  const textureDirection = ((38 + rotationDeg) % 180 + 180) % 180;

  return {
    "--foil-strength": formatNumber(foilStrength),
    "--foil-band-angle": `${formatNumber(bandAngle)}deg`,
    "--foil-band-width": `${formatNumber(clamp(6 + (thicknessSpan / 2000) * 10, 6, 16))}%`,
    "--foil-hue-offset": `${formatNumber((thicknessMin / 2000) * 360)}deg`,
    "--metallic-strength": formatNumber(metallicStrength),
    "--metallic-warmth": formatNumber(hints.metallicWarmth),
    "--gloss-strength": formatNumber(clamp(glossStrength * (0.4 + 0.6 * clearcoat), 0, 2)),
    "--gloss-size": `${formatNumber(55 + clearcoatRoughness * 70)}%`,
    "--texture-strength": formatNumber(textureStrength),
    "--texture-scale": "1",
    "--texture-direction": `${formatNumber(textureDirection)}deg`,
    "--ink-suppression": channels.includes("suppressionMask") ? "0.85" : "0"
  };
}

/** Tier plan: grid (simplified), detail (independent channels), static. */
export function tierPlan(profile, channels) {
  const maxTilt = clamp(finite(profile.renderer?.maxTiltDeg, 12), 0, 30);
  const detailTilt = Math.min(maxTilt, 16);
  const gridTilt = Math.round((detailTilt / 2) * 2) / 2;
  const foil = clamp(finite(profile.renderer?.foilStrength, 0), 0, 2);
  const metallic = clamp(finite(profile.renderer?.metallicStrength, 0), 0, 2);

  const detailLayers = [];
  if (channels.includes("metallicMask")) detailLayers.push("metallic");
  if (channels.includes("foilMask")) detailLayers.push("foil");
  if (channels.includes("textureMask")) detailLayers.push("texture");
  if (channels.includes("suppressionMask")) detailLayers.push("suppression");
  if (channels.includes("glossMask")) detailLayers.push("glare");

  const gridLayers = [];
  if (channels.includes("foilMask")) gridLayers.push("foil");
  if (channels.includes("glossMask")) gridLayers.push("glare");

  const staticOnly = detailLayers.length === 0;
  return {
    grid: {
      maxTiltDeg: staticOnly ? 0 : gridTilt,
      layers: gridLayers,
      suspendOffscreen: true,
      effectiveFoilStrength: Number(
        formatNumber(clamp(0.7 * foil + 0.3 * metallic, 0, 1.4))
      )
    },
    detail: {
      maxTiltDeg: staticOnly ? 0 : detailTilt,
      layers: detailLayers,
      suspendOffscreen: false
    },
    static: {
      maxTiltDeg: 0,
      layers: [],
      staticOnly
    }
  };
}

/** WebGL handoff manifest stub — only when CSS cannot reproduce a channel. */
export function webglHandoffFor(profile, declaredChannels) {
  const reasons = WEBGL_ONLY_CHANNELS.filter((channel) =>
    declaredChannels.includes(channel)
  ).map((channel) => `asset channel '${channel}' has no CSS equivalent`);
  if (reasons.length === 0) return null;
  const renderer = profile.renderer ?? {};
  return {
    schemaVersion: COMPILER_OUTPUT_SCHEMA_VERSION,
    generator: GENERATOR_ID,
    kind: "webgl-handoff-stub",
    reasons,
    webglPreset: renderer.webglPreset ?? null,
    channels: WEBGL_ONLY_CHANNELS.filter((channel) => declaredChannels.includes(channel))
  };
}

function cssSelector(profileId, suffix = "") {
  return `.card[data-card-profile="${profileId}"]${suffix}`;
}

/**
 * Deterministic card.css generation. The layer recipes below are shared,
 * variable-driven templates — profile identity only enters through the
 * scoping selector, the variable values, and the copied asset file names.
 */
export function generateCardCss({ profile, state, cssVariables, assetRefs, tiers }) {
  const id = profile.card.id;
  const lines = [];
  const header = [
    "/*",
    `  Compiled by ${GENERATOR_ID} — deterministic output, do not edit.`,
    `  Profile: ${id} (${profile.classification?.family ?? "unknown"})`,
    `  State: ${state.state}`
  ];
  if (state.notice) header.push(`  ${state.notice}`);
  if (state.state === "internal-reference-prototype") {
    header.splice(1, 0, `  ${INTERNAL_PROTOTYPE_BANNER}`);
  }
  header.push("*/");
  lines.push(header.join("\n"), "");

  const rootDeclarations = Object.entries(cssVariables).map(
    ([name, value]) => `  ${name}: ${value};`
  );
  for (const channel of DYNAMIC_CHANNELS) {
    const ref = assetRefs[channel];
    if (!ref) continue;
    const varName = {
      foilMask: "--foil-mask",
      metallicMask: "--metallic-mask",
      glossMask: "--gloss-mask",
      textureMask: "--texture-mask",
      suppressionMask: "--suppression-mask"
    }[channel];
    rootDeclarations.push(`  ${varName}: url("${ref.path}");`);
  }
  rootDeclarations.push(`  --max-tilt: ${formatNumber(tiers.detail.maxTiltDeg)}deg;`);
  lines.push(`${cssSelector(id)} {`, ...rootDeclarations, "}", "");

  const has = (channel) => Boolean(assetRefs[channel]);

  // Direct mask routing: url() consumed through a custom property resolves
  // against the document base in Chromium, so each layer also gets a direct
  // stylesheet-relative mask-image rule (these win on specificity).
  const maskTargets = [
    ["metallicMask", "foil-base"],
    ["foilMask", "shine"],
    ["textureMask", "etch"],
    ["suppressionMask", "suppression"],
    ["glossMask", "glare"]
  ];
  for (const [channel, layer] of maskTargets) {
    const ref = assetRefs[channel];
    if (!ref) continue;
    lines.push(
      `.card.masked[data-card-profile="${id}"] .card__${layer} {`,
      `  -webkit-mask-image: url("${ref.path}");`,
      `  mask-image: url("${ref.path}");`,
      "}",
      ""
    );
  }

  if (has("metallicMask")) {
    lines.push(
      `${cssSelector(id, " .card__foil-base")} {`,
      "  opacity: calc(var(--card-opacity) * var(--metallic-strength) * 0.62);",
      "  background-image:",
      "    radial-gradient(",
      "      farthest-corner circle at var(--pointer-x) var(--pointer-y),",
      "      hsla(0, 0%, 100%, 0.85) 0%,",
      "      hsla(48, 90%, 75%, 0.34) 16%,",
      "      hsla(210, 35%, 30%, 0.15) 43%,",
      "      hsla(0, 0%, 0%, 0.48) 100%",
      "    ),",
      "    linear-gradient(125deg, #161616 0%, #d6d2c7 22%, #353535 43%, #eee9da 64%, #171717 100%);",
      "  background-blend-mode: color-dodge, soft-light;",
      "  background-position: var(--background-x) var(--background-y), center;",
      "  background-size: 150% 150%, 220% 220%;",
      "  mix-blend-mode: color-dodge;",
      "  filter: contrast(1.12) saturate(0.72) brightness(0.92)",
      "    hue-rotate(calc((var(--metallic-warmth) - 0.5) * 60deg));",
      "}",
      ""
    );
  }

  if (has("foilMask")) {
    lines.push(
      `${cssSelector(id, " .card__shine")} {`,
      "  --band: calc(var(--foil-band-width) * var(--texture-scale));",
      "  opacity: calc(var(--card-opacity) * var(--foil-strength) * 0.78);",
      "  background-image:",
      "    repeating-linear-gradient(",
      "      var(--foil-band-angle),",
      "      hsla(43, 88%, 70%, 0.1) 0%,",
      "      hsla(188, 92%, 72%, 0.66) calc(var(--band) * 0.48),",
      "      hsla(262, 90%, 72%, 0.34) calc(var(--band) * 0.82),",
      "      hsla(313, 84%, 73%, 0.62) var(--band),",
      "      hsla(43, 88%, 70%, 0.08) calc(var(--band) * 1.44)",
      "    ),",
      "    radial-gradient(",
      "      farthest-corner circle at var(--pointer-x) var(--pointer-y),",
      "      hsla(0, 0%, 100%, 0.9) 0%,",
      "      hsla(198, 96%, 75%, 0.42) 18%,",
      "      hsla(290, 92%, 68%, 0.12) 39%,",
      "      transparent 72%",
      "    );",
      "  background-size: 240% 240%, 145% 145%;",
      "  background-position:",
      "    calc(var(--background-x) * 1.35) calc(var(--background-y) * 1.2),",
      "    var(--pointer-x) var(--pointer-y);",
      "  background-blend-mode: hard-light, screen;",
      "  mix-blend-mode: color-dodge;",
      "  filter: saturate(1.12) contrast(1.42) brightness(0.82)",
      "    hue-rotate(var(--foil-hue-offset));",
      "}",
      ""
    );
  }

  if (has("textureMask")) {
    lines.push(
      `${cssSelector(id, " .card__etch")} {`,
      "  opacity: calc(var(--card-opacity) * var(--texture-strength) * 0.9);",
      "  background-image:",
      "    repeating-linear-gradient(",
      "      var(--texture-direction),",
      "      rgba(255, 255, 255, 0.18) 0,",
      "      rgba(255, 255, 255, 0.18) 0.45px,",
      "      rgba(0, 0, 0, 0.09) 0.8px,",
      "      rgba(0, 0, 0, 0.09) 1.35px,",
      "      transparent 1.7px,",
      "      transparent 3.1px",
      "    );",
      "  background-size: calc(6px * var(--texture-scale)) calc(6px * var(--texture-scale));",
      "  background-position: calc(var(--background-x) * -0.18) calc(var(--background-y) * -0.18);",
      "  mix-blend-mode: overlay;",
      "  filter: contrast(1.8);",
      "}",
      ""
    );
  }

  if (has("suppressionMask")) {
    lines.push(
      `${cssSelector(id, " .card__suppression")} {`,
      "  display: block;",
      "  opacity: calc(var(--card-opacity) * var(--ink-suppression));",
      "  background: rgba(8, 8, 10, 0.92);",
      "  mix-blend-mode: multiply;",
      "}",
      ""
    );
  }

  if (has("glossMask")) {
    lines.push(
      `${cssSelector(id, " .card__glare")} {`,
      "  opacity: calc(var(--card-opacity) * var(--gloss-strength) * 0.72);",
      "  background-image:",
      "    radial-gradient(",
      "      farthest-corner circle at var(--pointer-x) var(--pointer-y),",
      "      rgba(255, 255, 255, 0.88) 0%,",
      "      rgba(255, 255, 255, 0.44) calc(var(--gloss-size) * 0.12),",
      "      rgba(220, 235, 255, 0.14) calc(var(--gloss-size) * 0.3),",
      "      rgba(0, 0, 0, 0.1) calc(var(--gloss-size) * 0.62),",
      "      rgba(0, 0, 0, 0.54) var(--gloss-size)",
      "    );",
      "  background-size: 145% 145%;",
      "  background-position: center;",
      "  mix-blend-mode: soft-light;",
      "  filter: brightness(calc(0.9 + var(--pointer-from-center) * 0.3)) contrast(1.08);",
      "}",
      ""
    );
  }

  // Grid tier: one simplified effective foil layer + glare, reduced tilt.
  const gridSelector = (suffix) => cssSelector(id, `[data-card-tier="grid"]${suffix}`);
  lines.push(
    `${gridSelector(" .card__foil-base")},`,
    `${gridSelector(" .card__etch")},`,
    `${gridSelector(" .card__suppression")} {`,
    "  display: none;",
    "}",
    ""
  );
  if (has("foilMask")) {
    lines.push(
      `${gridSelector(" .card__shine")} {`,
      `  opacity: calc(var(--card-opacity) * ${formatNumber(
        tiers.grid.effectiveFoilStrength
      )} * 0.78);`,
      "}",
      ""
    );
  }

  // Offscreen suspension (grid tier drives data-suspended via the component).
  lines.push(
    `${cssSelector(id, '[data-suspended="true"] .card__foil-base')},`,
    `${cssSelector(id, '[data-suspended="true"] .card__shine')},`,
    `${cssSelector(id, '[data-suspended="true"] .card__etch')},`,
    `${cssSelector(id, '[data-suspended="true"] .card__suppression')},`,
    `${cssSelector(id, '[data-suspended="true"] .card__glare')} {`,
    "  display: none;",
    "}",
    ""
  );

  // Reduced-motion / static fallback: albedo plus a faint static sheen.
  lines.push(
    "@media (prefers-reduced-motion: reduce) {",
    `  ${cssSelector(id, " .card__shine")},`,
    `  ${cssSelector(id, " .card__etch")},`,
    `  ${cssSelector(id, " .card__suppression")},`,
    `  ${cssSelector(id, " .card__glare")} {`,
    "    display: none;",
    "  }",
    `  ${cssSelector(id, " .card__foil-base")} {`,
    "    opacity: calc(var(--metallic-strength) * 0.18);",
    "    background-position: center, center;",
    "  }",
    "}",
    ""
  );

  return lines.join("\n");
}

async function readDeclaredAssets(profile, inputDir) {
  const declared = [];
  for (const channel of ALL_CHANNELS) {
    const asset = profile.assets?.[channel];
    if (!asset) continue;
    const uri = typeof asset === "string" ? asset : asset.uri;
    declared.push({ channel, uri, expectedSha256: asset.sha256 ?? null });
  }

  const resolved = [];
  for (const entry of declared) {
    const absolute = resolveAssetPath(entry.uri, inputDir);
    let bytes;
    try {
      bytes = await fs.readFile(absolute);
    } catch (error) {
      if (error?.code === "ENOENT" || error?.code === "EISDIR") {
        throw new CompileRefusal(
          `declared asset '${entry.channel}' is missing: ${entry.uri} ` +
            `(resolved ${absolute}). A declared asset that is absent is an error; ` +
            "omit the channel to degrade the output instead."
        );
      }
      throw error;
    }
    const digest = sha256Hex(bytes);
    if (entry.expectedSha256 && entry.expectedSha256.toLowerCase() !== digest) {
      throw new CompileRefusal(
        `declared asset '${entry.channel}' hash mismatch: profile declares ` +
          `${entry.expectedSha256}, file content is ${digest}`
      );
    }
    resolved.push({ ...entry, absolute, bytes, sha256: digest });
  }
  return resolved;
}

/**
 * Compile a profile into an output directory.
 *
 * options:
 *  - profilePath: path to the profile JSON (bytes are hashed as-is)
 *  - inputDir: root directory the profile's asset uris resolve inside
 *  - outDir: output directory (created; card.css/card-manifest.json/assets/)
 *  - publicationReportPath: attestation from `optcg-review check-publish`
 *  - generatedAt: optional fixed timestamp string recorded in the manifest
 */
export async function compileCardProfile(options) {
  const { profilePath, inputDir, outDir, publicationReportPath, generatedAt } = options;
  if (!profilePath || !inputDir || !outDir) {
    throw new CompileRefusal("profilePath, inputDir, and outDir are required");
  }

  const rawProfile = await fs.readFile(profilePath);
  const profileSha256 = sha256Hex(rawProfile);
  let profile;
  try {
    profile = JSON.parse(rawProfile.toString("utf8"));
  } catch (error) {
    throw new CompileRefusal(`profile is not valid JSON: ${error.message}`);
  }

  const validation = validateResearchProfile(profile);
  if (!validation.valid) {
    throw new CompileRefusal(`profile failed validation: ${validation.errors.join("; ")}`);
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/.test(profile.card.id)) {
    throw new CompileRefusal(`profile card.id is not a safe output identifier: ${profile.card.id}`);
  }

  const state = classifyProfileState(profile);

  let publication = null;
  if (state.requiresPublicationReport) {
    if (!publicationReportPath) {
      throw new CompileRefusal(
        "approved production profiles require --publication-report (the JSON " +
          "report emitted by `optcg-review check-publish`); the compiler does " +
          "not reimplement the publication gate and refuses without proof it passed"
      );
    }
    const rawReport = await fs.readFile(publicationReportPath);
    let report;
    try {
      report = JSON.parse(rawReport.toString("utf8"));
    } catch (error) {
      throw new CompileRefusal(`publication report is not valid JSON: ${error.message}`);
    }
    const result = validatePublicationReport(report, profileSha256);
    if (!result.ok) {
      throw new CompileRefusal(
        `publication-gate attestation rejected: ${result.errors.join("; ")}`
      );
    }
    publication = { reportSha256: sha256Hex(rawReport), passed: true };
  }

  const assets = await readDeclaredAssets(profile, inputDir);
  const declaredChannels = assets.map((asset) => asset.channel);
  const cssChannels = declaredChannels.filter((channel) => CSS_CHANNELS.includes(channel));

  const assetRefs = {};
  for (const asset of assets) {
    assetRefs[asset.channel] = {
      path: `assets/${assetOutputName(asset.channel, asset.sha256, asset.uri)}`,
      sha256: asset.sha256,
      sourceUri: asset.uri
    };
  }

  const cssVariables = cssVariablesFor(profile, cssChannels);
  const tiers = tierPlan(profile, cssChannels);
  const css = generateCardCss({ profile, state, cssVariables, assetRefs, tiers });
  const handoff = webglHandoffFor(profile, declaredChannels);

  const manifest = {
    schemaVersion: COMPILER_OUTPUT_SCHEMA_VERSION,
    generator: GENERATOR_ID,
    ...(generatedAt ? { generatedAt: String(generatedAt) } : {}),
    profile: {
      id: profile.card.id,
      name: profile.card.name ?? null,
      family: profile.classification?.family ?? "unknown",
      confidence: profile.classification?.confidence ?? null,
      lane: profile.lane ?? "physical"
    },
    profileSha256,
    state: state.state,
    visibility: state.visibility,
    ...(state.notice ? { notice: state.notice } : {}),
    publication,
    css: { path: "card.css", sha256: sha256Hex(css) },
    cssVariables,
    assets: assetRefs,
    tiers,
    webglHandoff: handoff ? { path: "webgl-handoff.json", reasons: handoff.reasons } : null
  };

  await fs.mkdir(path.join(outDir, "assets"), { recursive: true });
  for (const asset of assets) {
    await fs.writeFile(path.join(outDir, assetRefs[asset.channel].path), asset.bytes);
  }
  await fs.writeFile(path.join(outDir, "card.css"), css);
  await fs.writeFile(path.join(outDir, "card-manifest.json"), canonicalJson(manifest));
  if (handoff) {
    await fs.writeFile(path.join(outDir, "webgl-handoff.json"), canonicalJson(handoff));
  }

  return { outDir, state: state.state, visibility: state.visibility, manifest, css };
}
