import * as THREE from "three/webgpu";

const DEFAULT_RESOLUTION = 1024;

function clamp01(value) {
  return Math.min(Math.max(value, 0), 1);
}

function createCanvas(width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

async function fetchBitmap(uri) {
  const response = await fetch(uri, { credentials: "same-origin" });
  if (!response.ok) throw new Error(`Unable to load texture ${uri}: ${response.status}`);
  return createImageBitmap(await response.blob(), { imageOrientation: "none" });
}

function bitmapPixels(bitmap, width, height) {
  const canvas = createCanvas(width, height);
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(bitmap, 0, 0, width, height);
  return context.getImageData(0, 0, width, height);
}

export async function loadTexture(uri, { color = false, flipY = true } = {}) {
  if (!uri) return null;
  const texture = await new THREE.TextureLoader().loadAsync(uri);
  texture.flipY = flipY;
  texture.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.generateMipmaps = true;
  texture.anisotropy = 8;
  texture.needsUpdate = true;
  return texture;
}

export async function composePhysicalMaps(
  assets,
  {
    width = DEFAULT_RESOLUTION,
    height = Math.round(DEFAULT_RESOLUTION / 0.718),
    foilStrength = 1,
    metallicStrength = 1,
    glossStrength = 1,
    textureStrength = 1
  } = {}
) {
  const entries = Object.entries({
    foil: assets.foilMask,
    metallic: assets.metallicMask,
    gloss: assets.glossMask,
    texture: assets.textureMask,
    suppression: assets.suppressionMask,
    direction: assets.directionMap
  }).filter(([, uri]) => Boolean(uri));

  const loaded = new Map();
  await Promise.all(
    entries.map(async ([key, uri]) => {
      try {
        loaded.set(key, await fetchBitmap(uri));
      } catch (error) {
        console.warn(error);
      }
    })
  );

  const pixels = new Map();
  for (const [key, bitmap] of loaded) pixels.set(key, bitmapPixels(bitmap, width, height));

  const scalar = (name, index, fallback = 0) => {
    const data = pixels.get(name)?.data;
    return data ? data[index] / 255 : fallback;
  };

  const foilCanvas = createCanvas(width, height);
  const metalCanvas = createCanvas(width, height);
  const coatCanvas = createCanvas(width, height);
  const roughnessCanvas = createCanvas(width, height);
  const thicknessCanvas = createCanvas(width, height);
  const anisotropyCanvas = createCanvas(width, height);

  const foilImage = foilCanvas.getContext("2d").createImageData(width, height);
  const metalImage = metalCanvas.getContext("2d").createImageData(width, height);
  const coatImage = coatCanvas.getContext("2d").createImageData(width, height);
  const roughnessImage = roughnessCanvas.getContext("2d").createImageData(width, height);
  const thicknessImage = thicknessCanvas.getContext("2d").createImageData(width, height);
  const anisotropyImage = anisotropyCanvas.getContext("2d").createImageData(width, height);

  for (let pixel = 0; pixel < width * height; pixel += 1) {
    const index = pixel * 4;
    const suppression = scalar("suppression", index, 0);
    const foil = clamp01(scalar("foil", index, 0) * foilStrength * (1 - suppression));
    const metal = clamp01(scalar("metallic", index, 0) * metallicStrength);
    const gloss = clamp01(scalar("gloss", index, 1) * glossStrength);
    const texture = clamp01(scalar("texture", index, 0) * textureStrength);

    const directionData = pixels.get("direction")?.data;
    const directionR = directionData ? directionData[index] : 255;
    const directionG = directionData ? directionData[index + 1] : 128;
    const directionB = directionData ? directionData[index + 2] : Math.round(foil * 255);

    const foilByte = Math.round(foil * 255);
    const metalByte = Math.round(metal * 255);
    const glossByte = Math.round(gloss * 255);
    const roughness = clamp01(0.72 - gloss * 0.55 + texture * 0.24 + metal * 0.08);
    const roughnessByte = Math.round(roughness * 255);
    const thickness = clamp01(0.18 + foil * 0.66 + (directionG / 255) * 0.16);
    const thicknessByte = Math.round(thickness * 255);

    foilImage.data.set([foilByte, foilByte, foilByte, 255], index);
    metalImage.data.set([metalByte, metalByte, metalByte, 255], index);
    coatImage.data.set([glossByte, glossByte, glossByte, 255], index);
    roughnessImage.data.set([roughnessByte, roughnessByte, roughnessByte, 255], index);
    // MeshPhysicalMaterial reads the green channel for iridescence thickness.
    thicknessImage.data.set([0, thicknessByte, 0, 255], index);
    anisotropyImage.data.set(
      [directionR, directionG, Math.round((directionB / 255) * foil * 255), 255],
      index
    );
  }

  foilCanvas.getContext("2d").putImageData(foilImage, 0, 0);
  metalCanvas.getContext("2d").putImageData(metalImage, 0, 0);
  coatCanvas.getContext("2d").putImageData(coatImage, 0, 0);
  roughnessCanvas.getContext("2d").putImageData(roughnessImage, 0, 0);
  thicknessCanvas.getContext("2d").putImageData(thicknessImage, 0, 0);
  anisotropyCanvas.getContext("2d").putImageData(anisotropyImage, 0, 0);

  const makeDataTexture = (canvas) => {
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.NoColorSpace;
    texture.flipY = true;
    texture.minFilter = THREE.LinearMipmapLinearFilter;
    texture.magFilter = THREE.LinearFilter;
    texture.generateMipmaps = true;
    texture.needsUpdate = true;
    return texture;
  };

  return {
    iridescenceMap: makeDataTexture(foilCanvas),
    metalnessMap: makeDataTexture(metalCanvas),
    clearcoatMap: makeDataTexture(coatCanvas),
    roughnessMap: makeDataTexture(roughnessCanvas),
    iridescenceThicknessMap: makeDataTexture(thicknessCanvas),
    anisotropyMap: makeDataTexture(anisotropyCanvas),
    dispose() {
      for (const bitmap of loaded.values()) bitmap.close();
      this.iridescenceMap.dispose();
      this.metalnessMap.dispose();
      this.clearcoatMap.dispose();
      this.roughnessMap.dispose();
      this.iridescenceThicknessMap.dispose();
      this.anisotropyMap.dispose();
    }
  };
}
