# Teacher GPT Locator API

Version 3.1 extends the strict one-book locator API with a separate Exercise Locator
contract. Section and exercise identifiers remain in independent namespaces.

The original PDF in GPT file search is the only source of textbook content, exercise
text, and page visuals. This backend returns strict, page-by-page retrieval plans for a
requested section, learning-unit ID, or exercise ID. It does not return textbook prose,
images, summaries, search results, or generated answers.

- Architecture: `ARCHITECTURE_REFACTOR.md`
- Catalog build workflow and lessons: `CATALOG_BUILD_WORKFLOW.md`
- GPT Builder instructions: `PROMPT.md`
- Curated Action schema: `examples/openai_action_schema_one_book.yaml`

## Numbering model

### Printed sections

Printed textbook identifiers are preserved exactly:

```json
{
  "section_kind": "printed",
  "section_id": "2.6",
  "printed_section_id": "2.6"
}
```

### Project learning units

The reviewed Manifest stores an ordered heading tree but cannot store project IDs. The compiler assigns IDs from sibling order:

```text
2.6.1
2.6.2
2.6.3
```

Children recursively append an ordinal:

```text
2.6.5 Spatial Operations
├── 2.6.5.1 Single-Pixel Operations
├── 2.6.5.2 Neighborhood Operations
├── 2.6.5.3 Geometric Transformations
└── 2.6.5.4 Image Registration
```

The next top-level sibling is `2.6.6` (Vector and Matrix Operations); children never consume `2.6.6`.

Sibling headings must use the same `source_level`. Child headings must be exactly one structural level deeper. The Manifest is rejected if it contains a manually supplied project `section_id`.

## Runtime API

The backend registers four routes:

```text
GET /health
GET /gpt/section-locators/{section_id}
GET /gpt/exercise-locators/{exercise_id}
GET /gpt/chapters/{chapter_id}/exercises
```

The three locator routes are exported to GPT Actions:

```text
gptGetSectionLocator
gptGetExerciseLocator
gptListChapterExercises
```

All Version 2 routes were deleted. There are no deprecated redirects or aliases.

The reviewed Exercise Catalog is committed independently from the section catalog.
Set `TEACHING_GPT_EXERCISE_INDEX_PATH` to its package manifest to enable the exercise
routes. If the setting is absent, section lookup remains available and exercise routes
return `EXERCISE_CATALOG_UNAVAILABLE`; if present, a missing, malformed, partial, or
book-mismatched exercise package prevents startup.

Example:

```bash
curl -H "Authorization: Bearer $TEACHING_GPT_API_KEY" \
  http://localhost:8000/gpt/section-locators/2.6.5
```

A locator contains:

- the exact section ID and printed parent ID;
- unambiguous PDF index, PDF physical number, and printed page label;
- one retrieval step for every physical page in the section range;
- at least two file-search queries per page;
- required page evidence;
- first/last-page content boundaries;
- figures, equations, examples, and subheadings expected on each page.

It never contains textbook prose.

An exercise locator additionally contains:

- the exact `exercise_id`, chapter, source order, and starred state;
- one problem retrieval step for every physical page occupied by the exercise;
- explicit `exercise` content-window boundaries for same-page neighboring problems;
- required visual evidence for page identity and exercise boundaries;
- resolved retrieval plans for referenced sections, figures, equations, examples,
  tables, and other exercises.

It never contains a pre-generated solution.

## Strict startup behavior

The application loads this file during FastAPI startup:

```text
catalog/dip4e/compiled_locator_index.json
```

The repository includes the reviewed DIP4E catalog, so the default application and Docker configuration can start without a separate indexing step. `compiled_locator_index.json` is a strict package manifest that references one section shard per chapter. The runtime loads every shard and then validates the assembled `CompiledLocatorIndex`; missing, duplicate, malformed, or out-of-range shard data prevents startup.

Startup still fails when the package or any shard is missing, uses another data version, contains unknown fields, has incomplete body-page coverage, has broken parent/child ranges, or does not represent a complete index.

A partial catalog is not a runnable deployment.

The committed exercise runtime entry point is:

```text
catalog/dip4e/compiled_exercise_index.json
```

It is also a strict package manifest with one shard per represented chapter. The
repository validates shard names, chapter ownership, canonical page references,
exercise ordering, reference integrity, and cross-exercise cycles.

## Offline build workflow

The source PDF is intentionally not committed to Git.

For the full generation rationale, automation/manual-review boundary, failure modes, and reproducibility requirements, see `CATALOG_BUILD_WORKFLOW.md`.

### 0. Verify the exact source file

```bash
python tools/verify_dip4e_source.py "D:\teaching_gpt_backend\1.pdf"
```

The verifier requires:

- SHA-256 `7b2b48ed87b454970d0916e1dbd7a5160e33d28db0dcdeba647b61eb5d3b850b`;
- 1022 physical pages;
- known page-label mappings;
- the nine Spatial Operations pages and anchors;
- the complete 2.6 heading order, which assigns Spatial Operations to `2.6.5`.

### 1. Extract candidates

```bash
python tools/extract_pdf_candidates.py \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  build/dip4e/candidates.json
```

The extractor records:

- the PDF SHA-256 and metadata;
- all PDF page labels;
- the PDF outline;
- layout-derived heading candidates;
- per-page Figure, Equation, and Example anchors.

Candidate output is not runtime data and cannot be served by the API.
The verified source currently yields 446 layout heading candidates: 12 chapter headings, 102 numbered section headings, and 332 unnumbered candidates. Two unnumbered author-name headings occur before any printed section and are excluded, leaving 444 catalog headings: 114 printed nodes and 330 learning units.

### 2. Generate and review the complete Manifest

Regenerate the deterministic source manifest:

```bash
python tools/build_dip4e_manifest.py \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  catalog/dip4e/manifest.yaml
```

The committed Manifest covers all 1022 physical pages through explicit `front_matter`, `body`, and `back_matter` classifications. `manifest.yaml` is a strict package manifest referencing 12 per-chapter YAML shards. After assembly it stores 114 printed section nodes and ordered learning-unit trees. Project IDs are generated by the compiler, not authored in YAML.

Every page retrieval step contains at least two queries and typed required evidence. `printed_page_equals` and content-window boundary evidence are marked `visual_required`; the local compiler validates that their anchors exist in the source PDF but does not claim that GPT file-search retrieval has been tested.

### 3. Compile and verify against the source PDF

```bash
python tools/compile_locator_index.py \
  catalog/dip4e/manifest.yaml \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  catalog/dip4e/compiled_locator_index.json \
  --report catalog/dip4e/validation_report.json
```

The compiler checks the PDF SHA-256, page count, every page label, heading-tree levels, generated ID collisions, parent/child range containment, sibling boundaries, complete body-page coverage, complete retrieval plans, and all strict schemas.

It also compares every Manifest heading text, page index, bounding box, numbered state, and printed parent with every source-PDF heading candidate assigned to a printed section. Figure, Equation, Example, Table, heading, text, and query anchors are checked against the exact source page. Missing, extra, or wrong-page anchors prevent index generation.

The generated `validation_report.json` distinguishes `source_pdf_verification_status: passed` from `file_search_retrieval_status: not_tested`. The latter requires a real GPT file-search acceptance run and is never inferred from the local PDF compiler.

It writes no output when validation fails.

### 3a. Build and compile the Exercise Locator catalog

The committed catalog was generated with the deterministic exercise pipeline:

```bash
python tools/build_dip4e_exercise_manifest.py \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  catalog/dip4e/exercises.yaml

python tools/compile_exercise_index.py \
  catalog/dip4e/exercises.yaml \
  catalog/dip4e/compiled_locator_index.json \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  catalog/dip4e/compiled_exercise_index.json \
  --report catalog/dip4e/exercise_validation_report.json
```

The builder detects each chapter's `Problems` region, preserves two-column reading
order, separates same-page exercises, tracks starred and cross-page problems, and
extracts explicit textbook references. The compiler verifies the exact PDF, requires
all chapters that contain a formal `Problems` section (chapters 2-12 in this PDF),
resolves references against the section index and source anchors,
and writes no final output when validation fails.

Running these commands is an offline release step; normal application startup does
not parse the PDF.

The current reviewed baseline contains 492 exercises in chapters 2-12, 122 starred
exercises, 28 cross-page exercises, 520 page-retrieval steps, and 412 resolved
references. Chapter 1 has no formal `Problems` section in this source PDF. The source
prints `Fig. 10.10.4(a)` in exercise 10.23; the build records an explicit audited
normalization to `Fig. 10.4(a)`, the referenced 3 x 3 Laplacian kernel. Local source-PDF
verification and byte-for-byte repeatability passed; real GPT file-search retrieval
remains `not_tested`.

### 4. Validate GPT instructions

```bash
python tools/validate_prompt.py
```

`PROMPT.md` must remain under 8000 characters and may reference only the real Action and file-search tools.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
```

## Generate the GPT Action schema

```bash
python scripts/export_action_schema.py
```

The script imports the local FastAPI application and always writes:

```text
examples/openai_action_schema_one_book.yaml
```

It does not call or inspect a backend URL. The file uses JSON syntax, which is valid YAML/OpenAPI. The generated schema uses the placeholder server `https://YOUR_DOMAIN`; replace that value with the deployed API domain before importing it into GPT Builder.

The server can start only after a complete compiled index exists:

```bash
export TEACHING_GPT_LOCATOR_INDEX_PATH=./catalog/dip4e/compiled_locator_index.json
export TEACHING_GPT_EXERCISE_INDEX_PATH=./catalog/dip4e/compiled_exercise_index.json
export TEACHING_GPT_API_KEY=replace-me
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker compose -f deploy/docker-compose.yml up --build
```

The image copies `catalog/` into the container. It intentionally exits during startup if `compiled_locator_index.json` has not been generated and committed.

## Repository layout

```text
app/
  api/routes.py
  core/
  models/
    exercise.py
    exercise_manifest.py
    locator.py
    manifest.py
  repositories/locator_repository.py
  repositories/exercise_repository.py
  services/
    exercise_index_compiler.py
    index_compiler.py
    locator_service.py
catalog/
  README.md
  dip4e/
    manifest.yaml
    manifest.sections.01.yaml ... manifest.sections.12.yaml
    compiled_locator_index.json
    compiled_locator_index.sections.01.json ... compiled_locator_index.sections.12.json
    validation_report.json
    exercises.yaml
    exercises.sections.02.yaml ... exercises.sections.12.yaml
    compiled_exercise_index.json
    compiled_exercise_index.sections.02.json ... compiled_exercise_index.sections.12.json
    exercise_validation_report.json
tools/
  extract_pdf_candidates.py
  build_dip4e_exercise_manifest.py
  build_dip4e_manifest.py
  compile_exercise_index.py
  compile_locator_index.py
  validate_prompt.py
scripts/
  export_action_schema.py
tests/
PROMPT.md
ARCHITECTURE_REFACTOR.md
CATALOG_BUILD_WORKFLOW.md
```

## Removed Version 2 capabilities

Version 3 physically removes:

- `SectionPack` and section text windows;
- runtime PDF ingestion;
- full-text search;
- Figure and prerequisite APIs;
- multi-book routes;
- aliases and fuzzy ID fallback;
- derived IDs authored by the parser;
- image transport fields;
- old JSON storage and automatic migration.

The only accepted runtime data contract is Version 3.
