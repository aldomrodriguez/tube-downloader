import os
import sys
import json
import re
import subprocess
import threading
import tkinter.font as tkfont
from pathlib import Path

import customtkinter as ctk

import yt_dlp
import imageio_ffmpeg
from yt_dlp.utils import DownloadCancelled

import updater


# Single source of truth for the version: build.ps1 copies it into the .exe
# metadata, and the updater compares it with the latest GitHub release tag.
APP_VERSION = "1.0.0"
APP_NAME = "TubeDownloader"
_APPDATA = Path(os.environ.get("APPDATA", str(Path.home())))
CONFIG_DIR = _APPDATA / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"
# Where settings lived before the app was renamed; read once so an existing
# install keeps its folder and codec instead of silently starting over.
LEGACY_CONFIG_FILE = _APPDATA / "YouTubeDownloader" / "config.json"

YOUTUBE_URL_RE = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|m\.youtube\.com)/", re.IGNORECASE
)

# Palette — the "Studio" design direction.
BG = "#16171b"
CARD = "#1c1e23"
CARD_BORDER = "#282b33"
TEXT = "#e8eaf0"
TEXT_SOFT = "#c3c9d6"
MUTED = "#9aa2b4"
DIM = "#7d8496"
DIMMER = "#6e7688"
FOOTER = "#5b6273"
CHIP_BG = "#23262d"
CHIP_BORDER = "#2f333c"
OFF_BG = "#1b1d22"
OFF_BORDER = "#26292f"
OFF_TEXT = "#4d5464"
ACCENT = "#7c5cff"
ACCENT_HOVER = "#6a4ae8"
RING_TRACK = "#2a2d35"
ERR_CARD = "#1f1a1c"
ERR_BORDER = "#3d2a2e"
ERR_ICON_BG = "#332226"
ERR_RED = "#f87171"
ERR_TITLE = "#f2b8b8"
ERR_BODY = "#b99a9d"
WARN = "#fbbf24"

FONT_FAMILY = "Segoe UI"


def resource_path(name):
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", "")) / name
        if bundled.exists():
            return str(bundled)
    local = Path(__file__).parent / "assets" / name
    return str(local) if local.exists() else None


def get_ffmpeg_path():
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", "")) / "ffmpeg.exe"
        if bundled.exists():
            return str(bundled)
    return imageio_ffmpeg.get_ffmpeg_exe()


def setup_font():
    """Register the bundled display face, falling back to the system UI font.

    The variable TTF never shows up in Tk's family enumeration on Windows, but Tk
    still resolves it when asked for by name — so probe by name and compare what
    actually came back rather than trusting the load call.
    """
    global FONT_FAMILY
    path = resource_path("SpaceGrotesk.ttf")
    if not path:
        return
    try:
        ctk.FontManager.load_font(path)
        probe = tkfont.Font(family="Space Grotesk", size=14)
        if probe.actual()["family"].lower().startswith("space grotesk"):
            FONT_FAMILY = "Space Grotesk"
    except Exception:
        pass


def font(size, weight="normal"):
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


# Encoders are probed once with a 1-frame test encode, cheapest reliable way to
# know whether this machine's GPU can actually encode (having the hardware isn't
# enough — drivers, laptop GPU switching and busy sessions all make it fail).
_ENCODER_CACHE = {}

# Quality targets land around 4x the bitrate of a typical YouTube source, which is
# far more headroom than needed to stay visually identical to it. Pushing higher
# only inflates file size — it costs no extra time, since decoding (not encoding)
# is what limits throughput here.
# HEVC keeps more detail per bit than H.264, so it is given a slightly higher CQ
# to land at comparable quality with a smaller file. The hvc1 tag is what makes
# HEVC open in Premiere and QuickTime instead of being ignored.
GPU_ENCODERS = {
    "h264": [
        ("NVIDIA", ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq",
                    "-rc", "vbr", "-cq", "23", "-b:v", "0", "-profile:v", "high"]),
        ("Intel", ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "23"]),
        ("AMD", ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp",
                 "-qp_i", "23", "-qp_p", "23"]),
    ],
    "h265": [
        ("NVIDIA", ["-c:v", "hevc_nvenc", "-preset", "p4", "-tune", "hq",
                    "-rc", "vbr", "-cq", "25", "-b:v", "0", "-tag:v", "hvc1"]),
        ("Intel", ["-c:v", "hevc_qsv", "-preset", "medium", "-global_quality", "25",
                   "-tag:v", "hvc1"]),
        ("AMD", ["-c:v", "hevc_amf", "-quality", "quality", "-rc", "cqp",
                 "-qp_i", "25", "-qp_p", "25", "-tag:v", "hvc1"]),
    ],
}

CPU_ENCODERS = {
    "h264": ("CPU", ["-c:v", "libx264", "-preset", "fast", "-crf", "20"]),
    "h265": ("CPU", ["-c:v", "libx265", "-preset", "fast", "-crf", "23",
                     "-tag:v", "hvc1"]),
}

CODEC_NAMES = {"h264": "H.264", "h265": "H.265"}

NVENC_MAX_DIM = 4096


def detect_encoder(ffmpeg_path, codec="h264"):
    """Return (label, ffmpeg video options) for the fastest usable encoder."""
    if codec in _ENCODER_CACHE:
        return _ENCODER_CACHE[codec]

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for label, opts in GPU_ENCODERS[codec]:
        cmd = [
            ffmpeg_path, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=1",
            "-frames:v", "1", *opts, "-pix_fmt", "yuv420p", "-f", "null", "-",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=30,
                                    creationflags=creationflags)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            _ENCODER_CACHE[codec] = (label, opts)
            return _ENCODER_CACHE[codec]

    _ENCODER_CACHE[codec] = CPU_ENCODERS[codec]
    return _ENCODER_CACHE[codec]


def load_config():
    """Return (folder, codec), falling back to Downloads and H.264."""
    data = {}
    for path in (CONFIG_FILE, LEGACY_CONFIG_FILE):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            break
        except (OSError, json.JSONDecodeError):
            continue
    folder = data.get("last_folder")
    if not folder or not Path(folder).is_dir():
        folder = str(Path.home() / "Downloads")
    codec = data.get("codec")
    if codec not in GPU_ENCODERS:
        codec = "h264"
    return folder, codec


def save_config(folder, codec):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_folder": folder, "codec": codec}, f)
    except OSError:
        pass


def format_speed(speed):
    if not speed:
        return ""
    return f"{speed / 1024 / 1024:.1f} MB/s".replace(".", ",")


def format_eta(eta):
    if eta is None:
        return ""
    m, s = divmod(int(eta), 60)
    return f"{m:02d}:{s:02d}"


def format_size(num):
    if not num:
        return ""
    mb = num / 1024 / 1024
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB".replace(".", ",")
    return f"{mb:.0f} MB"


def rounded_rect(canvas, x1, y1, x2, y2, r, fill):
    canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill)
    canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill)
    for cx, cy in ((x1, y1), (x2 - 2 * r, y1), (x1, y2 - 2 * r), (x2 - 2 * r, y2 - 2 * r)):
        canvas.create_oval(cx, cy, cx + 2 * r, cy + 2 * r, fill=fill, outline=fill)


class Ring(ctk.CTkCanvas):
    """Circular progress indicator that eases toward its target value.

    The progress arc is deleted and redrawn every frame instead of being updated
    in place: reusing one arc item left visible remnants of the previous, larger
    sweep when the value dropped sharply (download finishing near 100%, then the
    conversion restarting at 0). Redrawing also keeps the motion continuous, so
    progress that only arrives once a second still reads as movement.
    """

    STEP_MS = 16
    EASE = 0.18

    def __init__(self, master, size=92, thickness=7, bg=CARD):
        super().__init__(master, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0)
        pad = thickness / 2 + 1
        self._box = (pad, pad, size - pad, size - pad)
        self._thickness = thickness
        self._size = size
        self._value = 0.0
        self._target = 0.0
        self._anim = None
        self._draw()

    def _draw(self):
        self.delete("ring")
        self.create_arc(*self._box, start=0, extent=359.99, style="arc",
                        outline=RING_TRACK, width=self._thickness, tags="ring")
        if self._value > 0.05:
            self.create_arc(*self._box, start=90,
                            extent=-359.99 * self._value / 100, style="arc",
                            outline=ACCENT, width=self._thickness, tags="ring")
        self.create_text(self._size / 2, self._size / 2,
                         text=f"{self._value:.0f}%", fill=TEXT,
                         font=(FONT_FAMILY, 15, "bold"), tags="ring")

    def set(self, percent):
        self._target = max(0.0, min(100.0, percent))
        # A big drop means a new phase started, not progress running backwards —
        # snap instead of sweeping the whole circle in reverse.
        if self._target < self._value - 20:
            self.reset(self._target)
            return
        if self._anim is None:
            self._tick()

    def reset(self, value=0.0):
        self._cancel()
        self._value = self._target = max(0.0, min(100.0, value))
        self._draw()

    def _tick(self):
        self._anim = None
        diff = self._target - self._value
        if abs(diff) < 0.2:
            self._value = self._target
            self._draw()
            return
        self._value += diff * self.EASE
        self._draw()
        try:
            self._anim = self.after(self.STEP_MS, self._tick)
        except Exception:
            self._anim = None

    def _cancel(self):
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None

    def destroy(self):
        self._cancel()
        super().destroy()


class DownloaderApp:
    def __init__(self, root):
        self.root = root
        root.title("Tube Downloader")
        # 30px taller than the 460 mock: the working panel (ring + three text
        # lines + chips) is the tallest state and clipped the footer at 460.
        root.geometry("600x490")
        root.resizable(False, False)
        root.configure(fg_color=BG)

        self.output_folder, self.codec = load_config()
        self.is_downloading = False
        self.last_output_dir = None
        self.current_proc = None
        self.cancel_requested = False
        self.encoder_label = "CPU"
        self._chips_key = None
        self._dl_bytes = {}
        self._dl_total = 0
        self._speed_ema = None
        self._convert_chips = []
        self._final_codec = None

        self._build_ui()
        self._center()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center(self):
        self.root.update_idletasks()
        w, h = 600, 490
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ---------------------------------------------------------------- layout

    def _build_ui(self):
        outer = ctk.CTkFrame(self.root, fg_color=BG)
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        self._build_header(outer)
        self._build_link_card(outer)
        self._build_main_card(outer)
        self._build_options(outer)
        self._build_actions(outer)
        self._build_footer(outer)

        self.show_idle()

    def _build_header(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=4)

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left")

        mark = ctk.CTkCanvas(left, width=26, height=26, bg=BG,
                             highlightthickness=0, bd=0)
        mark.pack(side="left")
        rounded_rect(mark, 0, 0, 26, 26, 8, ACCENT)
        mark.create_line(13, 6, 13, 15, fill=BG, width=2, capstyle="round")
        mark.create_line(9, 11, 13, 15, fill=BG, width=2, capstyle="round")
        mark.create_line(17, 11, 13, 15, fill=BG, width=2, capstyle="round")
        mark.create_line(6, 20, 20, 20, fill=BG, width=2, capstyle="round")

        ctk.CTkLabel(left, text="Tube Downloader", font=font(15, "bold"),
                     text_color=TEXT).pack(side="left", padx=(9, 0))

        self.gpu_pill = ctk.CTkFrame(row, fg_color="#1e2026", border_color=RING_TRACK,
                                     border_width=1, corner_radius=999, height=26)
        self.gpu_pill.pack(side="right")
        dot = ctk.CTkCanvas(self.gpu_pill, width=6, height=6, bg="#1e2026",
                            highlightthickness=0, bd=0)
        dot.pack(side="left", padx=(11, 6), pady=6)
        dot.create_oval(0, 0, 6, 6, fill=ACCENT, outline=ACCENT)
        self.gpu_label = ctk.CTkLabel(self.gpu_pill, text="Detectando…",
                                      font=font(11), text_color=MUTED)
        self.gpu_label.pack(side="left", padx=(0, 11))

    def _build_link_card(self, parent):
        self.link_card = ctk.CTkFrame(parent, fg_color=CARD, border_color=CARD_BORDER,
                                      border_width=1, corner_radius=12)
        self.link_card.pack(fill="x", pady=(12, 0))

        inner = ctk.CTkFrame(self.link_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=13)

        ctk.CTkLabel(inner, text="ENLACE", font=font(10, "bold"),
                     text_color=DIMMER).pack(anchor="w")

        self.url_entry = ctk.CTkEntry(
            inner, placeholder_text="Pegá el enlace del video",
            font=font(13), text_color=TEXT_SOFT, placeholder_text_color="#565e70",
            fg_color="transparent", border_width=0, height=24,
        )
        self.url_entry.pack(fill="x", pady=(6, 0))
        self.url_entry.bind("<Return>", lambda e: self._start_download())
        self.url_entry.bind("<FocusIn>", lambda e: self.link_card.configure(border_color=ACCENT))
        self.url_entry.bind("<FocusOut>", lambda e: self.link_card.configure(border_color=CARD_BORDER))

    def _build_main_card(self, parent):
        self.main_card = ctk.CTkFrame(parent, fg_color=CARD, border_color=CARD_BORDER,
                                      border_width=1, corner_radius=12)
        self.main_card.pack(fill="both", expand=True, pady=12)

        # Idle
        self.panel_idle = ctk.CTkFrame(self.main_card, fg_color="transparent")
        idle_icon = ctk.CTkCanvas(self.panel_idle, width=46, height=46, bg=CARD,
                                  highlightthickness=0, bd=0)
        idle_icon.pack()
        idle_icon.create_oval(0, 0, 46, 46, fill=CHIP_BG, outline=CHIP_BG)
        idle_icon.create_line(23, 14, 23, 28, fill=DIMMER, width=2, capstyle="round")
        idle_icon.create_line(17, 22, 23, 28, fill=DIMMER, width=2, capstyle="round")
        idle_icon.create_line(29, 22, 23, 28, fill=DIMMER, width=2, capstyle="round")
        idle_icon.create_line(14, 33, 32, 33, fill=DIMMER, width=2, capstyle="round")
        ctk.CTkLabel(self.panel_idle, text="Listo para descargar",
                     font=font(14, "bold"), text_color=TEXT).pack(pady=(11, 0))
        ctk.CTkLabel(self.panel_idle,
                     text="Baja la mejor calidad disponible y la deja en MP4\nlista para abrir en Premiere Pro.",
                     font=font(12), text_color=DIM, justify="center").pack(pady=(7, 0))

        # Working (download / convert)
        self.panel_work = ctk.CTkFrame(self.main_card, fg_color="transparent")
        self.ring = Ring(self.panel_work)
        self.ring.pack(side="left", padx=(0, 18))
        col = ctk.CTkFrame(self.panel_work, fg_color="transparent")
        col.pack(side="left", fill="both", expand=True)
        self.work_title = ctk.CTkLabel(col, text="", font=font(14, "bold"),
                                       text_color=TEXT, anchor="w", justify="left")
        self.work_title.pack(fill="x")
        self.work_name = ctk.CTkLabel(col, text="", font=font(12), text_color=TEXT_SOFT,
                                      anchor="w", justify="left")
        self.work_name.pack(fill="x", pady=(8, 0))
        self.work_sub = ctk.CTkLabel(col, text="", font=font(12), text_color=DIM,
                                     anchor="w", justify="left")
        self.work_sub.pack(fill="x", pady=(6, 0))
        self.chips_row = ctk.CTkFrame(col, fg_color="transparent")
        self.chips_row.pack(fill="x", pady=(9, 0))

        # Done
        self.panel_done = ctk.CTkFrame(self.main_card, fg_color="transparent")
        check = ctk.CTkCanvas(self.panel_done, width=66, height=66, bg=CARD,
                              highlightthickness=0, bd=0)
        check.pack(side="left", padx=(0, 18))
        check.create_oval(0, 0, 66, 66, fill=ACCENT, outline=ACCENT)
        check.create_line(19, 34, 29, 44, fill=BG, width=4, capstyle="round")
        check.create_line(29, 44, 47, 23, fill=BG, width=4, capstyle="round")
        dcol = ctk.CTkFrame(self.panel_done, fg_color="transparent")
        dcol.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(dcol, text="Descarga completa", font=font(15, "bold"),
                     text_color=TEXT, anchor="w").pack(fill="x")
        self.done_name = ctk.CTkLabel(dcol, text="", font=font(12), text_color=TEXT_SOFT,
                                      anchor="w", justify="left")
        self.done_name.pack(fill="x", pady=(8, 0))
        self.done_chips = ctk.CTkFrame(dcol, fg_color="transparent")
        self.done_chips.pack(fill="x", pady=(9, 0))

        # Error
        self.panel_error = ctk.CTkFrame(self.main_card, fg_color="transparent")
        eicon = ctk.CTkCanvas(self.panel_error, width=46, height=46, bg=ERR_CARD,
                              highlightthickness=0, bd=0)
        eicon.pack(side="left", padx=(0, 16))
        eicon.create_oval(0, 0, 46, 46, fill=ERR_ICON_BG, outline=ERR_ICON_BG)
        eicon.create_oval(12, 12, 34, 34, outline=ERR_RED, width=2)
        eicon.create_line(23, 17, 23, 25, fill=ERR_RED, width=2, capstyle="round")
        eicon.create_line(23, 29, 23, 29, fill=ERR_RED, width=2, capstyle="round")
        ecol = ctk.CTkFrame(self.panel_error, fg_color="transparent")
        ecol.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(ecol, text="No se pudo completar la descarga",
                     font=font(14, "bold"), text_color=ERR_TITLE, anchor="w").pack(fill="x")
        self.error_body = ctk.CTkLabel(ecol, text="", font=font(12), text_color=ERR_BODY,
                                       anchor="w", justify="left", wraplength=380)
        self.error_body.pack(fill="x", pady=(7, 0))

    def _build_options(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=4)

        folder_btn = ctk.CTkFrame(row, fg_color="transparent", cursor="hand2")
        folder_btn.pack(side="left")
        ficon = ctk.CTkCanvas(folder_btn, width=15, height=14, bg=BG,
                              highlightthickness=0, bd=0)
        ficon.pack(side="left")
        ficon.create_line(1, 12, 1, 4, fill=DIMMER, width=1.5)
        ficon.create_line(1, 4, 6, 4, fill=DIMMER, width=1.5)
        ficon.create_line(6, 4, 7, 6, fill=DIMMER, width=1.5)
        ficon.create_line(7, 6, 14, 6, fill=DIMMER, width=1.5)
        ficon.create_line(14, 6, 14, 12, fill=DIMMER, width=1.5)
        ficon.create_line(1, 12, 14, 12, fill=DIMMER, width=1.5)
        self.folder_label = ctk.CTkLabel(folder_btn, text=self._short_path(),
                                         font=font(12), text_color=MUTED, cursor="hand2")
        self.folder_label.pack(side="left", padx=(8, 0))
        for w in (folder_btn, ficon, self.folder_label):
            w.bind("<Button-1>", lambda e: self._choose_folder())
        self.folder_label.bind("<Enter>", lambda e: self.folder_label.configure(text_color=TEXT))
        self.folder_label.bind("<Leave>", lambda e: self.folder_label.configure(text_color=MUTED))

        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right")

        seg = ctk.CTkFrame(right, fg_color=OFF_BG, corner_radius=8,
                           border_color=OFF_BORDER, border_width=1)
        seg.pack(side="left", padx=(0, 16))
        self.codec_btns = {}
        for key in ("h264", "h265"):
            b = ctk.CTkButton(
                seg, text=CODEC_NAMES[key], font=font(11), width=50, height=21,
                corner_radius=6, fg_color="transparent", hover_color=CHIP_BG,
                text_color=DIM, command=lambda k=key: self._set_codec(k),
            )
            b.pack(side="left", padx=2, pady=2)
            self.codec_btns[key] = b
        self._paint_codec()

        self.playlist_switch = ctk.CTkSwitch(
            right, text="Playlist", font=font(12), text_color=MUTED,
            progress_color=ACCENT, fg_color=RING_TRACK, button_color=DIMMER,
            button_hover_color=MUTED, switch_width=30, switch_height=17,
        )
        self.playlist_switch.pack(side="left")

    def _build_actions(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(12, 0))

        self.primary_btn = ctk.CTkButton(
            row, text="Descargar", font=font(14, "bold"), height=44, corner_radius=10,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=BG,
            command=self._on_primary,
        )
        self.primary_btn.pack(side="left", fill="x", expand=True)

        self.secondary_btn = ctk.CTkButton(
            row, text="Abrir carpeta", font=font(14), height=44, width=140,
            corner_radius=10, fg_color=CHIP_BG, hover_color="#2b2f38",
            border_color=CHIP_BORDER, border_width=1, text_color=TEXT_SOFT,
            command=self._open_folder,
        )
        self.secondary_btn.pack(side="left", padx=(9, 0))

    def _build_footer(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=(12, 0))
        ctk.CTkLabel(row, text=f"Desarrollado por Aldo Rodriguez · v{APP_VERSION}",
                     font=font(11),
                     text_color=FOOTER).pack(side="left")
        link = ctk.CTkLabel(row, text="aldorodriguez.com.ar", font=font(11),
                            text_color=DIM, cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: self._open_site())
        link.bind("<Enter>", lambda e: link.configure(text_color=TEXT))
        link.bind("<Leave>", lambda e: link.configure(text_color=DIM))

    # ----------------------------------------------------------- ui helpers

    def _short_path(self, limit=24):
        p = self.output_folder
        return p if len(p) <= limit else "…" + p[-(limit - 1):]

    def _open_site(self):
        import webbrowser
        webbrowser.open("https://aldorodriguez.com.ar")

    def _hide_panels(self):
        for p in (self.panel_idle, self.panel_work, self.panel_done, self.panel_error):
            p.pack_forget()

    def _set_chips(self, container, values):
        for w in container.winfo_children():
            w.destroy()
        for v in values:
            if not v:
                continue
            chip = ctk.CTkFrame(container, fg_color=CHIP_BG, corner_radius=6)
            chip.pack(side="left", padx=(0, 6))
            ctk.CTkLabel(chip, text=v, font=font(11), text_color=MUTED).pack(
                padx=8, pady=3)

    def show_idle(self):
        self._hide_panels()
        self.main_card.configure(fg_color=CARD, border_color=CARD_BORDER)
        self.panel_idle.pack(expand=True)
        self.primary_btn.configure(text="Descargar", state="normal", fg_color=ACCENT,
                                   hover_color=ACCENT_HOVER, text_color=BG)
        self._set_secondary(enabled=bool(self.last_output_dir))

    def show_working(self, title, name="", sub="", chips=(), percent=0.0):
        if not self.panel_work.winfo_ismapped():
            self._hide_panels()
            self.main_card.configure(fg_color=CARD, border_color=CARD_BORDER)
            self.panel_work.pack(fill="both", expand=True, padx=16, pady=16)
        self.ring.set(percent)
        self.work_title.configure(text=title)
        self.work_name.configure(text=name)
        self.work_sub.configure(text=sub)
        key = tuple(chips)
        if key != self._chips_key:
            self._set_chips(self.chips_row, chips)
            self._chips_key = key

    def show_done(self, name, chips):
        self._hide_panels()
        self._chips_key = None
        self.main_card.configure(fg_color=CARD, border_color=CARD_BORDER)
        self.panel_done.pack(fill="both", expand=True, padx=16, pady=16)
        self.done_name.configure(text=name)
        self._set_chips(self.done_chips, chips)
        self.primary_btn.configure(text="Descargar otro", state="normal",
                                   fg_color=CHIP_BG, hover_color="#2b2f38",
                                   text_color=TEXT_SOFT)
        self._set_secondary(enabled=True, primary_look=True)

    def show_error(self, message):
        self._hide_panels()
        self._chips_key = None
        self.main_card.configure(fg_color=ERR_CARD, border_color=ERR_BORDER)
        self.panel_error.pack(fill="both", expand=True, padx=16, pady=16)
        self.error_body.configure(text=message)
        self.primary_btn.configure(text="Reintentar", state="normal", fg_color=ACCENT,
                                   hover_color=ACCENT_HOVER, text_color=BG)
        self._set_secondary(enabled=bool(self.last_output_dir))

    def _set_secondary(self, enabled, primary_look=False):
        self.secondary_btn.configure(text="Abrir carpeta", command=self._open_folder,
                                     border_width=1)
        if primary_look:
            self.secondary_btn.configure(state="normal", fg_color=ACCENT,
                                         hover_color=ACCENT_HOVER, text_color=BG,
                                         border_color=ACCENT)
        elif enabled:
            self.secondary_btn.configure(state="normal", fg_color=CHIP_BG,
                                         hover_color="#2b2f38", text_color=TEXT_SOFT,
                                         border_color=CHIP_BORDER)
        else:
            self.secondary_btn.configure(state="disabled", fg_color=OFF_BG,
                                         text_color=OFF_TEXT, border_color=OFF_BORDER)

    def _lock_actions(self, label):
        """Disable the primary action and turn the second slot into Detener."""
        self.primary_btn.configure(text=label, state="disabled", fg_color=OFF_BG,
                                   text_color=OFF_TEXT)
        self.secondary_btn.configure(
            text="Detener", state="normal", command=self._stop,
            fg_color="transparent", hover_color="#2a1f22",
            border_color="#4a3236", border_width=1, text_color="#f28b8b",
        )

    def _stop(self):
        if not self.is_downloading:
            return
        self.cancel_requested = True
        # Same teardown the close dialog performs: killing ffmpeg is what actually
        # releases the half-written file, since it is a separate OS process.
        if self.current_proc and self.current_proc.poll() is None:
            try:
                self.current_proc.kill()
            except OSError:
                pass
        self.secondary_btn.configure(text="Deteniendo…", state="disabled",
                                     fg_color=OFF_BG, text_color=OFF_TEXT,
                                     border_color=OFF_BORDER)

    def set_encoder_pill(self, text):
        self.gpu_label.configure(text=text)

    # -------------------------------------------------------------- actions

    def _on_primary(self):
        if self.is_downloading:
            return
        self._start_download()

    def _paint_codec(self):
        for key, btn in self.codec_btns.items():
            if key == self.codec:
                btn.configure(fg_color=ACCENT, text_color=BG, hover_color=ACCENT_HOVER)
            else:
                btn.configure(fg_color="transparent", text_color=DIM,
                              hover_color=CHIP_BG)

    def _set_codec(self, key):
        if self.is_downloading or key == self.codec:
            return
        self.codec = key
        self._paint_codec()
        save_config(self.output_folder, self.codec)

    def _choose_folder(self):
        if self.is_downloading:
            return
        from tkinter import filedialog
        folder = filedialog.askdirectory(initialdir=self.output_folder or str(Path.home()))
        if folder:
            self.output_folder = folder
            self.folder_label.configure(text=self._short_path())

    def _open_folder(self):
        target = self.last_output_dir or self.output_folder
        if target and Path(target).is_dir():
            os.startfile(target)

    def _start_download(self):
        if self.is_downloading:
            return

        url = self.url_entry.get().strip()
        if not url:
            self.show_error("Pegá primero el enlace del video que querés descargar.")
            return
        if not YOUTUBE_URL_RE.match(url):
            if not self._ask("Enlace no reconocido",
                             "No parece un enlace de YouTube. ¿Querés intentarlo igual?",
                             "Intentar", "Cancelar"):
                return

        folder = self.output_folder or str(Path.home() / "Downloads")
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.show_error(f"No se pudo usar la carpeta de destino: {e}")
            return

        save_config(folder, self.codec)

        self.is_downloading = True
        self.cancel_requested = False
        self._chips_key = None
        self._final_codec = None
        self._lock_actions("Descargando…")
        self.ring.reset(0)
        self.show_working("Conectando con YouTube", percent=0)

        download_playlist = bool(self.playlist_switch.get())
        thread = threading.Thread(
            target=self._download_worker, args=(url, folder, download_playlist), daemon=True
        )
        thread.start()

    # ---------------------------------------------------------------- logic

    def _download_worker(self, url, folder, download_playlist):
        try:
            ffmpeg_path = get_ffmpeg_path()

            if download_playlist:
                outtmpl = os.path.join(folder, "%(playlist_title)s", "%(title)s.%(ext)s")
            else:
                outtmpl = os.path.join(folder, "%(title)s.%(ext)s")

            # Resolution is sorted first so quality is never sacrificed, but among
            # formats of the *same* resolution H.264/AAC wins. That way the common case
            # (YouTube already serves H.264 at the video's max size) needs no transcode
            # at all, and only genuinely VP9/AV1-only sizes (1440p/4K) pay for one.
            ydl_opts = {
                "format": "bv*+ba/b",
                "format_sort": ["res", "fps", "vcodec:h264", "acodec:aac"],
                "merge_output_format": "mp4",
                "outtmpl": outtmpl,
                "ffmpeg_location": ffmpeg_path,
                "noplaylist": not download_playlist,
                "ignoreerrors": download_playlist,
                "progress_hooks": [self._progress_hook],
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
            }

            # yt-dlp fetches the video and audio streams as two separate files,
            # each reporting its own 0-100% and its own ETA. Summing the expected
            # sizes up front lets the hook report one honest overall figure
            # instead of a bar that fills, resets and fills again.
            self._dl_bytes = {}
            self._dl_total = 0
            self._speed_ema = None
            if not download_playlist:
                self.root.after(0, lambda: self.show_working(
                    "Consultando el video", "Leyendo las calidades disponibles…", "", (), 0))
                try:
                    probe_opts = dict(ydl_opts, skip_download=True, progress_hooks=[])
                    with yt_dlp.YoutubeDL(probe_opts) as probe:
                        pre = probe.extract_info(url, download=False)
                    for f in (pre.get("requested_formats") or [pre]):
                        self._dl_total += f.get("filesize") or f.get("filesize_approx") or 0
                except Exception:
                    self._dl_total = 0

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

            entries = info.get("entries") if info and "entries" in info else [info]
            summary = None
            for entry in entries:
                if self.cancel_requested:
                    raise DownloadCancelled()
                if entry:
                    self._finalize_to_mp4(ffmpeg_path, entry)
                    if summary is None:
                        summary = self._summarize(entry)

            self.last_output_dir = folder
            self.root.after(0, lambda: self._on_success(summary))
        except DownloadCancelled:
            self.root.after(0, self._on_cancelled)
        except Exception as e:
            self.root.after(0, lambda: self._on_error(str(e)))

    def _summarize(self, entry):
        name = (entry.get("title") or "Video") + ".mp4"
        h = entry.get("height")
        w = entry.get("width")
        res = f"{w}×{h}" if w and h else (f"{h}p" if h else "")
        size = format_size(entry.get("filesize") or entry.get("filesize_approx"))
        codec = getattr(self, "_final_codec", None) or CODEC_NAMES[self.codec]
        return name, [res, f"{codec} · AAC", size]

    def _finalize_to_mp4(self, ffmpeg_path, entry):
        for d in entry.get("requested_downloads") or []:
            if self.cancel_requested:
                raise DownloadCancelled()

            src = d.get("filepath")
            if not src or not os.path.exists(src):
                continue

            vcodec = (d.get("vcodec") or entry.get("vcodec") or "").lower()
            acodec = (d.get("acodec") or entry.get("acodec") or "").lower()
            is_h264 = vcodec.startswith("avc1") or vcodec.startswith("h264")
            is_aac = acodec.startswith("mp4a") or acodec.startswith("aac")
            premiere_ready = is_h264 and is_aac

            # Fast path: YouTube already served H.264/AAC at this video's best
            # resolution, so the file opens in Premiere as-is — no ffmpeg pass at all.
            if premiere_ready and src.lower().endswith(".mp4"):
                self._final_codec = "H.264"
                continue

            base = os.path.splitext(src)[0]
            final_path = base + ".mp4"
            # The download is often already a .mp4, so encoding straight to
            # final_path would make ffmpeg read and write one file ("Output ...
            # same as Input - exiting"). Always build a scratch file and swap it in.
            tmp_path = base + ".converting.mp4"
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

            duration = entry.get("duration") or d.get("duration")
            width = d.get("width") or entry.get("width") or 0
            height = d.get("height") or entry.get("height") or 0
            res = f"{width}×{height}" if width and height else ""

            if premiere_ready:
                self.root.after(0, lambda: self.show_working(
                    "Empaquetando a MP4", "Sin recodificar: la calidad queda intacta.",
                    "", [res, "H.264 · AAC"], 0))
                self._final_codec = "H.264"
                cmd = [ffmpeg_path, "-y", "-i", src, "-c", "copy",
                       "-movflags", "+faststart", tmp_path]
                returncode, stderr = self._run_ffmpeg(cmd)
            else:
                target = CODEC_NAMES[self.codec]
                self._convert_chips = [
                    res,
                    f"{vcodec.split('.')[0].upper()} → {target}",
                    "MP4 · AAC",
                ]
                returncode, stderr = self._transcode(
                    ffmpeg_path, src, tmp_path, duration, width, height
                )

            if returncode != 0:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                if self.cancel_requested:
                    raise DownloadCancelled()
                raise RuntimeError(f"ffmpeg no pudo generar el mp4 final:\n{stderr[-800:]}")

            os.replace(tmp_path, final_path)
            if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(final_path):
                os.remove(src)

    def _transcode(self, ffmpeg_path, src, dst, duration, width=0, height=0):
        """Re-encode to the chosen codec, preferring the GPU, falling back to CPU."""
        codec = self.codec
        cpu_label, cpu_opts = CPU_ENCODERS[codec]

        # NVENC's H.264 engine tops out at 4096px per side (measured: 4096 encodes,
        # 4097 reports "exceeds 4096 / No capable devices") while its HEVC engine
        # reaches 8192 — so an oversized video gets HEVC on the GPU rather than
        # crawling through libx264, whatever the user picked.
        if codec == "h264" and max(width, height) > NVENC_MAX_DIM:
            alt_label, alt_opts = detect_encoder(ffmpeg_path, "h265")
            if alt_label != "CPU":
                codec, cpu_label, cpu_opts = "h265", *CPU_ENCODERS["h265"]
                label, video_opts = alt_label, alt_opts
            else:
                label, video_opts = cpu_label, cpu_opts
        else:
            label, video_opts = detect_encoder(ffmpeg_path, codec)

        pill = f"{label} · {CODEC_NAMES[codec]}"
        self.encoder_label = label
        self._final_codec = CODEC_NAMES[codec]
        self.root.after(0, lambda p=pill: self.set_encoder_pill(p))
        returncode, stderr = self._run_ffmpeg(
            self._build_transcode(ffmpeg_path, src, dst, video_opts), duration=duration
        )

        # A GPU encode can still fail situationally (all NVENC sessions busy, driver
        # hiccup), so retry once on the CPU rather than failing the whole download.
        if returncode != 0 and not self.cancel_requested and video_opts is not cpu_opts:
            gpu_error = stderr
            self.encoder_label = cpu_label
            self.root.after(0, lambda c=codec: self.set_encoder_pill(
                f"CPU · {CODEC_NAMES[c]}"))
            returncode, stderr = self._run_ffmpeg(
                self._build_transcode(ffmpeg_path, src, dst, cpu_opts), duration=duration
            )
            if returncode != 0:
                stderr = f"[GPU {label}]\n{gpu_error[-600:]}\n\n[CPU]\n{stderr}"

        return returncode, stderr

    def _build_transcode(self, ffmpeg_path, src, dst, video_opts):
        return [
            ffmpeg_path, "-y", "-i", src,
            *video_opts, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "320k",
            "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats",
            dst,
        ]

    def _run_ffmpeg(self, cmd, duration=None):
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        self.current_proc = proc

        stderr_lines = []
        stderr_thread = threading.Thread(target=lambda: stderr_lines.extend(proc.stderr), daemon=True)
        stderr_thread.start()

        if duration:
            chips = getattr(self, "_convert_chips", [])
            target_name = CODEC_NAMES[self.codec]
            for line in proc.stdout:
                line = line.strip()
                if not line.startswith("out_time="):
                    continue
                try:
                    h, m, s = line.split("=", 1)[1].split(":")
                    out_time_s = int(h) * 3600 + int(m) * 60 + float(s)
                    percent = min(out_time_s / duration, 1.0) * 100
                except (ValueError, ZeroDivisionError):
                    continue
                label = self.encoder_label
                self.root.after(0, lambda p=percent, lb=label, c=chips,
                                tgt=target_name: self.show_working(
                    "Convirtiendo para Premiere Pro",
                    f"Codificando a {tgt} con {'la placa de video' if lb != 'CPU' else 'el procesador'},\npara que abra sin recodificar.",
                    "", c, p))

        proc.wait()
        stderr_thread.join(timeout=2)
        self.current_proc = None
        return proc.returncode, "".join(stderr_lines)

    def _progress_hook(self, d):
        if self.cancel_requested:
            raise DownloadCancelled()

        status = d.get("status")
        if status == "downloading":
            self._dl_bytes[d.get("filename") or ""] = d.get("downloaded_bytes") or 0
            done = sum(self._dl_bytes.values())
            total = self._dl_total
            if not total:
                # Playlist, or the pre-flight size lookup failed: fall back to
                # this single stream's own numbers.
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0

            percent = (done / total * 100) if total else 0

            # Raw per-chunk speed swings wildly; ease it so the readout and the
            # ETA derived from it stay legible.
            raw = d.get("speed")
            if raw:
                self._speed_ema = raw if self._speed_ema is None \
                    else self._speed_ema * 0.75 + raw * 0.25

            speed_str = format_speed(self._speed_ema)
            eta_str = ""
            if self._speed_ema and total and done < total:
                eta_str = format_eta((total - done) / self._speed_ema)
            info = d.get("info_dict") or {}
            title = info.get("title", "")
            h, w = info.get("height"), info.get("width")
            vcodec = (info.get("vcodec") or "").split(".")[0].upper()
            acodec = (info.get("acodec") or "").split(".")[0].upper()

            idx = info.get("playlist_index")
            count = info.get("n_entries") or info.get("playlist_count")
            heading = "Descargando video"
            if idx and count:
                heading = f"Descargando {idx} de {count}"

            sub = " · ".join(x for x in (speed_str, f"faltan {eta_str}" if eta_str else "") if x)
            chips = [
                f"{w}×{h}" if w and h else "",
                " · ".join(x for x in (vcodec, acodec) if x and x != "NONE"),
                format_size(total),
            ]
            self.root.after(0, lambda: self.show_working(heading, title, sub, chips, percent))
        elif status == "finished":
            # Fires once per stream. After the video stream there is still audio
            # to fetch, so only announce the merge when everything is in.
            done = sum(self._dl_bytes.values())
            if self._dl_total and done < self._dl_total * 0.97:
                return
            self.root.after(0, lambda: self.show_working(
                "Uniendo video y audio", "Casi listo…", "", (), 100))

    # --------------------------------------------------------------- states

    def _on_success(self, summary):
        self.is_downloading = False
        if summary:
            name, chips = summary
        else:
            name, chips = "Listo", []
        self.show_done(name, chips)

    def _on_error(self, error_msg):
        self.is_downloading = False
        self.show_error(self._humanize(error_msg))

    def _on_cancelled(self):
        self.is_downloading = False
        self.show_idle()

    def _humanize(self, msg):
        low = msg.lower()
        if "private" in low or "sign in" in low:
            return "El video es privado o pide iniciar sesión. Probá con otro enlace."
        if "unavailable" in low or "removed" in low or "not available" in low:
            return "El video no está disponible o fue eliminado."
        if "urlopen" in low or "getaddrinfo" in low or "connection" in low or "network" in low:
            return "No hay conexión con YouTube. Revisá tu internet y reintentá."
        if "no space" in low or "espacio" in low:
            return "No queda espacio en el disco de destino."
        if "is not a valid url" in low or "unsupported url" in low:
            return "El enlace no es válido. Copialo de nuevo desde YouTube."
        return msg.strip().splitlines()[0][:220] if msg.strip() else "Error desconocido."

    # ---------------------------------------------------------------- close

    def _ask(self, title, body, ok_text, cancel_text, destructive=False,
             ok_primary=False):
        """Themed modal question. Returns True when the user picks the ok action.

        By default the safe choice (cancel) is the highlighted button; with
        ok_primary the ok action is highlighted and an info icon replaces the
        warning one — for offers like an update rather than a risky action.
        """
        dlg = ctk.CTkToplevel(self.root)
        dlg.title(title)
        dlg.configure(fg_color=BG)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.attributes("-topmost", True)

        card = ctk.CTkFrame(dlg, fg_color=CARD, border_color="#343945",
                            border_width=1, corner_radius=14)
        card.pack(fill="both", expand=True, padx=14, pady=14)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(22, 0))
        icon = ctk.CTkCanvas(head, width=40, height=40, bg=CARD,
                             highlightthickness=0, bd=0)
        icon.pack(side="left")
        if ok_primary:
            icon.create_oval(0, 0, 40, 40, fill="#2a2440", outline="#2a2440")
            icon.create_line(20, 11, 20, 25, fill=ACCENT, width=2, capstyle="round")
            icon.create_line(14, 19, 20, 25, 26, 19, fill=ACCENT, width=2,
                             capstyle="round", joinstyle="round")
            icon.create_line(13, 29, 27, 29, fill=ACCENT, width=2, capstyle="round")
        else:
            icon.create_oval(0, 0, 40, 40, fill="#3a3020", outline="#3a3020")
            icon.create_polygon(20, 10, 31, 29, 9, 29, fill="", outline=WARN, width=2)
            icon.create_line(20, 16, 20, 22, fill=WARN, width=2, capstyle="round")
            icon.create_line(20, 25, 20, 25, fill=WARN, width=2, capstyle="round")
        ctk.CTkLabel(head, text=title, font=font(16, "bold"),
                     text_color=TEXT).pack(side="left", padx=(13, 0))

        ctk.CTkLabel(card, text=body, font=font(13), text_color=MUTED,
                     wraplength=330, justify="left").pack(
            fill="x", padx=22, pady=(15, 0))

        result = {"ok": False}

        def choose(value):
            result["ok"] = value
            dlg.grab_release()
            dlg.destroy()

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=22, pady=(18, 22))
        primary = (ok_text, True) if ok_primary else (cancel_text, False)
        secondary = (cancel_text, False) if ok_primary else (ok_text, True)
        ctk.CTkButton(btns, text=primary[0], font=font(13, "bold"), height=40,
                      corner_radius=10, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color=BG,
                      command=lambda v=primary[1]: choose(v)).pack(fill="x")
        ctk.CTkButton(btns, text=secondary[0], font=font(13), height=40,
                      corner_radius=10, fg_color="transparent",
                      hover_color="#2a1f22" if destructive else "#2b2f38",
                      border_color="#4a3236" if destructive else CHIP_BORDER,
                      border_width=1,
                      text_color="#f28b8b" if destructive else TEXT_SOFT,
                      command=lambda v=secondary[1]: choose(v)).pack(
            fill="x", pady=(8, 0))

        dlg.update_idletasks()
        w, h = 392, dlg.winfo_reqheight()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.protocol("WM_DELETE_WINDOW", lambda: choose(False))
        dlg.grab_set()
        self.root.wait_window(dlg)
        return result["ok"]

    def _on_close(self):
        if not self.is_downloading:
            self.root.destroy()
            return

        if not self._ask(
            "¿Cancelar y cerrar?",
            "Hay una descarga o conversión en curso. Si cerrás ahora se detiene "
            "y el archivo queda incompleto en la carpeta.",
            "Cancelar y cerrar", "Seguir descargando", destructive=True,
        ):
            return

        self.cancel_requested = True
        # Killing the ffmpeg subprocess directly is what actually frees the file
        # handle — otherwise it keeps running (and holding the file locked) after
        # the window closes, since it's a separate OS process, not a Python thread.
        if self.current_proc and self.current_proc.poll() is None:
            try:
                self.current_proc.kill()
            except OSError:
                pass
        self._wait_and_close(attempts=25)

    def _wait_and_close(self, attempts):
        if not self.is_downloading or attempts <= 0:
            self.root.destroy()
            return
        self.root.after(200, lambda: self._wait_and_close(attempts - 1))

    # --------------------------------------------------------------- update

    def check_for_update(self):
        """Ask GitHub for a newer release off the UI thread; silent if offline."""
        if not updater.can_self_update():
            return

        def run():
            info = updater.check_latest(APP_VERSION)
            if info:
                self.root.after(0, lambda: self._offer_update(info))
        threading.Thread(target=run, daemon=True).start()

    def _offer_update(self, info):
        # Never interrupt a download in progress: offer it once it's over.
        if self.is_downloading:
            self.root.after(3000, lambda: self._offer_update(info))
            return

        body = (f"Está disponible la versión {info['version']} (tenés la "
                f"{APP_VERSION}). Se descarga y la aplicación se reinicia sola.")
        notes = info["notes"]
        if notes:
            if len(notes) > 280:
                notes = notes[:280].rstrip() + "…"
            body += "\n\n" + notes
        if self._ask("Hay una actualización", body, "Actualizar ahora", "Más tarde",
                     ok_primary=True):
            self._start_update(info)

    def _start_update(self, info):
        # Reuses the download state: it locks the controls, turns the second
        # button into Detener and makes closing the window ask first.
        self.is_downloading = True
        self.cancel_requested = False
        self._chips_key = None
        self._lock_actions("Actualizando…")
        self.ring.reset(0)
        self.show_working("Descargando actualización",
                          f"Tube Downloader {info['version']}", percent=0)
        threading.Thread(target=self._update_worker, args=(info,), daemon=True).start()

    def _update_worker(self, info):
        name = f"Tube Downloader {info['version']}"

        def progress(done, total):
            sub = f"{format_size(done)} de {format_size(total)}"
            pct = done * 100 / total
            self.root.after(0, lambda: self.show_working(
                "Descargando actualización", name, sub, percent=pct))

        try:
            path = updater.download(info, progress, lambda: self.cancel_requested)
        except InterruptedError:
            self.root.after(0, self._on_cancelled)
            return
        except Exception as e:
            msg = f"No se pudo actualizar: {e}"
            self.root.after(0, lambda: self._on_update_failed(msg))
            return
        self.root.after(0, lambda: self._install_update(path, name))

    def _install_update(self, path, name):
        if self.cancel_requested:
            try:
                os.remove(path)
            except OSError:
                pass
            self._on_cancelled()
            return
        self.show_working("Reiniciando", name, "La aplicación se abre de nuevo sola.",
                          percent=100)
        try:
            updater.install_and_restart(path)
        except OSError as e:
            self._on_update_failed(f"No se pudo instalar la actualización: {e}")
            return
        self.is_downloading = False
        # The swap script waits for this process to exit before replacing the exe.
        self.root.after(400, self.root.destroy)

    def _on_update_failed(self, message):
        self.is_downloading = False
        self.show_error(message + "\nPodés seguir usando esta versión.")


def probe_encoder_async(app):
    """Warm the encoder probe off the UI thread so the pill shows the real device."""
    def run():
        try:
            label, _ = detect_encoder(get_ffmpeg_path())
        except Exception:
            label = "CPU"
        app.root.after(0, lambda: app.set_encoder_pill(label))
    threading.Thread(target=run, daemon=True).start()


def main():
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    setup_font()
    app = DownloaderApp(root)
    probe_encoder_async(app)
    # A short delay so the window is up before a possible update dialog.
    root.after(1500, app.check_for_update)
    root.mainloop()


if __name__ == "__main__":
    main()
