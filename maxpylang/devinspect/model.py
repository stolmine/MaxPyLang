"""
devinspect.model

DeviceDescription: everything devinspect learns about one .amxd / .maxpat.

    describe() --> DeviceDescription
        .to_markdown() --> concise LLM-oriented summary
        .to_dict() / .to_json() --> full detail
"""

import json
import os
from collections import Counter
from dataclasses import dataclass, field

from maxpylang.amxd import AmxdDevice, read_amxd

from .code import collect_code
from .flow import (AUDIO_SINKS, AUDIO_SOURCES, MIDI_SINKS, MIDI_SOURCES, FlowGraph)
from .layout import collect_comments, device_view, presentation_ids
from .params import collect_params
from .tree import box_word, walk_device

DEVICE_INFO_KEYS = ("description", "tags", "latency", "is_mpe", "minimum_live_version",
                    "minimum_max_version", "openinpresentation", "devicewidth")


def _max_version(patcher):
    v = patcher.get("appversion") or {}
    if not isinstance(v, dict) or "major" not in v:
        return ""
    return f"{v.get('major')}.{v.get('minor', 0)}.{v.get('revision', 0)}"


def load_any(path):
    """Read an .amxd (any layout) or a .maxpat/.json patcher into an AmxdDevice. Never writes."""
    path = str(path)
    if path.endswith(".amxd"):
        return read_amxd(path)
    with open(path, "rb") as f:
        raw = f.read()
    return AmxdDevice(path=path, type_code="", chunks=[], patcher_json=json.loads(raw),
                      raw_patcher=raw)


@dataclass
class DeviceDescription:
    """Structured description of a device; render with to_markdown() or to_json()."""

    name: str
    path: str
    device_type: str
    frozen: bool
    file_size: int
    chunks: list
    max_version: str
    info: dict
    files: list
    hierarchy: list
    unresolved: list
    params: list
    view: list
    comments: list
    code: list
    audio: dict
    midi: dict
    object_counts: dict
    graph: dict = field(repr=False)
    depth: int = 3
    full_code: bool = False

    def to_dict(self) -> dict:
        data = {k: v for k, v in self.__dict__.items() if k not in ("depth", "full_code")}
        return data

    def to_json(self, indent=2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)

    def to_markdown(self, depth=None, full_code=None) -> str:
        from .markdown import render
        return render(self, self.depth if depth is None else depth,
                      self.full_code if full_code is None else full_code)


def _io(graph, sources, sinks, signal_only):
    res = graph.io_path(sources, sinks, signal_only)
    labels = lambda gids, n=None: list(dict.fromkeys(graph.label(g) for g in gids))[:n]
    return {
        "sources": labels(res["sources"]),
        "sinks": labels(res["sinks"]),
        "connected": res["connected"],
        "chain": [graph.label(g) for g in res["chain"]],
        "on_path": labels(res["on_path"]),
        "feeding_sinks": labels(res["feeding_sinks"], 60),
        "from_sources": labels(res["from_sources"], 60),
    }


def describe(path, depth=3, full_code=False, max_hops=6):
    """
    Describe a Max for Live device (.amxd, plain or frozen) or a .maxpat. Read-only.

    depth --> subpatcher levels expanded in the Markdown hierarchy
    full_code --> include whole js/gen sources in the Markdown (JSON always has them)
    max_hops --> how far downstream parameter tracing goes
    """
    device = load_any(path)
    nodes, unresolved = walk_device(device)
    root = nodes[0].patcher

    view = device_view(nodes)
    shown = presentation_ids(view)
    graph = FlowGraph(nodes)

    params = collect_params(nodes, shown)
    for p in params:
        gid = f"{p['path']}#{p['box_id']}"
        targets, notable = graph.trace_param(gid, max_hops=max_hops)
        p["feeds"] = graph.grouped_labels(targets)
        p["reaches"] = list(dict.fromkeys(graph.label(g) for g in notable))

    counts = Counter(box_word(b) for n in nodes if not n.is_gen for b in n.boxes())
    counts.pop("", None)

    return DeviceDescription(
        name=os.path.splitext(os.path.basename(str(path)))[0],
        path=str(path),
        device_type=device.device_type or "patcher",
        frozen=device.frozen,
        file_size=os.path.getsize(path),
        chunks=device.chunks,
        max_version=_max_version(root),
        info={k: root[k] for k in DEVICE_INFO_KEYS if k in root and root[k] not in ("", None)},
        files=[f.summary() for f in device.files],
        hierarchy=[n.summary() for n in nodes],
        unresolved=unresolved,
        params=params,
        view=view,
        comments=collect_comments(nodes, shown),
        code=collect_code(nodes, device),
        audio=_io(graph, AUDIO_SOURCES, AUDIO_SINKS, True),
        midi=_io(graph, MIDI_SOURCES, MIDI_SINKS, False),
        object_counts=dict(counts.most_common()),
        graph=graph.to_dict(),
        depth=depth,
        full_code=full_code,
    )
