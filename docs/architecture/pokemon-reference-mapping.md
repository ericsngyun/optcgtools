# Mapping pokemon-cards-css into the OPTCG material system

## Upstream strengths to preserve

The linked Pokémon project is valuable because it solves the browser-interaction and compositing problem cleanly:

1. pointer and touch coordinates are normalized against the card bounds;
2. spring stores smooth rotation, pointer, and background movement;
3. the interaction component emits CSS custom properties rather than hard-coding finish logic;
4. card markup remains stable while rarity-specific CSS changes the material response;
5. the proxy layer resolves card metadata, foil assets, masks, and finish selection before rendering;
6. separate shine and glare layers allow foil movement and surface glare to behave differently;
7. masks can isolate reflective treatment from stable printed artwork.

Pinned upstream commit: `acb1197633e749a1fba4412231db2f6581586d00`.

## Upstream assumptions that do not generalize

### Pokémon rarity routing

The proxy infers finish assets from Pokémon-specific fields such as set, number, subtype, gallery status, shiny status, promo status, and rarity strings. OPTCG requires a material-family classifier and print-variant metadata instead.

### One material mask

The upstream renderer can apply one mask to several shine layers. High-rarity OPTCG cards need separate foil, metallic, texture, gloss, and suppression channels.

### Preset texture reuse

Pokémon preset textures such as sunpillar, secret-rare etching, rainbow gradients, and cosmos-style patterns are calibrated to Pokémon products. They are useful compositing references but are not evidence for One Piece print construction.

### Rarity equals material

An OPTCG SP label can cover gold ornamental, manga-scene, and broad color-field constructions. Manga, alt-art, leader-parallel, SR, and Treasure Rare labels also require subfamilies.

## Direct architectural mapping

| pokemon-cards-css concept | OPTCG equivalent |
| --- | --- |
| `Card.svelte` interaction engine | `HoloCard.svelte` interaction engine |
| CSS pointer/rotation variables | same variables, preserved |
| `CardProxy.svelte` rarity resolution | profile-manifest resolution |
| rarity CSS modules | material-family CSS/WebGL modules |
| `foil` asset | measured/approved albedo-adjacent foil asset when required |
| single `mask` | foil, metallic, gloss, texture, suppression, region masks |
| shine layer | diffraction/iridescence lobe |
| glare layer | clearcoat/specular lobe |
| etched presets | card-specific normal/texture maps |
| showcase mode | research and product-detail quality tiers |

## Compatibility policy

The OPTCG renderer keeps a legacy `mask` property so synthetic fixtures and simple cards continue to work. Production profiles should supply independent channels:

```js
{
  foilMask,
  metallicMask,
  glossMask,
  textureMask,
  normalMap,
  directionMap
}
```

CSS uses the four browser-compatible masks directly. Normal and direction maps are passed through the same profile boundary for the WebGL/WebGPU renderer.

## Render-layer interpretation

Current DOM classes remain intentionally compatible with the upstream compositing model:

- `.card__foil-base` → metallic response;
- `.card__shine` → foil/diffraction response;
- `.card__etch` → texture/relief approximation;
- `.card__glare` → gloss/clearcoat response.

This is an incremental migration path. The research renderer may use more explicit names internally, but profile semantics must remain stable.

## Extraction boundary

The upstream project hand-selects or derives foil and mask assets. The frontier OPTCG system automates the first pass from physical reference sequences, then requires human review. The automation must never bypass the profile boundary: extraction outputs maps and confidence; renderers consume approved maps and parameters.

## What “exactly using the repo as reference” means

- preserve the interaction architecture and layered-compositing concepts;
- retain source pinning and GPL attribution;
- compare our implementation against the upstream component and CSS organization;
- do not pretend Pokémon textures are correct for OPTCG;
- do not copy official Pokémon or One Piece card art into public fixtures;
- build OPTCG-specific extraction, taxonomy, masks, profiles, and physical validation.
