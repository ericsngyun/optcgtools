import * as THREE from "three/webgpu";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import { createCardGeometry } from "./cardGeometry.js";
import { assetUri, normalizeResearchProfile } from "./profile.js";
import { composePhysicalMaps, loadTexture } from "./textures.js";

const DEG_TO_RAD = Math.PI / 180;

const DEFAULT_STATE = Object.freeze({
  tiltXDeg: -6,
  tiltYDeg: 12,
  lightAzimuthDeg: 32,
  lightElevationDeg: 38,
  lightDistance: 3.2,
  exposure: 1.15,
  channels: {
    albedo: true,
    foil: true,
    metallic: true,
    clearcoat: true,
    texture: true,
    anisotropy: true
  }
});

function disposeMaterial(material) {
  if (!material) return;
  material.dispose();
}

function disposeTexture(texture) {
  texture?.dispose?.();
}

function cloneState(state = {}) {
  return {
    ...DEFAULT_STATE,
    ...state,
    channels: { ...DEFAULT_STATE.channels, ...(state.channels ?? {}) }
  };
}

export class ResearchCardRenderer {
  constructor(container, { onStatus, onError } = {}) {
    if (!container) throw new Error("ResearchCardRenderer requires a container element");
    this.container = container;
    this.onStatus = onStatus ?? (() => {});
    this.onError = onError ?? ((error) => console.error(error));
    this.profile = normalizeResearchProfile();
    this.state = cloneState();
    this.disposed = false;
    this.loadGeneration = 0;
    this.profileTextures = [];
    this.composedMaps = null;
    this.resizeObserver = null;
  }

  async init() {
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x09090b);

    this.camera = new THREE.PerspectiveCamera(28, 1, 0.05, 50);
    this.camera.position.set(0, 0.08, 4.25);

    this.renderer = new THREE.WebGPURenderer({
      antialias: true,
      alpha: false,
      samples: 4
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = this.state.exposure;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    await this.renderer.init();

    this.renderer.domElement.className = "research-renderer__canvas";
    this.container.replaceChildren(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = false;
    this.controls.enablePan = false;
    this.controls.minDistance = 2.7;
    this.controls.maxDistance = 7;
    this.controls.target.set(0, 0, 0);
    this.controls.update();

    this.cardGroup = new THREE.Group();
    this.scene.add(this.cardGroup);
    this.createCardMeshes();
    this.createLighting();
    this.createGround();

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.container);
    this.resize();

    this.renderer.setAnimationLoop(() => {
      if (!this.disposed) this.renderer.render(this.scene, this.camera);
    });

    const backendName = this.renderer.backend?.constructor?.name ?? "adaptive backend";
    this.onStatus({ phase: "ready", backend: backendName });
    await this.setProfile(this.profile);
    return this;
  }

  createCardMeshes() {
    const geometry = createCardGeometry();
    this.geometry = geometry;

    this.edgeMaterial = new THREE.MeshPhysicalMaterial({
      color: 0xb7aa87,
      roughness: 0.62,
      metalness: 0.18,
      clearcoat: 0.18,
      clearcoatRoughness: 0.55
    });
    this.frontMaterial = new THREE.MeshPhysicalMaterial({
      color: 0xffffff,
      roughness: 0.5,
      metalness: 0,
      side: THREE.DoubleSide
    });
    this.backMaterial = new THREE.MeshPhysicalMaterial({
      color: 0x201924,
      roughness: 0.56,
      metalness: 0,
      clearcoat: 0.42,
      clearcoatRoughness: 0.34,
      side: THREE.DoubleSide
    });

    this.bodyMesh = new THREE.Mesh(geometry.body, this.edgeMaterial);
    this.frontMesh = new THREE.Mesh(geometry.front, this.frontMaterial);
    this.backMesh = new THREE.Mesh(geometry.back, this.backMaterial);
    this.bodyMesh.castShadow = true;
    this.bodyMesh.receiveShadow = true;
    this.frontMesh.castShadow = true;
    this.frontMesh.receiveShadow = true;
    this.backMesh.castShadow = true;
    this.backMesh.receiveShadow = true;
    this.cardGroup.add(this.bodyMesh, this.frontMesh, this.backMesh);
    this.applyPose();
  }

  createLighting() {
    this.scene.add(new THREE.HemisphereLight(0xf7f3e8, 0x17121e, 1.45));

    const key = new THREE.DirectionalLight(0xfff5db, 2.4);
    key.position.set(-2.1, 2.8, 3.4);
    key.castShadow = true;
    this.scene.add(key);

    this.movingLight = new THREE.PointLight(0xeaf3ff, 32, 12, 1.55);
    this.movingLight.position.set(1.3, 1.4, 2.4);
    this.scene.add(this.movingLight);

    const rim = new THREE.PointLight(0xffb88c, 13, 10, 1.8);
    rim.position.set(-2.4, -1.1, -1.8);
    this.scene.add(rim);
    this.applyLightPose();
  }

  createGround() {
    const material = new THREE.MeshStandardMaterial({
      color: 0x111116,
      roughness: 0.94,
      metalness: 0
    });
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(12, 12), material);
    plane.position.set(0, -1.35, -0.9);
    plane.rotation.x = -Math.PI / 2;
    plane.receiveShadow = true;
    this.scene.add(plane);
    this.ground = plane;
  }

  async setProfile(input) {
    const generation = ++this.loadGeneration;
    const profile = normalizeResearchProfile(input);
    this.onStatus({ phase: "loading", card: profile.card.id });

    try {
      const albedoUri = assetUri(profile.assets.albedo);
      const backUri = assetUri(profile.assets.cardBack, "/img/demo/card-back.svg");
      const normalUri = assetUri(profile.assets.normalMap);
      const assetUris = {
        foilMask: assetUri(profile.assets.foilMask),
        metallicMask: assetUri(profile.assets.metallicMask),
        glossMask: assetUri(profile.assets.glossMask),
        textureMask: assetUri(profile.assets.textureMask),
        suppressionMask: assetUri(profile.assets.suppressionMask),
        directionMap: assetUri(profile.assets.directionMap)
      };

      const [albedoMap, backMap, normalMap, composedMaps] = await Promise.all([
        loadTexture(albedoUri, { color: true }),
        loadTexture(backUri, { color: true }),
        loadTexture(normalUri, { color: false }),
        composePhysicalMaps(assetUris, {
          foilStrength: profile.renderer.foilStrength,
          metallicStrength: profile.renderer.metallicStrength,
          glossStrength: profile.renderer.glossStrength,
          textureStrength: profile.renderer.textureStrength
        })
      ]);

      if (generation !== this.loadGeneration || this.disposed) {
        disposeTexture(albedoMap);
        disposeTexture(backMap);
        disposeTexture(normalMap);
        composedMaps.dispose();
        return;
      }

      this.disposeProfileResources();
      this.profile = profile;
      this.profileTextures = [albedoMap, backMap, normalMap].filter(Boolean);
      this.composedMaps = composedMaps;

      const renderer = profile.renderer;
      const nextFront = new THREE.MeshPhysicalMaterial({
        color: 0xffffff,
        map: albedoMap,
        metalness: 1,
        metalnessMap: composedMaps.metalnessMap,
        roughness: renderer.roughness,
        roughnessMap: composedMaps.roughnessMap,
        clearcoat: renderer.clearcoat,
        clearcoatMap: composedMaps.clearcoatMap,
        clearcoatRoughness: renderer.clearcoatRoughness,
        normalMap,
        normalScale: new THREE.Vector2(renderer.textureStrength, -renderer.textureStrength),
        clearcoatNormalMap: normalMap,
        clearcoatNormalScale: new THREE.Vector2(
          renderer.textureStrength * 0.35,
          -renderer.textureStrength * 0.35
        ),
        iridescence: renderer.iridescence,
        iridescenceMap: composedMaps.iridescenceMap,
        iridescenceIOR: renderer.iridescenceIor,
        iridescenceThicknessRange: [
          renderer.iridescenceThicknessMinNm,
          Math.max(renderer.iridescenceThicknessMinNm, renderer.iridescenceThicknessMaxNm)
        ],
        iridescenceThicknessMap: composedMaps.iridescenceThicknessMap,
        anisotropy: renderer.anisotropy,
        anisotropyMap: composedMaps.anisotropyMap,
        anisotropyRotation: renderer.anisotropyRotationRad,
        side: THREE.DoubleSide
      });
      const nextBack = new THREE.MeshPhysicalMaterial({
        color: 0xffffff,
        map: backMap,
        roughness: 0.54,
        metalness: 0,
        clearcoat: 0.45,
        clearcoatRoughness: 0.32,
        side: THREE.DoubleSide
      });

      disposeMaterial(this.frontMaterial);
      disposeMaterial(this.backMaterial);
      this.frontMaterial = nextFront;
      this.backMaterial = nextBack;
      this.frontMesh.material = this.frontMaterial;
      this.backMesh.material = this.backMaterial;
      this.applyChannels();
      this.onStatus({ phase: "profile-ready", card: profile.card.id });
    } catch (error) {
      if (generation === this.loadGeneration) {
        this.onStatus({ phase: "error", message: error.message });
        this.onError(error);
      }
    }
  }

  setState(partial) {
    this.state = cloneState({
      ...this.state,
      ...partial,
      channels: { ...this.state.channels, ...(partial.channels ?? {}) }
    });
    this.renderer.toneMappingExposure = this.state.exposure;
    this.applyPose();
    this.applyLightPose();
    this.applyChannels();
  }

  setChannel(channel, enabled) {
    this.setState({ channels: { [channel]: Boolean(enabled) } });
  }

  soloChannel(channel) {
    const channels = Object.fromEntries(
      Object.keys(this.state.channels).map((name) => [name, name === channel])
    );
    this.setState({ channels });
  }

  restoreChannels() {
    this.setState({ channels: { ...DEFAULT_STATE.channels } });
  }

  applyChannels() {
    if (!this.frontMaterial || !this.composedMaps) return;
    const channels = this.state.channels;
    const renderer = this.profile.renderer;
    this.frontMaterial.map = channels.albedo ? this.profileTextures[0] ?? null : null;
    this.frontMaterial.color.set(channels.albedo ? 0xffffff : 0x808080);
    this.frontMaterial.metalness = channels.metallic ? 1 : 0;
    this.frontMaterial.metalnessMap = channels.metallic
      ? this.composedMaps.metalnessMap
      : null;
    this.frontMaterial.iridescence = channels.foil ? renderer.iridescence : 0;
    this.frontMaterial.iridescenceMap = channels.foil
      ? this.composedMaps.iridescenceMap
      : null;
    this.frontMaterial.iridescenceThicknessMap = channels.foil
      ? this.composedMaps.iridescenceThicknessMap
      : null;
    this.frontMaterial.clearcoat = channels.clearcoat ? renderer.clearcoat : 0;
    this.frontMaterial.clearcoatMap = channels.clearcoat
      ? this.composedMaps.clearcoatMap
      : null;
    this.frontMaterial.normalMap = channels.texture
      ? this.profileTextures.find((texture) => texture !== this.profileTextures[0] && texture !== this.profileTextures[1]) ?? null
      : null;
    this.frontMaterial.clearcoatNormalMap = this.frontMaterial.normalMap;
    this.frontMaterial.anisotropy = channels.anisotropy ? renderer.anisotropy : 0;
    this.frontMaterial.anisotropyMap = channels.anisotropy
      ? this.composedMaps.anisotropyMap
      : null;
    this.frontMaterial.needsUpdate = true;
  }

  applyPose() {
    if (!this.cardGroup) return;
    this.cardGroup.rotation.x = this.state.tiltXDeg * DEG_TO_RAD;
    this.cardGroup.rotation.y = this.state.tiltYDeg * DEG_TO_RAD;
  }

  applyLightPose() {
    if (!this.movingLight) return;
    const azimuth = this.state.lightAzimuthDeg * DEG_TO_RAD;
    const elevation = this.state.lightElevationDeg * DEG_TO_RAD;
    const radial = Math.cos(elevation) * this.state.lightDistance;
    this.movingLight.position.set(
      Math.sin(azimuth) * radial,
      Math.sin(elevation) * this.state.lightDistance,
      Math.cos(azimuth) * radial
    );
  }

  resize() {
    if (!this.renderer || !this.camera) return;
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  snapshotState() {
    return {
      profile: this.profile,
      renderState: cloneState(this.state),
      camera: {
        position: this.camera.position.toArray(),
        quaternion: this.camera.quaternion.toArray(),
        target: this.controls.target.toArray(),
        fov: this.camera.fov
      },
      backend: this.renderer.backend?.constructor?.name ?? "unknown",
      threeRevision: THREE.REVISION
    };
  }

  async exportPng(filename = `${this.profile.card.id}-research.png`) {
    await this.renderer.renderAsync(this.scene, this.camera);
    const blob = await new Promise((resolve, reject) => {
      this.renderer.domElement.toBlob(
        (value) => (value ? resolve(value) : reject(new Error("Canvas export failed"))),
        "image/png"
      );
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  disposeProfileResources() {
    for (const texture of this.profileTextures) disposeTexture(texture);
    this.profileTextures = [];
    this.composedMaps?.dispose?.();
    this.composedMaps = null;
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.loadGeneration += 1;
    this.resizeObserver?.disconnect();
    this.controls?.dispose();
    this.renderer?.setAnimationLoop(null);
    this.disposeProfileResources();
    disposeMaterial(this.frontMaterial);
    disposeMaterial(this.backMaterial);
    disposeMaterial(this.edgeMaterial);
    this.geometry?.front?.dispose();
    this.geometry?.back?.dispose();
    this.geometry?.body?.dispose();
    this.ground?.geometry?.dispose();
    disposeMaterial(this.ground?.material);
    this.renderer?.dispose();
    this.container.replaceChildren();
  }
}

export { DEFAULT_STATE as DEFAULT_RESEARCH_STATE };
