"""
devinspect.code

Source code inside a device: js / v8 / jsui / v8ui / node.script files (embedded
in the box, the frozen bundle, or next to the device) and codebox code (gen~
codebox, v8.codebox).

    collect_code() --> one entry per distinct source, with every box that uses it
"""

import os

from ..gen import genexpr_params
from .tree import CODE_CLASSES, box_args, box_word

CODE_EXTS = ("", ".js", ".mjs", ".ts")


def _filename(box):
    for holder in (box, box.get("saved_object_attributes") or {}, box.get("textfile") or {}):
        name = holder.get("filename") if isinstance(holder, dict) else None
        if name:
            return str(name)
    args = [a for a in box_args(box) if not a.startswith("@")]
    return args[0] if args else ""


def _read_source(name, device, folder):
    """Return (origin, text) for a code file name, or (None, None)."""
    for ext in CODE_EXTS:
        candidate = name if not ext or name.endswith(ext) else name + ext
        f = device.find_file(candidate)
        if f is not None:
            return f"bundle:{f.name}", f.text()
    for ext in CODE_EXTS:
        candidate = name if not ext or name.endswith(ext) else name + ext
        full = os.path.join(folder, candidate) if folder else ""
        if full and os.sep not in candidate and os.path.isfile(full):
            with open(full, "rb") as fh:
                return f"file:{candidate}", fh.read().decode("utf-8", errors="replace")
    return None, None


def collect_code(nodes, device):
    """Return [{object, file, origin, text, lines, used_in: [path#id, ...]}].

    gen codebox entries also carry params: the GenExpr Param names.
    """
    folder = os.path.dirname(os.path.abspath(device.path)) if device.path else ""
    entries = {}

    def add(key, entry, where):
        if key not in entries:
            entry["used_in"] = []
            entries[key] = entry
        entries[key]["used_in"].append(where)

    for node in nodes:
        for box in node.boxes():
            where = f"{node.path}#{box.get('id', '')}"
            word = box_word(box)
            code = box.get("code")
            if isinstance(code, str) and code.strip():
                kind = "gen codebox" if node.is_gen else word
                entry = {"object": kind, "file": "", "origin": "box", "text": code}
                if node.is_gen:
                    entry["params"] = genexpr_params(code)
                add(("code", kind, code.strip()), entry, where)
                continue
            if word not in CODE_CLASSES:
                continue
            textfile = box.get("textfile") or {}
            name = _filename(box)
            if isinstance(textfile, dict) and textfile.get("embed") and textfile.get("text"):
                add(("embed", node.path, box.get("id")),
                    {"object": word, "file": name, "origin": "embedded in box",
                     "text": str(textfile["text"])}, where)
                continue
            if not name:
                continue
            origin, text = _read_source(name, device, folder)
            add(("file", name),
                {"object": word, "file": name, "origin": origin or "unresolved",
                 "text": text or ""}, where)

    out = []
    for entry in entries.values():
        entry["text"] = entry["text"].replace("\r\n", "\n").replace("\r", "\n")
        entry["lines"] = entry["text"].count("\n") + 1 if entry["text"] else 0
        out.append(entry)
    return out
