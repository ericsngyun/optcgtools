# Upstream audit

Pinned source: `simeydotme/pokemon-cards-css@acb1197633e749a1fba4412231db2f6581586d00`

## Files studied

- `src/lib/components/Card.svelte`
- `src/lib/components/CardProxy.svelte`
- `public/css/cards.css`
- `public/css/cards/base.css`
- `public/css/cards/v-full-art.css`
- the repository package and license configuration

## Preserved engineering concepts

- normalized pointer coordinates;
- spring-smoothed rotation, glare, and background movement;
- frame-batched pointer updates;
- CSS custom properties as the boundary between behavior and rendering;
- stable layered card DOM;
- independent shine and glare layers;
- optional card-specific foil and mask assets;
- metadata/proxy layer before the renderer;
- finish-specific CSS modules;
- device-motion and reduced-motion considerations;
- GPL-3.0 attribution and source pinning.

## Deliberate OPTCG changes

- finish profiles are explicit physical-material labels rather than Pokémon rarity selectors;
- metallic substrate and micro-etch are separate layers;
- SP is split into multiple families instead of treated as a universal finish;
- no official One Piece card artwork is bundled;
- the calibration UI accepts local card scans and masks;
- the generic mask is only a starting point and is not considered production-accurate.
