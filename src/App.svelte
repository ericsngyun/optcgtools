<script>
  import HoloCard from "./lib/components/HoloCard.svelte";
  import ResearchRenderer from "./lib/components/ResearchRenderer.svelte";
  import { finishes } from "./lib/data/finishes.js";
  import { DEFAULT_RESEARCH_PROFILE } from "./lib/research/profile.js";

  let view = "css";
  let researchProfile = DEFAULT_RESEARCH_PROFILE;
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
    content="Authenticated physical-card material extraction and accurate OPTCG web/3D holo simulation lab."
  />
</svelte:head>

<main>
  <header class="masthead">
    <div>
      <p class="eyebrow">GenkiStuff R&amp;D / authenticated OPTCG material study</p>
      <h1>Holo Material Lab</h1>
      <p class="lede">
        A measured pipeline for selective CSS effects and physically based 3D card assets. The CSS
        view preserves the Pokémon project’s interaction architecture; the physical view consumes
        independently extracted material channels.
      </p>
    </div>
    <a href="https://github.com/simeydotme/pokemon-cards-css" rel="noreferrer">
      Upstream architecture ↗
    </a>
  </header>

  <nav class="lab-tabs" aria-label="Renderer mode">
    <button class:active={view === "css"} type="button" on:click={() => (view = "css")}>
      CSS delivery approximation
    </button>
    <button class:active={view === "physical"} type="button" on:click={() => (view = "physical")}>
      Physical reference renderer
    </button>
  </nav>

  {#if view === "css"}
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
  {:else}
    <ResearchRenderer bind:profile={researchProfile} />
  {/if}

  <section class="method">
    <p class="eyebrow">Evidence-to-render protocol</p>
    <div class="method-grid">
      <article><strong>01</strong><h2>Authenticate</h2><p>Record card identity, print variant, source rights, capture settings, and immutable input hashes.</p></article>
      <article><strong>02</strong><h2>Measure</h2><p>Register tilt, moving-light, soft-light, and raking sequences before deriving any material mask.</p></article>
      <article><strong>03</strong><h2>Review</h2><p>Inspect semantic proposals, raw measurements, uncertainty, and each corrected mask independently.</p></article>
      <article><strong>04</strong><h2>Synthesize</h2><p>Compare physical and virtual frames at matched camera and light states before approving CSS or 3D assets.</p></article>
    </div>
  </section>
</main>
