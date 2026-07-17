# Research renderer

## Objective

Provide the ground-truth virtual renderer used to fit and evaluate physical-card material profiles. The CSS card effect is compiled from this renderer after approval.

## Required controls

- camera field of view, distance, and orientation;
- card orientation around both axes;
- point, area, and environment lights;
- light position, angular size, intensity, and color temperature;
- exposure and tone mapping;
- solo/mute for albedo, metallic, iridescence, texture, clearcoat, and edge response;
- reference-frame selection and overlay;
- deterministic capture of canonical comparison frames.

## Material model

Use interpretable components:

- printed dielectric base;
- roughness;
- warm/neutral metallic mask;
- clearcoat with independent roughness;
- iridescence intensity and thickness texture;
- normal map;
- anisotropy direction and strength;
- optional custom diffractive lobe when standard thin-film behavior is insufficient.

## Fitting modes

### Manual calibration

Reviewer adjusts physically meaningful parameters while observing matched reference frames.

### Automated fitting

Optimize approved parameters and map transforms against registered captures. Use region-weighted losses and regularization. Prevent parameter combinations outside plausible ranges.

### Hybrid fitting

Automated fitting proposes a solution and uncertainty; reviewer locks trusted channels and refits the remaining parameters.

## Losses and diagnostics

- robust linear-RGB image loss;
- edge-aware loss around semantic boundaries;
- regional luminance/chroma response loss;
- angular highlight trajectory loss;
- hue-order loss;
- perceptual preview loss for final display rendering;
- temporal consistency across tilt sequences.

## Technology direction

Start with Three.js/WebGL or WebGPU and explicit shader code so the pipeline remains inspectable. Retain compatibility with glTF standard materials, but do not limit the research renderer to standardized extensions when a measured OPTCG finish requires a custom lobe.

## Acceptance

- deterministic output for a saved profile/camera/light state;
- no hidden automatic exposure changes during fitting;
- linear-space comparison available;
- matched frames exportable with metadata;
- parameters serialize into the card-material profile;
- supports a flat card and a shallow rounded 3D mesh;
- runs diagnostics without production compression artifacts.
