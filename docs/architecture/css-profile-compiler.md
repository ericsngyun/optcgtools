# CSS profile compiler

The CSS renderer is a delivery approximation compiled from an approved material profile. It must not become a separate hand-tuned truth that drifts away from the research renderer.

## Inputs

- approved material-profile JSON;
- foil, metallic, gloss, and texture masks;
- optional region and direction maps;
- target tier: grid or detail;
- target browser capability matrix.

## Compilation

1. bake ink suppression into browser-compatible effective masks;
2. simplify direction maps into a small number of regional gradient orientations;
3. quantize texture frequency to avoid shimmer and moiré;
4. produce CSS variables and finish classes;
5. generate image variants and responsive sizes;
6. attach provenance and profile-version metadata;
7. compare compiled CSS output with the research renderer at canonical angles.

## Required outputs

- card-specific mask assets;
- finish-family CSS preset;
- per-card CSS variable manifest;
- visual-regression snapshots;
- approximation limitations;
- runtime budget report.

## Rules

- preserve the pokemon-cards-css interaction interface;
- keep clearcoat independent from diffraction;
- do not use a full-card rainbow gradient when the approved foil mask is selective;
- do not represent gold metallic regions with only a hue tint;
- no constant animation in product grids;
- pause offscreen work;
- honor reduced motion;
- fail to the static albedo rather than show missing masks or broken effects.
