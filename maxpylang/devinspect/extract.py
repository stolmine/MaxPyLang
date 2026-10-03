"""
devinspect.extract

Write a device's contents to a folder, and summarize whole device folders.

    extract() --> main patch as <name>.maxpat plus every embedded file
    survey_device() --> one summary dict for a device (never raises on bad files)
    survey() --> survey_device() for every .amxd under a folder
"""

import os
import unicodedata

from maxpylang.amxd import read_amxd
from maxpylang.exceptions import DeviceReadError, EncryptedDeviceError

from .model import load_any
from .params import collect_params
from .tree import walk_device


def _safe_name(name, fallback):
    base = os.path.basename(name.replace("\\", "/")).strip()
    if base in ("", ".", ".."):
        base = fallback
    return base


def _unique(path, used):
    root, ext = os.path.splitext(path)
    candidate, n = path, 2
    while candidate in used:
        candidate = f"{root}-{n}{ext}"
        n += 1
    used.add(candidate)
    return candidate


def extract(path, outdir):
    """
    Write the main patcher of a device as <name>.maxpat and its embedded files into outdir.

    The input device is only read. Returns the list of written file paths.
    """
    device = load_any(path)
    source = os.path.realpath(str(path))
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(str(path)))[0]
    used = set()
    written = []

    def write(name, data):
        target = _unique(os.path.join(outdir, name), used)
        if os.path.realpath(target) == source:
            raise ValueError(f"Refusing to overwrite the input device '{source}'")
        with open(target, "wb") as f:
            f.write(data)
        written.append(target)

    write(f"{stem}.maxpat", device.raw_patcher.rstrip(b"\x00"))
    for i, f in enumerate(device.embedded):
        write(_safe_name(f.name, f"file{i}"), f.data)
    return written


def survey_device(path, root=None):
    """Summarize one .amxd: name, type, status, #params, #files, size. Never raises on bad input."""
    row = {"name": unicodedata.normalize("NFC", os.path.splitext(os.path.basename(path))[0]),
           "path": os.path.relpath(path, root) if root else path,
           "type": "", "status": "", "params": None, "files": 0, "size": None}
    try:
        row["size"] = os.path.getsize(path)
        device = read_amxd(path)
    except EncryptedDeviceError:
        row["status"] = "encrypted"
        return row
    except OSError as e:
        row["status"] = "unreadable"
        row["error"] = e.strerror or type(e).__name__
        return row
    except DeviceReadError as e:
        row["status"] = f"error ({e})"
        return row
    row["type"] = device.device_type
    row["status"] = "frozen" if device.frozen else "plain"
    row["files"] = len(device.embedded)
    nodes, _ = walk_device(device)
    row["params"] = len(collect_params(nodes, set()))
    return row


def survey(folder):
    """Yield survey_device() rows for every .amxd under folder, sorted by path."""
    paths = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        paths += [os.path.join(dirpath, n) for n in filenames
                  if n.lower().endswith(".amxd") and not n.startswith("._")]
    for p in sorted(paths):
        yield survey_device(p, folder)
