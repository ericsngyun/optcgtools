# OPTCG Cards CSS — Holo Material Lab

A Svelte/Vite research environment for building physically plausible One Piece Card Game holofoil effects for GenkiStuff.

This repository is a GPL-3.0 derivative lab based on Simon Goellner's [`pokemon-cards-css`](https://github.com/simeydotme/pokemon-cards-css). The original project is preserved as a git submodule pinned to commit `acb1197633e749a1fba4412231db2f6581586d00`.

## Why this exists

The upstream interaction architecture is broadly reusable, but its CSS profiles are tuned to Pokémon Sword & Shield card finishes. This project retains the pointer/spring/CSS-variable model and develops independent OPTCG material profiles for:

- SP etched metallic cards;
- SP rainbow-field cards;
- alternate-art coated foil;
- later: gold anniversary and manga-rare finishes.

## Run

```bash
npm install
npm run dev
```

Then open the local Vite URL, upload a card scan, and optionally upload a grayscale foil mask.

## Initialize the pinned upstream source

```bash
git submodule update --init --recursive
```

## Structure

```text
src/lib/components/CardProxy.svelte treatment metadata and asset normalization
src/lib/components/HoloCard.svelte   pointer, spring, tilt, and CSS-variable engine
public/css/cards/base.css            stable 3D card layer stack
public/css/cards/one-piece-sp.css    SP material families
public/css/cards/one-piece-alt-art.css
public/img/masks/                     generic and card-specific masks
docs/engineering-notes.md            upstream analysis and adaptation rationale
docs/optcg-material-model.md         reference-capture and validation protocol
upstream/pokemon-cards-css/           pinned original project submodule
```

## Adding a real card

Do not commit third-party marketplace photographs. Add a scan or licensed product image you are permitted to use, then create a card-specific grayscale mask with the same dimensions.

```svelte
<HoloCard
  image="/img/cards/op01-078-sp.webp"
  mask="/img/masks/op01-078-sp-mask.webp"
  finish="sp-etched"
/>
```

## Material design rule

The shader should match the physical printing process, not maximize visual spectacle. Keep clear-coat glare, foil diffraction, metallic substrate, and embossed texture independently tunable.

## License

GPL-3.0. See `LICENSE` and the upstream attribution.
