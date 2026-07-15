# OPTCG material implementation roadmap

## Immediate architecture change

The existing lab has one `mask` plus shared `foil-base`, `shine`, `etch`, and `glare` layers. That is enough for exploratory tuning but not for accurate SP, manga, and textured alternate-art reproduction.

Move to a multi-channel material profile:

```ts
export type CardMaterialProfile = {
  id: string;
  family:
    | "manga-prismatic-panel"
    | "manga-gold-metallic"
    | "sp-gold-ornamental"
    | "sp-manga-scene"
    | "sp-color-field"
    | "alt-art-coated"
    | "alt-art-textured"
    | "leader-parallel-textured"
    | "treasure-rare";
  confidence: "hypothesis" | "photo-validated" | "capture-validated" | "production-validated";
  assets: {
    albedo: string;
    foilMask?: string;
    metallicMask?: string;
    glossMask?: string;
    normalMap?: string;
    directionMap?: string;
    regionMask?: string;
  };
  parameters: {
    foilStrength: number;
    metallicStrength: number;
    clearcoatStrength: number;
    roughness: number;
    diffractionBandwidth: number;
    diffractionRotation: number;
    textureScale: number;
    textureDepth: number;
    maxTilt: number;
  };
};
```

## Rendering tiers

### Tier 1 — CSS retail grid

Use for product grids and collection pages.

- 3D tilt;
- broad clear-coat glare;
- one foil mask;
- one metallic mask;
- low-cost gradient diffraction;
- no continuous autoplay;
- disable or simplify offscreen cards.

Target: convincing at thumbnail size with low GPU cost.

### Tier 2 — CSS enhanced product card

Use for product detail and featured cards.

- independent masks for foil, metallic, gloss, and texture;
- multiple pseudo-elements or nested layers;
- card-specific texture image;
- calibrated hue order and highlight width;
- optional device orientation.

Target: strong perceptual match without WebGL.

### Tier 3 — WebGL reference renderer

Use in the lab and optionally for a premium hero experience.

CSS gradients cannot accurately represent spatially varying diffraction direction, normal maps, multiple specular lobes, or per-pixel roughness. A fragment shader should support:

- albedo texture;
- metallic mask;
- roughness/gloss mask;
- normal map;
- diffraction direction map;
- region-specific intensity;
- warm metallic and prismatic responses as separate lobes;
- controllable camera/light vectors;
- tone mapping matched to browser output.

The WebGL renderer becomes the ground-truth implementation. CSS presets can then be fit as lower-cost approximations.

## Required component layers

Replace the single masked shine model with:

```html
<div class="card__front">
  <img class="card__albedo" />
  <div class="card__metallic" />
  <div class="card__diffraction" />
  <div class="card__texture" />
  <div class="card__clearcoat" />
  <div class="card__edge-glint" />
</div>
```

Each layer receives its own mask and blend mode.

## Why the current presets must change

### Current `sp-etched`

The preset uses a uniform repeating diagonal band and uniform procedural microtexture. Real gold-anniversary SP references show composition-specific gold linework and localized iridescent fill. The generic line pattern should become only a fallback fixture.

### Current `sp-rainbow`

The conic gradient produces a digital color wheel. Real manga-panel and manga-scene references show broad moving patches or bands constrained by printed regions, with dark ink suppressing the response. Replace the conic field with calibrated directional fields and masks.

### Current `alt-art`

The preset disables the etch layer and applies a restrained global glare. This is suitable only for coated, minimally textured alternate arts. Create a separate `alt-art-textured` family with card-specific height/texture assets and region masks.

## First benchmark card set

Use a small representative set rather than attempting every card immediately:

1. **Shanks OP01-120 manga** — baseline manga-prismatic panel behavior.
2. **Monkey.D.Luffy OP11 gold SP** — gold ornamental SP.
3. **Marshall.D.Teach OP09-093 gold SP** — verifies whether one ornamental preset generalizes across different compositions.
4. **Roronoa Zoro OP12 SP** — manga-scene SP.
5. **One clearly textured standard alternate art** — alt-art-textured benchmark.
6. **One restrained/gloss-dominant alternate art** — alt-art-coated benchmark.
7. **Gol D. Roger gold manga** — manga-gold-metallic benchmark.
8. **One leader parallel** — leader-specific frame and badge masking.

Select authenticated English cards where possible for the final GenkiStuff target, and photograph Japanese copies separately when comparing print differences.

## Research tasks

### R1 — Reference manifest

Create `references/manifest.json` containing:

- card ID;
- language and print run;
- rarity label;
- proposed material family;
- source URLs;
- capture ownership/permission;
- confidence level;
- known ambiguities.

### R2 — Multi-mask support

Update `HoloCard.svelte` and `CardProxy.svelte` to accept all material channels independently.

### R3 — Comparison mode

Add synchronized side-by-side views:

- real reference video/frame;
- virtual render;
- mask/debug visualization;
- difference/overlay mode;
- shared angle scrubber.

### R4 — WebGL reference shader

Build a small fragment-shader renderer behind a feature flag. Keep the Svelte control panel and material manifest shared with the CSS renderer.

### R5 — Parameter fitting

Fit parameters against registered reference frames. Start manually, then add an offline optimization script using image similarity and region-weighted error.

### R6 — Device QA

Validate on:

- Safari/iPhone;
- Chrome/Android;
- Chrome/macOS;
- Safari/macOS;
- low-power/reduced-motion mode;
- dark and light GenkiStuff surfaces.

## Definition of done for one card family

- at least two authenticated cards in the family;
- controlled multi-angle reference sets;
- independent foil/metallic/gloss/texture masks;
- Tier 3 renderer visually matched at defined benchmark angles;
- Tier 2 CSS approximation approved side-by-side;
- performance budget documented;
- fallback still image and reduced-motion behavior present;
- confidence marked `capture-validated` or higher.
