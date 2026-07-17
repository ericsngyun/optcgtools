import { expect, test } from "@playwright/test";

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

test("optimizer rejects unsafe and duplicate parameter specifications", () => {
  expect(() =>
    validateParameterSpec({ name: "assets.albedo", min: 0, max: 1 })
  ).toThrow(/unsupported/);
  expect(() =>
    validateParameterSpec({ name: "renderer.roughness", min: -1, max: 1 })
  ).toThrow(/bounds/);
  expect(() =>
    validateParameterSpecs([
      { name: "renderer.roughness" },
      { name: "renderer.roughness" }
    ])
  ).toThrow(/unique/);
});

test("optimizer mutations are immutable and candidates remain bounded", () => {
  const changed = setProfileParameter(PROFILE, "renderer.roughness", 0.6);
  expect(getProfileParameter(PROFILE, "renderer.roughness")).toBe(0.45);
  expect(getProfileParameter(changed, "renderer.roughness")).toBe(0.6);

  const spec = validateParameterSpec({
    name: "renderer.foilStrength",
    min: 0.65,
    max: 0.75,
    step: 0.1,
    minimumStep: 0.01
  });
  expect(
    coordinateCandidates(PROFILE, spec).map((profile) => profile.renderer.foilStrength)
  ).toEqual([0.65, 0.75]);
});

test("locked parameters, cache keys, and step reduction are deterministic", () => {
  const locked = validateParameterSpec({
    name: "renderer.roughness",
    locked: true
  });
  expect(coordinateCandidates(PROFILE, locked)).toEqual([]);

  const specs = validateParameterSpecs([
    { name: "renderer.foilStrength" },
    { name: "renderer.roughness" }
  ]);
  const equivalent = {
    metadata: { ignored: true },
    renderer: {
      roughness: 0.45,
      foilStrength: 0.7,
      iridescenceThicknessMinNm: 999
    }
  };
  expect(profileCacheKey(PROFILE, specs)).toBe(profileCacheKey(equivalent, specs));

  const stepSpec = validateParameterSpec({
    name: "renderer.roughness",
    min: 0.2,
    max: 0.8,
    step: 0.1,
    minimumStep: 0.025
  });
  const state = createOptimizerState(PROFILE, [stepSpec]);
  expect(state.steps["renderer.roughness"]).toBe(0.1);
  expect(nextStep(0.1, stepSpec)).toBe(0.05);
  expect(nextStep(0.05, stepSpec)).toBe(0.025);
  expect(nextStep(0.025, stepSpec)).toBe(0);
});
