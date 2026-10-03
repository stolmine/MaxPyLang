"""
devinspect.flow

Signal/control flow over a whole device.

The graph flattens the patcher hierarchy: a cord into inlet k of a subpatcher box
is rewired to the subpatcher's k-th inlet object, and a cord out of outlet k
comes from its k-th outlet object. Wireless pairs (s/r, send~/receive~, forward,
pv, value) become edges too. gen~ boxes stay single DSP nodes.

    FlowGraph(nodes) --> graph with forward/backward edges
        trace_param() --> first processing objects a control reaches (see trace.py)
        io_path() --> audio (plugin~ -> plugout~) or MIDI path summary
"""

import re
from collections import deque

from .trace import MAX_TARGETS, trace
from .tree import POLY_CLASSES, box_args, box_text, box_word

SENDERS = frozenset({"s", "send", "forward", "s~", "send~"})
RECEIVERS = frozenset({"r", "receive", "r~", "receive~"})
SHARED = frozenset({"pv", "value", "v"})
PORT_INS = frozenset({"in", "in~", "fftin~", "mc.in~"})
PORT_OUTS = frozenset({"out", "out~", "fftout~", "mc.out~"})
TRANSPARENT = SENDERS | RECEIVERS | SHARED | PORT_INS | PORT_OUTS | frozenset(
    {"inlet", "outlet", "t", "trigger", "prepend", "append", "defer", "deferlow"})
GEN_NODES = frozenset({"gen~", "mc.gen~", "rnbo~"})
_INSTANCE = re.compile(r"\[obj-[0-9]+\]")

AUDIO_SOURCES = frozenset({"plugin~", "mc.plugin~"})
AUDIO_SINKS = frozenset({"plugout~", "mc.plugout~"})
MIDI_SOURCES = frozenset({"midiin", "notein", "ctlin", "bendin", "pgmin", "touchin",
                          "polytouchin", "rtin", "live.miditool.in", "mpeconfig"})
MIDI_SINKS = frozenset({"midiout", "noteout", "ctlout", "bendout", "pgmout", "touchout",
                        "polytouchout", "live.miditool.out"})


def _x_order(boxes):
    return sorted(boxes, key=lambda b: tuple(b.get("patching_rect", [0, 0])[:2]))


def _ports(node, container_kind):
    """Return ({inlet index: [box ids]}, {outlet index: [box ids]}) of a subpatcher."""
    boxes = node.boxes()
    ins, outs = {}, {}
    if container_kind in POLY_CLASSES:
        for b in boxes:
            word, args = box_word(b), box_args(b)
            table = ins if word in PORT_INS else outs if word in PORT_OUTS else None
            if table is not None and args and args[0].isdigit():
                table.setdefault(int(args[0]) - 1, []).append(b["id"])
    if not ins:
        for i, b in enumerate(_x_order([b for b in boxes if b.get("maxclass") == "inlet"])):
            ins[i] = [b["id"]]
    if not outs:
        for i, b in enumerate(_x_order([b for b in boxes if b.get("maxclass") == "outlet"])):
            outs[i] = [b["id"]]
    return ins, outs


def _plain(name):
    return name.rsplit("@", 1)[0] if "#" in name else name


def is_signal(word) -> bool:
    return word.endswith("~") or word in GEN_NODES


class FlowGraph:
    """Flattened object graph of a device (gid = 'patcher path#obj-id')."""

    def __init__(self, nodes):
        self.boxes = {}
        self.fwd = {}
        self.back = {}
        self.ports = {}
        self.cords = []
        self.wireless = []
        children = {}
        self._scope = {}
        for node in nodes:
            if node.is_gen:
                continue
            local = not node.parent or node.source != "embedded"
            self._scope[node.path] = node.path if local else self._scope.get(node.parent, "/")
            for box in node.boxes():
                self.boxes[f"{node.path}#{box.get('id')}"] = (node.path, box)
        for node in nodes:
            if node.parent and not node.is_gen:
                children[(node.parent, node.box_id)] = (node.path, _ports(node, node.kind))
        self._children = children

        for node in nodes:
            if node.is_gen:
                continue
            for line in node.lines():
                try:
                    (src, so), (dst, di) = line["source"][:2], line["destination"][:2]
                except (KeyError, ValueError):
                    continue
                for s in self._resolve(node.path, src, so, out=True):
                    for d in self._resolve(node.path, dst, di, out=False):
                        self._add(s, d)
                        self.ports.setdefault(s, []).append((so, d, di))
                        self.cords.append((s, so, d, di))
        self._add_wireless()

    def _resolve(self, path, box_id, port, out):
        child = self._children.get((path, box_id))
        if child is None:
            return [f"{path}#{box_id}"]
        child_path, (ins, outs) = child
        ids = (outs if out else ins).get(port)
        if not ids:
            return [f"{path}#{box_id}"]
        return [f"{child_path}#{i}" for i in ids]

    def _add(self, s, d):
        if s == d:
            return
        self.fwd.setdefault(s, set()).add(d)
        self.back.setdefault(d, set()).add(s)

    def _add_wireless(self):
        senders, receivers = {}, {}
        for gid, (path, box) in self.boxes.items():
            word, args = box_word(box), box_args(box)
            if not args:
                continue
            name = args[0]
            if "#" in name:
                name = f"{name}@{self._scope.get(path, '/')}"
            if word in SENDERS or word in SHARED:
                senders.setdefault((word.endswith("~"), name), []).append(gid)
            if word in RECEIVERS or word in SHARED:
                receivers.setdefault((word.endswith("~"), name), []).append(gid)
        for key, srcs in senders.items():
            for s in srcs:
                for r in receivers.get(key, []):
                    if s != r:
                        self._add(s, r)
                        self.ports.setdefault(s, []).append((0, r, 0))
                        self.wireless.append((s, r, _plain(key[1])))

    def word(self, gid):
        return box_word(self.boxes[gid][1]) if gid in self.boxes else ""

    def label(self, gid, with_path=True):
        """Short display text of a node, with the subpatcher it lives in."""
        if gid not in self.boxes:
            return gid
        path, box = self.boxes[gid]
        text = " ".join(box_text(box).split()) or box.get("maxclass", "?")
        if box.get("maxclass") not in ("newobj", "message", "comment"):
            longname = box.get("saved_attribute_attributes", {}).get("valueof", {}).get(
                "parameter_longname") or box.get("varname")
            text = box.get("maxclass", "?") + (f" '{longname}'" if longname else "")
        if len(text) > 48:
            text = text[:45] + "..."
        if with_path and path != "/":
            text += f" (in {path.rsplit('/', 1)[-1]})"
        return text

    def grouped_labels(self, gids):
        """Labels in order; one object repeated across instances becomes 'x (in y xN)'."""
        groups = {}
        for gid in gids:
            label = self.label(gid)
            head, sep, where = label.rpartition(" (in ")
            key = (head, _INSTANCE.sub("", where)) if sep else (label, "")
            groups.setdefault(key, []).append(label)
        out = []
        for (head, where), labels in groups.items():
            if len(labels) == 1:
                out.append(labels[0])
            elif where:
                out.append(f"{head} (in {where[:-1]} x{len(labels)})")
            else:
                out.append(f"{head} x{len(labels)}")
        return out

    def trace_param(self, gid, max_hops=6, limit=MAX_TARGETS):
        """Return (first processing objects, endpoints or else dead ends) a control reaches."""
        return trace(self, gid, max_hops=max_hops, limit=limit)

    def _bfs(self, starts, edges):
        dist = {s: 0 for s in starts}
        prev = {}
        queue = deque(starts)
        while queue:
            cur = queue.popleft()
            for nxt in edges.get(cur, ()):
                if nxt not in dist:
                    dist[nxt] = dist[cur] + 1
                    prev[nxt] = cur
                    queue.append(nxt)
        return dist, prev

    def io_path(self, sources, sinks, signal_only):
        """Summarize the flow from source objects (plugin~, midiin) to sink objects."""
        srcs = [g for g in self.boxes if self.word(g) in sources]
        snks = [g for g in self.boxes if self.word(g) in sinks]
        result = {"sources": srcs, "sinks": snks, "connected": False,
                  "chain": [], "on_path": [], "feeding_sinks": [], "from_sources": []}
        if not snks and not srcs:
            return result
        keep = (lambda g: is_signal(self.word(g))) if signal_only else \
            (lambda g: self.word(g) not in TRANSPARENT)
        fdist, prev = self._bfs(srcs, self.fwd)
        bdist, _ = self._bfs(snks, self.back)
        reached = [s for s in snks if s in fdist]
        if reached:
            end = min(reached, key=lambda g: fdist[g])
            chain = [end]
            while chain[-1] in prev:
                chain.append(prev[chain[-1]])
            result["connected"] = True
            result["chain"] = [g for g in reversed(chain) if keep(g)]
            on_path = [g for g in fdist if g in bdist and keep(g)]
            result["on_path"] = sorted(on_path, key=lambda g: (fdist[g], g))
        result["feeding_sinks"] = [g for g in sorted(bdist, key=lambda g: (bdist[g], g))
                                   if keep(g) and g not in snks]
        result["from_sources"] = [g for g in sorted(fdist, key=lambda g: (fdist[g], g))
                                  if keep(g) and g not in srcs]
        return result

    def to_dict(self):
        return {
            "nodes": {gid: {"path": path, "id": box.get("id"), "class": box_word(box),
                            "text": box_text(box)} for gid, (path, box) in self.boxes.items()},
            "cords": [{"from": s, "outlet": so, "to": d, "inlet": di}
                      for s, so, d, di in self.cords],
            "wireless": [{"from": s, "to": r, "name": n} for s, r, n in self.wireless],
        }
