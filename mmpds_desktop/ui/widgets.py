from __future__ import annotations

from pathlib import Path
import hashlib
import sys
import tkinter as tk
from typing import Any, Callable

from mmpds_desktop.config.settings import THUMBNAIL_CACHE_DIR



class TkDebouncer:
    """Small Tkinter debounce helper for expensive UI refreshes."""

    def __init__(self, widget: Any, delay_ms: int = 220):
        self.widget = widget
        self.delay_ms = delay_ms
        self._job = None

    def cancel(self) -> None:
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self.cancel()
        self._job = self.widget.after(self.delay_ms, lambda: self._run(func, *args, **kwargs))

    def _run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self._job = None
        func(*args, **kwargs)


def enable_windows_dpi_awareness() -> None:
    """Enable per-monitor DPI awareness on Windows before creating Tk windows.

    This keeps text/tables sharper when the app is dragged between laptop and
    external monitors with different scaling settings. The function is safe on
    non-Windows systems and silently falls back when the OS policy blocks it.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def bind_mousewheel(canvas: tk.Canvas, *widgets) -> None:
    """Bind mouse wheel scrolling to canvas and child widgets."""
    def wheel(event):
        if hasattr(event, "delta") and event.delta:
            step = -1 if event.delta > 0 else 1
            if abs(event.delta) >= 120:
                step = int(-event.delta / 120)
            try:
                canvas.yview_scroll(step, "units")
            except tk.TclError:
                pass
            return "break"
        return None

    def button4(_event):
        try:
            canvas.yview_scroll(-1, "units")
        except tk.TclError:
            pass
        return "break"

    def button5(_event):
        try:
            canvas.yview_scroll(1, "units")
        except tk.TclError:
            pass
        return "break"

    def attach(w):
        try:
            w.bind("<MouseWheel>", wheel, add="+")
            w.bind("<Button-4>", button4, add="+")
            w.bind("<Button-5>", button5, add="+")
        except tk.TclError:
            pass

        for child in getattr(w, "winfo_children", lambda: [])():
            attach(child)

    attach(canvas)
    for w in widgets:
        attach(w)


class LazyImageCache:
    """Lazy source-image loader with Pillow + Tk fallback.

    Pillow is preferred because it supports resizing and more image formats.
    If Pillow is not installed, Tk's native PhotoImage is used for PNG/GIF files.
    """
    def __init__(self, max_size=(900, 1200), contrast_factor: float = 1.18, sharpness_factor: float = 1.05):
        self.max_size = max_size
        self.contrast_factor = contrast_factor
        self.sharpness_factor = sharpness_factor
        self._cache = {}
        self.last_error = ""

    def get(self, image_path: Path, max_size=None):
        size = max_size or self.max_size
        key = f"{image_path}|{size[0]}x{size[1]}|contrast={self.contrast_factor}|sharp={self.sharpness_factor}"
        if key in self._cache:
            return self._cache[key]

        self.last_error = ""

        try:
            from PIL import Image, ImageTk, ImageEnhance
            THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            try:
                mtime = image_path.stat().st_mtime
            except Exception:
                mtime = 0
            digest = hashlib.md5(
                f"{image_path}|{mtime}|{size[0]}x{size[1]}|contrast={self.contrast_factor}|sharp={self.sharpness_factor}".encode("utf-8", errors="ignore")
            ).hexdigest()
            thumb_path = THUMBNAIL_CACHE_DIR / f"{digest}.png"

            if thumb_path.exists():
                img = Image.open(thumb_path)
            else:
                img = Image.open(image_path)


                try:
                    img = ImageEnhance.Contrast(img).enhance(self.contrast_factor)
                    img = ImageEnhance.Sharpness(img).enhance(self.sharpness_factor)
                except Exception:
                    pass
                img.thumbnail(size)
                try:
                    img.save(thumb_path, "PNG")
                except Exception:
                    pass

            tk_img = ImageTk.PhotoImage(img)
            self._cache[key] = tk_img
            return tk_img
        except Exception as exc:
            self.last_error = str(exc)

        try:
            tk_img = tk.PhotoImage(file=str(image_path))
            self._cache[key] = tk_img
            return tk_img
        except Exception as exc:
            self.last_error = f"{self.last_error}; Tk fallback failed: {exc}"
            return None

    def clear(self):
        self._cache.clear()
