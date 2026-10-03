"""
Synthetic Max for Live devices for the frozen-reader and inspector tests.

build_device() --> patcher JSON of a small audio effect (subpatcher, abstraction,
                   send/receive, js, gen~ codebox, parameters, presentation)
freeze() --> bytes of a frozen .amxd (mx@c container) per the format in frozen.py
"""

import contextlib
import io
import json
import os
import struct
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import maxpylang as mp
from maxpylang.amxd import DEVICE_TYPES
from maxpylang.m4l import device_json

LIVE_RES = "/Applications/Ableton Live 12 Suite.app/Contents/App-Resources"
C74 = os.path.join(LIVE_RES, "Max/Max.app/Contents/Resources/C74")
M4L_PATCHERS = os.path.join(C74, "packages/Max for Live/patchers")
EXT_DEVICES = "/Volumes/music_production/M4L devices"
CORPUS_ROOTS = [os.path.join(LIVE_RES, "Builtin/Devices"), os.path.join(C74, "packages"),
                os.path.join(LIVE_RES, "Misc"),
                os.path.join(LIVE_RES, "Max/Max.app/Contents/Resources/Examples"), EXT_DEVICES]

JS_SOURCE = "inlets = 1;\noutlets = 1;\nfunction mode(v) {\n    outlet(0, v);\n}\n"
GEN_CODE = "out1 = in1 * 0.5;"


def _patch():
    return mp.MaxPatch(verbose=False)


def _quiet(func, *args, **kwargs):
    with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
        warnings.simplefilter("ignore")
        return func(*args, **kwargs)


def _abs(text, inlets, outlets):
    return _quiet(mp.MaxObject, text, abstraction=True, inlets=inlets, outlets=outlets)


def _place(patch, spec, x, y):
    patch.set_position(x, y)
    return _quiet(patch.place, spec, verbose=False)[0]


def _connect(patch, *pairs):
    patch.connect(*[[a, b] for a, b in pairs], verbose=False)


def filter_subpatcher():
    """inlet -> lores~ -> outlet, cutoff from 'r ---cut'."""
    sub = _patch()
    inlet = _place(sub, "inlet", 20, 20)
    recv = _place(sub, _abs("r ---cut", 0, 1), 120, 20)
    lores = _place(sub, "lores~ 1000 0.5", 20, 80)
    outlet = _place(sub, "outlet", 20, 140)
    _connect(sub, (inlet.outs[0], lores.ins[0]), (recv.outs[0], lores.ins[1]),
             (lores.outs[0], outlet.ins[0]))
    return sub.get_json()["patcher"]


def abstraction_patcher():
    """myabs.maxpat: inlet -> *~ 0.5 -> outlet."""
    sub = _patch()
    inlet = _place(sub, "inlet", 20, 20)
    mul = _place(sub, "*~ 0.5", 20, 80)
    outlet = _place(sub, "outlet", 20, 140)
    _connect(sub, (inlet.outs[0], mul.ins[0]), (mul.outs[0], outlet.ins[0]))
    return sub.get_json()


def gen_patcher():
    return {"fileversion": 1, "classnamespace": "dsp.gen", "boxes": [
        {"box": {"id": "obj-1", "maxclass": "newobj", "text": "in 1", "numinlets": 0,
                 "numoutlets": 1, "patching_rect": [10, 10, 30, 22]}},
        {"box": {"id": "obj-2", "maxclass": "codebox", "code": GEN_CODE, "numinlets": 1,
                 "numoutlets": 1, "patching_rect": [10, 50, 200, 100]}},
        {"box": {"id": "obj-3", "maxclass": "newobj", "text": "out 1", "numinlets": 1,
                 "numoutlets": 0, "patching_rect": [10, 170, 35, 22]}},
    ], "lines": [
        {"patchline": {"source": ["obj-1", 0], "destination": ["obj-2", 0]}},
        {"patchline": {"source": ["obj-2", 0], "destination": ["obj-3", 0]}},
    ]}


def _box(obj):
    return obj._dict["box"]


def build_device():
    """Return the patcher JSON of a synthetic audio effect."""
    patch = _patch()
    plugin = _place(patch, "plugin~", 20, 20)
    filt = _place(patch, _abs("p filter", 1, 1), 20, 80)
    absb = _place(patch, _abs("myabs", 1, 1), 20, 130)
    gen = _place(patch, _abs("gen~", 1, 1), 20, 180)
    mul = _place(patch, "*~ 1.", 20, 230)
    plugout = _place(patch, "plugout~", 20, 280)
    _connect(patch, (plugin.outs[0], filt.ins[0]), (filt.outs[0], absb.ins[0]),
             (absb.outs[0], gen.ins[0]), (gen.outs[0], mul.ins[0]),
             (mul.outs[0], plugout.ins[0]), (mul.outs[0], plugout.ins[1]))

    dial = _place(patch, _quiet(mp.MaxObject, "live.dial", parameter_longname="Cutoff",
                                      parameter_shortname="Cut", parameter_mmin=20.,
                                      parameter_mmax=20000., parameter_initial=[1000.],
                                      parameter_unitstyle="hertz", parameter_exponent=3.,
                                      parameter_modmode=2), 300, 20)
    send = _place(patch, _abs("s ---cut", 1, 0), 300, 90)
    tab = _place(patch, _quiet(mp.MaxObject, "live.tab", parameter_longname="Mode",
                                     parameter_enum=["lp", "hp"], parameter_mmax=1), 400, 20)
    prep = _place(patch, "prepend mode", 400, 90)
    js = _place(patch, _abs("js helper.js", 1, 1), 400, 130)
    gain = _place(patch, _quiet(mp.MaxObject, "live.dial", parameter_longname="Hidden Gain"),
                  500, 20)
    _connect(patch, (dial.outs[0], send.ins[0]), (tab.outs[0], prep.ins[0]),
             (prep.outs[0], js.ins[0]), (gain.outs[0], mul.ins[1]))

    title = _place(patch, "comment Cutoff", 300, 0)
    _place(patch, "comment Patching note: filter runs first", 600, 300)
    dial.present(10, 40)
    tab.present(80, 10)
    title.present(10, 20)

    data = device_json(patch.get_json(), "audio_effect")
    root = data["patcher"]
    root["openinpresentation"] = 1
    root["devicewidth"] = 200.0
    root["appversion"] = {"major": 8, "minor": 6, "revision": 2}
    for b in root["boxes"]:
        box = b["box"]
        if box.get("text") == "p filter":
            box["patcher"] = filter_subpatcher()
        elif box.get("text") == "gen~":
            box["patcher"] = gen_patcher()
        elif box.get("maxclass") == "comment" and box.get("text", "").startswith("comment "):
            box["text"] = box["text"][len("comment "):]
        elif box.get("text") == "js helper.js":
            box["saved_object_attributes"] = {"filename": "helper.js", "parameter_enable": 0}
    return data


def midi_device():
    """Return the patcher JSON of a MIDI effect: midiin -> midiparse -> midiformat -> midiout."""
    patch = _patch()
    midiin = _place(patch, "midiin", 20, 20)
    parse = _place(patch, "midiparse", 20, 60)
    form = _place(patch, "midiformat", 20, 120)
    midiout = _place(patch, "midiout", 20, 180)
    _connect(patch, (midiin.outs[0], parse.ins[0]), (parse.outs[0], form.ins[0]),
             (form.outs[0], midiout.ins[0]))
    return device_json(patch.get_json(), "midi_effect")


def _raw_box(box_id, text, x, y=0, maxclass="newobj", longname=None):
    box = {"id": box_id, "maxclass": maxclass, "numinlets": 2, "numoutlets": 2,
           "patching_rect": [x, y, 60, 22]}
    if maxclass in ("newobj", "message"):
        box["text"] = text
    if longname:
        box["saved_attribute_attributes"] = {"valueof": {"parameter_longname": longname}}
    return {"box": box}


def _raw_patcher(boxes, cords):
    return {"fileversion": 1, "boxes": boxes,
            "lines": [{"patchline": {"source": [s, so], "destination": [d, di]}}
                      for s, so, d, di in cords]}


def twoin_abstraction():
    """twoin.maxpat: left inlet -> cycle~, right inlet -> lores~ (right inlet listed first)."""
    return {"patcher": _raw_patcher(
        [_raw_box("obj-2", "", 120, maxclass="inlet"), _raw_box("obj-1", "", 20, maxclass="inlet"),
         _raw_box("obj-3", "cycle~ 440", 20, 60), _raw_box("obj-4", "lores~ 1000 0.5", 120, 60),
         _raw_box("obj-5", "", 20, 120, maxclass="outlet")],
        [("obj-1", 0, "obj-3", 0), ("obj-2", 0, "obj-4", 1),
         ("obj-3", 0, "obj-5", 0), ("obj-4", 0, "obj-5", 0)])}


def routing_device():
    """
    Patcher JSON of a device whose controls share routing:
    Alpha/Beta -> two inlets of the twoin abstraction; Gamma/Delta -> prepend freq/q ->
    one t l -> route freq q -> phasor~ / svf~; Echo -> 'level $1' -> s ---lvl ->
    r ---lvl in p mixer -> route level -> *~ 1. (an unrelated r ---other feeds noise~)
    """
    mixer = _raw_patcher(
        [_raw_box("obj-1", "r ---lvl", 20), _raw_box("obj-2", "route level", 20, 40),
         _raw_box("obj-3", "*~ 1.", 20, 80), _raw_box("obj-4", "r ---other", 120),
         _raw_box("obj-5", "noise~", 120, 80)],
        [("obj-1", 0, "obj-2", 0), ("obj-2", 0, "obj-3", 1), ("obj-4", 0, "obj-5", 0)])
    boxes = [
        _raw_box("obj-1", "", 20, maxclass="live.dial", longname="Alpha"),
        _raw_box("obj-2", "", 120, maxclass="live.dial", longname="Beta"),
        _raw_box("obj-3", "twoin", 20, 60),
        _raw_box("obj-4", "", 220, maxclass="live.dial", longname="Gamma"),
        _raw_box("obj-5", "", 320, maxclass="live.dial", longname="Delta"),
        _raw_box("obj-6", "prepend freq", 220, 40), _raw_box("obj-7", "prepend q", 320, 40),
        _raw_box("obj-8", "t l", 220, 80), _raw_box("obj-9", "route freq q", 220, 120),
        _raw_box("obj-10", "phasor~", 220, 160), _raw_box("obj-11", "svf~", 320, 160),
        _raw_box("obj-12", "", 420, maxclass="live.dial", longname="Echo"),
        _raw_box("obj-13", "level $1", 420, 40, maxclass="message"),
        _raw_box("obj-14", "s ---lvl", 420, 80),
        _raw_box("obj-15", "p mixer", 420, 120),
        _raw_box("obj-16", "", 20, 200, maxclass="live.dial", longname="Foxtrot"),
        _raw_box("obj-17", "s ---other", 20, 240),
    ]
    boxes[14]["box"]["patcher"] = mixer
    cords = [("obj-1", 0, "obj-3", 0), ("obj-2", 0, "obj-3", 1),
             ("obj-4", 0, "obj-6", 0), ("obj-5", 0, "obj-7", 0),
             ("obj-6", 0, "obj-8", 0), ("obj-7", 0, "obj-8", 0), ("obj-8", 0, "obj-9", 0),
             ("obj-9", 0, "obj-10", 1), ("obj-9", 1, "obj-11", 1),
             ("obj-12", 0, "obj-13", 0), ("obj-13", 0, "obj-14", 0), ("obj-16", 0, "obj-17", 0)]
    return device_json({"patcher": _raw_patcher(boxes, cords)}, "audio_effect")


def routing_files():
    return [("twoin.maxpat", b"JSON", json.dumps(twoin_abstraction()).encode() + b"\x00")]


def _sub(tag, payload):
    return tag + struct.pack(">I", 8 + len(payload)) + payload


def _entry(type_code, name, size, offset, flag, mdate=3759738635):
    fnam = name.encode("utf-8") + b"\x00"
    fnam += b"\x00" * (-len(fnam) % 4)
    return _sub(b"dire", _sub(b"type", type_code) + _sub(b"fnam", fnam)
                + _sub(b"sz32", struct.pack(">I", size)) + _sub(b"of32", struct.pack(">I", offset))
                + _sub(b"vers", b"\x00" * 4) + _sub(b"flag", struct.pack(">I", flag))
                + _sub(b"mdat", struct.pack(">I", mdate)))


def container(patcher_json, files=(), main_name="Synthetic.amxd", stale=b""):
    """Build an mx@c container: main JSON first, then (name, type, bytes) files."""
    main = json.dumps(patcher_json, indent=2).encode("utf-8") + b"\n\x00"
    blobs = [(main_name, b"JSON", main, 0x11)] + [(n, t, d, 0) for n, t, d in files]
    body, entries, offset = b"", b"", 16
    for name, type_code, data, flag in blobs:
        entries += _entry(type_code, name, len(data), offset, flag)
        body += data
        offset += len(data)
    return b"mx@c" + struct.pack(">III", 16, 0, offset) + body + _sub(b"dlst", entries) + stale


def freeze(patcher_json, files=(), device_type="audio_effect", meta=True, **kw):
    """Return the bytes of a frozen .amxd (meta=False gives the older meta-less layout)."""
    payload = container(patcher_json, files, **kw)
    out = b"ampf" + struct.pack("<I", 4) + DEVICE_TYPES[device_type]
    if meta:
        out += b"meta" + struct.pack("<I", 4) + b"\x07\x00\x00\x00"
    return out + b"ptch" + struct.pack("<I", len(payload)) + payload


def bundle_files():
    return [("myabs.maxpat", b"JSON", json.dumps(abstraction_patcher()).encode() + b"\x00"),
            ("helper.js", b"TEXT", JS_SOURCE.encode()),
            ("knob.svg", b"svg ", b"<svg xmlns='http://www.w3.org/2000/svg'/>")]


def encrypted_bytes():
    return (b"ampf" + struct.pack("<I", 4) + b"aaaa" + b"meta" + struct.pack("<I", 4)
            + b"\x00" * 4 + b"ciph" + struct.pack("<I", 8) + b"\x01\x00\x00\x00" + b"\xaa" * 4)


def write(path, data):
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def corpus_paths():
    """Every .amxd under the known corpus roots that exist on this machine."""
    paths = []
    for root in CORPUS_ROOTS + [r for r in os.environ.get("MAXPYLANG_AMXD_CORPUS", "").split(os.pathsep) if r]:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            paths += [os.path.join(dirpath, n) for n in sorted(filenames)
                      if n.endswith(".amxd") and not n.startswith("._")]
    return paths
