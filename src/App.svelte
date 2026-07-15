<script>
  import HoloCard from "./lib/components/HoloCard.svelte";
  import { finishes } from "./lib/data/finishes.js";

  let finish = "sp-etched";
  let image = "/img/demo/optcg-placeholder.svg";
  let mask = "/img/masks/sp-generic-mask.svg";
  let masked = true;
  let glareStrength = 0.85;
  let foilStrength = 0.82;
  let textureScale = 1;
  let maxTilt = 11;
  let fileUrl;
  let maskFileUrl;

  function loadImage(event) {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    if (fileUrl) URL.revokeObjectURL(fileUrl);
    fileUrl = URL.createObjectURL(file);
    image = fileUrl;
  }

  function loadMask(event) {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    if (maskFileUrl) URL.revokeObjectURL(maskFileUrl);
    maskFileUrl = URL.createObjectURL(file);
    mask = maskFileUrl;
    masked = true;
  }
</script>

<svelte:head>
  <meta
    name="description"
    content="A material calibration lab for One Piece Card Game SP and alternate-art holofoil effects."
  />
</svelte:head>

<main>
  <header class="masthead">
    <div>
      <p class="eyebrow">GenkiStuff R&amp;D / OPTCG material study</p>
      <h1>Holo Material Lab</h1>
      <p class="lede">
        A physically motivated test bench for SP, parallel, and alternate-art finishes. Upload a scan
        and a card-specific foil mask, then tune the material—not the artwork.
      </p>
    </div>
    <a href="https://github.com/simeydotme/pokemon-cards-css" rel="noreferrer">
      Upstream architecture ↗
    </a>
  </header>

  <section class="workspace">
    <div class="stage" aria-label="Interactive holo card preview">
      <HoloCard
        {image}
        {mask}
        {finish}
        {masked}
        {glareStrength}
        {foilStrength}
        {textureScale}
        {maxTilt}
      />
      <p class="hint">Move the pointer across the card. Use arrow keys when focused.</p>
    </div>

    <aside class="controls">
      <div class="control-group">
        <span class="control-number">01</span>
        <div>
          <label for="finish">Material profile</label>
          <select id="finish" bind:value={finish}>
            {#each finishes as option}
              <option value={option.id}>{option.label}</option>
            {/each}
          </select>
          <p>{finishes.find((item) => item.id === finish)?.description}</p>
        </div>
      </div>

      <div class="control-group">
        <span class="control-number">02</span>
        <div class="stack">
          <label for="card-file">Card scan</label>
          <input id="card-file" type="file" accept="image/*" on:change={loadImage} />
          <label for="image-url">Or image URL</label>
          <input id="image-url" type="url" bind:value={image} />
        </div>
      </div>

      <div class="control-group">
        <span class="control-number">03</span>
        <div class="stack">
          <label for="mask-file">Foil mask</label>
          <input id="mask-file" type="file" accept="image/*" on:change={loadMask} />
          <label for="mask-url">Or mask URL</label>
          <input id="mask-url" type="url" bind:value={mask} />
          <label class="toggle"><input type="checkbox" bind:checked={masked} /> Use selective mask</label>
        </div>
      </div>

      <div class="control-group sliders">
        <span class="control-number">04</span>
        <div class="stack">
          <label>Foil intensity <output>{foilStrength.toFixed(2)}</output></label>
          <input type="range" min="0" max="1.4" step="0.01" bind:value={foilStrength} />
          <label>Glare intensity <output>{glareStrength.toFixed(2)}</output></label>
          <input type="range" min="0" max="1.4" step="0.01" bind:value={glareStrength} />
          <label>Texture scale <output>{textureScale.toFixed(2)}</output></label>
          <input type="range" min="0.5" max="2.5" step="0.01" bind:value={textureScale} />
          <label>Maximum tilt <output>{maxTilt}°</output></label>
          <input type="range" min="2" max="18" step="1" bind:value={maxTilt} />
        </div>
      </div>
    </aside>
  </section>

  <section class="method">
    <p class="eyebrow">Calibration protocol</p>
    <div class="method-grid">
      <article><strong>01</strong><h2>Capture</h2><p>Use a straight-on scan plus a short physical reference video under one moving point light.</p></article>
      <article><strong>02</strong><h2>Segment</h2><p>Author a grayscale mask for foil ink, embossed linework, metallic borders, and matte zones.</p></article>
      <article><strong>03</strong><h2>Match</h2><p>Tune direction, bandwidth, chroma travel, glare radius, and luminance independently.</p></article>
      <article><strong>04</strong><h2>Validate</h2><p>Compare at several viewing angles and reject effects that look impressive but unlike the physical card.</p></article>
    </div>
  </section>
</main>
