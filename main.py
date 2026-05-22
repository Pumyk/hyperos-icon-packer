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
def get_app_private_dir():
    """Returns the app's private files directory — always writable, no permissions needed."""
    if ANDROID:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        ctx = PythonActivity.mActivity
        return ctx.getFilesDir().getAbsolutePath()
    return str(Path.home() / "HyperOS_IconPacker")

def get_downloads():
    """Returns the public Downloads folder. Only use for final output files."""
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




# ══════════════════════════════════════════════════════════════════════════════
# Screen 2 – Pick APK
# ══════════════════════════════════════════════════════════════════════════════
class PickApkScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.selected_path = ""

        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(20))

        lbl_title = Label(
            text="Step 1 — Select Icon Pack APK",
            font_size=dp(18), bold=True, color=ACCENT2,
            size_hint_y=None, height=dp(40),
            halign="left", valign="middle"
        )
        lbl_title.bind(size=lambda i, v: setattr(i, "text_size", v))
        root.add_widget(lbl_title)

        lbl_info = Label(
            text="Tap the button below. Your file manager will open — find and select your icon pack APK.",
            font_size=dp(13), color=GREY,
            size_hint_y=None, height=dp(60),
            halign="left", valign="top"
        )
        lbl_info.bind(size=lambda i, v: setattr(i, "text_size", v))
        root.add_widget(lbl_info)

        root.add_widget(BoxLayout(size_hint_y=1))

        self.select_btn = Button(
            text="Browse & Select APK",
            size_hint_y=None, height=dp(56),
            background_normal="", background_color=ACCENT,
            color=WHITE, font_size=dp(16), bold=True
        )
        self.select_btn.bind(on_release=self.open_file_picker)
        root.add_widget(self.select_btn)

        self.path_label = Label(
            text="No file selected",
            color=GREY, font_size=dp(12),
            size_hint_y=None, height=dp(80),
            halign="center", valign="middle"
        )
        self.path_label.bind(size=lambda i, v: setattr(i, "text_size", v))
        root.add_widget(self.path_label)

        root.add_widget(BoxLayout(size_hint_y=1))

        row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        back = Button(text="Back", size_hint_x=0.35,
                      background_normal="", background_color=CARD, color=WHITE)
        back.bind(on_release=self.go_back)
        self.next_btn = Button(text="Next", size_hint_x=0.65,
                               background_normal="", background_color=ACCENT,
                               color=WHITE, bold=True)
        self.next_btn.bind(on_release=self.go_next)
        self.next_btn.disabled = True
        row.add_widget(back)
        row.add_widget(self.next_btn)
        root.add_widget(row)

        self.add_widget(root)

    def set_status(self, msg, color=None):
        Clock.schedule_once(lambda dt: setattr(self.path_label, "text", msg))
        Clock.schedule_once(lambda dt: setattr(
            self.path_label, "color", color if color else GREY))

    def open_file_picker(self, *_):
        if ANDROID:
            self._open_android_picker()
        else:
            self._open_desktop_picker()

    def _open_android_picker(self):
        try:
            from jnius import autoclass, cast
            from android import activity
            self.set_status("Opening file picker...", GREY)
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            intent = Intent()
            intent.setAction(Intent.ACTION_GET_CONTENT)
            intent.setType("*/*")
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            activity.bind(on_activity_result=self._on_activity_result)
            cast("android.app.Activity", PythonActivity.mActivity).startActivityForResult(intent, 1001)
        except Exception as e:
            self.set_status("Picker error: " + str(e)[:100], ERROR)

    def _on_activity_result(self, request_code, result_code, data):
        try:
            from android import activity
            activity.unbind(on_activity_result=self._on_activity_result)

            if request_code != 1001 or result_code != -1 or data is None:
                self.set_status("Picker cancelled", GREY)
                return

            uri = data.getData()
            if uri is None:
                self.set_status("No URI returned", ERROR)
                return

            uri_str = uri.toString()
            self.set_status("Got URI, resolving path...", WARN)

            # Strategy 1: resolve to real file path (no copy needed)
            real_path = self._resolve_uri_to_path(uri_str)
            if real_path and os.path.isfile(real_path):
                # Verify it's a valid zip/apk before accepting
                if self._is_valid_zip(real_path):
                    Clock.schedule_once(lambda dt: self._set_selected(real_path))
                    return
                else:
                    self.set_status("Resolved path invalid, copying...", WARN)

            # Strategy 2: open file descriptor and read via Python os.read()
            # This is the most reliable — bypasses Java stream issues entirely
            self.set_status("Reading via file descriptor...", WARN)
            threading.Thread(
                target=self._fd_copy_uri, args=(uri,), daemon=True
            ).start()

        except Exception as e:
            self.set_status("Result error: " + str(e)[:100], ERROR)

    def _resolve_uri_to_path(self, uri_str):
        try:
            import urllib.parse
            decoded = urllib.parse.unquote(uri_str)
            if "primary:" in decoded:
                idx = decoded.find("primary:")
                rel = decoded[idx + len("primary:"):]
                return "/storage/emulated/0/" + rel
            if "/raw:" in decoded:
                return decoded[decoded.find("/raw:") + 5:]
        except Exception:
            pass
        return None

    def _is_valid_zip(self, path):
        try:
            import zipfile
            return zipfile.is_zipfile(path)
        except Exception:
            return False

    def _fd_copy_uri(self, uri):
        """
        Open the URI as a ParcelFileDescriptor, get its raw file descriptor int,
        then use Python's os.read() to copy — fully bypasses Java stream wrapping.
        """
        dest = None
        try:
            from jnius import autoclass
            PythonActivity  = autoclass("org.kivy.android.PythonActivity")
            ParcelFileDescriptor = autoclass("android.os.ParcelFileDescriptor")

            ctx      = PythonActivity.mActivity
            resolver = ctx.getContentResolver()

            # Open as ParcelFileDescriptor — MODE_READ_ONLY = "r"
            pfd = resolver.openFileDescriptor(uri, "r")
            if pfd is None:
                self.set_status("Could not open file descriptor", ERROR)
                return

            # Get the raw int fd
            raw_fd = pfd.getFd()

            cache_dir = ctx.getCacheDir().getAbsolutePath()
            dest = os.path.join(cache_dir, "icon_pack.apk")

            # Read using Python's os.read() — native, no JVM overhead
            CHUNK = 65536
            total = 0
            with open(dest, "wb") as out_f:
                while True:
                    chunk = os.read(raw_fd, CHUNK)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    total += len(chunk)

            pfd.close()

            size_mb = total / 1048576
            self.set_status("Read %.2f MB" % size_mb, WARN)

            if total == 0:
                self.set_status("File descriptor read 0 bytes", ERROR)
                return

            if not self._is_valid_zip(dest):
                self.set_status("Copied file is not a valid APK/zip (%.2f MB)" % size_mb, ERROR)
                return

            Clock.schedule_once(lambda dt: self._set_selected(dest))

        except Exception as e:
            self.set_status("FD copy error: " + str(e)[:100], ERROR)

    def _open_desktop_picker(self):
        from kivy.uix.filechooser import FileChooserListView
        from kivy.uix.popup import Popup
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        fc = FileChooserListView(path=str(Path.home()), filters=["*.apk"])
        content.add_widget(fc)
        btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        cancel_btn = Button(text="Cancel", background_normal="",
                            background_color=CARD, color=WHITE)
        select_btn = Button(text="Select", background_normal="",
                            background_color=ACCENT, color=WHITE, bold=True)
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(select_btn)
        content.add_widget(btn_row)
        popup = Popup(title="Select APK", content=content, size_hint=(0.95, 0.85))
        def do_select(*_):
            if fc.selection:
                self._set_selected(fc.selection[0])
            popup.dismiss()
        cancel_btn.bind(on_release=popup.dismiss)
        select_btn.bind(on_release=do_select)
        popup.open()

    def _set_selected(self, path):
        self.selected_path = path
        Clock.schedule_once(lambda dt: setattr(
            self.path_label, "text", "Selected: " + os.path.basename(path)))
        Clock.schedule_once(lambda dt: setattr(self.path_label, "color", SUCCESS))
        Clock.schedule_once(lambda dt: setattr(self.next_btn, "disabled", False))

    def go_back(self, *_):
        self.manager.transition = SlideTransition(direction="right")
        self.manager.current = "welcome"

    def go_next(self, *_):
        STATE.apk_path = self.selected_path
        self.manager.transition = SlideTransition(direction="left")
        self.manager.current = "extract"


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
            work = os.path.join(get_app_private_dir(), "HyperOS_IconPacker_" + base_name)
            # Wipe old run so stale data never bleeds in
            if os.path.exists(work):
                shutil.rmtree(work, ignore_errors=True)
            STATE.work_dir      = work
            STATE.copy_icon_dir = os.path.join(work, "copy_icon")
            STATE.rename_dir    = os.path.join(work, "icon_rename")
            STATE.resize_dir    = os.path.join(work, "icon_resize")
            STATE.final_dir     = os.path.join(work, "Final")
            for d in [STATE.copy_icon_dir, STATE.rename_dir, STATE.resize_dir,
                      STATE.final_dir,
                      os.path.join(STATE.final_dir, "res", "drawable-xxhdpi")]:
                os.makedirs(d, exist_ok=True)

            self.set_status("Extracting APK...")
            self.log("APK: " + apk)
            self.set_progress(5)

            extract_dir = os.path.join(work, "base_extract")
            os.makedirs(extract_dir, exist_ok=True)

            # Extract APK (it is a zip)
            with zipfile.ZipFile(apk, "r") as z:
                z.extractall(extract_dir)
            self.log("Extracted. Scanning contents...")
            self.set_progress(20)

            # ── DUMP full tree so we always know what's inside ─────────────
            tree = {}
            for root_dir, dirs, files in os.walk(extract_dir):
                rel = os.path.relpath(root_dir, extract_dir)
                if files:
                    by_ext = {}
                    for f in files:
                        ext = os.path.splitext(f)[1].lower()
                        by_ext.setdefault(ext, []).append(f)
                    tree[rel] = by_ext

            # Log every folder with PNGs (sorted by count desc)
            png_folders = sorted(
                [(p, v['.png']) for p, v in tree.items() if '.png' in v],
                key=lambda x: -len(x[1])
            )
            self.log("PNG folders found: %d" % len(png_folders))
            for path, files in png_folders[:8]:
                self.log("  %s — %d PNGs" % (path, len(files)))

            # Log xml files for appfilter hunt
            xml_files = []
            for root_dir, dirs, files in os.walk(extract_dir):
                for f in files:
                    if f.lower().endswith('.xml'):
                        xml_files.append(os.path.join(root_dir, f))
            self.log("XML files: %d total" % len(xml_files))
            for xf in xml_files[:10]:
                self.log("  " + os.path.relpath(xf, extract_dir))

            self.set_progress(30)

            # ── 1. appfilter.xml: try to read as text, decode binary if needed ──
            self.log("Locating appfilter.xml...")
            appfilter_path = None
            appfilter_text = None

            # Priority order: res/xml/, assets/, root, anywhere
            candidates = [xf for xf in xml_files if "appfilter" in os.path.basename(xf).lower()]
            self.log("appfilter candidates: %d" % len(candidates))
            for c in candidates:
                self.log("  " + os.path.relpath(c, extract_dir))

            for candidate in candidates:
                text = self._try_read_xml(candidate)
                if text and ("ComponentInfo" in text or "drawable=" in text):
                    appfilter_path = candidate
                    appfilter_text = text
                    self.log("appfilter OK: " + os.path.relpath(candidate, extract_dir))
                    break
                else:
                    self.log("  (binary/empty, skipping)")

            if appfilter_path:
                STATE.appfilter_path = appfilter_path
                # Save decoded plain text version for rename step
                plain = os.path.join(work, "appfilter.xml")
                with open(plain, "w", encoding="utf-8") as f:
                    f.write(appfilter_text)
                STATE.appfilter_decoded = plain
                count_map = len(re.findall(r'drawable="', appfilter_text))
                self.log("appfilter: %d drawable mappings" % count_map)
            else:
                self.log("appfilter.xml not readable — rename will copy as-is.")
                STATE.appfilter_path = None
                STATE.appfilter_decoded = None

            self.set_progress(45)

            # ── 2. Find icons folder ───────────────────────────────────────
            # Pick the folder with the most PNGs that is NOT a mipmap/launcher folder
            best_folder = None
            best_files  = []

            for folder_rel, files in png_folders:
                folder_abs = os.path.join(extract_dir, folder_rel)
                # Skip tiny launcher icon folders
                if len(files) < 5:
                    continue
                # Prefer drawable-nodpi, drawable-xxhdpi, drawable, assets/icons
                # Deprioritise mipmap folders (usually just launcher icons)
                if "mipmap" in folder_rel:
                    continue
                best_folder = folder_abs
                best_files  = files
                break

            # Fallback: biggest folder regardless
            if not best_folder and png_folders:
                folder_rel, files = png_folders[0]
                best_folder = os.path.join(extract_dir, folder_rel)
                best_files  = files

            if best_folder and best_files:
                self.log("Icons folder: %s (%d)" % (
                    os.path.relpath(best_folder, extract_dir), len(best_files)))
                self.set_progress(55)
                self.log("Copying icons...")
                for i, fname in enumerate(best_files):
                    shutil.copy2(os.path.join(best_folder, fname),
                                 os.path.join(STATE.copy_icon_dir, fname))
                    if i % 200 == 0:
                        self.set_progress(55 + int(35 * i / max(len(best_files), 1)))
                STATE.icon_count = len(best_files)
                self.log("Copied %d icons." % len(best_files))
                self.set_progress(100)
                self.set_status("Extracted %d icons!" % len(best_files), SUCCESS)
                Clock.schedule_once(lambda dt: setattr(self.next_btn, "disabled", False))
            else:
                self.log("No usable PNG folder found.")
                self.log("All folders: " + str([p for p, _ in png_folders[:10]]))
                self.set_status("Error: no icons found", ERROR)

        except Exception as e:
            import traceback
            self.log("ERROR: " + str(e))
            self.log(traceback.format_exc()[-300:])
            self.set_status("Error: " + str(e)[:60], ERROR)

    def _try_read_xml(self, path):
        """Try reading XML as plain text. If it looks binary, decode Android binary XML."""
        try:
            with open(path, "rb") as f:
                raw = f.read()
            # Plain text XML starts with '<' or BOM
            if raw[:1] in (b'<', b'\xef'):
                return raw.decode("utf-8", errors="ignore")
            # Android binary XML starts with 0x03 0x00 0x08 0x00
            if raw[:2] == b'\x03\x00':
                return self._decode_binary_xml(raw)
            # Try as text anyway
            text = raw.decode("utf-8", errors="ignore")
            if "drawable=" in text:
                return text
            return None
        except Exception:
            return None

    def _decode_binary_xml(self, data):
        """
        Decode Android binary XML (AXML) to extract drawable mappings.
        We don't need a full decoder — just extract all attribute strings.
        The string pool is at offset 8; we parse it to get all values,
        then reconstruct component→drawable pairs from the attribute data.
        """
        try:
            import struct

            # Parse string pool to get all strings
            strings = []
            i = 8  # skip file header
            while i < len(data) - 4:
                chunk_type = struct.unpack_from('<H', data, i)[0]
                chunk_size = struct.unpack_from('<I', data, i + 4)[0]
                if chunk_size == 0:
                    break
                if chunk_type == 0x0001:  # STRING_POOL_TYPE
                    str_count = struct.unpack_from('<I', data, i + 8)[0]
                    flags     = struct.unpack_from('<I', data, i + 16)[0]
                    str_start = struct.unpack_from('<I', data, i + 20)[0]
                    offsets_base = i + 28
                    pool_base    = i + 8 + str_start
                    is_utf8 = bool(flags & (1 << 8))
                    for s in range(str_count):
                        off = struct.unpack_from('<I', data, offsets_base + s * 4)[0]
                        abs_off = pool_base + off
                        try:
                            if is_utf8:
                                # skip two length bytes
                                slen = data[abs_off + 1]
                                s_bytes = data[abs_off + 2: abs_off + 2 + slen]
                                strings.append(s_bytes.decode("utf-8", errors="ignore"))
                            else:
                                slen = struct.unpack_from('<H', data, abs_off)[0]
                                s_bytes = data[abs_off + 2: abs_off + 2 + slen * 2]
                                strings.append(s_bytes.decode("utf-16-le", errors="ignore"))
                        except Exception:
                            strings.append("")
                i += chunk_size

            # Now reconstruct XML-like output from string list
            # appfilter entries look like:
            #   component="ComponentInfo{pkg/activity}" drawable="icon_name"
            # The strings pool contains all literal values.
            # Build synthetic appfilter from consecutive component/drawable strings.
            lines_out = ['<?xml version="1.0" encoding="utf-8"?>', '<appfilter>']
            component = None
            drawable  = None
            for s in strings:
                if s.startswith("ComponentInfo{") and "/" in s:
                    component = s
                elif component and s and not s.startswith("ComponentInfo") and "." not in s.split("/")[0]:
                    # drawable names are lowercase_underscore, no dots, no slashes
                    drawable = s
                    lines_out.append(
                        '  <item component="%s" drawable="%s"/>' % (component, drawable))
                    component = None
                    drawable  = None

            lines_out.append("</appfilter>")
            result = "\n".join(lines_out)
            if len(lines_out) > 3:
                return result
            return None
        except Exception:
            return None

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
            # Use the decoded plain-text appfilter saved by ExtractScreen
            appfilter_file = getattr(STATE, "appfilter_decoded", None)

            if not appfilter_file or not os.path.exists(appfilter_file):
                self.log("No readable appfilter — copying icons as-is.")
                icons = [f for f in os.listdir(STATE.copy_icon_dir)
                         if f.lower().endswith(".png")]
                for f in icons:
                    shutil.copy2(os.path.join(STATE.copy_icon_dir, f),
                                 os.path.join(STATE.rename_dir, f))
                self.log("Copied %d icons unchanged." % len(icons))
                Clock.schedule_once(lambda dt: setattr(self.next_btn, "disabled", False))
                return

            self.log("Reading appfilter.xml (%s)..." % appfilter_file)
            with open(appfilter_file, "r", encoding="utf-8", errors="ignore") as f:
                xml = f.read()

            # Match both formats:
            # component="ComponentInfo{pkg/activity}" drawable="name"
            # component="ComponentInfo{pkg/.Activity}" drawable="name"
            pattern = r'component="ComponentInfo\{([^/]+)/[^}]*\}"\s+drawable="([^"]+)"'
            matches = re.findall(pattern, xml)
            self.log("Mappings found: %d" % len(matches))

            if not matches:
                self.log("No mappings parsed — check first 500 chars of appfilter:")
                self.log(xml[:500])
                # Still copy as-is
                icons = [f for f in os.listdir(STATE.copy_icon_dir)
                         if f.lower().endswith(".png")]
                for f in icons:
                    shutil.copy2(os.path.join(STATE.copy_icon_dir, f),
                                 os.path.join(STATE.rename_dir, f))
                Clock.schedule_once(lambda dt: setattr(self.next_btn, "disabled", False))
                return

            success = 0
            missing = 0
            total   = len(matches)

            # Build lookup: drawable_name (lowercase) -> actual filename in copy_icon
            copy_icons = {f[:-4].lower(): f for f in os.listdir(STATE.copy_icon_dir)
                          if f.lower().endswith(".png")}
            self.log("Icons in copy_icon: %d" % len(copy_icons))

            for i, (pkg, drawable) in enumerate(matches):
                key = drawable.lower()
                if key in copy_icons:
                    src = os.path.join(STATE.copy_icon_dir, copy_icons[key])
                    dst = os.path.join(STATE.rename_dir, pkg + ".png")
                    shutil.copy2(src, dst)
                    success += 1
                else:
                    missing += 1
                if i % 100 == 0:
                    Clock.schedule_once(
                        lambda dt, v=int(100 * i / max(total, 1)):
                        setattr(self.progress, "value", v))

            Clock.schedule_once(lambda dt: setattr(self.progress, "value", 100))
            self.log("Renamed: %d | Not found: %d" % (success, missing))

            if success == 0:
                self.log("0 icons renamed — sample drawables from appfilter:")
                for _, d in matches[:5]:
                    self.log("  drawable='%s' in copy_icon: %s" % (
                        d, str(d.lower() in copy_icons)))
                self.log("Sample copy_icon files: " + str(list(copy_icons.keys())[:5]))

            Clock.schedule_once(lambda dt: setattr(
                self.status_label, "text", "%d icons renamed!" % success))
            Clock.schedule_once(lambda dt: setattr(
                self.status_label, "color", SUCCESS if success > 0 else ERROR))
            Clock.schedule_once(lambda dt: setattr(self.next_btn, "disabled", False))

        except Exception as e:
            import traceback
            self.log("ERROR: " + str(e))
            self.log(traceback.format_exc()[-200:])

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
        self.manager.current = "mask"


# ══════════════════════════════════════════════════════════════════════════════
# Screen 6 – Build Final.zip
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# Screen 6 – Mask (auto-generate iconback / iconmask / iconupon)
# ══════════════════════════════════════════════════════════════════════════════
class MaskScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))

        root.add_widget(styled_label(
            "Step 6 — Icon Shape Mask",
            font_size=dp(18), bold=True, color=ACCENT2))
        root.add_widget(styled_label(
            "Auto-generates iconback, iconmask & iconupon so unthemed apps "
            "adapt to your icon pack's shape.",
            color=GREY, font_size=dp(13)))

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

        btn_row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        self.gen_btn = Button(text="Generate Mask Files", size_hint_x=0.55,
                              background_normal="", background_color=ACCENT,
                              color=WHITE, bold=True)
        self.gen_btn.bind(on_release=self.run_generate)
        self.skip_btn = Button(text="Skip", size_hint_x=0.2,
                               background_normal="", background_color=CARD,
                               color=WHITE)
        self.skip_btn.bind(on_release=self.go_next)
        self.next_btn = Button(text="Next →", size_hint_x=0.25,
                               background_normal="", background_color=SUCCESS,
                               color=WHITE, bold=True)
        self.next_btn.bind(on_release=self.go_next)
        self.next_btn.disabled = True
        btn_row.add_widget(self.gen_btn)
        btn_row.add_widget(self.skip_btn)
        btn_row.add_widget(self.next_btn)
        root.add_widget(btn_row)

        self.add_widget(root)
        self.log_lines = []

    def log(self, msg):
        self.log_lines.append(msg)
        Clock.schedule_once(lambda dt: setattr(
            self.log_label, "text", "\n".join(self.log_lines[-40:])))

    def set_status(self, msg, color=WHITE):
        Clock.schedule_once(lambda dt: setattr(self.status_label, "text", msg))
        Clock.schedule_once(lambda dt: setattr(self.status_label, "color", color))

    def set_progress(self, v):
        Clock.schedule_once(lambda dt: setattr(self.progress, "value", v))

    def run_generate(self, *_):
        self.gen_btn.disabled = True
        self.log_lines = []
        threading.Thread(target=self.do_generate, daemon=True).start()

    def do_generate(self):
        try:
            from PIL import Image, ImageFilter, ImageDraw
            import numpy as np

            src_dir = STATE.resize_dir
            icons = [f for f in os.listdir(src_dir) if f.lower().endswith(".png")]
            if not icons:
                self.log("No icons in resize dir — run Resize step first.")
                self.set_status("Error: no icons found", ERROR)
                Clock.schedule_once(lambda dt: setattr(self.gen_btn, "disabled", False))
                return

            self.log("Analysing icons to detect shape...")
            self.set_progress(10)

            # ── Sample up to 20 icons, accumulate alpha masks ──────────────
            SIZE = 192
            sample = icons[:20]
            accumulated = None

            for fname in sample:
                try:
                    img = Image.open(os.path.join(src_dir, fname)).convert("RGBA")
                    img = img.resize((SIZE, SIZE), Image.LANCZOS)
                    alpha = img.split()[3]  # alpha channel
                    # Threshold: pixel is "inside" if alpha > 64
                    import array as _arr
                    alpha_data = list(alpha.getdata())
                    binary = [255 if a > 64 else 0 for a in alpha_data]
                    if accumulated is None:
                        accumulated = binary[:]
                    else:
                        # Union: if ANY icon has this pixel opaque, count it
                        accumulated = [max(accumulated[i], binary[i])
                                       for i in range(len(binary))]
                except Exception:
                    continue

            if accumulated is None:
                self.log("Could not read any icons.")
                self.set_status("Error reading icons", ERROR)
                Clock.schedule_once(lambda dt: setattr(self.gen_btn, "disabled", False))
                return

            self.set_progress(30)
            self.log("Shape detected. Generating mask files...")

            # Build alpha mask image from accumulated
            mask_img = Image.new("L", (SIZE, SIZE), 0)
            mask_img.putdata(accumulated)

            # Smooth the mask edges slightly
            mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=2))
            # Re-threshold after blur
            mask_data = [255 if p > 64 else 0 for p in list(mask_img.getdata())]
            mask_img.putdata(mask_data)

            self.set_progress(45)

            # ── iconmask.png: white inside shape, black outside ────────────
            iconmask = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
            white_layer = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255))
            iconmask.paste(white_layer, mask=mask_img)
            iconmask_path = os.path.join(src_dir, "iconmask.png")
            iconmask.save(iconmask_path)
            self.log("iconmask.png saved.")
            self.set_progress(55)

            # ── iconback.png: compute average bg color from sampled icons ──
            avg_r, avg_g, avg_b = [], [], []
            for fname in sample[:10]:
                try:
                    img = Image.open(os.path.join(src_dir, fname)).convert("RGBA")
                    img = img.resize((SIZE, SIZE), Image.LANCZOS)
                    pixels = list(img.getdata())
                    # Get opaque pixels only
                    opaque = [(r, g, b) for r, g, b, a in pixels if a > 128]
                    if opaque:
                        avg_r.append(sum(p[0] for p in opaque) // len(opaque))
                        avg_g.append(sum(p[1] for p in opaque) // len(opaque))
                        avg_b.append(sum(p[2] for p in opaque) // len(opaque))
                except Exception:
                    continue

            if avg_r:
                bg_color = (
                    sum(avg_r) // len(avg_r),
                    sum(avg_g) // len(avg_g),
                    sum(avg_b) // len(avg_b),
                    255
                )
            else:
                bg_color = (255, 255, 255, 255)

            self.log("Background color: rgb%s" % str(bg_color[:3]))

            iconback = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            color_layer = Image.new("RGBA", (SIZE, SIZE), bg_color)
            iconback.paste(color_layer, mask=mask_img)
            iconback_path = os.path.join(src_dir, "iconback.png")
            iconback.save(iconback_path)
            self.log("iconback.png saved.")
            self.set_progress(70)

            # ── iconupon.png: fully transparent overlay ────────────────────
            iconupon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            iconupon_path = os.path.join(src_dir, "iconupon.png")
            iconupon.save(iconupon_path)
            self.log("iconupon.png saved.")
            self.set_progress(80)

            # ── Inject tags into decoded appfilter.xml ─────────────────────
            appfilter_file = getattr(STATE, "appfilter_decoded", None)
            if appfilter_file and os.path.exists(appfilter_file):
                with open(appfilter_file, "r", encoding="utf-8") as f:
                    xml = f.read()

                mask_tags = (
                    '\n  <iconback img1="iconback"/>'
                    '\n  <iconmask img1="iconmask"/>'
                    '\n  <iconupon img1="iconupon"/>'
                )

                # Only inject if not already present
                if 'iconback' not in xml:
                    if '</appfilter>' in xml:
                        xml = xml.replace('</appfilter>', mask_tags + '\n</appfilter>')
                    elif '<appfilter>' in xml:
                        xml = xml.replace('<appfilter>', '<appfilter>' + mask_tags)
                    else:
                        xml = xml + mask_tags

                    with open(appfilter_file, "w", encoding="utf-8") as f:
                        f.write(xml)
                    self.log("Injected iconback/mask/upon into appfilter.xml.")
                else:
                    self.log("appfilter.xml already has mask tags.")
            else:
                self.log("No appfilter.xml to update.")

            self.set_progress(100)
            self.set_status("Mask files ready!", SUCCESS)
            self.log("Done! iconback, iconmask, iconupon generated.")
            Clock.schedule_once(lambda dt: setattr(self.next_btn, "disabled", False))

        except Exception as e:
            import traceback
            self.log("ERROR: " + str(e))
            self.log(traceback.format_exc()[-300:])
            self.set_status("Error: " + str(e)[:60], ERROR)
            Clock.schedule_once(lambda dt: setattr(self.gen_btn, "disabled", False))

    def go_next(self, *_):
        self.manager.transition = SlideTransition(direction="left")
        self.manager.current = "build"

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
            # Correct HyperOS zip structure to prevent theme revert:
            #   res/drawable-xxhdpi/  <- all icons
            #   res/xml/              <- appfilter.xml (NOT at root)
            #   transform_config.xml  <- root level (required)
            #   description.xml       <- root level (marks theme permanent)
            drawable_dir = os.path.join(STATE.final_dir, "res", "drawable-xxhdpi")
            xml_dir      = os.path.join(STATE.final_dir, "res", "xml")
            os.makedirs(drawable_dir, exist_ok=True)
            os.makedirs(xml_dir,      exist_ok=True)

            icon_src = STATE.resize_dir if STATE.do_resize else STATE.rename_dir
            files = [f for f in os.listdir(icon_src) if f.lower().endswith(".png")]
            total = len(files)
            self.log("Copying %d icons to res/drawable-xxhdpi..." % total)

            for i, f in enumerate(files):
                shutil.copy2(os.path.join(icon_src, f),
                             os.path.join(drawable_dir, f))
                if i % 200 == 0:
                    Clock.schedule_once(
                        lambda dt, v=int(40*i/max(total,1)):
                        setattr(self.progress, "value", v))

            self.log("Icons copied.")
            Clock.schedule_once(lambda dt: setattr(self.progress, "value", 45))

            # appfilter.xml -> res/xml/ (NOT root)
            appfilter_src = getattr(STATE, "appfilter_decoded", None) or \
                            os.path.join(STATE.work_dir, "appfilter.xml")
            if appfilter_src and os.path.exists(appfilter_src):
                shutil.copy2(appfilter_src, os.path.join(xml_dir, "appfilter.xml"))
                self.log("appfilter.xml -> res/xml/")
            else:
                self.log("WARNING: no appfilter.xml found.")

            Clock.schedule_once(lambda dt: setattr(self.progress, "value", 55))

            # transform_config.xml at root
            tc_dest = os.path.join(STATE.final_dir, "transform_config.xml")
            if self.xml_path and os.path.exists(self.xml_path):
                shutil.copy2(self.xml_path, tc_dest)
                self.log("transform_config.xml from user file.")
            else:
                tc_xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
                           '<configs>\n'
                           '  <config>\n'
                           '    <name>icons</name>\n'
                           '  </config>\n'
                           '</configs>\n')
                with open(tc_dest, "w", encoding="utf-8") as tf:
                    tf.write(tc_xml)
                self.log("transform_config.xml auto-generated.")

            # description.xml at root — prevents HyperOS reverting the theme
            pack_name = Path(STATE.apk_path).stem
            desc_xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
                         '<description>\n'
                         '  <item name="name" value="' + pack_name + '"/>\n'
                         '  <item name="designer" value="HyperOS Icon Packer"/>\n'
                         '  <item name="version" value="1"/>\n'
                         '  <item name="uiversion" value="1"/>\n'
                         '  <item name="preview" value="preview"/>\n'
                         '</description>\n')
            desc_dest = os.path.join(STATE.final_dir, "description.xml")
            with open(desc_dest, "w", encoding="utf-8") as df:
                df.write(desc_xml)
            self.log("description.xml generated.")

            Clock.schedule_once(lambda dt: setattr(self.progress, "value", 65))

            # Build zip
            zip_path = os.path.join(get_downloads(), "HyperOS_" + pack_name + ".zip")
            STATE.output_zip = zip_path
            self.log("Zipping to " + zip_path)

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root_d, dirs, files_z in os.walk(STATE.final_dir):
                    for file_z in files_z:
                        abs_path = os.path.join(root_d, file_z)
                        arc_name = os.path.relpath(abs_path, STATE.final_dir)
                        zf.write(abs_path, arc_name)

            # Log zip contents for verification
            self.log("Zip contents:")
            with zipfile.ZipFile(zip_path, "r") as zf:
                for e in sorted(zf.namelist())[:8]:
                    self.log("  " + e)
                total_z = len(zf.namelist())
                if total_z > 8:
                    self.log("  ... (%d total files)" % total_z)

            Clock.schedule_once(lambda dt: setattr(self.progress, "value", 100))
            self.log("Done! Saved to Downloads.")
            Clock.schedule_once(lambda dt: setattr(
                self.status_label, "text", "Final.zip is ready!"))
            Clock.schedule_once(lambda dt: setattr(self.status_label, "color", SUCCESS))
            Clock.schedule_once(lambda dt: self.manager.transition.__setattr__(
                "direction", "left"))
            Clock.schedule_once(lambda dt: setattr(
                self.manager, "current", "done"))

        except Exception as e:
            import traceback
            self.log("ERROR: " + str(e))
            self.log(traceback.format_exc()[-200:])
            Clock.schedule_once(lambda dt: setattr(self.build_btn, "disabled", False))

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
        sm.add_widget(MaskScreen(name="mask"))
        sm.add_widget(BuildScreen(name="build"))
        sm.add_widget(DoneScreen(name="done"))
        return sm

    def on_start(self):
        if ANDROID:
            from jnius import autoclass
            Build = autoclass("android.os.Build$VERSION")
            if Build.SDK_INT >= 30:
                # Android 11+ — request MANAGE_EXTERNAL_STORAGE for writing zip to Downloads
                Environment = autoclass("android.os.Environment")
                Intent       = autoclass("android.content.Intent")
                Settings     = autoclass("android.provider.Settings")
                Uri          = autoclass("android.net.Uri")
                if not Environment.isExternalStorageManager():
                    intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                    pkg = autoclass("org.kivy.android.PythonActivity").mActivity.getPackageName()
                    intent.setData(Uri.parse("package:" + pkg))
                    autoclass("org.kivy.android.PythonActivity").mActivity.startActivity(intent)
            else:
                request_permissions([Permission.READ_EXTERNAL_STORAGE,
                                     Permission.WRITE_EXTERNAL_STORAGE])


if __name__ == "__main__":
    HyperOSIconPacker().run()
