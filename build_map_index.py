"""Scan the Maps/ folder and write map_index.json."""
import os, json

ROOT     = os.path.dirname(__file__)
MAPS_DIR = os.path.join(ROOT, "Maps")
OUT      = os.path.join(ROOT, "map_index.json")


def _rel(path):
    return path.replace(ROOT + os.sep, "").replace(os.sep, "/")


def _scan_map(path, label):
    entries = os.listdir(path)
    pngs    = sorted(e for e in entries if e.lower().endswith(".png"))
    blends  = sorted(e for e in entries if e.lower().endswith(".blend"))
    preview = _rel(os.path.join(path, pngs[0]))   if pngs   else ""
    blend   = _rel(os.path.join(path, blends[0])) if blends else ""
    return {"label": label, "preview": preview, "blend": blend, "children": []}


def build():
    if not os.path.isdir(MAPS_DIR):
        print(f"Maps/ folder not found at {MAPS_DIR}")
        return

    items = []
    for name in sorted(os.listdir(MAPS_DIR)):
        full = os.path.join(MAPS_DIR, name)
        if os.path.isdir(full):
            items.append(_scan_map(full, name))

    index = {"Maps": items}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    print(f"map_index.json written — {len(items)} maps")


if __name__ == "__main__":
    build()
