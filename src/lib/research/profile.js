export const PROFILE_SCHEMA_VERSION = "1.0.0";

export const DEFAULT_RESEARCH_PROFILE = Object.freeze({
  schemaVersion: PROFILE_SCHEMA_VERSION,
  card: {
    id: "SYNTHETIC-001",
    name: "Synthetic Material Fixture",
    game: "one-piece-card-game",
    set: "LAB",
    rarity: "fixture",
    language: "EN",
    printVariant: "synthetic"
  },
  classification: {
    family: "sp-gold-ornamental",
    confidence: "hypothesis",
    evidence: ["Synthetic fixture only"]
  },
  assets: {
    albedo: { uri: "/img/demo/optcg-placeholder.svg", colorSpace: "srgb" },
    foilMask: { uri: "/img/masks/sp-generic-mask.svg", colorSpace: "linear" },
    metallicMask: { uri: "/img/masks/sp-generic-mask.svg", colorSpace: "linear" },
    glossMask: { uri: "/img/masks/sp-generic-mask.svg", colorSpace: "linear" },
    textureMask: { uri: "/img/masks/sp-generic-mask.svg", colorSpace: "linear" },
    normalMap: null,
    directionMap: null,
    suppressionMask: null,
    cardBack: { uri: "/img/demo/card-back.svg", colorSpace: "srgb" }
  },
  renderer: {
    cssPreset: "sp-etched",
    webglPreset: "physical-reference-v1",
    qualityTier: "research",
    foilStrength: 0.72,
    metallicStrength: 0.78,
    glossStrength: 0.88,
    textureStrength: 0.42,
    roughness: 0.48,
    clearcoat: 1,
    clearcoatRoughness: 0.14,
    iridescence: 0.82,
    iridescenceIor: 1.32,
    iridescenceThicknessMinNm: 120,
    iridescenceThicknessMaxNm: 470,
    anisotropy: 0.52,
    anisotropyRotationRad: 0,
    maxTiltDeg: 18
  },
  provenance: {
    sourceType: "synthetic",
    rights: "Synthetic fixture created for the public test bench.",
    reviewStatus: "unreviewed"
  }
});

const REQUIRED_FAMILIES = new Set([
  "rare-holo-standard",
  "sr-foil-basic",
  "sr-textured",
  "alt-art-coated",
  "alt-art-textured",
  "manga-prismatic-panel",
  "manga-gold-metallic",
  "sp-gold-ornamental",
  "sp-manga-scene",
  "sp-color-field",
  "leader-parallel-textured",
  "treasure-rare",
  "unknown"
]);

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function finite(value, fallback, minimum, maximum) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(Math.max(number, minimum), maximum);
}

function normalizeAsset(asset, fallback = null) {
  if (!asset) return fallback;
  if (typeof asset === "string") return { uri: asset };
  if (typeof asset.uri !== "string" || asset.uri.length === 0) return fallback;
  return { ...asset, uri: asset.uri };
}

export function assetUri(asset, fallback = null) {
  return normalizeAsset(asset, fallback ? { uri: fallback } : null)?.uri ?? fallback;
}

export function normalizeResearchProfile(input = {}) {
  const fallback = clone(DEFAULT_RESEARCH_PROFILE);
  const profile = input && typeof input === "object" ? input : {};
  const classification = profile.classification ?? {};
  const renderer = profile.renderer ?? {};
  const assets = profile.assets ?? {};
  const family = REQUIRED_FAMILIES.has(classification.family)
    ? classification.family
    : fallback.classification.family;

  return {
    schemaVersion: profile.schemaVersion ?? PROFILE_SCHEMA_VERSION,
    card: { ...fallback.card, ...(profile.card ?? {}) },
    classification: {
      ...fallback.classification,
      ...classification,
      family
    },
    assets: {
      albedo: normalizeAsset(assets.albedo, fallback.assets.albedo),
      foilMask: normalizeAsset(assets.foilMask, fallback.assets.foilMask),
      metallicMask: normalizeAsset(assets.metallicMask, fallback.assets.metallicMask),
      glossMask: normalizeAsset(assets.glossMask, fallback.assets.glossMask),
      textureMask: normalizeAsset(assets.textureMask, fallback.assets.textureMask),
      suppressionMask: normalizeAsset(assets.suppressionMask),
      normalMap: normalizeAsset(assets.normalMap),
      directionMap: normalizeAsset(assets.directionMap),
      regionMask: normalizeAsset(assets.regionMask),
      cardBack: normalizeAsset(assets.cardBack, fallback.assets.cardBack),
      gltf: normalizeAsset(assets.gltf)
    },
    renderer: {
      ...fallback.renderer,
      ...renderer,
      foilStrength: finite(renderer.foilStrength, fallback.renderer.foilStrength, 0, 2),
      metallicStrength: finite(renderer.metallicStrength, fallback.renderer.metallicStrength, 0, 2),
      glossStrength: finite(renderer.glossStrength, fallback.renderer.glossStrength, 0, 2),
      textureStrength: finite(renderer.textureStrength, fallback.renderer.textureStrength, 0, 2),
      roughness: finite(renderer.roughness, fallback.renderer.roughness, 0, 1),
      clearcoat: finite(renderer.clearcoat, fallback.renderer.clearcoat, 0, 1),
      clearcoatRoughness: finite(
        renderer.clearcoatRoughness,
        fallback.renderer.clearcoatRoughness,
        0,
        1
      ),
      iridescence: finite(renderer.iridescence, fallback.renderer.iridescence, 0, 1),
      iridescenceIor: finite(renderer.iridescenceIor, fallback.renderer.iridescenceIor, 1, 2.333),
      iridescenceThicknessMinNm: finite(
        renderer.iridescenceThicknessMinNm,
        fallback.renderer.iridescenceThicknessMinNm,
        0,
        2000
      ),
      iridescenceThicknessMaxNm: finite(
        renderer.iridescenceThicknessMaxNm,
        fallback.renderer.iridescenceThicknessMaxNm,
        0,
        2000
      ),
      anisotropy: finite(renderer.anisotropy, fallback.renderer.anisotropy, 0, 1),
      anisotropyRotationRad: finite(
        renderer.anisotropyRotationRad,
        fallback.renderer.anisotropyRotationRad,
        -Math.PI * 4,
        Math.PI * 4
      ),
      maxTiltDeg: finite(renderer.maxTiltDeg, fallback.renderer.maxTiltDeg, 0, 30)
    },
    provenance: { ...fallback.provenance, ...(profile.provenance ?? {}) },
    metrics: profile.metrics ? { ...profile.metrics } : undefined
  };
}

export function validateResearchProfile(input) {
  const errors = [];
  if (!input || typeof input !== "object") errors.push("profile must be an object");
  if (input?.schemaVersion !== PROFILE_SCHEMA_VERSION) {
    errors.push(`schemaVersion must equal ${PROFILE_SCHEMA_VERSION}`);
  }
  if (!input?.card?.id) errors.push("card.id is required");
  if (input?.card?.game !== "one-piece-card-game") {
    errors.push("card.game must equal one-piece-card-game");
  }
  if (!input?.assets?.albedo?.uri && typeof input?.assets?.albedo !== "string") {
    errors.push("assets.albedo.uri is required");
  }
  if (!REQUIRED_FAMILIES.has(input?.classification?.family)) {
    errors.push("classification.family is unknown");
  }
  return { valid: errors.length === 0, errors };
}
