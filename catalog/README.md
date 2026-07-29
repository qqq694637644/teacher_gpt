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

The reviewed Exercise Locator artifacts are generated and committed:

```text
catalog/dip4e/exercises.yaml
catalog/dip4e/exercises.sections.02.yaml ... exercises.sections.12.yaml
catalog/dip4e/compiled_exercise_index.json
catalog/dip4e/compiled_exercise_index.sections.02.json ... sections.12.json
catalog/dip4e/exercise_validation_report.json
```

The source PDF contains formal `Problems` sections in chapters 2-12; chapter 1 has no
exercise shard. The reviewed baseline contains 492 exercises, 122 starred exercises,
28 cross-page exercises, 520 problem retrieval steps, and 476 resolved references. The
compiled execution plan preserves 1,505 raw reference page steps as audit metadata,
uses explicit PDF-reviewed context-page selections for 4 section references, reduces
1,437 execution candidates by 73 same-page/same-window merges, preserves 5
same-page distinct-window cases, and exposes 1,364 execution steps. The compiled
package contains 7,336 evidence-derived queries, zero unbalanced queries, zero steps
without a balanced query, and zero queries requiring further NFKC normalization. All
chapter number ranges are
continuous and the independent rebuild matched all package and shard files byte-for-byte.

Deployments should set `TEACHING_GPT_EXERCISE_INDEX_PATH` to
`catalog/dip4e/compiled_exercise_index.json`. The package is strict: missing or
malformed shards, chapter mismatches, invalid references, cycles, and a source-book
mismatch prevent startup. `exercise_validation_report.json` records
`source_pdf_verification_status: passed` and keeps real GPT file-search retrieval at
`not_tested` until a separate acceptance run is completed.
