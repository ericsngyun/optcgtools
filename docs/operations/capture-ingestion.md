# Authenticated capture ingestion operations

This document is the operator runbook for issues #2 and #3. Raw physical-card media must remain in approved private storage or a private working directory. The public repository contains the pipeline, schemas, synthetic fixtures, and approved derived assets only.

## Fail-closed principles

- A model cannot mark a card authentic.
- Authentication and source rights are separate approval states.
- Capture files are immutable after ingestion; edits become new hashed inputs.
- Paths are relative to the session root and may not contain traversal or remote URLs.
- Duplicate file content is rejected.
- Frames that fail quality or geometry gates do not silently enter downstream fitting.
- Automatic card-corner detection must meet a confidence threshold. Otherwise use reviewed manual corners.

## Session lifecycle

### 1. Initialize

```bash
uv run optcg-material init ./private-references/<session-id> \
  --session-id <session-id> \
  --card-id <card-id> \
  --card-name "<name>" \
  --set-code <set-code> \
  --language EN \
  --operator "GenkiStuff Lab" \
  --rights-owner GenkiStuff
```

The command creates:

```text
capture-session.json
raw/
processed/rectified/
processed/registered/
diagnostics/quality/
diagnostics/registration/
review/
```

### 2. Ingest captures

Use one command per source file. Do not manually copy files into `raw/` and edit hashes.

```bash
uv run optcg-material add <session-root> <file> --kind albedo
uv run optcg-material add <session-root> <file> --kind tilt-x --angle -30
uv run optcg-material add <session-root> <file> --kind light-hard --angle -20
uv run optcg-material add <session-root> <file> --kind rake --direction left
uv run optcg-material add <session-root> <file> --kind macro --light-label title-plate
```

The default complete capture set requires:

- at least one diffuse albedo still;
- at least seven horizontal tilt stills or one horizontal tilt video;
- at least seven vertical tilt stills or one vertical tilt video;
- at least seven hard moving-light stills;
- at least three soft moving-light stills;
- four raking-light stills;
- four macro details.

These minimums are intake gates, not a guarantee that the material is sufficiently sampled.

### 3. Record authentication and rights

```bash
uv run optcg-material verify-auth <session-root> \
  --method "authenticated inventory intake and physical inspection" \
  --verifier "<reviewer>" \
  --evidence-reference "<private evidence record>"

uv run optcg-material set-rights <session-root> \
  --status owned-capture \
  --public-derivatives-allowed \
  --no-public-albedo-allowed
```

A verified state requires a named verifier and method. The model pipeline must never invoke this command automatically.

### 4. Validate integrity and completeness

```bash
uv run optcg-material validate <session-root>
```

Use `--integrity-only` during incomplete acquisition sessions. Strict validation is required before extraction.

### 5. Run quality preflight

```bash
uv run optcg-material quality <session-root>
```

The current deterministic gates measure:

- decodability;
- image dimensions;
- Laplacian blur variance;
- mean luminance;
- dark clipping;
- bright clipping;
- per-channel clipping.

The reports are written to `diagnostics/quality/`. These are baseline gates. Later work should add exposure-drift checks across a sequence, color-checker calibration, motion blur direction, and polarization metadata.

### 6. Rectify to canonical coordinates

```bash
uv run optcg-material rectify <session-root>
```

The detector uses card contour geometry and the known trading-card aspect ratio, then warps accepted images to 1436×2000. If detection is ambiguous, create a manual-quads JSON file:

```json
{
  "raw/albedo/0000-example.png": [
    [412.0, 238.0],
    [1510.0, 302.0],
    [1414.0, 2112.0],
    [318.0, 2048.0]
  ]
}
```

Run:

```bash
uv run optcg-material rectify <session-root> --manual-quads ./manual-quads.json
```

### 7. Residual registration

```bash
uv run optcg-material register <session-root>
```

The first albedo frame becomes the reference. SIFT features are matched with a ratio test and a robust MAGSAC homography. The pipeline records matches, inliers, inlier ratio, and median reprojection error.

For heavily reflective cards, use a reviewed stable-region mask that excludes changing foil areas:

```bash
uv run optcg-material register <session-root> --stable-mask ./stable-ink-mask.png
```

## Current implementation boundary

This milestone produces trustworthy canonical image stacks. It does not yet derive foil, metallic, gloss, texture, suppression, or directional maps. Those stages depend on registered captures and are tracked by issues #4 and #5.
