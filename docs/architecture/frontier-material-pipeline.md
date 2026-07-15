# Frontier authenticated-card material pipeline

## Objective

Produce reviewable, provenance-aware material maps and renderer profiles from authenticated One Piece Card Game physical references. The system must support lightweight CSS simulations, research-grade WebGL/WebGPU rendering, and exportable 3D card assets.

The pipeline is analysis-by-synthesis: extraction is not accepted because a model says a mask looks plausible. A candidate profile is rendered under matched camera and light conditions and compared against the physical capture sequence.

## What we retain from pokemon-cards-css

The upstream project establishes several excellent engineering boundaries:

- interaction state is normalized into pointer, rotation, distance, and background coordinates;
- spring smoothing prevents mechanical cursor motion;
- CSS custom properties separate behavior from material styling;
- a stable card DOM contains independent image, shine, and glare passes;
- rarity/proxy logic resolves assets before the renderer;
- card-specific masks and foil assets are supported;
- finish CSS remains modular.

We preserve those boundaries. We do not preserve the assumption that one rarity maps to one shader or that one grayscale mask is enough.

Pinned reference: `simeydotme/pokemon-cards-css@acb1197633e749a1fba4412231db2f6581586d00`.

## Frontier system topology

```text
Authenticated card / controlled capture
        │
        ▼
Capture ingestion + provenance ledger
        │
        ▼
Frame rectification and registration
        │
        ├── stable albedo stack
        ├── tilt-x / tilt-y stacks
        ├── moving hard-light stack
        ├── moving soft-light stack
        └── raking-light stack
        │
        ▼
Promptable semantic segmentation
        │
        ├── character
        ├── manga panels / background
        ├── frame and border
        ├── title plate
        ├── cost / power / icons
        └── black-ink groups
        │
        ▼
Measured reflectance decomposition
        │
        ├── foil activity
        ├── metallic activity
        ├── gloss / clearcoat
        ├── ink suppression
        ├── texture / normal
        └── directional anisotropy
        │
        ▼
Material-profile fitting
        │
        ├── CSS fallback profile
        ├── WebGL/WebGPU research profile
        └── glTF 3D asset profile
        │
        ▼
Review UI + analysis-by-synthesis evaluation
        │
        ▼
Human approval and production publication
```

## Agent roles

### Catalog agent

- identifies the card and print variant;
- reconciles set, rarity, language, and known finish family;
- records evidence and rights metadata;
- never treats rarity as the final material classification.

### Registration agent

- detects the four card corners;
- estimates projective transforms;
- rectifies every frame to a canonical canvas;
- performs residual alignment on stable printed regions;
- rejects frames with blur, clipping, exposure drift, or severe glare saturation.

### Semantic-region agent

Use promptable segmentation as an interactive accelerator, not as the final source of truth. SAM 2 is suitable for propagating human prompts through a tilt video, but masks must be registered to the canonical card and reviewed around text, black ink, fine gold linework, and transparent-looking foil regions.

### Reflectance agent

Computes per-pixel and per-region features across registered frames:

- luminance variance;
- chroma variance;
- hue travel and hue order;
- highlight peak and angular location;
- low-frequency versus high-frequency response;
- warm-metal versus neutral-metal response;
- response under hard versus soft light.

It emits candidate foil, metallic, gloss, suppression, texture, direction, and confidence maps.

### Material-fitting agent

Fits a small number of interpretable material lobes rather than one arbitrary neural appearance field:

1. stable printed albedo;
2. dielectric clearcoat;
3. neutral or warm metallic response;
4. iridescent/diffractive response;
5. anisotropic or embossed texture response.

The first production implementation may use optimized procedural parameters. The research renderer should support per-pixel maps and differentiable or gradient-free fitting against reference frames.

### Review agent

- compares predicted and reference frames at matched angles;
- produces difference heatmaps and region-level metrics;
- identifies over-foiling, missing suppression, wrong hue order, and wrong highlight direction;
- cannot approve publication without human review.

### Asset-publishing agent

- validates the JSON profile schema;
- hashes every asset;
- verifies rights and provenance;
- emits CSS, WebGL, and glTF manifests;
- prevents raw unlicensed reference photography from entering the public repository.

## Recommended frontier techniques

### Multi-view inverse rendering

Use recent multi-view inverse-rendering work as research guidance for recovering albedo, roughness, metallic response, normals, and lighting consistently across views. For this flat-object domain, controlled capture plus strong geometric priors should outperform blindly applying a general scene model.

Relevant primary research:

- MAIR++: https://arxiv.org/abs/2408.06707
- IRIS: https://arxiv.org/abs/2401.12977
- MVInverse: https://arxiv.org/abs/2512.21003
- Dynamic Inverse Rendering: https://arxiv.org/abs/2607.09329
- Interpretable Basis BRDFs: https://arxiv.org/abs/2411.17994

### Glossy and reflective reconstruction

Reflective Gaussian methods are useful as a research baseline for view-dependent appearance and relighting, but production card assets should remain compact and interpretable rather than shipping an opaque splat field.

- RGS-DR: https://arxiv.org/abs/2504.18468

### Promptable video segmentation

- SAM 2: https://arxiv.org/abs/2408.00714
- official implementation: https://github.com/facebookresearch/sam2

### Material standards for 3D delivery

Use glTF 2.0 with standard Khronos extensions where they match the measured material:

- `KHR_materials_iridescence` for thin-film-style view-dependent hue;
- `KHR_materials_anisotropy` for directional elongated highlights;
- core metallic-roughness, normal maps, and clearcoat extensions;
- custom shader metadata only when the standardized model cannot reproduce the capture.

Specifications:

- https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_materials_iridescence
- https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_materials_anisotropy

## Data and artifact boundaries

### Private reference storage

Contains authenticated-card RAW images, videos, marketplace research references, and review screenshots.

### Public repository

Contains code, schemas, synthetic fixtures, legally usable derived maps, documentation, profile manifests, and approved demo assets.

### Immutable provenance ledger

Every processed artifact records:

- source capture session;
- card identity and print variant;
- source rights;
- model/tool versions;
- pipeline commit;
- input and output hashes;
- human reviewer;
- confidence state.

## Acceptance gates

A profile cannot advance beyond `hypothesis` without multiple independent photo references. It cannot advance to `capture-validated` without controlled physical capture. It cannot advance to `production-validated` until the real and virtual card have been reviewed side by side on target desktop and mobile devices.

Minimum quantitative checks:

- corner-registration error;
- semantic-region mask IoU on reviewed frames;
- highlight trajectory error across both tilt axes;
- hue-order agreement;
- regional foil-activity correlation;
- texture-frequency plausibility at target render sizes;
- runtime frame time and memory usage.

## Implementation sequence

1. establish private capture storage and manifest ingestion;
2. build registration and frame-quality gates;
3. add promptable region-mask review;
4. derive measured material maps;
5. fit four benchmark finish families;
6. build the WebGL/WebGPU reference renderer;
7. build the side-by-side review UI;
8. export glTF 3D assets;
9. compile lightweight CSS profiles;
10. expand by finish family with human approval.
