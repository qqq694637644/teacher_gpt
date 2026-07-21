from app.core.config import Settings
from app.services.pdf_ingestor import PDFIngestor, SectionCandidate
from app.services.section_service import SectionService
from app.services.storage import JsonStore


def _line(
    line_index: int,
    text: str,
    *,
    size: float = 10.0,
    font: str = "TimesTen-Roman",
    bold: bool = False,
) -> dict:
    return {
        "line_index": line_index,
        "text": text,
        "bbox": [120.0, float(line_index * 12), 480.0, float(line_index * 12 + 10)],
        "font_size": size,
        "fonts": [font],
        "is_bold": bold,
    }


def _dip4e_page_records() -> list[dict]:
    """Minimal layout fixture based on the supplied DIP 4e pages around Fig. 2.37."""
    heading = {"size": 10.954451560974121, "font": "Futura-Heavy", "bold": True}
    figure_caption = {"size": 8.5, "font": "Futura-CondensedBold", "bold": True}
    example_label = {"size": 9.85900592803955, "font": "Futura-CondensedBold", "bold": True}
    diagram = {"size": 7.0, "font": "TimesTen-Roman", "bold": False}
    pages = [
        [
            _line(0, "Logical Operations", **heading),
            _line(1, "B1 and B2, respectively, are illustrated in Fig. 2.37."),
            _line(2, "SPATIAL OPERATIONS", **heading),
            _line(3, "Spatial operations are performed directly on the pixels of an image."),
            _line(4, "FIGURE 2.37 Illustration of logical operations", **figure_caption),
            _line(5, "B1 AND B2", **diagram),
            _line(6, "B1 OR B2", **diagram),
            _line(7, "B1 AND [NOT (B2)]", **diagram),
            _line(8, "B1 XOR B2", **diagram),
        ],
        [
            _line(
                0,
                "2.6 Introduction to the Basic Mathematical Tools Used in Digital Image Processing 99",
                size=11.0,
                font="Futura-CondensedBold",
                bold=True,
            ),
            _line(1, "Single-Pixel Operations", **heading),
            _line(2, "As shown in Fig. 2.38, the single-pixel mapping is s = T(z). (2-42)"),
            _line(3, "Neighborhood Operations", **heading),
            _line(4, "A neighborhood operation is g(x,y)=T[Sxy]. (2-43)"),
            _line(5, "FIGURE 2.38 Negative transformation", **figure_caption),
        ],
        [
            _line(0, "This sentence continues the neighborhood discussion."),
            _line(1, "Geometric Transformations", **heading),
            _line(2, "Coordinate transformation is expressed by Eq. (2-44)."),
            _line(3, "EXAMPLE 2.9 : Geometric transformation.", **example_label),
            _line(4, "Image Registration", **heading),
            _line(5, "Registration uses corresponding tie points. (2-46)"),
        ],
        [
            _line(0, "The registration coefficients satisfy Eq. (2-47)."),
            _line(1, "EXAMPLE 2.10 : Image registration.", **example_label),
            _line(2, "VECTOR AND MATRIX OPERATIONS", **heading),
            _line(3, "Matrix multiplication is defined by Eq. (2-48)."),
            _line(4, "IMAGE TRANSFORMS", **heading),
            _line(5, "The forward transform is defined by Eq. (2-55)."),
        ],
    ]
    return [
        {
            "page_index": page_number - 1,
            "page_number": page_number,
            "body_font_size": 10.0,
            "lines": lines,
            "text": "\n".join(line["text"] for line in lines),
        }
        for page_number, lines in enumerate(pages, start=1)
    ]


def test_dip4e_layout_headings_exclude_figure_labels(tmp_path):
    ingestor = PDFIngestor(Settings(data_dir=tmp_path))
    parent = SectionCandidate(
        section_id="2.6",
        title="Introduction to the Basic Mathematical Tools Used in Digital Image Processing",
        level=2,
        page_start=1,
        page_end=4,
    )

    derived = ingestor._derive_subsections([parent], _dip4e_page_records())

    assert [section.title for section in derived] == [
        "Logical Operations",
        "Spatial Operations",
        "Single-Pixel Operations",
        "Neighborhood Operations",
        "Geometric Transformations",
        "Image Registration",
        "Vector And Matrix Operations",
        "Image Transforms",
    ]
    assert all("B1" not in section.title for section in derived)


def test_dip4e_exact_line_boundaries_prevent_repeated_text_and_resource_pollution(tmp_path):
    settings = Settings(data_dir=tmp_path)
    ingestor = PDFIngestor(settings)
    parent = SectionCandidate(
        section_id="2.6",
        title="Introduction to the Basic Mathematical Tools Used in Digital Image Processing",
        level=2,
        page_start=1,
        page_end=4,
    )
    page_records = _dip4e_page_records()
    derived = ingestor._derive_subsections([parent], page_records)
    sections = [parent, *derived]
    page_texts = {
        section.section_id: ingestor._section_page_texts(section, page_records)
        for section in sections
    }

    single_pixel = next(section for section in derived if section.title == "Single-Pixel Operations")
    single_pixel_text = "\n".join(
        fragment["text"] for fragment in page_texts[single_pixel.section_id]
    )
    assert single_pixel_text.startswith("Single-Pixel Operations")
    assert "(2-42)" in single_pixel_text
    assert "Fig. 2.38" in single_pixel_text
    assert "FIGURE 2.38" not in single_pixel_text
    assert "Neighborhood Operations" not in single_pixel_text
    assert "(2-43)" not in single_pixel_text
    assert "B1 and B2, respectively." not in single_pixel_text

    figure_map = ingestor._build_figure_map(page_records, sections, page_texts)
    section_map = ingestor._build_section_map(sections)
    ingestor._write_section_packs(
        "dip4e",
        sections,
        section_map,
        figure_map,
        page_texts,
    )

    store = JsonStore(settings)
    store.save_json("dip4e", "book_meta.json", {"book_id": "dip4e", "version": "2"})
    service = SectionService(store=store)
    single_pack = service.get_section("dip4e", single_pixel.section_id)
    logical = next(section for section in derived if section.title == "Logical Operations")
    logical_pack = service.get_section("dip4e", logical.section_id)
    spatial = next(section for section in derived if section.title == "Spatial Operations")
    spatial_pack = service.get_section("dip4e", spatial.section_id)
    neighborhood = next(section for section in derived if section.title == "Neighborhood Operations")
    neighborhood_pack = service.get_section("dip4e", neighborhood.section_id)
    image_registration = next(section for section in derived if section.title == "Image Registration")
    image_registration_pack = service.get_section("dip4e", image_registration.section_id)
    vector = next(section for section in derived if section.title == "Vector And Matrix Operations")
    vector_pack = service.get_section("dip4e", vector.section_id)

    assert [figure.figure_id for figure in logical_pack.figures] == ["2.37"]
    assert spatial_pack.figures == []
    assert all("FIGURE 2.37" not in block.text for block in spatial_pack.text_blocks)
    assert all("B1 AND" not in block.text for block in spatial_pack.text_blocks)
    assert [equation.equation_id for equation in single_pack.equations] == ["2-42"]
    assert [figure.figure_id for figure in single_pack.figures] == ["2.38"]
    assert [equation.equation_id for equation in neighborhood_pack.equations] == ["2-43"]
    assert neighborhood_pack.figures == []
    assert [equation.equation_id for equation in image_registration_pack.equations] == ["2-46", "2-47"]
    assert [example.example_id for example in image_registration_pack.examples] == ["2.10"]
    assert [equation.equation_id for equation in vector_pack.equations] == ["2-48"]
    assert vector_pack.examples == []
