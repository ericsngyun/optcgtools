# Canonical card mesh specification

The canonical mesh is a shallow rounded rectangular solid used by the research renderer and GLB exporter.

## Parameters

- width and height in millimeters;
- thickness in millimeters;
- corner radius;
- bevel width and segments;
- front, back, and edge material groups;
- UV orientation and safe border;
- explicit normals and tangents.

## Coordinate system

- origin at card center;
- +X right across card face;
- +Y up across card face;
- +Z out of front face;
- front UV origin documented and consistent with image-processing canvas;
- back UV orientation explicitly flipped as needed rather than corrected in shader code.

## Constraints

- geometry remains identical across card profiles unless measured physical dimensions differ;
- no exaggerated thickness for visual effect in validation mode;
- any presentation bend is a separate runtime deformation and is disabled for matched-angle evaluation;
- embossing remains in normal/height channels;
- mesh generation is deterministic from a versioned geometry manifest.
