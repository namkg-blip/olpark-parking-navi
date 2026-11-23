"""HWP 5.0 바이너리에서 본문 텍스트를 추출한다 (한글 프로그램 불필요)."""
import struct
import sys
import zlib

import olefile

HWPTAG_PARA_TEXT = 67
CHAR_CTRL = {0, 10, 13} | set(range(24, 32))


def records(data):
    pos = 0
    while pos + 4 <= len(data):
        (header,) = struct.unpack_from("<I", data, pos)
        pos += 4
        tag = header & 0x3FF
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", data, pos)
            pos += 4
        yield tag, data[pos:pos + size]
        pos += size


def para_text(payload):
    units = struct.unpack("<%dH" % (len(payload) // 2), payload)
    out, i = [], 0
    while i < len(units):
        c = units[i]
        if c < 32:
            if c in CHAR_CTRL:
                if c in (10, 13):
                    out.append("\n")
                i += 1
            else:
                if c == 9:
                    out.append("\t")
                i += 8
        else:
            out.append(chr(c))
            i += 1
    return "".join(out)


def extract(path):
    ole = olefile.OleFileIO(path)
    header = ole.openstream("FileHeader").read()
    flags = struct.unpack_from("<I", header, 36)[0]
    compressed = bool(flags & 1)
    distributed = bool(flags & 4)
    prefix = "ViewText" if distributed else "BodyText"
    sections = sorted(
        (e for e in ole.listdir() if e[0] == prefix),
        key=lambda e: int(e[1].replace("Section", "")),
    )
    if distributed:
        raise SystemExit("배포용 문서(ViewText 암호화)라 직접 추출 불가")
    texts = []
    for sec in sections:
        raw = ole.openstream(sec).read()
        if compressed:
            raw = zlib.decompress(raw, -15)
        for tag, payload in records(raw):
            if tag == HWPTAG_PARA_TEXT:
                texts.append(para_text(payload).rstrip("\n"))
    return "\n".join(texts)


if __name__ == "__main__":
    text = extract(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(text)
    print(len(text), "chars")
