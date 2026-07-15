# Primary research sources

This list records primary papers and official specifications guiding the material pipeline. Inclusion does not mean the method should be copied wholesale; each technique must be evaluated against the constrained flat-card domain.

## Multi-view and inverse rendering

- MAIR++ — https://arxiv.org/abs/2408.06707
- IRIS — https://arxiv.org/abs/2401.12977
- MVInverse — https://arxiv.org/abs/2512.21003
- Dynamic Inverse Rendering for Enhanced Material-Lighting Decomposition — https://arxiv.org/abs/2607.09329
- Differentiable Inverse Rendering with Interpretable Basis BRDFs — https://arxiv.org/abs/2411.17994
- RGS-DR: Reflective Gaussian Surfels with Deferred Rendering for Shiny Objects — https://arxiv.org/abs/2504.18468
- MERLiN — https://arxiv.org/abs/2409.00674

## Segmentation

- SAM 2 paper — https://arxiv.org/abs/2408.00714
- SAM 2 implementation — https://github.com/facebookresearch/sam2

## Spectral and iridescent appearance

- Practical and Accurate Reconstruction of an Illuminant's Spectral Power Distribution — https://arxiv.org/abs/2410.22679
- Khronos glTF iridescence — https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_materials_iridescence
- Khronos glTF anisotropy — https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_materials_anisotropy

## Upstream browser architecture

- pokemon-cards-css — https://github.com/simeydotme/pokemon-cards-css
- pinned commit — `acb1197633e749a1fba4412231db2f6581586d00`

## Evaluation rule

Prefer controlled measurement, interpretable outputs, and reproducible fitting. General-purpose neural inverse-rendering results may provide useful initialization, but the production artifact must remain reviewable at the level of card region, material channel, source capture, and renderer parameter.
