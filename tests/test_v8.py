"""
Tests for v8.codebox support (maxpylang.v8).

Tests:
1. inlets/outlets declarations: defaults, comments ignored, last one wins
2. v8_codebox box shape and validation
3. Placing, .amxd round trip, reload and describe output
4. Shape against a real v8.codebox from the Max 9 bundle (when available)
"""

import contextlib
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import maxpylang as mp
from maxpylang.amxd import load_amxd

CODE = """// probe
inlets = 1;
outlets = 2; /* outlets = 9; */
function bang() { outlet(1, "done"); }
"""

MAX_C74 = ("/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/Max/Max.app/"
           "Contents/Resources/C74")
REAL = os.path.join(MAX_C74, "packages/Jitter Geometry/patchers/abstractions/geom.edgelines.maxpat")


def _box(obj):
    return obj._dict["box"]


def _quiet(func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return func(*args, **kwargs)


class TestIO:
    def test_declared(self):
        assert mp.js_io(CODE) == (1, 2)

    def test_defaults(self):
        assert mp.js_io("function bang() {}") == (1, 1)

    def test_member_access_ignored(self):
        assert mp.js_io("this.outlets = 4;\nx.inlets = 3;\noutlets = 2;") == (1, 2)

    def test_last_wins(self):
        assert mp.js_io("inlets = 2;\ninlets = 3;") == (3, 1)


class TestShape:
    def test_box(self):
        box = _box(mp.v8_codebox(CODE))
        assert box["maxclass"] == "v8.codebox" and box["code"] == CODE
        assert (box["numinlets"], box["numoutlets"]) == (1, 2)
        assert box["outlettype"] == ["", ""]
        assert box["filename"] == "none"
        assert box["saved_object_attributes"] == {"parameter_enable": 0}
        assert "text" not in box

    def test_size_and_attribs(self):
        box = _box(mp.v8_codebox(CODE, size=(500, 300), varname="probe"))
        assert box["patching_rect"][2:] == [500.0, 300.0] and box["varname"] == "probe"

    def test_known_object(self):
        obj = mp.v8_codebox(CODE)
        assert not obj.notknown()
        assert (len(obj.ins), len(obj.outs)) == (1, 2)

    def test_count_mismatch(self):
        with pytest.raises(ValueError, match="declares 1 inlets / 2 outlets"):
            mp.v8_codebox(CODE, outlets=3)

    def test_empty(self):
        with pytest.raises(ValueError):
            mp.v8_codebox("   ")


@pytest.fixture
def device(tmp_path):
    patch = mp.MaxPatch(verbose=False)
    btn = _quiet(patch.place, "live.text")[0]
    js = _quiet(patch.place, mp.v8_codebox(CODE))[0]
    status = _quiet(patch.place, "live.comment status")[0]
    plugin = _quiet(patch.place, "plugin~")[0]
    plugout = _quiet(patch.place, "plugout~")[0]
    patch.connect([btn.outs[0], js.ins[0]], [js.outs[1], status.ins[0]],
                  [plugin.outs[0], plugout.ins[0]], verbose=False)
    path = str(tmp_path / "v8_fx.amxd")
    _quiet(patch.save, path, device_type="audio_effect", verbose=False)
    return path


class TestDevice:
    def test_round_trip(self, device):
        boxes = [b["box"] for b in load_amxd(device)["patcher"]["boxes"]]
        js = next(b for b in boxes if b["maxclass"] == "v8.codebox")
        assert js["code"] == CODE and js["numoutlets"] == 2

    def test_reload(self, device):
        patch = _quiet(mp.MaxPatch, load_file=device, verbose=False)
        js = next(o for o in patch.objs.values() if o.name == "v8.codebox")
        assert (len(js.ins), len(js.outs)) == (1, 2) and not js.notknown()

    def test_describe(self, device):
        d = mp.describe(device)
        assert any(c["object"] == "v8.codebox" and c["text"] == CODE for c in d.code)


def _real_codebox(patcher):
    for b in patcher.get("boxes", []):
        box = b["box"]
        if box.get("maxclass") == "v8.codebox":
            return box
        if isinstance(box.get("patcher"), dict):
            found = _real_codebox(box["patcher"])
            if found:
                return found
    return None


@pytest.mark.skipif(not os.path.exists(REAL), reason="Max 9 bundle not available")
def test_matches_real_v8_codebox():
    with open(REAL) as f:
        real = _real_codebox(json.load(f)["patcher"])
    ours = _box(mp.v8_codebox(real["code"]))
    assert set(real) - {"id", "patching_rect"} <= set(ours)
    for key in ("maxclass", "filename", "fontface", "fontname", "fontsize", "numinlets",
                "numoutlets", "outlettype", "saved_object_attributes"):
        assert ours[key] == real[key], key
