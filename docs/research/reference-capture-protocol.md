# Physical card reference capture protocol

The goal is to recover stable artwork, foil occupancy, texture/relief, clear-coat glare, and directional color travel from authenticated physical cards.

Static marketplace photographs are useful for classification, but they are not sufficient for final shader fitting because lighting, white balance, camera processing, sleeves, and viewing angle are uncontrolled.

## Minimum equipment

- authenticated raw card, removed from sleeve only when safe;
- modern phone or camera capable of locked exposure, focus, and white balance;
- rigid overhead mount or tripod;
- diffuse neutral light source;
- small hard/raking light source;
- black, mid-gray, and white nonreflective backgrounds;
- color checker or neutral gray card;
- optional linear polarizing film for light and circular/linear polarizer for lens;
- optional turntable or printed angle jig.

## Required capture sets

### A. Stable albedo capture

Purpose: obtain the card artwork with minimum foil/glare contamination.

- camera square to card;
- diffuse lights at symmetric angles;
- lock focus, exposure, ISO, shutter, and white balance;
- capture RAW when possible;
- use cross-polarization if available;
- include gray reference in the first frame;
- capture front and back.

Output: `albedo.png`.

### B. Tilt sweep

Purpose: measure angle-dependent hue and brightness.

- keep camera and light fixed;
- rotate the card from approximately -30° to +30° in 2° to 5° increments around the vertical axis;
- repeat around the horizontal axis;
- avoid automatic exposure or white-balance changes;
- record at least one continuous 4K/60 video sweep as well as stills.

Outputs:

- `tilt-x/*.png`
- `tilt-y/*.png`
- `tilt-x.mp4`
- `tilt-y.mp4`

### C. Moving-light sweep

Purpose: separate surface response from perspective changes.

- keep card and camera fixed;
- move one compact light along a known arc;
- capture at regular angle intervals;
- repeat with a larger diffuse light.

Outputs:

- `light-hard/*.png`
- `light-soft/*.png`

### D. Raking-light texture capture

Purpose: reveal embossing, etching, stamped linework, and surface relief.

- place a hard light very low to the card plane;
- capture from left, right, top, and bottom;
- keep exposure low enough to preserve highlight shape;
- repeat with the card rotated 90°.

Outputs:

- `rake-left.png`
- `rake-right.png`
- `rake-top.png`
- `rake-bottom.png`

### E. Macro details

Purpose: identify texture scale and whether motifs are printed, metallic, embossed, or only optical.

Capture macro crops of:

- character edge;
- manga panel/background;
- title/name plate;
- cost and power numbers;
- rarity mark/card number;
- border corners;
- any repeated texture motif.

## Capture rules

- no sleeve, top loader, slab, or protective film in calibration captures unless the website is intentionally simulating that enclosure;
- do not use portrait mode, HDR stacking, beauty filters, or automatic scene modes;
- keep camera processing consistent across the entire set;
- record camera model, lens, distance, light type, color temperature, and card language/print run;
- photograph both English and Japanese copies when comparing print variants;
- never infer texture scale from a resized marketplace thumbnail.

## Frame registration

All frames should be warped to a canonical card rectangle before analysis.

Suggested pipeline:

1. detect the four card corners;
2. estimate a projective transform;
3. warp each frame to a fixed 718×1000 or larger working canvas;
4. align residual movement using feature matching constrained to nonreflective printed regions;
5. crop to the same physical card boundary.

## Derived maps

### Foil activity map

For every pixel across the registered tilt/light sequence, measure:

- luminance variance;
- chroma variance;
- maximum highlight strength;
- hue range traveled.

High variance indicates angle-dependent foil or specular response. Separate broad low-frequency changes from fine texture response.

### Character-protection / ink suppression mask

Regions that remain chromatically stable while neighboring background areas shift should receive lower diffraction intensity. Dense black ink usually needs strong suppression rather than additive rainbow.

### Metallic map

Identify regions with strong brightness change but limited hue travel. These are candidates for neutral silver or warm-gold metallic response.

### Diffraction direction map

For each region, estimate the card/light angle producing maximum response. Encode dominant direction as a two-channel vector or angle texture when CSS gradients are insufficient.

### Height/normal map

Use opposing raking-light captures to estimate local surface orientation. Manual cleanup is expected around printed edges and dark artwork.

### Clear-coat map

Use the broad soft-light sweep to identify laminate glare independent of small-scale texture and rainbow diffraction.

## Dataset structure

```text
references/
  <card-id>/
    metadata.json
    source-notes.md
    raw/
      albedo/
      tilt-x/
      tilt-y/
      light-hard/
      light-soft/
      rake/
      macro/
    processed/
      albedo.png
      foil-mask.png
      metallic-mask.png
      gloss-mask.png
      normal-map.png
      direction-map.png
      region-mask.png
```

Do not commit copyrighted official card scans or third-party marketplace photos to a public repository without permission. Keep raw reference media in a private storage bucket or a private repository. Public code should contain synthetic fixtures, derived nonreconstructive maps where legally appropriate, and source metadata.

## Acceptance test

A finish is `capture-validated` only when:

- the virtual card and real card are shown at matching angles;
- highlight position and direction agree across at least two axes;
- rainbow hue order and bandwidth agree;
- character/background masking agrees;
- texture scale remains plausible at desktop and mobile sizes;
- the effect remains convincing under both dark and light UI backgrounds.
