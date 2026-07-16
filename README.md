# OPTCG Cards CSS — Holo Material Lab

A Svelte/Vite research environment and Python computer-vision pipeline for building physically plausible One Piece Card Game holofoil effects, reviewable material profiles, and 3D card assets for GenkiStuff.

This repository is a GPL-3.0 derivative lab based on Simon Goellner's [`pokemon-cards-css`](https://github.com/simeydotme/pokemon-cards-css). The original project can be fetched exactly at commit `acb1197633e749a1fba4412231db2f6581586d00`.

## Clone

```bash
git clone --branch holo-lab https://github.com/ericsngyun/optcgtools.git optcg-cards-css
cd optcg-cards-css
```

## Install

Web and renderer tools:

```bash
npm install
npx playwright install chromium
```

Python extraction tools require [`uv`](https://docs.astral.sh/uv/) and Python 3.12:

```bash
uv sync --group dev
```

## Run the web lab

```bash
npm run dev
```

The web lab has two modes:

- **CSS delivery approximation** — preserves the upstream pointer/spring/CSS-variable architecture for lightweight retail surfaces;
- **Physical reference renderer** — uses three.js r185 with adaptive WebGPU/WebGL 2 rendering and independently controlled metalness, clearcoat, iridescence, normal, roughness, and anisotropy channels.

The public runtime is self-contained: its placeholder card, card back, and generic SP mask are committed under `public/img/`.

To fetch the exact upstream engineering reference:

```bash
npm run fetch:upstream
npm run check:source-pin
```

## 1. Authenticated capture ingestion

Initialize a private capture session:

```bash
uv run optcg-material init ./private-references/op01-120-shanks-en-001 \
  --session-id op01-120-shanks-en-001 \
  --card-id OP01-120 \
  --card-name Shanks \
  --set-code OP01 \
  --language EN \
  --operator "GenkiStuff Lab" \
  --rights-owner GenkiStuff
```

Add physical captures. Every file is copied into the session, assigned a BLAKE3 content hash, and written to the immutable manifest:

```bash
uv run optcg-material add ./private-references/op01-120-shanks-en-001 ./captures/albedo.png --kind albedo
uv run optcg-material add ./private-references/op01-120-shanks-en-001 ./captures/tilt-x-minus-30.png --kind tilt-x --angle -30
uv run optcg-material add ./private-references/op01-120-shanks-en-001 ./captures/rake-left.png --kind rake --direction left
```

Record authentication and rights separately from model output:

```bash
uv run optcg-material verify-auth ./private-references/op01-120-shanks-en-001 \
  --method "authenticated inventory intake and physical inspection" \
  --verifier "GenkiStuff reviewer"

uv run optcg-material set-rights ./private-references/op01-120-shanks-en-001 \
  --status owned-capture \
  --public-derivatives-allowed \
  --no-public-albedo-allowed
```

Validate, preflight, rectify, and register:

```bash
uv run optcg-material validate ./private-references/op01-120-shanks-en-001
uv run optcg-material quality ./private-references/op01-120-shanks-en-001
uv run optcg-material rectify ./private-references/op01-120-shanks-en-001
uv run optcg-material register ./private-references/op01-120-shanks-en-001
```

Automatic card-boundary detection fails closed. Ambiguous frames require a reviewed `--manual-quads` JSON file instead of silently accepting a weak homography.

## 2. Semantic-region proposals

The base install validates prompt and review contracts without PyTorch. The optional GPU worker is pinned to Meta SAM 2.1 source commit `2b90b9f5ceec907a1c18123530e92e794ad901a4`.

Install a platform-appropriate official PyTorch build, then:

```bash
SAM2_SKIP_TORCH_CHECK=1 bash scripts/install-sam2.sh
uv run optcg-semantic check-environment \
  --checkpoint /models/sam2.1_hiera_base_plus.pt
```

Validate and execute a reviewed request:

```bash
uv run optcg-semantic validate-request examples/segmentation-request.example.json
uv run optcg-semantic image <session-root> <request.json> \
  --checkpoint /models/sam2.1_hiera_base_plus.pt
```

The worker preserves prompts, model source commit, checkpoint hash, predicted IoU, uncertainty, and low-resolution refinement logits. Manual corrections are immutable replace/union/subtract/intersect events rather than destructive edits.

## 3. Measured material maps

Create an extraction request that references approved semantic masks when available, then:

```bash
uv run optcg-maps validate-request <material-extraction-request.json>
uv run optcg-maps extract <session-root> <material-extraction-request.json>
```

Outputs include:

- registered albedo;
- foil activity proposal;
- low-chroma metallic proposal;
- clearcoat/gloss proposal;
- black-ink suppression proposal;
- texture and normal proposals;
- direction and confidence maps;
- raw float16 measurement arrays;
- hashed extraction manifest.

Semantic masks influence the measured maps as soft priors. They do not replace the physical evidence.

## 4. Physical reference rendering

The physical renderer maps approved or proposed channels into a standards-based three.js r185 `MeshPhysicalMaterial` baseline. Use the **Physical reference renderer** tab to:

- load a material-profile JSON;
- lock card and light angles;
- switch between flat validation and rounded 3D presentation;
- solo or disable material channels;
- overlay a matched physical frame or use difference blend;
- export a deterministic render state and PNG.

Example profile:

```text
examples/research-profile.example.json
```

Run browser validation:

```bash
npm run build
npm run test:web
```

## 5. Deterministic render sequences

Start the lab at the URL declared in the request, then export candidate frames:

```bash
npm run dev -- --host 127.0.0.1 --port 4173
npm run render:sequence -- examples/render-sequence.example.json
```

The exporter uses the renderer automation API, records the exact profile/card/light/camera state, exports one PNG and JSON state per frame, and writes a sequence manifest.

## 6. Analysis-by-synthesis evaluation

Compare authenticated registered frames with candidate renders:

```bash
uv run optcg-fit validate-request examples/fit-sequence.example.json
uv run optcg-fit evaluate <session-root> <fit-sequence-request.json>
```

The evaluator reports:

- linear-RGB error;
- gradient error;
- circular hue error;
- highlight-centroid trajectory error;
- exposure error;
- temporal-delta error;
- separately weighted approved semantic-region metrics;
- input and profile hashes.

It does not normalize away incorrect exposure or hide localized foil errors inside whole-card averages.

## Upstream architecture retained

The Pokémon project’s strongest engineering boundaries remain:

- normalized pointer/touch coordinates;
- spring-smoothed 3D movement;
- CSS custom properties between interaction and material styling;
- stable layered card markup;
- separate shine and glare behavior;
- proxy-driven asset and finish resolution.

OPTCG extraction is intentionally more rigorous. `SP`, `manga`, `parallel`, `SR`, and `alt art` are not treated as sufficient material definitions. Authenticated captures are decomposed into reviewable foil, metallic, gloss, texture, suppression, normal, direction, and semantic-region channels.

## Multi-channel CSS usage

The original single `mask` prop remains a fallback. Production profiles should supply independent channels:

```svelte
<HoloCard
  image="/approved/cards/op01-120/albedo.webp"
  foilMask="/approved/cards/op01-120/foil-mask.webp"
  metallicMask="/approved/cards/op01-120/metallic-mask.webp"
  glossMask="/approved/cards/op01-120/gloss-mask.webp"
  textureMask="/approved/cards/op01-120/texture-mask.webp"
  normalMap="/approved/cards/op01-120/normal-map.webp"
  directionMap="/approved/cards/op01-120/direction-map.webp"
  finish="manga-prismatic-panel"
/>
```

The CSS renderer consumes browser-compatible derivatives. Normal and direction maps remain in the shared profile contract for the physical renderer and future GLB exporter.

## Pipeline

```text
authenticated capture
  -> provenance and quality gates
  -> rectification and registration
  -> semantic-region proposals
  -> measured material maps
  -> deterministic physical candidate renders
  -> quantitative matched-sequence evaluation
  -> human review
  -> CSS / WebGL / GLB publication
```

Start with:

- [`docs/architecture/README.md`](docs/architecture/README.md)
- [`docs/architecture/frontier-material-pipeline.md`](docs/architecture/frontier-material-pipeline.md)
- [`docs/architecture/reference-renderer.md`](docs/architecture/reference-renderer.md)
- [`docs/research/reference-capture-protocol.md`](docs/research/reference-capture-protocol.md)
- [`docs/operations/capture-ingestion.md`](docs/operations/capture-ingestion.md)
- [`schemas/capture-session.schema.json`](schemas/capture-session.schema.json)
- [`schemas/card-material-profile.schema.json`](schemas/card-material-profile.schema.json)
- [`references/README.md`](references/README.md)

## Current implementation order

Two evidence lanes exist (ADR-0002): Lane B (authenticated physical capture)
and Lane A (public-reference synthesis, labeled `reference-derived`).

1. capture and provenance (Lane B) — complete;
2. deterministic registration — complete, exercised on real Lane A references;
3. semantic regions — foundation complete (SAM 2.1 pinned; SAM 3.1 challenger
   pinned, checkpoint-gated), pending real GPU/card validation;
4. measured material maps (Lane B) — MVP complete, pending real-card calibration;
5. physical reference renderer — complete;
6. analysis-by-synthesis evaluation — Lane B MVP complete; Lane A
   cross-reference fitting implemented and exercised on real public
   references — the first fits were honestly REJECTED by the acceptance gates
   (insufficient cross-source coherence); no card profile exists yet;
7. review workspace — partial (UI not implemented);
8. CSS compilation — pending;
9. 3D GLB assets — pending;
10. benchmark calibration and GenkiStuff integration — pending.

Current product goal: one internal reference-derived English Perona OP06-093
alternate-art web prototype (Lane A; physical capture NOT required for an
internal prototype). Do not begin broad card-specific shader tuning before a
reviewed evidence bundle exists for the target card.

## Rights boundary

Do not commit third-party marketplace photographs or official card scans without permission. Raw GenkiStuff physical captures belong in approved private storage. Public code may contain synthetic fixtures, source URLs and observations, approved manifests, and legally approved derived assets.

## Material design rule

Match the observed physical card, not maximum visual spectacle. Keep clearcoat glare, foil diffraction, metallic response, embossed texture, and ink suppression independently measurable and tunable.

## License

GPL-3.0. See `LICENSE` and the upstream attribution.
