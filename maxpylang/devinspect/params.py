"""
devinspect.params

Collect Live parameters from every patcher of a device.

    collect_params() --> list of parameter dicts (longname, type, range, unit, ...)

Max omits values equal to the class default when saving, so missing values are
filled from the m4l object database defaults (parameter_type, enum, range).
"""

import json
import os
from functools import lru_cache

from maxpylang.m4l import PARAM_TYPES, UNITSTYLES
from maxpylang.tools.constants import obj_info_folder

from .tree import box_word

TYPE_NAMES = {code: name for name, code in PARAM_TYPES.items()}
UNIT_NAMES = {code: name for name, code in UNITSTYLES.items()}
MODMODES = {0: "none", 1: "unipolar", 2: "bipolar", 3: "additive", 4: "absolute"}
FALLBACK_TYPES = {"flonum": 0, "number": 1, "toggle": 1, "umenu": 2, "slider": 1, "dial": 1}


@lru_cache(maxsize=None)
def _class_defaults(maxclass):
    path = os.path.join(obj_info_folder, "m4l", f"{maxclass}.json")
    if not os.path.isfile(path):
        return {}
    with open(path, "r") as f:
        box = json.load(f).get("default", {}).get("box", {})
    valueof = box.get("saved_attribute_attributes", {}).get("valueof", {})
    return {k: v for k, v in valueof.items()
            if k not in ("parameter_longname", "parameter_shortname")}


def _num(val):
    if isinstance(val, list):
        val = val[0] if len(val) == 1 else val
    if isinstance(val, float) and val.is_integer():
        return int(val)
    return val


def is_parameter(box) -> bool:
    """Return True if a box is a Live parameter (live.* UI, or parameter_enable on)."""
    if box.get("parameter_enable") == 1:
        return True
    if box.get("parameter_enable") == 0:
        return False
    maxclass = box.get("maxclass", "")
    return maxclass.startswith(("live.", "mc.live.")) and "parameter_type" in _class_defaults(maxclass)


def param_info(box, node_path, in_presentation):
    """Describe one parameter box."""
    maxclass = box.get("maxclass", "")
    valueof = box.get("saved_attribute_attributes", {}).get("valueof", {})
    values = {**_class_defaults(maxclass), **valueof}

    ptype = values.get("parameter_type", FALLBACK_TYPES.get(maxclass, 0))
    type_name = TYPE_NAMES.get(ptype, f"type{ptype}")
    longname = values.get("parameter_longname") or box.get("varname") or maxclass
    unitstyle = values.get("parameter_unitstyle")
    unit = UNIT_NAMES.get(unitstyle, unitstyle) if unitstyle is not None else None

    info = {
        "longname": longname,
        "shortname": values.get("parameter_shortname", longname),
        "type": type_name,
        "object": box_word(box),
        "box_id": box.get("id", ""),
        "varname": box.get("varname", ""),
        "path": node_path,
        "presentation": bool(in_presentation),
    }

    if type_name == "enum":
        items = values.get("parameter_enum", [])
        info["enum"] = [str(i) for i in (items if isinstance(items, list) else [items])]
    elif type_name in ("float", "int"):
        info["min"] = _num(values.get("parameter_mmin", 0))
        info["max"] = _num(values.get("parameter_mmax", 127))

    if values.get("parameter_initial_enable") and "parameter_initial" in values:
        info["initial"] = _num(values["parameter_initial"])
    if unit is not None:
        info["unitstyle"] = unit
    if unit == "custom" and values.get("parameter_units"):
        info["units"] = values["parameter_units"]
    exponent = values.get("parameter_exponent")
    if exponent not in (None, 1, 1.0):
        info["exponent"] = _num(exponent)
    if values.get("parameter_steps"):
        info["steps"] = values["parameter_steps"]
    modmode = values.get("parameter_modmode")
    if modmode:
        info["modulation"] = MODMODES.get(modmode, str(modmode))
    if values.get("parameter_invisible"):
        info["visibility"] = {1: "hidden", 2: "stored only"}.get(values["parameter_invisible"],
                                                                   str(values["parameter_invisible"]))
    if values.get("parameter_info"):
        info["info"] = str(values["parameter_info"])
    if box.get("annotation"):
        info["annotation"] = str(box["annotation"])
    return info


def collect_params(nodes, presentation_ids):
    """
    Return parameters from all patchers.

    presentation_ids --> set of (node path, box id) shown in the device view
    """
    params = []
    for node in nodes:
        if node.is_gen:
            continue
        for box in node.boxes():
            if is_parameter(box):
                shown = (node.path, box.get("id")) in presentation_ids
                params.append(param_info(box, node.path, shown))
    return params


def format_param(p) -> str:
    """One-line human summary of a parameter's value range."""
    if p["type"] == "enum":
        items = p.get("enum", [])
        shown = ", ".join(items[:12]) + (f", ... (+{len(items) - 12})" if len(items) > 12 else "")
        rng = f"enum [{shown}]"
    elif p["type"] in ("float", "int"):
        rng = f"{p['type']} {p['min']}..{p['max']}"
    else:
        rng = p["type"]
    extras = []
    if "unitstyle" in p and p["unitstyle"] not in ("int", "float"):
        extras.append(p.get("units") or p["unitstyle"])
    if "exponent" in p:
        extras.append(f"exp {p['exponent']}")
    if "initial" in p:
        extras.append(f"init {p['initial']}")
    if "modulation" in p:
        extras.append(f"mod {p['modulation']}")
    if "visibility" in p:
        extras.append(p["visibility"])
    return rng + (" | " + ", ".join(str(e) for e in extras) if extras else "")
