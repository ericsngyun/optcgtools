# OPTCG finish taxonomy v0

Status: provisional, based on real-card photographs and marketplace reference galleries. This taxonomy must be validated against controlled captures of authenticated physical cards before any preset is marked production-accurate.

## Core conclusion

`SP`, `manga`, `parallel`, and `alternate art` are collection/rarity labels, not sufficient material definitions. Cards sharing the same label can use visibly different foil geometry, texture density, masking, metallic response, and clear-coat behavior.

The renderer must classify cards by observed material construction, not only by rarity.

## Material channels

Every finish should be decomposed into independent channels:

1. **Albedo** — the stable printed artwork.
2. **Foil occupancy** — where angle-dependent color or brightness is allowed.
3. **Metallic occupancy** — where neutral or gold/silver mirror response is allowed.
4. **Emboss/etch height** — high-frequency surface relief or line texture.
5. **Clear-coat/gloss** — broad white glare from the laminate.
6. **Diffraction direction** — dominant direction or field controlling rainbow travel.
7. **Intensity groups** — separate strengths for background, character, frame, text, icons, and title plate.

A single grayscale mask is insufficient for high-fidelity cards.

## Observed finish families

### MANGA-PRISMATIC-PANEL

Representative references:

- Shanks OP01-120 manga parallel
- Sabo OP13-120 manga parallel

Observed behavior:

- large manga-panel regions exhibit broad cyan/green/magenta travel;
- character foreground remains substantially more stable than the panel field;
- black inks suppress the rainbow response rather than becoming uniformly luminous;
- power/cost numerals and selected border elements can show a separate reflective response;
- the effect is spatially masked by the composition, not a full-card rainbow overlay.

Implementation implications:

- background/panel foil mask;
- character-protection mask;
- separate stat/icon metallic mask;
- low-frequency prismatic field with restrained saturation;
- broad clear-coat glare independent from the prismatic layer.

### MANGA-GOLD-METALLIC

Representative target:

- Gol D. Roger gold manga and later gold-forward manga treatments.

Expected distinction:

- gold or warm metallic substrate dominates;
- rainbow response is secondary and localized;
- linework and ornamental regions require a dedicated metallic/relief channel;
- cannot reuse the standard manga-prismatic preset with a yellow tint.

This family remains unvalidated until controlled multi-angle references are captured.

### SP-GOLD-ORNAMENTAL

Representative references:

- Monkey.D.Luffy OP05-119 / OP11 3rd-anniversary gold SP
- Marshall.D.Teach OP09-093 3rd-anniversary gold SP

Observed behavior:

- dense gold linework and ornamental geometry catch light as a distinct surface layer;
- selected fills show strong iridescent color travel beneath or between gold outlines;
- the title plate/frame uses a more stable warm metallic response;
- microtexture is composition-specific rather than a uniform diagonal grain;
- the character and decorative field do not share one identical reflectance response.

Implementation implications:

- gold-line metallic mask;
- color-field diffraction mask;
- title-plate metallic mask;
- texture/height map derived from the actual ornamental linework;
- separate warm specular and rainbow diffraction lobes.

### SP-MANGA-SCENE

Representative references:

- Roronoa Zoro OP12 SP manga-scene treatment
- anniversary manga-style SP cards

Observed behavior:

- manga line art remains readable while white/gray regions receive broad rainbow patches;
- black title plates and dense ink regions suppress most prismatic energy;
- foil response is larger-scale and patch-like, not a fine repeating rainbow stripe;
- selected gold/bronze text elements require a separate material response.

Implementation implications:

- paper/panel foil mask;
- black-ink suppression mask;
- title plate metallic mask;
- broad low-frequency diffraction field;
- minimal synthetic micro-etch unless real relief is visible.

### SP-COLOR-FIELD

Representative target:

- earlier SP reprints with saturated or monochrome character/background fields.

Likely behavior:

- large colored background field with directional or radial foil travel;
- character, symbols, and text may have different masking strengths;
- some cards include repeated motifs or line textures that should be extracted from the actual card.

This family needs a dedicated physical reference set before parameter lock.

### ALT-ART-COATED

Representative target:

- alternate arts whose dominant cue is laminate glare plus restrained foil.

Observed/expected behavior:

- broad clear-coat highlight is more important than rainbow intensity;
- foil may be present across much of the art but is visually restrained by printed ink;
- should not receive a strong generic prismatic overlay.

### ALT-ART-TEXTURED

Representative target:

- alternate arts with visible background etching, repeating motifs, border relief, or character-outline texture.

Implementation implications:

- card-specific texture/height map is mandatory;
- background and character masks must be separate;
- the current generic `alt-art` preset should be split into coated and textured families.

### LEADER-PARALLEL-TEXTURED

Leader parallels frequently require their own family because the full-card frame, life badge, leader label, and character art can have different reflective groups. Do not treat them as ordinary character alternate arts.

### TREASURE-RARE

The official card database uses a distinct `TR` rarity label. Treasure Rare should remain an independent research family rather than inheriting SP or alt-art settings.

## Initial reference sources

These are useful visual references, not authoritative manufacturing specifications:

- Official card list: https://en.onepiece-cardgame.com/cardlist/
- Luffy gold SP reference: https://www.ebay.com/itm/156763908931
- Teach gold SP reference: https://paypayfleamarket.yahoo.co.jp/item/z446544586
- Sabo manga reference: https://www.ebay.com/itm/388990214588
- Shanks manga reference: https://magi.camp/items/1922013436

Do not copy marketplace photographs into the repository. Store only source URLs, observations, user-owned captures, or assets for which GenkiStuff has permission.

## Confidence levels

Each production preset must carry one of:

- `hypothesis` — inferred from static photos;
- `photo-validated` — confirmed across multiple unrelated real-card photo sets;
- `capture-validated` — fitted against controlled multi-angle captures of an authenticated card;
- `production-validated` — reviewed side-by-side on target devices and approved for GenkiStuff.
