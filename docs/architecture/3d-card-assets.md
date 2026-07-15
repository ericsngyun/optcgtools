# 3D card asset pipeline

## Goal

Generate compact, portable 3D card assets that preserve card dimensions, edge profile, printed artwork, clearcoat, metallic regions, iridescence, and anisotropic texture while remaining practical for GenkiStuff product pages.

## Geometry

A trading card should not be represented as an infinitely thin plane in the research or hero renderer.

Recommended mesh:

- physical aspect ratio derived from the measured card;
- shallow rounded rectangular solid;
- separate front, back, and edge material groups;
- bevel width calibrated from macro photography;
- optional subtle bend parameter for presentation only, disabled for material validation;
- consistent UVs with front and back occupying independent texture regions;
- explicit normals and tangents.

Do not encode embossed foil as large geometric displacement. Use normal or height maps for surface relief unless macro capture proves a visible silhouette change.

## Material channels

### Front printed layer

- base color / albedo;
- opacity fixed to opaque;
- low or zero metallic value outside measured metallic regions;
- roughness map derived from the clearcoat and ink behavior.

### Metallic layer

Use the metallic occupancy map to blend neutral or warm metal behavior. Gold ornamental linework should not be approximated by tinting the entire card.

### Iridescent layer

Use `KHR_materials_iridescence` where the measured response is acceptably represented by thin-film-style hue travel. Drive intensity with the foil mask and thickness with a spatial thickness texture when useful.

The standardized model is a delivery baseline, not proof that the physical foil is literally manufactured as a thin film. If observed hue order or angular bandwidth cannot be matched, retain a custom research shader and export a documented approximation for glTF.

### Anisotropic layer

Use `KHR_materials_anisotropy` for directional elongated highlights. The direction map should be encoded in tangent space and correlated with the normal map. Explicit mesh tangents are required for stable cross-view behavior.

### Clearcoat

Use a separate clearcoat response for laminate glare. Clearcoat intensity and roughness must be fitted independently from rainbow diffraction.

### Texture and relief

- normal map for small embossing and etched linework;
- optional height map retained as a source artifact;
- no baked rainbow color in the normal map;
- texture amplitude clamped so mobile rendering does not resemble rough sandpaper.

## glTF profile

Target `.glb` output with:

- glTF 2.0 core metallic-roughness material;
- normal texture;
- `KHR_materials_clearcoat`;
- `KHR_materials_iridescence` when applicable;
- `KHR_materials_anisotropy` when applicable;
- KTX2/Basis Universal compressed textures for delivery;
- explicit asset metadata linking to the source material-profile JSON and hashes.

Example metadata contract:

```json
{
  "asset": { "generator": "GenkiStuff Card Material Pipeline" },
  "extras": {
    "cardId": "OP01-120",
    "materialProfile": "profiles/OP01-120.json",
    "confidence": "capture-validated",
    "pipelineCommit": "<git-sha>"
  }
}
```

## Renderer tiers

### Grid tier

- CSS renderer only;
- albedo, compiled foil mask, broad glare;
- no 3D mesh download.

### Detail tier

- CSS or WebGL based on capability;
- independent metallic, foil, gloss, and texture masks;
- lazy-loaded 3D asset after user interaction.

### Hero tier

- WebGL/WebGPU renderer;
- full card mesh;
- normal, roughness, metallic, iridescence, anisotropy, and clearcoat channels;
- environment lighting and controlled key light;
- quality fallback for low-power devices.

### Research tier

- matched camera and light controls;
- reference-frame overlay;
- diagnostic material-channel toggles;
- error heatmaps;
- uncompressed source textures where needed.

## Asset build stages

1. validate material profile and provenance;
2. resolve canonical card dimensions and edge measurements;
3. generate or load the card mesh;
4. pack approved texture channels;
5. construct standardized PBR material;
6. attach custom research-shader metadata if needed;
7. export GLB;
8. run Khronos glTF validation;
9. render turntable and matched-angle snapshots;
10. compare against physical references;
11. compress approved delivery textures;
12. publish versioned asset manifest.

## Quality gates

- no texture stretching at rounded corners;
- front/back orientation correct;
- edge does not expose transparent seams;
- tangent space consistent across exporters and browser renderer;
- iridescence hue order stable under camera orbit;
- clearcoat highlight does not move with the foil texture;
- gold linework retains readable contrast;
- normal-map detail remains subpixel-stable;
- GLB validates and loads without console warnings;
- hero asset meets the agreed mobile memory and frame-time budgets.

## Official material references

- glTF iridescence extension: https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_materials_iridescence
- glTF anisotropy extension: https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_materials_anisotropy
- glTF specification and validator: https://github.com/KhronosGroup/glTF
