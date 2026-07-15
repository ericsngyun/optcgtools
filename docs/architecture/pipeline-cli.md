# Pipeline CLI outline

Proposed commands:

```text
cardlab capture init
cardlab capture validate
cardlab register run
cardlab regions propose
cardlab maps derive
cardlab profile fit
cardlab review serve
cardlab asset build-css
cardlab asset build-glb
cardlab evaluate
cardlab publish
```

Every command accepts a manifest path, writes machine-readable reports, records the pipeline commit and dependency versions, and supports a dry-run mode. Worker execution may later move behind a queue, but the CLI remains the reproducible local and CI entrypoint.
