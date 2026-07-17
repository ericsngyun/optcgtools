# Material-map derivation

## Registered input

All calculations operate on frames rectified to a canonical card canvas with locked exposure and white balance. Keep both linearized RGB and display-ready previews.

## Foil activity

Estimate angle-dependent chromatic response from tilt and hard-light stacks.

Candidate signals:

- temporal luminance variance;
- temporal chroma variance;
- maximum-minus-minimum saturation;
- hue arc length with circular statistics;
- peak-response frame index;
- local response correlation.

Reject or downweight clipped pixels and frames with exposure drift.

## Metallic activity

Metallic candidates show strong directional brightness variation with less hue travel than diffractive regions. Separate warm and neutral metallic groups using calibrated color references and the stable albedo estimate.

## Gloss / clearcoat

Use the soft moving-light sequence. Extract broad, smooth highlights and suppress high-frequency printed texture. The clearcoat map should explain broad white reflection, not rainbow hue travel.

## Ink suppression

Estimate regions where foil-active neighbors vary while the local printed region remains stable. Dense black ink often requires strong suppression. Preserve semantic boundaries to prevent rainbow leakage into type and dark character linework.

## Texture and normal

Use opposing raking-light pairs. Begin with photometric-stereo-style normal estimates, then regularize toward a flat card plane. Preserve high-frequency relief only where observations are consistent across opposing lights.

## Direction and anisotropy

Record the angle of peak response or highlight elongation per pixel/region. For 3D export, encode tangent-space direction in red/green and strength in blue to align with glTF anisotropy conventions. For CSS fallback, cluster directions into a small number of region-level gradient orientations.

## Region mask

Use indexed colors or integer labels for character, background/panel, frame, title plate, stats/icons, black ink, and miscellaneous detail. This enables region-specific fitting and metrics.

## Confidence

Every output map must have either an explicit confidence map or a region-level confidence summary. Confidence should decrease for:

- clipped highlights;
- missing angular coverage;
- poor registration;
- compression artifacts;
- sleeve or slab reflections;
- uncertain semantic boundaries;
- uncalibrated lighting;
- conflicting behavior across frames.

## Cleanup policy

Store three versions:

1. raw measured map;
2. model-regularized proposal;
3. human-approved map.

Never overwrite the raw measurement or silently replace low-confidence areas with visually convenient masks.
