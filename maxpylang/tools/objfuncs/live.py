"""
tools.objfuncs.live

Methods for Max for Live (live.*) objects.

    is_live_obj() --> check if the object comes from the m4l object database
    is_live_ui() --> check if the object is a live.* UI object (own maxclass, no box text)

    add_live_params() --> route Live parameter attributes into saved_attribute_attributes.valueof
    update_live_text() --> box text handling for live.* UI objects
"""

import copy
from pathlib import Path

from maxpylang.m4l import LIVE_PARAM_NAMES, normalize_live_params


def is_live_obj(self):
    """
    Return True if the object's reference file is in the m4l object database.
    """

    if self._ref_file in (None, "abstraction", "not_found"):
        return False

    return Path(self._ref_file).parent.name == "m4l"


def is_live_ui(self):
    """
    Return True for live.* UI objects, which use their own maxclass instead of newobj.
    """

    return self.is_live_obj() and self._dict['box']['maxclass'] != 'newobj'


def add_live_params(self, extra_attribs):
    """
    Helper function for adding extra attributes.

    Moves Live parameter attributes (parameter_longname, parameter_mmin, ...) into
    saved_attribute_attributes.valueof and applies a named prototype, if given.
    Returns the remaining (top-level) attributes.

    Giving parameters turns on parameter_enable; the longname also becomes the
    shortname and varname unless those are given.
    """

    params = {key: val for key, val in extra_attribs.items() if key in LIVE_PARAM_NAMES}
    prototype = extra_attribs.get('prototype')
    remaining = {key: val for key, val in extra_attribs.items()
                 if key not in params and key != 'prototype'}

    if not params and prototype is None:
        return remaining

    box = self._dict['box']

    params = normalize_live_params(params)
    if 'parameter_longname' in params and 'parameter_shortname' not in params:
        params['parameter_shortname'] = params['parameter_longname']

    #apply prototype first, so given attributes override it
    if prototype is not None:
        prototypes = self.get_info().get('prototypes', {})
        if prototype not in prototypes:
            raise ValueError(f"{self._name}: unknown prototype {prototype!r}. "
                             f"Choose from: {', '.join(sorted(prototypes))}")
        box.update(copy.deepcopy(prototypes[prototype].get('box', {})))
        params = {**prototypes[prototype].get('valueof', {}), **params}

    if not params:
        return remaining

    valueof = box.setdefault('saved_attribute_attributes', {}).setdefault('valueof', {})
    valueof.update(params)
    box['parameter_enable'] = 1

    if 'parameter_longname' in params and 'varname' not in extra_attribs:
        box['varname'] = params['parameter_longname']

    return remaining


def update_live_text(self):
    """
    Helper function for updating text.

    live.* UI objects have no in-box text: in-text attributes (@attr val) become box
    attributes, and for live.comment the arguments become the comment text.
    """

    box = self._dict['box']

    attribs = {}
    for attrib, vals in self._text_attribs.items():
        if attrib in ('text', 'texton'):
            attribs[attrib] = " ".join(vals)
        else:
            typed = self.get_typed_args(vals)
            attribs[attrib] = typed[0] if len(typed) == 1 else typed
    self._text_attribs = {}

    for attrib, val in self.add_live_params(attribs).items():
        box[attrib] = val

    if self._name == 'live.comment' and len(self._args) != 0:
        box['text'] = " ".join(str(x) for x in self._args)

    return
