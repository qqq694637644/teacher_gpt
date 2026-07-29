import pytest

from app.models.manifest import BookManifest, LearningUnitManifest
from app.services.index_compiler import LocatorIndexCompiler
from tests.helpers import complete_manifest, page_range, step


def test_compiler_generates_ids_from_order_and_tree_depth() -> None:
    compiled = LocatorIndexCompiler().compile(complete_manifest())

    assert compiled.sections["2"].section_kind == "printed"
    assert compiled.sections["2.6"].printed_section_id == "2.6"
    assert compiled.sections["2.6.1"].title == "Elementwise versus Matrix Operations"
    assert compiled.sections["2.6.4"].title == "Set and Logical Operations"
    assert compiled.sections["2.6.4.1"].title == "Basic Set Operations"
    assert compiled.sections["2.6.4.2"].title == "Logical Operations"
    assert compiled.sections["2.6.5"].title == "Spatial Operations"
    assert compiled.sections["2.6.5"].parent_section_id == "2.6"
    assert compiled.sections["2.6.5.1"].title == "Single-Pixel Operations"
    assert compiled.sections["2.6.5.4"].title == "Image Registration"
    assert compiled.sections["2.6.6"].title == "Vector and Matrix Operations"
    assert compiled.sections["2.6.7"].title == "Image Transforms"
    assert compiled.sections["2.6.8"].title == "Image Intensities as Random Variables"
    assert "2.6.9" not in compiled.sections


def test_manifest_rejects_child_at_the_same_structural_level() -> None:
    with pytest.raises(ValueError, match="one structural level deeper"):
        LearningUnitManifest(
            title="Spatial Operations",
            source_heading="SPATIAL OPERATIONS",
            source_location={
                "page": {"pdf_page_index": 2, "pdf_page_number": 3, "printed_page_label": "100"},
                "bbox": [120.0, 100.0, 320.0, 112.0],
            },
            source_level=1,
            page_range=page_range(2, 2),
            retrieval_plan=[step(2, heading="Spatial Operations")],
            children=[
                LearningUnitManifest(
                    title="Image Registration",
                    source_heading="Image Registration",
                    source_location={
                        "page": {
                            "pdf_page_index": 3,
                            "pdf_page_number": 4,
                            "printed_page_label": "101",
                        },
                        "bbox": [120.0, 100.0, 320.0, 112.0],
                    },
                    source_level=1,
                    page_range=page_range(3, 3),
                    retrieval_plan=[step(3, heading="Image Registration")],
                )
            ],
        )


def test_manifest_has_no_field_for_manual_project_id() -> None:
    raw = {
        "title": "Spatial Operations",
        "source_heading": "SPATIAL OPERATIONS",
        "source_location": {
            "page": {"pdf_page_index": 2, "pdf_page_number": 3, "printed_page_label": "100"},
            "bbox": [120.0, 100.0, 320.0, 112.0],
        },
        "source_level": 1,
        "page_range": page_range(2, 2).model_dump(),
        "retrieval_plan": [step(2, heading="Spatial Operations").model_dump()],
        "section_id": "2.6.99",
    }
    with pytest.raises(ValueError, match="section_id"):
        LearningUnitManifest.model_validate(raw)


def test_compiler_rejects_siblings_not_in_pdf_appearance_order() -> None:
    raw = complete_manifest().model_dump(mode="json")
    units = raw["printed_sections"][1]["learning_units"]
    units[0], units[1] = units[1], units[0]
    manifest = BookManifest.model_validate(raw)

    with pytest.raises(ValueError, match="PDF appearance order"):
        LocatorIndexCompiler().compile(manifest)
