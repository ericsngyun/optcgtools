# Material review workspace

## Purpose

Provide a human-in-the-loop environment for validating automatically extracted masks and material profiles against authenticated physical reference captures.

## Core views

### Reference viewer

- neutral albedo frame;
- tilt-x and tilt-y video/still scrubber;
- hard-light and soft-light sweeps;
- raking-light and macro references;
- card and capture metadata;
- provenance and rights status.

### Mask editor

- semantic regions;
- foil activity;
- metallic activity;
- gloss;
- texture;
- suppression;
- normal and direction diagnostic views;
- brush, erase, threshold, feather, region fill, and undo history;
- model confidence overlay.

### Matched renderer

- CSS and WebGL/WebGPU render modes;
- synchronized camera/card angle;
- synchronized light direction and softness;
- material-channel solo/mute;
- profile parameter controls;
- device-quality tier selector.

### Comparison workspace

- side-by-side, swipe, flicker, and difference views;
- highlight trajectory overlay;
- hue-order comparison;
- region-level response plots;
- error heatmaps;
- frame and region comments.

## Review states

```text
unreviewed
  -> needs-revision
  -> technically-approved
  -> rights-approved
  -> production-approved
```

Technical and rights approval are distinct. Publication requires both.

## Required actions

- accept or reject material family;
- accept or edit each map;
- approve renderer parameters per quality tier;
- record limitations of CSS or standardized glTF approximations;
- assign confidence state;
- capture reviewer identity and timestamp;
- create a revision task from any rejected region or frame.

## Audit record

Every review decision should append an immutable JSONL event:

```json
{
  "eventId": "uuid",
  "profileVersion": "sha256-or-semver",
  "reviewer": "user-id",
  "action": "approve-map",
  "channel": "metallicMask",
  "before": "sha256",
  "after": "sha256",
  "comment": "Retained gold linework; removed character skin region.",
  "createdAt": "ISO-8601"
}
```

## Acceptance criteria

- reviewer can complete the full workflow without editing repository files manually;
- all displayed frames are registered to the same canonical card coordinates;
- corrections preserve original model output and create a new derived asset;
- angle and light state can be reproduced from a saved URL or review record;
- profile cannot be published with unresolved required comments;
- every approved output validates against the material-profile schema.
