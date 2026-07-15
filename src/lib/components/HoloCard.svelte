<script>
  import { spring } from "svelte/motion";
  import { onDestroy, onMount } from "svelte";

  export let image = "/img/demo/optcg-placeholder.svg";
  export let back = "/img/demo/card-back.svg";

  // `mask` remains as a backwards-compatible fallback. Production profiles
  // should provide independent material-channel masks.
  export let mask = "/img/masks/sp-generic-mask.svg";
  export let foilMask = "";
  export let metallicMask = "";
  export let glossMask = "";
  export let textureMask = "";
  export let normalMap = "";
  export let directionMap = "";

  export let finish = "sp-etched";
  export let label = "One Piece Card Game holofoil test card";
  export let masked = true;
  export let maxTilt = 12;
  export let glareStrength = 1;
  export let foilStrength = 1;
  export let textureScale = 1;

  let card;
  let frame = null;
  let pending = null;
  let reducedMotion = false;
  let interacting = false;

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
    if (reducedMotion || !card) return;

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

  $: distanceFromCenter = clamp(
    Math.sqrt(($pointer.x - 50) ** 2 + ($pointer.y - 50) ** 2) / 50,
    0,
    1
  );

  $: resolvedFoilMask = foilMask || mask;
  $: resolvedMetallicMask = metallicMask || mask;
  $: resolvedGlossMask = glossMask || mask;
  $: resolvedTextureMask = textureMask || mask;

  $: dynamicStyles = `
    --pointer-x: ${$pointer.x}%;
    --pointer-y: ${$pointer.y}%;
    --pointer-from-center: ${distanceFromCenter};
    --card-opacity: ${$pointer.opacity};
    --rotate-x: ${$rotation.x}deg;
    --rotate-y: ${$rotation.y}deg;
    --background-x: ${$background.x}%;
    --background-y: ${$background.y}%;
    --glare-strength: ${glareStrength};
    --foil-strength: ${foilStrength};
    --texture-scale: ${textureScale};
    --mask: ${cssUrl(mask)};
    --foil-mask: ${cssUrl(resolvedFoilMask)};
    --metallic-mask: ${cssUrl(resolvedMetallicMask)};
    --gloss-mask: ${cssUrl(resolvedGlossMask)};
    --texture-mask: ${cssUrl(resolvedTextureMask)};
    --normal-map: ${cssUrl(normalMap)};
    --direction-map: ${cssUrl(directionMap)};
  `;

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
  });
</script>

<div
  bind:this={card}
  class:interacting
  class:masked
  class="card interactive"
  data-tcg="one-piece"
  data-finish={finish}
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
        <div class="card__glare" aria-hidden="true"></div>
      </div>
    </button>
  </div>
</div>
