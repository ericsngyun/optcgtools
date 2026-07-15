# Engineering notes: upstream architecture and the OPTCG adaptation

## Upstream architecture

The upstream project separates the illusion into two systems:

1. **Interaction state** in Svelte
   - pointer position is normalized into percentages;
   - pointer position drives tilt, glare origin, background position, and distance from center;
   - Svelte springs smooth all movement;
   - the component writes the result into CSS custom properties.

2. **Material profiles** in CSS
   - a stable DOM stack contains the card image, shine, and glare layers;
   - selectors use card metadata to choose a foil profile;
   - gradients, image textures, masks, blend modes, filters, and pseudo-elements create the finish;
   - card-specific masks constrain foil to printed regions.

The upstream also uses a proxy layer to normalize card metadata and resolve image, foil, and mask assets before rendering the interaction component. This lab keeps all three responsibilities separate: `CardProxy.svelte` maps OPTCG treatment metadata, `HoloCard.svelte` is the interaction engine, and files under `public/css/cards/` are material models.

## What is intentionally changed

Pokémon rarity labels are not reused. OPTCG profiles use explicit material IDs such as `sp-etched`, `sp-rainbow`, and `alt-art`. This prevents game metadata from being confused with the physical finish.

The DOM stack adds two explicit layers:

- `card__foil-base` for metallic substrate response;
- `card__etch` for embossed or printed microtexture.

The original `card__shine` and `card__glare` roles remain conceptually intact.

## Why masks are mandatory for credible SP cards

A full-card rainbow overlay can look attractive while being materially wrong. Real premium cards often combine matte printed ink, metallic foil, line texture, borders, and a clear coating. A grayscale mask gives each region a controlled response.

Recommended mask convention:

- black: matte / no foil;
- dark gray: weak clear-coat response only;
- mid gray: subdued metallic ink;
- light gray: strong foil;
- white: strongest etched or stamped region.

## Performance constraints

- Pointer work is batched through `requestAnimationFrame`.
- Only transform and CSS custom properties change during interaction.
- Effects shut off under `prefers-reduced-motion`.
- The production GenkiStuff integration should pause offscreen cards and reserve the full shader for product-detail or featured-card contexts.
