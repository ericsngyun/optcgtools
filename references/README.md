# Physical reference datasets

Raw authenticated-card captures are intentionally not stored in this public repository.

Use the structure below in approved private object storage or a private dataset repository:

```text
references/
  <card-id>-<print-variant>/
    metadata.json
    rights.json
    source-notes.md
    raw/
      albedo/
      tilt-x/
      tilt-y/
      light-hard/
      light-soft/
      rake/
      macro/
    registered/
    processed/
      albedo.png
      foil-mask.png
      metallic-mask.png
      gloss-mask.png
      texture-mask.png
      suppression-mask.png
      normal-map.png
      direction-map.png
      region-mask.png
    profiles/
      card-material-profile.json
    review/
      decisions.jsonl
      comparison-renders/
      error-maps/
```

Rules:

- use authenticated cards for capture-validated profiles;
- record language, set, print run when known, camera, lens, lighting, and color-management details;
- hash original captures and derived artifacts;
- never upload marketplace images as training or production assets without permission;
- marketplace references may be recorded as URLs and observations only;
- every published profile must validate against `schemas/card-material-profile.schema.json`;
- keep model-generated masks reviewable and reversible;
- retain the exact pipeline commit and model versions for reproducibility.
