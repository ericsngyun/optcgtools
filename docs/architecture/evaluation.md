# Evaluation and release gates

## Registration

- corner reprojection error;
- residual alignment error on stable printed regions;
- frame blur and clipping rates;
- exposure and white-balance drift.

## Masks

- reviewed intersection-over-union by material channel;
- boundary error around text, character edges, and gold linework;
- false-positive foil area;
- false-negative metallic area;
- uncertainty calibration.

## Angular appearance

- highlight centroid trajectory error;
- highlight width and elongation error;
- regional luminance-response correlation;
- regional chroma-response correlation;
- hue-order agreement;
- angular bandwidth error;
- temporal consistency during continuous tilt.

## Perceptual review

Reviewers score:

- physical believability;
- restraint versus over-foiling;
- character/background separation;
- black-ink suppression;
- gold/silver material correctness;
- texture scale;
- clearcoat independence;
- fidelity on dark and light UI backgrounds.

## Performance

Measure grid, detail, and hero tiers separately:

- initial asset bytes;
- decoded texture memory;
- average and p95 frame time;
- offscreen CPU/GPU activity;
- interaction latency;
- reduced-motion and static fallback behavior.

## Release state

```text
hypothesis
photo-validated
capture-validated
production-validated
```

A release report must include metrics, known limitations, reviewer identity, approved devices/browsers, profile hash, asset hashes, and pipeline commit.
