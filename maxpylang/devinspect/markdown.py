"""
devinspect.markdown

Render a DeviceDescription as concise Markdown for people and LLM agents.
Long sections are capped; the JSON output has everything.
"""

from collections import Counter

from .layout import BACKGROUND
from .params import format_param

MAX_VIEW = 60
MAX_PARAMS = 60
MAX_TREE = 60
MAX_FILES = 30
MAX_COMMENTS = 40
MAX_CODE_ENTRIES = 8
MAX_FEEDS = 6
CODE_LINES = 15
CODE_LANG = {"js": "js", "v8": "js", "jsui": "js", "v8ui": "js", "node.script": "js",
             "jstrigger": "js", "gen codebox": "c", "codebox": "c"}


def _size(n):
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _cut(text, n=120):
    return text if len(text) <= n else text[:n - 3] + "..."


def _capped(items, n=MAX_FEEDS):
    return "; ".join(items[:n]) + (f"; +{len(items) - n} more" if len(items) > n else "")


def _more(lines, shown, total, hint):
    if total > shown:
        lines.append(f"- ... {total - shown} more ({hint})")


def _header(d, out):
    out.append(f"# {d.name}")
    out.append("")
    facts = [f"**Type:** {d.device_type}",
             "frozen" if d.frozen else "not frozen",
             f"Max {d.max_version}" if d.max_version else "",
             _size(d.file_size)]
    if "devicewidth" in d.info:
        facts.append(f"devicewidth {d.info['devicewidth']:g}")
    out.append(" | ".join(f for f in facts if f))
    for key in ("description", "tags", "minimum_live_version", "latency", "is_mpe"):
        if d.info.get(key):
            out.append(f"- {key}: {_cut(str(d.info[key]), 200)}")
    if d.info.get("openinpresentation") != 1:
        out.append("- opens in patching view (no presentation)")
    out.append(f"- {len(d.params)} parameters, {len(d.hierarchy)} patchers, "
               f"{sum(d.object_counts.values())} objects, {len(d.code)} code sources")


def _view(d, out):
    items = [it for it in d.view if it["class"] not in BACKGROUND]
    out += ["", f"## Device view ({len(items)} visible items, top-to-bottom)"]
    params = {(p["path"], p["box_id"]) for p in d.params}
    for it in items[:MAX_VIEW]:
        mark = " [param]" if (it["path"], it["box_id"]) in params else ""
        cap = f" \"{_cut(it['caption'], 60)}\"" if it["caption"] else ""
        out.append(f"- ({it['x']:g}, {it['y']:g}) {it['class']}{cap}{mark}")
    _more(out, MAX_VIEW, len(items), "see --json")


def _params(d, out):
    out += ["", f"## Parameters ({len(d.params)})"]
    for p in d.params[:MAX_PARAMS]:
        name = p["longname"] + (f" (`{p['shortname']}`)" if p["shortname"] != p["longname"] else "")
        where = "" if p["path"] == "/" else f" in {p['path']}"
        hidden = "" if p["presentation"] else ", not in device view"
        out.append(f"- **{name}**: {p['object']}, {format_param(p)}{where}{hidden}")
        if p.get("feeds"):
            out.append(f"  - feeds: {_capped(p['feeds'])}")
        elif p.get("reaches"):
            out.append(f"  - reaches: {_capped(p['reaches'])}")
        if p.get("info"):
            out.append(f"  - info: {_cut(' '.join(p['info'].split()))}")
    _more(out, MAX_PARAMS, len(d.params), "run `maxpylang params` for all")


def _chain(label, io, out, kind):
    if not io["sources"] and not io["sinks"]:
        out.append(f"- {label}: none")
        return
    if io["connected"]:
        out.append(f"- {label} path: {' -> '.join(io['chain'])}")
        if len(io["on_path"]) > len(io["chain"]):
            shown = io["on_path"][:20]
            out.append(f"  - {len(io['on_path'])} {kind} objects on paths: {'; '.join(shown)}"
                       + (" ..." if len(io["on_path"]) > 20 else ""))
    elif not io["sources"]:
        out.append(f"- {label}: no input object; output via {', '.join(sorted(set(io['sinks'])))}")
    elif not io["sinks"]:
        out.append(f"- {label}: input via {', '.join(sorted(set(io['sources'])))}; no output object")
    else:
        out.append(f"- {label}: {', '.join(sorted(set(io['sources'])))} and "
                   f"{', '.join(sorted(set(io['sinks'])))} present, no cord path found")
    if io["from_sources"] and not io["sinks"]:
        out.append(f"  - from {', '.join(sorted(set(io['sources'])))} (nearest first): "
                   + "; ".join(io["from_sources"][:15]))
    if io["feeding_sinks"] and not io["connected"]:
        out.append(f"  - feeding {', '.join(sorted(set(io['sinks'])))} (nearest first): "
                   + "; ".join(io["feeding_sinks"][:15]))


def _flow(d, out):
    out += ["", "## Signal flow"]
    _chain("Audio", d.audio, out, "signal")
    _chain("MIDI", d.midi, out, "control")


def _tree(d, depth, out):
    nodes = [n for n in d.hierarchy if n["depth"] <= depth]
    out += ["", f"## Structure ({len(d.hierarchy)} patchers, showing depth <= {depth})"]
    for n in nodes[:MAX_TREE]:
        src = "" if n["source"] == "embedded" else f", {n['source']}"
        name = n["path"].rsplit("/", 1)[-1] or "(device)"
        out.append(f"{'  ' * n['depth']}- {name}: {n['kind']}, {n['num_boxes']} objects{src}")
    _more(out, MAX_TREE, len(nodes), "use --depth or --json")
    for u in d.unresolved[:10]:
        out.append(f"- unresolved {u['kind']} '{u['name']}' in {u['path']}")


def _objects(d, out):
    top = list(d.object_counts.items())[:40]
    out += ["", "## Objects used", ", ".join(f"{k} x{v}" for k, v in top)]


def _files(d, out):
    if not d.files:
        return
    out += ["", f"## Embedded files ({len(d.files)})"]
    for f in d.files[:MAX_FILES]:
        main = " (main patcher)" if f["main"] else ""
        out.append(f"- {f['name']} ({f['type'] or '?'}, {_size(f['size'])}){main}")
    if len(d.files) > MAX_FILES:
        rest = Counter(f["type"] or "?" for f in d.files[MAX_FILES:])
        out.append(f"- ... {len(d.files) - MAX_FILES} more: "
                   + ", ".join(f"{t} x{n}" for t, n in rest.most_common()))


def _comments(d, out):
    seen, texts = set(), []
    for c in d.comments:
        if not c["presentation"] and c["text"] not in seen:
            seen.add(c["text"])
            where = "" if c["path"] == "/" else f" ({c['path'].rsplit('/', 1)[-1]})"
            texts.append(f"- {_cut(c['text'])}{where}")
    if texts:
        out += ["", f"## Patcher comments ({len(texts)})"] + texts[:MAX_COMMENTS]
        _more(out, MAX_COMMENTS, len(texts), "see --json")


def _code(d, full, out):
    if not d.code:
        return
    out += ["", f"## Code ({len(d.code)} sources)"]
    entries = d.code if full else d.code[:MAX_CODE_ENTRIES]
    for c in entries:
        title = f"{c['object']} {c['file']}".strip()
        uses = f", used {len(c['used_in'])}x" if len(c["used_in"]) > 1 else ""
        out.append(f"### {title} ({c['origin']}, {c['lines']} lines{uses})")
        out.append(f"at {c['used_in'][0]}")
        if not c["text"]:
            continue
        lines = c["text"].split("\n")
        body = lines if full else lines[:CODE_LINES]
        out.append(f"```{CODE_LANG.get(c['object'], '')}")
        out += [ln.rstrip() for ln in body]
        if len(body) < len(lines):
            out.append(f"// ... {len(lines) - len(body)} more lines (use --full-code)")
        out.append("```")
    if not full and len(d.code) > MAX_CODE_ENTRIES:
        names = [c["file"] or c["object"] for c in d.code[MAX_CODE_ENTRIES:]]
        out.append(f"- ... {len(names)} more: {', '.join(names[:30])}")


def render(d, depth=3, full_code=False) -> str:
    out = []
    _header(d, out)
    _view(d, out)
    _params(d, out)
    _flow(d, out)
    _tree(d, depth, out)
    _objects(d, out)
    _files(d, out)
    _comments(d, out)
    _code(d, full_code, out)
    return "\n".join(out) + "\n"
