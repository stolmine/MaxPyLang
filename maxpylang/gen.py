"""
gen.py — gen~ boxes whose DSP is a GenExpr codebox.

gen_codebox() returns a MaxObject for a gen~ (or gen) box that carries its own
patcher (no .gendsp file): ``in N`` objects -> one codebox -> ``out N`` objects.
This is the layout Max writes for an inline codebox, so the code travels inside a
.maxpat or a non-frozen .amxd and Max compiles it when the patch loads::

    code = "Param gain(0.5, min=0, max=1);\\nout1 = in1 * gain;\\nout2 = in2 * gain;"
    gen = patch.place(mp.gen_codebox(code))[0]            # 2 in / 2 out, from the code
    patch.connect([plugin.outs[0], gen.ins[0]], [plugin.outs[1], gen.ins[1]])

genexpr_params() and genexpr_io() read Param names and in/out counts from GenExpr.
"""

import copy
import json
import os
import re

from .maxobject import MaxObject
from .tools.constants import obj_info_folder

GEN_KINDS = {"gen~": "signal", "gen": "float"}

#gen operators and keywords that a Param name would shadow
RESERVED_NAMES = frozenset("""
    abs accum and atodb buffer ceil change channels clamp clip cos counter cycle data dbtoa
    dcblock delay delta dim elapsed exp fixdenorm fixnan floor fold fract ftom gate history
    in interp isnan latch log lookup max maximum min minimum mix mod mstosamps mtof mulequals
    noise not or out param peek phasor pi plusequals poke pow rate round sah sample samplerate
    sampstoms scale selector sign sin slide smoothstep splat sqrt step switch t60 t60time tan
    train triangle trunc twopi vectorsize wave wrap xor
""".split())

CODEBOX_FONT = {"fontface": 0, "fontname": "<Monospaced>", "fontsize": 12.0}

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_IN = re.compile(r"(?<![\w.])in(\d+)\b")
_OUT = re.compile(r"(?<![\w.])out(\d+)\b")
_PARAM = re.compile(r"(?<![\w.])Param\s+([^;]*);")
_IDENT = re.compile(r"\s*([A-Za-z_]\w*)")


def _strip_comments(code):
    return _COMMENT.sub(" ", code)


def _split_top_level(text):
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def genexpr_params(code):
    """
    Return the Param names declared in GenExpr code, in order.

    Handles several declarations per statement: ``Param a(0), b(1, min=0);``.
    """
    names = []
    for decl in _PARAM.findall(_strip_comments(code)):
        for part in _split_top_level(decl):
            match = _IDENT.match(part)
            if match and match.group(1) not in names:
                names.append(match.group(1))
    return names


def genexpr_io(code):
    """
    Return (inlets, outlets): the highest ``inN`` / ``outN`` used in GenExpr code.
    """
    code = _strip_comments(code)
    ins = [int(n) for n in _IN.findall(code)]
    outs = [int(n) for n in _OUT.findall(code)]
    return max(ins, default=0), max(outs, default=0)


def _format_value(val):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise TypeError(f"gen Param values must be numbers, got {val!r}")
    return repr(float(val)) if isinstance(val, float) else str(val)


def param_declarations(params):
    """
    Return GenExpr Param lines for {name: default} or {name: {"default", "min", "max"}}.
    """
    lines = []
    for name, spec in params.items():
        if isinstance(spec, dict):
            unknown = set(spec) - {"default", "min", "max"}
            if unknown:
                raise ValueError(f"gen Param {name!r}: unknown keys {sorted(unknown)}")
            args = [_format_value(spec.get("default", 0))]
            args += [f"{key}={_format_value(spec[key])}" for key in ("min", "max") if key in spec]
        else:
            args = [_format_value(spec)]
        lines.append(f"Param {name}({', '.join(args)});")
    return lines


def check_param_names(names):
    """Raise ValueError for Param names that are not identifiers or shadow gen operators."""
    for name in names:
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            raise ValueError(f"gen Param name {name!r} is not an identifier")
        if name.lower() in RESERVED_NAMES:
            raise ValueError(f"gen Param name {name!r} shadows the gen operator {name.lower()!r}; "
                             f"choose another name")


def _patcher_template():
    with open(os.path.join(obj_info_folder, "msp", "gen~.json")) as f:
        patcher = json.load(f)["default"]["box"]["patcher"]
    patcher["boxes"], patcher["lines"] = [], []
    return patcher


def _box(box_id, text, numinlets, numoutlets, rect):
    box = {"id": box_id, "maxclass": "newobj", "numinlets": numinlets,
           "numoutlets": numoutlets, "patching_rect": [float(v) for v in rect], "text": text}
    if numoutlets:
        box["outlettype"] = [""] * numoutlets
    return {"box": box}


def _line(src, src_out, dst, dst_in):
    return {"patchline": {"source": [src, src_out], "destination": [dst, dst_in]}}


def gen_patcher(code, inlets, outlets, size=(600.0, 450.0)):
    """
    Return the dsp.gen patcher dict: ``in 1..inlets`` -> codebox -> ``out 1..outlets``.

    The codebox gets one inlet/outlet per ``inN``/``outN`` its code uses.
    """
    code_in, code_out = genexpr_io(code)
    width, height = float(size[0]), float(size[1])
    spacing = max(width / max(inlets, outlets, 1), 40.0)

    patcher = _patcher_template()
    patcher["rect"] = [0.0, 0.0, width + 60.0, height + 130.0]
    boxes, lines = patcher["boxes"], patcher["lines"]

    codebox = {"id": "obj-codebox", "maxclass": "codebox", "code": code, **CODEBOX_FONT,
               "numinlets": code_in, "numoutlets": code_out,
               "outlettype": [""] * code_out, "patching_rect": [20.0, 50.0, width, height]}
    boxes.append({"box": codebox})

    for n in range(1, inlets + 1):
        boxes.append(_box(f"obj-in-{n}", f"in {n}", 0, 1, [20 + (n - 1) * spacing, 15, 30, 22]))
        if n <= code_in:
            lines.append(_line(f"obj-in-{n}", 0, "obj-codebox", n - 1))
    for n in range(1, outlets + 1):
        boxes.append(_box(f"obj-out-{n}", f"out {n}", 1, 0,
                          [20 + (n - 1) * spacing, 50 + height + 20, 37, 22]))
        if n <= code_out:
            lines.append(_line("obj-codebox", n - 1, f"obj-out-{n}", 0))
    return patcher


def gen_codebox(code, inlets=None, outlets=None, params=None, kind="gen~",
                codebox_size=(600.0, 450.0), **box_attribs):
    """
    Return a MaxObject: a gen~ box with an embedded patcher holding one GenExpr codebox.

    code --> GenExpr source (Max compiles it when the patch loads)
    inlets / outlets --> box inlet/outlet count; defaults to the highest inN / outN in
                         the code. Must be at least what the code uses.
    params --> optional {name: default} or {name: {"default", "min", "max"}}; prepended to
               the code as Param declarations (set them with ``<name> <value>`` messages
               into the first inlet)
    kind --> "gen~" (signal outlets) or "gen" (event-rate, float outlets)
    codebox_size --> (width, height) of the codebox inside the gen patcher
    box_attribs --> extra box keys, e.g. varname="dsp"

    Param names that shadow gen operators (mix, wrap, delay, ...) raise ValueError.
    """
    if kind not in GEN_KINDS:
        raise ValueError(f"kind must be one of {', '.join(GEN_KINDS)}, got {kind!r}")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("gen_codebox needs non-empty GenExpr code")

    if params:
        code = "\n".join(param_declarations(params)) + "\n" + code
    check_param_names(genexpr_params(code))

    code_in, code_out = genexpr_io(code)
    inlets = code_in if inlets is None else inlets
    outlets = code_out if outlets is None else outlets
    if inlets < code_in or outlets < code_out:
        raise ValueError(f"code uses in1..in{code_in} / out1..out{code_out}, but the box has "
                         f"{inlets} inlets / {outlets} outlets")

    box = {"id": "obj-1", "maxclass": "newobj", "text": kind,
           "numinlets": max(inlets, 1), "numoutlets": outlets,
           "outlettype": [GEN_KINDS[kind]] * outlets,
           "patching_rect": [100.0, 100.0, max(60.0, 24.0 * max(inlets, outlets)), 22.0],
           "patcher": gen_patcher(code, inlets, outlets, codebox_size)}
    box.update(copy.deepcopy(box_attribs))
    return MaxObject({"box": box}, from_dict=True)
