import * as THREE from "three/webgpu";

export const CARD_WIDTH = 1.436;
export const CARD_HEIGHT = 2;
export const CARD_DEPTH = 0.018;
export const CARD_RADIUS = 0.055;

function roundedRectangleShape(width, height, radius) {
  const halfWidth = width / 2;
  const halfHeight = height / 2;
  const shape = new THREE.Shape();
  shape.moveTo(-halfWidth + radius, -halfHeight);
  shape.lineTo(halfWidth - radius, -halfHeight);
  shape.quadraticCurveTo(halfWidth, -halfHeight, halfWidth, -halfHeight + radius);
  shape.lineTo(halfWidth, halfHeight - radius);
  shape.quadraticCurveTo(halfWidth, halfHeight, halfWidth - radius, halfHeight);
  shape.lineTo(-halfWidth + radius, halfHeight);
  shape.quadraticCurveTo(-halfWidth, halfHeight, -halfWidth, halfHeight - radius);
  shape.lineTo(-halfWidth, -halfHeight + radius);
  shape.quadraticCurveTo(-halfWidth, -halfHeight, -halfWidth + radius, -halfHeight);
  return shape;
}

function normalizePlaneUvs(geometry, width, height, flipX = false) {
  const positions = geometry.attributes.position;
  const uv = geometry.attributes.uv;
  for (let index = 0; index < positions.count; index += 1) {
    const normalizedX = positions.getX(index) / width + 0.5;
    const normalizedY = positions.getY(index) / height + 0.5;
    uv.setXY(index, flipX ? 1 - normalizedX : normalizedX, normalizedY);
  }
  uv.needsUpdate = true;
  return geometry;
}

export function createCardGeometry({
  width = CARD_WIDTH,
  height = CARD_HEIGHT,
  depth = CARD_DEPTH,
  radius = CARD_RADIUS
} = {}) {
  const shape = roundedRectangleShape(width, height, radius);
  const body = new THREE.ExtrudeGeometry(shape, {
    depth,
    steps: 1,
    curveSegments: 18,
    bevelEnabled: true,
    bevelSegments: 3,
    bevelSize: Math.min(depth * 0.42, radius * 0.18),
    bevelThickness: depth * 0.22
  });
  body.translate(0, 0, -depth / 2);
  body.computeVertexNormals();

  const front = normalizePlaneUvs(new THREE.ShapeGeometry(shape, 18), width, height, false);
  front.translate(0, 0, depth / 2 + 0.0012);
  front.computeVertexNormals();

  const back = normalizePlaneUvs(new THREE.ShapeGeometry(shape, 18), width, height, true);
  back.rotateY(Math.PI);
  back.translate(0, 0, -depth / 2 - 0.0012);
  back.computeVertexNormals();

  return { body, front, back, width, height, depth, radius };
}
