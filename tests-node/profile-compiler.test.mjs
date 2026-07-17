import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  CompileRefusal,
  FORBIDDEN_ASSET_PATH_SEGMENTS,
  INTERNAL_PROTOTYPE_BANNER,
  SYNTHETIC_NOTICE,
  canonicalJson,
  classifyProfileState,
  compileCardProfile,
  cssVariablesFor,
  resolveAssetPath,
  sha256Hex,
  tierPlan,
  validateAssetUri,
  validatePublicationReport,
  webglHandoffFor
} from "../scripts/lib/profile-compiler.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..");
const FIXTURE_PROFILE = path.join(
  REPO_ROOT,
  "examples/profiles/OP01-120.synthetic.example.json"
);
const PUBLIC_DIR = path.join(REPO_ROOT, "public");

async function makeWorkspace() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "profile-compiler-"));
  test.after?.(() => {});
  return root;
}

async function writeFixtureAssets(inputDir) {
  await fs.mkdir(path.join(inputDir, "img"), { recursive: true });
  const files = {
    "img/albedo.svg": "<svg xmlns='http://www.w3.org/2000/svg'><rect fill='#345'/></svg>",
    "img/foil.svg": "<svg xmlns='http://www.w3.org/2000/svg'><rect fill='#fff'/></svg>",
    "img/metal.svg": "<svg xmlns='http://www.w3.org/2000/svg'><circle fill='#ccc'/></svg>",
    "img/gloss.svg": "<svg xmlns='http://www.w3.org/2000/svg'><circle fill='#eee'/></svg>",
    "img/texture.svg": "<svg xmlns='http://www.w3.org/2000/svg'><path d='M0 0h4'/></svg>",
    "img/suppress.svg": "<svg xmlns='http://www.w3.org/2000/svg'><rect fill='#000'/></svg>",
    "img/normal.png": "not-really-a-png-but-content-hashable"
  };
  for (const [name, content] of Object.entries(files)) {
    await fs.writeFile(path.join(inputDir, name), content);
  }
}

function syntheticProfile(overrides = {}) {
  return {
    schemaVersion: "1.0.0",
    card: {
      id: "TEST-001",
      name: "Compiler fixture",
      game: "one-piece-card-game",
      language: "EN",
      printVariant: "synthetic-test-only",
      ...(overrides.card ?? {})
    },
    classification: {
      family: "sp-gold-ornamental",
      confidence: "hypothesis",
      ...(overrides.classification ?? {})
    },
    assets: overrides.assets ?? {
      albedo: { uri: "/img/albedo.svg", colorSpace: "srgb" },
      foilMask: { uri: "/img/foil.svg", colorSpace: "linear" },
      metallicMask: { uri: "/img/metal.svg", colorSpace: "linear" },
      glossMask: { uri: "/img/gloss.svg", colorSpace: "linear" },
      textureMask: { uri: "/img/texture.svg", colorSpace: "linear" },
      suppressionMask: { uri: "/img/suppress.svg", colorSpace: "linear" }
    },
    renderer: {
      cssPreset: "sp-etched",
      qualityTier: "grid",
      foilStrength: 0.7,
      metallicStrength: 0.5,
      glossStrength: 0.8,
      textureStrength: 0.3,
      clearcoat: 0.9,
      clearcoatRoughness: 0.2,
      iridescence: 0.8,
      iridescenceThicknessMinNm: 120,
      iridescenceThicknessMaxNm: 470,
      anisotropyRotationRad: 0,
      maxTiltDeg: 12,
      ...(overrides.renderer ?? {})
    },
    provenance: {
      sourceType: "synthetic",
      rights: "Repository-authored synthetic test fixture.",
      reviewStatus: "unreviewed",
      ...(overrides.provenance ?? {})
    },
    ...(overrides.lane ? { lane: overrides.lane } : {})
  };
}

async function compileFromObject(profile, extra = {}) {
  const root = await makeWorkspace();
  const inputDir = path.join(root, "input");
  await writeFixtureAssets(inputDir);
  const profilePath = path.join(root, "profile.json");
  await fs.writeFile(profilePath, `${JSON.stringify(profile, null, 2)}\n`);
  const outDir = path.join(root, "out");
  const result = await compileCardProfile({ profilePath, inputDir, outDir, ...extra });
  return { root, inputDir, profilePath, outDir, result };
}

test("deterministic: compiling twice yields byte-identical output", async () => {
  const root = await makeWorkspace();
  const outA = path.join(root, "a");
  const outB = path.join(root, "b");
  for (const outDir of [outA, outB]) {
    await compileCardProfile({
      profilePath: FIXTURE_PROFILE,
      inputDir: PUBLIC_DIR,
      outDir
    });
  }
  const walk = async (dir) => {
    const names = (await fs.readdir(dir, { recursive: true })).sort();
    const entries = [];
    for (const name of names) {
      const file = path.join(dir, name);
      if ((await fs.stat(file)).isFile()) entries.push([name, await fs.readFile(file)]);
    }
    return entries;
  };
  const [a, b] = [await walk(outA), await walk(outB)];
  assert.equal(a.length, b.length);
  for (let index = 0; index < a.length; index += 1) {
    assert.equal(a[index][0], b[index][0]);
    assert.ok(a[index][1].equals(b[index][1]), `byte mismatch in ${a[index][0]}`);
  }
});

test("manifest binds profile hash, css hash, and per-asset hashes", async () => {
  const { result, outDir, profilePath } = await compileFromObject(syntheticProfile());
  const rawProfile = await fs.readFile(profilePath);
  assert.equal(result.manifest.profileSha256, sha256Hex(rawProfile));
  const css = await fs.readFile(path.join(outDir, "card.css"), "utf8");
  assert.equal(result.manifest.css.sha256, sha256Hex(css));
  for (const [channel, ref] of Object.entries(result.manifest.assets)) {
    const copied = await fs.readFile(path.join(outDir, ref.path));
    assert.equal(sha256Hex(copied), ref.sha256, `asset hash mismatch for ${channel}`);
  }
  // Manifest serialization is canonical (sorted keys).
  const manifestRaw = await fs.readFile(path.join(outDir, "card-manifest.json"), "utf8");
  assert.equal(manifestRaw, canonicalJson(result.manifest));
});

test("declared asset sha256 mismatch is refused", async () => {
  const profile = syntheticProfile();
  profile.assets.foilMask.sha256 = "0".repeat(64);
  await assert.rejects(() => compileFromObject(profile), /hash mismatch/);
});

test("missing optional channels degrade to static output", async () => {
  const profile = syntheticProfile({
    assets: { albedo: { uri: "/img/albedo.svg", colorSpace: "srgb" } }
  });
  const { result } = await compileFromObject(profile);
  assert.equal(result.manifest.tiers.static.staticOnly, true);
  assert.deepEqual(result.manifest.tiers.detail.layers, []);
  assert.equal(result.manifest.tiers.detail.maxTiltDeg, 0);
  assert.ok(!result.css.includes("--foil-mask"), "static output must not route a foil layer");
  assert.ok(!result.css.includes("--gloss-mask"), "static output must not route a glare layer");
});

test("a DECLARED asset that is absent is an error, not a degradation", async () => {
  const profile = syntheticProfile();
  profile.assets.textureMask = { uri: "/img/does-not-exist.svg" };
  await assert.rejects(() => compileFromObject(profile), /declared asset 'textureMask' is missing/);
});

test("independent mask routing: each channel references its own copied asset", async () => {
  const { result } = await compileFromObject(syntheticProfile());
  const refs = result.manifest.assets;
  const channelVars = {
    foilMask: "--foil-mask",
    metallicMask: "--metallic-mask",
    glossMask: "--gloss-mask",
    textureMask: "--texture-mask",
    suppressionMask: "--suppression-mask"
  };
  const paths = new Set();
  for (const [channel, varName] of Object.entries(channelVars)) {
    assert.ok(refs[channel], `manifest missing ${channel}`);
    assert.ok(
      result.css.includes(`${varName}: url("${refs[channel].path}")`),
      `card.css does not route ${channel} through ${varName}`
    );
    paths.add(refs[channel].path);
  }
  assert.equal(paths.size, 5, "channels must not collapse into one generic overlay");
  assert.deepEqual(result.manifest.tiers.detail.layers, [
    "metallic",
    "foil",
    "texture",
    "suppression",
    "glare"
  ]);
});

test("synthetic fixture output is marked not-an-accurate-card", async () => {
  const { result } = await compileFromObject(syntheticProfile());
  assert.equal(result.state, "synthetic");
  assert.equal(result.manifest.visibility, "synthetic-fixture");
  assert.equal(result.manifest.notice, SYNTHETIC_NOTICE);
  assert.ok(result.css.includes(SYNTHETIC_NOTICE));
});

test("internal reference prototype output is private and non-publishable", async () => {
  const profile = syntheticProfile({
    lane: "reference",
    classification: {
      family: "sp-gold-ornamental",
      confidence: "reference-derived"
    },
    provenance: {
      sourceType: "public-reference-synthesis",
      rights: "Derived from public references; internal preview only.",
      reviewStatus: "unreviewed",
      referenceBundleId: "bundle-test-1"
    }
  });
  const { result } = await compileFromObject(profile);
  assert.equal(result.state, "internal-reference-prototype");
  assert.equal(result.manifest.visibility, "private-nonpublishable");
  assert.ok(result.css.includes(INTERNAL_PROTOTYPE_BANNER));
});

function productionProfile() {
  return syntheticProfile({
    classification: { family: "sp-gold-ornamental", confidence: "production-validated" },
    provenance: {
      sourceType: "controlled-capture",
      rights: "Owned physical card, controlled capture.",
      reviewStatus: "approved",
      reviewer: "Eric Yun"
    }
  });
}

/** A structurally complete check-publish report (review.py PublicationReport). */
function publicationReport(profileDigest, overrides = {}) {
  return {
    passed: true,
    state: "production-approved",
    errors: [],
    warnings: [],
    profile_digest: profileDigest,
    ledger_head_digest: "b".repeat(64),
    checked_assets: { albedo: "c".repeat(64) },
    ...overrides
  };
}

test("approved production profile refuses without a publication-gate attestation", async () => {
  await assert.rejects(() => compileFromObject(productionProfile()), /publication-report/);
});

test("production compiles only with a passing, strictly-shaped, hash-bound attestation", async () => {
  const root = await makeWorkspace();
  const inputDir = path.join(root, "input");
  await writeFixtureAssets(inputDir);
  const profilePath = path.join(root, "profile.json");
  const rawProfile = `${JSON.stringify(productionProfile(), null, 2)}\n`;
  await fs.writeFile(profilePath, rawProfile);
  const digest = sha256Hex(rawProfile);

  const compileWith = async (name, report) => {
    const reportPath = path.join(root, `${name}.json`);
    await fs.writeFile(reportPath, JSON.stringify(report));
    return compileCardProfile({
      profilePath,
      inputDir,
      outDir: path.join(root, `out-${name}`),
      publicationReportPath: reportPath
    });
  };

  await assert.rejects(
    () =>
      compileWith(
        "failing",
        publicationReport(digest, { passed: false, errors: ["review state is 'unreviewed'"] })
      ),
    /did not pass/
  );
  await assert.rejects(
    () => compileWith("wrong-digest", publicationReport("a".repeat(64))),
    /bound to a different profile/
  );
  // Forged minimal attestation: passed + matching digest alone is not proof.
  await assert.rejects(
    () => compileWith("forged-minimal", { passed: true, profile_digest: digest }),
    /errors must be an array/
  );
  // Non-array errors field (e.g. errors: "gate failed") must be rejected.
  await assert.rejects(
    () => compileWith("errors-string", publicationReport(digest, { errors: "gate failed" })),
    /errors must be an array/
  );
  await assert.rejects(
    () => compileWith("no-ledger", publicationReport(digest, { ledger_head_digest: undefined })),
    /ledger_head_digest/
  );
  await assert.rejects(
    () => compileWith("bad-state", publicationReport(digest, { state: "rights-approved" })),
    /state must be 'production-approved'/
  );
  await assert.rejects(
    () => compileWith("no-assets", publicationReport(digest, { checked_assets: {} })),
    /checked_assets is empty/
  );
  await assert.rejects(
    () => compileWith("bad-warnings", publicationReport(digest, { warnings: "looks fine" })),
    /warnings must be an array/
  );

  const passingRaw = JSON.stringify(publicationReport(digest));
  const passingPath = path.join(root, "passing.json");
  await fs.writeFile(passingPath, passingRaw);
  const result = await compileCardProfile({
    profilePath,
    inputDir,
    outDir: path.join(root, "out-ok"),
    publicationReportPath: passingPath
  });
  assert.equal(result.state, "production");
  assert.equal(result.manifest.visibility, "public");
  assert.deepEqual(result.manifest.publication, {
    reportSha256: sha256Hex(passingRaw),
    passed: true
  });
});

test("approved profile below publishable confidence is refused", async () => {
  const profile = productionProfile();
  profile.classification.confidence = "photo-validated";
  await assert.rejects(() => compileFromObject(profile), /not compilable/);
});

test("lane omission cannot launder reference synthesis into production", async () => {
  const profile = productionProfile();
  profile.provenance.sourceType = "public-reference-synthesis";
  // No lane declared: must refuse, never classify as production/public.
  await assert.rejects(() => compileFromObject(profile), /must declare lane: 'reference'/);
  assert.throws(() => classifyProfileState(profile), /must declare lane: 'reference'/);
});

test("reference lane requires reference labels, synthesis provenance, and bundle id", async () => {
  const base = () =>
    syntheticProfile({
      lane: "reference",
      classification: { family: "sp-gold-ornamental", confidence: "reference-derived" },
      provenance: {
        sourceType: "public-reference-synthesis",
        rights: "Derived from public references; internal preview only.",
        reviewStatus: "unreviewed",
        referenceBundleId: "bundle-test-1"
      }
    });

  const badConfidence = base();
  badConfidence.classification.confidence = "not-a-state";
  await assert.rejects(() => compileFromObject(badConfidence), /not a reference-lane label/);

  const badSource = base();
  badSource.provenance.sourceType = "controlled-capture";
  await assert.rejects(
    () => compileFromObject(badSource),
    /sourceType must be 'public-reference-synthesis'/
  );

  const noBundle = base();
  delete noBundle.provenance.referenceBundleId;
  await assert.rejects(() => compileFromObject(noBundle), /referenceBundleId is required/);

  const physicalConfidence = base();
  physicalConfidence.classification.confidence = "capture-validated";
  await assert.rejects(
    () => compileFromObject(physicalConfidence),
    /not a reference-lane label/
  );
});

test("any other review state refuses with a clear error", async () => {
  const profile = syntheticProfile({
    provenance: {
      sourceType: "controlled-capture",
      rights: "Owned card, not yet reviewed.",
      reviewStatus: "unreviewed"
    }
  });
  await assert.rejects(() => compileFromObject(profile), CompileRefusal);
  assert.throws(() => classifyProfileState(profile), /not compilable/);
});

test("reduced-motion static fallback is part of every compiled stylesheet", async () => {
  const { result } = await compileFromObject(syntheticProfile());
  assert.ok(result.css.includes("@media (prefers-reduced-motion: reduce)"));
  assert.ok(result.css.includes('[data-suspended="true"]'));
  assert.ok(result.css.includes('[data-card-tier="grid"]'));
});

test("private and invalid asset URIs are refused", async () => {
  for (const segment of FORBIDDEN_ASSET_PATH_SEGMENTS) {
    assert.equal(validateAssetUri(`${segment}/frame.png`).ok, false, segment);
    assert.equal(validateAssetUri(`nested/${segment}/frame.png`).ok, false, segment);
  }
  assert.equal(validateAssetUri("https://cdn.example.com/mask.png").ok, false);
  assert.equal(validateAssetUri("//cdn.example.com/mask.png").ok, false);
  // Any URI scheme is refused, with or without slashes.
  assert.equal(validateAssetUri("data:image/svg+xml;base64,AAAA").ok, false);
  assert.equal(validateAssetUri("mailto:someone@example.com").ok, false);
  assert.equal(validateAssetUri("http:evil.png").ok, false);
  assert.equal(validateAssetUri("file:local.png").ok, false);
  assert.equal(validateAssetUri("../outside.png").ok, false);
  assert.equal(validateAssetUri("img/../../outside.png").ok, false);
  assert.equal(validateAssetUri("~/masks/a.png").ok, false);
  assert.equal(validateAssetUri("img\\masks\\a.png").ok, false);
  assert.equal(validateAssetUri("/img/masks/a.png").ok, true);

  // Absolute web-root URIs resolve inside the input directory, never outside.
  const root = await makeWorkspace();
  const inputDir = path.join(root, "input");
  await fs.mkdir(inputDir, { recursive: true });
  assert.throws(() => resolveAssetPath("private-media/x.png", inputDir), CompileRefusal);
  const resolved = resolveAssetPath("/img/mask.png", inputDir);
  assert.ok(resolved.startsWith(path.resolve(inputDir) + path.sep));

  const profile = syntheticProfile();
  profile.assets.foilMask = { uri: "raw-captures/session/frame-000.png" };
  await assert.rejects(() => compileFromObject(profile), /private source area/);
});

test("webgl handoff stub is emitted only for channels CSS cannot reproduce", async () => {
  const plain = syntheticProfile();
  assert.equal(webglHandoffFor(plain, Object.keys(plain.assets)), null);

  const profile = syntheticProfile();
  profile.assets.normalMap = { uri: "/img/normal.png", colorSpace: "normal" };
  const { result, outDir } = await compileFromObject(profile);
  assert.deepEqual(result.manifest.webglHandoff.reasons, [
    "asset channel 'normalMap' has no CSS equivalent"
  ]);
  const handoff = JSON.parse(
    await fs.readFile(path.join(outDir, "webgl-handoff.json"), "utf8")
  );
  assert.equal(handoff.kind, "webgl-handoff-stub");
  assert.deepEqual(handoff.channels, ["normalMap"]);

  const { result: plainResult } = await compileFromObject(plain);
  assert.equal(plainResult.manifest.webglHandoff, null);
});

test("css variables stay bounded and interpretable", () => {
  const channels = ["foilMask", "metallicMask", "glossMask", "textureMask", "suppressionMask"];
  const vars = cssVariablesFor(syntheticProfile(), channels);
  const expectedNames = [
    "--foil-strength",
    "--foil-band-angle",
    "--foil-band-width",
    "--foil-hue-offset",
    "--metallic-strength",
    "--metallic-warmth",
    "--gloss-strength",
    "--gloss-size",
    "--texture-strength",
    "--texture-scale",
    "--texture-direction",
    "--ink-suppression"
  ];
  assert.deepEqual(Object.keys(vars).sort(), [...expectedNames].sort());

  const extreme = cssVariablesFor(
    syntheticProfile({
      renderer: { foilStrength: 99, iridescenceThicknessMaxNm: 99999 }
    }),
    channels
  );
  assert.ok(Number(extreme["--foil-strength"]) <= 2);
  assert.ok(parseFloat(extreme["--foil-band-width"]) <= 16);

  const noSuppression = cssVariablesFor(syntheticProfile(), ["foilMask"]);
  assert.equal(noSuppression["--ink-suppression"], "0");
});

test("tier plan reduces grid tilt and folds foil+metallic into one layer", () => {
  const channels = ["foilMask", "metallicMask", "glossMask", "textureMask", "suppressionMask"];
  const tiers = tierPlan(syntheticProfile({ renderer: { maxTiltDeg: 24 } }), channels);
  assert.equal(tiers.detail.maxTiltDeg, 16);
  assert.equal(tiers.grid.maxTiltDeg, 8);
  assert.deepEqual(tiers.grid.layers, ["foil", "glare"]);
  assert.equal(tiers.grid.suspendOffscreen, true);
  assert.ok(tiers.grid.effectiveFoilStrength > 0);
});

test("no card-specific constants in any compiler source", async () => {
  // Enumerate ALL compiler sources: the CLI, the library entry, and every
  // file under scripts/lib/profile-compiler/ if that directory exists. The
  // test fails if an enumerated file cannot be read.
  const required = [
    path.join(REPO_ROOT, "scripts/compile-card-profile.mjs"),
    path.join(REPO_ROOT, "scripts/lib/profile-compiler.mjs")
  ];
  const sources = [...required];
  const libDir = path.join(REPO_ROOT, "scripts/lib/profile-compiler");
  try {
    const entries = await fs.readdir(libDir, { recursive: true });
    for (const entry of entries.sort()) {
      const file = path.join(libDir, entry);
      if ((await fs.stat(file)).isFile()) sources.push(file);
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error; // unreadable directory = failure
  }

  const cardIdPattern = /\b(?:OP|ST|EB|PRB|P)-?\d{2}-\d{3}\b/i;
  const cardNamePattern = /\b(?:perona|luffy|zoro|shanks|buggy|nami|sanji|hancock|yamato)\b/i;
  // Lookup tables keyed by card-id-shaped strings, e.g. { "XX01-001": ... }.
  const cardIdKeyPattern = /["'][A-Za-z]{1,4}-?\d{2}-\d{3}["']\s*:/;

  assert.ok(sources.length >= required.length, "compiler source enumeration failed");
  for (const source of sources) {
    // A file that cannot be read is a hard failure, not a skipped scan.
    const text = await fs.readFile(source, "utf8");
    const label = path.relative(REPO_ROOT, source);
    assert.ok(!cardIdPattern.test(text), `${label} contains a card-id constant`);
    assert.ok(!cardNamePattern.test(text), `${label} contains a card/character name`);
    assert.ok(
      !cardIdKeyPattern.test(text),
      `${label} contains a lookup table keyed by a card-id-shaped string`
    );
  }
});

test("publication report with unknown extra fields is refused", () => {
  const profileBytes = Buffer.from(JSON.stringify({ any: "profile" }));
  const digest = createHash("sha256").update(profileBytes).digest("hex");
  const report = {
    passed: true,
    errors: [],
    warnings: [],
    state: "production-approved",
    ledger_head_digest: "a".repeat(64),
    checked_assets: { albedo: "b".repeat(64) },
    profile_digest: digest,
    extra: "forged",
  };
  const result = validatePublicationReport(report, digest);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.includes("unknown field 'extra'")));
});
