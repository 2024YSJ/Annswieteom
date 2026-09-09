from __future__ import annotations

import struct
import zlib
from io import BytesIO
from pathlib import Path

DOCUMENT_EXTENSIONS = (".txt", ".md", ".docx", ".hwp")

# HWP 5.0 record tag for a paragraph's text content (HWPTAG_BEGIN=0x10 + 51).
_HWPTAG_PARA_TEXT = 0x10 + 51


class UnsupportedDocumentError(Exception):
    """Raised when a document's bytes can't be turned into text at all —
    wrong/corrupt format, or (for .hwp) password-protected/distribution-locked."""


def extract_text_from_document(content: bytes, filename: str) -> str:
    """Extract plain text from an uploaded document, dispatching on extension.

    Takes raw bytes rather than a filesystem path — same storage-agnostic
    convention the removed ocr.py::extract_text_from_image used.
    """
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md"):
        return _decode_text(content)
    if ext == ".docx":
        return _extract_docx(content)
    if ext == ".hwp":
        return _extract_hwp(content)
    raise UnsupportedDocumentError(f"Unsupported document extension: {ext}")


def _decode_text(content: bytes) -> str:
    # Plain text files from Korean users are often EUC-KR/CP949 (Windows
    # Notepad's historical default), not UTF-8 — try UTF-8 first since it's
    # the common case, then fall back rather than mangling the whole file.
    for encoding in ("utf-8", "cp949", "euc-kr"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _extract_docx(content: bytes) -> str:
    from docx import Document  # local import: only needed on this path

    try:
        doc = Document(BytesIO(content))
    except Exception as exc:
        raise UnsupportedDocumentError(f"Not a valid .docx file: {exc}") from exc

    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_hwp(content: bytes) -> str:
    """Best-effort text extraction from an HWP 5.0 (OLE compound file) binary.

    No actively-maintained pip package handles this well (pyhwp-style
    packages have been unmaintained for years), so this reads the OLE
    container with `olefile` and walks the HWP record structure directly:
    each BodyText/SectionN stream is optionally zlib-deflated, then holds a
    sequence of (tag, level, size) headers each followed by that many bytes
    of payload; HWPTAG_PARA_TEXT payloads are UTF-16LE paragraph text with
    embedded control characters (inline objects, tabs, etc.) below U+0020
    that are stripped rather than interpreted.

    Limitations: distribution-locked ("배포용") documents obfuscate the
    stream layout differently, and password-protected or pre-5.0 files won't
    parse — all of these raise UnsupportedDocumentError rather than
    returning garbage, so the caller can surface a clear "이 한글 파일은 읽을
    수 없어요" message instead of silently mis-chunking noise into evidence.
    """
    import olefile

    try:
        ole = olefile.OleFileIO(BytesIO(content))
    except Exception as exc:
        raise UnsupportedDocumentError(f"Not a valid .hwp (OLE) file: {exc}") from exc

    try:
        if not ole.exists("FileHeader"):
            raise UnsupportedDocumentError("Missing HWP FileHeader stream")
        header = ole.openstream("FileHeader").read()
        # Byte 36 of the 256-byte FileHeader is a property bitfield; bit 0 is
        # the "streams are zlib-compressed" flag (HWP 5.0 spec).
        is_compressed = len(header) > 36 and (header[36] & 0x01) != 0

        section_paths = sorted(
            (p for p in ole.listdir() if len(p) == 2 and p[0] == "BodyText" and p[1].startswith("Section")),
            key=lambda p: int(p[1][len("Section"):]),
        )
        if not section_paths:
            raise UnsupportedDocumentError("No BodyText sections found")

        paragraphs: list[str] = []
        for path in section_paths:
            raw = ole.openstream(path).read()
            data = zlib.decompressobj(-15).decompress(raw) if is_compressed else raw
            paragraphs.extend(_extract_paragraphs_from_section(data))

        text = "\n\n".join(p for p in paragraphs if p.strip())
        if not text.strip():
            raise UnsupportedDocumentError("No extractable text (possibly a distribution-locked document)")
        return text
    finally:
        ole.close()


def _extract_paragraphs_from_section(data: bytes) -> list[str]:
    paragraphs: list[str] = []
    offset = 0
    length = len(data)
    while offset + 4 <= length:
        header = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        tag_id = header & 0x3FF
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:  # extended size follows as a separate 4-byte field
            if offset + 4 > length:
                break
            size = struct.unpack_from("<I", data, offset)[0]
            offset += 4
        payload = data[offset:offset + size]
        offset += size

        if tag_id == _HWPTAG_PARA_TEXT:
            paragraphs.append(_decode_para_text(payload))

    return paragraphs


def _decode_para_text(payload: bytes) -> str:
    # UTF-16LE code units; anything below U+0020 is a control character (line
    # break markers, inline object/field placeholders, tab, etc.) rather than
    # visible text — drop those instead of rendering them as stray glyphs.
    try:
        units = struct.unpack(f"<{len(payload) // 2}H", payload[: len(payload) - (len(payload) % 2)])
    except struct.error:
        return ""
    chars = [chr(u) for u in units if u >= 0x20]
    return "".join(chars)
