# Agent workflow

```text
capture-ingest
  -> register
  -> semantic-regions
  -> reflectance-maps
  -> material-fit
  -> review
  -> css/glb-build
  -> publish
```

Each transition is explicit and stores immutable inputs, outputs, metrics, and review state. Failed jobs remain inspectable and can be resumed from the last accepted artifact. No worker may mutate an approved artifact in place.
