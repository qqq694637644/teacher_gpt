from app.utils.text import (
    extract_figure_references,
    extract_figures_from_page,
    is_probable_heading_text,
    is_probable_upper_heading,
    parse_section_heading,
)


def test_parse_section_heading():
    assert parse_section_heading("2.4 Image Sampling and Quantization") == (
        "2.4",
        "Image Sampling and Quantization",
    )


def test_upper_heading():
    assert is_probable_upper_heading("IMAGE INTERPOLATION")
    assert not is_probable_upper_heading("FIGURE 2.27 Comparison of interpolation")
    assert not is_probable_upper_heading("B1 AND B2")
    assert not is_probable_upper_heading("B1 OR B2")
    assert not is_probable_upper_heading("B1 AND [NOT (B2)]")
    assert not is_probable_upper_heading("B1 XOR B2")


def test_heading_text_accepts_book_subheadings_but_rejects_diagram_labels():
    assert is_probable_heading_text("Single-Pixel Operations")
    assert is_probable_heading_text("VECTOR AND MATRIX OPERATIONS")
    assert not is_probable_heading_text("B1 AND B2")
    assert not is_probable_heading_text("NOT(B1)")


def test_figure_caption_extraction_does_not_treat_inline_references_as_captions():
    text = "As shown in Fig. 2.38, the mapping is pointwise.\nFIGURE 2.38 Negative transformation"

    assert [figure["figure_id"] for figure in extract_figures_from_page(text)] == ["2.38"]
    assert extract_figure_references(text) == ["2.38"]
