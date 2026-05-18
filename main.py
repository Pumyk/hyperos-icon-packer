"""
HyperOS Icon Packer
A step-by-step app to convert any icon pack into a HyperOS-compatible theme.
"""

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.progressbar import ProgressBar
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.togglebutton import ToggleButton
from kivy.core.window import Window
from kivy.utils import get_color_from_hex
from kivy.clock import Clock
from kivy.metrics import dp

import os
import re
import shutil
import struct
import threading
import zipfile
import zlib
from pathlib import Path

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    from android.permissions import request_permissions, Permission
    from android.storage import primary_external_storage_path
    ANDROID = True
except ImportError:
    ANDROID = False

# ── Colours ──────────────────────────────────────────────────────────────────
BG       = get_color_from_hex("#0D0D0D")
CARD     = get_color_from_hex("#1A1A2E")
ACCENT   = get_color_from_hex("#7C3AED")
ACCENT2  = get_color_from_hex("#A855F7")
SUCCESS  = get_color_from_hex("#22C55E")
WARN     = get_color_from_hex("#F59E0B")
ERROR    = get_color_from_hex("#EF4444")
WHITE    = get_color_from_hex("#F1F5F9")
GREY     = get_color_from_hex("#94A3B8")

Window.clearcolor = BG


# ── Helpers ──────────────────────────────────────────────────────────────────
def get_downloads():
    if ANDROID:
        base = primary_external_storage_path()
        return os.path.join(base, "Download")
    return str(Path.home() / "Downloads")

def card_layout(orientation="vertical", padding=dp(16), spacing=dp(12)):
    layout = BoxLayout(orientation=orientation, padding=padding, spacing=spacing,
                       size_hint_y=None)
    layout.bind(minimum_height=layout.setter("height"))
    return layout

def styled_label(text, font_size=dp(14), color=WHITE, bold=False, halign="left"):
    lbl = Label(text=text, font_size=font_size, color=color, bold=bold,
                halign=halign, size_hint_y=None, height=dp(30),
                text_size=(None, None))
    lbl.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
    return lbl

def accent_button(text, callback, color=None):
    btn = Button(text=text, size_hint_y=None, height=dp(48),
                 background_normal="", background_color=color or ACCENT,
                 color=WHITE, font_size=dp(15), bold=True)
    btn.bind(on_release=callback)
    return btn

def add_srgb_sbit(png_path):
    with open(png_path, "rb") as f:
        data = f.read()
    srgb_data = b'\x00'
    srgb_crc  = zlib.crc32(b'sRGB' + srgb_data) & 0xffffffff
    srgb_chunk = struct.pack('>I', 1) + b'sRGB' + srgb_data + struct.pack('>I', srgb_crc)
    sbit_data  = bytes([8, 8, 8, 8])
    sbit_crc   = zlib.crc32(b'sBIT' + sbit_data) & 0xffffffff
    sbit_chunk = struct.pack('>I', 4) + b'sBIT' + sbit_data + struct.pack('>I', sbit_crc)
    new_data   = data[:33] + srgb_chunk + sbit_chunk + data[33:]
    with open(png_path, "wb") as f:
        f.write(new_data)


# ── State (shared across screens) ────────────────────────────────────────────
class State:
    apk_path       = ""
    work_dir       = ""
    copy_icon_dir  = ""
    rename_dir     = ""
    resize_dir     = ""
    final_dir      = ""
    appfilter_path = ""
    icon_count     = 0
    do_resize      = True
    resize_px      = 266
    output_zip     = ""
    log_lines      = []

STATE = State()


# ══════════════════════════════════════════════════════════════════════════════
# Screen 1 – Welcome
# ══════════════════════════════════════════════════════════════════════════════
class WelcomeScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(16))

        root.add_widget(Label(size_hint_y=0.15))

        # Logo / title area
        root.add_widget(Label(
            text="⚙  HyperOS\nIcon Packer",
            font_size=dp(32), bold=True, color=ACCENT2,
            halign="center", size_hint_y=0.25
        ))

        root.add_widget(styled_label(
            "Convert any Android icon pack into a\nHyperOS-compatible theme zip.",
            font_size=dp(15), color=GREY, halign="center"
        ))

        root.add_widget(Label(size_hint_y=0.1))

        steps = [
            "1.  Select icon pack APK",
            "2.  Auto-extract & parse icons",
            "3.  Rename to package names",
            "4.  Resize (optional)",
            "5.  Build Final.zip",
        ]
        for s in steps:
            root.add_widget(styled_label(s, color=WHITE, font_size=dp(14)))

        root.add_widget(Label(size_hint_y=0.15))
        btn = Button(text="Get Started  →", size_hint=(0.7, None), height=dp(52),
                     pos_hint={"center_x": 0.5},
                     background_normal="", background_color=ACCENT,
                     color=WHITE, font_size=dp(16), bold=True)
        btn.bind(on_release=self.go_next)
        root.add_widget(btn)
        root.add_widget(Label(size_hint_y=0.05))

        self.add_widget(root)

    def go_next(self, *_):
        if ANDROID:
            request_permissions([Permission.READ_EXTERNAL_STORAGE,
                                  Permission.WRITE_EXTERNAL_STORAGE])
        self.manager.transition = SlideTransition(direction="left")
        self.manager.current = "pick_apk"


# ══════════════════════════════════════════════════════════════════════════════
# Screen 2 – Pick APK
# ══════════════════════════════════════════════════════════════════════════════
class PickApkScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.selected_path = ""

        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        root.add_widget(styled_label("Step 1 — Select Icon Pack APK",
                                     font_size=dp(18), bold=True, color=ACCENT2))
        root.add_widget(styled_label(
            "Browse to your icon pack APK file.\n"
            "Tip: use ADB  →  adb pull <apk path>  to get it onto your device first.",
            color=GREY, font_size=dp(13)
        ))

        start = get_downloads()
        self.fc = FileChooserListView(path=start, filters=["*.apk"],
                                      size_hint_y=1)
        self.fc.bind(selection=self.on_select)
        root.add_widget(self.fc)

        self.path_label = styled_label("No file selected", color=GREY,
                                       font_size=dp(12))
        root.add_widget(self.path_label)

        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        back = Button(text="← Back", size_hint_x=0.3,
                      background_normal="", background_color=CARD, color=WHITE)
        back.bind(on_release=self.go_back)
        self.next_btn = Button(text="Next →", size_hint_x=0.7,
                               background_normal="", background_color=ACCENT,
                               color=WHITE, bold=True)
        self.next_btn.bind(on_release=self.go_next)
        self.next_btn.disabled = True
        row.add_widget(back)
        row.add_widget(self.next_btn)
        root.add_widget(row)

        self.add_widget(root)

    def on_select(self, chooser, selection):
        if selection:
            self.selected_path = selection[0]
            self.path_label.text = self.selected_path
            self.next_btn.disabled = False

    def go_back(self, *_):
        self.manager.transition = SlideTransition(direction="right")
        self.manager.current = "welcome"

    def go_next(self, *_):
        STATE.apk_path = self.selected_path
        self.manager.transition = SlideTransition(direction="left")
        self.manager.current = "extract"


# ══════════════════════════════════════════════════════════════════════════════
# Screen 3 – Extract
# ══════════════════════════════════════════════════════════════════════════════
class ExtractScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.root_layout = BoxLayout(orientation="vertical",
                                     padding=dp(16), spacing=dp(12))

        self.root_layout.add_widget(styled_label(
            "Step 2 — Extracting APK", font_size=dp(18), bold=True, color=ACCENT2))

        self.status_label = styled_label("Ready to extract...", color=GREY)
        self.root_layout.add_widget(self.status_label)

        self.progress = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(20))
        self.root_layout.add_widget(self.progress)

        sv = ScrollView(size_hint_y=1)
        self.log_label = Label(text="", color=GREY, font_size=dp(11),
                               size_hint_y=None, halign="left",
                               text_size=(Window.width - dp(32), None))
        self.log_label.bind(texture_size=self.log_label.setter("size"))
        sv.add_widget(self.log_label)
        self.root_layout.add_widget(sv)

        self.next_btn = Button(text="Next →", size_hint_y=None, height=dp(48),
                               background_normal="", background_color=ACCENT,
                               color=WHITE, bold=True)
        self.next_btn.bind(on_release=self.go_next)
        self.next_btn.disabled = True
        self.root_layout.add_widget(self.next_btn)

        self.add_widget(self.root_layout)

    def on_enter(self):
        self.log_lines = []
        self.log("APK: " + STATE.apk_path)
        threading.Thread(target=self.do_extract, daemon=True).start()

    def log(self, msg):
        self.log_lines.append(msg)
        Clock.schedule_once(lambda dt: setattr(
            self.log_label, "text", "\n".join(self.log_lines[-40:])))

    def set_progress(self, val):
        Clock.schedule_once(lambda dt: setattr(self.progress, "value", val))

    def set_status(self, msg, color=WHITE):
        Clock.schedule_once(lambda dt: setattr(self.status_label, "text", msg))
        Clock.schedule_once(lambda dt: setattr(self.status_label, "color", color))

    def do_extract(self):
        try:
            apk = STATE.apk_path
            base_name = Path(apk).stem
            work = os.path.join(get_downloads(), f"HyperOS_IconPacker_{base_name}")
            STATE.work_dir      = work
            STATE.copy_icon_dir = os.path.join(work, "copy_icon")
            STATE.rename_dir    = os.path.join(work, "icon_rename")
            STATE.resize_dir    = os.path.join(work, "icon_resize")
            STATE.final_dir     = os.path.join(work, "Final")

            for d in [STATE.copy_icon_dir, STATE.rename_dir,
                      STATE.resize_dir, STATE.final_dir,
                      os.path.join(STATE.final_dir, "res", "drawable-xxhdpi")]:
                os.makedirs(d, exist_ok=True)

            self.set_status("Extracting APK…")
            self.log("Extracting APK...")
            self.set_progress(10)

            extract_dir = os.path.join(work, "base_extract")
            os.makedirs(extract_dir, exist_ok=True)

            with zipfile.ZipFile(apk, "r") as z:
                z.extractall(extract_dir)
            self.log("APK extracted.")
            self.set_progress(30)

            # Find appfilter.xml
            self.log("Searching for appfilter.xml...")
            appfilter = None
            for root_dir, dirs, files in os.walk(extract_dir):
                for f in files:
                    if f == "appfilter.xml":
                        appfilter = os.path.join(root_dir, f)
                        break
                if appfilter:
                    break

            if not appfilter:
                # Try assets/
                assets_dir = os.path.join(extract_dir, "assets")
                for root_dir, dirs, files in os.walk(assets_dir if os.path.exists(assets_dir) else extract_dir):
                    for f in files:
                        if "appfilter" in f.lower():
                            appfilter = os.path.join(root_dir, f)
                            break

            if appfilter:
                STATE.appfilter_path = appfilter
                shutil.copy2(appfilter, os.path.join(work, "appfilter.xml"))
                self.log(f"appfilter.xml found: {appfilter}")
            else:
                self.log("⚠ appfilter.xml not found — rename step will be skipped.")
            self.set_progress(50)

            # Find icons folder (largest drawable folder)
            self.log("Searching for icons folder...")
            res_dir = os.path.join(extract_dir, "res")
            best_folder = None
            best_count  = 0

            if os.path.exists(res_dir):
                for folder in os.listdir(res_dir):
                    folder_path = os.path.join(res_dir, folder)
                    if os.path.isdir(folder_path):
                        count = len([f for f in os.listdir(folder_path)
                                     if f.endswith(".png")])
                        if count > best_count:
                            best_count  = count
                            best_folder = folder_path

            if best_folder and best_count > 0:
                self.log(f"Icons folder: {Path(best_folder).name} ({best_count} icons)")
                self.set_progress(60)
                self.log(f"Copying {best_count} icons to copy_icon...")
                for i, fname in enumerate(os.listdir(best_folder)):
                    if fname.endswith(".png"):
                        shutil.copy2(os.path.join(best_folder, fname),
                                     os.path.join(STATE.copy_icon_dir, fname))
                    if i % 200 == 0:
                        self.set_progress(60 + int(30 * i / best_count))
                STATE.icon_count = best_count
                self.log(f"Done. {best_count} icons copied.")
                self.set_progress(100)
                self.set_status(f"✓ Extracted {best_count} icons!", SUCCESS)
                Clock.schedule_once(lambda dt: setattr(self.next_btn, "disabled", False))
            else:
                self.log("ERROR: Could not find icons folder in APK.")
                self.set_status("Error — no icons found in APK", ERROR)

        except Exception as e:
            self.log(f"ERROR: {e}")
            self.set_status(f"Error: {e}", ERROR)

    def go_next(self, *_):
        self.manager.transition = SlideTransition(direction="left")
        self.manager.current = "rename"


# ══════════════════════════════════════════════════════════════════════════════
# Screen 4 – Rename
# ══════════════════════════════════════════════════════════════════════════════
class RenameScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))

        root.add_widget(styled_label(
            "Step 3 — Rename Icons", font_size=dp(18), bold=True, color=ACCENT2))
        root.add_widget(styled_label(
            "This maps icon pack names (e.g. whatsapp.png) to "
            "package names (e.g. com.whatsapp.png) using appfilter.xml.",
            color=GREY, font_size=dp(13)
        ))

        self.status_label = styled_label("Ready.", color=GREY)
        root.add_widget(self.status_label)

        self.progress = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(20))
        root.add_widget(self.progress)

        sv = ScrollView(size_hint_y=1)
        self.log_label = Label(text="", color=GREY, font_size=dp(11),
                               size_hint_y=None, halign="left",
                               text_size=(Window.width - dp(32), None))
        self.log_label.bind(texture_size=self.log_label.setter("size"))
        sv.add_widget(self.log_label)
        root.add_widget(sv)

        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        self.run_btn = Button(text="▶  Run Rename", size_hint_x=0.5,
                              background_normal="", background_color=ACCENT,
                              color=WHITE, bold=True)
        self.run_btn.bind(on_release=self.run_rename)
        self.next_btn = Button(text="Next →", size_hint_x=0.5,
                               background_normal="", background_color=SUCCESS,
                               color=WHITE, bold=True)
        self.next_btn.bind(on_release=self.go_next)
        self.next_btn.disabled = True
        row.add_widget(self.run_btn)
        row.add_widget(self.next_btn)
        root.add_widget(row)

        self.add_widget(root)
        self.log_lines = []

    def log(self, msg):
        self.log_lines.append(msg)
        Clock.schedule_once(lambda dt: setattr(
            self.log_label, "text", "\n".join(self.log_lines[-40:])))

    def run_rename(self, *_):
        self.run_btn.disabled = True
        self.log_lines = []
        threading.Thread(target=self.do_rename, daemon=True).start()

    def do_rename(self):
        try:
            if not STATE.appfilter_path or not os.path.exists(STATE.appfilter_path):
                self.log("No appfilter.xml found — skipping rename.")
                self.log("Icons in copy_icon will be used as-is.")
                # Copy as-is to rename dir
                for f in os.listdir(STATE.copy_icon_dir):
                    shutil.copy2(os.path.join(STATE.copy_icon_dir, f),
                                 os.path.join(STATE.rename_dir, f))
                Clock.schedule_once(lambda dt: setattr(self.next_btn, "disabled", False))
                return

            appfilter_file = os.path.join(STATE.work_dir, "appfilter.xml")
            self.log("Reading appfilter.xml...")
            with open(appfilter_file, "r", encoding="utf-8", errors="ignore") as f:
                xml = f.read()

            pattern = r'component="ComponentInfo\{([^/]+)/[^}]+\}"\s+drawable="([^"]+)"'
            matches = re.findall(pattern, xml)
            self.log(f"Found {len(matches)} mappings in appfilter.xml")

            success = 0
            missing = 0
            total = len(matches)

            for i, (pkg, drawable) in enumerate(matches):
                src = os.path.join(STATE.copy_icon_dir, f"{drawable}.png")
                dst = os.path.join(STATE.rename_dir, f"{pkg}.png")
                if os.path.exists(src):
                    shutil.copy2(src, dst)
                    success += 1
                else:
                    missing += 1
                if i % 100 == 0:
                    Clock.schedule_once(
                        lambda dt, v=int(100*i/total): setattr(self.progress, "value", v))

            Clock.schedule_once(lambda dt: setattr(self.progress, "value", 100))
            self.log(f"Done! Renamed: {success} | Missing: {missing}")
            Clock.schedule_once(lambda dt: setattr(
                self.status_label, "text", f"✓ {success} icons renamed!"))
            Clock.schedule_once(lambda dt: setattr(
                self.status_label, "color", SUCCESS))
            Clock.schedule_once(lambda dt: setattr(self.next_btn, "disabled", False))

        except Exception as e:
            self.log(f"ERROR: {e}")

    def go_next(self, *_):
        self.manager.transition = SlideTransition(direction="left")
        self.manager.current = "resize"


# ══════════════════════════════════════════════════════════════════════════════
# Screen 5 – Resize
# ══════════════════════════════════════════════════════════════════════════════
class ResizeScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))

        root.add_widget(styled_label(
            "Step 4 — Resize Icons (Optional)",
            font_size=dp(18), bold=True, color=ACCENT2))
        root.add_widget(styled_label(
            "Resize icons to match a HyperOS theme's expected size. "
            "Disable if your icons are already the correct size.",
            color=GREY, font_size=dp(13)
        ))

        # Toggle
        self.toggle = ToggleButton(text="Resize: ON", state="down",
                                   size_hint_y=None, height=dp(44),
                                   background_normal="",
                                   background_color=ACCENT,
                                   color=WHITE, bold=True)
        self.toggle.bind(on_press=self.toggle_resize)
        root.add_widget(self.toggle)

        # Size input
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        row.add_widget(styled_label("Target size (px):", color=WHITE, font_size=dp(14)))
        self.size_input = TextInput(text="266", multiline=False,
                                    size_hint_x=0.4, size_hint_y=None, height=dp(40),
                                    background_color=CARD, foreground_color=WHITE,
                                    font_size=dp(16), input_filter="int")
        row.add_widget(self.size_input)
        root.add_widget(row)

        if not PIL_AVAILABLE:
            root.add_widget(styled_label(
                "⚠ Pillow not installed — resize unavailable. "
                "Icons will be copied without resizing.",
                color=WARN, font_size=dp(12)
            ))

        self.status_label = styled_label("Ready.", color=GREY)
        root.add_widget(self.status_label)

        self.progress = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(20))
        root.add_widget(self.progress)

        sv = ScrollView(size_hint_y=1)
        self.log_label = Label(text="", color=GREY, font_size=dp(11),
                               size_hint_y=None, halign="left",
                               text_size=(Window.width - dp(32), None))
        self.log_label.bind(texture_size=self.log_label.setter("size"))
        sv.add_widget(self.log_label)
        root.add_widget(sv)

        row2 = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        self.run_btn = Button(text="▶  Run Resize", size_hint_x=0.5,
                              background_normal="", background_color=ACCENT,
                              color=WHITE, bold=True)
        self.run_btn.bind(on_release=self.run_resize)
        self.next_btn = Button(text="Next →", size_hint_x=0.5,
                               background_normal="", background_color=SUCCESS,
                               color=WHITE, bold=True)
        self.next_btn.bind(on_release=self.go_next)
        self.next_btn.disabled = True
        row2.add_widget(self.run_btn)
        row2.add_widget(self.next_btn)
        root.add_widget(row2)

        self.add_widget(root)
        self.log_lines = []

    def toggle_resize(self, btn):
        STATE.do_resize = btn.state == "down"
        btn.text = "Resize: ON" if STATE.do_resize else "Resize: OFF"
        btn.background_color = ACCENT if STATE.do_resize else GREY

    def log(self, msg):
        self.log_lines.append(msg)
        Clock.schedule_once(lambda dt: setattr(
            self.log_label, "text", "\n".join(self.log_lines[-40:])))

    def run_resize(self, *_):
        self.run_btn.disabled = True
        self.log_lines = []
        try:
            STATE.resize_px = int(self.size_input.text)
        except:
            STATE.resize_px = 266
        threading.Thread(target=self.do_resize, daemon=True).start()

    def do_resize(self):
        src_dir = STATE.rename_dir
        dst_dir = STATE.resize_dir

        files = [f for f in os.listdir(src_dir) if f.endswith(".png")]
        total = len(files)
        self.log(f"{total} icons to process...")

        if not STATE.do_resize or not PIL_AVAILABLE:
            self.log("Copying without resize...")
            for i, f in enumerate(files):
                shutil.copy2(os.path.join(src_dir, f), os.path.join(dst_dir, f))
                if i % 100 == 0:
                    Clock.schedule_once(
                        lambda dt, v=int(100*i/total): setattr(self.progress, "value", v))
        else:
            sz = (STATE.resize_px, STATE.resize_px)
            self.log(f"Resizing to {STATE.resize_px}px...")
            for i, fname in enumerate(files):
                try:
                    src = os.path.join(src_dir, fname)
                    dst = os.path.join(dst_dir, fname)
                    with Image.open(src) as img:
                        img = img.convert("RGBA")
                        bbox = img.getbbox()
                        if bbox:
                            img = img.crop(bbox)
                        img = img.resize(sz, Image.Resampling.LANCZOS)
                        img.save(dst, format="PNG")
                    add_srgb_sbit(dst)
                except Exception as e:
                    self.log(f"Skip {fname}: {e}")
                if i % 50 == 0:
                    Clock.schedule_once(
                        lambda dt, v=int(100*i/total): setattr(self.progress, "value", v))

        Clock.schedule_once(lambda dt: setattr(self.progress, "value", 100))
        self.log("Done!")
        Clock.schedule_once(lambda dt: setattr(
            self.status_label, "text", f"✓ {total} icons processed!"))
        Clock.schedule_once(lambda dt: setattr(self.status_label, "color", SUCCESS))
        Clock.schedule_once(lambda dt: setattr(self.next_btn, "disabled", False))

    def go_next(self, *_):
        self.manager.transition = SlideTransition(direction="left")
        self.manager.current = "build"


# ══════════════════════════════════════════════════════════════════════════════
# Screen 6 – Build Final.zip
# ══════════════════════════════════════════════════════════════════════════════
class BuildScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))

        root.add_widget(styled_label(
            "Step 5 — Build Final.zip",
            font_size=dp(18), bold=True, color=ACCENT2))
        root.add_widget(styled_label(
            "This builds the Final folder structure and zips it up, "
            "ready for injection via MT Manager.",
            color=GREY, font_size=dp(13)
        ))

        # transform_config.xml picker
        root.add_widget(styled_label(
            "transform_config.xml (optional but recommended):",
            color=WHITE, font_size=dp(13)
        ))
        xml_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.xml_label = styled_label("None selected", color=GREY, font_size=dp(12))
        xml_btn = Button(text="Browse", size_hint_x=0.3,
                         background_normal="", background_color=CARD,
                         color=WHITE, font_size=dp(13))
        xml_btn.bind(on_release=self.pick_xml)
        xml_row.add_widget(self.xml_label)
        xml_row.add_widget(xml_btn)
        root.add_widget(xml_row)

        self.status_label = styled_label("Ready to build.", color=GREY)
        root.add_widget(self.status_label)

        self.progress = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(20))
        root.add_widget(self.progress)

        sv = ScrollView(size_hint_y=1)
        self.log_label = Label(text="", color=GREY, font_size=dp(11),
                               size_hint_y=None, halign="left",
                               text_size=(Window.width - dp(32), None))
        self.log_label.bind(texture_size=self.log_label.setter("size"))
        sv.add_widget(self.log_label)
        root.add_widget(sv)

        self.build_btn = Button(text="▶  Build Final.zip", size_hint_y=None, height=dp(52),
                                background_normal="", background_color=ACCENT,
                                color=WHITE, bold=True, font_size=dp(16))
        self.build_btn.bind(on_release=self.do_build)
        root.add_widget(self.build_btn)

        self.add_widget(root)
        self.log_lines = []
        self.xml_path  = ""

    def pick_xml(self, *_):
        content = BoxLayout(orientation="vertical")
        fc = FileChooserListView(path=get_downloads(), filters=["*.xml"])
        content.add_widget(fc)
        btn_row = BoxLayout(size_hint_y=None, height=dp(44))

        def confirm(*_):
            if fc.selection:
                self.xml_path = fc.selection[0]
                self.xml_label.text = Path(self.xml_path).name
            popup.dismiss()

        def cancel(*_):
            popup.dismiss()

        btn_row.add_widget(Button(text="Cancel", on_release=cancel,
                                  background_normal="", background_color=ERROR, color=WHITE))
        btn_row.add_widget(Button(text="Select", on_release=confirm,
                                  background_normal="", background_color=SUCCESS, color=WHITE))
        content.add_widget(btn_row)
        popup = Popup(title="Select transform_config.xml",
                      content=content, size_hint=(0.95, 0.8))
        popup.open()

    def log(self, msg):
        self.log_lines.append(msg)
        Clock.schedule_once(lambda dt: setattr(
            self.log_label, "text", "\n".join(self.log_lines[-40:])))

    def do_build(self, *_):
        self.build_btn.disabled = True
        self.log_lines = []
        threading.Thread(target=self._build, daemon=True).start()

    def _build(self):
        try:
            drawable_dir = os.path.join(STATE.final_dir, "res", "drawable-xxhdpi")
            os.makedirs(drawable_dir, exist_ok=True)

            icon_src = STATE.resize_dir if STATE.do_resize else STATE.rename_dir
            files = [f for f in os.listdir(icon_src) if f.endswith(".png")]
            total = len(files)
            self.log(f"Copying {total} icons to Final/res/drawable-xxhdpi...")

            for i, f in enumerate(files):
                shutil.copy2(os.path.join(icon_src, f),
                             os.path.join(drawable_dir, f))
                if i % 200 == 0:
                    Clock.schedule_once(
                        lambda dt, v=int(40*i/total): setattr(self.progress, "value", v))

            self.log("Icons copied.")
            Clock.schedule_once(lambda dt: setattr(self.progress, "value", 45))

            # Copy transform_config.xml if provided
            if self.xml_path and os.path.exists(self.xml_path):
                shutil.copy2(self.xml_path,
                             os.path.join(STATE.final_dir, "transform_config.xml"))
                self.log("transform_config.xml copied.")
            else:
                self.log("No transform_config.xml — you'll need to add it manually.")

            # Copy appfilter.xml
            appfilter_dest = os.path.join(STATE.final_dir, "appfilter.xml")
            appfilter_src  = os.path.join(STATE.work_dir, "appfilter.xml")
            if os.path.exists(appfilter_src):
                shutil.copy2(appfilter_src, appfilter_dest)

            Clock.schedule_once(lambda dt: setattr(self.progress, "value", 60))

            # Build zip
            zip_path = os.path.join(get_downloads(),
                                    f"Final_{Path(STATE.apk_path).stem}.zip")
            STATE.output_zip = zip_path
            self.log(f"Zipping to {zip_path}...")

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root_d, dirs, files_z in os.walk(STATE.final_dir):
                    for file_z in files_z:
                        abs_path = os.path.join(root_d, file_z)
                        arc_name = os.path.relpath(abs_path, STATE.final_dir)
                        zf.write(abs_path, arc_name)
                        Clock.schedule_once(lambda dt: setattr(
                            self.progress, "value",
                            min(99, self.progress.value + 0.05)))

            Clock.schedule_once(lambda dt: setattr(self.progress, "value", 100))
            self.log(f"✓ Final.zip saved to Downloads!")
            Clock.schedule_once(lambda dt: setattr(
                self.status_label, "text", "✓ Final.zip is ready!"))
            Clock.schedule_once(lambda dt: setattr(self.status_label, "color", SUCCESS))
            Clock.schedule_once(lambda dt: self.manager.transition.__setattr__(
                "direction", "left"))
            Clock.schedule_once(lambda dt: setattr(
                self.manager, "current", "done"))

        except Exception as e:
            self.log(f"ERROR: {e}")
            Clock.schedule_once(lambda dt: setattr(self.build_btn, "disabled", False))


# ══════════════════════════════════════════════════════════════════════════════
# Screen 7 – Done
# ══════════════════════════════════════════════════════════════════════════════
class DoneScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(16))

        root.add_widget(Label(size_hint_y=0.1))

        root.add_widget(Label(text="🎉", font_size=dp(56),
                              size_hint_y=None, height=dp(80)))
        root.add_widget(Label(text="Final.zip is ready!", font_size=dp(24),
                              bold=True, color=SUCCESS,
                              size_hint_y=None, height=dp(40)))
        root.add_widget(Label(
            text="Saved to your Downloads folder.",
            font_size=dp(14), color=GREY,
            size_hint_y=None, height=dp(30)
        ))

        root.add_widget(Label(size_hint_y=0.05))

        steps = [
            "Next steps:",
            "1. Install a dummy theme from Theme Store",
            "2. Open MT Manager",
            "3. Navigate to the dummy theme .mrc file",
            "4. Delete old res / transform_config.xml inside it",
            "5. Copy your Final.zip contents into it",
            "6. Apply the theme from Theme Store → Icons",
        ]
        for s in steps:
            lbl = Label(text=s, font_size=dp(13),
                        color=ACCENT2 if s == "Next steps:" else WHITE,
                        bold=s == "Next steps:",
                        size_hint_y=None, height=dp(26),
                        halign="left")
            lbl.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
            root.add_widget(lbl)

        root.add_widget(Label(size_hint_y=0.1))

        restart = Button(text="Start Over", size_hint=(0.6, None), height=dp(48),
                         pos_hint={"center_x": 0.5},
                         background_normal="", background_color=ACCENT,
                         color=WHITE, bold=True)
        restart.bind(on_release=self.restart)
        root.add_widget(restart)

        self.add_widget(root)

    def restart(self, *_):
        STATE.apk_path = ""
        STATE.work_dir = ""
        self.manager.transition = SlideTransition(direction="right")
        self.manager.current = "welcome"


# ══════════════════════════════════════════════════════════════════════════════
# App
# ══════════════════════════════════════════════════════════════════════════════
class HyperOSIconPacker(App):
    def build(self):
        sm = ScreenManager()
        sm.add_widget(WelcomeScreen(name="welcome"))
        sm.add_widget(PickApkScreen(name="pick_apk"))
        sm.add_widget(ExtractScreen(name="extract"))
        sm.add_widget(RenameScreen(name="rename"))
        sm.add_widget(ResizeScreen(name="resize"))
        sm.add_widget(BuildScreen(name="build"))
        sm.add_widget(DoneScreen(name="done"))
        return sm

    def on_start(self):
        if ANDROID:
            request_permissions([Permission.READ_EXTERNAL_STORAGE,
                                  Permission.WRITE_EXTERNAL_STORAGE])


if __name__ == "__main__":
    HyperOSIconPacker().run()
