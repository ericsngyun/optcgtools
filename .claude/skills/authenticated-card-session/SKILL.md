---
name: authenticated-card-session
description: Run the full authenticated capture-session workflow for one physical OPTCG card — init, ingest, authentication, rights, validation, quality preflight, rectification, registration, and review opening. Use when a new physical card arrives or a session must be completed/repaired.
---

# Authenticated card session

Follow `AGENTS.md`. Raw captures live in private storage outside the repo
(e.g. `~/GenkiStuff/optcg-reference-lab/<session-id>/`). Never copy card
imagery into the repository.

## 1. Initialize

```bash
uv run optcg-material init <session-root> \
  --session-id <set>-<num>-<name>-<lang>-<seq> \
  --card-id OP01-120 --card-name Shanks --set-code OP01 --language EN \
  --operator "<operator>" --rights-owner GenkiStuff
```

## 2. Ingest captures

Minimum set: 1 albedo, 7 tilt-x, 7 tilt-y, 7 light-hard, 3 light-soft,
4 rake, 4 macro. Sample more for narrow spectral bands, gold linework, fine
embossing, manga panels, or strong foreground/background differences.

```bash
uv run optcg-material add <session-root> <file> --kind albedo
uv run optcg-material add <session-root> <file> --kind tilt-x --angle -30
uv run optcg-material add <session-root> <file> --kind rake --direction left
```

Capture rules: fixed camera and card center; locked focus/exposure/white
balance; no HDR, portrait mode, or filters; record light type and position;
document any sleeve or slab; never edit an ingested source.

## 3. Record authentication and rights (human facts, not model output)

```bash
uv run optcg-material verify-auth <session-root> \
  --method "<inspection method>" --verifier "<named human>"
uv run optcg-material set-rights <session-root> \
  --status owned-capture --public-derivatives-allowed --no-public-albedo-allowed
```

## 4. Validate → preflight → rectify → register

```bash
uv run optcg-material validate <session-root>
uv run optcg-material quality <session-root>
uv run optcg-material rectify <session-root>
uv run optcg-material register <session-root>
```

Each step fails closed. On ambiguous corner detection, prepare a reviewed
`--manual-quads` JSON rather than accepting a weak homography. If registered
text or linework swims between frames, stop: no extraction may proceed.

## 5. Open review and record promotion

```bash
uv run optcg-review open <session-root> --reviewer "<named human>"
```

Record `authenticated-capture-ingested` in the promotion ledger with the
session reference and input hashes. Quality and registration approvals are
human-only transitions — propose them; do not perform them.

## Stop conditions

Missing authentication or rights → stop. Failed quality gate → stop and
report the diagnostics. Never work around a failed gate.
