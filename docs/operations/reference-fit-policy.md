# Reference fit acceptance policies

Task packet: `convergence-p3-reference-fit-policy`. Code:
`src/optcg_material/reference_fitting.py` (`FitPolicy`,
`ReferenceSynthesisThresholds`, `_evaluate_reference_synthesis`). CLI:
`optcg-reference-fit fit --policy {physical-fit,reference-synthesis-fit}`
(default `reference-synthesis-fit`; the library API default remains
`physical-fit` so pre-policy callers keep pre-policy decisions).

## Why two policies

The joint analysis-by-synthesis fit (one shared material profile, per-source
nuisances) originally accepted a profile only when the masked linear-RGB MAE of
at least two sources fell under an absolute threshold (0.06) and an
error-derived consistency score cleared 0.35. That is the right discipline for
controlled captures — and it is retained unchanged as **`physical-fit`** — but
it is miscalibrated *by design* for uncontrolled public media: real run
`jp-aa-fit-002` was rejected (0 sources ≤ 0.06, consistency 0.021) although the
fitted direction was plausible. Unknown camera exposure, white balance, tone
curves, and compression put an irreducible floor under absolute RGB error that
has nothing to do with whether the profile reproduces the card's appearance.

**`reference-synthesis-fit` is a different measurement, not a looser one.**
No absolute-RGB threshold was rescaled; acceptance is decided by
perceptual/regional agreement criteria, each chosen because the nuisances of
uncontrolled media approximately cancel out of it. A profile that merely "looks
numerically close" no longer passes or fails on that basis; it must activate
the right regions, in the right order, in the right place, coherently across
sources.

Invariant under BOTH policies:

- The optimization objective and nuisance model are identical. Camera exposure
  is solved per source in closed form and is never traded against material
  parameters (the material block has no gain term).
- The single-reference-overfit rejection and the renderer-model-limit
  diagnostic (a finding, never worked around) stay in force.
- The frozen report schema (`docs/agent-ops/reference-fitting-report.schema.json`)
  is unchanged. The policy used and the per-metric values are recorded as
  `policy-*` keys inside each source's free-form `regional_error` map
  (`policy-physical-fit: 1.0` or `policy-reference-synthesis-fit: 1.0` plus the
  metric scores); reports without these keys predate the policy split and are
  physical-fit reports.

## reference-synthesis-fit criteria

All image-side quantities are computed on the registered observation frames
against the fitted candidate renders, inside the interference-mask valid area.
"Activation" means luminance above the *diffuse baseline* — the same fitted
frame re-rendered with the specular term switched off — after subtracting the
per-image median residual, then thresholded at a fraction (0.35) of the
per-image robust peak (P99). Both the median subtraction and the
fraction-of-own-peak threshold make the activation maps invariant to global
gain and to residual exposure offsets.

Per-metric definition, floor, and robustness rationale:

| # | Metric (rejection token) | Definition | Floor/ceiling | Why robust where absolute RGB is not |
|---|---|---|---|---|
| 1 | `regional-foil-activation` | IoU of thresholded observed vs rendered activation maps, frame-averaged, prior-weighted across sources | IoU ≥ 0.30 | Each map is thresholded relative to its *own* robust peak, so a global exposure or tone-curve change rescales both sides of the same map and leaves the binary regions unchanged. Compares *where* the foil responds, not how bright the pixels are. |
| 2 | `foil-occupancy` | absolute difference of active-area fractions (observed vs rendered) | Δ ≤ 0.20 | An area fraction of a self-normalized binary map carries no radiometric units at all; exposure/WB cannot move it. Catches "render lights up half the card, observation a small lobe" even when the regions overlap. |
| 3 | `hue-ordering` | Fisher-Lee circular correlation of chroma-weighted opponent-hue profiles, binned along the dominant activation-gradient axis (structure tensor of the observed activation), observed vs rendered | ρ ≥ 0.10 | Hue is a ratio of opponent chroma components: a global exposure change cancels exactly, and a moderate WB gain shifts all hues coherently without reversing their *ordering* along the gradient. Rank/ordering survives compression that destroys absolute chroma. Degenerate (hue-uniform) regions return not-computable and are skipped, never penalized. |
| 4 | `highlight-position` | distance between observed and rendered highlight centroids (percentile-thresholded, intensity-weighted), normalized by the image diagonal | ≤ 0.10 | A centroid of the top-percentile pixels is invariant to any monotone intensity mapping (exposure, gamma, tone curve): the same pixels stay on top. Position is geometry, not radiometry. |
| 5 | `relative-intensity-coherence` | Pearson correlation of source-to-source DELTAS of log peak activation levels (robust P99.5 activation over the diffuse-baseline level), damped by spread agreement; needs ≥ 3 sources | ≥ 0.25 | Only *differences between sources* enter — absolute levels never do, so per-source exposure divides out of the level (activation and baseline scale together) before deltas are taken. The peak level cannot be modulated by per-source lobe-geometry nuisances (hardness/elevation change lobe area, not amplitude), so sources that disagree about it are mutually incoherent as views of one shared material. Skipped (not penalized) when the sources already agree (log-spread < 0.25) — there is nothing to correlate. Known limitation: heavily clipped highlights compress observed peaks; P99.5 and the log domain soften but do not eliminate this. |
| 6 | `texture-frequency` | 1 − ½·L1 between normalized radial-FFT band-energy distributions (4 dominant bands, 0.02–0.5 cyc/px) of standardized (zero-mean, unit-variance), Hann-windowed luminance | ≥ 0.55 | Standardizing luminance before the FFT removes gain and offset entirely; comparing *normalized* band distributions removes overall contrast. Coarse bands are insensitive to JPEG's high-frequency ringing while still separating "smooth lobe" from "fine foil grain" responses. |
| 7 | `temporal-coherence` | sequences only: frame-to-frame highlight-centroid displacement agreement (½ direction cosine + ½ magnitude ratio), averaged over informative steps | ≥ 0.40 | Built from the position metric (4), so monotone-mapping-invariant per frame; differencing consecutive frames additionally cancels anything constant within the source (its exposure, WB, vignette). Still-only sets have no value here and are NOT penalized; static steps are skipped as uninformative. |
| 8 | `perceptual-similarity` | masked mean of the SSIM *structure* component on luminance (local means removed, local deviations normalized, Gaussian 11×11/σ1.5 windows; cv2 + numpy only) | ≥ 0.45 | The structure term correlates locally normalized signals: a global or slowly varying gain (exposure, vignetting, WB after luminance projection) cancels in the covariance/deviation ratio. JPEG perturbs it mildly and diffusely; a wrong response pattern collapses it. |

### Acceptance combination

A `reference-synthesis-fit` run is accepted iff ALL of:

1. every computable hard criterion above clears its floor (prior-weighted mean
   across usable sources; sequence-only for temporal; ≥ 3 sources for
   intensity coherence);
2. the prior-weighted mean composite score clears `min_composite` (0.55), where
   the per-source composite is the mean of the available per-source scores
   mapped to [0, 1] (position scaled by 0.25 of the diagonal, occupancy by
   0.5);
3. at least `min_accepted_sources` (2) sources individually meet the composite
   floor — one privileged source cannot carry the set;
4. the single-reference-overfit gate does not fire;
5. the renderer-model-limit diagnostic does not fire.

Every failing criterion is NAMED in the rejection reasons with its bracketed
token (e.g. `reference-synthesis-fit rejection [hue-ordering]: …`) and the
individually failing sources are appended to the report's `outlier_report`.

### Not-computable metrics

Per the task packet's stop condition, a metric that cannot be computed from the
available observation data is dropped with rationale, never faked and never
penalized:

- `hue-ordering`: region too small (< 48 px), too few informative bins, or hue
  effectively constant along the axis (circular resultant > 0.995).
- `temporal-coherence`: no sequence sources, missing centroids, or no
  informative (non-static) steps.
- `relative-intensity-coherence`: fewer than 3 usable sources, no meaningful
  foil level anywhere, or sources already agreeing about intensity.
- `texture-frequency`: near-constant luminance or too few valid pixels.

## Calibration evidence

Fixtures in `tests/test_reference_fitting.py` (synthetic observations of a
known ground-truth profile, deterministic):

| Set | Construction | reference-synthesis-fit | physical-fit |
|---|---|---|---|
| GOOD (`policy-good`) | 3 coherent views, per-source exposure 0.8/1.05/1.3, per-source WB gains ±10%, JPEG q40 | **accept** (IoU ≈ 0.89, hue ≈ 0.99, composite ≈ 0.96) | **reject** (only 1 source ≤ 0.06; consistency 0.29 < 0.35) — the jp-aa-fit-002 pattern |
| BAD hue | chromaticity mirrored along x, per-pixel luminance preserved | **reject `[hue-ordering]`** (ρ ≈ −0.99) | — |
| BAD displaced highlight | two equal bright blobs; observed centroid sits at their empty midpoint, the fitted lobe cannot | **reject `[highlight-position]`** (0.15–0.17 vs ≤ 0.10) | — |
| BAD wrong regions | activation painted as a border ring a compact lobe cannot cover | **reject `[regional-foil-activation]`** (IoU ≈ 0.08) | — |
| BAD incoherent | 4 sources rendered with specular strength 0.02/0.9/0.4/0.7 | **reject `[relative-intensity-coherence]`** (≈ 0.10 vs ≥ 0.25) | — |
| Existing coherent set (with sequence) | clean synthetic multi-source | **accept**, `policy-temporal-coherence ≈ 0.96` on the sequence only | accept (unchanged) |
| Existing overfit set | one true + two contradictory sources | **reject** (overfit gate, both policies) | reject (unchanged) |

`physical-fit` decisions are regression-guarded by the pre-existing tests
(unedited) plus a byte-identical report comparison against an explicit
`policy="physical-fit"` rerun.
