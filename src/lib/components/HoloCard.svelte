<script>
  import { spring } from "svelte/motion";
  import { onDestroy, onMount } from "svelte";

  export let image = "/img/demo/optcg-placeholder.svg";
  export let back = "/img/demo/card-back.svg";

  // `mask` remains as a backwards-compatible fallback. Production profiles
  // should provide independent material-channel masks.
  const DEFAULT_MASK = "/img/masks/sp-generic-mask.svg";
  export let mask = DEFAULT_MASK;
  export let foilMask = "";
  export let metallicMask = "";
  export let glossMask = "";
  export let textureMask = "";
  export let suppressionMask = "";
  export let normalMap = "";
  export let directionMap = "";

  export let finish = "sp-etched";
  export let label = "One Piece Card Game holofoil test card";
  export let masked = true;
  export let maxTilt = 12;
  export let glareStrength = 1;
  export let foilStrength = 1;
  export let textureScale = 1;

  // Compiled-profile wiring (scripts/compile-card-profile.mjs output). When
  // `profileId` is set, mask/effect variables come from the compiled
  // stylesheet scope instead of inline fallbacks.
  export let profileId = "";
  export let tier = "";
  export let profileVars = null;
  export let suspendOffscreen = null;
  // Deterministic pose for tests/render harnesses: { x, y, opacity } in
  // pointer percentages; bypasses springs and pointer input entirely.
  export let staticPose = null;

  let card;
  let frame = null;
  let pending = null;
  let reducedMotion = false;
  let interacting = false;
  let suspended = false;
  let intersectionObserver = null;

  const rotation = spring({ x: 0, y: 0 }, { stiffness: 0.09, damping: 0.35 });
  const pointer = spring({ x: 50, y: 50, opacity: 0 }, { stiffness: 0.1, damping: 0.4 });
  const background = spring({ x: 50, y: 50 }, { stiffness: 0.075, damping: 0.35 });

  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
  const map = (value, inMin, inMax, outMin, outMax) =>
    ((value - inMin) * (outMax - outMin)) / (inMax - inMin) + outMin;
  const cssUrl = (value) => (value ? `url("${value}")` : "none");

  function applyInteraction(next) {
    rotation.set(next.rotation);
    pointer.set(next.pointer);
    background.set(next.background);
  }

  function interact(event) {
    if (reducedMotion || suspended || staticPose || !card) return;

    const rect = card.getBoundingClientRect();
    const clientX = event.clientX ?? event.touches?.[0]?.clientX;
    const clientY = event.clientY ?? event.touches?.[0]?.clientY;
    if (typeof clientX !== "number" || typeof clientY !== "number") return;

    const x = clamp(((clientX - rect.left) / rect.width) * 100, 0, 100);
    const y = clamp(((clientY - rect.top) / rect.height) * 100, 0, 100);
    const centerX = x - 50;
    const centerY = y - 50;

    pending = {
      rotation: {
        x: map(centerX, -50, 50, -maxTilt, maxTilt),
        y: map(centerY, -50, 50, maxTilt, -maxTilt)
      },
      pointer: { x, y, opacity: 1 },
      background: {
        x: map(x, 0, 100, 35, 65),
        y: map(y, 0, 100, 32, 68)
      }
    };

    interacting = true;
    if (frame === null) {
      frame = requestAnimationFrame(() => {
        if (pending) applyInteraction(pending);
        pending = null;
        frame = null;
      });
    }
  }

  function reset() {
    interacting = false;
    rotation.set({ x: 0, y: 0 });
    pointer.set({ x: 50, y: 50, opacity: 0 });
    background.set({ x: 50, y: 50 });
  }

  function keyboardTilt(event) {
    if (reducedMotion || suspended || staticPose) return;
    const step = 3;
    const next = { x: $rotation.x, y: $rotation.y };

    if (event.key === "ArrowLeft") next.x -= step;
    else if (event.key === "ArrowRight") next.x += step;
    else if (event.key === "ArrowUp") next.y += step;
    else if (event.key === "ArrowDown") next.y -= step;
    else if (event.key === "Escape") return reset();
    else return;

    event.preventDefault();
    interacting = true;
    rotation.set({
      x: clamp(next.x, -maxTilt, maxTilt),
      y: clamp(next.y, -maxTilt, maxTilt)
    });
    pointer.set({
      x: map(clamp(next.x, -maxTilt, maxTilt), -maxTilt, maxTilt, 0, 100),
      y: map(clamp(next.y, -maxTilt, maxTilt), maxTilt, -maxTilt, 0, 100),
      opacity: 1
    });
  }

  function staticPoseValues(pose, tilt) {
    const x = clamp(Number(pose.x ?? 50), 0, 100);
    const y = clamp(Number(pose.y ?? 50), 0, 100);
    return {
      pointerX: x,
      pointerY: y,
      opacity: clamp(Number(pose.opacity ?? 1), 0, 1),
      rotateX: map(x - 50, -50, 50, -tilt, tilt),
      rotateY: map(y - 50, -50, 50, tilt, -tilt),
      backgroundX: map(x, 0, 100, 35, 65),
      backgroundY: map(y, 0, 100, 32, 68)
    };
  }

  $: usingProfile = Boolean(profileId);

  $: pose = staticPose
    ? staticPoseValues(staticPose, maxTilt)
    : {
        pointerX: $pointer.x,
        pointerY: $pointer.y,
        opacity: $pointer.opacity,
        rotateX: $rotation.x,
        rotateY: $rotation.y,
        backgroundX: $background.x,
        backgroundY: $background.y
      };

  $: distanceFromCenter = clamp(
    Math.sqrt((pose.pointerX - 50) ** 2 + (pose.pointerY - 50) ** 2) / 50,
    0,
    1
  );

  $: resolvedFoilMask = foilMask || mask;
  $: resolvedMetallicMask = metallicMask || mask;
  $: resolvedGlossMask = glossMask || mask;
  $: resolvedTextureMask = textureMask || mask;

  // With a compiled profile, mask and effect variables live in the compiled
  // stylesheet scope; inline declarations would override them, so only emit
  // explicitly-provided values.
  $: maskStyles = usingProfile
    ? [
        mask && mask !== DEFAULT_MASK ? `--mask: ${cssUrl(mask)};` : "",
        foilMask ? `--foil-mask: ${cssUrl(foilMask)};` : "",
        metallicMask ? `--metallic-mask: ${cssUrl(metallicMask)};` : "",
        glossMask ? `--gloss-mask: ${cssUrl(glossMask)};` : "",
        textureMask ? `--texture-mask: ${cssUrl(textureMask)};` : "",
        suppressionMask ? `--suppression-mask: ${cssUrl(suppressionMask)};` : ""
      ]
        .filter(Boolean)
        .join("\n")
    : `
    --glare-strength: ${glareStrength};
    --foil-strength: ${foilStrength};
    --texture-scale: ${textureScale};
    --mask: ${cssUrl(mask)};
    --foil-mask: ${cssUrl(resolvedFoilMask)};
    --metallic-mask: ${cssUrl(resolvedMetallicMask)};
    --gloss-mask: ${cssUrl(resolvedGlossMask)};
    --texture-mask: ${cssUrl(resolvedTextureMask)};
    --suppression-mask: ${cssUrl(suppressionMask)};
    --normal-map: ${cssUrl(normalMap)};
    --direction-map: ${cssUrl(directionMap)};
  `;

  $: profileVarStyles = profileVars
    ? Object.keys(profileVars)
        .sort()
        .map((name) => `${name}: ${profileVars[name]};`)
        .join("\n")
    : "";

  $: dynamicStyles = `
    --pointer-x: ${pose.pointerX}%;
    --pointer-y: ${pose.pointerY}%;
    --pointer-from-center: ${distanceFromCenter};
    --card-opacity: ${pose.opacity};
    --rotate-x: ${pose.rotateX}deg;
    --rotate-y: ${pose.rotateY}deg;
    --background-x: ${pose.backgroundX}%;
    --background-y: ${pose.backgroundY}%;
    ${maskStyles}
    ${profileVarStyles}
  `;

  $: shouldSuspend = suspendOffscreen ?? tier === "grid";

  function observeSuspension() {
    intersectionObserver?.disconnect();
    intersectionObserver = null;
    suspended = false;
    if (!shouldSuspend || !card || typeof IntersectionObserver === "undefined") return;
    intersectionObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        suspended = !entry.isIntersecting;
        if (suspended) reset();
      }
    });
    intersectionObserver.observe(card);
  }

  $: if (card !== undefined) {
    shouldSuspend;
    observeSuspension();
  }

  onMount(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => {
      reducedMotion = query.matches;
      if (reducedMotion) reset();
    };
    sync();
    query.addEventListener?.("change", sync);
    return () => query.removeEventListener?.("change", sync);
  });

  onDestroy(() => {
    if (frame !== null) cancelAnimationFrame(frame);
    intersectionObserver?.disconnect();
  });
</script>

<div
  bind:this={card}
  class:interacting
  class:masked
  class="card interactive"
  data-tcg="one-piece"
  data-finish={finish}
  data-card-profile={profileId || undefined}
  data-card-tier={usingProfile && tier ? tier : undefined}
  data-suspended={suspended ? "true" : undefined}
  style={dynamicStyles}
>
  <div class="card__translater">
    <button
      class="card__rotator"
      aria-label={label}
      on:pointermove={interact}
      on:pointerleave={reset}
      on:touchmove|preventDefault={interact}
      on:touchend={reset}
      on:blur={reset}
      on:keydown={keyboardTilt}
    >
      <img class="card__back" src={back} alt="Generic card back" draggable="false" />
      <div class="card__front">
        <img class="card__image" src={image} alt={label} draggable="false" />
        <div class="card__foil-base" aria-hidden="true"></div>
        <div class="card__shine" aria-hidden="true"></div>
        <div class="card__etch" aria-hidden="true"></div>
        <div class="card__suppression" aria-hidden="true"></div>
        <div class="card__glare" aria-hidden="true"></div>
      </div>
    </button>
  </div>
</div>
