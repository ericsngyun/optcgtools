# Implementation plan

## Milestone 0 — foundations

- material-profile JSON schema;
- independent CSS material masks;
- private reference dataset contract;
- pinned upstream architecture audit;
- benchmark finish taxonomy.

## Milestone 1 — capture and registration

- capture-session CLI and manifests;
- frame-quality checks;
- card-corner detection and perspective rectification;
- residual multi-frame registration;
- reproducible private dataset storage.

## Milestone 2 — region and material extraction

- promptable semantic-region masks;
- video mask propagation;
- foil, metallic, gloss, suppression, texture, and direction maps;
- confidence and uncertainty outputs;
- manual correction format.

## Milestone 3 — reference renderer and fitting

- WebGL/WebGPU research renderer;
- matched camera/light controls;
- parameter fitting against physical reference frames;
- interpretable material lobes;
- CSS profile compiler.

## Milestone 4 — review workspace

- physical-reference and virtual-render side-by-side view;
- angle synchronization;
- material channel toggles;
- mask painting and region correction;
- heatmaps and metrics;
- approval and provenance audit trail.

## Milestone 5 — 3D assets

- rounded card mesh generator;
- material-profile to glTF converter;
- iridescence, anisotropy, clearcoat, normal, metallic, and roughness channels;
- GLB validation and compression;
- product-detail viewer.

## Milestone 6 — benchmark calibration

Initial benchmark families:

1. standard rare holo;
2. basic SR foil;
3. textured alternate art;
4. manga prismatic panel;
5. gold ornamental SP;
6. manga-scene SP;
7. textured leader parallel;
8. Treasure Rare;
9. gold manga when an authenticated capture is available.

## Milestone 7 — production integration

- asset registry and CDN publication;
- GenkiStuff component package;
- grid/detail/hero capability tiers;
- performance budgets and fallbacks;
- monitoring and visual regression tests;
- approved-card coverage dashboard.

## Exit criteria

The program is successful when a reviewer can select an authenticated reference session, inspect automatically proposed masks, correct them, fit a material profile, compare matched-angle physical and virtual renders, approve the profile, and publish both a lightweight website profile and a validated 3D GLB without manually moving files between systems.
