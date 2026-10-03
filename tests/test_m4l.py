"""
Tests for Max for Live object/parameter/device support in MaxPyLang.

Tests:
1. m4l object database (maxclass, xlets, checked against Live's maxproto files)
2. Connections to/from live.* objects
3. Live parameter attributes (valueof routing, defaults, prototypes)
4. live.comment / live.text box text
5. Round-trip save/load of .amxd keeps parameters
6. Device-level settings
7. .amxd header bytes vs Live 12 template devices
8. Example device
"""

import glob
import json
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import maxpylang as mp
from maxpylang.amxd import load_amxd
from maxpylang.tools.constants import obj_info_folder

LIVE_APP = "/Applications/Ableton Live 12 Suite.app"
C74 = os.path.join(LIVE_APP, "Contents/App-Resources/Max/Max.app/Contents/Resources/C74")
PROTO_DIR = os.path.join(C74, "object-prototypes", "m4l")
TEMPLATE_DIR = os.path.join(LIVE_APP, "Contents/App-Resources/Misc/Max Devices")
M4L_DIR = os.path.join(obj_info_folder, "m4l")

needs_live = pytest.mark.skipif(not os.path.exists(C74), reason="Ableton Live 12 Suite not installed")


def _box(obj):
    return obj._dict["box"]


def _valueof(obj):
    return _box(obj)["saved_attribute_attributes"]["valueof"]


def _cutoff_dial(**extra):
    return mp.MaxObject("live.dial", parameter_longname="Cutoff", parameter_mmin=20.,
                        parameter_mmax=20000., parameter_initial=[1000.],
                        parameter_unitstyle=3, parameter_exponent=3., **extra)


# =====================================================================
# TEST 1: m4l object database
# =====================================================================

class TestDatabase:
    def test_m4l_package_registered(self):
        assert "m4l" in mp.MaxObject.known_objs
        assert "live.dial" in mp.MaxObject.known_objs["m4l"]

    def test_all_entries_valid(self):
        files = sorted(glob.glob(os.path.join(M4L_DIR, "*.json")))
        assert len(files) >= 33
        for path in files:
            with open(path) as f:
                info = json.load(f)
            assert {"default", "args", "attribs", "in/out"} <= set(info), path
            box = info["default"]["box"]
            assert len(box.get("outlettype", [])) == box["numoutlets"], path

    @pytest.mark.parametrize("name", ["live.dial", "live.numbox", "live.slider", "live.toggle",
                                      "live.button", "live.text", "live.menu", "live.tab",
                                      "live.gain~", "live.meter~", "live.comment", "live.grid",
                                      "live.step", "live.drop", "live.arrows", "live.line",
                                      "mc.live.gain~"])
    def test_ui_objects_keep_maxclass(self, name):
        obj = mp.MaxObject(name)
        assert not obj.notknown()
        assert _box(obj)["maxclass"] == name
        assert "text" not in _box(obj)

    @pytest.mark.parametrize("name,ins,outs", [("live.object", 2, 1), ("live.path", 1, 3),
                                               ("live.observer", 2, 2), ("live.thisdevice", 1, 3),
                                               ("live.remote~", 2, 1),
                                               ("live.modulate~", 2, 1), ("live.map", 1, 5),
                                               ("live.routing", 1, 5), ("live.banks", 1, 1),
                                               ("live.colors", 1, 2), ("live.miditool.in", 1, 3),
                                               ("live.miditool.out", 1, 0)])
    def test_api_objects_are_newobj(self, name, ins, outs):
        obj = mp.MaxObject(name)
        assert _box(obj)["maxclass"] == "newobj"
        assert _box(obj)["text"] == name
        assert (len(obj.ins), len(obj.outs)) == (ins, outs)

    def test_live_dial_io(self):
        dial = mp.MaxObject("live.dial")
        assert (len(dial.ins), len(dial.outs)) == (1, 2)
        assert _box(dial)["outlettype"] == ["", "float"]

    def test_live_gain_io(self):
        gain = mp.MaxObject("live.gain~")
        assert _box(gain)["outlettype"] == ["signal", "signal", "", "float", "list"]

    def test_live_param_tilde_takes_name(self):
        obj = mp.MaxObject("live.param~ Cutoff")
        assert not obj.notknown()
        assert _box(obj)["text"] == "live.param~ Cutoff"
        assert (len(obj.ins), len(obj.outs)) == (0, 1)

    def test_text_args_kept_for_api_objects(self):
        obs = mp.MaxObject("live.observer value")
        assert _box(obs)["text"] == "live.observer value"

    @needs_live
    def test_xlets_match_maxproto(self):
        checked = 0
        for path in glob.glob(os.path.join(PROTO_DIR, "live.*", "*.maxproto")):
            with open(path) as f:
                proto = json.load(f)["boxes"][0]["box"]
            box = _box(mp.MaxObject(proto["maxclass"]))
            assert box["maxclass"] == proto["maxclass"], path
            assert box["numinlets"] == proto["numinlets"], path
            assert box["numoutlets"] == proto["numoutlets"], path
            assert box.get("outlettype", []) == proto.get("outlettype", []), path
            checked += 1
        assert checked > 0

    def test_stubs(self):
        from maxpylang.objects import live_dial, live_thisdevice
        assert live_dial.name == "live.dial"
        assert live_thisdevice.name == "live.thisdevice"


# =====================================================================
# TEST 2: Connections
# =====================================================================

class TestConnections:
    def test_connect_live_dial_outlets(self):
        patch = mp.MaxPatch(verbose=False)
        dial = patch.place(_cutoff_dial())[0]
        filt = patch.place("lores~")[0]
        num = patch.place("flonum")[0]
        patch.connect([dial.outs[0], filt.ins[1]], [dial.outs[1], num.ins[0]], verbose=False)

        lines = patch.get_json()["patcher"]["lines"]
        sources = sorted(tuple(line["patchline"]["source"]) for line in lines)
        assert sources == [(_box(dial)["id"], 0), (_box(dial)["id"], 1)]

    def test_connect_into_live_gain(self):
        patch = mp.MaxPatch(verbose=False)
        plugin = patch.place("plugin~")[0]
        gain = patch.place("live.gain~")[0]
        plugout = patch.place("plugout~")[0]
        patch.connect([plugin.outs[0], gain.ins[0]], [plugin.outs[1], gain.ins[1]],
                      [gain.outs[0], plugout.ins[0]], [gain.outs[1], plugout.ins[1]], verbose=False)
        assert len(patch.get_json()["patcher"]["lines"]) == 4


# =====================================================================
# TEST 3: Live parameter attributes
# =====================================================================

class TestLiveParams:
    def test_params_in_valueof_not_top_level(self):
        box = _box(_cutoff_dial())
        for key in ("parameter_longname", "parameter_mmin", "parameter_mmax",
                    "parameter_initial", "parameter_unitstyle", "parameter_exponent"):
            assert key not in box
        valueof = box["saved_attribute_attributes"]["valueof"]
        assert valueof["parameter_longname"] == "Cutoff"
        assert valueof["parameter_mmin"] == 20.
        assert valueof["parameter_mmax"] == 20000.
        assert valueof["parameter_initial"] == [1000.]
        assert valueof["parameter_unitstyle"] == 3
        assert valueof["parameter_exponent"] == 3.

    def test_enable_varname_shortname_defaults(self):
        dial = _cutoff_dial()
        assert _box(dial)["parameter_enable"] == 1
        assert _box(dial)["varname"] == "Cutoff"
        assert _valueof(dial)["parameter_shortname"] == "Cutoff"
        assert _valueof(dial)["parameter_initial_enable"] == 1

    def test_explicit_varname_and_shortname(self):
        dial = _cutoff_dial(varname="cutoff_dial", parameter_shortname="Cut")
        assert _box(dial)["varname"] == "cutoff_dial"
        assert _valueof(dial)["parameter_shortname"] == "Cut"

    def test_plain_dial_defaults(self):
        dial = mp.MaxObject("live.dial")
        assert _box(dial)["parameter_enable"] == 1
        assert _valueof(dial)["parameter_longname"] == "live.dial"
        assert _valueof(dial)["parameter_type"] == 0

    def test_named_unitstyle_and_scalar_initial(self):
        dial = mp.MaxObject("live.dial", parameter_longname="Res", parameter_initial=0.3,
                            parameter_unitstyle="percent", parameter_type="float")
        assert _valueof(dial)["parameter_unitstyle"] == mp.m4l.UNITSTYLES["percent"] == 5
        assert _valueof(dial)["parameter_initial"] == [0.3]
        assert _valueof(dial)["parameter_type"] == 0

    def test_unknown_unitstyle_raises(self):
        with pytest.raises(ValueError):
            mp.MaxObject("live.dial", parameter_unitstyle="furlongs")

    def test_enum_params(self):
        menu = mp.MaxObject("live.menu", parameter_longname="Mode",
                            parameter_enum=["LP", "HP", "BP"], parameter_mmax=2)
        assert _valueof(menu)["parameter_enum"] == ["LP", "HP", "BP"]
        assert _valueof(menu)["parameter_type"] == 2

    def test_params_from_text_attribs(self):
        dial = mp.MaxObject("live.dial @parameter_longname Drive @parameter_mmax 24.")
        assert _valueof(dial)["parameter_longname"] == "Drive"
        assert _valueof(dial)["parameter_mmax"] == 24.
        assert "parameter_longname" not in _box(dial)

    def test_prototype(self):
        dial = mp.MaxObject("live.dial", prototype="freq", parameter_longname="Cutoff")
        assert _valueof(dial)["parameter_unitstyle"] == 3
        assert _valueof(dial)["parameter_mmax"] == 10000.
        assert _valueof(dial)["parameter_longname"] == "Cutoff"
        assert _valueof(dial)["parameter_shortname"] == "Cutoff"
        assert _box(dial)["varname"] == "Cutoff"

    def test_unknown_prototype_raises(self):
        with pytest.raises(ValueError):
            mp.MaxObject("live.dial", prototype="nope")

    def test_edit_updates_valueof(self):
        dial = _cutoff_dial()
        dial.edit(parameter_mmax=10000.)
        assert _valueof(dial)["parameter_mmax"] == 10000.
        assert _valueof(dial)["parameter_longname"] == "Cutoff"
        assert "text" not in _box(dial)

    def test_params_rejected_on_non_param_objects(self):
        obj = mp.MaxObject("live.object", parameter_longname="x")
        assert "saved_attribute_attributes" not in _box(obj)

    def test_float_attrib_on_regular_object(self):
        filt = mp.MaxObject("lores~", cutoff=200.)
        assert _box(filt)["cutoff"] == 200.


# =====================================================================
# TEST 4: live.comment / live.text text
# =====================================================================

class TestLiveText:
    def test_live_comment_text(self):
        comment = mp.MaxObject("live.comment Filter Cutoff")
        assert _box(comment)["text"] == "Filter Cutoff"

    def test_live_text_labels(self):
        button = mp.MaxObject("live.text @text Bypass @texton Active")
        assert _box(button)["text"] == "Bypass"
        assert _box(button)["texton"] == "Active"

    def test_present(self):
        dial = mp.MaxObject("live.dial")
        dial.present(10, 20)
        assert _box(dial)["presentation"] == 1
        assert _box(dial)["presentation_rect"] == [10., 20., 44., 47.]
        dial.present(0, 0, 60., 60.)
        assert _box(dial)["presentation_rect"] == [0., 0., 60., 60.]


# =====================================================================
# TEST 5: Round-trip
# =====================================================================

class TestRoundTrip:
    def test_amxd_round_trip_keeps_params(self, tmp_path):
        patch = mp.MaxPatch(verbose=False)
        dial = patch.place(_cutoff_dial())[0]
        dial.present(8, 8)
        patch.place("live.comment Cutoff", "live.thisdevice")
        filename = str(tmp_path / "rt.amxd")
        patch.save(filename, device_type="audio_effect", verbose=False, check=False)

        loaded = mp.MaxPatch(load_file=filename, verbose=False)
        dials = [o for o in loaded.objs.values() if o.name == "live.dial"]
        assert len(dials) == 1
        assert _box(dials[0]) == _box(dial)
        assert not dials[0].notknown()
        assert len(dials[0].outs) == 2

        resaved = str(tmp_path / "rt2.amxd")
        loaded.save(resaved, device_type="audio_effect", verbose=False, check=False)
        boxes = load_amxd(resaved)["patcher"]["boxes"]
        valueofs = [b["box"]["saved_attribute_attributes"]["valueof"] for b in boxes
                    if b["box"]["maxclass"] == "live.dial"]
        assert valueofs[0]["parameter_longname"] == "Cutoff"

    @needs_live
    @pytest.mark.parametrize("name", ["Max Audio Effect", "Max Instrument", "Max MIDI Effect"])
    def test_load_live_templates(self, name):
        patch = mp.MaxPatch(load_file=os.path.join(TEMPLATE_DIR, name + ".amxd"), verbose=False)
        assert patch.num_objs > 0
        assert all(not o.notknown() for o in patch.objs.values())


# =====================================================================
# TEST 6: Device settings
# =====================================================================

class TestDeviceSettings:
    def test_set_device(self, tmp_path):
        patch = mp.MaxPatch(verbose=False)
        patch.set_device(openinpresentation=1, devicewidth=240., latency=64)
        filename = str(tmp_path / "dev.amxd")
        patch.save(filename, device_type="instrument", verbose=False, check=False)
        patcher = load_amxd(filename)["patcher"]
        assert patcher["openinpresentation"] == 1
        assert patcher["devicewidth"] == 240.
        assert patcher["latency"] == 64

    def test_set_device_unknown_key_raises(self):
        with pytest.raises(ValueError):
            mp.MaxPatch(verbose=False).set_device(bogus=1)

    @pytest.mark.parametrize("device_type", list(mp.DEVICE_TYPES))
    def test_project_amxdtype(self, tmp_path, device_type):
        patch = mp.MaxPatch(verbose=False)
        filename = str(tmp_path / "dev.amxd")
        patch.save(filename, device_type=device_type, verbose=False, check=False)
        patcher = load_amxd(filename)["patcher"]
        code = mp.DEVICE_TYPES[device_type]
        assert patcher["project"]["amxdtype"] == int.from_bytes(code, "big")
        assert patcher["openrect"] == [0.0, 0.0, 0.0, 169.0]

    def test_maxpat_save_has_no_device_keys(self, tmp_path):
        patch = mp.MaxPatch(verbose=False)
        filename = str(tmp_path / "plain.maxpat")
        patch.save(filename, verbose=False, check=False)
        with open(filename) as f:
            assert "project" not in json.load(f)["patcher"]


# =====================================================================
# TEST 7: Header bytes
# =====================================================================

class TestHeader:
    @pytest.mark.parametrize("device_type", list(mp.DEVICE_TYPES))
    def test_header_layout(self, tmp_path, device_type):
        filename = str(tmp_path / "h.amxd")
        mp.MaxPatch(verbose=False).save(filename, device_type=device_type, verbose=False, check=False)
        with open(filename, "rb") as f:
            data = f.read()
        expected = (b"ampf" + struct.pack("<I", 4) + mp.DEVICE_TYPES[device_type] +
                    b"meta" + struct.pack("<I", 4) + b"\x00" * 4 + b"ptch")
        assert data[:28] == expected
        assert struct.unpack("<I", data[28:32])[0] == len(data) - 32
        assert data.endswith(b"}\n\x00")

    @needs_live
    @pytest.mark.parametrize("name,device_type", [("Max Audio Effect", "audio_effect"),
                                                  ("Max Instrument", "instrument"),
                                                  ("Max MIDI Effect", "midi_effect")])
    def test_header_matches_live_template(self, tmp_path, name, device_type):
        with open(os.path.join(TEMPLATE_DIR, name + ".amxd"), "rb") as f:
            ref = f.read()
        filename = str(tmp_path / "h.amxd")
        mp.MaxPatch(verbose=False).save(filename, device_type=device_type, verbose=False, check=False)
        with open(filename, "rb") as f:
            data = f.read()
        assert data[:28] == ref[:28]
        assert ref[-3:] == data[-3:] == b"}\n\x00"
        assert struct.unpack("<I", ref[28:32])[0] == len(ref) - 32
        assert load_amxd(filename)["patcher"]["project"]["amxdtype"] == \
            load_amxd(os.path.join(TEMPLATE_DIR, name + ".amxd"))["patcher"]["project"]["amxdtype"]


# =====================================================================
# TEST 8: Example device
# =====================================================================

class TestExample:
    def test_m4l_filter_device_example(self, tmp_path):
        example = os.path.join(os.path.dirname(__file__), "..", "examples", "m4l_filter_device", "main.py")
        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            exec(open(example).read(), {"__name__": "__main__"})
        finally:
            os.chdir(old_cwd)

        patcher = load_amxd(str(tmp_path / "m4l_filter_device.amxd"))["patcher"]
        assert patcher["openinpresentation"] == 1
        dials = {b["box"]["varname"]: b["box"] for b in patcher["boxes"]
                 if b["box"]["maxclass"] == "live.dial"}
        assert set(dials) == {"Cutoff", "Resonance"}
        assert all(d["presentation"] == 1 for d in dials.values())
        assert dials["Cutoff"]["saved_attribute_attributes"]["valueof"]["parameter_unitstyle"] == 3
