import assert from "node:assert/strict";
import test from "node:test";

import {
  coordinateCandidates,
  createOptimizerState,
  getProfileParameter,
  nextStep,
  profileCacheKey,
  setProfileParameter,
  validateParameterSpec,
  validateParameterSpecs
} from "../scripts/lib/profile-optimizer.mjs";

const PROFILE = Object.freeze({
  renderer: {
    foilStrength: 0.7,
    roughness: 0.45,
    iridescenceThicknessMinNm: 120,
    iridescenceThicknessMaxNm: 470
  }
});

test("unsupported and unsafe parameters fail closed", () => {
  assert.throws(
    () => validateParameterSpec({ name: "assets.albedo", min: 0, max: 1 }),
    /unsupported/
  );
  assert.throws(
    () => validateParameterSpec({ name: "renderer.roughness", min: -1, max: 1 }),
    /bounds/
  );
  assert.throws(
    () => validateParameterSpecs([
      { name: "renderer.roughness" },
      { name: "renderer.roughness" }
    ]),
    /unique/
  );
});

test("setProfileParameter is immutable", () => {
  const changed = setProfileParameter(PROFILE, "renderer.roughness", 0.6);
  assert.equal(getProfileParameter(PROFILE, "renderer.roughness"), 0.45);
  assert.equal(getProfileParameter(changed, "renderer.roughness"), 0.6);
});

test("coordinate candidates remain inside physical bounds", () => {
  const spec = validateParameterSpec({
    name: "renderer.foilStrength",
    min: 0.65,
    max: 0.75,
    step: 0.1,
    minimumStep: 0.01
  });
  const candidates = coordinateCandidates(PROFILE, spec);
  assert.deepEqual(
    candidates.map((profile) => profile.renderer.foilStrength),
    [0.65, 0.75]
  );
});

test("locked parameters produce no candidates", () => {
  const spec = validateParameterSpec({
    name: "renderer.roughness",
    locked: true
  });
  assert.deepEqual(coordinateCandidates(PROFILE, spec), []);
});

test("cache keys depend only on selected parameter values", () => {
  const specs = validateParameterSpecs([
    { name: "renderer.foilStrength" },
    { name: "renderer.roughness" }
  ]);
  const a = profileCacheKey(PROFILE, specs);
  const equivalent = {
    metadata: { ignored: true },
    renderer: {
      roughness: 0.45,
      foilStrength: 0.7,
      iridescenceThicknessMinNm: 999
    }
  };
  assert.equal(a, profileCacheKey(equivalent, specs));
  assert.notEqual(
    a,
    profileCacheKey(setProfileParameter(PROFILE, "renderer.roughness", 0.5), specs)
  );
});

test("optimizer state validates initial values and halves steps", () => {
  const specs = validateParameterSpecs([
    {
      name: "renderer.roughness",
      min: 0.2,
      max: 0.8,
      step: 0.1,
      minimumStep: 0.025
    }
  ]);
  const state = createOptimizerState(PROFILE, specs);
  assert.equal(state.steps["renderer.roughness"], 0.1);
  assert.equal(nextStep(0.1, specs[0]), 0.05);
  assert.equal(nextStep(0.05, specs[0]), 0.025);
  assert.equal(nextStep(0.025, specs[0]), 0);
});
