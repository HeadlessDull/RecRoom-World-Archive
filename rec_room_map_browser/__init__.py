bl_info = {
    "name": "RRO Map & NPC Browser (BETA)",
    "author": "Headless Dull",
    "version": (1, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > RR Archive",
    "description": "Browse and append Rec Room maps and NPCs",
    "category": "Object",
}


import bpy, bpy.utils.previews
import os, json, tempfile, threading, hashlib, shutil
import urllib.request, urllib.error, urllib.parse


# Config (Hellooooo!!!!)


REPO              = "HeadlessDull/RecRoom-World-Archive"
DISCORD_URL       = "https://discord.gg/UauGKxtuWJ"
AVATAR_ARCHIVE_URL = "https://github.com/HeadlessDull/RecRoom-Avatar-Archive"
RAW_BASE     = f"https://raw.githubusercontent.com/{REPO}/main"
MAP_INDEX_URL = f"{RAW_BASE}/map_index.json"
NPC_INDEX_URL = f"{RAW_BASE}/npc_index.json"


# Custom icons

_CUSTOM_ICONS = None

def _load_custom_icons():
    global _CUSTOM_ICONS
    _CUSTOM_ICONS = bpy.utils.previews.new()
    icon_path = os.path.join(os.path.dirname(__file__), "RRIcon.png")
    if os.path.isfile(icon_path):
        _CUSTOM_ICONS.load("RR_ICON", icon_path, "IMAGE")

def _unload_custom_icons():
    global _CUSTOM_ICONS
    if _CUSTOM_ICONS:
        bpy.utils.previews.remove(_CUSTOM_ICONS)
        _CUSTOM_ICONS = None

def _rr_icon():
    if _CUSTOM_ICONS and "RR_ICON" in _CUSTOM_ICONS:
        return _CUSTOM_ICONS["RR_ICON"].icon_id
    return 0


# State


MAP_CACHE    = None
MAP_ERROR    = ""
MAP_LOADING  = False

NPC_CACHE    = None
NPC_ERROR    = ""
NPC_LOADING  = False

PREVIEW_COLL = None
_PREVIEW_ICONS = {}
_FETCHING      = set()
_DOWNLOAD_SEMAPHORE = threading.Semaphore(5)


# Helpers


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "RROMapBrowser"})
    with urllib.request.urlopen(req, timeout=30) as r: return r.read()

def _cache_dir(subdir=""):
    d = os.path.join(os.path.dirname(__file__), ".cache", subdir) if subdir else \
        os.path.join(os.path.dirname(__file__), ".cache")
    os.makedirs(d, exist_ok=True)
    return d

def _preview_local(subdir, repo_path):
    d = _cache_dir(subdir)
    return os.path.join(d, hashlib.md5(repo_path.encode()).hexdigest() + ".png")

def _redraw_all():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()

def _load_icon(local):
    global PREVIEW_COLL
    if PREVIEW_COLL is None: PREVIEW_COLL = bpy.utils.previews.new()
    if local in PREVIEW_COLL:
        ico = PREVIEW_COLL[local].icon_id
        if ico != 0: return ico
        try: del PREVIEW_COLL[local]
        except: pass
    try:
        PREVIEW_COLL.load(local, local, "IMAGE")
        return PREVIEW_COLL[local].icon_id
    except:
        return 0

def _watch_and_load(repo_path, local):
    import time
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if os.path.isfile(local):
            def _do_load(l=local, p=repo_path):
                ico = _load_icon(l)
                _PREVIEW_ICONS[l] = ico if ico != 0 else -1
                _redraw_all()
                return None
            bpy.app.timers.register(_do_load, first_interval=0.05)
            return
        time.sleep(0.1)
    _PREVIEW_ICONS[local] = -1

def _load_preview(subdir, repo_path):
    if not repo_path: return 0
    local = _preview_local(subdir, repo_path)
    if local in _PREVIEW_ICONS:
        ico = _PREVIEW_ICONS[local]
        return ico if ico > 0 else 0
    if os.path.isfile(local):
        ico = _load_icon(local)
        _PREVIEW_ICONS[local] = ico if ico != 0 else 0
        return ico
    if repo_path not in _FETCHING:
        _FETCHING.add(repo_path)
        def _fetch_and_watch(rp=repo_path, lp=local):
            with _DOWNLOAD_SEMAPHORE:
                try:
                    data = _fetch(f"{RAW_BASE}/{urllib.parse.quote(rp, safe='/').replace('(','%28').replace(')','%29')}")
                    open(lp, "wb").write(data)
                except Exception as e:
                    print(f"Preview download failed: {rp} — {e}")
            _watch_and_load(rp, lp)
        threading.Thread(target=_fetch_and_watch, daemon=True).start()
    return 0

def load_map_preview(repo_path):  return _load_preview("maps", repo_path)
def load_npc_preview(repo_path):  return _load_preview("npc",  repo_path)

def _reset_previews():
    global PREVIEW_COLL, _DOWNLOAD_SEMAPHORE
    _PREVIEW_ICONS.clear()
    _FETCHING.clear()
    _DOWNLOAD_SEMAPHORE = threading.Semaphore(5)
    if PREVIEW_COLL:
        bpy.utils.previews.remove(PREVIEW_COLL)
        PREVIEW_COLL = None

def _wipe_cache():
    cache_root = os.path.join(os.path.dirname(__file__), ".cache")
    if os.path.isdir(cache_root):
        shutil.rmtree(cache_root, ignore_errors=True)
    os.makedirs(cache_root, exist_ok=True)

def _remove_col(col):
    for c in list(col.children): _remove_col(c)
    for c in list(bpy.data.collections):
        if col.name in {x.name for x in c.children}: c.children.unlink(col)
    for s in bpy.data.scenes:
        if col.name in {x.name for x in s.collection.children}: s.collection.children.unlink(col)
    bpy.data.collections.remove(col)

def _safe_key(label):
    return "".join(c if c.isalnum() else "_" for c in label).lower()

def _open_set(s):
    return set(x for x in s.split(",") if x)

def _toggle_open(scene, prop_name, key):
    s = _open_set(getattr(scene, prop_name))
    s.discard(key) if key in s else s.add(key)
    setattr(scene, prop_name, ",".join(s))


# Index loading


def _load_map_bg():
    global MAP_CACHE, MAP_ERROR, MAP_LOADING
    try:
        MAP_CACHE = json.loads(_fetch(MAP_INDEX_URL))
    except urllib.error.HTTPError as e:
        MAP_ERROR = "map_index.json not found." if e.code == 404 else f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        MAP_ERROR = str(e)
    finally:
        MAP_LOADING = False
        bpy.app.timers.register(lambda: _redraw_all() or None, first_interval=0.05)

def fetch_maps():
    global MAP_LOADING
    if MAP_CACHE or MAP_LOADING: return
    MAP_LOADING = True
    threading.Thread(target=_load_map_bg, daemon=True).start()

def _load_npc_bg():
    global NPC_CACHE, NPC_ERROR, NPC_LOADING
    try:
        NPC_CACHE = json.loads(_fetch(NPC_INDEX_URL))
    except urllib.error.HTTPError as e:
        NPC_ERROR = "npc_index.json not found." if e.code == 404 else f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        NPC_ERROR = str(e)
    finally:
        NPC_LOADING = False
        bpy.app.timers.register(lambda: _redraw_all() or None, first_interval=0.05)

def fetch_npcs():
    global NPC_LOADING
    if NPC_CACHE or NPC_LOADING: return
    NPC_LOADING = True
    threading.Thread(target=_load_npc_bg, daemon=True).start()


# Data helpers


def all_maps():
    if not MAP_CACHE: return []
    return MAP_CACHE.get("Maps", [])

def all_npcs():
    if not NPC_CACHE: return []
    return NPC_CACHE.get("NPCs", [])

def _search(items, q):
    q = q.lower()
    out = []
    for item in items:
        children = item.get("children") or []
        if children:
            matched = [c for c in children if q in c.get("label", "").lower()]
            out.append({**item, "children": matched} if matched
                       else item if q in item.get("label", "").lower() else None)
        elif item.get("blend") and q in item.get("label", "").lower():
            out.append(item)
    return [x for x in out if x]

def search_maps(q):
    return _search(all_maps(), q)

def search_npcs(q):
    return _search(all_npcs(), q)

def flatten(items):
    return [i for item in items
            for i in (flatten(item["children"]) if item.get("children") else [item] if item.get("blend") else [])]


# Preferences


class RROMapPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    def draw(self, context):
        layout = self.layout
        layout.label(text="Links:", icon="URL")
        row = layout.row(align=True)
        op = row.operator("rromap.open_url", text="Discord", icon="COMMUNITY")
        op.url = DISCORD_URL
        op = row.operator("rromap.open_url", text="Avatar Archive", icon="WORLD")
        op.url = AVATAR_ARCHIVE_URL


# Operators


class RROMAP_OT_open_url(bpy.types.Operator):
    bl_idname   = "rromap.open_url"; bl_label = "Open URL"
    bl_description = "Open link in your browser"; bl_options = {"REGISTER"}
    url: bpy.props.StringProperty()
    def execute(self, context):
        import webbrowser
        webbrowser.open(self.url); return {"FINISHED"}


class RROMAP_OT_fetch_maps(bpy.types.Operator):
    bl_idname = "rromap.fetch_maps"; bl_label = "Refresh Maps"
    bl_description = "Re-download map_index.json"; bl_options = {"REGISTER"}
    def execute(self, context):
        global MAP_CACHE, MAP_ERROR
        MAP_CACHE = None; MAP_ERROR = ""
        fetch_maps()
        self.report({"INFO"}, "Fetching maps…"); return {"FINISHED"}


class RROMAP_OT_fetch_npcs(bpy.types.Operator):
    bl_idname = "rromap.fetch_npcs"; bl_label = "Refresh NPCs"
    bl_description = "Re-download npc_index.json"; bl_options = {"REGISTER"}
    def execute(self, context):
        global NPC_CACHE, NPC_ERROR
        NPC_CACHE = None; NPC_ERROR = ""
        fetch_npcs()
        self.report({"INFO"}, "Fetching NPCs…"); return {"FINISHED"}


class RROMAP_OT_clear_cache(bpy.types.Operator):
    bl_idname = "rromap.clear_cache"; bl_label = "Clear Preview Cache"
    bl_description = "Delete all cached preview images"; bl_options = {"REGISTER"}
    def execute(self, context):
        _reset_previews()
        _wipe_cache()
        self.report({"INFO"}, "Cache cleared."); return {"FINISHED"}


class RROMAP_OT_clear_map_search(bpy.types.Operator):
    bl_idname = "rromap.clear_map_search"; bl_label = "Clear"; bl_options = {"REGISTER"}
    def execute(self, context):
        context.scene.rromap_map_search = ""; return {"FINISHED"}


class RROMAP_OT_clear_npc_search(bpy.types.Operator):
    bl_idname = "rromap.clear_npc_search"; bl_label = "Clear"; bl_options = {"REGISTER"}
    def execute(self, context):
        context.scene.rromap_npc_search = ""; return {"FINISHED"}


class RROMAP_OT_toggle_map_group(bpy.types.Operator):
    bl_idname = "rromap.toggle_map_group"; bl_label = "Toggle"; bl_options = {"REGISTER"}
    group_key: bpy.props.StringProperty()
    def execute(self, context):
        _toggle_open(context.scene, "rromap_open_map_groups", self.group_key)
        return {"FINISHED"}


class RROMAP_OT_toggle_npc_group(bpy.types.Operator):
    bl_idname = "rromap.toggle_npc_group"; bl_label = "Toggle"; bl_options = {"REGISTER"}
    group_key: bpy.props.StringProperty()
    def execute(self, context):
        _toggle_open(context.scene, "rromap_open_npc_groups", self.group_key)
        return {"FINISHED"}


class RROMAP_OT_append_map(bpy.types.Operator):
    bl_idname      = "rromap.append_map"
    bl_label       = "Append Map"
    bl_description = "Download .blend, append the scene and switch into it"
    bl_options     = {"REGISTER"}
    blend_path: bpy.props.StringProperty()
    item_label: bpy.props.StringProperty()

    def execute(self, context):
        if not self.blend_path:
            self.report({"ERROR"}, "Nothing selected."); return {"CANCELLED"}
        try:
            data = _fetch(f"{RAW_BASE}/{urllib.parse.quote(self.blend_path, safe='/')}")
        except Exception as e:
            self.report({"ERROR"}, f"Download failed: {e}"); return {"CANCELLED"}
        tmp = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".blend", delete=False) as f:
                f.write(data); tmp = f.name

            with bpy.data.libraries.load(tmp, link=False) as (src, dst):
                dst.scenes = list(src.scenes)

            appended = [s for s in dst.scenes if s is not None]
            if not appended:
                self.report({"WARNING"}, "No scenes found in blend file."); return {"CANCELLED"}

            bpy.context.window.scene = appended[0]

        except Exception as e:
            self.report({"ERROR"}, f"Append failed: {e}"); return {"CANCELLED"}
        finally:
            try: os.remove(tmp)
            except: pass

        bpy.ops.ed.undo_push(message=f"Append map: {self.item_label}")
        self.report({"INFO"}, f"Loaded map: {appended[0].name}")
        return {"FINISHED"}


class RROMAP_OT_append_npc(bpy.types.Operator):
    bl_idname      = "rromap.append_npc"
    bl_label       = "Append NPC"
    bl_description = "Download and append NPC to scene"
    bl_options     = {"REGISTER"}
    blend_path: bpy.props.StringProperty()
    item_label: bpy.props.StringProperty()

    def execute(self, context):
        if not self.blend_path:
            self.report({"ERROR"}, "Nothing selected."); return {"CANCELLED"}
        try:
            data = _fetch(f"{RAW_BASE}/{urllib.parse.quote(self.blend_path, safe='/')}")
        except Exception as e:
            self.report({"ERROR"}, f"Download failed: {e}"); return {"CANCELLED"}
        tmp = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".blend", delete=False) as f:
                f.write(data); tmp = f.name
            with bpy.data.libraries.load(tmp, link=False) as (src, dst):
                dst.collections = list(src.collections)
            npcs_col = bpy.data.collections.get("NPCs")
            if not npcs_col:
                npcs_col = bpy.data.collections.new("NPCs")
                context.scene.collection.children.link(npcs_col)
            moved = []
            for col in dst.collections:
                if not col: continue
                for obj in list(col.objects):
                    if obj.name not in {o.name for o in npcs_col.objects}:
                        npcs_col.objects.link(obj)
                    moved.append(obj.name)
                _remove_col(col)
        finally:
            try: os.remove(tmp)
            except: pass
        if not moved:
            self.report({"WARNING"}, "No objects found."); return {"CANCELLED"}
        bpy.ops.ed.undo_push(message=f"Append NPC: {self.item_label}")
        self.report({"INFO"}, f"Added {len(moved)} NPC object(s)")
        return {"FINISHED"}


# Panel


class RROMAP_PT_main(bpy.types.Panel):
    bl_label      = "RRO Map & NPC Browser"
    bl_idname     = "RROMAP_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category   = "RR Archive"
    bl_order      = 10

    def draw_header(self, context):
        ico = _rr_icon()
        if ico:
            self.layout.label(text="", icon_value=ico)

    def draw(self, context):
        layout = self.layout
        scene  = context.scene

        mbox = layout.box()
        mrow = mbox.row(align=True)
        mrow.prop(scene, "rromap_maps_open", text="Map Browser",
                  icon="TRIA_DOWN" if scene.rromap_maps_open else "TRIA_RIGHT",
                  emboss=False)
        if scene.rromap_maps_open:
            ibox = mbox.box()
            irow = ibox.row(align=True)
            if MAP_LOADING:
                irow.label(text="Loading…", icon="TIME")
            elif MAP_ERROR:
                irow.alert = True; irow.label(text=MAP_ERROR, icon="ERROR"); irow.alert = False
                ibox.operator("rromap.fetch_maps", text="Retry", icon="FILE_REFRESH")
            elif MAP_CACHE is None:
                irow.label(text="Not loaded", icon="QUESTION")
                ibox.operator("rromap.fetch_maps", text="Load from GitHub", icon="URL")
                fetch_maps()
            else:
                irow.label(text="Maps loaded ✓", icon="CHECKMARK")
                irow.operator("rromap.fetch_maps", text="", icon="FILE_REFRESH")
                irow.operator("rromap.clear_cache", text="", icon="TRASH")
                mbox.separator()
                q = scene.rromap_map_search.strip()
                srow = mbox.row(align=True)
                srow.prop(scene, "rromap_map_search", text="", icon="VIEWZOOM")
                if q: srow.operator("rromap.clear_map_search", text="", icon="X")
                mbox.separator()
                items = search_maps(q) if q else all_maps()
                if q and not items:
                    mbox.label(text=f'No results for "{q}"', icon="INFO")
                else:
                    open_grps = _open_set(scene.rromap_open_map_groups)
                    sel = scene.rromap_selected_map_blend
                    self._category_grid(mbox, items, open_grps, sel,
                                        "rromap.append_map", load_map_preview,
                                        "rromap.toggle_map_group")

        layout.separator()

        nbox = layout.box()
        nrow = nbox.row(align=True)
        nrow.prop(scene, "rromap_npcs_open", text="NPC Browser",
                  icon="TRIA_DOWN" if scene.rromap_npcs_open else "TRIA_RIGHT",
                  emboss=False)
        if scene.rromap_npcs_open:
            ibox = nbox.box()
            irow = ibox.row(align=True)
            if NPC_LOADING:
                irow.label(text="Loading…", icon="TIME")
            elif NPC_ERROR:
                irow.alert = True; irow.label(text=NPC_ERROR, icon="ERROR"); irow.alert = False
                ibox.operator("rromap.fetch_npcs", text="Retry", icon="FILE_REFRESH")
            elif NPC_CACHE is None:
                irow.label(text="Not loaded", icon="QUESTION")
                ibox.operator("rromap.fetch_npcs", text="Load from GitHub", icon="URL")
                fetch_npcs()
            else:
                irow.label(text="NPCs loaded ✓", icon="CHECKMARK")
                irow.operator("rromap.fetch_npcs", text="", icon="FILE_REFRESH")
                nbox.separator()
                q = scene.rromap_npc_search.strip()
                srow = nbox.row(align=True)
                srow.prop(scene, "rromap_npc_search", text="", icon="VIEWZOOM")
                if q: srow.operator("rromap.clear_npc_search", text="", icon="X")
                nbox.separator()
                items = search_npcs(q) if q else all_npcs()
                if q and not items:
                    nbox.label(text=f'No results for "{q}"', icon="INFO")
                else:
                    open_grps = _open_set(scene.rromap_open_npc_groups)
                    sel = scene.rromap_selected_npc_blend
                    self._category_grid(nbox, items, open_grps, sel,
                                        "rromap.append_npc", load_npc_preview,
                                        "rromap.toggle_npc_group")

    def _category_grid(self, layout, items, open_grps, sel, op_id, load_fn, toggle_op):
        grid = layout.grid_flow(row_major=True, columns=0,
                                even_columns=True, even_rows=True, align=True)
        for item in items:
            children = item.get("children") or []
            if children:
                key = _safe_key(item["label"]); is_open = key in open_grps
                ico = load_fn(item.get("preview")) if item.get("preview") else 0
                cell = grid.column(align=True)
                if ico:
                    cell.template_icon(icon_value=ico, scale=6.0)
                else:
                    row = cell.row(); row.scale_y = 6.0
                    row.label(text="", icon="TRIA_DOWN" if is_open else "TRIA_RIGHT")
                btn = cell.row(align=True)
                op = btn.operator(toggle_op, text=item["label"],
                                  icon="TRIA_DOWN" if is_open else "TRIA_RIGHT",
                                  emboss=True)
                op.group_key = key
                if is_open:
                    for child in children:
                        blend = child.get("blend", "")
                        if not blend: continue
                        lbl = child["label"]
                        ico_c = load_fn(child.get("preview")) if child.get("preview") else 0
                        self._grid_tile(grid, blend, lbl, ico_c, blend == sel,
                                        op_id, use_box=True)
            else:
                blend = item.get("blend", "")
                if not blend: continue
                lbl = item["label"]
                ico = load_fn(item.get("preview")) if item.get("preview") else 0
                self._grid_tile(grid, blend, lbl, ico, blend == sel, op_id)

    def _grid_tile(self, grid, blend, label, ico, is_sel, op_id, use_box=False):
        outer = grid.column(align=True)
        cell = outer.box().column(align=True) if use_box else outer
        if ico:
            cell.template_icon(icon_value=ico, scale=6.0)
        else:
            row = cell.row(); row.scale_y = 6.0
            row.label(text="", icon="IMAGE_DATA")
        btn = cell.row(align=True)
        btn.alert = is_sel
        op = btn.operator(op_id, text=label, emboss=True, depress=is_sel)
        op.blend_path = blend
        op.item_label = label


# Registration


classes = [
    RROMapPreferences,
    RROMAP_OT_open_url,
    RROMAP_OT_fetch_maps,
    RROMAP_OT_fetch_npcs,
    RROMAP_OT_clear_cache,
    RROMAP_OT_clear_map_search,
    RROMAP_OT_clear_npc_search,
    RROMAP_OT_toggle_map_group,
    RROMAP_OT_toggle_npc_group,
    RROMAP_OT_append_map,
    RROMAP_OT_append_npc,
    RROMAP_PT_main,
]


def register():
    _load_custom_icons()
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.rromap_maps_open           = bpy.props.BoolProperty(name="Maps",  default=False)
    bpy.types.Scene.rromap_map_search          = bpy.props.StringProperty(name="Search", default="")
    bpy.types.Scene.rromap_selected_map_blend  = bpy.props.StringProperty(default="")
    bpy.types.Scene.rromap_open_map_groups     = bpy.props.StringProperty(default="")
    bpy.types.Scene.rromap_npcs_open           = bpy.props.BoolProperty(name="NPCs",  default=False)
    bpy.types.Scene.rromap_npc_search          = bpy.props.StringProperty(name="Search", default="")
    bpy.types.Scene.rromap_selected_npc_blend  = bpy.props.StringProperty(default="")
    bpy.types.Scene.rromap_open_npc_groups     = bpy.props.StringProperty(default="")


def unregister():
    global MAP_CACHE, MAP_ERROR, MAP_LOADING
    global NPC_CACHE, NPC_ERROR, NPC_LOADING
    MAP_CACHE = None; MAP_ERROR = ""; MAP_LOADING = False
    NPC_CACHE = None; NPC_ERROR = ""; NPC_LOADING = False
    _reset_previews()
    _unload_custom_icons()
    for cls in reversed(classes):
        try: bpy.utils.unregister_class(cls)
        except: pass
    for a in ["rromap_maps_open", "rromap_map_search", "rromap_selected_map_blend",
              "rromap_open_map_groups",
              "rromap_npcs_open", "rromap_npc_search", "rromap_selected_npc_blend",
              "rromap_open_npc_groups"]:
        try: delattr(bpy.types.Scene, a)
        except: pass


if __name__ == "__main__": register()
