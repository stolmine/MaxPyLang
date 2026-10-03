"""
devinspect.tree

Walk a device's patcher hierarchy: embedded subpatchers (p, patcher, bpatcher,
gen~ ...) and abstractions resolved from the frozen bundle or the device folder.

    walk_device() --> list of PatcherNode, root first, parents before children
    box_word() --> the object class a box stands for ("cycle~", "live.dial", ...)
"""

import json
import os
from dataclasses import dataclass, field

MAX_DEPTH = 32

GEN_CLASSES = frozenset({"gen~", "gen", "mc.gen~", "jit.gen", "jit.gl.pix", "jit.pix", "rnbo~"})
POLY_CLASSES = frozenset({"poly~", "mc.poly~", "pfft~"})
CODE_CLASSES = frozenset({"js", "v8", "node.script", "jsui", "v8ui", "jstrigger"})
PATCHER_EXTS = ("", ".maxpat", ".amxd", ".json", ".maxhelp")
GEN_EXTS = ("", ".gendsp", ".genjit", ".genexpr")


@dataclass
class PatcherNode:
    """One patcher in the hierarchy."""

    path: str
    kind: str
    depth: int
    patcher: dict = field(repr=False)
    box_id: str = ""
    parent: str = ""
    text: str = ""
    source: str = "embedded"
    is_gen: bool = False

    def boxes(self):
        return [b["box"] for b in self.patcher.get("boxes", []) if "box" in b]

    def lines(self):
        return [ln["patchline"] for ln in self.patcher.get("lines", []) if "patchline" in ln]

    def summary(self) -> dict:
        return {"path": self.path, "kind": self.kind, "depth": self.depth,
                "source": self.source, "box_id": self.box_id,
                "num_boxes": len(self.patcher.get("boxes", [])),
                "num_lines": len(self.patcher.get("lines", []))}


def box_text(box) -> str:
    return box.get("text") or ""


def box_word(box) -> str:
    """Return the object class of a box: its maxclass, or the first word of a newobj."""
    if box.get("maxclass") == "newobj":
        text = box_text(box).strip()
        return text.split()[0] if text else ""
    return box.get("maxclass", "")


def box_args(box) -> list:
    if box.get("maxclass") != "newobj":
        return []
    return box_text(box).split()[1:]


def positional_args(box) -> list:
    """Return a newobj's arguments before the first @attribute."""
    out = []
    for arg in box_args(box):
        if arg.startswith("@"):
            break
        out.append(arg)
    return out


def box_attr_arg(box, name):
    """Return the value of '@name value' in a newobj's text, or None."""
    args = box_args(box)
    key = "@" + name
    if key in args:
        i = args.index(key)
        if i + 1 < len(args):
            return args[i + 1]
    return None


class Resolver:
    """Finds abstraction files in the frozen bundle, then next to the device. Read-only."""

    def __init__(self, device):
        self.device = device
        self.folder = os.path.dirname(os.path.abspath(device.path)) if device.path else ""
        self._cache = {}

    def find(self, name, exts):
        """Return (source label, patcher dict) for an abstraction name, or None."""
        if not name:
            return None
        for ext in exts:
            candidate = name if not ext or name.endswith(ext) else name + ext
            if candidate not in self._cache:
                self._cache[candidate] = self._lookup(candidate)
            if self._cache[candidate] is not None:
                return self._cache[candidate]
        return None

    def _lookup(self, candidate):
        f = self.device.find_file(candidate)
        if f is not None and f.type in ("JSON", "gDSP", "GenX", "TEXT", ""):
            data = _parse_patcher(f.data)
            if data is not None:
                return (f"bundle:{f.name}", data)
        if self.folder and os.sep not in candidate:
            full = os.path.join(self.folder, candidate)
            if candidate.endswith((".maxpat", ".gendsp", ".genjit", ".json")) and os.path.isfile(full):
                with open(full, "rb") as fh:
                    data = _parse_patcher(fh.read())
                if data is not None:
                    return (f"file:{candidate}", data)
        return None


def _parse_patcher(raw):
    try:
        data = json.loads(raw.rstrip(b"\x00"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(data, dict) and isinstance(data.get("patcher"), dict):
        return data["patcher"]
    return None


def _child_patcher(box, resolver):
    """Return (kind, source, patcher dict) for a box that contains a patcher, or None."""
    word = box_word(box)
    mclass = box.get("maxclass")

    if isinstance(box.get("patcher"), dict):
        kind = "bpatcher" if mclass == "bpatcher" else word or mclass
        return kind, "embedded", box["patcher"]
    data = box.get("data")
    if word in GEN_CLASSES and isinstance(data, dict) and isinstance(data.get("patcher"), dict):
        return word, "embedded", data["patcher"]

    if mclass == "bpatcher":
        name = box.get("name") or ""
        found = resolver.find(name, PATCHER_EXTS)
        return ("bpatcher",) + found if found else ("bpatcher", f"unresolved:{name}", None)
    if word in GEN_CLASSES:
        args = positional_args(box)
        name = box_attr_arg(box, "gen") or (args[0] if args else None)
        if name is None:
            return None
        found = resolver.find(name, GEN_EXTS)
        return (word,) + found if found else (word, f"unresolved:{name}", None)
    if word in POLY_CLASSES:
        args = positional_args(box)
        if not args:
            return None
        found = resolver.find(args[0], PATCHER_EXTS)
        return (word,) + found if found else (word, f"unresolved:{args[0]}", None)
    if mclass == "newobj" and word and word not in CODE_CLASSES:
        found = resolver.find(word, PATCHER_EXTS[1:])
        if found:
            return ("abstraction",) + found
    return None


def _label(box, kind):
    text = box_text(box)
    if box.get("maxclass") == "bpatcher":
        name = box.get("name") or box.get("varname") or ""
        text = f"bpatcher {name}".strip()
    text = " ".join(text.split())
    if len(text) > 40:
        text = text[:37] + "..."
    return f"{text or kind}[{box.get('id', '?')}]"


def walk_device(device, patcher=None):
    """Return every patcher in the device as PatcherNodes, depth-first, root first."""
    resolver = Resolver(device)
    root_patcher = patcher if patcher is not None else device.patcher_json["patcher"]
    root = PatcherNode(path="/", kind="device", depth=0, patcher=root_patcher,
                       source=device.main_name and f"bundle:{device.main_name}" or "main")
    nodes = [root]
    unresolved = []
    _walk(root, resolver, nodes, unresolved, ())
    return nodes, unresolved


def _walk(node, resolver, nodes, unresolved, ancestry):
    if node.depth >= MAX_DEPTH:
        return
    for box in node.boxes():
        child = _child_patcher(box, resolver)
        if child is None:
            continue
        kind, source, patcher = child
        if patcher is None:
            unresolved.append({"path": node.path, "box_id": box.get("id"),
                               "kind": kind, "name": source.split(":", 1)[1]})
            continue
        if source != "embedded" and source in ancestry:
            continue
        path = node.path.rstrip("/") + "/" + _label(box, kind)
        sub = PatcherNode(path=path, kind=kind, depth=node.depth + 1, patcher=patcher,
                          box_id=box.get("id", ""), parent=node.path, text=box_text(box),
                          source=source, is_gen=node.is_gen or kind in GEN_CLASSES)
        nodes.append(sub)
        _walk(sub, resolver, nodes, unresolved,
              ancestry + ((source,) if source != "embedded" else ()))
