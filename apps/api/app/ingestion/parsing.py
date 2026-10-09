from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
MAX_PAGES = 200
CHUNK_WORDS = 180
OVERLAP_WORDS = 30
CHUNK_VERSION = "whitespace-v1-180-30"


class InvalidDocument(ValueError):
    pass


@dataclass(frozen=True)
class Chunk:
    content: str
    page: int | None
    ordinal: int


def parse_document(filename: str, data: bytes) -> list[tuple[int | None, str]]:
    suffix = Path(filename).suffix.lower()
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidDocument("Files must be no larger than 5 MiB.")
    if suffix not in {".pdf", ".txt", ".md"}:
        raise InvalidDocument("Use a text-based PDF, TXT, or Markdown file.")
    if suffix == ".pdf":
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise InvalidDocument("Encrypted PDFs are unsupported.")
            if len(reader.pages) > MAX_PAGES:
                raise InvalidDocument("PDFs must contain at most 200 pages.")
            pages = []
            count = 0
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                count += len(text)
                if count > MAX_TEXT_CHARS:
                    raise InvalidDocument("Parsed text exceeds 200,000 characters.")
                pages.append((number, text))
        except InvalidDocument:
            raise
        except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
            raise InvalidDocument("The PDF could not be parsed.") from exc
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InvalidDocument("TXT and Markdown files must use UTF-8 encoding.") from exc
        if "\x00" in text:
            raise InvalidDocument("Binary text files are unsupported.")
        pages = [(None, text)]
    if sum(len(text) for _, text in pages) > MAX_TEXT_CHARS:
        raise InvalidDocument("Parsed text exceeds 200,000 characters.")
    if not any(text.strip() for _, text in pages):
        raise InvalidDocument("No extractable text found. Scanned PDFs need OCR, which is unsupported.")
    return pages


def chunk_pages(pages: list[tuple[int | None, str]], size: int = CHUNK_WORDS, overlap: int = OVERLAP_WORDS) -> list[Chunk]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Chunk size must be positive and overlap smaller than size.")
    chunks = []
    for page, text in pages:
        words = text.split()
        start = 0
        while start < len(words):
            chunks.append(Chunk(" ".join(words[start:start + size]), page, len(chunks)))
            if start + size >= len(words):
                break
            start += size - overlap
    if len(chunks) > 500:
        raise InvalidDocument("Document produces too many chunks (maximum 500).")
    return chunks
