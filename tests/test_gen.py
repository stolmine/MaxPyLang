"""
Tests for gen~ codebox support (maxpylang.gen).

Tests:
1. GenExpr scanning: in/out counts, Param names, comments ignored
2. gen_codebox box shape: counts, outlet types, embedded patcher, cords
3. Validation: reserved Param names, too few xlets, bad kind/params
4. Placing, connecting, .amxd round trip and describe output
5. Shape against a real device with an inline gen~ codebox (when available)
"""

import contextlib
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import maxpylang as mp
from maxpylang.amxd import load_amxd
from maxpylang.gen import genexpr_io, param_declarations

STEREO = """// stereo gain
Param gain(0.5, min=0, max=1), pan(0);
Param drive(1);   /* Param hidden(0); */
out1 = in1 * gain;
out2 = in2 * gain * drive;
"""

SWIRL = "/Volumes/music_production/M4L devices/Kentaro/swirl_1.1.1.amxd"


def _box(obj):
    return obj._dict["box"]


def _inner(obj):
    return {b["box"]["id"]: b["box"] for b in _box(obj)["patcher"]["boxes"]}


def _cords(obj):
    return {(tuple(l["patchline"]["source"]), tuple(l["patchline"]["destination"]))
            for l in _box(obj)["patcher"]["lines"]}


def _quiet(func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return func(*args, **kwargs)


# =====================================================================
# TEST 1: GenExpr scanning
# =====================================================================

class TestScan:
    def test_io_counts(self):
        assert genexpr_io(STEREO) == (2, 2)

    def test_io_ignores_comments_and_members(self):
        code = "// out9 = in9;\n/* in7 */ x = foo.in3; out1 = in1;"
        assert genexpr_io(code) == (1, 1)

    def test_io_none(self):
        assert genexpr_io("x = 1;") == (0, 0)

    def test_params(self):
        assert mp.genexpr_params(STEREO) == ["gain", "pan", "drive"]

    def test_params_bare_declaration(self):
        assert mp.genexpr_params("Param a; Param b(1, min=0, max=2), c;") == ["a", "b", "c"]

    def test_param_declarations(self):
        lines = param_declarations({"g": 0.5, "n": {"default": 8, "min": 1, "max": 24}})
        assert lines == ["Param g(0.5);", "Param n(8, min=1, max=24);"]


# =====================================================================
# TEST 2: box shape
# =====================================================================

class TestShape:
    def test_outer_counts_from_code(self):
        box = _box(mp.gen_codebox(STEREO))
        assert box["text"] == "gen~"
        assert (box["numinlets"], box["numoutlets"]) == (2, 2)
        assert box["outlettype"] == ["signal", "signal"]

    def test_embedded_patcher(self):
        obj = mp.gen_codebox(STEREO)
        patcher = _box(obj)["patcher"]
        assert patcher["classnamespace"] == "dsp.gen"
        inner = _inner(obj)
        code = inner["obj-codebox"]
        assert code["maxclass"] == "codebox" and code["code"] == STEREO
        assert (code["numinlets"], code["numoutlets"]) == (2, 2)
        assert code["outlettype"] == ["", ""]
        texts = sorted(b["text"] for b in inner.values() if b["maxclass"] == "newobj")
        assert texts == ["in 1", "in 2", "out 1", "out 2"]

    def test_cords(self):
        assert _cords(mp.gen_codebox(STEREO)) == {
            (("obj-in-1", 0), ("obj-codebox", 0)), (("obj-in-2", 0), ("obj-codebox", 1)),
            (("obj-codebox", 0), ("obj-out-1", 0)), (("obj-codebox", 1), ("obj-out-2", 0))}

    def test_extra_xlets_not_wired_to_codebox(self):
        obj = mp.gen_codebox("out1 = in1;", inlets=3, outlets=2)
        assert (_box(obj)["numinlets"], _box(obj)["numoutlets"]) == (3, 2)
        assert _inner(obj)["obj-codebox"]["numinlets"] == 1
        assert {"obj-in-3", "obj-out-2"} <= set(_inner(obj))
        assert all("obj-in-3" not in s and "obj-out-2" not in d for s, d in _cords(obj))

    def test_no_inputs_keeps_message_inlet(self):
        box = _box(mp.gen_codebox("out1 = noise();"))
        assert box["numinlets"] == 1 and box["numoutlets"] == 1

    def test_event_gen(self):
        box = _box(mp.gen_codebox("out1 = in1 + 1;", kind="gen"))
        assert box["text"] == "gen" and box["outlettype"] == ["float"]

    def test_params_prepended(self):
        obj = mp.gen_codebox("out1 = in1 * g;", params={"g": {"default": 0.5, "max": 1}})
        code = _inner(obj)["obj-codebox"]["code"]
        assert code.startswith("Param g(0.5, max=1);\n")

    def test_box_attribs(self):
        assert _box(mp.gen_codebox("out1 = in1;", varname="dsp"))["varname"] == "dsp"

    def test_codebox_size(self):
        obj = mp.gen_codebox("out1 = in1;", codebox_size=(900, 700))
        assert _inner(obj)["obj-codebox"]["patching_rect"][2:] == [900.0, 700.0]


# =====================================================================
# TEST 3: validation
# =====================================================================

class TestValidation:
    @pytest.mark.parametrize("name", ["mix", "Wrap", "delay", "in", "samplerate"])
    def test_reserved_param_name(self, name):
        with pytest.raises(ValueError, match="shadows"):
            mp.gen_codebox(f"Param {name}(0);\nout1 = in1;")

    def test_reserved_name_in_params_kwarg(self):
        with pytest.raises(ValueError, match="mix"):
            mp.gen_codebox("out1 = in1;", params={"mix": 0.5})

    def test_too_few_xlets(self):
        with pytest.raises(ValueError, match="in1..in2"):
            mp.gen_codebox(STEREO, inlets=1)
        with pytest.raises(ValueError):
            mp.gen_codebox(STEREO, outlets=1)

    def test_bad_kind(self):
        with pytest.raises(ValueError, match="kind"):
            mp.gen_codebox("out1 = in1;", kind="jit.gen")

    def test_empty_code(self):
        with pytest.raises(ValueError):
            mp.gen_codebox("  ")

    def test_bad_param_value(self):
        with pytest.raises(TypeError):
            mp.gen_codebox("out1 = in1;", params={"g": "loud"})
        with pytest.raises(ValueError, match="unknown keys"):
            mp.gen_codebox("out1 = in1;", params={"g": {"dflt": 1}})


# =====================================================================
# TEST 4: in a patch / device
# =====================================================================

@pytest.fixture
def device(tmp_path):
    patch = mp.MaxPatch(verbose=False)
    plugin = _quiet(patch.place, "plugin~")[0]
    gen = _quiet(patch.place, mp.gen_codebox(STEREO))[0]
    plugout = _quiet(patch.place, "plugout~")[0]
    msg = _quiet(patch.place, "prepend gain")[0]
    patch.connect([plugin.outs[0], gen.ins[0]], [plugin.outs[1], gen.ins[1]],
                  [msg.outs[0], gen.ins[0]],
                  [gen.outs[0], plugout.ins[0]], [gen.outs[1], plugout.ins[1]], verbose=False)
    path = str(tmp_path / "gen_fx.amxd")
    _quiet(patch.save, path, device_type="audio_effect", verbose=False)
    return path


class TestDevice:
    def test_round_trip(self, device):
        boxes = [b["box"] for b in load_amxd(device)["patcher"]["boxes"]]
        gen = next(b for b in boxes if b.get("text") == "gen~")
        codebox = next(b for b in gen["patcher"]["boxes"] if b["box"]["maxclass"] == "codebox")
        assert codebox["box"]["code"] == STEREO
        assert len(load_amxd(device)["patcher"]["lines"]) == 5

    def test_reload_xlets(self, device):
        patch = _quiet(mp.MaxPatch, load_file=device, verbose=False)
        gen = next(o for o in patch.objs.values() if o.name == "gen~")
        assert (len(gen.ins), len(gen.outs)) == (2, 2)

    def test_describe(self, device):
        d = mp.describe(device)
        gen_code = [c for c in d.code if c["object"] == "gen codebox"]
        assert len(gen_code) == 1
        assert gen_code[0]["params"] == ["gain", "pan", "drive"]
        md = d.to_markdown(full_code=True)
        assert "Params: gain, pan, drive" in md
        assert "out2 = in2 * gain * drive;" in md
        assert "plugin~ -> gen~ -> plugout~" in md


# =====================================================================
# TEST 5: compared with a real device
# =====================================================================

def _gen_codeboxes(patcher):
    for b in patcher.get("boxes", []):
        box = b["box"]
        sub = box.get("patcher")
        if isinstance(sub, dict):
            if sub.get("classnamespace") == "dsp.gen" and box.get("text") == "gen~":
                yield box, sub
            else:
                yield from _gen_codeboxes(sub)


@pytest.mark.skipif(not os.path.exists(SWIRL), reason="reference device not available")
def test_matches_real_inline_gen():
    real_box, real_patcher = next(_gen_codeboxes(load_amxd(SWIRL)["patcher"]))
    real_code = next(b["box"] for b in real_patcher["boxes"] if b["box"]["maxclass"] == "codebox")
    ours = mp.gen_codebox(real_code["code"])
    box, code = _box(ours), _inner(ours)["obj-codebox"]

    assert (box["numinlets"], box["numoutlets"]) == (real_box["numinlets"], real_box["numoutlets"])
    assert box["outlettype"] == real_box["outlettype"]
    assert (code["numinlets"], code["numoutlets"]) == (real_code["numinlets"], real_code["numoutlets"])
    for key in ("maxclass", "fontname", "fontface", "fontsize", "outlettype"):
        assert code[key] == real_code[key], key
    real_texts = sorted(b["box"]["text"] for b in real_patcher["boxes"] if b["box"]["maxclass"] == "newobj")
    ours_texts = sorted(b["text"] for b in _inner(ours).values() if b["maxclass"] == "newobj")
    assert ours_texts == real_texts
