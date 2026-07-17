# Material-pipeline agent contracts

## Operating rule

Agents produce evidence, candidate assets, metrics, and review tasks. They do not silently publish a card profile as accurate.

## Shared job envelope

```json
{
  "jobId": "uuid",
  "cardId": "OP01-120",
  "printVariant": "JP-first-print",
  "captureSession": "capture-session-id",
  "pipelineCommit": "git-sha",
  "inputs": [{ "uri": "private://...", "sha256": "..." }],
  "requestedOutputs": ["registered-frames", "foil-mask"],
  "createdAt": "ISO-8601"
}
```

Every worker must be idempotent for the same job envelope and content hashes.

## Catalog agent

Input:

- card identifier or image/video set;
- optional official card-list metadata;
- source and rights information.

Output:

- canonical card metadata;
- candidate material family with confidence;
- duplicate/variant warnings;
- unresolved questions.

Hard failure:

- card identity cannot be resolved;
- source rights are absent;
- alleged authenticated capture has no provenance record.

## Registration agent

Input:

- capture sequence;
- camera and capture metadata.

Output:

- canonical homographies;
- registered frames;
- blur, saturation, exposure-drift, and corner-error metrics;
- stable-region mask used for residual alignment.

Hard failure:

- card corners leave the image;
- highlight clipping destroys a required measurement region;
- registration exceeds the configured error threshold.

## Semantic-region agent

Input:

- registered neutral frame;
- optional human points, boxes, or rough masks;
- prior family template.

Output:

- character, background/panel, border, title plate, stats/icons, black-ink, and miscellaneous region masks;
- uncertainty map;
- review prompts.

Constraint:

- use SAM 2 or comparable promptable segmentation as a proposal engine;
- preserve small text and gold linework for manual review;
- never replace uncertainty with fabricated crisp edges.

## Reflectance agent

Input:

- registered image stacks;
- semantic regions;
- lighting/camera metadata.

Output:

- foil activity;
- metallic activity;
- gloss/clearcoat;
- ink suppression;
- texture/normal;
- direction/anisotropy;
- per-pixel confidence;
- diagnostic plots and angular response summaries.

Constraint:

- distinguish brightness-only metallic response from hue-traveling foil response;
- separate soft-light clearcoat from hard-light microtexture;
- preserve raw measured maps before cleanup.

## Material-fitting agent

Input:

- approved candidate maps;
- matched reference frames;
- renderer and device tier.

Output:

- parameterized CSS profile;
- parameterized WebGL/WebGPU profile;
- optional glTF material settings;
- matched-angle renders;
- fitting loss by region and frame.

Constraint:

- prefer interpretable basis responses;
- do not bake camera exposure errors into the material;
- report when the standardized PBR model cannot reproduce the observed response.

## Review agent

Input:

- physical references;
- candidate maps/profile;
- comparison renders.

Output:

- structured findings;
- accept/revise recommendation;
- over-foil and under-foil heatmaps;
- wrong hue-order and highlight-direction flags;
- region-specific comments.

Constraint:

- recommendation is advisory;
- final approval requires a named human reviewer.

## 3D asset agent

Input:

- approved material profile;
- card geometry specification;
- delivery quality tier.

Output:

- GLB;
- validation report;
- texture manifest;
- turntable renders;
- performance report.

Constraint:

- use standard glTF material extensions where adequate;
- retain custom shader metadata when the approximation is known to be incomplete;
- validate normals, tangents, UVs, and texture color spaces.

## Publishing agent

Input:

- approved profile and assets;
- rights metadata;
- review record.

Output:

- immutable versioned manifest;
- CDN paths;
- cache/version keys;
- deployment record.

Hard failure:

- profile schema invalid;
- asset hash mismatch;
- rights status missing;
- review state not approved;
- production asset points at raw private captures.
