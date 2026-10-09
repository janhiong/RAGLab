from io import BytesIO
import pytest
from pypdf import PdfWriter
from app.ingestion.parsing import InvalidDocument, chunk_pages, parse_document
from app.retrieval import reciprocal_rank_fusion


def test_overlap_and_pages():
    chunks = chunk_pages([(1, "one two three four five six seven"), (2, "page two")], 4, 1)
    assert [(c.content, c.page, c.ordinal) for c in chunks] == [("one two three four", 1, 0), ("four five six seven", 1, 1), ("page two", 2, 2)]
    assert len(chunk_pages([(None, "a b c d")], 4, 1)) == 1


@pytest.mark.parametrize("filename,data", [("empty.txt", b"  "), ("binary.md", b"\xff"), ("program.exe", b"hello"), ("bad.pdf", b"not a pdf"), ("binary.txt", b"a\x00b")])
def test_invalid_documents(filename, data):
    with pytest.raises(InvalidDocument):
        parse_document(filename, data)


def test_scanned_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(InvalidDocument, match="OCR"):
        parse_document("scanned.pdf", buffer.getvalue())


def test_utf8_and_chunk_configuration():
    assert parse_document("notes.md", b"\xef\xbb\xbfHello") == [(None, "Hello")]
    with pytest.raises(ValueError):
        chunk_pages([(None, "text")], 10, 10)


def test_rrf_deduplication():
    a, b = {"id": "a", "score": 100}, {"id": "b", "score": .001}
    result = reciprocal_rank_fusion([[a, a, b], [b, a]], 2)
    assert len(result) == 2
    assert result[0]["id"] == "a"
    assert result[0]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert a["score"] == 100


def test_text_pdf_keeps_page_location():
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 200 Td (Retrieval preserves PDF page citations.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    pages = parse_document('text.pdf', buffer.getvalue())
    assert pages[0][0] == 1 and 'page citations' in pages[0][1]
    assert chunk_pages(pages)[0].page == 1
