"""
m4l.py — Max for Live helpers.

Live parameter constants (unit styles, parameter types), the parameter attribute
specs that live.* UI objects accept, and device-level patcher settings.

Live parameter properties are passed to MaxObject like any attribute and are stored
in the box's saved_attribute_attributes.valueof::

    dial = mp.MaxObject("live.dial", parameter_longname="Cutoff",
                        parameter_mmin=20., parameter_mmax=20000.,
                        parameter_initial=1000., parameter_unitstyle="hertz",
                        parameter_exponent=3.)
"""

import copy

from .amxd import DEVICE_TYPES

#parameter_unitstyle values, as shown in the Max inspector
UNITSTYLES = {
    "int": 0,
    "float": 1,
    "time": 2,
    "hertz": 3,
    "decibel": 4,
    "percent": 5,
    "pan": 6,
    "semitones": 7,
    "midi": 8,
    "custom": 9,
    "native": 10,
}

#parameter_type values
PARAM_TYPES = {
    "float": 0,
    "int": 1,
    "enum": 2,
    "blob": 3,
}

#parameter properties stored in saved_attribute_attributes.valueof
#(parameter_enable and parameter_mappable stay top-level box attributes)
LIVE_PARAM_ATTRIBS = [
    {"name": "parameter_longname", "type": "symbol", "size": "1"},
    {"name": "parameter_shortname", "type": "symbol", "size": "1"},
    {"name": "parameter_type", "type": "atom", "size": "1"},
    {"name": "parameter_mmin", "type": "float", "size": "1"},
    {"name": "parameter_mmax", "type": "float", "size": "1"},
    {"name": "parameter_initial", "type": "atom", "size": "1"},
    {"name": "parameter_initial_enable", "type": "int", "size": "1"},
    {"name": "parameter_unitstyle", "type": "atom", "size": "1"},
    {"name": "parameter_units", "type": "symbol", "size": "1"},
    {"name": "parameter_exponent", "type": "float", "size": "1"},
    {"name": "parameter_steps", "type": "int", "size": "1"},
    {"name": "parameter_enum", "type": "atom", "size": "1"},
    {"name": "parameter_enum_icons", "type": "atom", "size": "1"},
    {"name": "parameter_modmode", "type": "int", "size": "1"},
    {"name": "parameter_modmin", "type": "float", "size": "1"},
    {"name": "parameter_modmax", "type": "float", "size": "1"},
    {"name": "parameter_invisible", "type": "int", "size": "1"},
    {"name": "parameter_info", "type": "symbol", "size": "1"},
    {"name": "parameter_annotation_name", "type": "symbol", "size": "1"},
    {"name": "parameter_linknames", "type": "int", "size": "1"},
    {"name": "parameter_order", "type": "int", "size": "1"},
    {"name": "parameter_speedlim", "type": "float", "size": "1"},
    {"name": "parameter_defer", "type": "int", "size": "1"},
    {"name": "parameter_button_mode", "type": "symbol", "size": "1"},
]

LIVE_PARAM_NAMES = frozenset(spec["name"] for spec in LIVE_PARAM_ATTRIBS)

#patcher keys that set_device() accepts
DEVICE_KEYS = ("openinpresentation", "devicewidth", "latency", "openrect", "title",
               "description", "digest", "tags", "is_mpe", "minimum_live_version",
               "minimum_max_version", "platform_compatibility")

#device keys present in every Live 12 template device (Misc/Max Devices/*.amxd)
DEVICE_DEFAULTS = {
    "openrect": [0.0, 0.0, 0.0, 169.0],
    "latency": 0,
    "project": {
        "version": 1,
        "creationdate": 3590052493,
        "modificationdate": 3590052493,
        "viewrect": [0.0, 0.0, 300.0, 500.0],
        "autoorganize": 1,
        "hideprojectwindow": 1,
        "showdependencies": 1,
        "autolocalize": 0,
        "contents": {"patchers": {}},
        "layout": {},
        "searchpath": {},
        "detailsvisible": 0,
        "amxdtype": 0,
        "readonly": 0,
        "devpathtype": 0,
        "devpath": ".",
        "sortmode": 0,
        "viewmode": 0,
    },
}


def amxdtype(device_type):
    """
    Return the project.amxdtype integer for a device type (its ampf code read big-endian).
    """
    if device_type not in DEVICE_TYPES:
        raise ValueError(f"Unknown device_type {device_type!r}. "
                         f"Choose from: {', '.join(DEVICE_TYPES)}")
    return int.from_bytes(DEVICE_TYPES[device_type], "big")


def device_json(patcher_json, device_type):
    """
    Fill in the patcher keys Live writes for a device, without overriding values already set.

    project.amxdtype is always set to match device_type.
    """
    patcher = patcher_json["patcher"]
    for key, val in DEVICE_DEFAULTS.items():
        if key not in patcher:
            patcher[key] = copy.deepcopy(val)
    patcher["project"]["amxdtype"] = amxdtype(device_type)

    return patcher_json


def normalize_live_params(params):
    """
    Convert user-facing parameter values to the form Max saves in valueof.

    Unit style / type names map to ints, parameter_initial becomes a list,
    and giving parameter_initial turns on parameter_initial_enable.
    """
    params = dict(params)

    for key, table in (("parameter_unitstyle", UNITSTYLES), ("parameter_type", PARAM_TYPES)):
        val = params.get(key)
        if isinstance(val, str):
            if val not in table:
                raise ValueError(f"Unknown {key} {val!r}. Choose from: {', '.join(table)}")
            params[key] = table[val]

    if "parameter_initial" in params:
        if not isinstance(params["parameter_initial"], list):
            params["parameter_initial"] = [params["parameter_initial"]]
        params.setdefault("parameter_initial_enable", 1)

    return params
