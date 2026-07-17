import crypto from "node:crypto";

export const ALLOWED_PROFILE_PARAMETERS = Object.freeze({
  "renderer.foilStrength": { min: 0, max: 2, defaultStep: 0.18, minimumStep: 0.01 },
  "renderer.metallicStrength": { min: 0, max: 2, defaultStep: 0.18, minimumStep: 0.01 },
  "renderer.glossStrength": { min: 0, max: 2, defaultStep: 0.15, minimumStep: 0.01 },
  "renderer.textureStrength": { min: 0, max: 2, defaultStep: 0.12, minimumStep: 0.01 },
  "renderer.roughness": { min: 0, max: 1, defaultStep: 0.08, minimumStep: 0.005 },
  "renderer.clearcoat": { min: 0, max: 1, defaultStep: 0.08, minimumStep: 0.005 },
  "renderer.clearcoatRoughness": { min: 0, max: 1, defaultStep: 0.06, minimumStep: 0.005 },
  "renderer.iridescence": { min: 0, max: 1, defaultStep: 0.1, minimumStep: 0.005 },
  "renderer.iridescenceIor": { min: 1, max: 2.333, defaultStep: 0.08, minimumStep: 0.005 },
  "renderer.iridescenceThicknessMinNm": {
    min: 0,
    max: 2000,
    defaultStep: 40,
    minimumStep: 2
  },
  "renderer.iridescenceThicknessMaxNm": {
    min: 0,
    max: 2000,
    defaultStep: 55,
    minimumStep: 2
  },
  "renderer.anisotropy": { min: 0, max: 1, defaultStep: 0.1, minimumStep: 0.005 },
  "renderer.anisotropyRotationRad": {
    min: -Math.PI * 4,
    max: Math.PI * 4,
    defaultStep: Math.PI / 12,
    minimumStep: Math.PI / 720
  }
});

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function finite(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number)) throw new Error(`${label} must be finite`);
  return number;
}

export function getProfileParameter(profile, path) {
  return path.split(".").reduce((value, key) => value?.[key], profile);
}

export function setProfileParameter(profile, path, value) {
  const output = clone(profile);
  const keys = path.split(".");
  let target = output;
  for (const key of keys.slice(0, -1)) {
    if (!target[key] || typeof target[key] !== "object") target[key] = {};
    target = target[key];
  }
  target[keys.at(-1)] = value;
  return output;
}

export function validateParameterSpec(input) {
  if (!input || typeof input !== "object") throw new Error("parameter spec must be an object");
  const name = String(input.name ?? "");
  const safety = ALLOWED_PROFILE_PARAMETERS[name];
  if (!safety) throw new Error(`unsupported optimization parameter: ${name}`);

  const minimum = finite(input.min ?? safety.min, `${name}.min`);
  const maximum = finite(input.max ?? safety.max, `${name}.max`);
  if (minimum < safety.min || maximum > safety.max || maximum <= minimum) {
    throw new Error(
      `${name} bounds must remain within [${safety.min}, ${safety.max}] and min < max`
    );
  }

  const step = finite(input.step ?? safety.defaultStep, `${name}.step`);
  const minimumStep = finite(
    input.minimumStep ?? safety.minimumStep,
    `${name}.minimumStep`
  );
  if (step <= 0 || minimumStep <= 0 || minimumStep > step) {
    throw new Error(`${name} requires 0 < minimumStep <= step`);
  }

  return Object.freeze({
    name,
    min: minimum,
    max: maximum,
    step,
    minimumStep,
    locked: Boolean(input.locked)
  });
}

export function validateParameterSpecs(inputs) {
  if (!Array.isArray(inputs) || inputs.length === 0) {
    throw new Error("optimizer requires at least one parameter spec");
  }
  const specs = inputs.map(validateParameterSpec);
  const names = specs.map((spec) => spec.name);
  if (new Set(names).size !== names.length) throw new Error("parameter names must be unique");
  return specs;
}

export function clampParameter(value, spec) {
  return Math.min(Math.max(finite(value, spec.name), spec.min), spec.max);
}

export function coordinateCandidates(profile, spec, step = spec.step) {
  if (spec.locked) return [];
  const current = finite(getProfileParameter(profile, spec.name), spec.name);
  const candidates = [current - step, current + step]
    .map((value) => clampParameter(value, spec))
    .filter((value) => Math.abs(value - current) > 1e-12);
  return [...new Set(candidates)].map((value) => setProfileParameter(profile, spec.name, value));
}

export function profileParameterSnapshot(profile, specs) {
  return Object.fromEntries(
    specs.map((spec) => [spec.name, finite(getProfileParameter(profile, spec.name), spec.name)])
  );
}

export function profileCacheKey(profile, specs) {
  const snapshot = profileParameterSnapshot(profile, specs);
  const canonical = JSON.stringify(
    Object.fromEntries(Object.entries(snapshot).sort(([a], [b]) => a.localeCompare(b)))
  );
  return crypto.createHash("sha256").update(canonical).digest("hex");
}

export function createOptimizerState(profile, specs) {
  for (const spec of specs) {
    const value = finite(getProfileParameter(profile, spec.name), spec.name);
    if (value < spec.min || value > spec.max) {
      throw new Error(`${spec.name} initial value ${value} is outside requested bounds`);
    }
  }
  return {
    profile: clone(profile),
    steps: Object.fromEntries(specs.map((spec) => [spec.name, spec.step])),
    bestLoss: Number.POSITIVE_INFINITY,
    bestTrialId: null,
    trials: []
  };
}

export function nextStep(currentStep, spec) {
  const reduced = currentStep / 2;
  return reduced < spec.minimumStep ? 0 : reduced;
}
