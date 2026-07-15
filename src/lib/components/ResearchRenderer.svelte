<script>
  import { createEventDispatcher, onDestroy, onMount } from "svelte";

  import {
    DEFAULT_RESEARCH_STATE,
    ResearchCardRenderer
  } from "../research/ResearchCardRenderer.js";
  import {
    DEFAULT_RESEARCH_PROFILE,
    normalizeResearchProfile,
    validateResearchProfile
  } from "../research/profile.js";

  export let profile = DEFAULT_RESEARCH_PROFILE;

  const dispatch = createEventDispatcher();
  let container;
  let renderer;
  let status = "Initializing adaptive renderer…";
  let backend = "pending";
  let error = "";
  let profileFileName = "Synthetic fixture";
  let referenceUrl = "";
  let referenceName = "No matched reference loaded";
  let comparisonMode = "off";
  let referenceOpacity = 0.55;
  let tiltXDeg = DEFAULT_RESEARCH_STATE.tiltXDeg;
  let tiltYDeg = DEFAULT_RESEARCH_STATE.tiltYDeg;
  let lightAzimuthDeg = DEFAULT_RESEARCH_STATE.lightAzimuthDeg;
  let lightElevationDeg = DEFAULT_RESEARCH_STATE.lightElevationDeg;
  let lightDistance = DEFAULT_RESEARCH_STATE.lightDistance;
  let exposure = DEFAULT_RESEARCH_STATE.exposure;
  let channels = { ...DEFAULT_RESEARCH_STATE.channels };
  let lastProfile = profile;

  onMount(async () => {
    renderer = new ResearchCardRenderer(container, {
      onStatus(event) {
        status = event.phase;
        if (event.backend) backend = event.backend;
        if (event.message) error = event.message;
        dispatch("status", event);
      },
      onError(value) {
        error = value.message;
        dispatch("error", value);
      }
    });

    try {
      await renderer.init();
      renderer.setState(currentState());
      lastProfile = profile;
    } catch (value) {
      error = value.message;
      status = "error";
    }
  });

  onDestroy(() => {
    renderer?.dispose();
    if (referenceUrl) URL.revokeObjectURL(referenceUrl);
  });

  $: if (renderer) renderer.setState(currentState());

  $: if (renderer && profile !== lastProfile) {
    lastProfile = profile;
    renderer.setProfile(profile);
  }

  function currentState() {
    return {
      tiltXDeg: Number(tiltXDeg),
      tiltYDeg: Number(tiltYDeg),
      lightAzimuthDeg: Number(lightAzimuthDeg),
      lightElevationDeg: Number(lightElevationDeg),
      lightDistance: Number(lightDistance),
      exposure: Number(exposure),
      channels: { ...channels }
    };
  }

  function setChannel(name, event) {
    channels = { ...channels, [name]: event.currentTarget.checked };
  }

  function solo(name) {
    channels = Object.fromEntries(Object.keys(channels).map((key) => [key, key === name]));
  }

  function restoreChannels() {
    channels = { ...DEFAULT_RESEARCH_STATE.channels };
  }

  async function loadProfile(event) {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    error = "";
    try {
      const raw = JSON.parse(await file.text());
      const validation = validateResearchProfile(raw);
      if (!validation.valid) throw new Error(validation.errors.join("; "));
      profile = normalizeResearchProfile(raw);
      profileFileName = file.name;
      dispatch("profile", profile);
    } catch (value) {
      error = `Profile rejected: ${value.message}`;
    } finally {
      event.currentTarget.value = "";
    }
  }

  function loadReference(event) {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    if (referenceUrl) URL.revokeObjectURL(referenceUrl);
    referenceUrl = URL.createObjectURL(file);
    referenceName = file.name;
    comparisonMode = "overlay";
    event.currentTarget.value = "";
  }

  function resetPose() {
    tiltXDeg = DEFAULT_RESEARCH_STATE.tiltXDeg;
    tiltYDeg = DEFAULT_RESEARCH_STATE.tiltYDeg;
    lightAzimuthDeg = DEFAULT_RESEARCH_STATE.lightAzimuthDeg;
    lightElevationDeg = DEFAULT_RESEARCH_STATE.lightElevationDeg;
    lightDistance = DEFAULT_RESEARCH_STATE.lightDistance;
    exposure = DEFAULT_RESEARCH_STATE.exposure;
    restoreChannels();
    renderer?.controls?.reset();
  }

  function exportState() {
    const snapshot = {
      ...renderer.snapshotState(),
      comparison: {
        referenceName,
        mode: comparisonMode,
        opacity: Number(referenceOpacity)
      }
    };
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${profile.card.id}-render-state.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
</script>

<section class="research-shell" aria-label="Physical material research renderer">
  <div class="research-viewport">
    <div bind:this={container} class="research-canvas-host" aria-label="Interactive 3D card"></div>
    {#if referenceUrl && comparisonMode !== "off"}
      <img
        class:difference={comparisonMode === "difference"}
        class="reference-overlay"
        src={referenceUrl}
        alt="Matched authenticated physical reference"
        style:opacity={referenceOpacity}
      />
    {/if}
    <div class="research-status">
      <span class:failed={status === "error"}>{status}</span>
      <span>{backend}</span>
      <span>three r185</span>
    </div>
    {#if error}
      <p class="research-error" role="alert">{error}</p>
    {/if}
  </div>

  <aside class="research-controls">
    <div class="research-panel-heading">
      <div>
        <p class="eyebrow">Reference renderer</p>
        <h2>{profile.card.name}</h2>
      </div>
      <span>{profile.classification.family}</span>
    </div>

    <div class="research-control-block">
      <label for="research-profile">Material profile JSON</label>
      <input id="research-profile" type="file" accept="application/json,.json" on:change={loadProfile} />
      <p>{profileFileName} · {profile.classification.confidence}</p>
    </div>

    <div class="research-control-block">
      <label for="matched-reference">Matched physical frame</label>
      <input id="matched-reference" type="file" accept="image/*" on:change={loadReference} />
      <p>{referenceName}</p>
      <div class="research-segmented" aria-label="Comparison mode">
        {#each ["off", "overlay", "difference"] as mode}
          <button
            class:active={comparisonMode === mode}
            type="button"
            disabled={!referenceUrl && mode !== "off"}
            on:click={() => (comparisonMode = mode)}
          >{mode}</button>
        {/each}
      </div>
      <div class="research-label"><span>Reference opacity</span><output>{Number(referenceOpacity).toFixed(2)}</output></div>
      <input type="range" min="0" max="1" step="0.01" bind:value={referenceOpacity} disabled={!referenceUrl} />
    </div>

    <div class="research-control-block">
      <div class="research-label"><span>Card X tilt</span><output>{Number(tiltXDeg).toFixed(1)}°</output></div>
      <input type="range" min="-30" max="30" step="0.25" bind:value={tiltXDeg} />
      <div class="research-label"><span>Card Y tilt</span><output>{Number(tiltYDeg).toFixed(1)}°</output></div>
      <input type="range" min="-30" max="30" step="0.25" bind:value={tiltYDeg} />
    </div>

    <div class="research-control-block">
      <div class="research-label"><span>Light azimuth</span><output>{Number(lightAzimuthDeg).toFixed(0)}°</output></div>
      <input type="range" min="-180" max="180" step="1" bind:value={lightAzimuthDeg} />
      <div class="research-label"><span>Light elevation</span><output>{Number(lightElevationDeg).toFixed(0)}°</output></div>
      <input type="range" min="-10" max="85" step="1" bind:value={lightElevationDeg} />
      <div class="research-label"><span>Light distance</span><output>{Number(lightDistance).toFixed(2)}</output></div>
      <input type="range" min="1.5" max="6" step="0.05" bind:value={lightDistance} />
      <div class="research-label"><span>Exposure</span><output>{Number(exposure).toFixed(2)}</output></div>
      <input type="range" min="0.35" max="2.2" step="0.01" bind:value={exposure} />
    </div>

    <div class="research-control-block channel-block">
      <div class="research-label"><span>Material channels</span><button type="button" on:click={restoreChannels}>Restore</button></div>
      {#each Object.keys(channels) as channel}
        <div class="channel-row">
          <label>
            <input
              type="checkbox"
              checked={channels[channel]}
              on:change={(event) => setChannel(channel, event)}
            />
            {channel}
          </label>
          <button type="button" on:click={() => solo(channel)}>Solo</button>
        </div>
      {/each}
    </div>

    <div class="research-actions">
      <button type="button" on:click={resetPose}>Reset state</button>
      <button type="button" on:click={exportState}>Export state</button>
      <button type="button" on:click={() => renderer.exportPng()}>Export PNG</button>
    </div>

    <p class="research-disclaimer">
      This is the standards-based reference baseline. Capture matching may still require a custom
      diffraction model when thin-film iridescence cannot reproduce the authenticated card.
    </p>
  </aside>
</section>
