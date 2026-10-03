"""
import_m4l.py — Build the bundled Max for Live (m4l) object database offline.

No running Max is needed. Reads from an Ableton Live install:
    - C74/docs/refpages/m4l-ref/*.maxref.xml --> args, attributes, docs (parsed with importobjs helpers)
    - real saved boxes (C74/object-prototypes/m4l/*.maxproto, C74/help/m4l/*.maxhelp,
      and every readable .amxd in the app) --> maxclass, inlets/outlets, outlet types, sizes,
      default Live parameter settings
    - C74/object-prototypes/m4l/live.*/*.maxproto --> named prototypes (e.g. live.dial "freq")

Writes data/OBJ_INFO/m4l/*.json and objects/m4l.py.

Usage:
    python -m maxpylang.import_m4l ["/Applications/Ableton Live 12 Suite.app"]
"""

import collections
import glob
import json
import os
import re
import sys
from pathlib import Path

from .amxd import load_amxd
from .m4l import LIVE_PARAM_ATTRIBS
from .tools.constants import obj_info_folder
from .importobjs import is_unlisted, get_objarg_info, get_objattrib_info, \
                        get_objinout_info, get_obj_doc_info, sanitize_py_name

DEFAULT_LIVE_APP = "/Applications/Ableton Live 12 Suite.app"
C74_SUBPATH = "Contents/App-Resources/Max/Max.app/Contents/Resources/C74"

#box keys that describe the object itself (not a particular instance)
CORE_BOX_KEYS = ('id', 'maxclass', 'numinlets', 'numoutlets', 'outlettype', 'patching_rect',
                 'presentation_rect', 'saved_attribute_attributes', 'varname', 'prototypename',
                 'parameter_enable', 'text')

#fresh enum defaults Max uses for menu-like objects (help files use custom enums)
ENUM_DEFAULTS = {'live.menu': {'parameter_enum': ['one', 'two', 'three'], 'parameter_mmax': 2},
                 'live.tab': {'parameter_enum': ['one', 'two', 'three'], 'parameter_mmax': 2}}

#sizes where the most common saved size is a poor default (live.comment: mostly "L"/"R" labels)
DEFAULT_SIZES = {'live.comment': [150.0, 18.0]}

NEWOBJ_HEIGHT = 22.0


def import_m4l(live_app=DEFAULT_LIVE_APP):
    """
    Regenerate data/OBJ_INFO/m4l/ and objects/m4l.py from a Live install.
    """

    c74 = os.path.join(live_app, C74_SUBPATH)
    ref_folder = os.path.join(c74, "docs", "refpages", "m4l-ref")
    if not os.path.exists(ref_folder):
        raise FileNotFoundError(f"m4l refpages not found at {ref_folder}")

    refs = sorted(glob.glob(os.path.join(ref_folder, "*.maxref.xml")))
    refs = [ref for ref in refs if not is_unlisted(ref)]
    names = [Path(Path(ref).stem).stem for ref in refs]

    boxes = harvest_boxes(live_app, c74, names)
    prototypes = get_prototypes(c74)

    args = get_objarg_info(refs, names)
    for name in names:
        for arg in args[name]['required'] + args[name]['optional']:
            arg['type'] = arg['type'] or ['any'] #e.g. live.param~ "parameter-name"
    attribs = get_objattrib_info(refs, names)
    inouts = get_objinout_info("m4l", names)
    docs = get_obj_doc_info(refs, names)

    info_folder = os.path.join(obj_info_folder, "m4l")
    os.makedirs(info_folder, exist_ok=True)
    for old in glob.glob(os.path.join(info_folder, "*.json")):
        os.remove(old)

    obj_infos = {}
    for ref, name in zip(refs, names):
        default = get_default_box(name, ref, boxes[name])
        obj_info = {'default': default,
                    'args': args[name],
                    'attribs': get_live_attribs(attribs[name], default, name in prototypes),
                    'in/out': inouts[name]}
        if name in prototypes:
            obj_info['prototypes'] = prototypes[name]
        obj_info['doc'] = trim_doc(docs[name])

        with open(os.path.join(info_folder, name + ".json"), 'w') as f:
            f.write(dumps_compact(obj_info) + "\n")
        obj_infos[name] = obj_info

    write_stubs(obj_infos)
    print(len(names), "m4l objects imported")

    return names


#************************************************************
#*************** HARVESTING REAL BOXES **********************
#************************************************************

def harvest_boxes(live_app, c74, names):
    """
    Collect every saved box of the given objects from prototypes, help files and devices.

    Returns {name: [box dicts]}, prototype boxes first.
    """

    files = sorted(glob.glob(os.path.join(c74, "object-prototypes", "m4l", "*", "*.maxproto")))
    files += sorted(glob.glob(os.path.join(c74, "help", "**", "*.maxhelp"), recursive=True))
    files += sorted(glob.glob(os.path.join(live_app, "**", "*.amxd"), recursive=True))

    found = collections.defaultdict(list)
    for path in files:
        patch = read_patch(path)
        if patch is None:
            continue
        for box in walk_boxes(patch):
            name = box_name(box)
            if name in names:
                found[name].append(box)

    return {name: found[name] for name in names}


def read_patch(path):
    """
    Read a .maxproto/.maxhelp (JSON) or .amxd file; None if unreadable (e.g. encrypted devices).
    """
    try:
        if path.endswith(".amxd"):
            return load_amxd(path)
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def walk_boxes(node):
    """
    Yield every box dict in a patcher JSON tree, including subpatchers.
    """
    if isinstance(node, dict):
        if isinstance(node.get('box'), dict):
            yield node['box']
        for val in node.values():
            yield from walk_boxes(val)
    elif isinstance(node, list):
        for val in node:
            yield from walk_boxes(val)


def box_name(box):
    """
    Object name of a box: maxclass for UI objects, first word of text for newobj.
    """
    if box.get('maxclass') == 'newobj':
        text = box.get('text')
        return text.split(" ")[0] if isinstance(text, str) else None
    return box.get('maxclass')


def most_common(values):
    return collections.Counter(values).most_common(1)[0][0]


#************************************************************
#*************** DEFAULT BOX ********************************
#************************************************************

def get_default_box(name, ref, boxes):
    """
    Build the default box for an object from its real saved boxes (or its maxref if none).
    """

    if boxes:
        bare = [b for b in boxes if b.get('maxclass') != 'newobj' or b.get('text') == name]
        sample = bare or boxes
        maxclass = most_common(b['maxclass'] for b in sample)
        xlets = most_common((b['numinlets'], b['numoutlets'], tuple(b.get('outlettype', [])))
                            for b in sample)
        size = DEFAULT_SIZES.get(name) or list(most_common(tuple(b['patching_rect'][2:4]) for b in sample))
    else:
        maxclass, xlets, size = get_ref_box(name, ref)

    box = {'id': 'obj-1', 'maxclass': maxclass, 'numinlets': xlets[0], 'numoutlets': xlets[1]}
    if xlets[1] > 0:
        box['outlettype'] = list(xlets[2]) or [""] * xlets[1]

    if maxclass == 'newobj':
        box['patching_rect'] = [100.0, 100.0, newobj_width(name), NEWOBJ_HEIGHT]
        box['text'] = name
        return {'box': box}

    box['patching_rect'] = [100.0, 100.0] + [float(round(x)) for x in size]

    #Live parameter defaults, from the most minimal saved instance
    params = [b for b in boxes if 'valueof' in b.get('saved_attribute_attributes', {})]
    if params:
        box['parameter_enable'] = most_common(b.get('parameter_enable', 0) for b in params)
        #prefer instances still carrying Max's auto name (name or name[n]), i.e. barely edited
        auto = re.compile(re.escape(name) + r"(\[\d+\])?$")
        fresh = [b for b in params
                 if auto.match(str(b['saved_attribute_attributes']['valueof'].get('parameter_longname', '')))]
        minimal = min(fresh or params, key=lambda b: len(b['saved_attribute_attributes']['valueof']))
        valueof = dict(minimal['saved_attribute_attributes']['valueof'])
        valueof.update(ENUM_DEFAULTS.get(name, {}))
        if 'parameter_modmode' in valueof:
            valueof['parameter_modmode'] = 0
        valueof['parameter_longname'] = name
        valueof['parameter_shortname'] = name
        box['saved_attribute_attributes'] = {'valueof': dict(sorted(valueof.items()))}
        box['varname'] = name
    elif any('parameter_enable' in b for b in boxes):
        box['parameter_enable'] = most_common(b['parameter_enable'] for b in boxes
                                              if 'parameter_enable' in b)

    return {'box': box}


def get_ref_box(name, ref):
    """
    Fallback default from the maxref: xlet counts/types and category-based maxclass.
    """
    import xml.etree.ElementTree as ET

    root = ET.parse(ref).getroot()
    ui = "UI" in root.attrib.get('category', '')
    ins = root.findall("./inletlist/inlet")
    outs = root.findall("./outletlist/outlet")
    types = ["signal" if "signal" in o.attrib.get('type', '') else "" for o in outs]

    return (name if ui else 'newobj'), (len(ins), len(outs), tuple(types)), [newobj_width(name), NEWOBJ_HEIGHT]


def newobj_width(name):
    """
    Width of a newobj box holding just the object name (12pt default font).
    """
    return float(round(7.0 * len(name) + 10.0))


def get_live_attribs(attribs, default, has_prototypes):
    """
    Add Live parameter attribute specs to parameter-aware objects, plus 'prototype' if available.
    """
    names = {a['name'] for a in attribs}
    box = default['box']

    if 'parameter_enable' in box and 'parameter_enable' not in names:
        attribs.append({'name': 'parameter_enable', 'type': 'int', 'size': '1'})
    if 'saved_attribute_attributes' in box:
        attribs += [dict(spec) for spec in LIVE_PARAM_ATTRIBS if spec['name'] not in names]
    if has_prototypes:
        attribs.append({'name': 'prototype', 'type': 'symbol', 'size': '1'})

    return attribs


def get_prototypes(c74):
    """
    Read named prototypes: {name: {prototype: {'box': extra attribs, 'valueof': params}}}.
    """
    prototypes = collections.defaultdict(dict)

    for path in sorted(glob.glob(os.path.join(c74, "object-prototypes", "m4l", "*", "*.maxproto"))):
        name = Path(path).parent.name
        patch = read_patch(path)
        if patch is None or not (name.startswith("live.") or name.startswith("mc.live.")):
            continue
        box = patch['boxes'][0]['box']
        proto = {'box': {k: v for k, v in sorted(box.items()) if k not in CORE_BOX_KEYS}}
        valueof = box.get('saved_attribute_attributes', {}).get('valueof')
        if valueof:
            proto['valueof'] = dict(sorted(valueof.items()))
        prototypes[name][Path(path).stem] = proto

    return dict(prototypes)


#************************************************************
#*************** OUTPUT *************************************
#************************************************************

def trim_doc(doc):
    """
    Keep docs compact: drop long method descriptions (method names and digests stay).
    """
    doc = dict(doc)
    if 'methods' in doc:
        doc['methods'] = [{k: v for k, v in m.items() if k != 'description'} for m in doc['methods']]
    return doc


def dumps_compact(obj, depth=0, max_depth=3):
    """
    JSON with one line per entry down to max_depth, compact below and for flat
    entries such as attribute specs (keeps files short).
    """
    if depth >= max_depth or is_flat(obj):
        return json.dumps(obj)

    pad = "  " * (depth + 1)
    if isinstance(obj, dict):
        items = [f"{pad}{json.dumps(k)}: {dumps_compact(v, depth + 1, max_depth)}" for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + "\n" + "  " * depth + "}"

    items = [pad + dumps_compact(v, depth + 1, max_depth) for v in obj]
    return "[\n" + ",\n".join(items) + "\n" + "  " * depth + "]"


def is_flat(obj):
    """
    True for scalars, empty containers, and containers holding only scalars or scalar lists.
    """
    if not isinstance(obj, (dict, list)) or not obj:
        return True
    vals = obj.values() if isinstance(obj, dict) else obj
    return all(not isinstance(v, (dict, list)) or
               (isinstance(v, list) and all(not isinstance(x, (dict, list)) for x in v)) for v in vals)


def write_stubs(obj_infos):
    """
    Write objects/m4l.py stubs (digest-only docstrings) and register them in objects/__init__.py.
    """
    objects_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "objects")
    names = {sanitize_py_name(name): name for name in obj_infos}

    lines = ['"""MaxObject stubs for m4l objects. Auto-generated by import_m4l()."""',
             "import os as _os", "import sys as _sys", "from maxpylang.maxobject import MaxObject", "",
             "__all__ = ["] + [f"    '{py}'," for py in sorted(names)] + ["]", "",
             "_devnull = open(_os.devnull, 'w')", "_old_stdout = _sys.stdout", "_sys.stdout = _devnull", ""]

    for py in sorted(names):
        digest = obj_infos[names[py]]['doc'].get('digest', names[py])
        digest = re.sub(r"\s+", " ", digest).replace('"""', "'''")
        lines += [f'"""{names[py]} - {digest}"""', f"{py} = MaxObject('{names[py]}')", ""]

    lines += ["_sys.stdout = _old_stdout", "_devnull.close()", "del _devnull, _old_stdout", ""]
    with open(os.path.join(objects_dir, "m4l.py"), 'w') as f:
        f.write("\n".join(lines))

    init_path = os.path.join(objects_dir, "__init__.py")
    with open(init_path, 'r') as f:
        init = f.read()
    if "from .m4l import" not in init:
        with open(init_path, 'a') as f:
            f.write("with warnings.catch_warnings():\n"
                    "    warnings.simplefilter(\"ignore\", UnknownObjectWarning)\n"
                    "    try:\n        from .m4l import *\n    except ImportError:\n        pass\n")

    return


if __name__ == "__main__":
    import_m4l(*sys.argv[1:])
