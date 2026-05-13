import json
import random
import gradio as gr
from pathlib import Path
from PIL import Image, ImageColor, ImageDraw
from typing import List, Dict, Tuple

# --- CONFIGURATION ---
DEFAULT_IMG_SIZE = 512
DEFAULT_SOURCE_FOLDER = "monsterfirendss_512x512"
DEFAULT_BG_COLOR = "#000000"
LAYOUTS_FILE = Path("layouts.json")
EDITOR_SCALE = 12  
THUMBNAIL_SCALE = 3 

# --- CUSTOM CSS ---
CUSTOM_CSS = """
footer { display: none !important; }
#main-output {
    border: 2px solid #e5e7eb;
    border-radius: 12px;
    box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1);
    background-color: #f9fafb;
}
#pattern-gallery {
    min-height: 300px;
}
.grid-wrap {
    grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)) !important;
}
.selected {
    border-color: #10b981 !important;
    border-width: 3px !important;
    transform: scale(1.05);
    transition: all 0.2s;
}
.stat-box {
    background: #f3f4f6;
    padding: 10px;
    border-radius: 8px;
    font-family: monospace;
    font-size: 0.9em;
    color: #374151;
    border: 1px solid #e5e7eb;
    margin-top: 10px;
}
.warning-text {
    color: #dc2626;
    font-weight: bold;
}
"""

# --- BACKEND UTILS ---

def load_layouts() -> Dict:
    if not LAYOUTS_FILE.exists(): return {}
    with open(LAYOUTS_FILE, "r") as f: return json.load(f)

def get_source_images(src_folder: str) -> List[Path]:
    path = Path(src_folder)
    if not path.exists(): return []
    extensions = {'.jpg', '.jpeg', '.png', '.webp'}
    return [p for p in path.iterdir() if p.suffix.lower() in extensions]

def crop_and_resize(image: Image.Image, size: int) -> Image.Image:
    img_ratio = image.width / image.height
    if img_ratio > 1:
        new_width = int(img_ratio * image.height)
        offset = (image.width - new_width) // 2
        crop_box = (offset, 0, offset + new_width, image.height)
    else:
        new_height = int(image.width / img_ratio)
        offset = (image.height - new_height) // 2
        crop_box = (0, offset, image.width, offset + new_height)
    return image.crop(crop_box).resize((size, size), Image.Resampling.LANCZOS)

# --- RENDERERS ---

def render_editor_grid(pixels: list, cols: int, rows: int, scale=EDITOR_SCALE, bg_color="black", line_color="#333333"):
    w = cols * scale
    h = rows * scale
    img = Image.new("RGB", (w, h), bg_color)
    draw = ImageDraw.Draw(img)
    
    if scale > 2: 
        for x in range(0, w + 1, scale): draw.line([(x, 0), (x, h)], fill=line_color)
        for y in range(0, h + 1, scale): draw.line([(0, y), (w, y)], fill=line_color)
    
    pixel_set = set(pixels)
    inset = 1 if scale > 4 else 0
    
    for p_idx in pixel_set:
        idx = p_idx - 1
        r = idx // cols
        c = idx % cols
        x1, y1 = c * scale, r * scale
        x2, y2 = x1 + scale - 1, y1 + scale - 1
        draw.rectangle([x1 + inset, y1 + inset, x2 - inset, y2 - inset], fill="white")
        
    return img

def generate_thumbnails():
    layouts = load_layouts()
    gallery_items = []
    sorted_keys = sorted(list(layouts.keys()))
    
    for name in sorted_keys:
        data = layouts[name]
        cols = data.get("cols", 65)
        rows = data.get("rows", 65)
        pixels = data.get("pixels", [])
        img = render_editor_grid(pixels, cols, rows, scale=THUMBNAIL_SCALE, bg_color="#111", line_color="#111")
        gallery_items.append((img, name))
    return gallery_items, sorted_keys

# --- GENERATION ---

def generate_grid(job_name: str, source_folder: str, layout_name: str, 
                 tile_size: int, bg_hex: str, invert_layout: bool) -> str:
    
    if not layout_name: raise gr.Error("Please select a layout pattern below.")
    layouts = load_layouts()
    if layout_name not in layouts: raise gr.Error(f"Layout '{layout_name}' not found.")

    # FIX: Clamp minimum size to 32 logic side to prevent crashes
    safe_tile_size = max(32, int(tile_size))

    layout_data = layouts[layout_name]
    cols, rows = layout_data.get("cols", 65), layout_data.get("rows", 65)
    defined_pixels = set(layout_data.get("pixels", [])) 
    
    active_pixels = (set(range(1, (cols*rows)+1)) - defined_pixels) if invert_layout else defined_pixels

    try: bg_color = ImageColor.getrgb(bg_hex)
    except: bg_color = (0, 0, 0)

    canvas = Image.new("RGB", (cols * safe_tile_size, rows * safe_tile_size), bg_color)
    image_paths = get_source_images(source_folder)
    
    placeholder = not bool(image_paths)
    if not placeholder:
        random.shuffle(image_paths)
        img_iter = iter(image_paths)
    
    for pixel_idx in active_pixels:
        idx = pixel_idx - 1
        r, c = idx // cols, idx % cols
        x, y = c * safe_tile_size, r * safe_tile_size

        if placeholder:
             draw = ImageDraw.Draw(canvas)
             draw.rectangle([x, y, x+safe_tile_size, y+safe_tile_size], fill="#555")
        else:
            try:
                try: img_path = next(img_iter)
                except StopIteration:
                    img_iter = iter(image_paths)
                    img_path = next(img_iter)
                with Image.open(img_path) as img:
                    canvas.paste(crop_and_resize(img, safe_tile_size), (x, y))
            except: continue

    output_dir = Path("output") / job_name
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"{layout_name}_{random.randint(1000,9999)}.jpg"
    canvas.save(filename, quality=90)
    return str(filename)

# --- HELPER: STATS CALCULATION ---

def calculate_layout_stats(layout_name, tile_size, invert):
    if not layout_name: return ""
    layouts = load_layouts()
    if layout_name not in layouts: return ""
    
    data = layouts[layout_name]
    cols, rows = data.get("cols", 65), data.get("rows", 65)
    total_tiles = cols * rows
    
    active_count = len(data.get("pixels", []))
    if invert:
        active_count = total_tiles - active_count
    
    bg_count = total_tiles - active_count
    
    # Visual warning if too small
    size_warning = ""
    if tile_size < 32:
        size_warning = " <span class='warning-text'>(Too small! Will output at 32px)</span>"
    
    final_w = cols * int(tile_size)
    final_h = rows * int(tile_size)
    
    return f"""
    <div class='stat-box'>
        <strong>Output Size:</strong> {final_w}px x {final_h}px {size_warning} &nbsp;|&nbsp; 
        <strong>Active Images:</strong> {active_count} &nbsp;|&nbsp; 
        <strong>Background Tiles:</strong> {bg_count} &nbsp;|&nbsp;
        <strong>Grid:</strong> {cols}x{rows}
    </div>
    """

# --- FILE HELPERS ---

def save_layout_to_file(name, c, r, p):
    if not name: return "Error: Name required"
    layouts = load_layouts()
    layouts[name] = {"cols": int(c), "rows": int(r), "pixels": sorted(list(set(p)))}
    with open(LAYOUTS_FILE, "w") as f: json.dump(layouts, f, indent=2)
    return f"Saved '{name}'"

def delete_layout_from_file(name):
    layouts = load_layouts()
    if name in layouts:
        del layouts[name]
        with open(LAYOUTS_FILE, "w") as f: json.dump(layouts, f, indent=2)
        return f"Deleted '{name}'"
    return "Error"

def rename_layout_in_file(old, new):
    layouts = load_layouts()
    if old not in layouts or new in layouts: return "Error"
    layouts[new] = layouts.pop(old)
    with open(LAYOUTS_FILE, "w") as f: json.dump(layouts, f, indent=2)
    return f"Renamed to '{new}'"

# --- EVENT HANDLERS ---

def refresh_ui():
    gal, names = generate_thumbnails()
    return gal, gr.update(choices=names), gr.update(value=names), names

def select_layout_from_gallery(evt: gr.SelectData, names_list):
    if not names_list or evt.index >= len(names_list): return None
    return names_list[evt.index]

def ui_analyze(img, th, dim, dark):
    if img is None: return None, ""
    img_l = Image.fromarray(img).convert("L").resize((dim, dim))
    data = list(img_l.getdata())
    active = [i+1 for i, v in enumerate(data) if (v < th if dark else v > th)]
    prev = Image.new("RGB", (dim, dim), "black")
    pix = prev.load()
    for i in [(a-1) for a in active]: pix[i%dim, i//dim] = (255,255,255)
    return prev, json.dumps(active)

# --- EDITOR HANDLERS ---

def ui_load_edit(name):
    layouts = load_layouts()
    if name not in layouts: return None, [], 65, 65, "Error", ""
    d = layouts[name]
    return render_editor_grid(d["pixels"], d["cols"], d["rows"]), d["pixels"], d["cols"], d["rows"], f"Loaded {name}", name

def ui_click_edit(evt: gr.SelectData, p, c, r):
    if not c: return gr.update(), p
    x, y = evt.index
    idx = ((y // EDITOR_SCALE) * c) + (x // EDITOR_SCALE) + 1
    p_set = set(p)
    if idx in p_set: p_set.remove(idx)
    else: p_set.add(idx)
    new_p = sorted(list(p_set))
    return render_editor_grid(new_p, c, r), new_p

def ui_invert_edit(p, c, r):
    if not c: return gr.update(), p
    total_pixels = c * r
    all_pixels = set(range(1, total_pixels + 1))
    current_pixels = set(p)
    new_p = sorted(list(all_pixels - current_pixels))
    return render_editor_grid(new_p, c, r), new_p

# =============================================================================
# MAIN UI BLOCKS
# =============================================================================

init_gal, init_names = generate_thumbnails()

with gr.Blocks(theme=gr.themes.Soft(font=[gr.themes.GoogleFont("Inter")], primary_hue="zinc"), css=CUSTOM_CSS) as demo:
    
    state_layout_names = gr.State(value=init_names) 
    state_selected_layout = gr.State(value=init_names[0] if init_names else None)
    
    state_edit_p = gr.State([])
    state_edit_c = gr.State(65)
    state_edit_r = gr.State(65)

    with gr.Tabs():
        
        # --- TAB 1: GENERATE ---
        with gr.Tab("Generate"):
            with gr.Row():
                output_image = gr.Image(label="Result", type="filepath", height=550, elem_id="main-output", show_label=False, interactive=False)

            with gr.Row(variant="panel", equal_height=True):
                with gr.Column(scale=2):
                    source_folder = gr.Textbox(value=DEFAULT_SOURCE_FOLDER, label="Source Image Folder")
                    job_name = gr.Textbox(value="my_art", label="Job Name", visible=False)
                
                with gr.Column(scale=2):
                    # FIX: minimum=1 allows typing "1", "10", "100" without crashing
                    tile_size = gr.Slider(minimum=1, maximum=2048, value=128, label="Tile Size (px)")
                    
                with gr.Column(scale=1):
                    bg_color = gr.ColorPicker(value=DEFAULT_BG_COLOR, label="Background", container=True)

                with gr.Column(scale=1):
                     invert_chk = gr.Checkbox(value=False, label="Invert Output")
                     generate_btn = gr.Button("GENERATE", variant="primary", size="lg")

            # Stats Bar
            stats_bar = gr.HTML(label="Layout Info")

            gr.Markdown("### Select Pattern")
            layout_gallery = gr.Gallery(
                value=init_gal, 
                label="Patterns", 
                show_label=False, 
                columns=10, 
                rows=3,
                height="350px", 
                elem_id="pattern-gallery",
                allow_preview=False
            )

        # --- TAB 2: CREATE ---
        with gr.Tab("Create"):
            with gr.Row():
                with gr.Column():
                    c_img = gr.Image(label="Upload Shape")
                    c_th = gr.Slider(0, 255, 128, label="Threshold")
                    c_dim = gr.Slider(10, 200, 65, label="Grid Size")
                    c_dark = gr.Checkbox(label="Target Black Pixels")
                    c_preview_btn = gr.Button("Preview")
                with gr.Column():
                    c_out_img = gr.Image(label="Mask", image_mode="L")
                    c_json = gr.Textbox(visible=False)
            with gr.Row():
                c_name = gr.Textbox(label="Name")
                c_save = gr.Button("Save New Pattern", variant="primary")
            c_stat = gr.Textbox(label="Status")

        # --- TAB 3: EDIT ---
        with gr.Tab("Edit"):
            with gr.Row():
                with gr.Column(scale=1, variant="panel"):
                    gr.Markdown("**Manage**")
                    e_dd = gr.Dropdown(choices=init_names, label="Pattern")
                    e_load = gr.Button("Load")
                    with gr.Row():
                        e_rename_txt = gr.Textbox(placeholder="New name", show_label=False, scale=2)
                        e_rename_btn = gr.Button("Rename", scale=1)
                    e_del = gr.Button("Delete", variant="stop")
                    e_stat = gr.Textbox(label="Status")
                
                with gr.Column(scale=2):
                    e_canvas = gr.Image(label="Canvas", interactive=False)
                    e_invert_btn = gr.Button("Invert Active Pixels (Flip)", variant="secondary")
                
                with gr.Column(scale=1, variant="panel"):
                    gr.Markdown("**Save Changes**")
                    e_save_name = gr.Textbox(label="Save As...")
                    e_save = gr.Button("Save", variant="primary")

    # =========================================
    # EVENT BINDINGS
    # =========================================
    
    # 1. Main Tab
    def update_stats(name, size, inv):
        return calculate_layout_stats(name, size, inv)

    layout_gallery.select(select_layout_from_gallery, [state_layout_names], [state_selected_layout]) \
                  .then(update_stats, [state_selected_layout, tile_size, invert_chk], stats_bar)
    
    tile_size.change(update_stats, [state_selected_layout, tile_size, invert_chk], stats_bar)
    invert_chk.change(update_stats, [state_selected_layout, tile_size, invert_chk], stats_bar)
    
    demo.load(update_stats, [state_selected_layout, tile_size, invert_chk], stats_bar)

    generate_btn.click(generate_grid, [job_name, source_folder, state_selected_layout, tile_size, bg_color, invert_chk], [output_image])

    # 2. Create Tab
    c_preview_btn.click(ui_analyze, [c_img, c_th, c_dim, c_dark], [c_out_img, c_json])
    
    def create_save_wrap(n, d, j):
        try:
            msg = save_layout_to_file(n, d, d, json.loads(j))
            g, dd_upd, st_upd, names = refresh_ui()
            return msg, g, dd_upd, st_upd
        except Exception as e: return str(e), gr.update(), gr.update(), gr.update()

    c_save.click(create_save_wrap, [c_name, c_dim, c_json], [c_stat, layout_gallery, e_dd, state_layout_names])

    # 3. Edit Tab
    e_load.click(ui_load_edit, e_dd, [e_canvas, state_edit_p, state_edit_c, state_edit_r, e_stat, e_save_name])
    e_canvas.select(ui_click_edit, [state_edit_p, state_edit_c, state_edit_r], [e_canvas, state_edit_p])
    e_invert_btn.click(ui_invert_edit, [state_edit_p, state_edit_c, state_edit_r], [e_canvas, state_edit_p])

    def edit_save_wrap(n, c, r, p):
        msg = save_layout_to_file(n, c, r, p)
        g, dd_upd, st_upd, names = refresh_ui()
        return msg, g, dd_upd, st_upd
    
    e_save.click(edit_save_wrap, [e_save_name, state_edit_c, state_edit_r, state_edit_p], [e_stat, layout_gallery, e_dd, state_layout_names])

    def del_wrap(n):
        msg = delete_layout_from_file(n)
        g, dd_upd, st_upd, names = refresh_ui()
        return msg, g, dd_upd, st_upd
    e_del.click(del_wrap, e_dd, [e_stat, layout_gallery, e_dd, state_layout_names])

    def ren_wrap(o, n):
        msg = rename_layout_in_file(o, n)
        g, dd_upd, st_upd, names = refresh_ui()
        return msg, g, dd_upd, st_upd
    e_rename_btn.click(ren_wrap, [e_dd, e_rename_txt], [e_stat, layout_gallery, e_dd, state_layout_names])

if __name__ == "__main__":
    demo.launch(inbrowser=True)