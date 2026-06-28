"""Чтение резюме/шаблонов/карты: PDF (текстовый слой) и текстовые форматы.

Без сети: PDF собирается в памяти минимальным валидным байт-стримом, текст
извлекается через pypdf. Покрывает резолв относительного пути от base_dir.
"""

from __future__ import annotations

from pathlib import Path

from job_agent.pipeline import _read_document


def _make_pdf(text: str) -> bytes:
    """Минимальный валидный PDF с одним текстовым объектом (ASCII в Tj)."""
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"",  # contents — заполняется ниже
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    stream = b"BT /F1 24 Tf 72 700 Td (" + text.encode("latin-1") + b") Tj ET"
    objs[3] = b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream"

    out = b"%PDF-1.4\n"
    offsets: list[int] = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj" + obj + b"endobj\n"
    xref_off = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        b"trailer<</Size "
        + str(len(objs) + 1).encode()
        + b"/Root 1 0 R>>\nstartxref\n"
        + str(xref_off).encode()
        + b"\n%%EOF"
    )
    return out


def test_read_document_extracts_pdf_text(tmp_path: Path) -> None:
    (tmp_path / "cv.pdf").write_bytes(_make_pdf("Senior Backend Engineer Python"))
    text = _read_document("cv.pdf", tmp_path)
    assert "Senior Backend Engineer Python" in text


def test_read_document_pdf_suffix_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "CV.PDF").write_bytes(_make_pdf("Product Manager"))
    assert "Product Manager" in _read_document("CV.PDF", tmp_path)


def test_read_document_reads_text_as_utf8(tmp_path: Path) -> None:
    (tmp_path / "map.md").write_text("# Карта\nпродуктовые роли b2b", encoding="utf-8")
    text = _read_document("map.md", tmp_path)
    assert "продуктовые роли" in text


def test_read_document_resolves_absolute_path(tmp_path: Path) -> None:
    abs_pdf = tmp_path / "sub" / "resume.pdf"
    abs_pdf.parent.mkdir()
    abs_pdf.write_bytes(_make_pdf("Tech Lead"))
    # абсолютный путь не привязывается к base_dir
    assert "Tech Lead" in _read_document(abs_pdf, Path("/nonexistent"))
