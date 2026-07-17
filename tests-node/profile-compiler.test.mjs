import assert from "node:assert/strict";
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

test("approved production profile refuses without a publication-gate attestation", async () => {
  const profile = syntheticProfile({
    classification: { family: "sp-gold-ornamental", confidence: "production-validated" },
    provenance: {
      sourceType: "controlled-capture",
      rights: "Owned physical card, controlled capture.",
      reviewStatus: "approved",
      reviewer: "Eric Yun"
    }
  });
  await assert.rejects(() => compileFromObject(profile), /publication-report/);
});

test("production compiles only with a passing, hash-bound attestation", async () => {
  const profile = syntheticProfile({
    classification: { family: "sp-gold-ornamental", confidence: "production-validated" },
    provenance: {
      sourceType: "controlled-capture",
      rights: "Owned physical card, controlled capture.",
      reviewStatus: "approved",
      reviewer: "Eric Yun"
    }
  });
  const root = await makeWorkspace();
  const inputDir = path.join(root, "input");
  await writeFixtureAssets(inputDir);
  const profilePath = path.join(root, "profile.json");
  const rawProfile = `${JSON.stringify(profile, null, 2)}\n`;
  await fs.writeFile(profilePath, rawProfile);
  const digest = sha256Hex(rawProfile);

  const failing = path.join(root, "failing-report.json");
  await fs.writeFile(
    failing,
    JSON.stringify({ passed: false, errors: ["review state is 'unreviewed'"], profile_digest: digest })
  );
  await assert.rejects(
    () =>
      compileCardProfile({
        profilePath,
        inputDir,
        outDir: path.join(root, "out-fail"),
        publicationReportPath: failing
      }),
    /did not pass/
  );

  const wrongDigest = path.join(root, "wrong-digest-report.json");
  await fs.writeFile(
    wrongDigest,
    JSON.stringify({ passed: true, errors: [], profile_digest: "a".repeat(64) })
  );
  await assert.rejects(
    () =>
      compileCardProfile({
        profilePath,
        inputDir,
        outDir: path.join(root, "out-wrong"),
        publicationReportPath: wrongDigest
      }),
    /bound to a different profile/
  );

  const passing = path.join(root, "passing-report.json");
  const passingRaw = JSON.stringify({ passed: true, errors: [], profile_digest: digest });
  await fs.writeFile(passing, passingRaw);
  const result = await compileCardProfile({
    profilePath,
    inputDir,
    outDir: path.join(root, "out-ok"),
    publicationReportPath: passing
  });
  assert.equal(result.state, "production");
  assert.equal(result.manifest.visibility, "public");
  assert.deepEqual(result.manifest.publication, {
    reportSha256: sha256Hex(passingRaw),
    passed: true
  });
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

test("no card-specific constants in compiler sources", async () => {
  const sources = [
    path.join(REPO_ROOT, "scripts/lib/profile-compiler.mjs"),
    path.join(REPO_ROOT, "scripts/compile-card-profile.mjs")
  ];
  const cardIdPatterns = [/OP\d{2}-\d{3}/, /ST\d{2}-\d{3}/, /EB\d{2}-\d{3}/, /PRB\d{2}-\d{3}/];
  for (const source of sources) {
    const text = await fs.readFile(source, "utf8");
    for (const pattern of cardIdPatterns) {
      assert.ok(
        !pattern.test(text),
        `${path.basename(source)} contains a card-specific constant matching ${pattern}`
      );
    }
  }
});
