# First benchmark — capture checklist

For the human operator photographing the Stage 1 benchmark card (standard rare
holo or basic SR foil). Task packet:
`docs/agent-ops/task-packets/first-benchmark-stage1.json`. Commands:
`first-benchmark-command-sheet.md`.

All files go to **private storage**, never into this repository:

```text
~/GenkiStuff/optcg-reference-lab/<session-id>/incoming/
```

Suggested `<session-id>`: `<set>-<num>-<name>-<lang>-001`, e.g.
`op05-119-luffy-en-001` (lowercase, digits, dots/dashes only).

## Camera settings (all sequences)

| Setting | Requirement |
| --- | --- |
| Camera position | Fixed on tripod/stand for the whole session |
| Card center | Fixed; card pivots around its center for tilts |
| Focus | Locked (manual or AF-lock) before the first frame |
| Exposure | Locked; no auto compensation between frames |
| White balance | Locked to one value; record it |
| HDR | Off |
| Portrait/bokeh mode | Off |
| Beauty/enhancement filters | Off |
| Format | Highest-quality JPEG or HEIC→PNG export; keep originals unedited |
| Background | Stable, matte, neutral (gray/black); no patterned surface |

**Minimum resolution: the card must occupy at least 1200×1600 px** in every
frame (quality gate rejects smaller). Fill the frame with the card plus a
small margin; keep all four corners visible in every non-macro frame.

Card handling: remove sleeve if safe. If a sleeve or slab must stay, note it
— it will be recorded in the session notes and limits gloss measurement.

## Required capture set

| Sequence | Count | Description | Filename pattern |
| --- | --- | --- | --- |
| Albedo | 1 | Card flat, even diffuse light, no visible highlight | `albedo.png` |
| Tilt X | 7 | Rotate card about its **vertical** axis: −30°, −20°, −10°, 0°, +10°, +20°, +30°; light and camera fixed | `tilt-x-m30.png` … `tilt-x-p30.png` |
| Tilt Y | 7 | Rotate about the **horizontal** axis, same angles | `tilt-y-m30.png` … `tilt-y-p30.png` |
| Hard light | 7 | Card flat; move a small hard source (bare LED/flashlight) through 7 positions in an arc left→right; record each position | `light-hard-01.png` … `light-hard-07.png` |
| Soft light | 3 | Same, 3 positions with a diffused source (softbox, paper diffuser) | `light-soft-01.png` … `light-soft-03.png` |
| Rake | 4 | Very low-angle light from left, right, top, bottom to reveal embossing | `rake-left.png`, `rake-right.png`, `rake-top.png`, `rake-bottom.png` |
| Macro | 4 | Close-ups: title plate, character face, one foil field, one border/icon region | `macro-title.png`, `macro-face.png`, `macro-foil.png`, `macro-border.png` |
| Back (optional but recommended) | 1 | Card back, diffuse light | `back.png` |

Approved tilt **videos** (slow continuous ±30° sweep, locked settings) may
replace the 7-frame tilt stills — ingest with `--kind tilt-x-video` /
`tilt-y-video`. Stills are preferred for the first benchmark.

For every light frame, record in a note (paper or text file kept privately):
light type, approximate azimuth (clock position), elevation, and distance.

## Acceptable vs unacceptable

Acceptable: minor hand-tilt inaccuracy (±3°); slight framing drift if all
corners stay visible; visible foil highlights (that is the point) as long as
they do not white-clip entire regions.

Unacceptable — reshoot the frame if:

- any blur (quality gate rejects Laplacian variance < 70 — practically: zoom
  to 100%, title text must be crisp);
- exposure visibly shifts between frames of one sequence (gate rejects mean
  luminance drift > 0.08 within a group);
- more than ~3% of the card is blown white or ~8% crushed black
  (`bright/dark clip` gates);
- a corner leaves the frame or is covered by fingers;
- the card moved off its center mark between frames;
- HDR/auto-enhance turned itself back on (check after any phone lock);
- reflections of the operator/phone appear on the card face.

## Reshoot conditions after ingestion

`optcg-material quality` prints a per-frame table. Any `accepted: no` row
lists its reasons — reshoot those frames and ingest the replacements as new
files (never edit or overwrite an ingested file; the manifest is append-only).
If a whole sequence fails group-exposure drift, reshoot the sequence with
exposure re-locked.

## Authenticity and rights (human-only)

Only a named human records authentication (`verify-auth`) after physically
inspecting the card, and rights (`set-rights`). Keep authentication evidence
(purchase records, inspection notes) in private storage — never in the
repository. No agent may perform either step.
