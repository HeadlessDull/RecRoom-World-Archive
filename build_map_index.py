"""Scan the Maps/ folder and write map_index.json.

Each entry directly under Maps/ has its own preview image, and is either:
  - a leaf:  the folder also contains a .blend directly  -> single item
  - a group: the folder instead contains subfolders, each of which is
             itself a leaf (its own image + .blend)       -> rendered as a
             collapsible group of variants in the addon
"""
import os, json

ROOT     = os.path.dirname(__file__)
MAPS_DIR = os.path.join(ROOT, "Maps")
OUT      = os.path.join(ROOT, "map_index.json")


def _rel(path):
    return path.replace(ROOT + os.sep, "").replace(os.sep, "/")


def _first(entries, suffix):
    matches = sorted(e for e in entries if e.lower().endswith(suffix))
    return matches[0] if matches else ""


def _scan_leaf(path, label):
    entries = os.listdir(path)
    png     = _first(entries, ".png")
    blend   = _first(entries, ".blend")
    return {
        "label":    label,
        "preview":  _rel(os.path.join(path, png))   if png   else "",
        "blend":    _rel(os.path.join(path, blend)) if blend else "",
        "children": [],
    }


def _scan_entry(path, label):
    entries = os.listdir(path)
    subdirs = sorted(e for e in entries if os.path.isdir(os.path.join(path, e)))

    if subdirs:
        png = _first(entries, ".png")
        return {
            "label":    label,
            "preview":  _rel(os.path.join(path, png)) if png else "",
            "blend":    "",
            "children": [_scan_leaf(os.path.join(path, sub), sub) for sub in subdirs],
        }

    return _scan_leaf(path, label)


def build():
    if not os.path.isdir(MAPS_DIR):
        print(f"Maps/ folder not found at {MAPS_DIR}")
        return

    items = []
    for name in sorted(os.listdir(MAPS_DIR)):
        full = os.path.join(MAPS_DIR, name)
        if os.path.isdir(full):
            items.append(_scan_entry(full, name))

    index = {"Maps": items}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    group_count = sum(1 for i in items if i["children"])
    print(f"map_index.json written — {len(items)} top-level entries ({group_count} grouped)")


if __name__ == "__main__":
    build()
