# Catalog

Version 3 runtime data for the reviewed DIP4E source PDF is committed here.

The generation, review, validation, and reproducibility process is documented in `CATALOG_BUILD_WORKFLOW.md` at the repository root.

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

## Exercise catalog status

The repository contains the Exercise Locator schemas, runtime loader, API, and
offline builder/compiler code. The real full-book exercise artifacts have not yet
been generated or committed:

```text
catalog/dip4e/exercises.yaml
catalog/dip4e/exercises.sections.01.yaml ... exercises.sections.12.yaml
catalog/dip4e/compiled_exercise_index.json
catalog/dip4e/compiled_exercise_index.sections.01.json ... sections.12.json
catalog/dip4e/exercise_validation_report.json
```

Until those files pass the source-PDF build and review workflow, deployments should
leave `TEACHING_GPT_EXERCISE_INDEX_PATH` unset. Exercise endpoints then return
`EXERCISE_CATALOG_UNAVAILABLE`; the committed section catalog continues to load.
Once configured, the exercise package is strict: missing or malformed shards, chapter
mismatches, invalid references, and a source-book mismatch prevent startup.
