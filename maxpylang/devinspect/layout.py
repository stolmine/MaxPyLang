"""
devinspect.layout

What the user sees: the device view (presentation, including the contents of
bpatchers placed in it) and the comments written in every patcher.

    device_view() --> visible boxes in device coordinates, ordered top-to-bottom
    collect_comments() --> comment texts with their patcher path
"""

from .tree import box_text, box_word

BACKGROUND = frozenset({"panel", "live.line", "fpic", "live.colors", "swatch"})


def _rect(box, key):
    rect = box.get(key) or box.get("patching_rect") or [0, 0, 0, 0]
    return [float(v) for v in (list(rect) + [0, 0, 0, 0])[:4]]


def box_caption(box) -> str:
    """Text a box shows or names: comment text, parameter name, button text, ..."""
    maxclass = box.get("maxclass", "")
    if maxclass in ("comment", "live.comment", "message", "newobj", "textbutton"):
        return " ".join(box_text(box).split())
    valueof = box.get("saved_attribute_attributes", {}).get("valueof", {})
    name = valueof.get("parameter_shortname") or valueof.get("parameter_longname")
    if maxclass == "live.text" and box.get("text"):
        name = f"{name} [{box['text']}]" if name else box["text"]
    if maxclass == "fpic" and box.get("pic"):
        name = str(box["pic"])
    if maxclass == "bpatcher":
        name = box.get("name") or box.get("varname")
    return name or box.get("varname", "")


def _visible(box, use_presentation):
    if box.get("hidden") == 1:
        return False
    if use_presentation:
        return box.get("presentation") == 1
    return box.get("maxclass") not in ("newobj", "inlet", "outlet")


def device_view(nodes):
    """Return visible items of the device view, top-to-bottom then left-to-right."""
    by_parent = {(n.parent, n.box_id): n for n in nodes if n.parent}
    root = nodes[0]
    items = []
    _collect(root, by_parent, root.patcher.get("openinpresentation") == 1, 0.0, 0.0,
             None, items, 0)
    items.sort(key=lambda it: (round(it["y"] / 8.0), it["x"]))
    return items


def _collect(node, by_parent, use_presentation, ox, oy, clip, items, depth):
    if depth > 16 or node.is_gen:
        return
    key = "presentation_rect" if use_presentation else "patching_rect"
    for box in node.boxes():
        if not _visible(box, use_presentation):
            continue
        x, y, w, h = _rect(box, key)
        if clip is not None:
            cx, cy, cw, ch = clip
            if x >= cx + cw or y >= cy + ch or x + w <= cx or y + h <= cy:
                continue
        item = {"x": round(ox + x, 1), "y": round(oy + y, 1), "w": w, "h": h,
                "class": box_word(box), "caption": box_caption(box),
                "path": node.path, "box_id": box.get("id", "")}
        items.append(item)
        if box.get("maxclass") == "bpatcher":
            child = by_parent.get((node.path, box.get("id")))
            if child is not None:
                off = box.get("offset", [0.0, 0.0]) or [0.0, 0.0]
                child_pres = child.patcher.get("openinpresentation") == 1
                _collect(child, by_parent, child_pres, ox + x + off[0], oy + y + off[1],
                         (-off[0], -off[1], w, h), items, depth + 1)


def presentation_ids(view_items):
    return {(it["path"], it["box_id"]) for it in view_items}


def collect_comments(nodes, shown):
    """Return every comment as {path, text, presentation}; shown = presentation ids."""
    out = []
    for node in nodes:
        if node.is_gen:
            continue
        for box in node.boxes():
            if box.get("maxclass") not in ("comment", "live.comment"):
                continue
            text = " ".join(box_text(box).split())
            if text:
                out.append({"path": node.path, "text": text,
                            "presentation": (node.path, box.get("id")) in shown})
    return out
