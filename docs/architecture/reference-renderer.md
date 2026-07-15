# Physical reference renderer

## Purpose

The physical renderer is the analysis-by-synthesis target for authenticated OPTCG captures. It is not a decorative replacement for the CSS card. It renders a deterministic 3D card at the same card pose, camera state, and light state used by a physical capture so measured material maps can be reviewed and fitted.

Current implementation: three.js r185 `WebGPURenderer`, with the renderer's built-in WebGL 2 fallback when WebGPU is unavailable.

## Mapping from measured channels

| Extracted channel | three.js physical input | Notes |
| --- | --- | --- |
| albedo | `map` | sRGB printed artwork |
| metallic mask | `metalnessMap` | scalar proposal; strength baked into browser map |
| foil mask | `iridescenceMap` | portable thin-film baseline, not a claim about foil manufacturing |
| suppression mask | multiplied into the effective iridescence map | prevents dense black ink from receiving generic rainbow response |
| gloss mask | `clearcoatMap` | broad laminate response remains independent from foil |
| texture mask | contributes to derived roughness | high-frequency surface response |
| normal map | `normalMap` and restrained `clearcoatNormalMap` | tangent-style raking-light estimate |
| direction map | `anisotropyMap` | RG direction, B strength |
| direction + foil | derived `iridescenceThicknessMap` | bounded approximation for spatial hue travel |

The original extracted maps remain immutable. Browser delivery maps are compiled derivatives with provenance back to the extraction run.

## Geometry

The card uses a shallow rounded rectangular body plus independent front and back cap geometry:

- width: 1.436 units;
- height: 2 units;
- depth: 0.018 units;
- rounded corners and small edge bevel;
- separate front, back, and edge materials;
- normalized front/back UVs;
- deterministic camera and card transforms.

This is adequate for product and fitting views. Micrometer-scale cardstock deformation, print-layer depth, edge wear, sleeve optics, and slab optics are outside the current geometry model.

## Deterministic state

A saved render state includes:

- normalized material profile;
- card X/Y pose;
- light azimuth, elevation, and distance;
- exposure;
- channel enable/solo state;
- camera position, quaternion, target, and FOV;
- selected three.js revision and active renderer backend.

The same state must be loadable by the future fitting worker and review workspace. The UI exports this state as JSON and can export a canonical PNG.

## Channel review

Reviewers can independently disable or solo:

- albedo;
- foil/iridescence;
- metallic;
- clearcoat;
- texture/normal;
- anisotropy.

A profile cannot be approved while a material channel is only visually plausible in the composite but incorrect when isolated.

## Standards boundary

`MeshPhysicalMaterial` provides a useful portable baseline:

- clearcoat and clearcoat normal;
- iridescence intensity and thickness;
- anisotropy direction and strength;
- metallic/roughness and tangent-space normals.

Real trading-card foil is not necessarily thin-film interference. If matched physical captures show incorrect hue order, highlight width, angular speed, spatial direction, or region coupling, the research renderer must add a custom TSL material node. The standardized material should remain available as the GLB/export fallback and its approximation error must be recorded.

## Runtime gates

The repository browser test checks:

- CSS renderer still initializes;
- physical renderer canvas becomes visible;
- adaptive WebGPU/WebGL backend reaches a ready state;
- no page or console errors occur;
- material channel controls update;
- software-GPU Chromium can render the lab in CI.

Future gates should add fixed-state screenshot comparisons only after a stable cross-platform reference tolerance is defined. Exact pixel equality is not appropriate across different GPU backends.
