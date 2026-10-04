"""
v8.py — v8.codebox boxes: modern-engine JavaScript embedded in the patch.

v8_codebox() returns a MaxObject for a ``v8.codebox`` UI box whose JavaScript lives in
the box's ``code`` key (no .js file), so it travels inside a .maxpat or a non-frozen
.amxd and Max compiles it when the patch loads::

    code = "inlets = 1;\\noutlets = 2;\\nfunction bang() { outlet(1, 'hi'); }"
    js = patch.place(mp.v8_codebox(code))[0]          # 1 in / 2 out, read from the code

The box layout matches what Max 9 saves for a v8.codebox (maxclass "v8.codebox",
``code``, ``filename`` "none", monospaced font, saved_object_attributes).

js_io() reads the ``inlets = N`` / ``outlets = N`` declarations from the code.
"""

import copy
import re

from .maxobject import MaxObject

CODEBOX_FONT = {"fontface": 0, "fontname": "<Monospaced>", "fontsize": 12.0}

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_DECL = re.compile(r"(?<![\w.$])(inlets|outlets)\s*=\s*(\d+)\s*;?")


def js_io(code):
    """
    Return (inlets, outlets) declared in JavaScript with ``inlets = N`` / ``outlets = N``.

    Missing declarations default to 1, as in Max. The last declaration wins.
    """
    found = {"inlets": 1, "outlets": 1}
    for name, num in _DECL.findall(_COMMENT.sub(" ", code)):
        found[name] = int(num)
    return found["inlets"], found["outlets"]


def v8_codebox(code, inlets=None, outlets=None, size=(400.0, 200.0), **box_attribs):
    """
    Return a MaxObject: a v8.codebox UI box holding JavaScript source.

    code --> JavaScript source (v8 engine, ES6+; LiveAPI, Task, File, Dict available)
    inlets / outlets --> box xlet counts; default to the code's ``inlets = N`` /
                         ``outlets = N`` declarations (1 when absent). Must match them,
                         since Max rebuilds the xlets from the code when it compiles.
    size --> (width, height) of the box in the patcher
    box_attribs --> extra box keys, e.g. varname="probe", linenumbers=1

    Raises ValueError for empty code or counts that disagree with the code.
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError("v8_codebox needs non-empty JavaScript code")

    code_in, code_out = js_io(code)
    inlets = code_in if inlets is None else inlets
    outlets = code_out if outlets is None else outlets
    if (inlets, outlets) != (code_in, code_out):
        raise ValueError(f"code declares {code_in} inlets / {code_out} outlets, but the box "
                         f"asks for {inlets} / {outlets}; set inlets/outlets in the code")

    box = {"id": "obj-1", "maxclass": "v8.codebox", "code": code, "filename": "none",
           **CODEBOX_FONT, "numinlets": inlets, "numoutlets": outlets,
           "outlettype": [""] * outlets,
           "patching_rect": [100.0, 100.0, float(size[0]), float(size[1])],
           "saved_object_attributes": {"parameter_enable": 0}}
    box.update(copy.deepcopy(box_attribs))
    return MaxObject({"box": box}, from_dict=True)
