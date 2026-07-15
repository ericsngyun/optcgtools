# OPTCG Cards CSS — Holo Material Lab

A Svelte/Vite research environment for building physically plausible One Piece Card Game holofoil effects, reviewable material profiles, and 3D card assets for GenkiStuff.

This repository is a GPL-3.0 derivative lab based on Simon Goellner's [`pokemon-cards-css`](https://github.com/simeydotme/pokemon-cards-css). The original project can be fetched exactly at commit `acb1197633e749a1fba4412231db2f6581586d00`.

## Clone and run

```bash
git clone --branch holo-lab https://github.com/ericsngyun/optcgtools.git optcg-cards-css
cd optcg-cards-css
npm install
npm run dev
```

The runtime is self-contained: its placeholder card, card back, and generic SP mask are committed under `public/img/`.

To download the pinned upstream source used for the engineering reference:

```bash
npm run fetch:upstream
npm run check:source-pin
```

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
