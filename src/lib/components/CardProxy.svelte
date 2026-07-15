<script>
  import HoloCard from "./HoloCard.svelte";

  export let cardId = "";
  export let image = "";
  export let mask = "";
  export let back = "/img/demo/card-back.svg";
  export let treatment = "sp-etched";
  export let label = "One Piece Card Game card";
  export let masked = true;
  export let glareStrength = 0.85;
  export let foilStrength = 0.82;
  export let textureScale = 1;
  export let maxTilt = 11;

  const treatmentMap = {
    sp: "sp-etched",
    "sp-etched": "sp-etched",
    "sp-rainbow": "sp-rainbow",
    parallel: "alt-art",
    "alt-art": "alt-art"
  };

  $: finish = treatmentMap[treatment] ?? "alt-art";
  $: resolvedImage = image || "/img/demo/optcg-placeholder.svg";
  $: resolvedMask = mask || "/img/masks/sp-generic-mask.svg";
  $: resolvedLabel = cardId ? `${label} ${cardId}` : label;
</script>

<HoloCard
  image={resolvedImage}
  mask={resolvedMask}
  {back}
  {finish}
  label={resolvedLabel}
  {masked}
  {glareStrength}
  {foilStrength}
  {textureScale}
  {maxTilt}
/>
