"""
devinspect.trace

Parameter tracing: the first processing objects a control's value reaches.

The walk follows cords outlet by outlet (FlowGraph.ports). Each step carries the
known leading atoms of the message ('fx mix_tone' after two prepends) and whether
it is a signal, so routing objects only pass the branch the value can take.

Transparent (no hop cost, the walk continues through them):
    inlet/outlet, in/out, s/r, send~/receive~, forward, value/pv, defer, gate, append,
    number boxes, toggle, umenu; message boxes and prepend (set the leading atoms),
    funnel (prefixes the inlet index), t/trigger (per outlet; bang outlets and
    b/bangbang are not followed, the value stops there), route/routepass/select
    (matching outlet or the reject outlet when the leading atom is known, all outlets
    otherwise). 'set ...' messages stop at anything but routing objects; a signal
    only enters in~, a message only enters in.
Pass-through with a hop (control math, pack/pak, scale, expr, line, zl, ...): every
    other known control object; the leading atoms become unknown
Smoothers and converters (line~, slide~, sig~, mstosamps~, ...) entered at their left
    inlet: passed, reported only when nothing further downstream of them is found;
    entered at another inlet (ramp or slide time) they are targets
Targets (the walk stops): any other signal object, gen~/rnbo~, plugout~, live.gain~
Endpoints (reported under "reaches"): js/jsui/v8, live.object/remote~, MIDI outs,
    unresolved abstractions and externals unknown to maxpylang; the walk stops
    except at makenote, coll, dict and pattr
"""

import json
import os
from collections import deque
from functools import lru_cache

from maxpylang.tools.constants import obj_info_folder

from .tree import box_text, positional_args

ROUTERS = frozenset({"route", "routepass", "select", "sel"})
KEEP_SELECTOR = frozenset({"s", "send", "forward", "s~", "send~", "r", "receive", "r~",
                           "receive~", "pv", "value", "v", "inlet", "outlet", "in", "in~",
                           "out", "out~", "fftin~", "fftout~", "mc.in~", "mc.out~", "defer",
                           "deferlow", "gate", "append"})
NUMBER_UI = frozenset({"flonum", "number", "toggle", "umenu"})
FREE = ROUTERS | KEEP_SELECTOR | NUMBER_UI | frozenset({"t", "trigger", "prepend", "message",
                                                      "funnel"})
SMOOTHERS = frozenset({"sig~", "line~", "curve~", "slide~", "rampsmooth~", "mc.sig~",
                       "mc.line~", "number~", "mstosamps~", "sampstoms~"})
ENDPOINTS = frozenset({"midiout", "noteout", "ctlout", "bendout", "pgmout", "touchout",
                       "polytouchout", "live.object", "live.remote~", "live.observer",
                       "live.path", "js", "v8", "node.script", "buffer~", "poly~", "mc.poly~",
                       "thispatcher", "live.miditool.out", "jsui", "v8ui", "makenote",
                       "coll", "dict", "pattr"})
NOT_DSP = frozenset({"thispoly~", "mc.thispoly~"})
PASS_ENDPOINTS = frozenset({"makenote", "coll", "dict", "pattr"})
EXTRA_KNOWN = frozenset({"p", "patcher", "s", "r", "i", "f", "v", "pfft~", "del", "Uzi",
                         "list.slice", "list.ecils", "s~", "r~", "mc.s~", "mc.r~", "v8",
                         "node.script", "live.adsr~", "mc.plugin~", "mc.plugout~"})
CONVERTERS = frozenset({"mstosamps~", "sampstoms~"})
SIGNAL_PORTS = frozenset({"in~", "fftin~", "mc.in~"})
MESSAGE_PORTS = frozenset({"in"})
SET_PASSES = KEEP_SELECTOR | ROUTERS | frozenset({"t", "trigger", "prepend", "funnel"})
INLET_AWARE = ROUTERS | SMOOTHERS | frozenset({"prepend", "funnel"})
MAX_TARGETS = 12


@lru_cache(maxsize=1)
def known_objects():
    """Names of every Max/MSP/Jitter/M4L object maxpylang knows, plus aliases."""
    names = set(EXTRA_KNOWN)
    for sub in ("max", "msp", "jit", "m4l"):
        folder = os.path.join(obj_info_folder, sub)
        if os.path.isdir(folder):
            names.update(f[:-5] for f in os.listdir(folder) if f.endswith(".json"))
    with open(os.path.join(obj_info_folder, "obj_aliases.json")) as f:
        names.update(json.load(f))
    return frozenset(names)


def _is_number(token):
    try:
        float(token)
    except ValueError:
        return False
    return True


def _literal(token):
    """A message atom as route compares it (numbers by value), or None for $ arguments."""
    if not token or token.startswith(("$", "#")):
        return None
    return float(token) if _is_number(token) else token


def _head(tokens):
    """Known leading atoms of a message ('fx mix_tone $1' -> ('fx', 'mix_tone'))."""
    out = []
    for tok in tokens:
        atom = _literal(tok)
        if atom is None:
            break
        out.append(atom)
    return tuple(out)


def _known(heads):
    heads = frozenset(heads)
    return None if not heads or () in heads else heads


def message_selectors(text):
    """Return the known leading atoms of each message a message box sends, or None."""
    return _known(_head(msg.split()) for msg in text.split(";", 1)[0].split(","))


def _router(word, args, inlet, sel, outlet):
    """Return (passes, selector out) for a route/select box."""
    if inlet != 0 or sel is None or not args:
        return True, None
    out = set()
    args = [_literal(a) for a in args]
    for head in sel:
        index = args.index(head[0]) if head[0] in args else len(args)
        if index != outlet:
            continue
        if index == len(args) or word == "routepass":
            out.add(head)
        elif word in ("select", "sel"):
            out.add(("bang",))
        else:
            out.add(head[1:])
    return bool(out), _known(out)


def _trigger(args, sel, outlet):
    arg = args[outlet] if outlet < len(args) else "l"
    if arg in ("l", "a", "s", "list", "anything", "symbol"):
        return sel
    return _known({_head([arg])}) if arg not in ("f", "i", "float", "int") else None


def emit(word, box, inlet, sel, outlet):
    """Return (passes, selector) of the message leaving `outlet` of a box hit by `sel`."""
    if box.get("maxclass") == "message":
        return True, message_selectors(box_text(box))
    if word in ROUTERS:
        return _router(word, positional_args(box), inlet, sel, outlet)
    if word in ("t", "trigger"):
        args = positional_args(box)
        if outlet < len(args) and args[outlet] in ("b", "bang"):
            return False, None
        return True, _trigger(args, sel, outlet)
    if word in ("b", "bangbang"):
        return False, None
    if word == "funnel":
        args = positional_args(box)
        offset = int(args[1]) if len(args) > 1 and args[1].lstrip("-").isdigit() else 0
        prefix = (float(inlet + offset),)
        return True, frozenset(prefix + h for h in sel) if sel else frozenset({prefix})
    if word == "prepend":
        prefix = _head(positional_args(box)) if inlet == 0 else ()
        if not prefix:
            return True, None
        return True, frozenset(prefix + h for h in sel) if sel else frozenset({prefix})
    if word in KEEP_SELECTOR:
        return True, sel
    return True, None


def _kind(word, box, signal, inlet):
    if word in SMOOTHERS and inlet == 0:
        return "smoother"
    if signal and word not in KEEP_SELECTOR and word not in NOT_DSP:
        return "target"
    if word in ENDPOINTS or (box.get("maxclass") == "newobj" and not _is_number(word)
                             and word not in known_objects()):
        return "pass_endpoint" if word in PASS_ENDPOINTS else "endpoint"
    return "control"


def _signal_out(word, outlet, signal, sig):
    """Whether what leaves `outlet` is a signal (sig: what came in)."""
    if word in KEEP_SELECTOR:
        return sig
    if word in CONVERTERS:
        return outlet == 0
    return signal


def _blocked(nword, sel, sig):
    """True when a message cannot pass into the next object."""
    if nword in SIGNAL_PORTS:
        return not sig
    if nword in MESSAGE_PORTS:
        return sig
    return bool(sel) and all(h[0] == "set" for h in sel) and nword not in SET_PASSES


def trace(graph, start, max_hops=6, limit=MAX_TARGETS):
    """Return (targets, endpoints or else dead ends) downstream of a control, nearest first."""
    from .flow import is_signal
    first = (start, 0, None, is_signal(graph.word(start)))
    dist, parent = {first: 0}, {}
    queue = deque([first])
    targets, endpoints, leaves, smoothers, satisfied = {}, {}, {}, {}, set()

    def found(table, gid, d, state):
        table[gid] = min(d, table.get(gid, d))
        while state in parent:
            state = parent[state]
            if state[0] in satisfied:
                break
            satisfied.add(state[0])

    while queue:
        state = queue.popleft()
        cur, inlet, sel, sig = state
        box = graph.boxes[cur][1] if cur in graph.boxes else {}
        word = graph.word(cur)
        signal = is_signal(word)
        for outlet, nxt, nin in graph.ports.get(cur, ()):
            passes, out_sel = emit(word, box, inlet, sel, outlet) if cur != start else (True, None)
            out_sig = _signal_out(word, outlet, signal, sig)
            nword = graph.word(nxt)
            if not passes or _blocked(nword, out_sel, out_sig):
                continue
            free = nword in FREE
            d = dist[state] + (0 if free else 1)
            nstate = (nxt, nin if nword in INLET_AWARE else 0, out_sel, out_sig)
            if d > max_hops or dist.get(nstate, d + 1) <= d:
                continue
            dist[nstate] = d
            parent.setdefault(nstate, state)
            kind = _kind(nword, graph.boxes[nxt][1] if nxt in graph.boxes else {},
                         is_signal(nword), nin)
            if kind == "target":
                found(targets, nxt, d, nstate)
                continue
            if kind in ("endpoint", "pass_endpoint"):
                found(endpoints, nxt, d, nstate)
                if kind == "endpoint":
                    continue
            elif kind == "smoother":
                smoothers[nxt] = min(d, smoothers.get(nxt, d))
            elif nxt not in graph.ports:
                leaves[nxt] = min(d, leaves.get(nxt, d))
            if free:
                queue.appendleft(nstate)
            else:
                queue.append(nstate)

    for gid, d in smoothers.items():
        if gid not in satisfied:
            targets[gid] = min(d, targets.get(gid, d))
    return _nearest(targets, limit), _nearest(endpoints or leaves, limit)


def _nearest(table, limit):
    return sorted(table, key=lambda g: (table[g], g))[:limit]
