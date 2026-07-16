# Bounded material-profile optimization

## Purpose

The optimizer tunes a small set of interpretable renderer parameters against authenticated, registered physical reference sequences. It is not a generative shader search and it cannot alter source images, semantic masks, card identity, authentication, or rights metadata.

Entry point:

```bash
node scripts/optimize-profile.mjs <optimization-request.json>
```

Example contract:

```text
examples/optimize-profile.example.json
```

## Preconditions

Do not run optimization until all of the following are true:

1. the physical card is authenticated by a named human reviewer;
2. source rights are recorded;
3. the capture session passes quality, rectification, and registration gates;
4. the render and fit templates contain the same ordered frame identifiers;
5. physical reference frames are in canonical card coordinates;
6. semantic-region masks used for weighting are reviewed;
7. the Vite research renderer can load every profile asset;
8. `uv`, Python dependencies, Chromium, and npm dependencies are installed.

## Canonicalized candidate frames

The renderer produces a perspective image because material appearance depends on the real viewing direction. Before evaluation, the batch exporter:

1. records the renderer camera and card pose;
2. projects the four physical card corners into renderer-canvas coordinates;
3. captures the full perspective canvas;
4. sends the screenshot and projected quadrilateral through the same OpenCV projective warp used by the physical-capture pipeline;
5. emits a 1436×2000 canonical candidate frame by default;
6. preserves projected corners and canonical dimensions in the frame-state JSON.

This is mandatory. Comparing a canonical physical frame against an unrectified perspective candidate would mix geometric error into the material loss.

## Allowed parameters

The optimizer only accepts the hard-coded whitelist in `scripts/lib/profile-optimizer.mjs`:

- foil strength;
- metallic strength;
- gloss strength;
- texture strength;
- roughness;
- clearcoat;
- clearcoat roughness;
- iridescence strength;
- iridescence IOR;
- iridescence thickness minimum and maximum;
- anisotropy strength;
- anisotropy rotation.

Each parameter has global physical/safety bounds. A request may narrow those bounds but cannot expand them. Parameters may be locked.

Exposure is deliberately excluded from profile optimization. Capture and renderer exposure must be calibrated explicitly rather than silently absorbing material errors.

## Search strategy

The current strategy is retained coarse-to-fine coordinate descent:

1. evaluate the baseline profile;
2. evaluate positive and negative bounded steps for one parameter;
3. accept the best candidate only when it improves aggregate loss beyond the configured tolerance;
4. otherwise halve that parameter's step;
5. continue across parameters and passes until the trial budget or minimum steps are reached.

Repeated parameter vectors are cached. Invalid coupled states, including minimum iridescence thickness exceeding maximum thickness, fail before rendering.

This strategy is intentionally conservative and interpretable. Future optimizers may add Bayesian or gradient-free search, but they must retain the same parameter bounds, locked-channel behavior, trial provenance, and failure reporting.

## Trial artifacts

Every trial retains:

```text
review/optimization/<run-id>/trials/<trial-id>/
  profile.json
  render-request.json
  render.log
  candidate/
    <frame-id>.png
    <frame-id>.json
    render-sequence.json
  fit-request.json
  fit.log
  fit-report.json
```

The run directory also contains:

- `optimization-progress.json` after every completed trial;
- `best-profile.json`;
- `optimization-report.json` with all losses, parameters, steps, cache keys, and retained artifact paths.

Do not delete losing trials from a profile submitted for review. They are evidence of the search process and help diagnose parameter coupling or model inadequacy.

## Objective function

The evaluator reports and weights:

- linear-RGB error;
- image-gradient error;
- circular hue error;
- highlight-centroid position error;
- exposure error;
- temporal-delta error;
- approved semantic-region metrics.

A whole-card average is not enough. Localized foil fields, title plates, black ink, gold linework, character regions, and frame elements should receive explicit region masks and weights where appropriate.

## Promotion gates

An optimizer output remains `trial` or `hypothesis` unless:

- the best profile improves over the baseline on held-out angles, not only optimization frames;
- per-region losses improve without introducing obvious failures elsewhere;
- highlight direction and hue order agree on both horizontal and vertical tilt sequences;
- the result survives a repeat capture of the same physical card;
- a human reviewer approves the composite and isolated channels;
- the source physical-material model is documented as adequate.

If the standards-based three.js iridescence model cannot reproduce hue order, angular speed, bandwidth, or spatial direction, do not compensate by pushing parameters to extreme bounds. Record the failure and implement a custom TSL diffraction model while preserving the standard PBR profile as a comparison baseline.

## Family-level reuse

One optimized card does not establish a reusable finish family. At least two authenticated cards with the same observed print construction must independently fit within an agreed tolerance before a family preset is proposed.
