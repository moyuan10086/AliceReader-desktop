import base64
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import re
import shutil
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont
import wave

import requests


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
CONFIG_EXAMPLE_PATH = APP_DIR / "config.example.json"
CACHE_DIR = APP_DIR / "cache"
HISTORY_PATH = APP_DIR / "records.json"
EXTENSION_ASSETS_DIR = APP_DIR.parent / "AliceReader划线朗读插件" / "assets"
MASCOT_READY_PATH = EXTENSION_ASSETS_DIR / "player-mascot-ready.png"
CACHE_DIR.mkdir(exist_ok=True)

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
HOTKEY_ID = 0xA11CE

VK = {"S": 0x53, "C": 0x43}

THEME = {
    "page": "#eef6ff",
    "panel": "#ffffff",
    "panel_soft": "#f0f7ff",
    "panel_hover": "#e3f1ff",
    "line": "#bbd9ff",
    "line_soft": "#dbeaff",
    "brand": "#1c8aff",
    "brand_mid": "#0f7af0",
    "brand_hover": "#0d6ed7",
    "brand_dark": "#0b2a55",
    "brand_glow": "#74b9ff",
    "cyan": "#8ff4ff",
    "cyan_soft": "#e2f8ff",
    "ink": "#172033",
    "muted": "#526071",
    "muted_blue": "#3d5179",
    "white": "#ffffff",
    "danger": "#e34d6a",
    "danger_hover": "#c63d58",
    "danger_soft": "#ffe0e6",
    "success": "#1bb572",
    "warning": "#f5a623",
    "chip": "#eaf3ff",
    "chip_active": "#1c8aff",
    "chip_text": "#0b2a55",
}

MODEL_OPTIONS = ["speech-2.8-turbo", "speech-2.8-hd", "speech-2.6-turbo", "speech-2.6-hd"]

VOICE_OPTIONS = [
    ("英语叙述女声", "English_expressive_narrator"),
    ("英语新闻女声", "English_Graceful_Lady"),
    ("英语青年男声", "English_Trustworth_Man"),
    ("英语活力女声", "English_ReservedYoungWoman"),
    ("英语温柔女声", "English_CalmWoman"),
    ("英语清晰男声", "English_Deep-Voiced"),
    ("中文女声", "Chinese_KindheartedGirl"),
    ("中文男声", "Chinese_Trustworth_Man"),
    ("自定义 Voice ID", "custom"),
]

LANGUAGE_OPTIONS = ["auto", "English", "Chinese", "Chinese,Yue", "Japanese", "Korean", "French", "Spanish", "German"]

EMOTION_OPTIONS = [
    ("自然流畅", "fluent"),
    ("中性", ""),
    ("开心", "happy"),
    ("悲伤", "sad"),
    ("愤怒", "angry"),
    ("害怕", "fearful"),
    ("厌恶", "disgusted"),
    ("惊讶", "surprised"),
]

SPEED_PRESETS = [0.75, 1.0, 1.25, 1.5, 2.0]
SEEK_STEP_MS = 5000
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

DEFAULT_CONFIG = {
    "provider": "minimax",
    "api_key": "",
    "endpoint": "https://api.minimaxi.com/v1/t2a_v2",
    "model": "speech-2.8-turbo",
    "voice_id": "English_expressive_narrator",
    "language_boost": "auto",
    "emotion": "fluent",
    "speed": 1.0,
    "volume": 1.0,
    "pitch": 0,
    "sample_rate": 32000,
    "bitrate": 128000,
    "hotkey": "Ctrl+Shift+S",
    "providers": {
        "minimax": {},
        "doubao": {"model": "seed-tts-2.0", "voice_id": "zh_female_vv_uranus_bigtts", "sample_rate": 24000},
        "alibaba": {"model": "cosyvoice-v3-flash", "voice_id": "longanhuan_v3", "language_hint": "zh", "rate": 1.0, "volume": 50, "pitch": 1.0, "sample_rate": 24000, "format": "wav"},
    },
}

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm", use_last_error=True)


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def load_config():
    if not CONFIG_PATH.exists():
        if CONFIG_EXAMPLE_PATH.exists():
            shutil.copyfile(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
        else:
            save_config(DEFAULT_CONFIG)
        raise RuntimeError(f"请先填写配置文件: {CONFIG_PATH}")

    data = normalize_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    provider = data.get("provider", "minimax")
    active = data["providers"].get(provider, {})
    env_key = os.environ.get("MINIMAX_API_KEY", "") if provider == "minimax" else ""
    data["api_key"] = (env_key or active.get("api_key") or data.get("api_key", "")).strip()
    if not data["api_key"]:
        raise RuntimeError("请在配置面板填写 api_key，或设置 MINIMAX_API_KEY 环境变量。")
    return data


def read_config_without_validation():
    if CONFIG_PATH.exists():
        try:
            return normalize_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def normalize_config(raw):
    data = DEFAULT_CONFIG | (raw or {})
    provider_defaults = DEFAULT_CONFIG["providers"]
    stored_providers = (raw or {}).get("providers") or {}
    data["providers"] = {name: defaults | (stored_providers.get(name) or {}) for name, defaults in provider_defaults.items()}
    legacy_minimax = {key: data[key] for key in ("endpoint", "model", "voice_id", "language_boost", "emotion", "speed", "volume", "pitch", "sample_rate", "bitrate") if key in data}
    data["providers"]["minimax"] = legacy_minimax | data["providers"]["minimax"]
    if data.get("api_key") and not data["providers"]["minimax"].get("api_key"):
        data["providers"]["minimax"]["api_key"] = data["api_key"]
    return data


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def load_records():
    if not HISTORY_PATH.exists():
        return []
    try:
        records = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return records if isinstance(records, list) else []


def save_records(records):
    HISTORY_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def make_title(text):
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return "未命名作文"
    return compact[:36] + ("..." if len(compact) > 36 else "")


def format_time(ms):
    seconds = max(0, int(ms / 1000))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def estimate_duration(text):
    """粗略估算播放时长（秒），基于平均朗读速度 ~3.5 字符/秒。仅在没有真实音频时使用。"""
    if not text:
        return 0
    return max(1, int(len(text) / 3.5))


def wav_duration_seconds(path):
    """读取 WAV 文件头，返回精确时长（秒，浮点）。失败返回 None。"""
    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 1
            return frames / float(rate)
    except Exception:
        return None


# ───────────────────────────── Color helpers ─────────────────────────────
def _hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, int(c))) for c in rgb])


def mix(a, b, t):
    """Linear mix between two hex colors. t in [0,1]."""
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    return _rgb_to_hex((ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t))


# ───────────────────────────── Rounded widgets ─────────────────────────────
def draw_round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    """Draw a rounded rectangle on a Canvas, returns the polygon item id."""
    r = max(0, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
    points = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=36, **kwargs)


class RoundedFrame(tk.Canvas):
    """A pill / rounded-rect container. Children are placed inside via .body."""

    def __init__(self, master, *, bg, fill, border=None, radius=14, parent_bg=None, **kwargs):
        super().__init__(
            master,
            bg=parent_bg or bg,
            highlightthickness=0,
            bd=0,
            **kwargs,
        )
        self._fill = fill
        self._border = border or fill
        self._radius = radius
        self._shape = None
        self.body = tk.Frame(self, bg=fill, highlightthickness=0, bd=0)
        self.bind("<Configure>", self._redraw)

    def _redraw(self, event=None):
        self.delete("all")
        w = self.winfo_width() if event is None else event.width
        h = self.winfo_height() if event is None else event.height
        if w < 2 or h < 2:
            return
        # Draw shadow (subtle)
        shadow = mix(self._fill, "#000000", 0.06)
        draw_round_rect(self, 0, 2, w, h, self._radius, fill=shadow, outline=shadow)
        # Main shape
        draw_round_rect(self, 0, 0, w - 1, h - 2, self._radius, fill=self._fill, outline=self._border, width=1)
        # Inset body
        pad = max(self._radius // 3, 6)
        self.create_window(pad, pad, anchor="nw", window=self.body, width=w - pad * 2, height=h - pad * 2 - 2)

    def set_fill(self, color):
        self._fill = color
        self.body.configure(bg=color)
        self._redraw()


class RoundedButton(tk.Canvas):
    """Pill-shaped button with hover / pressed states drawn on a Canvas."""

    def __init__(
        self,
        master,
        text="",
        command=None,
        *,
        bg,                # parent background (so canvas blends)
        fill,              # button fill at rest
        hover=None,        # hover fill
        pressed=None,      # pressed fill
        fg=None,
        font=("Microsoft YaHei UI", 9),
        radius=12,
        padx=18,
        pady=8,
        width=None,
        outline=None,
        outline_hover=None,
        primary=False,
        icon=None,         # leading PhotoImage
    ):
        self._fill = fill
        self._hover = hover or mix(fill, "#000000", 0.08)
        self._pressed = pressed or mix(fill, "#000000", 0.16)
        self._fg = fg or ("#ffffff" if primary else "#172033")
        self._radius = radius
        self._outline = outline or fill
        self._outline_hover = outline_hover or self._hover
        self._command = command
        self._enabled = True
        self._state = "normal"   # normal | hover | pressed | disabled
        self._text = text
        self._font = font
        self._icon = icon
        self._padx = padx
        self._pady = pady

        # Measure desired size
        f = tkfont.Font(font=font)
        text_w = f.measure(text) if text else 0
        text_h = f.metrics("linespace")
        if icon is not None:
            text_w += icon.width() + 8
            text_h = max(text_h, icon.height())
        w = (width or text_w + padx * 2)
        h = text_h + pady * 2

        super().__init__(master, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.configure(cursor="hand2")
        self.bind("<Configure>", lambda _e: self._redraw())

    def _current_fill(self):
        if not self._enabled:
            return mix(self._fill, "#ffffff", 0.45)
        if self._state == "hover":
            return self._hover
        if self._state == "pressed":
            return self._pressed
        return self._fill

    def _current_outline(self):
        if not self._enabled:
            return mix(self._outline, "#ffffff", 0.4)
        if self._state in ("hover", "pressed"):
            return self._outline_hover
        return self._outline

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2:
            return
        fill = self._current_fill()
        outline = self._current_outline()
        # Slightly darker rim at the bottom to fake a soft shadow
        rim = mix(fill, "#000000", 0.10)
        draw_round_rect(self, 0, 1, w - 1, h - 1, self._radius, fill=rim, outline=rim)
        draw_round_rect(self, 0, 0, w - 1, h - 2, self._radius, fill=fill, outline=outline, width=1)

        cx, cy = w // 2, (h - 2) // 2 + 1
        if self._icon is not None:
            f = tkfont.Font(font=self._font)
            text_w = f.measure(self._text)
            total = self._icon.width() + 8 + text_w
            ix = cx - total // 2 + self._icon.width() // 2
            tx = ix + self._icon.width() // 2 + 8 + text_w // 2
            self.create_image(ix, cy, image=self._icon)
            self.create_text(tx, cy, text=self._text, fill=self._fg, font=self._font)
        else:
            self.create_text(cx, cy, text=self._text, fill=self._fg, font=self._font)

    def _on_enter(self, _e):
        if not self._enabled:
            return
        self._state = "hover"
        self._redraw()

    def _on_leave(self, _e):
        if not self._enabled:
            return
        self._state = "normal"
        self._redraw()

    def _on_press(self, _e):
        if not self._enabled:
            return
        self._state = "pressed"
        self._redraw()

    def _on_release(self, _e):
        if not self._enabled:
            return
        was_pressed = self._state == "pressed"
        self._state = "hover"
        self._redraw()
        if was_pressed and self._command:
            self._command()

    # Public API mimicking tk.Button
    def configure(self, **kwargs):
        text = kwargs.pop("text", None)
        if text is not None:
            self._text = text
        textvariable = kwargs.pop("textvariable", None)
        if textvariable is not None:
            self._textvariable = textvariable
            self._text = textvariable.get()
            textvariable.trace_add("write", lambda *_: (setattr(self, "_text", textvariable.get()), self._redraw()))
        state = kwargs.pop("state", None)
        if state is not None:
            self._enabled = state != "disabled"
            self.configure(cursor="hand2" if self._enabled else "arrow")
        if "fill" in kwargs:
            self._fill = kwargs.pop("fill")
        if "fg" in kwargs:
            self._fg = kwargs.pop("fg")
        if kwargs:
            super().configure(**kwargs)
        self._redraw()

    config = configure


class RoundedEntry(tk.Frame):
    """Entry wrapped in a rounded canvas border for a softer look."""

    def __init__(self, master, *, bg, fill, border, focus_border, textvariable=None, font=None, fg="#172033", placeholder=None, radius=10, **entry_kwargs):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0)
        self._fill = fill
        self._border = border
        self._focus_border = focus_border
        self._radius = radius
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, height=32)
        self.canvas.pack(fill="both", expand=True)
        # Search icon
        self._icon_id = None
        self.entry = tk.Entry(
            self.canvas,
            textvariable=textvariable,
            relief="flat",
            bg=fill,
            fg=fg,
            insertbackground=fg,
            highlightthickness=0,
            font=font or ("Microsoft YaHei UI", 9),
            **entry_kwargs,
        )
        self._win = self.canvas.create_window(0, 0, anchor="nw", window=self.entry)
        self.canvas.bind("<Configure>", self._redraw)
        self.entry.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda _e: self._set_focus(False))
        self._focused = False

    def _set_focus(self, focused):
        self._focused = focused
        self._redraw()

    def _redraw(self, event=None):
        self.canvas.delete("all")
        w = self.canvas.winfo_width() if event is None else event.width
        h = self.canvas.winfo_height() if event is None else event.height
        if w < 2 or h < 2:
            return
        border = self._focus_border if self._focused else self._border
        draw_round_rect(self.canvas, 0, 0, w - 1, h - 1, self._radius, fill=self._fill, outline=border, width=1)
        # Inline search glyph
        self.canvas.create_text(14, h // 2, text="🔍", fill="#7286a8", font=("Segoe UI", 10))
        # Place entry inside, with horizontal padding accounting for icon
        left_pad = 28
        right_pad = 10
        self.canvas.coords(self._win, left_pad, h // 2 - 10)
        self.canvas.itemconfigure(self._win, width=w - left_pad - right_pad, height=20)


class RoundedProgress(tk.Canvas):
    """Custom rounded progress + scrub bar — replaces tk.Scale for a softer look."""

    def __init__(
        self,
        master,
        *,
        bg,
        track,
        fill,
        knob,
        knob_outline,
        radius=4,
        height=18,
        on_seek=None,
        on_seek_start=None,
        on_seek_end=None,
    ):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, height=height)
        self._track = track
        self._fill = fill
        self._knob = knob
        self._knob_outline = knob_outline
        self._radius = radius
        self._height = height
        self._fraction = 0.0  # 0..1
        self._on_seek = on_seek
        self._on_seek_start = on_seek_start
        self._on_seek_end = on_seek_end
        self._dragging = False
        self._hover = False
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.configure(cursor="hand2")

    def set_fraction(self, fraction):
        if self._dragging:
            return
        self._fraction = max(0.0, min(1.0, fraction))
        self._redraw()

    def _enter(self, _e):
        self._hover = True
        self._redraw()

    def _leave(self, _e):
        self._hover = False
        self._redraw()

    def _fraction_from_x(self, x):
        w = self.winfo_width()
        margin = 8
        usable = max(1, w - margin * 2)
        return max(0.0, min(1.0, (x - margin) / usable))

    def _press(self, e):
        self._dragging = True
        if self._on_seek_start:
            self._on_seek_start()
        self._fraction = self._fraction_from_x(e.x)
        self._redraw()
        if self._on_seek:
            self._on_seek(self._fraction)

    def _motion(self, e):
        if not self._dragging:
            return
        self._fraction = self._fraction_from_x(e.x)
        self._redraw()
        if self._on_seek:
            self._on_seek(self._fraction)

    def _release(self, _e):
        self._dragging = False
        if self._on_seek_end:
            self._on_seek_end()
        if self._on_seek:
            self._on_seek(self._fraction)

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return
        margin = 8
        track_h = 6
        ty1 = h // 2 - track_h // 2
        ty2 = ty1 + track_h
        # Track
        draw_round_rect(self, margin, ty1, w - margin, ty2, track_h // 2,
                        fill=self._track, outline=self._track)
        # Filled portion
        usable = w - margin * 2
        fx2 = margin + int(usable * self._fraction)
        if fx2 > margin:
            draw_round_rect(self, margin, ty1, fx2, ty2, track_h // 2,
                            fill=self._fill, outline=self._fill)
        # Knob
        knob_r = 8 if (self._hover or self._dragging) else 6
        cx = fx2
        cy = h // 2
        # Soft halo when hovering
        if self._hover or self._dragging:
            self.create_oval(cx - knob_r - 4, cy - knob_r - 4, cx + knob_r + 4, cy + knob_r + 4,
                             fill=mix(self._fill, "#ffffff", 0.7), outline="")
        self.create_oval(cx - knob_r, cy - knob_r, cx + knob_r, cy + knob_r,
                         fill=self._knob, outline=self._knob_outline, width=2)


def mci(command):
    buffer = ctypes.create_unicode_buffer(512)
    error = winmm.mciSendStringW(command, buffer, len(buffer), None)
    if error:
        err = ctypes.create_unicode_buffer(512)
        winmm.mciGetErrorStringW(error, err, len(err))
        raise RuntimeError(err.value or f"MCI error {error}")
    return buffer.value


class MciPlayer:
    def __init__(self):
        self.alias = "alicereader_audio"
        self.opened = False

    def close(self):
        if self.opened:
            try:
                mci(f"close {self.alias}")
            except Exception:
                pass
        self.opened = False

    def open(self, path):
        self.close()
        mci(f'open "{path}" type waveaudio alias {self.alias}')
        mci(f"set {self.alias} time format milliseconds")
        self.opened = True

    def play(self):
        if self.opened:
            mci(f"play {self.alias}")

    def pause(self):
        if self.opened:
            mci(f"pause {self.alias}")

    def resume(self):
        if self.opened:
            mci(f"resume {self.alias}")

    def stop(self):
        if self.opened:
            mci(f"stop {self.alias}")
            mci(f"seek {self.alias} to start")

    def seek_ms(self, ms):
        if self.opened:
            mci(f"seek {self.alias} to {int(ms)}")

    def status(self, key):
        if not self.opened:
            return ""
        try:
            return mci(f"status {self.alias} {key}")
        except Exception:
            return ""

    def position_ms(self):
        value = self.status("position")
        return int(value) if value.isdigit() else 0

    def length_ms(self):
        value = self.status("length")
        return int(value) if value.isdigit() else 0

    def mode(self):
        return self.status("mode")


def hex_to_bytes(hex_audio):
    if re.fullmatch(r"[0-9a-fA-F]+", hex_audio or ""):
        return bytes.fromhex(hex_audio)
    return base64.b64decode(hex_audio)


def synthesize(text, config):
    provider = config.get("provider", "minimax")
    provider_config = (config.get("providers") or {}).get(provider) or {}
    if provider == "doubao":
        return synthesize_doubao(text, config, provider_config)
    if provider == "alibaba":
        return synthesize_alibaba(text, config, provider_config)
    voice_setting = {
        "voice_id": config.get("voice_id", "English_expressive_narrator"),
        "speed": float(config.get("speed", 1.0)),
        "vol": float(config.get("volume", 1.0)),
        "pitch": int(config.get("pitch", 0)),
    }
    if config.get("emotion"):
        voice_setting["emotion"] = config["emotion"]

    payload = {
        "model": config.get("model", "speech-2.8-turbo"),
        "text": text,
        "stream": False,
        "voice_setting": voice_setting,
        "audio_setting": {
            "sample_rate": int(config.get("sample_rate", 32000)),
            "bitrate": int(config.get("bitrate", 128000)),
            "format": "wav",
            "channel": 1,
        },
        "language_boost": config.get("language_boost", "auto"),
        "subtitle_enable": True,
        "subtitle_type": "sentence",
        "output_format": "hex",
    }

    response = requests.post(
        config.get("endpoint", "https://api.minimaxi.com/v1/t2a_v2"),
        headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=120,
    )
    raw = response.text
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(f"MiniMax 返回无法解析: HTTP {response.status_code}") from exc

    if not response.ok:
        raise RuntimeError(data.get("base_resp", {}).get("status_msg") or raw)

    base_resp = data.get("base_resp") or {}
    if base_resp.get("status_code") not in (None, 0):
        raise RuntimeError(base_resp.get("status_msg") or f"MiniMax error {base_resp.get('status_code')}")

    audio_hex = (data.get("data") or {}).get("audio")
    if not audio_hex:
        raise RuntimeError("MiniMax 没有返回 data.audio。")

    output = CACHE_DIR / f"alicereader-{int(time.time())}.wav"
    output.write_bytes(hex_to_bytes(audio_hex))
    return output, data


def synthesize_alibaba(text, config, settings):
    model = settings.get("model", "cosyvoice-v3-flash")
    cosy = model.startswith("cosyvoice-") or model.startswith("qwen-audio-")
    endpoint = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer" if cosy else "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    voice = settings.get("voice_id", "longanhuan_v3" if cosy else "Cherry")
    if cosy and (voice == "Cherry" or not voice):
        voice = "longanhuan_v3"
    body = {"text": text, "voice": voice}
    if cosy:
        body.update({"format": settings.get("format", "wav"), "sample_rate": int(settings.get("sample_rate", 24000)), "rate": float(settings.get("rate", 1.0)), "volume": int(settings.get("volume", 50)), "pitch": float(settings.get("pitch", 1.0))})
        if settings.get("language_hint"): body["language_hints"] = [settings["language_hint"]]
        if settings.get("instruction"): body["instruction"] = settings["instruction"]
    else:
        body["language_type"] = settings.get("language_type", "Chinese")
        if settings.get("instruction") and model == "qwen3-tts-instruct-flash": body.update({"instructions": settings["instruction"], "optimize_instructions": True})
    response = requests.post(endpoint, headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"}, json={"model": model, "input": body}, timeout=120)
    data = response.json()
    if not response.ok or data.get("code") or data.get("status_code", 200) != 200: raise RuntimeError(data.get("message") or f"阿里百炼 HTTP {response.status_code}")
    url = ((data.get("output") or {}).get("audio") or {}).get("url")
    if not url: raise RuntimeError("阿里百炼未返回音频 URL。")
    audio = requests.get(url, timeout=120)
    audio.raise_for_status()
    output = CACHE_DIR / f"alicereader-{int(time.time())}.wav"
    output.write_bytes(audio.content)
    return output, data


def synthesize_doubao(text, config, settings):
    endpoint = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
    model = settings.get("model", "seed-tts-2.0")
    response = requests.post(endpoint, headers={"Content-Type": "application/json", "X-Api-Key": config["api_key"], "X-Api-Resource-Id": model, "X-Api-Request-Id": str(time.time_ns())}, json={"req_params": {"text": text, "speaker": settings.get("voice_id", "zh_female_vv_uranus_bigtts"), "audio_params": {"format": "wav", "sample_rate": int(settings.get("sample_rate", 24000))}}}, timeout=120)
    if not response.ok: raise RuntimeError(f"豆包 TTS HTTP {response.status_code}")
    chunks = []
    for line in response.text.splitlines():
        if line.strip():
            item = json.loads(line)
            if item.get("code", 0) not in (0, 20000000): raise RuntimeError(item.get("message") or f"豆包 TTS 错误 {item.get('code')}")
            if item.get("data"): chunks.append(item["data"])
    if not chunks: raise RuntimeError("豆包 TTS 未返回音频数据。")
    output = CACHE_DIR / f"alicereader-{int(time.time())}.wav"
    output.write_bytes(b"".join(base64.b64decode(chunk) for chunk in chunks))
    return output, {"provider": "doubao", "model": model}


def copy_selected_text(root):
    try:
        old_clipboard = root.clipboard_get()
    except Exception:
        old_clipboard = None

    root.clipboard_clear()
    root.update()

    keyup = 0x0002
    user32.keybd_event(0x11, 0, 0, 0)
    user32.keybd_event(VK["C"], 0, 0, 0)
    user32.keybd_event(VK["C"], 0, keyup, 0)
    user32.keybd_event(0x11, 0, keyup, 0)

    time.sleep(0.15)
    root.update()

    try:
        text = root.clipboard_get()
    except Exception:
        text = ""

    if old_clipboard is not None:
        try:
            root.clipboard_clear()
            root.clipboard_append(old_clipboard)
            root.update()
        except Exception:
            pass

    return (text or "").strip()


class AliceReaderApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AliceReader Desktop")
        self.root.geometry("1020x660+700+220")
        self.root.minsize(820, 520)
        self.root.state("normal")
        self.root.attributes("-topmost", False)
        self.root.attributes("-alpha", 0.985)

        self.events = queue.Queue()
        self.config = None
        self.player = MciPlayer()
        self.audio_path = None
        self.audio_text = ""
        self.is_paused = False
        self.is_seeking = False
        self.is_loading = False
        self.spinner_index = 0
        self.running = True
        self.hotkey_thread_id = None
        self.records = load_records()
        self.filtered_records = list(self.records)
        self.current_record_id = None
        self.mascot_image = None
        self.last_status_kind = "info"

        self.status_var = tk.StringVar(value="可以直接输入作文，或在其他软件选中文字后按 Ctrl+Shift+S")
        self.progress_var = tk.DoubleVar(value=0)
        self.count_var = tk.StringVar(value="0 字符")
        self.time_var = tk.StringVar(value="00:00 / 00:00")
        self.speed_var = tk.StringVar(value="1.0×")
        self.search_var = tk.StringVar(value="")
        self.read_btn_text = tk.StringVar(value="▶  朗读文本")

        self.setup_ttk_style()
        self.build_ui()
        self.bind_shortcuts()
        self.load_config_to_ui()
        self.repair_record_audio_paths()
        self.refresh_history()
        self.start_hotkey_thread()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(80, lambda: self.root.state("normal"))
        self.root.after(160, self.poll_events)
        self.root.after(220, self.update_progress)
        self.root.after(120, self.tick_spinner)

    def setup_ttk_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground=THEME["white"],
            background=THEME["panel_soft"],
            foreground=THEME["brand_dark"],
            bordercolor=THEME["line_soft"],
            arrowcolor=THEME["brand"],
            padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", THEME["white"])],
            selectbackground=[("readonly", THEME["white"])],
            selectforeground=[("readonly", THEME["brand_dark"])],
            bordercolor=[("focus", THEME["brand"])],
        )
        style.configure(
            "Alice.Horizontal.TProgressbar",
            troughcolor=THEME["panel_soft"],
            background=THEME["brand"],
            bordercolor=THEME["panel_soft"],
            lightcolor=THEME["brand"],
            darkcolor=THEME["brand"],
            thickness=6,
        )

    def build_ui(self):
        bg = THEME["page"]
        panel = THEME["panel"]
        ink = THEME["brand_dark"]
        muted = THEME["muted_blue"]
        blue = THEME["brand"]

        self.root.configure(bg=bg)
        shell = tk.Frame(self.root, bg=bg, padx=18, pady=16)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.columnconfigure(1, weight=0)
        shell.rowconfigure(1, weight=1)

        # ── Header ──────────────────────────────────────────────
        header = tk.Frame(shell, bg=bg)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)

        title_group = tk.Frame(header, bg=bg)
        title_group.grid(row=0, column=0, sticky="w")
        self.mascot_image = self.load_mascot_image()
        if self.mascot_image:
            tk.Label(title_group, image=self.mascot_image, bg=bg, bd=0).pack(side="left", padx=(0, 12))
        text_group = tk.Frame(title_group, bg=bg)
        text_group.pack(side="left")
        tk.Label(text_group, text="AliceReader", bg=bg, fg=THEME["brand_mid"], font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        tk.Label(text_group, text="作文朗读本 · 桌面版", bg=bg, fg=muted, font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        chip_pill = RoundedFrame(header, bg=bg, fill=THEME["chip"], border=THEME["line_soft"], radius=14, parent_bg=bg, height=34, width=200)
        chip_pill.grid_propagate(False)
        chip_pill.grid(row=0, column=1, sticky="e")
        chip_pill.body.configure(bg=THEME["chip"])
        tk.Label(chip_pill.body, text="⌨", bg=THEME["chip"], fg=blue, font=("Segoe UI", 11, "bold")).pack(side="left", padx=(2, 6))
        tk.Label(chip_pill.body, text="Ctrl+Shift+S 导入选区", bg=THEME["chip"], fg=THEME["chip_text"], font=("Microsoft YaHei UI", 9)).pack(side="left")

        # ── Editor Panel ────────────────────────────────────────
        editor_wrap = self.make_panel(shell)
        editor_wrap.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        editor_body = editor_wrap.body
        editor_body.configure(bg=panel)
        editor_body.rowconfigure(1, weight=1)
        editor_body.columnconfigure(0, weight=1)

        editor_top = tk.Frame(editor_body, bg=panel)
        editor_top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        editor_top.columnconfigure(1, weight=1)
        tk.Label(editor_top, text="✎  文本", bg=panel, fg=ink, font=("Microsoft YaHei UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(editor_top, textvariable=self.count_var, bg=panel, fg=muted, font=("Microsoft YaHei UI", 9)).grid(row=0, column=2, sticky="e")

        # Editor inside its own rounded sub-card
        editor_card = RoundedFrame(editor_body, bg=panel, fill=THEME["white"], border=THEME["line_soft"], radius=14, parent_bg=panel)
        editor_card.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 4))
        editor_card.body.configure(bg=THEME["white"])
        editor_card.body.rowconfigure(0, weight=1)
        editor_card.body.columnconfigure(0, weight=1)

        self.editor = tk.Text(
            editor_card.body,
            wrap="word",
            undo=True,
            bg=THEME["white"],
            fg=ink,
            insertbackground=blue,
            insertwidth=2,
            selectbackground=THEME["cyan_soft"],
            selectforeground=ink,
            relief="flat",
            padx=14,
            pady=12,
            spacing1=2,
            spacing3=4,
            font=("Segoe UI", 13),
            borderwidth=0,
            highlightthickness=0,
        )
        self.editor.grid(row=0, column=0, sticky="nsew")
        self.editor.bind("<<Modified>>", self.on_text_modified)
        self.editor.bind("<KeyRelease>", lambda _e: self.update_count())

        editor_scroll = tk.Scrollbar(editor_card.body, command=self.editor.yview, bg=THEME["panel_soft"], troughcolor=THEME["white"], relief="flat", bd=0, width=10, activebackground=THEME["brand_glow"])
        editor_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=4)
        self.editor.configure(yscrollcommand=editor_scroll.set)

        # ── History Panel ───────────────────────────────────────
        history_wrap = self.make_panel(shell, width=300)
        history_wrap.grid(row=1, column=1, sticky="ns")
        history_wrap.grid_propagate(False)
        history_body = history_wrap.body
        history_body.configure(bg=panel)
        history_body.rowconfigure(2, weight=1)
        history_body.columnconfigure(0, weight=1)

        history_header = tk.Frame(history_body, bg=panel)
        history_header.grid(row=0, column=0, sticky="ew", pady=(2, 6))
        history_header.columnconfigure(0, weight=1)
        tk.Label(history_header, text="🕮  记录", bg=panel, fg=ink, font=("Microsoft YaHei UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        self.history_count_label = tk.Label(history_header, text=f"{len(self.records)} 条", bg=panel, fg=muted, font=("Microsoft YaHei UI", 9))
        self.history_count_label.grid(row=0, column=1, sticky="e")

        # Search box (rounded)
        search_box = RoundedEntry(
            history_body,
            bg=panel,
            fill=THEME["panel_soft"],
            border=THEME["line_soft"],
            focus_border=THEME["brand_glow"],
            textvariable=self.search_var,
            font=("Microsoft YaHei UI", 9),
            fg=ink,
            radius=12,
        )
        search_box.canvas.configure(height=32)
        search_box.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.search_var.trace_add("write", lambda *_: self.refresh_history())

        # History list inside a rounded white card
        list_card = RoundedFrame(history_body, bg=panel, fill=THEME["white"], border=THEME["line_soft"], radius=12, parent_bg=panel)
        list_card.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        list_card.body.configure(bg=THEME["white"])
        list_card.body.rowconfigure(0, weight=1)
        list_card.body.columnconfigure(0, weight=1)

        self.history_list = tk.Listbox(
            list_card.body,
            bg=THEME["white"],
            fg=ink,
            activestyle="none",
            relief="flat",
            highlightthickness=0,
            selectbackground=THEME["chip_active"],
            selectforeground=THEME["white"],
            font=("Microsoft YaHei UI", 9),
            bd=0,
        )
        self.history_list.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.history_list.bind("<<ListboxSelect>>", self.on_history_select)
        self.history_list.bind("<Double-Button-1>", lambda _event: self.play_selected_record())
        self.history_list.bind("<Return>", lambda _event: self.load_selected_record())
        self.history_list.bind("<Delete>", lambda _event: self.delete_selected_record())

        history_buttons = tk.Frame(history_body, bg=panel)
        history_buttons.grid(row=3, column=0, sticky="ew", pady=(0, 2))
        self.make_button(history_buttons, "打开", self.load_selected_record, kind="ghost", parent_bg=panel).pack(side="left", padx=(0, 6))
        self.make_button(history_buttons, "删除", self.delete_selected_record, kind="danger", parent_bg=panel).pack(side="left", padx=6)
        self.make_button(history_buttons, "导出 TXT", self.export_text, kind="ghost", parent_bg=panel).pack(side="left", padx=6)

        # ── Player Card ─────────────────────────────────────────
        player_card = self.make_panel(shell, radius=20)
        player_card.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        player_body = player_card.body
        player_body.configure(bg=panel)
        player_body.columnconfigure(1, weight=1)

        # Big primary button on the left (extra wide, prominent)
        self.read_btn = RoundedButton(
            player_body,
            text="▶  朗读文本",
            command=self.primary_action,
            bg=panel,
            fill=THEME["brand"],
            hover=THEME["brand_hover"],
            pressed=THEME["brand_dark"],
            fg=THEME["white"],
            font=("Microsoft YaHei UI", 12, "bold"),
            radius=18,
            padx=28,
            pady=14,
            primary=True,
        )
        # bind text variable manually
        self.read_btn._textvariable = self.read_btn_text
        self.read_btn_text.trace_add("write", lambda *_: (setattr(self.read_btn, "_text", self.read_btn_text.get()), self.read_btn._redraw()))
        self.read_btn.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(2, 16), pady=4)

        # Right side: progress + control row
        right_wrap = tk.Frame(player_body, bg=panel)
        right_wrap.grid(row=0, column=1, sticky="nsew")
        right_wrap.columnconfigure(0, weight=1)
        right_wrap.rowconfigure(0, weight=1)
        right_wrap.rowconfigure(1, weight=1)

        # Custom rounded progress bar
        self.progress_bar = RoundedProgress(
            right_wrap,
            bg=panel,
            track=THEME["panel_soft"],
            fill=THEME["brand"],
            knob=THEME["white"],
            knob_outline=THEME["brand"],
            radius=4,
            height=18,
            on_seek=self._on_seek_fraction,
            on_seek_start=lambda: setattr(self, "is_seeking", True),
            on_seek_end=lambda: setattr(self, "is_seeking", False),
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", pady=(2, 4))
        self.time_label = tk.Label(right_wrap, textvariable=self.time_var, bg=panel, fg=muted, font=("Consolas", 10))
        self.time_label.grid(row=0, column=1, sticky="e", padx=(12, 4))

        # Control row
        ctl_row = tk.Frame(right_wrap, bg=panel)
        ctl_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 2))

        self.play_pause_btn = self.make_icon_button(ctl_row, "⏸", self.toggle_play, "播放/暂停 (Space)", parent_bg=panel)
        self.play_pause_btn.pack(side="left", padx=(0, 4))
        self.make_icon_button(ctl_row, "⏹", self.stop, "停止 (Esc)", parent_bg=panel).pack(side="left", padx=4)
        self.make_icon_button(ctl_row, "⏪", lambda: self.skip(-SEEK_STEP_MS), "后退 5s (←)", parent_bg=panel).pack(side="left", padx=4)
        self.make_icon_button(ctl_row, "⏩", lambda: self.skip(SEEK_STEP_MS), "前进 5s (→)", parent_bg=panel).pack(side="left", padx=4)

        # Speed pill (rounded, with label)
        speed_pill = RoundedButton(
            ctl_row,
            text="1.0×",
            command=self.cycle_speed,
            bg=panel,
            fill=THEME["chip"],
            hover=THEME["panel_hover"],
            pressed=mix(THEME["panel_hover"], "#000000", 0.08),
            fg=THEME["brand_dark"],
            outline=THEME["line_soft"],
            outline_hover=THEME["brand_glow"],
            font=("Consolas", 10, "bold"),
            radius=12,
            padx=14,
            pady=7,
        )
        speed_pill._textvariable = self.speed_var
        self.speed_var.trace_add("write", lambda *_: (setattr(speed_pill, "_text", self.speed_var.get()), speed_pill._redraw()))
        speed_pill.pack(side="left", padx=(12, 4))

        # Secondary actions on the right
        sec_wrap = tk.Frame(ctl_row, bg=panel)
        sec_wrap.pack(side="right")
        for label, cmd in [
            ("📥 导入选区", self.import_selection),
            ("💾 保存", self.save_current_record),
            ("✚ 新建", self.new_text),
            ("♫ 导出", self.save_audio),
            ("⚙ 配置", self.open_config),
        ]:
            self.make_button(sec_wrap, label, cmd, kind="ghost", parent_bg=panel).pack(side="left", padx=4)

        # ── Status Bar ──────────────────────────────────────────
        status_bar = tk.Frame(shell, bg=bg)
        status_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        status_bar.columnconfigure(1, weight=1)
        self.status_dot = tk.Label(status_bar, text="●", bg=bg, fg=THEME["success"], font=("Segoe UI", 11))
        self.status_dot.grid(row=0, column=0, padx=(4, 8))
        tk.Label(status_bar, textvariable=self.status_var, bg=bg, fg=muted, anchor="w", font=("Microsoft YaHei UI", 9)).grid(row=0, column=1, sticky="ew")

    def make_panel(self, parent, width=None, height=None, radius=18):
        """Rounded panel container. Use `.body` to add children."""
        kwargs = {}
        if width:
            kwargs["width"] = width
        if height:
            kwargs["height"] = height
        panel = RoundedFrame(
            parent,
            bg=THEME["panel"],
            fill=THEME["panel"],
            border=THEME["line_soft"],
            radius=radius,
            parent_bg=THEME["page"],
            **kwargs,
        )
        return panel

    def load_mascot_image(self):
        if not MASCOT_READY_PATH.exists():
            return None
        try:
            image = tk.PhotoImage(file=str(MASCOT_READY_PATH))
            factor = max(1, image.width() // 64)
            return image.subsample(factor, factor)
        except Exception:
            return None

    def make_button(self, parent, text, command, kind="ghost", width=None, parent_bg=None):
        """kind: primary | ghost | danger"""
        parent_bg = parent_bg or THEME["panel"]
        if kind == "primary":
            return RoundedButton(
                parent, text=text, command=command,
                bg=parent_bg, fill=THEME["brand"], hover=THEME["brand_hover"],
                pressed=THEME["brand_dark"], fg=THEME["white"],
                font=("Microsoft YaHei UI", 9, "bold"), radius=14,
                padx=18, pady=8, width=width, primary=True,
            )
        if kind == "danger":
            return RoundedButton(
                parent, text=text, command=command,
                bg=parent_bg, fill=THEME["white"], hover=THEME["danger_soft"],
                pressed=mix(THEME["danger_soft"], "#000000", 0.1),
                fg=THEME["danger"], outline=THEME["line_soft"],
                outline_hover=THEME["danger"],
                font=("Microsoft YaHei UI", 9), radius=12,
                padx=14, pady=7, width=width,
            )
        # ghost
        return RoundedButton(
            parent, text=text, command=command,
            bg=parent_bg, fill=THEME["white"], hover=THEME["panel_hover"],
            pressed=mix(THEME["panel_hover"], "#000000", 0.08),
            fg=THEME["brand_dark"], outline=THEME["line_soft"],
            outline_hover=THEME["brand_glow"],
            font=("Microsoft YaHei UI", 9), radius=12,
            padx=14, pady=7, width=width,
        )

    def make_icon_button(self, parent, glyph, command, tooltip="", parent_bg=None, size=38):
        parent_bg = parent_bg or THEME["panel"]
        button = RoundedButton(
            parent, text=glyph, command=command,
            bg=parent_bg, fill=THEME["white"], hover=THEME["panel_hover"],
            pressed=mix(THEME["panel_hover"], "#000000", 0.1),
            fg=THEME["brand_dark"], outline=THEME["line_soft"],
            outline_hover=THEME["brand_glow"],
            font=("Segoe UI Symbol", 13), radius=12,
            padx=10, pady=6, width=size,
        )
        if tooltip:
            self._add_tooltip(button, tooltip)
        return button

    def _bind_hover(self, *_args, **_kwargs):
        # Hover is built into RoundedButton; this is now a no-op for backwards compat.
        return

    def _add_tooltip(self, widget, text):
        tooltip = {"win": None}

        def show(_e):
            if tooltip["win"] or not text:
                return
            x = widget.winfo_rootx() + widget.winfo_width() // 2
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x - 60}+{y}")
            tip.attributes("-topmost", True)
            tk.Label(
                tip,
                text=text,
                bg=THEME["brand_dark"],
                fg=THEME["white"],
                font=("Microsoft YaHei UI", 8),
                padx=8,
                pady=3,
            ).pack()
            tooltip["win"] = tip

        def hide(_e):
            if tooltip["win"]:
                tooltip["win"].destroy()
                tooltip["win"] = None

        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")

    def bind_shortcuts(self):
        self.root.bind_all("<F5>", lambda _e: self.read_editor_text())
        self.root.bind_all("<Control-Return>", lambda _e: self.read_editor_text())
        self.root.bind_all("<Control-s>", lambda _e: self._shortcut(self.save_current_record))
        self.root.bind_all("<Control-S>", lambda _e: self._shortcut(self.save_current_record))
        self.root.bind_all("<Control-n>", lambda _e: self._shortcut(self.new_text))
        self.root.bind_all("<Control-N>", lambda _e: self._shortcut(self.new_text))
        self.root.bind_all("<Control-l>", lambda _e: self._shortcut(self.import_selection))
        self.root.bind_all("<Control-L>", lambda _e: self._shortcut(self.import_selection))
        self.root.bind("<Escape>", lambda _e: self.stop())
        # arrows: only when editor not focused
        self.root.bind("<Left>", lambda e: self._maybe_skip(e, -SEEK_STEP_MS))
        self.root.bind("<Right>", lambda e: self._maybe_skip(e, SEEK_STEP_MS))
        self.root.bind("<space>", self._maybe_toggle)

    def _shortcut(self, fn):
        # Suppress default key behavior in editor for these shortcuts
        fn()
        return "break"

    def _maybe_skip(self, event, ms):
        if event.widget is self.editor or isinstance(event.widget, tk.Entry):
            return
        self.skip(ms)

    def _maybe_toggle(self, event):
        if event.widget is self.editor or isinstance(event.widget, tk.Entry):
            return
        self.toggle_play()

    def on_text_modified(self, _event=None):
        if self.editor.edit_modified():
            self.update_count()
            self.editor.edit_modified(False)

    def update_count(self):
        text = self.get_editor_text()
        chars = len(text)
        if chars == 0:
            self.count_var.set("0 字符")
            return

        # Prefer the real audio duration when we have a cached file matching the editor text
        seconds = self._real_duration_for_text(text)
        if seconds is not None:
            label = f"{chars:,} 字符 · {int(seconds) // 60:02d}:{int(seconds) % 60:02d}"
        else:
            est = estimate_duration(text)
            label = f"{chars:,} 字符 · 约 {est // 60:02d}:{est % 60:02d}"
        self.count_var.set(label)

    def _real_duration_for_text(self, text):
        """Return precise WAV duration in seconds if we have a cached audio file
        matching the current text; otherwise None."""
        text = text.strip()

        # 1) Open MCI handle (already loaded — most accurate, in milliseconds)
        if self.player.opened and self.audio_text.strip() == text:
            length = self.player.length_ms()
            if length > 0:
                return length / 1000.0

        # 2) On-disk WAV that matches current text
        if self.audio_path and self.audio_text.strip() == text and Path(self.audio_path).exists():
            secs = wav_duration_seconds(self.audio_path)
            if secs:
                return secs

        # 3) History record with cached audio for this exact text
        for record in self.records:
            if (record.get("text") or "").strip() == text:
                cached = self.record_audio_path(record)
                if cached:
                    secs = wav_duration_seconds(cached)
                    if secs:
                        return secs
                break
        return None

    def set_status(self, message, kind="info"):
        """kind: info | success | error | loading | warning"""
        self.last_status_kind = kind
        self.status_var.set(message)
        color = {
            "success": THEME["success"],
            "error": THEME["danger"],
            "warning": THEME["warning"],
            "loading": THEME["brand"],
            "info": THEME["success"],
        }.get(kind, THEME["success"])
        if hasattr(self, "status_dot"):
            self.status_dot.configure(fg=color)

    def get_editor_text(self):
        return self.editor.get("1.0", "end-1c").strip()

    def set_editor_text(self, text):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self.update_count()

    def load_config_to_ui(self):
        try:
            self.config = load_config()
        except Exception as exc:
            self.config = read_config_without_validation()
            self.set_status(str(exc), "warning")
        # Sync speed display
        try:
            speed = float(self.config.get("speed", 1.0))
            self.speed_var.set(f"{speed}×")
        except (TypeError, ValueError):
            self.speed_var.set("1.0×")

    def record_audio_path(self, record):
        audio_path = record.get("audio_path")
        if audio_path:
            path = Path(audio_path)
            if not path.is_absolute():
                path = APP_DIR / path
            if path.exists():
                return path

            # Older records may contain mojibake absolute paths. The WAV filename
            # is still intact, so recover from the local cache by basename.
            cached_by_name = CACHE_DIR / path.name
            if cached_by_name.exists():
                record["audio_path"] = str(cached_by_name.resolve())
                save_records(self.records)
                return cached_by_name

        inferred = self.infer_cached_audio_for_record(record)
        if inferred:
            record["audio_path"] = str(inferred.resolve())
            record["audio_created_at"] = record.get("audio_created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_records(self.records)
            return inferred

        return None

    def infer_cached_audio_for_record(self, record):
        cache_files = sorted(CACHE_DIR.glob("alicereader-*.wav"))
        if not cache_files:
            return None

        candidates = []
        record_id = str(record.get("id") or "")
        if record_id.isdigit():
            target_seconds = int(record_id[:10])
            candidates.append(target_seconds)

        created_at = record.get("created_at")
        if created_at:
            try:
                candidates.append(int(datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").timestamp()))
            except ValueError:
                pass

        best_path = None
        best_delta = 10**9
        for path in cache_files:
            match = re.search(r"alicereader-(\d+)\.wav$", path.name)
            if not match:
                continue
            wav_seconds = int(match.group(1))
            for target_seconds in candidates:
                delta = abs(wav_seconds - target_seconds)
                if delta < best_delta:
                    best_delta = delta
                    best_path = path

        return best_path if best_path and best_delta <= 180 else None

    def refresh_history(self):
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        self.history_list.delete(0, "end")
        if query:
            self.filtered_records = [
                r for r in self.records
                if query in (r.get("title") or "").lower()
                or query in (r.get("text") or "").lower()
            ]
        else:
            self.filtered_records = list(self.records)

        for record in self.filtered_records:
            title = record.get("title") or make_title(record.get("text", ""))
            created_at = record.get("created_at", "")
            prefix = "♪  " if self.record_audio_path(record) else "○  "
            self.history_list.insert("end", f"{prefix}{title}")
            if created_at:
                # add the date as a faded second entry — use insert with 2 lines per record? Keep single-line for now
                pass

        if hasattr(self, "history_count_label"):
            total = len(self.records)
            shown = len(self.filtered_records)
            label = f"{shown}/{total} 条" if query else f"{total} 条"
            self.history_count_label.configure(text=label)

    def repair_record_audio_paths(self):
        changed = False
        for record in self.records:
            before = record.get("audio_path")
            audio_path = self.record_audio_path(record)
            after = record.get("audio_path")
            if audio_path and after != before:
                changed = True
        if changed:
            save_records(self.records)

    def find_record_by_id(self, record_id):
        if not record_id:
            return None
        for record in self.records:
            if record.get("id") == record_id:
                return record
        return None

    def find_record_by_text(self, text):
        normalized = text.strip()
        for record in self.records:
            if record.get("text", "").strip() == normalized:
                return record
        return None

    def cached_audio_for_text(self, text):
        record = self.find_record_by_id(self.current_record_id)
        if record and record.get("text", "").strip() == text.strip():
            audio_path = self.record_audio_path(record)
            if audio_path:
                return audio_path, record

        record = self.find_record_by_text(text)
        if record:
            audio_path = self.record_audio_path(record)
            if audio_path:
                return audio_path, record
        return None, record

    def attach_audio_to_record(self, text, audio_path):
        record = self.find_record_by_id(self.current_record_id) or self.find_record_by_text(text)
        if not record:
            return
        record["audio_path"] = str(Path(audio_path).resolve())
        record["audio_created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_records(self.records)
        self.refresh_history()

    def play_audio_path(self, path, status="正在播放缓存音频"):
        self.audio_path = Path(path)
        self.audio_text = self.get_editor_text()
        self.player.open(self.audio_path)
        self.player.play()
        self.is_paused = False
        self.set_status(status, "success")
        self._refresh_play_button()
        self.update_count()

    def save_current_record(self):
        text = self.get_editor_text()
        if not text:
            self.set_status("文本框还是空的，先输入或导入一篇作文。", "warning")
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing = self.find_record_by_id(self.current_record_id)
        if existing and existing.get("text", "").strip() == text.strip():
            existing["title"] = make_title(text)
            existing["text"] = text
            existing["updated_at"] = now
            record = existing
        else:
            record = {"id": str(int(time.time() * 1000)), "title": make_title(text), "text": text, "created_at": now}
            self.records.insert(0, record)
            self.current_record_id = record["id"]

        if self.audio_path and self.audio_text.strip() == text.strip() and Path(self.audio_path).exists():
            record["audio_path"] = str(Path(self.audio_path).resolve())
            record["audio_created_at"] = now

        self.records = self.records[:100]
        save_records(self.records)
        self.refresh_history()
        self.set_status("已保存到记录。", "success")

    def load_selected_record(self):
        selection = self.history_list.curselection()
        if not selection:
            self.set_status("先在右侧选择一条记录。", "warning")
            return

        record = self.filtered_records[selection[0]]
        self.current_record_id = record.get("id")
        self.set_editor_text(record.get("text", ""))
        audio_path = self.record_audio_path(record)
        if audio_path:
            self.audio_path = audio_path
            self.audio_text = record.get("text", "")
            self.set_status("已打开记录，按空格或点击大按钮直接播放缓存音频。", "success")
        else:
            self.audio_path = None
            self.audio_text = ""
            self.set_status("已打开记录，尚未生成音频。", "info")
        self.update_count()

    def on_history_select(self, _event=None):
        if getattr(self, "_history_select_after_id", None):
            self.root.after_cancel(self._history_select_after_id)
        self._history_select_after_id = self.root.after(80, self.load_selected_record)

    def play_selected_record(self):
        self.load_selected_record()
        text = self.get_editor_text()
        if not text:
            return

        audio_path, record = self.cached_audio_for_text(text)
        if audio_path:
            self.current_record_id = record.get("id") if record else self.current_record_id
            self.play_audio_path(audio_path, "正在播放历史缓存音频。")
            return

        self.set_status("这条记录还没有可用的历史音频，点击“朗读文本”会生成并自动绑定。", "warning")

    def delete_selected_record(self):
        selection = self.history_list.curselection()
        if not selection:
            self.set_status("先在右侧选择一条记录。", "warning")
            return
        record = self.filtered_records[selection[0]]
        try:
            self.records.remove(record)
        except ValueError:
            return
        if record.get("id") == self.current_record_id:
            self.current_record_id = None
        save_records(self.records)
        self.refresh_history()
        self.set_status("记录已删除。", "info")

    def export_text(self):
        text = self.get_editor_text()
        if not text:
            self.set_status("没有可导出的文本。", "warning")
            return
        target = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text file", "*.txt")], initialfile=f"{make_title(text)}.txt")
        if target:
            Path(target).write_text(text, encoding="utf-8")
            self.set_status(f"已导出: {target}", "success")

    def new_text(self):
        if self.get_editor_text() and not messagebox.askyesno("新建", "清空当前文本？未保存的内容会丢失。"):
            return
        self.set_editor_text("")
        self.audio_path = None
        self.audio_text = ""
        self.current_record_id = None
        self.progress_bar.set_fraction(0)
        self.time_var.set("00:00 / 00:00")
        self.set_status("已新建空白文本。", "info")
        self.editor.focus_set()

    def start_hotkey_thread(self):
        threading.Thread(target=self.hotkey_loop, name="AliceReaderHotkey", daemon=True).start()

    def hotkey_loop(self):
        self.hotkey_thread_id = kernel32.GetCurrentThreadId()
        ok = user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT, VK["S"])
        if not ok:
            self.events.put(("status", "全局热键注册失败，仍可点击“导入选区”。"))
            return

        msg = MSG()
        try:
            while self.running:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    self.events.put(("status", "全局热键监听异常，仍可点击“导入选区”。"))
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.events.put(("hotkey", None))
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "hotkey":
                    self.import_selection(read_after_import=True)
                elif kind == "ready":
                    path = payload["path"]
                    text = payload["text"]
                    self.audio_path = path
                    self.audio_text = text
                    self.attach_audio_to_record(text, path)
                    self.player.open(path)
                    self.player.play()
                    self.is_paused = False
                    self.is_loading = False
                    self.set_status("音频生成完成，正在播放。", "success")
                    self.read_btn.configure(state="normal")
                    self._refresh_play_button()
                    self.update_count()
                elif kind == "error":
                    self.is_loading = False
                    self.set_status(f"⚠ {payload}", "error")
                    self.read_btn.configure(state="normal")
                    self._refresh_play_button()
                elif kind == "status":
                    self.set_status(payload, "warning")
                elif kind == "enable_read":
                    self.is_loading = False
                    self.read_btn.configure(state="normal")
                    self._refresh_play_button()
        except queue.Empty:
            pass

        if self.running:
            self.root.after(140, self.poll_events)

    def tick_spinner(self):
        if self.is_loading:
            self.spinner_index = (self.spinner_index + 1) % len(SPINNER_FRAMES)
            self.read_btn_text.set(f"{SPINNER_FRAMES[self.spinner_index]}  生成中…")
        if self.running:
            self.root.after(90, self.tick_spinner)

    def import_selection(self, read_after_import=False):
        text = copy_selected_text(self.root)
        if not text:
            if read_after_import:
                self.read_editor_text()
            else:
                self.set_status("没有检测到外部选中文字。", "warning")
            return

        self.set_editor_text(text)
        self.current_record_id = None
        self.audio_path = None
        self.audio_text = ""
        self.set_status(f"已导入选区，共 {len(text):,} 字符。", "success")
        if read_after_import:
            self.read_editor_text()

    def primary_action(self):
        """Smart primary button: toggles play/pause if audio matches editor text, else generates."""
        if self.is_loading:
            return
        text = self.get_editor_text()
        # If audio is loaded and matches current text, toggle play/pause
        if (
            self.player.opened
            and self.audio_path
            and self.audio_text.strip() == text.strip()
        ):
            self.toggle_play()
            return
        # If we have cached audio matching text but player is closed, just play it
        if self.audio_path and self.audio_text.strip() == text.strip() and Path(self.audio_path).exists():
            self.play_audio_path(self.audio_path)
            return
        # Otherwise generate
        self.read_editor_text()

    def read_editor_text(self):
        if self.is_loading:
            return
        if not self.config or not self.config.get("api_key"):
            self.load_config_to_ui()
            if not self.config or not self.config.get("api_key"):
                self.open_config()
                return

        text = self.get_editor_text()
        if not text:
            self.set_status("文本框为空，先输入或导入一段作文。", "warning")
            return
        provider = self.config.get("provider", "minimax")
        if provider == "minimax" and len(text) >= 10000:
            self.set_status("文本太长，MiniMax 同步接口要求少于 10000 字符。", "error")
            return

        audio_path, record = self.cached_audio_for_text(text)
        if audio_path:
            self.current_record_id = record.get("id") if record else self.current_record_id
            self.play_audio_path(audio_path, "命中缓存，直接播放（不消耗 MiniMax 配额）。")
            return

        self.is_loading = True
        self.set_status(f"{provider} 正在生成整段音频…", "loading")
        self.read_btn.configure(state="disabled")
        self.read_btn_text.set("⠋  生成中…")

        def worker():
            try:
                path, _ = synthesize(text, self.config)
                self.events.put(("ready", {"path": path, "text": text}))
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("enable_read", None))

        threading.Thread(target=worker, daemon=True).start()

    def toggle_play(self):
        if not self.player.opened:
            text = self.get_editor_text()
            if self.audio_path and self.audio_text.strip() == text.strip() and Path(self.audio_path).exists():
                self.play_audio_path(self.audio_path)
                return
            self.read_editor_text()
            return

        mode = self.player.mode()
        if mode == "playing":
            self.player.pause()
            self.is_paused = True
            self.set_status("已暂停", "info")
        elif self.is_paused:
            self.player.resume()
            self.is_paused = False
            self.set_status("继续播放", "success")
        else:
            if self.player.position_ms() >= max(0, self.player.length_ms() - 80):
                self.player.seek_ms(0)
            self.player.play()
            self.set_status("正在播放", "success")
        self._refresh_play_button()

    def stop(self):
        if self.player.opened:
            self.player.stop()
            self.is_paused = False
            self.progress_bar.set_fraction(0)
            self.time_var.set(f"00:00 / {format_time(self.player.length_ms())}")
            self.set_status("已停止", "info")
            self._refresh_play_button()

    def skip(self, delta_ms):
        if not self.player.opened:
            return
        length = self.player.length_ms()
        if length <= 0:
            return
        target = max(0, min(length - 50, self.player.position_ms() + delta_ms))
        self.player.seek_ms(target)
        if self.player.mode() == "playing" or self.is_paused:
            # MCI sometimes pauses on seek; keep playing if it was playing
            if not self.is_paused:
                self.player.play()
        direction = "前进" if delta_ms > 0 else "后退"
        self.set_status(f"{direction} {abs(delta_ms) // 1000}s · {format_time(target)}", "info")

    def cycle_speed(self):
        try:
            current = float(self.speed_var.get().rstrip("×"))
        except ValueError:
            current = 1.0
        nearest = min(SPEED_PRESETS, key=lambda v: abs(v - current))
        idx = (SPEED_PRESETS.index(nearest) + 1) % len(SPEED_PRESETS)
        new_speed = SPEED_PRESETS[idx]
        self.speed_var.set(f"{new_speed}×")
        if self.config:
            self.config["speed"] = new_speed
            provider = self.config.get("provider", "minimax")
            active = self.config.setdefault("providers", {}).setdefault(provider, {})
            if provider == "minimax":
                active["speed"] = new_speed
            elif provider == "alibaba":
                active["rate"] = new_speed
        # Drop any cached audio so next read uses the new speed
        text = self.get_editor_text()
        if self.audio_path and self.audio_text.strip() == text.strip():
            self.audio_path = None
            self.audio_text = ""
        self.set_status(f"播放速度已切换为 {new_speed}×（下次朗读生效）。", "info")

    def _refresh_play_button(self):
        if self.is_loading:
            return
        if self.player.opened and self.player.mode() == "playing":
            self.play_pause_btn.configure(text="⏸")
            self.read_btn_text.set("⏸  暂停播放")
        elif self.is_paused:
            self.play_pause_btn.configure(text="▶")
            self.read_btn_text.set("▶  继续播放")
        else:
            self.play_pause_btn.configure(text="▶")
            self.read_btn_text.set("▶  朗读文本")

    def save_audio(self):
        if not self.audio_path or not Path(self.audio_path).exists():
            self.set_status("还没有可导出的音频。", "warning")
            return

        target = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV audio", "*.wav")], initialfile=Path(self.audio_path).name)
        if target:
            shutil.copyfile(self.audio_path, target)
            self.set_status(f"已导出: {target}", "success")

    def open_config(self):
        return self.open_provider_config()

    def open_provider_config(self):
        config = read_config_without_validation()
        providers = config["providers"]
        win = tk.Toplevel(self.root)
        win.title("AliceReader 渠道配置")
        win.geometry("620x760+760+120")
        win.transient(self.root)
        win.configure(bg=THEME["page"])
        win.columnconfigure(1, weight=1)

        provider_var = tk.StringVar(value=config.get("provider", "minimax"))
        variables = {}
        rows = []

        def add_row(label, key, value="", values=None, secret=False):
            row = tk.Frame(win, bg=THEME["page"])
            tk.Label(row, text=label, width=24, anchor="e", bg=THEME["page"], fg=THEME["brand_dark"]).pack(side="left", padx=(0, 8))
            var = tk.StringVar(value=str(value))
            variables[key] = var
            if values:
                widget = ttk.Combobox(row, textvariable=var, values=values, state="readonly")
                if key == "model":
                    widget.bind("<<ComboboxSelected>>", rebuild)
            else:
                widget = tk.Entry(row, textvariable=var, show="*" if secret else None, relief="flat", highlightthickness=1, highlightbackground=THEME["line_soft"])
            widget.pack(side="left", fill="x", expand=True, ipady=4)
            rows.append(row)

        def rebuild(*_):
            for row in rows: row.destroy()
            rows.clear(); variables.clear()
            provider = provider_var.get()
            current = providers.get(provider, {})
            add_row(f"{provider} API Key", "api_key", current.get("api_key", config.get("api_key", "") if provider == "minimax" else ""), secret=True)
            if provider == "minimax":
                add_row("MiniMax 接口", "endpoint", current.get("endpoint", DEFAULT_CONFIG["endpoint"]))
                add_row("MiniMax 模型", "model", current.get("model", "speech-2.8-turbo"), MODEL_OPTIONS)
                add_row("MiniMax Voice ID", "voice_id", current.get("voice_id", DEFAULT_CONFIG["voice_id"]))
                add_row("MiniMax language_boost", "language_boost", current.get("language_boost", "auto"), LANGUAGE_OPTIONS)
                add_row("MiniMax emotion", "emotion", current.get("emotion", "fluent"), [value for _, value in EMOTION_OPTIONS])
                for label, key, default in (("MiniMax speed", "speed", 1), ("MiniMax volume", "volume", 1), ("MiniMax pitch", "pitch", 0), ("MiniMax sample_rate", "sample_rate", 32000), ("MiniMax bitrate", "bitrate", 128000)): add_row(label, key, current.get(key, default))
            elif provider == "doubao":
                add_row("豆包模型", "model", current.get("model", "seed-tts-2.0"), ["seed-tts-2.0", "seed-icl-2.0"])
                add_row("豆包 Speaker ID", "voice_id", current.get("voice_id", "zh_female_vv_uranus_bigtts"), ["zh_female_vv_uranus_bigtts", "zh_male_beijingxiaoye_moon_bigtts", "zh_female_wanwanxiaohe_moon_bigtts"])
                add_row("豆包 sample_rate", "sample_rate", current.get("sample_rate", 24000), ["24000", "16000"])
            else:
                model = current.get("model", "cosyvoice-v3-flash")
                add_row("阿里模型", "model", model, ["qwen3-tts-flash", "qwen3-tts-instruct-flash", "cosyvoice-v3-flash"])
                if model.startswith("cosyvoice-"):
                    add_row("CosyVoice Voice ID", "voice_id", current.get("voice_id", "longanhuan_v3"), ["longanhuan_v3", "longanyang", "loongabby_v3", "loongandy_v3"])
                    add_row("CosyVoice language_hint", "language_hint", current.get("language_hint", "zh"), ["", "zh", "en", "ja", "ko"])
                    add_row("CosyVoice instruction", "instruction", current.get("instruction", ""))
                    for label, key, default in (("CosyVoice rate", "rate", 1), ("CosyVoice volume", "volume", 50), ("CosyVoice pitch", "pitch", 1), ("CosyVoice sample_rate", "sample_rate", 24000)): add_row(label, key, current.get(key, default))
                else:
                    add_row("Qwen3-TTS Voice ID", "voice_id", current.get("voice_id", "Cherry"), ["Cherry", "Serena", "Ethan", "Chelsie"])
                    add_row("Qwen3-TTS language_type", "language_type", current.get("language_type", "Chinese"), ["Auto", "Chinese", "English", "Japanese", "Korean"])
                    if model == "qwen3-tts-instruct-flash": add_row("Qwen3-TTS instructions", "instruction", current.get("instruction", ""))
            for index, row in enumerate(rows, start=2): row.grid(row=index, column=0, columnspan=2, sticky="ew", padx=14, pady=5)

        def save_active():
            provider = provider_var.get()
            values = {key: var.get().strip() for key, var in variables.items()}
            for key in ("speed", "volume", "pitch", "rate"):
                if key in values: values[key] = float(values[key])
            for key in ("sample_rate", "bitrate"):
                if key in values: values[key] = int(float(values[key]))
            providers[provider] = providers.get(provider, {}) | values
            new_config = config | {"provider": provider, "providers": providers, "api_key": values.get("api_key", ""), "hotkey": "Ctrl+Shift+S"}
            if provider == "minimax": new_config.update(providers["minimax"])
            save_config(new_config)
            self.config = normalize_config(new_config)
            self.config["api_key"] = values.get("api_key", "")
            self.speed_var.set(f"{float(values.get('speed', values.get('rate', 1.0)))}×")
            self.set_status(f"{provider} 配置已保存。", "success")
            win.destroy()

        tk.Label(win, text="朗读渠道", bg=THEME["page"], fg=THEME["brand_dark"]).grid(row=0, column=0, sticky="e", padx=8, pady=12)
        provider_box = ttk.Combobox(win, textvariable=provider_var, values=["minimax", "doubao", "alibaba"], state="readonly")
        provider_box.grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=12)
        provider_box.bind("<<ComboboxSelected>>", rebuild)
        button_row = tk.Frame(win, bg=THEME["page"])
        button_row.grid(row=30, column=0, columnspan=2, sticky="e", padx=14, pady=16)
        self.make_button(button_row, "保存", save_active, kind="primary", parent_bg=THEME["page"]).pack(side="left", padx=4)
        self.make_button(button_row, "取消", win.destroy, kind="ghost", parent_bg=THEME["page"]).pack(side="left", padx=4)
        rebuild()

    def open_config_legacy(self):
        config = read_config_without_validation()
        win = tk.Toplevel(self.root)
        win.title("AliceReader 配置")
        win.geometry("540x700+860+180")
        win.transient(self.root)
        win.attributes("-topmost", False)
        win.configure(bg=THEME["page"])
        win.columnconfigure(1, weight=1)

        vars_map = {
            "api_key": tk.StringVar(value=config.get("api_key", "")),
            "endpoint": tk.StringVar(value=config.get("endpoint", DEFAULT_CONFIG["endpoint"])),
            "model": tk.StringVar(value=config.get("model", DEFAULT_CONFIG["model"])),
            "voice_preset": tk.StringVar(),
            "custom_voice": tk.StringVar(value=""),
            "language_boost": tk.StringVar(value=config.get("language_boost", "auto")),
            "emotion": tk.StringVar(),
            "speed": tk.StringVar(value=str(config.get("speed", 1.0))),
            "volume": tk.StringVar(value=str(config.get("volume", 1.0))),
            "pitch": tk.StringVar(value=str(config.get("pitch", 0))),
            "sample_rate": tk.StringVar(value=str(config.get("sample_rate", 32000))),
            "bitrate": tk.StringVar(value=str(config.get("bitrate", 128000))),
        }

        voice_values = [f"{name} | {voice_id}" for name, voice_id in VOICE_OPTIONS]
        voice_id = config.get("voice_id", DEFAULT_CONFIG["voice_id"])
        matched_voice = next((f"{name} | {value}" for name, value in VOICE_OPTIONS if value == voice_id), None)
        vars_map["voice_preset"].set(matched_voice or voice_values[-1])
        if not matched_voice:
            vars_map["custom_voice"].set(voice_id)

        emotion_values = [f"{name} | {value}" if value else name for name, value in EMOTION_OPTIONS]
        emotion = config.get("emotion", "fluent")
        vars_map["emotion"].set(next((item for item in emotion_values if item.endswith(f"| {emotion}") or (not emotion and item == "中性")), emotion_values[0]))

        def add_label(row, text):
            tk.Label(win, text=text, bg=THEME["page"], fg=THEME["brand_dark"], anchor="e", font=("Microsoft YaHei UI", 9)).grid(row=row, column=0, sticky="e", padx=(14, 8), pady=6)

        def add_entry(row, key, show=None):
            add_label(row, key)
            entry = tk.Entry(win, textvariable=vars_map[key], show=show, relief="flat", bg=THEME["white"], fg=THEME["brand_dark"], highlightthickness=1, highlightbackground=THEME["line_soft"])
            entry.grid(row=row, column=1, sticky="ew", padx=(0, 14), pady=6, ipady=5)
            return entry

        add_entry(0, "api_key", show="*")
        add_entry(1, "endpoint")

        add_label(2, "model")
        ttk.Combobox(win, textvariable=vars_map["model"], values=MODEL_OPTIONS, state="readonly").grid(row=2, column=1, sticky="ew", padx=(0, 14), pady=6)
        add_label(3, "voice")
        ttk.Combobox(win, textvariable=vars_map["voice_preset"], values=voice_values, state="readonly").grid(row=3, column=1, sticky="ew", padx=(0, 14), pady=6)
        add_entry(4, "custom_voice")
        add_label(5, "language_boost")
        ttk.Combobox(win, textvariable=vars_map["language_boost"], values=LANGUAGE_OPTIONS, state="readonly").grid(row=5, column=1, sticky="ew", padx=(0, 14), pady=6)
        add_label(6, "emotion")
        ttk.Combobox(win, textvariable=vars_map["emotion"], values=emotion_values, state="readonly").grid(row=6, column=1, sticky="ew", padx=(0, 14), pady=6)

        for row, key in enumerate(["speed", "volume", "pitch", "sample_rate", "bitrate"], start=7):
            add_entry(row, key)

        def selected_voice_id():
            value = vars_map["voice_preset"].get()
            if value.endswith("| custom"):
                return vars_map["custom_voice"].get().strip() or DEFAULT_CONFIG["voice_id"]
            return value.split("|", 1)[1].strip()

        def selected_emotion():
            value = vars_map["emotion"].get()
            return value.split("|", 1)[1].strip() if "|" in value else ""

        def save_from_ui():
            try:
                new_config = {
                    "api_key": vars_map["api_key"].get().strip(),
                    "endpoint": vars_map["endpoint"].get().strip() or DEFAULT_CONFIG["endpoint"],
                    "model": vars_map["model"].get().strip() or DEFAULT_CONFIG["model"],
                    "voice_id": selected_voice_id(),
                    "language_boost": vars_map["language_boost"].get().strip() or "auto",
                    "emotion": selected_emotion(),
                    "speed": float(vars_map["speed"].get()),
                    "volume": float(vars_map["volume"].get()),
                    "pitch": int(float(vars_map["pitch"].get())),
                    "sample_rate": int(float(vars_map["sample_rate"].get())),
                    "bitrate": int(float(vars_map["bitrate"].get())),
                    "hotkey": "Ctrl+Shift+S",
                }
            except ValueError:
                messagebox.showerror("配置错误", "speed/volume/pitch/sample_rate/bitrate 必须是数字。", parent=win)
                return
            save_config(new_config)
            self.config = new_config
            try:
                self.speed_var.set(f"{float(new_config.get('speed', 1.0))}×")
            except (TypeError, ValueError):
                pass
            self.set_status("配置已保存。", "success")
            win.destroy()

        button_row = tk.Frame(win, bg=THEME["page"])
        button_row.grid(row=12, column=0, columnspan=2, sticky="e", padx=14, pady=14)
        self.make_button(button_row, "保存", save_from_ui, kind="primary", parent_bg=THEME["page"]).pack(side="left", padx=4)
        self.make_button(button_row, "取消", win.destroy, kind="ghost", parent_bg=THEME["page"]).pack(side="left", padx=4)

    def _on_seek_fraction(self, fraction):
        if not self.player.opened:
            return
        length = self.player.length_ms()
        if length <= 0:
            return
        ms = int(length * fraction)
        self.time_var.set(f"{format_time(ms)} / {format_time(length)}")
        # Live seek if not currently dragging-too-fast
        if abs(ms - self.player.position_ms()) > 400:
            self.player.seek_ms(ms)
            if not self.is_paused:
                self.player.play()

    def on_seek(self, _value):
        # Legacy hook (no-op; kept for backwards compat)
        pass

    def update_progress(self):
        if self.player.opened:
            length = self.player.length_ms()
            pos = self.player.position_ms()
            if length > 0 and not self.is_seeking:
                self.progress_bar.set_fraction(pos / length)
                self.time_var.set(f"{format_time(pos)} / {format_time(length)}")
            mode = self.player.mode()
            if mode == "stopped" and length > 0 and pos >= length - 80:
                if self.last_status_kind != "info" or "完成" not in self.status_var.get():
                    self.set_status("✓ 已播放完成", "success")
                self._refresh_play_button()
            elif mode == "stopped" and self.is_paused:
                pass
            elif mode == "paused":
                self.is_paused = True

        if self.running:
            self.root.after(220, self.update_progress)

    def on_close(self):
        self.running = False
        if self.hotkey_thread_id:
            user32.PostThreadMessageW(self.hotkey_thread_id, WM_QUIT, 0, 0)
        self.player.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    AliceReaderApp().run()
