# Proposed implementation dependencies

Initial evaluation set:

- Python 3.12;
- OpenCV for rectification and registration;
- NumPy/SciPy/scikit-image for measured map derivation;
- PyTorch for segmentation and learned initialization;
- SAM 2 for promptable video-region proposals;
- FastAPI or equivalent for pipeline/review services;
- Svelte UI for review integration with the current lab;
- Three.js WebGL/WebGPU for the reference renderer and 3D viewer;
- JSON Schema validation;
- glTF-Transform and Khronos validator for GLB generation;
- KTX2/Basis Universal for delivery texture compression.

Dependencies are provisional. Each must be benchmarked for license, reproducibility, deployment fit, and performance before adoption.
