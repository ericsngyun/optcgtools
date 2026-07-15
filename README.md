# OPTCG Cards CSS — Holo Material Lab

A Svelte/Vite research environment and Python computer-vision pipeline for building physically plausible One Piece Card Game holofoil effects, reviewable material profiles, and 3D card assets for GenkiStuff.

This repository is a GPL-3.0 derivative lab based on Simon Goellner's [`pokemon-cards-css`](https://github.com/simeydotme/pokemon-cards-css). The original project can be fetched exactly at commit `acb1197633e749a1fba4412231db2f6581586d00`.

## Clone

```bash
git clone --branch holo-lab https://github.com/ericsngyun/optcgtools.git optcg-cards-css
cd optcg-cards-css
```

## Run the web holo lab

```bash
npm install
npm run dev
```

The runtime is self-contained: its placeholder card, card back, and generic SP mask are committed under `public/img/`.

To download the exact upstream source used for the engineering reference:

```bash
npm run fetch:upstream
npm run check:source-pin
```

## Run the authenticated-capture pipeline

Install [`uv`](https://docs.astral.sh/uv/) and use Python 3.12:

```bash
uv sync --group dev
uv run optcg-material --help
```

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

Add authenticated physical captures. Every file is copied into the session, assigned a BLAKE3 content hash, and written to the immutable manifest:

```bash
uv run optcg-material add ./private-references/op01-120-shanks-en-001 ./captures/albedo.png --kind albedo
uv run optcg-material add ./private-references/op01-120-shanks-en-001 ./captures/tilt-x-minus-30.png --kind tilt-x --angle -30
uv run optcg-material add ./private-references/op01-120-shanks-en-001 ./captures/rake-left.png --kind rake --direction left
```

Record human authentication and rights separately from model output:

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

## Architecture rule

The upstream interaction architecture is retained:

- normalized pointer/touch coordinates;
- spring-smoothed 3D movement;
- CSS custom properties as the interaction/material boundary;
- stable layered card markup;
- separate shine and glare behavior;
- proxy-driven asset and finish resolution.

OPTCG material extraction is intentionally more rigorous. `SP`, `manga`, `parallel`, `SR`, and `alt art` are not treated as sufficient material definitions. Authenticated physical captures are decomposed into reviewable foil, metallic, gloss, texture, suppression, normal, direction, and semantic-region channels.

## Multi-channel card usage

The original single `mask` prop still works as a fallback. Production profiles should supply independent channels:

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

The CSS renderer consumes the browser-compatible masks. Normal and direction maps are carried through the same profile contract for the WebGL/WebGPU and 3D renderers.

## Frontier pipeline

```text
authenticated capture
  -> provenance and quality gates
  -> rectification and registration
  -> semantic-region proposals
  -> measured material maps
  -> interpretable material fitting
  -> human review
  -> CSS / WebGL / GLB publication
```

Start with:

- [`docs/architecture/README.md`](docs/architecture/README.md)
- [`docs/architecture/frontier-material-pipeline.md`](docs/architecture/frontier-material-pipeline.md)
- [`docs/research/reference-capture-protocol.md`](docs/research/reference-capture-protocol.md)
- [`schemas/capture-session.schema.json`](schemas/capture-session.schema.json)
- [`schemas/card-material-profile.schema.json`](schemas/card-material-profile.schema.json)
- [`references/README.md`](references/README.md)

## Implementation order

The GitHub backlog is intentionally dependency-ordered:

1. capture and provenance;
2. deterministic registration;
3. semantic regions;
4. measured material maps;
5. research renderer;
6. analysis-by-synthesis fitting;
7. review workspace;
8. CSS compilation;
9. 3D GLB assets;
10. benchmark calibration and GenkiStuff integration.

Do not begin large-scale card-specific shader tuning before capture and registration are working.

## Rights boundary

Do not commit third-party marketplace photographs or official card scans without permission. Raw GenkiStuff physical captures belong in approved private storage. Public code may contain synthetic fixtures, source URLs and observations, approved manifests, and legally approved derived assets.

## Material design rule

Match the observed physical card, not maximum visual spectacle. Keep clearcoat glare, foil diffraction, metallic response, embossed texture, and ink suppression independently measurable and tunable.

## License

GPL-3.0. See `LICENSE` and the upstream attribution.
