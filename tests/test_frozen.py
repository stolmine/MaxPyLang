"""
Tests for reading frozen / meta-less / encrypted .amxd files.

Tests:
1. mx@c container parsing (synthetic devices built with tests/devfixtures.py)
2. .amxd layouts: frozen, meta-less, plain, encrypted, malformed
3. MaxPatch(load_file=...) on frozen devices
4. Real devices from the Live install / device library (skipped when missing)
"""

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import devfixtures as F
import maxpylang as mp
from maxpylang.amxd import parse_amxd, read_amxd
from maxpylang.exceptions import DeviceReadError, EncryptedDeviceError
from maxpylang.frozen import main_file, parse_container

AUTOFILTER = os.path.join(F.M4L_PATCHERS, "Max Audio Effect/Max AutoFilter/Max AutoFilter.amxd")
COMPRESSOR = os.path.join(F.M4L_PATCHERS, "Max Audio Effect/Max Compressor/Max Compressor.amxd")
VELOCITY_SHAPER = os.path.join(F.LIVE_RES, "Builtin/Devices/MIDI Tools/Transformations/"
                                           "Velocity Shaper/Velocity Shaper.amxd")


@pytest.fixture
def frozen_path(tmp_path):
    return F.write(tmp_path / "Synthetic.amxd", F.freeze(F.build_device(), F.bundle_files()))


# =====================================================================
# TEST 1: mx@c container
# =====================================================================

class TestContainer:
    def test_files_in_directory_order(self):
        files = parse_container(F.container(F.build_device(), F.bundle_files()))
        assert [f.name for f in files] == ["Synthetic.amxd", "myabs.maxpat", "helper.js", "knob.svg"]
        assert [f.type for f in files] == ["JSON", "JSON", "TEXT", "svg"]

    def test_main_file_flag(self):
        files = parse_container(F.container(F.build_device(), F.bundle_files()))
        main = main_file(files)
        assert main.is_main and main.flags == 0x11 and main.offset == 16
        assert not any(f.is_main for f in files[1:])

    def test_file_bytes_and_sizes(self):
        files = parse_container(F.container(F.build_device(), F.bundle_files()))
        js = files[2]
        assert js.data == F.JS_SOURCE.encode()
        assert js.size == len(js.data)
        assert js.text() == F.JS_SOURCE

    def test_mdate_is_mac_epoch(self):
        files = parse_container(F.container(F.build_device()))
        assert files[0].modified.year == 2023

    def test_stale_bytes_after_directory_ignored(self):
        files = parse_container(F.container(F.build_device(), F.bundle_files(), stale=b"dire" * 50))
        assert len(files) == 4

    def test_not_a_container(self):
        with pytest.raises(DeviceReadError):
            parse_container(b'{"patcher": {}}')

    def test_bad_directory_offset(self):
        data = bytearray(F.container(F.build_device()))
        data[12:16] = (5).to_bytes(4, "big")
        with pytest.raises(DeviceReadError, match="dlst"):
            parse_container(bytes(data))

    def test_truncated_entry(self):
        data = F.container(F.build_device())
        with pytest.raises(DeviceReadError):
            parse_container(data[:-20])


# =====================================================================
# TEST 2: .amxd layouts
# =====================================================================

class TestLayouts:
    def test_frozen_device(self, frozen_path):
        device = read_amxd(frozen_path)
        assert device.frozen
        assert device.device_type == "audio_effect"
        assert device.chunks == ["ampf", "meta", "ptch"]
        assert device.main_name == "Synthetic.amxd"
        assert [f.name for f in device.embedded] == ["myabs.maxpat", "helper.js", "knob.svg"]
        assert device.patcher_json["patcher"]["devicewidth"] == 200.0

    def test_meta_less_device(self):
        device = parse_amxd(F.freeze(F.build_device(), meta=False, device_type="instrument"))
        assert device.chunks == ["ampf", "ptch"]
        assert device.device_type == "instrument"
        assert device.frozen

    def test_plain_device(self, tmp_path):
        path = str(tmp_path / "plain.amxd")
        mp.save_amxd(F.build_device(), path, device_type="midi_effect")
        device = read_amxd(path)
        assert not device.frozen and device.files == []
        assert device.device_type == "midi_effect"

    def test_encrypted_device_raises(self, tmp_path):
        path = F.write(tmp_path / "enc.amxd", F.encrypted_bytes())
        with pytest.raises(EncryptedDeviceError, match="encrypted device"):
            read_amxd(path)
        with pytest.raises(EncryptedDeviceError):
            mp.load_amxd(path)

    def test_not_amxd(self):
        with pytest.raises(DeviceReadError, match="ampf"):
            parse_amxd(b"hello world, not a device")

    def test_invalid_frozen_json(self):
        data = bytearray(F.freeze(F.build_device()))
        data[data.index(b'{\n  "patcher"')] = ord("X")
        with pytest.raises(DeviceReadError, match="invalid JSON"):
            parse_amxd(bytes(data))

    def test_read_does_not_modify_file(self, frozen_path):
        before = hashlib.sha256(open(frozen_path, "rb").read()).hexdigest()
        mtime = os.path.getmtime(frozen_path)
        read_amxd(frozen_path)
        mp.describe(frozen_path)
        assert hashlib.sha256(open(frozen_path, "rb").read()).hexdigest() == before
        assert os.path.getmtime(frozen_path) == mtime


# =====================================================================
# TEST 3: MaxPatch loading
# =====================================================================

class TestMaxPatchLoad:
    def test_load_frozen(self, frozen_path):
        patch = mp.MaxPatch(load_file=frozen_path, verbose=False)
        assert patch.num_objs == len(F.build_device()["patcher"]["boxes"])

    def test_load_meta_less(self, tmp_path):
        path = F.write(tmp_path / "old.amxd", F.freeze(F.midi_device(), meta=False,
                                                       device_type="midi_effect"))
        patch = mp.MaxPatch(load_file=path, verbose=False)
        assert {o.name for o in patch.objs.values()} >= {"midiin", "midiout"}


# =====================================================================
# TEST 4: real devices
# =====================================================================

@pytest.mark.skipif(not os.path.exists(AUTOFILTER), reason="Ableton Live 12 Suite not installed")
def test_live_autofilter_frozen():
    device = read_amxd(AUTOFILTER)
    assert device.frozen and device.chunks == ["ampf", "meta", "ptch"]
    assert device.main_name == "Max AutoFilter.amxd"
    assert device.patcher_json["patcher"]["boxes"]
    mp.MaxPatch(load_file=AUTOFILTER, verbose=False)


@pytest.mark.skipif(not os.path.exists(COMPRESSOR), reason="Ableton Live 12 Suite not installed")
def test_live_meta_less_with_stale_directory():
    device = read_amxd(COMPRESSOR)
    assert device.chunks == ["ampf", "ptch"]
    assert [f.name for f in device.files] == ["Max Compressor.amxd", "omx.comp~flow.png"]


@pytest.mark.skipif(not os.path.exists(VELOCITY_SHAPER), reason="Ableton Live 12 Suite not installed")
def test_live_encrypted():
    with pytest.raises(EncryptedDeviceError):
        read_amxd(VELOCITY_SHAPER)
