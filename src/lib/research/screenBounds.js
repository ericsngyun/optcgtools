import * as THREE from "three/webgpu";

export function projectCardBounds(researchRenderer, padding = 2) {
  const { camera, cardGroup, geometry, renderer } = researchRenderer;
  if (!camera || !cardGroup || !geometry || !renderer) {
    throw new Error("Research renderer is not initialized");
  }

  cardGroup.updateWorldMatrix(true, false);
  camera.updateMatrixWorld(true);
  const halfWidth = geometry.width / 2;
  const halfHeight = geometry.height / 2;
  const frontZ = geometry.depth / 2 + 0.002;
  const corners = [
    [-halfWidth, -halfHeight, frontZ],
    [halfWidth, -halfHeight, frontZ],
    [halfWidth, halfHeight, frontZ],
    [-halfWidth, halfHeight, frontZ]
  ].map(([x, y, z]) => {
    const point = new THREE.Vector3(x, y, z);
    cardGroup.localToWorld(point);
    return point.project(camera);
  });

  const canvasBounds = renderer.domElement.getBoundingClientRect();
  const xs = corners.map((point) => ((point.x + 1) / 2) * canvasBounds.width);
  const ys = corners.map((point) => ((1 - point.y) / 2) * canvasBounds.height);
  const left = Math.max(0, Math.min(...xs) - padding);
  const top = Math.max(0, Math.min(...ys) - padding);
  const right = Math.min(canvasBounds.width, Math.max(...xs) + padding);
  const bottom = Math.min(canvasBounds.height, Math.max(...ys) + padding);

  return {
    x: left,
    y: top,
    width: Math.max(1, right - left),
    height: Math.max(1, bottom - top)
  };
}
