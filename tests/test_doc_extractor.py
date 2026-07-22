import io
import struct

from app.extractor.doc_extractor import DOCExtractor


class _FakeOle:
    """Minimal stand-in for olefile.OleFileIO exposing exists()/openstream()."""

    def __init__(self, streams: dict[str, bytes]) -> None:
        self._streams = streams

    def exists(self, name: str) -> bool:
        return name in self._streams

    def openstream(self, name: str):
        return io.BytesIO(self._streams[name])


def _build_fake_doc(text: str) -> tuple[bytes, bytes]:
    """
    Build a minimal WordDocument stream + "0Table" stream whose FIB and
    single-piece Clx/PlcPcd point at `text` encoded as UTF-16LE, mirroring
    what a real (uncompressed, single-piece) .doc produces.
    """
    encoded = text.encode("utf-16-le")
    n_chars = len(text)
    text_offset = 460

    word_doc = bytearray(500)
    struct.pack_into("<H", word_doc, 10, 0)  # flags: fWhichTblStm=0 -> "0Table"
    struct.pack_into("<H", word_doc, 152, 40)  # cbRgFcLcb: enough entries for fcClx
    word_doc[text_offset:text_offset + len(encoded)] = encoded

    cps = struct.pack("<II", 0, n_chars)
    pcd = struct.pack("<H", 0) + struct.pack("<I", text_offset) + struct.pack("<H", 0)
    plc_pcd = cps + pcd
    clx = bytes([2]) + struct.pack("<I", len(plc_pcd)) + plc_pcd

    struct.pack_into("<II", word_doc, 154 + 33 * 8, 0, len(clx))  # fcClx/lcbClx
    return bytes(word_doc), clx


def test_extract_doc_text_decodes_piece_table():
    text = "1. Savol matni?\rA) Noto'g'ri\rB) To'g'ri*\r"
    word_doc, table = _build_fake_doc(text)
    ole = _FakeOle({"0Table": table})

    result = DOCExtractor._extract_doc_text(ole, word_doc)

    assert result == "1. Savol matni?\nA) Noto'g'ri\nB) To'g'ri*\n"


def test_extract_doc_text_falls_back_when_table_stream_missing():
    word_doc = b"plain ascii fallback text here" + b"\x00" * 200
    ole = _FakeOle({})

    result = DOCExtractor._extract_doc_text(ole, word_doc)

    assert "plain ascii fallback text here" in result
