"""
Tests for maxpylang.devinspect (describe / params / extract / survey) and the CLI.

Tests:
1. Parameters (type, range, unit, enum, modulation, presentation)
2. Hierarchy (subpatcher, bundled abstraction, gen~) and code
3. Signal flow (audio path, MIDI path, parameter tracing through s/r, subpatcher inlets,\n   routing hubs; AutoFilter Env* params when installed)
4. Device view and comments
5. Output formats (Markdown, JSON)
6. extract / survey
7. CLI
8. Corpus sweep: every readable, non-encrypted device describes (skipped when missing)
"""

import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import devfixtures as F
import maxpylang as mp
from maxpylang.cli import main
from maxpylang.exceptions import EncryptedDeviceError


@pytest.fixture
def device_path(tmp_path):
    return F.write(tmp_path / "Synthetic.amxd", F.freeze(F.build_device(), F.bundle_files()))


@pytest.fixture
def desc(device_path):
    return mp.describe(device_path)


@pytest.fixture
def routing(tmp_path):
    path = F.write(tmp_path / "Routing.amxd", F.freeze(F.routing_device(), F.routing_files()))
    return mp.describe(path)


AUTOFILTER = os.path.join(F.M4L_PATCHERS, "Max Audio Effect/Max AutoFilter/Max AutoFilter.amxd")


def _param(desc, name):
    return next(p for p in desc.params if p["longname"] == name)


def _run(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    out = capsys.readouterr()
    return exc.value.code, out.out, out.err


# =====================================================================
# TEST 1: Parameters
# =====================================================================

class TestParams:
    def test_param_count(self, desc):
        assert [p["longname"] for p in desc.params] == ["Cutoff", "Mode", "Hidden Gain"]

    def test_float_param(self, desc):
        p = _param(desc, "Cutoff")
        assert (p["shortname"], p["type"], p["object"]) == ("Cut", "float", "live.dial")
        assert (p["min"], p["max"], p["initial"]) == (20, 20000, 1000)
        assert (p["unitstyle"], p["exponent"], p["modulation"]) == ("hertz", 3, "bipolar")
        assert p["presentation"] and p["path"] == "/"

    def test_enum_param(self, desc):
        p = _param(desc, "Mode")
        assert p["type"] == "enum" and p["enum"] == ["lp", "hp"]

    def test_defaults_filled(self, desc):
        p = _param(desc, "Hidden Gain")
        assert (p["type"], p["min"], p["max"]) == ("float", 0, 127)
        assert not p["presentation"]

    def test_format_param(self, desc):
        line = mp.devinspect.format_param(_param(desc, "Cutoff"))
        assert line.startswith("float 20..20000") and "hertz" in line and "exp 3" in line


# =====================================================================
# TEST 2: Hierarchy and code
# =====================================================================

class TestHierarchy:
    def test_paths_and_kinds(self, desc):
        kinds = {h["path"]: (h["kind"], h["source"]) for h in desc.hierarchy}
        assert kinds["/"][0] == "device"
        assert kinds["/p filter[obj-2]"] == ("p", "embedded")
        assert kinds["/myabs[obj-3]"] == ("abstraction", "bundle:myabs.maxpat")
        assert kinds["/gen~[obj-4]"] == ("gen~", "embedded")
        assert desc.unresolved == []

    def test_unresolved_abstraction(self, tmp_path):
        data = F.build_device()
        for b in data["patcher"]["boxes"]:
            if b["box"].get("text") == "gen~":
                b["box"]["text"] = "poly~ missing.voice 4"
                del b["box"]["patcher"]
        path = F.write(tmp_path / "u.amxd", F.freeze(data, F.bundle_files()))
        d = mp.describe(path)
        assert d.unresolved == [{"path": "/", "box_id": "obj-4", "kind": "poly~",
                                 "name": "missing.voice"}]

    def test_code_sources(self, desc):
        code = {c["object"]: c for c in desc.code}
        assert code["js"]["file"] == "helper.js" and code["js"]["origin"] == "bundle:helper.js"
        assert code["js"]["text"] == F.JS_SOURCE
        assert code["gen codebox"]["text"] == F.GEN_CODE

    def test_maxpat_input(self, tmp_path):
        path = tmp_path / "p.maxpat"
        path.write_text(json.dumps(F.midi_device()))
        d = mp.describe(str(path))
        assert d.device_type == "patcher" and not d.frozen


# =====================================================================
# TEST 3: Signal flow
# =====================================================================

class TestFlow:
    def test_audio_chain_through_subpatchers(self, desc):
        chain = desc.audio["chain"]
        assert chain[0] == "plugin~" and chain[-1] == "plugout~"
        assert "lores~ 1000 0.5 (in p filter[obj-2])" in chain
        assert "*~ 0.5 (in myabs[obj-3])" in chain
        assert "gen~" in chain

    def test_param_through_send_receive(self, desc):
        assert _param(desc, "Cutoff")["feeds"] == ["lores~ 1000 0.5 (in p filter[obj-2])"]

    def test_param_direct(self, desc):
        assert _param(desc, "Hidden Gain")["feeds"] == ["*~ 1.0"]

    def test_param_reaches_js(self, desc):
        p = _param(desc, "Mode")
        assert p["feeds"] == [] and p["reaches"] == ["js helper.js"]

    def test_abstraction_inlets_respected(self, routing):
        assert _param(routing, "Alpha")["feeds"] == ["cycle~ 440 (in twoin[obj-3])"]
        assert _param(routing, "Beta")["feeds"] == ["lores~ 1000 0.5 (in twoin[obj-3])"]

    def test_routing_hub_does_not_fan_out(self, routing):
        assert _param(routing, "Gamma")["feeds"] == ["phasor~"]
        assert _param(routing, "Delta")["feeds"] == ["svf~"]

    def test_message_and_send_receive_pass_through(self, routing):
        assert _param(routing, "Echo")["feeds"] == ["*~ 1. (in p mixer[obj-15])"]
        assert _param(routing, "Foxtrot")["feeds"] == ["noise~ (in p mixer[obj-15])"]

    def test_markdown_caps_feeds(self, desc):
        p = _param(desc, "Hidden Gain")
        p["feeds"] = [f"*~ {i}" for i in range(9)]
        assert "  - feeds: *~ 0; *~ 1; *~ 2; *~ 3; *~ 4; *~ 5; +3 more" in desc.to_markdown()

    @pytest.mark.skipif(not os.path.exists(AUTOFILTER), reason="Max AutoFilter not installed")
    def test_autofilter_env_params_distinct(self):
        d = mp.describe(AUTOFILTER)
        env = {p["longname"]: tuple(p["feeds"]) for p in d.params
               if p["longname"].startswith("Env")}
        assert len(env) == 6 and all(env.values())
        assert len(set(env.values())) >= 5
        assert env["EnvMode"] == ("average~ 44100 absolute (in M4L.envfol~ x2)",)
        assert env["EnvSharpness"] == ("pow~ (in M4L.envfol~ x2)",)
        assert "slide~ (in M4L.envfol~ x2)" in env["EnvSmooth"]

    def test_wireless_edges(self, desc):
        assert [w["name"] for w in desc.graph["wireless"]] == ["---cut"]

    def test_midi_path(self, tmp_path):
        path = F.write(tmp_path / "m.amxd", F.freeze(F.midi_device(), device_type="midi_effect"))
        d = mp.describe(path)
        assert d.midi["connected"]
        assert d.midi["chain"] == ["midiin", "midiparse", "midiformat", "midiout"]
        assert d.audio["sources"] == [] and d.audio["sinks"] == []


# =====================================================================
# TEST 4: Device view and comments
# =====================================================================

class TestView:
    def test_view_order(self, desc):
        assert [(v["class"], v["caption"]) for v in desc.view] == [
            ("live.tab", "Mode"), ("comment", "Cutoff"), ("live.dial", "Cut")]

    def test_comments(self, desc):
        by_text = {c["text"]: c["presentation"] for c in desc.comments}
        assert by_text == {"Cutoff": True, "Patching note: filter runs first": False}


# =====================================================================
# TEST 5: Output formats
# =====================================================================

class TestOutput:
    def test_markdown_sections(self, desc):
        md = desc.to_markdown()
        for heading in ("# Synthetic", "## Device view", "## Parameters (3)", "## Signal flow",
                        "## Structure", "## Embedded files (4)", "## Code"):
            assert heading in md
        assert "**Cutoff (`Cut`)**" in md
        assert "Audio path: plugin~ ->" in md

    def test_markdown_depth(self, desc):
        assert "p filter[obj-2]" not in desc.to_markdown(depth=0).split("## Structure")[1] \
            .split("## Objects")[0]

    def test_code_truncation(self, tmp_path):
        files = F.bundle_files()
        files[1] = ("helper.js", b"TEXT", "\n".join(f"// line {i}" for i in range(100)).encode())
        d = mp.describe(F.write(tmp_path / "c.amxd", F.freeze(F.build_device(), files)))
        assert "// line 99" not in d.to_markdown()
        assert "more lines (use --full-code)" in d.to_markdown()
        assert "// line 99" in d.to_markdown(full_code=True)

    def test_json(self, desc):
        data = json.loads(desc.to_json())
        assert data["device_type"] == "audio_effect" and data["frozen"]
        assert len(data["params"]) == 3
        assert data["graph"]["cords"]
        assert data["code"][0]["text"]


# =====================================================================
# TEST 6: extract / survey
# =====================================================================

class TestExtractSurvey:
    def test_extract(self, device_path, tmp_path):
        before = hashlib.sha256(open(device_path, "rb").read()).hexdigest()
        out = tmp_path / "out"
        written = mp.extract(device_path, str(out))
        assert sorted(os.path.basename(w) for w in written) == [
            "Synthetic.maxpat", "helper.js", "knob.svg", "myabs.maxpat"]
        assert (out / "helper.js").read_text() == F.JS_SOURCE
        patch = mp.MaxPatch(load_file=str(out / "Synthetic.maxpat"), verbose=False)
        assert patch.num_objs == len(F.build_device()["patcher"]["boxes"])
        assert hashlib.sha256(open(device_path, "rb").read()).hexdigest() == before

    def test_extract_sanitizes_names(self, tmp_path):
        files = [("../../evil.js", b"TEXT", b"x"), ("a.js", b"TEXT", b"1"), ("a.js", b"TEXT", b"2")]
        path = F.write(tmp_path / "e.amxd", F.freeze(F.build_device(), files))
        written = mp.extract(path, str(tmp_path / "out"))
        assert all(os.path.dirname(w) == str(tmp_path / "out") for w in written)
        assert sorted(os.path.basename(w) for w in written) == ["a-2.js", "a.js", "e.maxpat",
                                                                "evil.js"]

    def test_survey(self, tmp_path):
        F.write(tmp_path / "frozen.amxd", F.freeze(F.build_device(), F.bundle_files()))
        mp.save_amxd(F.midi_device(), str(tmp_path / "plain.amxd"), device_type="midi_effect")
        F.write(tmp_path / "secret.amxd", F.encrypted_bytes())
        F.write(tmp_path / "junk.amxd", b"not a device")
        rows = {r["name"]: r for r in mp.survey(str(tmp_path))}
        assert rows["frozen"]["status"] == "frozen" and rows["frozen"]["params"] == 3
        assert rows["frozen"]["files"] == 3
        assert rows["plain"]["status"] == "plain" and rows["plain"]["type"] == "midi_effect"
        assert rows["secret"]["status"] == "encrypted"
        assert rows["junk"]["status"].startswith("error")

    def test_describe_encrypted(self, tmp_path):
        with pytest.raises(EncryptedDeviceError):
            mp.describe(F.write(tmp_path / "s.amxd", F.encrypted_bytes()))


# =====================================================================
# TEST 7: CLI
# =====================================================================

class TestCLI:
    def test_describe(self, device_path, capsys):
        code, out, _ = _run(["describe", device_path], capsys)
        assert code == 0 and out.startswith("# Synthetic")

    def test_describe_json(self, device_path, capsys):
        code, out, _ = _run(["describe", device_path, "--json"], capsys)
        assert code == 0 and json.loads(out)["name"] == "Synthetic"

    def test_params(self, device_path, capsys):
        code, out, _ = _run(["params", device_path], capsys)
        assert code == 0
        assert out.splitlines()[0].startswith("Cutoff (Cut): live.dial, float 20..20000")

    def test_extract(self, device_path, tmp_path, capsys):
        code, out, _ = _run(["extract", device_path, str(tmp_path / "x")], capsys)
        assert code == 0 and len(out.splitlines()) == 4

    def test_survey(self, device_path, capsys):
        code, out, err = _run(["survey", os.path.dirname(device_path)], capsys)
        assert code == 0 and "Synthetic" in out and "3 params" in out
        assert "1 devices" in err

    def test_encrypted(self, tmp_path, capsys):
        code, _, err = _run(["describe", F.write(tmp_path / "s.amxd", F.encrypted_bytes())],
                            capsys)
        assert code == 2 and "encrypted device — cannot be read" in err

    def test_missing_file(self, tmp_path, capsys):
        code, _, err = _run(["params", str(tmp_path / "nope.amxd")], capsys)
        assert code == 1 and "nope.amxd" in err


# =====================================================================
# TEST 8: Corpus sweep
# =====================================================================

CORPUS = F.corpus_paths()


@pytest.mark.skipif(not CORPUS, reason="no .amxd corpus on this machine")
def test_corpus_sweep():
    described, encrypted, unreadable, failed = 0, 0, 0, []
    for path in CORPUS:
        try:
            with open(path, "rb"):
                pass
        except OSError:
            unreadable += 1
            continue
        try:
            d = mp.describe(path)
            d.to_markdown()
            d.to_json()
            described += 1
        except EncryptedDeviceError:
            encrypted += 1
        except Exception as exc:
            failed.append(f"{path}: {exc!r}")
    assert failed == []
    assert described > 0
