# Security, rights, and dataset controls

## Rights boundary

The material pipeline may analyze public photographs as visual research, but public marketplace images and official card scans must not be copied into the public repository or republished as website assets without permission.

Approved source classes:

- GenkiStuff-owned physical-card captures;
- images licensed for the intended use;
- synthetic fixtures;
- derived maps that are legally approved and do not reconstruct unlicensed source imagery;
- source URLs and written observations.

## Authentication boundary

A profile may be `photo-validated` from multiple public references. Only a documented authenticated physical card can produce a `capture-validated` profile.

Record:

- owner or custodian;
- acquisition/source record when available;
- authentication method;
- card condition;
- language and print variant;
- capture operator and date.

## Private storage

Raw reference media should use private object storage with:

- encryption at rest and in transit;
- least-privilege service accounts;
- immutable object hashes;
- versioning;
- retention rules;
- audit logs;
- no public bucket listing;
- signed short-lived access URLs for review tools.

## Model boundary

Do not send private captures to external model APIs unless the service and data terms have been explicitly approved. Prefer local or controlled inference for raw captures. Persist model name, version, weights hash, configuration, and prompts for every derived output.

## Publication gate

The publishing worker must fail closed when:

- rights metadata is missing;
- asset hashes do not match;
- review approval is absent;
- profile schema validation fails;
- a public manifest references a private raw capture;
- the card identity or print variant is unresolved.
