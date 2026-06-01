from app.utils.text import is_probable_upper_heading, parse_section_heading


def test_parse_section_heading():
    assert parse_section_heading("2.4 Image Sampling and Quantization") == (
        "2.4",
        "Image Sampling and Quantization",
    )


def test_upper_heading():
    assert is_probable_upper_heading("IMAGE INTERPOLATION")
    assert not is_probable_upper_heading("FIGURE 2.27 Comparison of interpolation")
