"""
frozen.py — Read the mx@c container that frozen Max for Live devices store in ptch.

A frozen device bundles its main patcher and every dependency (abstractions,
js, gen~ code, images, audio) into one container. All integers are big-endian.

Header (16 bytes, at the start of the ptch payload)::

    0   'mx@c'
    4   u32  header size (always 16)
    8   u32  reserved (always 0; high word of the directory offset)
    12  u32  directory offset, from the start of the container

File data follows the header; the first file (the main patcher JSON) is at
offset 16. The directory is a ``dlst`` chunk of ``dire`` entries. Every chunk
is ``tag(4) + u32 size + payload``, where size counts the 8 header bytes::

    dlst <size>
      dire <size>
        type  4-byte type code: JSON (patchers, abstractions), TEXT (js, txt),
              gDSP (gen~), GenX, 'svg ', 'PNG ', JPEG, WAVE, mx64/iLaX/xdll
              (externals), or 4 null bytes; read with trailing spaces dropped
        fnam  file name, null-terminated and padded to 4 bytes
        sz32  u32 file size
        of32  u32 file offset, from the start of the container
        vers  u32 (always 0)
        flag  u32 (0x11 on the main patcher, otherwise almost always 0)
        mdat  u32 modification date, seconds since 1904-01-01
      dire ...

Only the declared dlst is authoritative: some devices that Max re-saved in
place keep stale bytes of an older directory after it.
"""

import datetime
import struct
from dataclasses import dataclass, field

from .exceptions import DeviceReadError

MAGIC = b"mx@c"
MAIN_FLAG = 0x01
_MAC_EPOCH = datetime.datetime(1904, 1, 1, tzinfo=datetime.timezone.utc)


@dataclass
class EmbeddedFile:
    """One file stored in a frozen device."""

    name: str
    type: str
    size: int
    offset: int
    flags: int
    version: int
    mdate: int
    data: bytes = field(repr=False)

    @property
    def is_main(self) -> bool:
        return bool(self.flags & MAIN_FLAG)

    @property
    def modified(self):
        """Modification time as a UTC datetime, or None when unset."""
        if not self.mdate:
            return None
        return _MAC_EPOCH + datetime.timedelta(seconds=self.mdate)

    def text(self) -> str:
        """File contents decoded as UTF-8 (undecodable bytes replaced)."""
        return self.data.rstrip(b"\x00").decode("utf-8", errors="replace")

    def summary(self) -> dict:
        return {"name": self.name, "type": self.type, "size": self.size,
                "main": self.is_main}


def is_frozen(payload) -> bool:
    """Return True if a ptch payload is an mx@c container."""
    return payload[:4] == MAGIC


def _chunks(buf, start, end, where):
    """Yield (tag, payload_start, payload_end) for big-endian chunks in buf[start:end]."""
    pos = start
    while pos < end:
        if pos + 8 > end:
            raise DeviceReadError(f"Truncated chunk header in {where} at offset {pos}")
        tag = bytes(buf[pos:pos + 4])
        size = struct.unpack(">I", buf[pos + 4:pos + 8])[0]
        if size < 8 or pos + size > end:
            raise DeviceReadError(f"Chunk {tag!r} in {where} at offset {pos} "
                                  f"has invalid size {size}")
        yield tag, pos + 8, pos + size
        pos += size


def _type_code(raw):
    if raw == b"\x00\x00\x00\x00":
        return ""
    return raw.decode("latin-1").rstrip("\x00 ")


def parse_container(payload):
    """
    Parse an mx@c container and return its files in directory order.

    payload --> the ptch chunk bytes, starting with 'mx@c'
    """
    if not is_frozen(payload):
        raise DeviceReadError("ptch payload is not an mx@c container")
    if len(payload) < 16:
        raise DeviceReadError("mx@c header is truncated")

    header_size, reserved, dir_offset = struct.unpack(">III", payload[4:16])
    if header_size != 16:
        raise DeviceReadError(f"Unexpected mx@c header size {header_size}")
    if reserved:
        raise DeviceReadError(f"Unsupported mx@c directory offset high word {reserved}")
    if payload[dir_offset:dir_offset + 4] != b"dlst":
        raise DeviceReadError(f"No dlst directory at mx@c offset {dir_offset}")

    dlst_size = struct.unpack(">I", payload[dir_offset + 4:dir_offset + 8])[0]
    dlst_end = dir_offset + dlst_size
    if dlst_end > len(payload):
        raise DeviceReadError("mx@c directory extends past the end of the container")

    files = []
    for tag, start, end in _chunks(payload, dir_offset + 8, dlst_end, "dlst"):
        if tag != b"dire":
            raise DeviceReadError(f"Unexpected {tag!r} entry in mx@c directory")
        fields = {ftag: payload[fs:fe] for ftag, fs, fe in _chunks(payload, start, end, "dire")}
        missing = {b"type", b"fnam", b"sz32", b"of32"} - fields.keys()
        if missing:
            raise DeviceReadError(f"mx@c directory entry lacks {sorted(missing)}")

        size = struct.unpack(">I", fields[b"sz32"][:4])[0]
        offset = struct.unpack(">I", fields[b"of32"][:4])[0]
        name = fields[b"fnam"].split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        if offset + size > dir_offset:
            raise DeviceReadError(f"Embedded file {name!r} overlaps the mx@c directory")

        def opt(tag):
            raw = fields.get(tag)
            return struct.unpack(">I", raw[:4])[0] if raw and len(raw) >= 4 else 0

        files.append(EmbeddedFile(
            name=name,
            type=_type_code(fields[b"type"][:4]),
            size=size,
            offset=offset,
            flags=opt(b"flag"),
            version=opt(b"vers"),
            mdate=opt(b"mdat"),
            data=bytes(payload[offset:offset + size]),
        ))

    if not files:
        raise DeviceReadError("mx@c directory is empty")
    return files


def main_file(files):
    """Return the main patcher entry: the one flagged main, else the first JSON file."""
    for f in files:
        if f.is_main:
            return f
    for f in files:
        if f.type == "JSON":
            return f
    raise DeviceReadError("mx@c container has no patcher JSON")
