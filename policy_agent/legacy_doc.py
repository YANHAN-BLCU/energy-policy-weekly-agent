"""MS-DOC piece-table text extraction; no Word installation or byte scraping."""
from io import BytesIO
import re
import struct


def _u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def word_stream_text(word, table):
    if len(word) < 160 or _u16(word, 0) != 0xA5EC or _u16(word, 2) < 0xC1:
        raise ValueError("UNSUPPORTED_WORD_FIB")
    flags = _u16(word, 10)
    if flags & 0x8100:
        raise ValueError("ENCRYPTED_WORD_DOCUMENT")
    pos = 34 + _u16(word, 32) * 2
    lw_count = _u16(word, pos)
    lw_start = pos + 2
    if lw_count < 11:
        raise ValueError("INVALID_WORD_CHARACTER_COUNTS")
    counts = [_u32(word, lw_start + 4 * index) for index in (3, 4, 5, 7, 8, 9, 10)]
    if not 0 < counts[0] <= 10_000_000:
        raise ValueError("EMPTY_OR_OVERSIZED_WORD_BODY")
    pairs = lw_start + lw_count * 4 + 2
    fc, length = _u32(word, pairs + 33 * 8), _u32(word, pairs + 33 * 8 + 4)
    if not length or fc + length > len(table):
        raise ValueError("WORD_PIECE_TABLE_MISSING")
    clx = table[fc:fc + length]
    cursor = 0
    while cursor < len(clx) and clx[cursor] == 1:
        cursor += 3 + _u16(clx, cursor + 1)
    if cursor + 5 > len(clx) or clx[cursor] != 2:
        raise ValueError("INVALID_WORD_PIECE_TABLE")
    size = _u32(clx, cursor + 1)
    plc = clx[cursor + 5:cursor + 5 + size]
    if len(plc) != size or size < 16 or (size - 4) % 12:
        raise ValueError("TRUNCATED_WORD_PIECE_TABLE")
    count = (size - 4) // 12
    cps = [_u32(plc, index * 4) for index in range(count + 1)]
    needed = sum(counts)
    if cps[0] != 0 or cps[-1] < needed or any(a > b for a, b in zip(cps, cps[1:])):
        raise ValueError("INCOMPLETE_WORD_CHARACTER_COVERAGE")
    parts = []
    for index in range(count):
        start, end = cps[index], min(cps[index + 1], needed)
        if start >= needed:
            break
        encoded_fc = _u32(plc, (count + 1) * 4 + index * 8 + 2)
        compressed = bool(encoded_fc & 0x40000000)
        offset = encoded_fc & 0x3FFFFFFF
        offset = offset // 2 if compressed else offset
        byte_count = (end - start) * (1 if compressed else 2)
        if offset + byte_count > len(word):
            raise ValueError("TRUNCATED_WORD_TEXT_PIECE")
        raw = word[offset:offset + byte_count]
        parts.append(raw.decode("cp1252" if compressed else "utf-16-le", errors="strict"))
    text = "".join(parts)
    if len(text.encode("utf-16-le")) // 2 != needed:
        raise ValueError("WORD_TEXT_CHARACTER_COUNT_MISMATCH")
    # Word fields retain displayed results; instructions do not become policy text.
    text = re.sub(r"\x13[^\x13\x14\x15]*\x14([^\x13\x15]*)\x15", r"\1", text)
    text = re.sub(r"\x13[^\x13\x15]*\x15", "", text)
    text = text.replace("\r", "\n").replace("\x07", "\t").replace("\x0b", "\n").replace("\x0c", "\n")
    return re.sub(r"[\x00-\x08\x0e-\x1f]", "", text), {"main_characters": counts[0], "story_characters": needed, "pieces": count}


def extract_legacy_document(content):
    import olefile
    with olefile.OleFileIO(BytesIO(content)) as container:
        if not container.exists("WordDocument"):
            raise ValueError("UNSUPPORTED_NATIVE_WPS_FORMAT")
        word = container.openstream("WordDocument").read()
        stream = "1Table" if _u16(word, 10) & 0x0200 else "0Table"
        if not container.exists(stream):
            raise ValueError("WORD_TABLE_STREAM_MISSING")
        return word_stream_text(word, container.openstream(stream).read())
