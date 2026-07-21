# Catalog

Version 3 runtime data for the reviewed DIP4E source PDF is committed here.

Runtime and audit files:

```text
catalog/dip4e/manifest.yaml
catalog/dip4e/manifest.sections.01.yaml ... manifest.sections.12.yaml
catalog/dip4e/compiled_locator_index.json
catalog/dip4e/compiled_locator_index.sections.01.json ... compiled_locator_index.sections.12.json
catalog/dip4e/validation_report.json
```

`manifest.yaml` and `compiled_locator_index.json` are strict package manifests. Each references one per-chapter shard. The compiler and runtime reject missing, duplicate, malformed, or unexpected shard filenames, assemble all shards, and then run the full `BookManifest` or `CompiledLocatorIndex` validation.

`compiled_locator_index.json` remains the configured runtime entry point. `validation_report.json` records hashes for package manifests and every shard, source-PDF checks, and explicitly reports real file-search retrieval as `not_tested` until a separate GPT acceptance run is recorded.

The application intentionally fails if the complete Version 3 index is missing or invalid. Partial indexes and Version 2 data are not accepted.
