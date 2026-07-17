<script>
  import HoloCard from "./HoloCard.svelte";

  export let cardId = "";
  export let image = "";
  export let mask = "";
  export let foilMask = "";
  export let metallicMask = "";
  export let glossMask = "";
  export let textureMask = "";
  export let normalMap = "";
  export let directionMap = "";
  export let back = "/img/demo/card-back.svg";
  export let treatment = "sp-etched";
  export let label = "One Piece Card Game card";
  export let masked = true;
  export let glareStrength = 0.85;
  export let foilStrength = 0.82;
  export let textureScale = 1;
  export let maxTilt = 11;

  // Compiled-manifest wiring: pass the parsed card-manifest.json produced by
  // scripts/compile-card-profile.mjs plus the URL prefix its outputs are
  // served from. The compiled card.css must be loaded alongside.
  export let manifest = null;
  export let manifestBase = "";
  export let tier = "grid";
  export let staticPose = null;

  const treatmentMap = {
    sp: "sp-etched",
    "sp-etched": "sp-etched",
    "sp-rainbow": "sp-rainbow",
    parallel: "alt-art",
    "alt-art": "alt-art"
  };

  const joinBase = (assetPath) =>
    manifestBase ? `${manifestBase.replace(/\/+$/, "")}/${assetPath}` : assetPath;

  $: compiled = manifest
    ? {
        profileId: manifest.profile?.id ?? cardId,
        image: manifest.assets?.albedo ? joinBase(manifest.assets.albedo.path) : image,
        back: manifest.assets?.cardBack ? joinBase(manifest.assets.cardBack.path) : back,
        vars: manifest.cssVariables ?? null,
        maxTilt: manifest.tiers?.[tier]?.maxTiltDeg ?? maxTilt,
        suspendOffscreen: manifest.tiers?.[tier]?.suspendOffscreen ?? tier === "grid",
        notice: manifest.notice ?? ""
      }
    : null;

  $: finish = compiled ? "compiled" : treatmentMap[treatment] ?? "alt-art";
  $: resolvedImage = compiled?.image || image || "/img/demo/optcg-placeholder.svg";
  $: resolvedMask = mask || "/img/masks/sp-generic-mask.svg";
  $: resolvedCardId = compiled?.profileId ?? cardId;
  $: resolvedLabel = [resolvedCardId ? `${label} ${resolvedCardId}` : label, compiled?.notice]
    .filter(Boolean)
    .join(" — ");
</script>

{#if compiled}
  <HoloCard
    image={resolvedImage}
    back={compiled.back}
    {finish}
    label={resolvedLabel}
    {masked}
    maxTilt={compiled.maxTilt}
    profileId={compiled.profileId}
    {tier}
    profileVars={compiled.vars}
    suspendOffscreen={compiled.suspendOffscreen}
    {staticPose}
  />
{:else}
  <HoloCard
    image={resolvedImage}
    mask={resolvedMask}
    {foilMask}
    {metallicMask}
    {glossMask}
    {textureMask}
    {normalMap}
    {directionMap}
    {back}
    {finish}
    label={resolvedLabel}
    {masked}
    {glareStrength}
    {foilStrength}
    {textureScale}
    {maxTilt}
    {staticPose}
  />
{/if}
