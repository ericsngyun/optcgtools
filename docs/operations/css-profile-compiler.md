# CSS profile compiler

`scripts/compile-card-profile.mjs` (library: `scripts/lib/profile-compiler.mjs`)
compiles a card-material-profile JSON plus the asset files it declares into
deterministic browser delivery assets. The compiler is pure data flow: it
never creates or infers material maps, and it contains no card-specific
constants (a source-scan test in `tests-node/profile-compiler.test.mjs`
enforces this).

## Contract

```
npm run compile:profile -- \
  --profile <card-material-profile.json> \
  --input-dir <asset-root> \
  [--out <dir>]                     # default: generated/cards/<card.id>/
  [--publication-report <report>]  # required for approved production profiles
  [--generated-at <iso-string>]    # optional; omitted by default so output
                                   # carries no timestamp
```

Inputs:

- a profile conforming to `schemas/card-material-profile.schema.json`;
- the asset files its `assets.*.uri` entries declare, resolved inside
  `--input-dir` (web-root URIs such as `/img/masks/x.svg` resolve under the
  input directory).

Outputs (`generated/cards/<profile-id>/`, git-ignored, never committed):

- `card.css` — scoped to `.card[data-card-profile="<id>"]`;
- `card-manifest.json` — canonical JSON (recursively sorted keys, no
  timestamp unless `--generated-at` is passed) binding the profile sha256,
  the card.css sha256, and per-asset sha256 hashes;
- `assets/<channel>-<sha256[0:16]>.<ext>` — verbatim copies of the declared
  assets, content-addressed;
- `webgl-handoff.json` — only when the profile declares channels CSS cannot
  reproduce (`normalMap`, `directionMap`, `gltf`). Stub manifest only; no GLB
  and no WebGL implementation.

Determinism: identical profile bytes + asset bytes produce byte-identical
output. Verified by a compile-twice test.

Asset rules:

- a DECLARED asset that is missing is an error (`CompileRefusal`);
- an UNDECLARED optional channel degrades the output (fewer layers, down to
  a static albedo-only fallback);
- refused outright: remote URIs, `..` traversal, backslashes, `~`, paths
  escaping the input directory, and any path containing `private-media/`,
  `public-reference-bundles/`, `raw-captures/`, `private-references/`, or
  `marketplace-references/`;
- an `assets.*.sha256` declared in the profile must match the file content.

## State gating

The compiler reads `lane`, `classification.confidence`, and
`provenance.reviewStatus`/`provenance.sourceType`:

| Profile state | Result |
| --- | --- |
| `provenance.sourceType: "synthetic"` (fixture convention, see `examples/profiles/OP01-120.synthetic.example.json`) | Compiles; manifest `visibility: "synthetic-fixture"` and notice `"synthetic — not an accurate card"` (also in the CSS header). |
| `lane: "reference"` | Compiles as internal preview; manifest `visibility: "private-nonpublishable"`, CSS header `INTERNAL REFERENCE PROTOTYPE — PRIVATE, NON-PUBLISHABLE`. Reference-lane publication remains fail-closed upstream (ADR-0002). |
| physical lane, `provenance.reviewStatus: "approved"` | Compiles only with `--publication-report`, the JSON report emitted by `optcg-review check-publish --report`. The compiler validates `passed: true`, empty `errors`, and that `profile_digest` equals the sha256 of the exact profile bytes being compiled. The gate itself is never reimplemented — the report is proof it passed. |
| anything else | Refused with a clear error. |

## CSS variable set

`card.css` defines the documented variable set on the profile scope. All
formulas are fixed, card-agnostic mappings from bounded renderer parameters
(family presets in `FAMILY_RENDER_HINTS` key off the schema's finish-family
enum, never off card ids):

| Variable | Source |
| --- | --- |
| `--foil-strength` | `renderer.foilStrength` (clamped 0..2) |
| `--foil-band-angle` | `117deg + anisotropyRotationRad` (degrees, mod 360) |
| `--foil-band-width` | `6% + iridescence thickness span / 2000nm * 10%`, clamped 6–16% |
| `--foil-hue-offset` | `iridescenceThicknessMinNm / 2000nm * 360deg` |
| `--metallic-strength` | `renderer.metallicStrength` |
| `--metallic-warmth` | finish-family preset (e.g. `manga-gold-metallic` → 0.85) |
| `--gloss-strength` | `glossStrength * (0.4 + 0.6 * clearcoat)` |
| `--gloss-size` | `55% + clearcoatRoughness * 70%` |
| `--texture-strength` | `renderer.textureStrength` |
| `--texture-scale` | `1` (no schema parameter yet) |
| `--texture-direction` | `38deg + anisotropyRotationRad` (degrees, mod 180) |
| `--ink-suppression` | `0.85` when a suppression mask is declared, else `0` |

Six material layers route independently: albedo (`.card__image`), diffractive
foil (`.card__shine` ← `foilMask`), metallic (`.card__foil-base` ←
`metallicMask`), texture/etching (`.card__etch` ← `textureMask`), ink
suppression (`.card__suppression` ← `suppressionMask`), clearcoat glare
(`.card__glare` ← `glossMask`). Mask routing is emitted both as custom
properties and as direct `mask-image` rules — Chromium resolves `url()`
consumed through a custom property against the document base rather than the
stylesheet, so the direct rules are authoritative.

## Tiers

- **grid** — one simplified effective foil layer (`--grid` effective strength
  `clamp(0.7*foil + 0.3*metallic, 0, 1.4)`) plus glare; metallic, etch, and
  suppression layers hidden; tilt halved (`min(maxTiltDeg,16)/2`);
  `suspendOffscreen: true` (HoloCard drives `data-suspended` from an
  IntersectionObserver; all effect layers and the 3D transform collapse when
  suspended).
- **detail** — independent multi-channel layers; restrained tilt
  `min(maxTiltDeg, 16)`.
- **static / reduced motion** — `@media (prefers-reduced-motion: reduce)`
  hides shine/etch/suppression/glare and keeps a faint static metallic sheen
  over the albedo. Profiles that declare no dynamic channels compile to
  static-only output (`tiers.static.staticOnly: true`, tilt 0).
- **hero** — WebGL handoff manifest stub only (see above).

## Consuming compiled output

`CardProxy` accepts `manifest` (parsed `card-manifest.json`), `manifestBase`
(URL prefix where the compiled directory is served), `tier`, and optional
`staticPose`. It resolves the albedo/back images, injects the manifest's
CSS variables, and sets `data-card-profile`/`data-card-tier` so the compiled
stylesheet takes over; `finish` is set to `compiled` so no built-in preset
recipe double-applies. The compiled `card.css` must be loaded (e.g. a
`<link>`), and the upstream pointer/spring/CSS-variable interaction boundary
is unchanged. Neither tier imports Three.js.

## Visual comparison and CSS fidelity limits

`tests-web/profile-compiler-visual.spec.js` renders the compiled synthetic
fixture through HoloCard at seven canonical poses (neutral, tilt left/right/
top/bottom, glare center/edge, pointer state driven deterministically via
`staticPose`) and captures the research renderer at matched card tilts and
light states (flat presentation; low-elevation light so the specular response
stays on the card face). It writes a pose-grid contact sheet and metrics to
`test-results/profile-compiler-visual/`.

Measured with the `OP01-120` synthetic fixture (mean absolute luminance
difference over 240x336 downsampled frames, 0..1 scale):

| Pose | meanAbsDiff |
| --- | --- |
| neutral | 0.214 |
| tilt-left | 0.284 |
| tilt-right | 0.320 |
| tilt-top | 0.317 |
| tilt-bottom | 0.305 |
| glare-center | 0.283 |
| glare-edge | 0.253 |

Pose responsiveness (CSS left-vs-right frame difference): 0.146; neutral vs
glare-center: 0.134.

Hard assertions guard only gross failures (blank output, meanAbsDiff ≥ 0.45,
high-saturation fraction ≥ 0.85 i.e. full-card rainbow, unresponsive
layers). The residual differences are known, expected divergences of the CSS
approximation, not regressions:

- **Diffuse/spectral energy.** The physically based reference with a dark
  albedo responds almost exclusively through the clearcoat specular lobe; the
  CSS stack is systematically brighter and far more saturated (gradient foil
  bands are always partially visible while the pointer is active). This is
  the standardized-PBR-vs-stylized-CSS gap, recorded here as a finding.
- **Highlight shape.** CSS glare is a radial gradient at the pointer; the PBR
  highlight is a physically-shaped lobe whose size depends on roughness and
  light distance.
- **Iridescence.** CSS approximates thin-film hue travel with fixed
  hue-rotated gradient bands; it cannot reproduce angle-dependent thin-film
  interference, anisotropic highlight stretching, or normal-map relief (these
  channels trigger the WebGL handoff instead).
- **Perspective.** The research camera has physical perspective; the CSS card
  uses CSS 3D transforms with a 900px perspective and content-bbox cropping
  in the comparison, so edge geometry differs slightly at high tilt.
