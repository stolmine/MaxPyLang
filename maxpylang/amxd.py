"""
amxd.py — Save and load Max for Live .amxd files.

The .amxd format is a binary wrapper around the same JSON that .maxpat uses.
Three chunks: ampf (device type), meta (reserved), ptch (patcher JSON + null).
Matches the layout of the Live 12 template devices (Misc/Max Devices/*.amxd):
meta holds 4 null bytes, and the ptch payload ends with a newline + null byte.

Reading also accepts the other layouts found in the wild:

- frozen devices, whose ptch payload is an mx@c container (see frozen.py)
- devices without a meta chunk (ampf, then ptch directly; older Max versions)
- Ableton-encrypted devices, whose payload chunk is ciph: these raise
  EncryptedDeviceError and are never decrypted

Outer chunks are tag(4) + little-endian u32 payload size + payload.
Reading never modifies the input file.
"""

import struct
import json
from dataclasses import dataclass, field

from .exceptions import DeviceReadError, EncryptedDeviceError
from .frozen import is_frozen, main_file, parse_container

DEVICE_TYPES = {
    "audio_effect":        b"aaaa",
    "midi_effect":         b"mmmm",
    "instrument":          b"iiii",
    "midi_generator":      b"nagg",
    "midi_transformation": b"natt",
}


def save_amxd(patcher_json, filename, device_type="instrument"):
    """Wrap a patcher JSON dict in .amxd binary format and write to file."""
    if not isinstance(patcher_json, dict):
        raise TypeError(f"patcher_json must be a dict, got {type(patcher_json).__name__}")
    if device_type not in DEVICE_TYPES:
        raise ValueError(f"Unknown device_type {device_type!r}. "
                         f"Choose from: {', '.join(DEVICE_TYPES)}")

    json_bytes = json.dumps(patcher_json, indent=2).encode("utf-8") + b"\n\x00"

    with open(filename, "wb") as f:
        # ampf chunk — device type identifier
        f.write(b"ampf")
        f.write(struct.pack("<I", 4))
        f.write(DEVICE_TYPES[device_type])
        # meta chunk — reserved, 4 null bytes
        f.write(b"meta")
        f.write(struct.pack("<I", 4))
        f.write(b"\x00\x00\x00\x00")
        # ptch chunk — the patcher JSON, null-terminated
        f.write(b"ptch")
        f.write(struct.pack("<I", len(json_bytes)))
        f.write(json_bytes)


DEVICE_TYPE_NAMES = {code: name for name, code in DEVICE_TYPES.items()}


@dataclass
class AmxdDevice:
    """A parsed .amxd file: device type, main patcher JSON and any embedded (frozen) files."""

    path: str
    type_code: str
    chunks: list
    patcher_json: dict = field(repr=False)
    raw_patcher: bytes = field(repr=False)
    frozen: bool = False
    main_name: str = ""
    files: list = field(default_factory=list, repr=False)

    @property
    def device_type(self) -> str:
        return DEVICE_TYPE_NAMES.get(self.type_code.encode("latin-1"), self.type_code)

    @property
    def embedded(self) -> list:
        """Embedded files other than the main patcher."""
        return [f for f in self.files if not f.is_main and f.name != self.main_name]

    def find_file(self, name):
        """Return the embedded file with this name, or None."""
        for f in self.files:
            if f.name == name:
                return f
        return None


def read_chunks(data):
    """Return the outer chunks of an .amxd as a list of (tag, payload_start, payload_end)."""
    chunks = []
    offset = 0
    while offset + 8 <= len(data):
        tag = bytes(data[offset:offset + 4])
        size = struct.unpack("<I", data[offset + 4:offset + 8])[0]
        if offset + 8 + size > len(data):
            raise DeviceReadError(f"Chunk {tag!r} size {size} extends past end of file")
        chunks.append((tag, offset + 8, offset + 8 + size))
        if tag in (b"ptch", b"ciph"):
            break
        offset += 8 + size
    return chunks


def _decode_patcher(raw, where):
    try:
        return json.loads(raw.rstrip(b"\x00"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise DeviceReadError(f"{where} contains invalid JSON: {e}") from e


def parse_amxd(data, path="<bytes>"):
    """Parse .amxd bytes into an AmxdDevice."""
    if data[:4] != b"ampf":
        raise DeviceReadError(f"'{path}' is not an .amxd file (no ampf chunk)")

    chunks = read_chunks(data)
    tags = [tag for tag, _, _ in chunks]
    _, ts, te = chunks[0]
    type_code = data[ts:te].decode("latin-1")

    if b"ciph" in tags:
        raise EncryptedDeviceError(f"encrypted device — cannot be read: '{path}'")
    if b"ptch" not in tags:
        raise DeviceReadError(f"No ptch chunk found in '{path}'")

    _, ps, pe = chunks[tags.index(b"ptch")]
    payload = data[ps:pe]
    names = [t.decode("latin-1") for t in tags]

    if not is_frozen(payload):
        return AmxdDevice(path=path, type_code=type_code, chunks=names,
                          patcher_json=_decode_patcher(payload, f"ptch chunk in '{path}'"),
                          raw_patcher=bytes(payload))

    files = parse_container(payload)
    main = main_file(files)
    return AmxdDevice(path=path, type_code=type_code, chunks=names,
                      patcher_json=_decode_patcher(main.data, f"frozen patcher {main.name!r} in '{path}'"),
                      raw_patcher=main.data, frozen=True, main_name=main.name, files=files)


def read_amxd(filename):
    """Read an .amxd file (plain, frozen or meta-less) into an AmxdDevice. Never writes."""
    with open(filename, "rb") as f:
        data = f.read()
    return parse_amxd(data, str(filename))


def load_amxd(filename):
    """Read an .amxd file and return the patcher JSON dict."""
    return read_amxd(filename).patcher_json
