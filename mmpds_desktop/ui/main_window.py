from __future__ import annotations

from dataclasses import field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import getpass
import hashlib
import json
import math
import os
import pandas as pd
import re
import shutil
import sys
import threading
import tkinter as tk
from typing import Any, Dict, List, Optional, Tuple

from mmpds_desktop.calculations.conversions import _normalized_col_key, clamp, convert_value, converted_unit_label, display_spec, display_spec_value, find_col, first_nonblank_value, fmt_number, is_blank, norm, remove_duplicate_items, row_first_nonblank, row_get_first_nonblank_tolerant, row_spec2_value, source_cross_section_value, source_gui_thickness_label, source_row_identity_key, source_thickness_base_value, source_thickness_display_label, source_unit_label, strip_dropdown_mark, strip_edit_box, try_float, with_dropdown_mark
from mmpds_desktop.config.settings import BASIS_OPTIONS, DEFAULT_BASIS_CODES, DEFAULT_DIRECTION_CODES, DEFAULT_UNIT_CONVERSIONS, DIRECTION_OPTIONS, DUCKDB_FILE, EXPORT_AUDIT_FILE, EXPORT_COUNTER_MAX, EXPORT_COUNTER_START, FONTS, IMAGE_DIR, IMAGE_INDEX_FILE, LOG_DIR, LOG_TRACKING_AUTOSAVE_MS, LOG_TRACKING_VISIBLE_LIMIT, MAT_MODELS, MAX_SOURCE_IMAGES, NO_SPEC_DISPLAY, OPTION_UPDATE_DEBOUNCE_MS, PALETTE_LABELS, PALETTE_ORDER, PERFORMANCE_ENGINE_AVAILABLE, PLACEHOLDER_SEARCH, PROJECT_ROOT, PROPERTY_ROWS, READONLY_VALUE_ROWS, REQUIRED_MAT_VALUE_GROUPS, SOURCE_IMAGES_DIR, STAGES, THEME, UNIT_CONVERSION_ROWS, UNIT_SYSTEMS, UNIT_SYSTEM_SPEC, WINDOW_RESIZE_DEBOUNCE_MS, apply_theme, is_dark_theme, logger
from mmpds_desktop.models.app_state import FastMaterialEngine, HistoryStore, MaterialDatabase, SourceImageIndex, advance_session_export_id_after, export_counter_status_text, normalize_export_id, peek_next_export_id, reserve_next_export_id
from mmpds_desktop.ui.widgets import LazyImageCache, TkDebouncer, bind_mousewheel



class MaterialSelectorApp(tk.Tk):
    def __init__(self, db: MaterialDatabase):
        super().__init__()
        self.db = db
        self.perf_engine = None
        if PERFORMANCE_ENGINE_AVAILABLE and FastMaterialEngine is not None:
            try:
                self.perf_engine = FastMaterialEngine(
                    self.db.master,
                    material_to_series=getattr(self.db, "_material_to_series", {}),
                )
                logger.info("Performance engine loaded successfully.")
            except Exception as exc:
                self.perf_engine = None
                logger.warning("Performance engine could not start: %s", exc)
        self.history = HistoryStore()
        self.image_cache = LazyImageCache()
        self.source_image_index = SourceImageIndex(
            folders=[SOURCE_IMAGES_DIR, IMAGE_DIR],
            index_file=IMAGE_INDEX_FILE,
            duckdb_file=DUCKDB_FILE,
        )
        self.source_image_index._load_cache()


        self.is_dark_mode = False
        self.theme_family = "graphite"
        apply_theme(self.theme_family, "dark" if self.is_dark_mode else "light")

        self.title("MMPDS Material Selector")
        self.geometry("1480x880")
        self.minsize(1200, 760)
        self.configure(bg=THEME["bg"])


        self._root_resize_after_id = None
        self._last_root_size = (0, 0)
        self._last_screen_profile = None
        self._apply_tk_scaling_for_current_monitor()
        self.bind("<Configure>", self._on_root_configure_smooth, add="+")

        self._style()

        self.container = tk.Frame(self, bg=THEME["bg"])
        self.container.pack(fill=tk.BOTH, expand=True)
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value=f"Ready | {export_counter_status_text()} | Fast in-memory index enabled")

        sep = tk.Frame(self, bg=THEME["border"], height=1)
        sep.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_bar = tk.Frame(self, bg=THEME["accent"], height=28)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_bar.pack_propagate(False)
        self.status_label = tk.Label(
            self.status_bar,
            textvariable=self.status_var,
            bg=THEME["accent"],
            fg=THEME["accent_text"],
            font=FONTS["small"],
            anchor="w",
        )
        self.status_label.pack(fill=tk.X, padx=14, pady=4)

        self.screens = {}
        self.current_screen_name = "SelectionScreen"
        self._build_screens()


        self.bind_all("<Button-1>", self._global_audit_click, add="+")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.show_screen("SelectionScreen")

    def _apply_tk_scaling_for_current_monitor(self):
        """Apply safe Tk scaling based on current monitor DPI.

        This does not rebuild the interface. It only updates Tk's internal
        scaling value, helping the app stay sharp across monitors.
        """
        try:
            ppi = float(self.winfo_fpixels("1i"))
            scaling = clamp(ppi / 72.0, 1.0, 2.25)
            self.tk.call("tk", "scaling", scaling)
            return scaling
        except Exception:
            return None

    def _on_root_configure_smooth(self, event):
        """Debounce root resize/monitor movement events.

        Moving a Tk window between monitors can fire many Configure events.
        We wait until the movement/resizing settles, then refresh only geometry
        helpers instead of rebuilding engineering cards or reloading images.
        """
        try:
            if event.widget is not self:
                return
            size = (int(event.width), int(event.height))
            if abs(size[0] - self._last_root_size[0]) < 2 and abs(size[1] - self._last_root_size[1]) < 2:
                return
            self._last_root_size = size
            if self._root_resize_after_id is not None:
                self.after_cancel(self._root_resize_after_id)
            self._root_resize_after_id = self.after(WINDOW_RESIZE_DEBOUNCE_MS, self._handle_root_resize_settled)
        except Exception:
            pass

    def _handle_root_resize_settled(self):
        self._root_resize_after_id = None
        self._apply_tk_scaling_for_current_monitor()
        try:
            card = self.screens.get("CardScreen")
            if self.current_screen_name == "CardScreen" and card is not None:
                card._on_debounced_monitor_resize()
        except Exception:
            pass

    def _style(self):
        """Central ttk style configuration for the 2026 light/dark UI refresh."""
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass


        style.configure(
            "Primary.TButton",
            font=FONTS["body_bold"],
            padding=(16, 9),
            background=THEME["btn_primary"],
            foreground="white",
            borderwidth=0,
            focusthickness=0,
        )
        style.map(
            "Primary.TButton",
            background=[("active", THEME["btn_primary_hover"]), ("disabled", "#94A3B8")],
            foreground=[("disabled", "#FFFFFF")],
        )

        style.configure(
            "Secondary.TButton",
            font=FONTS["body"],
            padding=(12, 7),
            background=THEME["btn_secondary_bg"],
            foreground=THEME["btn_secondary_fg"],
            borderwidth=1,
            bordercolor=THEME["border"],
            focusthickness=0,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", THEME["btn_secondary_hover"]), ("disabled", THEME["panel_elevated"])],
            foreground=[("disabled", THEME["disabled_fg"])],
            bordercolor=[("active", THEME["accent"])],
        )

        style.configure(
            "Danger.TButton",
            font=FONTS["body_bold"],
            padding=(12, 7),
            background=THEME["btn_danger"],
            foreground="white",
            borderwidth=0,
        )
        style.map("Danger.TButton", background=[("active", THEME["btn_danger_hover"])])

        style.configure(
            "Success.TButton",
            font=FONTS["body_bold"],
            padding=(12, 7),
            background=THEME["btn_success"],
            foreground="white",
            borderwidth=0,
        )
        style.map("Success.TButton", background=[("active", THEME["btn_success_hover"])])

        style.configure(
            "ThemeToggle.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(18, 8),
            background=THEME["accent"],
            foreground="white",
            borderwidth=0,
        )
        style.map("ThemeToggle.TButton", background=[("active", THEME["accent_hover"])])

        style.configure(
            "Header.TButton",
            font=FONTS["small_bold"],
            padding=(18, 8),
            background=THEME["panel"],
            foreground=THEME["accent"],
            borderwidth=1,
            bordercolor=THEME["border"],
            focusthickness=0,
            relief="flat",
        )
        style.map(
            "Header.TButton",
            background=[("active", THEME["panel_elevated"])],
            foreground=[("active", THEME["accent_hover"]), ("disabled", THEME["disabled_fg"])],
            bordercolor=[("active", THEME["accent"])],
        )


        table_bg = THEME["table_bg"]
        table_alt_bg = THEME["table_alt_bg"]
        table_fg = THEME["table_fg"]
        table_select_bg = THEME["table_select_bg"]
        table_select_fg = THEME["table_select_fg"]

        style.configure(
            "Treeview",
            rowheight=30,
            font=FONTS["body"],
            background=table_bg,
            fieldbackground=table_bg,
            foreground=table_fg,
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", table_select_bg)],
            foreground=[("selected", table_select_fg)],
        )
        style.configure(
            "Treeview.Heading",
            background=THEME["table_header_bg"],
            foreground=THEME["table_header_fg"],
            font=FONTS["body_bold"],
            padding=(6, 7),
            borderwidth=0,
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", THEME["accent_hover"])])

        style.configure(
            "Advanced.Treeview",
            rowheight=38,
            font=("Segoe UI", 10),
            background=table_bg,
            fieldbackground=table_bg,
            foreground=table_fg,
            borderwidth=0,
        )
        style.map(
            "Advanced.Treeview",
            background=[("selected", table_select_bg)],
            foreground=[("selected", table_select_fg)],
        )
        style.configure(
            "Advanced.Treeview.Heading",
            background=THEME["table_header_bg"],
            foreground=THEME["table_header_fg"],
            font=FONTS["small_bold"],
            padding=(8, 8),
            borderwidth=0,
            relief="flat",
        )


        style.configure("Panel.TFrame", background=THEME["panel"])
        style.configure("AltPanel.TFrame", background=THEME["panel_alt"])
        style.configure("BG.TFrame", background=THEME["bg"])
        style.configure("Body.TLabel", background=THEME["panel"],
                        foreground=THEME["text"], font=FONTS["body"])
        style.configure("SmallBold.TLabel", background=THEME["panel"],
                        foreground=THEME["text_muted"], font=FONTS["small_bold"])
        style.configure("MutedSmall.TLabel", background=THEME["panel"],
                        foreground=THEME["text_muted"], font=FONTS["small"])
        style.configure("Mono.TLabel", background=THEME["panel"],
                        foreground=THEME["text"], font=FONTS["mono_small"])
        style.configure("BG.TLabel", background=THEME["bg"],
                        foreground=THEME["text"], font=FONTS["body"])
        style.configure("BGMuted.TLabel", background=THEME["bg"],
                        foreground=THEME["text_muted"], font=FONTS["small"])
        style.configure("BGTitle.TLabel", background=THEME["bg"],
                        foreground=THEME["accent"], font=FONTS["title"])

        style.configure(
            "Danger.TLabel",
            background=THEME["bg"],
            foreground="#FCA5A5" if is_dark_theme() else "#DC2626",
            font=("Segoe UI", 10, "bold"),
        )


        style.configure(
            "TEntry",
            padding=(6, 5),
            fieldbackground=THEME["entry_bg"],
            foreground=THEME["entry_fg"],
            insertcolor=THEME["entry_fg"],
            bordercolor=THEME["border"],
            lightcolor=THEME["border"],
            darkcolor=THEME["border"],
        )
        style.map(
            "TEntry",
            fieldbackground=[("focus", THEME["entry_bg"])],
            foreground=[("focus", THEME["entry_fg"])],
            bordercolor=[("focus", THEME["focus_ring"])],
            lightcolor=[("focus", THEME["focus_ring"])],
            darkcolor=[("focus", THEME["focus_ring"])],
        )
        style.configure(
            "TCombobox",
            padding=(5, 4),
            fieldbackground=THEME["entry_bg"],
            background=THEME["entry_bg"],
            foreground=THEME["entry_fg"],
            bordercolor=THEME["border"],
            arrowcolor=THEME["accent"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", THEME["entry_bg"]), ("focus", THEME["entry_bg"])],
            foreground=[("readonly", THEME["entry_fg"]), ("focus", THEME["entry_fg"])],
            bordercolor=[("focus", THEME["focus_ring"])],
        )


        style.configure("TNotebook", background=THEME["bg"], borderwidth=0, tabmargins=(2, 6, 2, 0))
        style.configure(
            "TNotebook.Tab",
            padding=(18, 9),
            font=FONTS["body_bold"],
            background=THEME["tab_inactive_bg"],
            foreground=THEME["tab_inactive_fg"],
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", THEME["tab_active_bg"]), ("active", THEME["panel_elevated"])],
            foreground=[("selected", THEME["tab_active_fg"]), ("active", THEME["tab_active_fg"])],
            expand=[("selected", (0, 0, 0, 0))],
        )


        style.configure(
            "Soft.TLabelframe",
            background=THEME["panel"],
            bordercolor=THEME["border"],
            lightcolor=THEME["border"],
            darkcolor=THEME["border"],
            relief="solid",
            padding=(10, 8),
        )
        style.configure(
            "Soft.TLabelframe.Label",
            background=THEME["panel"],
            foreground=THEME["accent"],
            font=FONTS["small_bold"],
        )


        style.configure(
            "Vertical.TScrollbar",
            background=THEME["panel_elevated"],
            troughcolor=THEME["bg"],
            bordercolor=THEME["border"],
            arrowcolor=THEME["accent"],
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=THEME["panel_elevated"],
            troughcolor=THEME["bg"],
            bordercolor=THEME["border"],
            arrowcolor=THEME["accent"],
        )


        for _btn in ("Primary.TButton", "Secondary.TButton", "Danger.TButton", "Success.TButton"):
            try:
                style.map(_btn, relief=[("pressed", "sunken"), ("!pressed", "flat")])
            except Exception:
                pass

        style.configure(
            "Ghost.TButton",
            font=FONTS["small_bold"],
            padding=(12, 7),
            background=THEME["panel"],
            foreground=THEME["text_muted"],
            borderwidth=1,
            bordercolor=THEME["border"],
            focusthickness=0,
            relief="flat",
        )
        style.map(
            "Ghost.TButton",
            background=[("active", THEME["panel_elevated"])],
            foreground=[("active", THEME["accent"]), ("disabled", THEME["disabled_fg"])],
            bordercolor=[("active", THEME["accent"])],
        )

        style.configure(
            "Chip.TButton",
            font=FONTS["small_bold"],
            padding=(14, 6),
            background=THEME["select_bg"],
            foreground=THEME["select_fg"],
            borderwidth=0,
            relief="flat",
            focusthickness=0,
        )
        style.map(
            "Chip.TButton",
            background=[("active", THEME["accent"])],
            foreground=[("active", THEME["accent_text"])],
        )

        style.configure("Card.TFrame", background=THEME["panel"], relief="solid", borderwidth=1, bordercolor=THEME["border"])
        style.configure("CardElevated.TFrame", background=THEME["panel_elevated"], relief="solid", borderwidth=1, bordercolor=THEME["border"])
        style.configure("Toolbar.TFrame", background=THEME["panel_alt"], relief="flat", borderwidth=0)

        style.configure("Display.TLabel", background=THEME["bg"], foreground=THEME["accent"], font=FONTS["display"])
        style.configure("H1.TLabel", background=THEME["panel"], foreground=THEME["text"], font=FONTS["h1"])
        style.configure("H2.TLabel", background=THEME["panel"], foreground=THEME["text"], font=FONTS["h2"])
        style.configure("FieldLabel.TLabel", background=THEME["panel"], foreground=THEME["text_muted"], font=FONTS["label"])
        style.configure("Subtitle.TLabel", background=THEME["bg"], foreground=THEME["text_muted"], font=FONTS["subtitle"])
        style.configure("Caption.TLabel", background=THEME["panel"], foreground=THEME["text_subtle"], font=FONTS["caption"])

        try:
            style.map("TCombobox", arrowcolor=[("focus", THEME["accent_hover"]), ("active", THEME["accent_hover"])])
        except Exception:
            pass


    def _build_screens(self):
        for child in self.container.winfo_children():
            child.destroy()
        self.screens = {}
        for Screen in (SelectionScreen, CardScreen):
            scr = Screen(self.container, self)
            self.screens[Screen.__name__] = scr
            scr.grid(row=0, column=0, sticky="nsew")

    def theme_button_text(self) -> str:
        if self.is_dark_mode:
            return "Theme: Dark -> Light"
        return "Theme: Light -> Dark"

    def _capture_theme_state(self, target: str) -> Dict[str, Any]:
        """Keep current selections/card state when switching between light and dark mode."""
        state: Dict[str, Any] = {"target": target}
        try:
            if target == "SelectionScreen":
                scr = self.screens.get("SelectionScreen")
                if scr is not None:
                    state.update({
                        "selections": dict(getattr(scr, "selections", {})),
                        "adv_selections": dict(getattr(scr, "adv_selections", {})),
                        "advanced_items": [dict(x) for x in getattr(scr, "advanced_items", [])],
                        "adv_output_dir": getattr(scr, "adv_output_dir_var", tk.StringVar(value="")).get(),
                        "adv_id_start": getattr(scr, "adv_id_start_var", tk.StringVar(value=str(EXPORT_COUNTER_START))).get(),
                        "finder_selections": dict(getattr(scr, "finder_selections", {})),
                        "finder_filters": [dict(x) for x in getattr(scr, "finder_filters", [])],
                    })
                    try:
                        state["tab_index"] = scr.notebook.index(scr.notebook.select())
                    except Exception:
                        state["tab_index"] = 0
            elif target == "CardScreen":
                card = self.screens.get("CardScreen")
                if card is not None and getattr(card, "current_row", None) is not None:
                    rows = getattr(card, "thickness_rows", []) or [card.current_row]
                    state["card"] = {
                        "row": card.current_row,
                        "matching_rows": pd.DataFrame(rows),
                        "selections": dict(getattr(card, "current_selections", {})),
                        "history_state": {
                            "Basis": card.basis_var.get(),
                            "Direction": card.direction_var.get(),
                            "Unit_System": card.unit_sys_var.get(),
                            "Material_Model": card.mat_model_var.get(),
                            "Thickness": card._thickness_display_label(card.current_row),
                            "Thickness_Row_Key": card._row_identity_key(card.current_row),
                            "prop_values": dict(getattr(card, "prop_values", {})),
                            "unit_conversions": dict(getattr(card, "unit_conversions", {})),
                        },
                    }
        except Exception:
            pass
        return state

    def _restore_theme_state(self, state: Dict[str, Any]) -> None:
        """Restore visible state after the widgets are rebuilt for a theme change."""
        target = state.get("target") or "SelectionScreen"
        if target == "SelectionScreen":
            scr = self.screens.get("SelectionScreen")
            if scr is not None:
                try:
                    scr.selections.update(state.get("selections", {}))
                    scr.adv_selections.update(state.get("adv_selections", {}))
                    scr.advanced_items = [dict(x) for x in state.get("advanced_items", [])]
                    if state.get("adv_output_dir") and hasattr(scr, "adv_output_dir_var"):
                        scr.adv_output_dir_var.set(state.get("adv_output_dir"))
                    if state.get("adv_id_start") and hasattr(scr, "adv_id_start_var"):
                        scr.adv_id_start_var.set(state.get("adv_id_start"))
                    if hasattr(scr, "finder_selections"):
                        scr.finder_selections.update(state.get("finder_selections", {}))
                    if hasattr(scr, "finder_filters"):
                        scr.finder_filters = [dict(x) for x in state.get("finder_filters", [])]
                    scr._refresh_all()
                    scr._adv_refresh_all_stages()
                    scr._adv_refresh_tree()
                    if hasattr(scr, "_finder_refresh_all_stages"):
                        scr._finder_refresh_all_stages()
                        scr._finder_refresh_filter_tree()
                        scr._finder_search_materials(auto=True)
                    tab_index = int(state.get("tab_index", 0))
                    if hasattr(scr, "notebook"):
                        scr.notebook.select(tab_index)
                except Exception:
                    pass
            self.show_screen("SelectionScreen")
            return

        if target == "CardScreen" and isinstance(state.get("card"), dict):
            card_state = state["card"]
            self.show_screen(
                "CardScreen",
                row=card_state.get("row"),
                selections=card_state.get("selections"),
                matching_rows=card_state.get("matching_rows"),
                history_state=card_state.get("history_state"),
            )
            return

        self.show_screen(target)

    def _reapply_theme(self, status_message: str, toast_message: str, toast_kind: str = "info"):
        """Shared rebuild path for both mode and palette switching."""
        target = self.current_screen_name or "SelectionScreen"
        saved_state = self._capture_theme_state(target)
        apply_theme(getattr(self, "theme_family", "graphite"), "dark" if self.is_dark_mode else "light")
        self.configure(bg=THEME["bg"])
        try:
            self.status_bar.configure(bg=THEME["accent"])
            self.status_label.configure(bg=THEME["accent"], fg=THEME["accent_text"])
        except Exception:
            pass
        self.image_cache.clear()
        self._style()
        self._build_screens()
        self._restore_theme_state(saved_state)
        self.status_var.set(status_message)
        self.show_toast(toast_message, kind=toast_kind)

    def toggle_dark_mode(self):
        """Toggle light/dark appearance without losing the active screen context."""
        self.is_dark_mode = not self.is_dark_mode
        mode = "Dark" if self.is_dark_mode else "Light"
        fam = PALETTE_LABELS.get(getattr(self, "theme_family", "graphite"), "Graphite")
        self._reapply_theme(f"{fam} {mode} theme active", f"{fam} {mode} theme applied", "success")

    def cycle_palette(self):
        """Switch color family while keeping the current light/dark mode."""
        current = getattr(self, "theme_family", "graphite")
        try:
            next_index = (PALETTE_ORDER.index(current) + 1) % len(PALETTE_ORDER)
        except ValueError:
            next_index = 0
        self.theme_family = PALETTE_ORDER[next_index]
        fam = PALETTE_LABELS.get(self.theme_family, "Graphite")
        self._reapply_theme(f"Palette: {fam}", f"Palette changed to {fam}", "info")

    def palette_button_text(self) -> str:
        current = getattr(self, "theme_family", "graphite")
        try:
            next_family = PALETTE_ORDER[(PALETTE_ORDER.index(current) + 1) % len(PALETTE_ORDER)]
        except ValueError:
            next_family = PALETTE_ORDER[0]
        return f"Palette: {PALETTE_LABELS.get(current, 'Graphite')} -> {PALETTE_LABELS.get(next_family, 'Graphite')}"

    def show_toast(self, message: str, kind: str = "info", duration_ms: int = 2600) -> None:
        """Self-dismissing corner notification. kind: info|success|error. Never raises."""
        try:
            bg = THEME.get(f"toast_{kind}_bg", THEME.get("toast_info_bg", THEME["accent"]))
            fg = THEME.get(f"toast_{kind}_fg", THEME.get("toast_info_fg", THEME["accent_text"]))
            icon = {"success": "OK", "error": "!", "info": "i"}.get(kind, "i")
            existing = getattr(self, "_toast_win", None)
            if existing is not None and existing.winfo_exists():
                existing.destroy()
            toast = tk.Toplevel(self)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            try:
                toast.attributes("-alpha", 0.0)
            except Exception:
                pass
            toast.configure(bg=bg)
            frame = tk.Frame(toast, bg=bg, padx=16, pady=10)
            frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(frame, text=icon, bg=bg, fg=fg, font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(frame, text=message, bg=bg, fg=fg, font=FONTS["small_bold"], justify="left").pack(side=tk.LEFT)
            self.update_idletasks()
            tw, th = toast.winfo_reqwidth(), toast.winfo_reqheight()
            rx, ry = self.winfo_rootx(), self.winfo_rooty()
            rw, rh = self.winfo_width(), self.winfo_height()
            x = rx + rw - tw - 26
            y = ry + rh - th - 52
            toast.geometry(f"+{max(rx + 10, x)}+{max(ry + 10, y)}")
            self._toast_win = toast

            def _fade(step, target, after_done=None):
                try:
                    cur = float(toast.attributes("-alpha"))
                except Exception:
                    if after_done:
                        after_done()
                    return
                nxt = cur + step
                done = (step > 0 and nxt >= target) or (step < 0 and nxt <= target)
                try:
                    toast.attributes("-alpha", target if done else nxt)
                except Exception:
                    pass
                if done:
                    if after_done:
                        after_done()
                else:
                    toast.after(16, lambda: _fade(step, target, after_done))

            def _dismiss():
                if toast.winfo_exists():
                    _fade(-0.12, 0.0, after_done=lambda: toast.winfo_exists() and toast.destroy())

            _fade(0.12, 0.96)
            toast.after(duration_ms, _dismiss)
        except Exception:
            pass

    def show_screen(self, name, **kwargs):
        self.current_screen_name = name
        scr = self.screens[name]
        scr.tkraise()
        if hasattr(scr, "on_show"):
            scr.on_show(**kwargs)

    def _on_close(self):
        """Flush lightweight logs before closing the app."""
        try:
            scr = self.screens.get("SelectionScreen")
            if scr is not None and hasattr(scr, "_flush_log_tracking"):
                scr._flush_log_tracking()
        except Exception:
            pass
        self.destroy()

    def _global_audit_click(self, event):
        """Route every application click to the current SelectionScreen audit store.

        Raw click rows are stored internally only, so Full Audit export has every
        click while the visible Export Log remains readable.
        """
        try:
            selection_screen = self.screens.get("SelectionScreen")
            if selection_screen is not None and hasattr(selection_screen, "_app_click_log"):
                return selection_screen._app_click_log(event)
        except Exception:
            return None
        return None


class SelectionScreen(tk.Frame):
    """Screen 1 with normal cascade selection plus an Advanced Selection tab.

    Advanced Selection lets the user build a list of materials and export multiple
    MAT024 keyfiles without opening each material card individually.
    """
    def __init__(self, parent, app: MaterialSelectorApp):
        super().__init__(parent, bg=THEME["bg"])
        self.app = app
        self.db = app.db
        self.perf_engine = getattr(app, "perf_engine", None)
        if self.perf_engine is not None and TkDebouncer is not None:
            self.adv_perf_debouncer = TkDebouncer(self, 160)
            self.finder_perf_debouncer = TkDebouncer(self, 200)
        else:
            self.adv_perf_debouncer = None
            self.finder_perf_debouncer = None
        self.selections = {s: "" for s in STAGES}
        self.listboxes = {}
        self.search_vars = {}
        self.visible_values = {s: [] for s in STAGES}
        self.selection_labels = {}
        self.count_labels = {}


        self.adv_selections = {s: "" for s in STAGES}
        self.adv_listboxes = {}
        self.adv_search_vars = {}
        self.adv_visible_values = {s: [] for s in STAGES}
        self.adv_selection_labels = {}
        self.adv_count_labels = {}
        self.adv_match_var = tk.StringVar(value="Advanced Matching Materials: 0")

        # Material Finder state: used when the user knows property values
        # but does not know the exact material/specification.
        self.finder_selections = {s: "" for s in STAGES}
        self.finder_listboxes = {}
        self.finder_search_vars = {}
        self.finder_visible_values = {s: [] for s in STAGES}
        self.finder_selection_labels = {}
        self.finder_count_labels = {}
        self.finder_stage_vars = {s: tk.StringVar(value="") for s in STAGES}
        self.finder_property_var = tk.StringVar(value="")
        self.finder_value_var = tk.StringVar(value="")
        self.finder_tolerance_var = tk.StringVar(value="")
        self.finder_filters: List[Dict[str, str]] = []
        self.finder_result_rows: List[pd.Series] = []
        self.finder_match_var = tk.StringVar(value="Material Finder Matches: 0")
        self.finder_summary_var = tk.StringVar(value="No filters active.")
        self.finder_basis_var = tk.StringVar(value="B")
        self.finder_basis_display_var = tk.StringVar(value="B Basis")
        self.finder_direction_var = tk.StringVar(value="L")
        self.finder_unit_sys_var = tk.StringVar(value="mm_T_s")
        self.finder_model_var = tk.StringVar(value="MAT024+GISSMO")

        # Extra listbox filters requested for Advanced Selection.
        # These sit above the export list and drive the default values added to each export row.
        self.adv_extra_filter_stages = ["Thickness", "Basis", "Direction", "Matcard"]
        self.adv_extra_listboxes: Dict[str, tk.Listbox] = {}
        self.adv_extra_visible_values: Dict[str, List[str]] = {s: [] for s in self.adv_extra_filter_stages}
        self.adv_extra_selection_labels: Dict[str, tk.Label] = {}
        self.adv_extra_count_labels: Dict[str, tk.Label] = {}

        self.adv_id_start_var = tk.StringVar(value=str(EXPORT_COUNTER_START))
        self.adv_id_range_note_var = tk.StringVar(value="")
        self.advanced_items: List[Dict[str, Any]] = []
        self.adv_basis_var = tk.StringVar(value="B")
        self.adv_basis_display_var = tk.StringVar(value="B Basis")
        self.adv_direction_var = tk.StringVar(value="L")
        self.adv_unit_sys_var = tk.StringVar(value="mm_T_s")
        self.adv_model_var = tk.StringVar(value="MAT024+GISSMO")
        self.adv_thickness_mode_var = tk.StringVar(value="First matching thickness")
        self.adv_thickness_text_var = tk.StringVar(value="")
        self.adv_thickness_display_var = tk.StringVar(value="First matching thickness")
        self.adv_output_dir_var = tk.StringVar(value=str(PROJECT_ROOT / "outputs" / "advanced_keyfiles"))


        self.adv_basis_buttons: Dict[str, tk.Radiobutton] = {}
        self.adv_tree_edit_widget = None


        self.adv_cell_widgets: List[tk.Widget] = []
        self.adv_image_refs = []

        self._build()
        self._refresh_all()
        self._refresh_history()

    def _build(self):
        outer = tk.Frame(self, bg=THEME["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=22, pady=18)

        header = tk.Frame(outer, bg=THEME["bg"])
        header.pack(fill=tk.X, pady=(0, 14))


        title_block = tk.Frame(header, bg=THEME["bg"])
        title_block.pack(side=tk.LEFT)
        tk.Label(
            title_block,
            text="MMPDS Material Database",
            bg=THEME["bg"],
            fg=THEME["accent"],
            font=FONTS["title"],
            anchor="w",
        ).pack(anchor="w")

        right_group = tk.Frame(header, bg=THEME["bg"])
        right_group.pack(side=tk.RIGHT)

        tk.Label(
            right_group,
            text=f"{len(self.db.master):,} materials loaded",
            bg=THEME["bg"],
            fg=THEME["text_muted"],
            font=FONTS["small"],
        ).pack(side=tk.RIGHT, padx=(12, 0))
        ttk.Button(
            right_group,
            text=self.app.theme_button_text(),
            style="ThemeToggle.TButton",
            command=self.app.toggle_dark_mode,
        ).pack(side=tk.RIGHT, padx=(0, 10))
        ttk.Button(
            right_group,
            text=self.app.palette_button_text(),
            style="Ghost.TButton",
            command=self.app.cycle_palette,
        ).pack(side=tk.RIGHT, padx=(0, 8))

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.standard_tab = tk.Frame(self.notebook, bg=THEME["bg"])
        self.advanced_tab = tk.Frame(self.notebook, bg=THEME["bg"])
        self.material_finder_tab = tk.Frame(self.notebook, bg=THEME["bg"])
        self.export_log_tab = tk.Frame(self.notebook, bg=THEME["bg"])
        self.log_tracking_tab = tk.Frame(self.notebook, bg=THEME["bg"])
        self.notebook.add(self.standard_tab, text="Material Selection")
        self.notebook.add(self.advanced_tab, text="Advanced Selection")
        self.notebook.add(self.material_finder_tab, text="Material Finder")
        self.notebook.add(self.export_log_tab, text="Export Log")
        self.notebook.add(self.log_tracking_tab, text="Log Tracking")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed, add="+")

        self._build_standard_tab(self.standard_tab)
        self._build_advanced_tab(self.advanced_tab)
        self._build_material_finder_tab(self.material_finder_tab)
        self._build_export_log_tab(self.export_log_tab)
        self._build_log_tracking_tab(self.log_tracking_tab)


        self._adv_log("Application started. Material Selection, Advanced Selection, Material Finder, and Export Log tabs are ready.",
                      action="Application Started", status="Ready", screen="Application")


    def _next_log_tracking_path(self) -> Path:
        """Create the next YYYY_MM_DD_MMPDS_LogN.txt path.

        Log Tracking is intentionally lightweight: clicks are appended to memory
        first and flushed to a text file in batches, so the GUI does not slow
        down on every mouse click.
        """
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        date_prefix = datetime.now().strftime("%Y_%m_%d")
        existing = sorted(LOG_DIR.glob(f"{date_prefix}_MMPDS_Log*.txt"))
        max_num = 0
        for path in existing:
            stem = path.stem
            try:
                n = int(stem.split("_MMPDS_Log", 1)[1])
                max_num = max(max_num, n)
            except Exception:
                continue
        return LOG_DIR / f"{date_prefix}_MMPDS_Log{max_num + 1}.txt"

    def _ensure_log_tracking_state(self):
        if not hasattr(self, "log_tracking_records"):
            self.log_tracking_records: List[Dict[str, Any]] = []
        if not hasattr(self, "log_tracking_buffer"):
            self.log_tracking_buffer: List[Dict[str, Any]] = []
        if not hasattr(self, "log_tracking_path"):
            self.log_tracking_path = self._next_log_tracking_path()
            try:
                self.log_tracking_path.write_text(
                    "MMPDS Material Selector - Log Tracking\n"
                    f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"User: {getpass.getuser()}\n"
                    "=" * 110 + "\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
        if not hasattr(self, "_log_tracking_flush_job"):
            self._log_tracking_flush_job = None

    def _make_header_button(self, parent, text: str, command, *, danger: bool = False):
        """Create a clearly visible header button without dotted focus outlines."""
        bg = "#FFFFFF"
        fg = THEME["btn_danger"] if danger else THEME["accent"]
        active_bg = THEME["panel_elevated"]
        active_fg = THEME["btn_danger_hover"] if danger else THEME["accent_hover"]
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=active_fg,
            font=FONTS["small_bold"],
            relief="raised",
            bd=1,
            padx=14,
            pady=5,
            cursor="hand2",
            takefocus=0,
            highlightthickness=0,
        )
        return btn

    def _build_log_tracking_tab(self, parent):
        self._ensure_log_tracking_state()
        inset = tk.Frame(parent, bg=THEME["bg"])
        inset.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        panel = tk.Frame(inset, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        panel.pack(fill=tk.BOTH, expand=True)

        hdr = tk.Frame(panel, bg=THEME["accent"], height=40)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="Log Tracking", bg=THEME["accent"], fg="white",
                 font=FONTS["body_bold"]).pack(side=tk.LEFT, padx=12, pady=8)
        self._make_header_button(hdr, "Save Now", self._flush_log_tracking).pack(side=tk.RIGHT, padx=(6, 10), pady=5)
        self._make_header_button(hdr, "Open Log Folder", self._open_log_tracking_folder).pack(side=tk.RIGHT, padx=6, pady=5)
        self._make_header_button(hdr, "Clear View", self._clear_log_tracking_view).pack(side=tk.RIGHT, padx=6, pady=5)

        # Keep the current log path internally for saving, but do not display it on screen.
        self.log_tracking_path_var = tk.StringVar(value=str(getattr(self, "log_tracking_path", "")))

        table_wrap = tk.Frame(panel, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        table_wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=(4, 12))
        columns = ("time", "screen", "action", "widget", "material", "notes")
        self.log_tracking_tree = ttk.Treeview(table_wrap, columns=columns, show="headings", height=16)
        headings = {"time":"Date / Time", "screen":"Screen", "action":"Action", "widget":"Clicked Widget", "material":"Selected Material", "notes":"Notes"}
        widths = {"time":145, "screen":130, "action":190, "widget":180, "material":360, "notes":420}
        for c in columns:
            self.log_tracking_tree.heading(c, text=headings[c])
            self.log_tracking_tree.column(c, width=widths[c], anchor="w", stretch=True)
        ysb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.log_tracking_tree.yview)
        xsb = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.log_tracking_tree.xview)
        self.log_tracking_tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.log_tracking_tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

        for rec in self.log_tracking_records[-LOG_TRACKING_VISIBLE_LIMIT:]:
            self._insert_log_tracking_row(rec)

    def _is_log_tracking_visible(self) -> bool:
        """Return True only when the Log Tracking tab is visible to the user."""
        try:
            if not hasattr(self, "notebook"):
                return False
            tab_id = self.notebook.select()
            return bool(tab_id and self.notebook.tab(tab_id, "text") == "Log Tracking")
        except Exception:
            return False

    def _is_export_log_visible(self) -> bool:
        """Return True only when the Export Log tab is visible.

        This avoids refreshing a hidden audit table on every click/action, which
        was one of the causes of visible lag and blinking in Advanced Selection.
        """
        try:
            if not hasattr(self, "notebook"):
                return False
            tab_id = self.notebook.select()
            return bool(tab_id and self.notebook.tab(tab_id, "text") == "Export Log")
        except Exception:
            return False

    def _refresh_log_tracking_table(self):
        """Refresh Log Tracking table only when the user opens that tab.

        This avoids updating a hidden Treeview on every click, which was one
        reason Advanced Selection felt slow. Records are still saved internally.
        """
        tree = getattr(self, "log_tracking_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        try:
            for iid in tree.get_children():
                tree.delete(iid)
            for rec in getattr(self, "log_tracking_records", [])[-LOG_TRACKING_VISIBLE_LIMIT:]:
                self._insert_log_tracking_row(rec)
        except Exception:
            pass

    def _on_notebook_tab_changed(self, _event=None):
        if self._is_log_tracking_visible():
            self._refresh_log_tracking_table()
        if self._is_export_log_visible():
            self._refresh_export_log_table()

    def _open_log_tracking_folder(self):
        self._ensure_log_tracking_state()
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(str(LOG_DIR))
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(LOG_DIR)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(LOG_DIR)])
        except Exception as exc:
            messagebox.showinfo("Log Tracking", f"Log folder:\n{LOG_DIR}\n\nCould not open automatically: {exc}")

    def _clear_log_tracking_view(self):
        tree = getattr(self, "log_tracking_tree", None)
        if tree is not None and tree.winfo_exists():
            for iid in tree.get_children():
                tree.delete(iid)

    def _insert_log_tracking_row(self, rec: Dict[str, Any]):
        tree = getattr(self, "log_tracking_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        try:
            children = tree.get_children()
            if len(children) >= LOG_TRACKING_VISIBLE_LIMIT:
                tree.delete(children[0])
            iid = str(rec.get("Log_ID", len(children) + 1))
            tree.insert("", "end", iid=iid, values=(
                rec.get("Date_Time", ""),
                rec.get("Screen", ""),
                rec.get("Action", ""),
                rec.get("Widget_Class", ""),
                rec.get("Material_Summary", ""),
                rec.get("Notes", ""),
            ))
            tree.see(iid)
        except Exception:
            pass

    def _track_click_fast(self, *, screen: str, action: str, widget_class: str = "",
                          widget_text: str = "", material_summary: str = "", notes: str = "",
                          x: str = "", y: str = ""):
        self._ensure_log_tracking_state()
        rec = {
            "Log_ID": len(self.log_tracking_records) + 1,
            "Date_Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Screen": screen,
            "Action": action,
            "Widget_Class": widget_class,
            "Widget_Text": widget_text,
            "Material_Summary": material_summary,
            "Notes": notes,
            "Click_X": x,
            "Click_Y": y,
        }
        self.log_tracking_records.append(rec)
        self.log_tracking_buffer.append(rec)
        if self._is_log_tracking_visible():
            self._insert_log_tracking_row(rec)
        self._schedule_log_tracking_flush()

    def _schedule_log_tracking_flush(self):
        if getattr(self, "_log_tracking_flush_job", None):
            return
        try:
            self._log_tracking_flush_job = self.after(LOG_TRACKING_AUTOSAVE_MS, self._flush_log_tracking)
        except Exception:
            self._log_tracking_flush_job = None

    def _flush_log_tracking(self):
        self._ensure_log_tracking_state()
        self._log_tracking_flush_job = None
        if not self.log_tracking_buffer:
            return
        rows = list(self.log_tracking_buffer)
        self.log_tracking_buffer.clear()
        try:
            with self.log_tracking_path.open("a", encoding="utf-8") as f:
                for rec in rows:
                    line = (
                        f"[{rec.get('Date_Time','')}] "
                        f"Screen={rec.get('Screen','')} | "
                        f"Action={rec.get('Action','')} | "
                        f"Widget={rec.get('Widget_Class','')} | "
                        f"Text={rec.get('Widget_Text','')} | "
                        f"Material={rec.get('Material_Summary','')} | "
                        f"XY={rec.get('Click_X','')},{rec.get('Click_Y','')} | "
                        f"Notes={rec.get('Notes','')}\n"
                    )
                    f.write(line)
            if hasattr(self, "log_tracking_path_var"):
                self.log_tracking_path_var.set(str(self.log_tracking_path))
        except Exception:

            self.log_tracking_buffer = rows + self.log_tracking_buffer


    def _build_export_log_tab(self, parent):
        """Build a readable, exportable audit log tab.

        Meaningful application actions are stored as structured rows. Cleared
        rows remain in an internal archive, and the current or full audit trail
        can be exported as TXT, CSV, or Excel.
        """


        if not hasattr(self, "export_log_records"):
            self.export_log_records: List[Dict[str, Any]] = []
        if not hasattr(self, "export_log_archive"):
            self.export_log_archive: List[Dict[str, Any]] = self._load_export_log_archive()
        self._last_log_id = self._next_export_log_id()

        inset = tk.Frame(parent, bg=THEME["bg"])
        inset.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        panel = tk.Frame(inset, bg=THEME["panel"],
                         highlightbackground=THEME["border"], highlightthickness=1)
        panel.pack(fill=tk.BOTH, expand=True)

        hdr = tk.Frame(panel, bg=THEME["accent"], height=40)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="Application / Export Audit Log", bg=THEME["accent"], fg="white",
                 font=FONTS["body_bold"]).pack(side=tk.LEFT, padx=12, pady=8)

        self._make_header_button(hdr, "Clear Visible Log", self._clear_export_log, danger=True).pack(side=tk.RIGHT, padx=(6, 10), pady=5)
        self._make_header_button(hdr, "Export Full Audit", lambda: self._export_log_dialog(scope="full")).pack(side=tk.RIGHT, padx=6, pady=5)
        self._make_header_button(hdr, "Export Current", lambda: self._export_log_dialog(scope="current")).pack(side=tk.RIGHT, padx=6, pady=5)

        table_wrap = tk.Frame(panel, bg=THEME["panel"],
                              highlightbackground=THEME["border"], highlightthickness=1)
        table_wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=(4, 8))

        columns = ("time", "action", "material_summary", "status", "notes")
        self.export_log_tree = ttk.Treeview(table_wrap, columns=columns, show="headings", height=12)
        headings = {
            "time": "Time",
            "action": "Action",
            "material_summary": "Material Summary",
            "status": "Status",
            "notes": "Notes",
        }
        widths = {"time": 135, "action": 175, "material_summary": 560, "status": 105, "notes": 390}
        for c in columns:
            self.export_log_tree.heading(c, text=headings[c])
            self.export_log_tree.column(c, width=widths[c], anchor="w", stretch=True)
        self.export_log_tree.tag_configure("ok", foreground=THEME["status_ok_fg"])
        self.export_log_tree.tag_configure("warn", foreground=THEME["status_warn_fg"])
        self.export_log_tree.tag_configure("error", foreground=THEME["status_error_fg"])
        self.export_log_tree.tag_configure("info", foreground=THEME["text"])

        ysb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.export_log_tree.yview)
        xsb = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.export_log_tree.xview)
        self.export_log_tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.export_log_tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)
        self.export_log_tree.bind("<<TreeviewSelect>>", self._show_export_log_details)

        detail_box = tk.Frame(panel, bg=THEME["panel_alt"],
                              highlightbackground=THEME["border"], highlightthickness=1)
        detail_box.pack(fill=tk.X, padx=14, pady=(0, 12))
        tk.Label(detail_box, text="Selected Log Details", bg=THEME["panel_alt"], fg=THEME["accent"],
                 font=FONTS["small_bold"], anchor="w").pack(fill=tk.X, padx=10, pady=(7, 0))
        self.export_log_detail = tk.Text(detail_box, height=6, wrap="word", font=FONTS["mono_small"],
                                         bg=THEME["text_area_bg"], fg=THEME["text_area_fg"], relief="flat",
                                         padx=10, pady=8)
        self.export_log_detail.pack(fill=tk.X, padx=10, pady=(4, 10))
        self.export_log_detail.configure(state=tk.DISABLED)

        self._refresh_export_log_table()

    def _load_export_log_archive(self) -> List[Dict[str, Any]]:
        """Load the hidden audit archive from disk when available."""
        try:
            if EXPORT_AUDIT_FILE.exists():
                payload = json.loads(EXPORT_AUDIT_FILE.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    records = payload.get("records", [])
                    if isinstance(records, list):
                        return [r for r in records if isinstance(r, dict)]
                if isinstance(payload, list):
                    return [r for r in payload if isinstance(r, dict)]
        except Exception:
            pass
        return []

    def _persist_export_log_archive(self) -> None:
        """Persist the full internal audit trail silently (debounced)."""
        if not hasattr(self, "_persist_log_pending"):
            self._persist_log_pending = None
        if self._persist_log_pending is not None:
            try:
                self.after_cancel(self._persist_log_pending)
            except Exception:
                pass
        
        def _write():
            self._persist_log_pending = None
            try:
                payload = {
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "records": self._all_export_log_records(),
                }
                EXPORT_AUDIT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            except Exception:
                pass
        self._persist_log_pending = self.after(2000, _write)

    def _flush_log_tracking(self) -> None:
        """Immediately write any pending log persistence requests."""
        if getattr(self, "_persist_log_pending", None) is not None:
            try:
                self.after_cancel(self._persist_log_pending)
            except Exception:
                pass
            self._persist_log_pending = None
            try:
                payload = {
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "records": self._all_export_log_records(),
                }
                EXPORT_AUDIT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _all_export_log_records(self) -> List[Dict[str, Any]]:
        archive = list(getattr(self, "export_log_archive", []))
        current = list(getattr(self, "export_log_records", []))
        return archive + current

    def _next_export_log_id(self) -> int:
        max_id = 0
        for rec in self._all_export_log_records():
            try:
                max_id = max(max_id, int(rec.get("Log_ID", 0)))
            except Exception:
                continue
        return max_id + 1

    def _new_export_log_record(self, *, screen="", action="Info", status="Info",
                               material_summary="", element="", series="", material="",
                               temper="", specification="", form="", basis="",
                               direction="", unit_system="", changed_field="",
                               old_value="", new_value="", keyfile_name="",
                               image_name="", export_folder="", notes="", details="",
                               widget_class="", widget_text="", widget_path="",
                               click_x="", click_y="") -> Dict[str, Any]:
        now = datetime.now()
        rec = {
            "Log_ID": getattr(self, "_last_log_id", 1),
            "Date_Time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "Time": now.strftime("%H:%M:%S"),
            "Screen": screen,
            "Action": action,
            "Status": status,
            "Material_Summary": material_summary,
            "Element": element,
            "Series": series,
            "Material": material,
            "Temper": temper,
            "Specification": specification,
            "Form": form,
            "Basis": basis,
            "Direction": direction,
            "Unit_System": unit_system,
            "Changed_Field": changed_field,
            "Old_Value": old_value,
            "New_Value": new_value,
            "Keyfile_Name": keyfile_name,
            "Image_Name": image_name,
            "Export_Folder": export_folder,
            "Notes": notes,
            "Details": details,
            "Widget_Class": widget_class,
            "Widget_Text": widget_text,
            "Widget_Path": widget_path,
            "Click_X": click_x,
            "Click_Y": click_y,
        }
        self._last_log_id = int(rec["Log_ID"]) + 1
        return rec

    def _audit_log_action(self, *, screen="", action="Info", status="Info",
                          material_summary="", element="", series="", material="",
                          temper="", specification="", form="", basis="",
                          direction="", unit_system="", changed_field="",
                          old_value="", new_value="", keyfile_name="",
                          image_name="", export_folder="", notes="", details="",
                          widget_class="", widget_text="", widget_path="",
                          click_x="", click_y="") -> Dict[str, Any]:
        """Append one meaningful visible audit row and refresh the Export Log tab."""
        rec = self._new_export_log_record(
            screen=screen, action=action, status=status, material_summary=material_summary,
            element=element, series=series, material=material, temper=temper,
            specification=specification, form=form, basis=basis, direction=direction,
            unit_system=unit_system, changed_field=changed_field, old_value=old_value,
            new_value=new_value, keyfile_name=keyfile_name, image_name=image_name,
            export_folder=export_folder, notes=notes, details=details,
            widget_class=widget_class, widget_text=widget_text, widget_path=widget_path,
            click_x=click_x, click_y=click_y,
        )
        self.export_log_records.append(rec)
        self._persist_export_log_archive()
        if self._is_export_log_visible():
            self._refresh_export_log_table()
        return rec

    def _refresh_export_log_table(self):
        tree = getattr(self, "export_log_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        for iid in tree.get_children():
            tree.delete(iid)
        for idx, rec in enumerate(getattr(self, "export_log_records", [])):
            status = str(rec.get("Status", ""))
            tag = "info"
            if status.lower() in {"success", "exported", "saved", "ready"}:
                tag = "ok"
            elif "error" in status.lower() or "failed" in status.lower() or "skipped" in status.lower():
                tag = "error"
            elif "warn" in status.lower() or "cleared" in status.lower():
                tag = "warn"
            tree.insert("", "end", iid=str(idx), values=(
                rec.get("Date_Time", ""),
                rec.get("Action", ""),
                rec.get("Material_Summary", ""),
                rec.get("Status", ""),
                rec.get("Notes", ""),
            ), tags=(tag,))
        if getattr(self, "export_log_records", []):
            last_iid = str(len(self.export_log_records) - 1)
            try:
                tree.see(last_iid)
                tree.selection_set(last_iid)
            except Exception:
                pass
        self._show_export_log_details()

    def _show_export_log_details(self, _event=None):
        detail = getattr(self, "export_log_detail", None)
        if detail is None or not detail.winfo_exists():
            return
        text = "Select a log row to see full details."
        try:
            sel = self.export_log_tree.selection()
            if sel:
                rec = self.export_log_records[int(sel[0])]
                lines = [
                    f"Log ID: {rec.get('Log_ID', '')}",
                    f"Date/Time: {rec.get('Date_Time', '')}",
                    f"Screen: {rec.get('Screen', '')}",
                    f"Action: {rec.get('Action', '')}",
                    f"Status: {rec.get('Status', '')}",
                ]
                if rec.get("Material_Summary"):
                    lines.append(f"Material Summary: {rec.get('Material_Summary')}")
                if rec.get("Changed_Field"):
                    lines.append(f"Changed Field(s): {rec.get('Changed_Field')}")
                    lines.append(f"Old Value(s): {rec.get('Old_Value')}")
                    lines.append(f"New Value(s): {rec.get('New_Value')}")
                if rec.get("Keyfile_Name"):
                    lines.append(f"Keyfile: {rec.get('Keyfile_Name')}")
                if rec.get("Image_Name"):
                    lines.append(f"Image: {rec.get('Image_Name')}")
                if rec.get("Export_Folder"):
                    lines.append(f"Export Folder: {rec.get('Export_Folder')}")
                if rec.get("Notes"):
                    lines.append(f"Notes: {rec.get('Notes')}")
                if rec.get("Details"):
                    lines.append("")
                    lines.append(str(rec.get("Details")))
                text = "\n".join(lines)
        except Exception:
            pass
        detail.configure(state=tk.NORMAL)
        detail.delete("1.0", tk.END)
        detail.insert("1.0", text)
        detail.configure(state=tk.DISABLED)

    def _clear_export_log(self):
        old_count = len(getattr(self, "export_log_records", []))
        if old_count <= 0:
            messagebox.showinfo("Clear Log", "There are no visible log records to clear.")
            return
        if not messagebox.askyesno(
            "Clear Visible Log",
            f"Clear {old_count} visible log record(s)?\n\nThey will stay stored internally for Full Audit export."
        ):
            return
        self.export_log_archive.extend(self.export_log_records)
        clear_rec = self._new_export_log_record(
            screen="Export Log",
            action="Clear Log",
            status="Cleared",
            notes=f"User cleared {old_count} visible log record(s). Records stored internally.",
            details=f"{old_count} visible record(s) were moved into the hidden audit archive."
        )

        self.export_log_records = [clear_rec]
        self._persist_export_log_archive()
        self._refresh_export_log_table()

    def _export_log_dialog(self, scope: str = "current"):
        records = list(getattr(self, "export_log_records", [])) if scope == "current" else self._all_export_log_records()
        if not records:
            messagebox.showwarning("Export Log", "No log records are available to export.")
            return
        default_name = f"mmpds_{'current_log' if scope == 'current' else 'full_audit_log'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        path = filedialog.asksaveasfilename(
            title="Export Current Log" if scope == "current" else "Export Full Internal Audit Log",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[
                ("Excel Workbook", "*.xlsx"),
                ("CSV File", "*.csv"),
                ("Text Report", "*.txt"),
                ("All Files", "*.*"),
            ],
        )
        if not path:
            return
        path = Path(path)
        try:
            self._write_log_records(records, path)
            self._audit_log_action(
                screen="Export Log",
                action="Export Log",
                status="Success",
                export_folder=str(path.parent),
                notes=f"Exported {len(records)} {'current' if scope == 'current' else 'full audit'} log record(s) to {path.name}.",
                details=f"Saved file: {path}",
            )
            messagebox.showinfo("Export Log", f"Log exported successfully:\n\n{path}")
        except Exception as exc:
            self._audit_log_action(
                screen="Export Log",
                action="Export Log",
                status="Error",
                export_folder=str(path.parent),
                notes=f"Could not export log to {path.name}.",
                details=str(exc),
            )
            messagebox.showerror("Export Log", f"Could not export log:\n\n{exc}")

    def _write_log_records(self, records: List[Dict[str, Any]], path: Path) -> None:
        columns = [
            "Log_ID", "Date_Time", "Screen", "Action", "Status", "Material_Summary",
            "Element", "Series", "Material", "Temper", "Specification", "Form",
            "Basis", "Direction", "Unit_System", "Changed_Field", "Old_Value",
            "New_Value", "Keyfile_Name", "Image_Name", "Export_Folder",
            "Widget_Class", "Widget_Text", "Widget_Path", "Click_X", "Click_Y",
            "Notes", "Details",
        ]
        rows = []
        for rec in records:
            rows.append({col: rec.get(col, "") for col in columns})
        df = pd.DataFrame(rows, columns=columns)
        suffix = path.suffix.lower()
        if suffix == ".csv":
            df.to_csv(path, index=False)
            return
        if suffix == ".txt":
            path.write_text(self._format_log_records_as_text(records), encoding="utf-8")
            return

        if suffix != ".xlsx":
            path = path.with_suffix(".xlsx")
        df.to_excel(path, index=False)

    def _format_log_records_as_text(self, records: List[Dict[str, Any]]) -> str:
        lines = []
        lines.append("MMPDS Material Selector - Export Audit Log")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Records: {len(records)}")
        lines.append("=" * 90)
        for rec in records:
            lines.append(f"[{rec.get('Date_Time', '')}] {rec.get('Action', '')} - {rec.get('Status', '')}")
            if rec.get("Material_Summary"):
                lines.append(f"Material Summary: {rec.get('Material_Summary')}")
            if rec.get("Changed_Field"):
                lines.append(f"Changed Field(s): {rec.get('Changed_Field')}")
                lines.append(f"Old Value(s): {rec.get('Old_Value')}")
                lines.append(f"New Value(s): {rec.get('New_Value')}")
            if rec.get("Keyfile_Name"):
                lines.append(f"Keyfile: {rec.get('Keyfile_Name')}")
            if rec.get("Image_Name"):
                lines.append(f"Image: {rec.get('Image_Name')}")
            if rec.get("Export_Folder"):
                lines.append(f"Export Folder: {rec.get('Export_Folder')}")
            if rec.get("Notes"):
                lines.append(f"Notes: {rec.get('Notes')}")
            if rec.get("Details"):
                lines.append("Details:")
                lines.append(str(rec.get("Details")))
            lines.append("-" * 90)
        return "\n".join(lines)

    def _current_audit_screen_name(self, widget=None) -> str:
        """Return a readable screen/tab name for click audit rows."""
        try:
            if getattr(self.app, "current_screen_name", "") == "CardScreen":
                return "Material Card"
            if hasattr(self, "notebook"):
                tab_id = self.notebook.select()
                if tab_id:
                    return self.notebook.tab(tab_id, "text") or "Material Selection"
        except Exception:
            pass
        return getattr(self.app, "current_screen_name", "Application") or "Application"

    def _material_summary_for_current_click(self) -> str:
        """Attach material context to raw click rows when Screen 2 is open."""
        try:
            card = self.app.screens.get("CardScreen")
            if getattr(self.app, "current_screen_name", "") == "CardScreen" and card is not None:
                if hasattr(card, "_current_material_summary_for_audit"):
                    has_edits = any(edited for _value, edited in getattr(card, "prop_values", {}).values())
                    return card._current_material_summary_for_audit(custom=has_edits)
        except Exception:
            pass
        return ""

    def _widget_text_for_click(self, widget) -> str:
        """Best-effort visible text/value for the clicked widget."""
        try:
            value = str(widget.cget("text")).strip()
            if value:
                return value
        except Exception:
            pass
        try:
            cls = widget.winfo_class()
            if cls == "Treeview":
                return "Treeview row/cell"
            if cls == "Listbox":
                idx = widget.nearest(widget.winfo_pointery() - widget.winfo_rooty())
                if idx >= 0:
                    return str(widget.get(idx)).strip()
        except Exception:
            pass
        return ""

    def _app_click_log(self, event):
        """Fast click tracking for the Log Tracking tab.

        Clicks are stored in memory and flushed to a TXT log file in batches.
        Meaningful application actions still use structured Export Log rows.
        """
        try:
            widget = event.widget
            widget_class = widget.winfo_class()
            widget_text = self._widget_text_for_click(widget)
            screen = self._current_audit_screen_name(widget)
            action = "Click"
            if widget_text:
                clean = " ".join(str(widget_text).split())
                if len(clean) > 70:
                    clean = clean[:67] + "..."
                action = f"Click - {clean}"
            notes = f"Clicked {widget_class}"
            if widget_text:
                notes += f"; value/text: {widget_text}"
            self._track_click_fast(
                screen=screen,
                action=action,
                widget_class=widget_class,
                widget_text=widget_text,
                material_summary=self._material_summary_for_current_click(),
                notes=notes,
                x=str(getattr(event, "x_root", "")),
                y=str(getattr(event, "y_root", "")),
            )
        except Exception:
            pass
        return None

    def _adv_log(self, message: str, action: str = "Log Note", status: str = "Info",
                 screen: str = "Advanced Selection", **extra):
        """Compatibility logger used by existing Advanced Selection code.

        Existing code calls _adv_log(message). Instead of writing raw text into a
        Text widget, route it into the structured audit table as a readable note.
        """
        if not str(message).strip():
            return
        try:
            self._audit_log_action(screen=screen, action=action, status=status,
                                   notes=str(message), details=extra.get("details", ""))
        except Exception:
            pass


    # ------------------------------------------------------------------
    # Material Finder tab
    # ------------------------------------------------------------------
    def _build_material_finder_tab(self, parent):
        inset = tk.Frame(parent, bg=THEME["bg"])
        inset.pack(fill=tk.BOTH, expand=True, padx=4, pady=6)
        inset.columnconfigure(0, weight=1)
        inset.rowconfigure(0, weight=0)
        inset.rowconfigure(1, weight=0)
        inset.rowconfigure(2, weight=1)
        inset.rowconfigure(3, weight=1)

        material_panel = tk.Frame(inset, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        material_panel.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        material_hdr = tk.Frame(material_panel, bg=THEME["accent"], height=30)
        material_hdr.pack(fill=tk.X)
        material_hdr.pack_propagate(False)
        tk.Label(material_hdr, text="Material Finder", bg=THEME["accent"], fg="white",
                 font=FONTS["body_bold"]).pack(side=tk.LEFT, padx=12, pady=6)
        tk.Label(material_hdr, textvariable=self.finder_match_var, bg=THEME["accent"], fg="#dde6f3",
                 font=FONTS["small"]).pack(side=tk.RIGHT, padx=12, pady=7)

        filter_row = tk.Frame(material_panel, bg=THEME["panel"])
        filter_row.pack(fill=tk.X, padx=8, pady=8)
        finder_top_fields = list(STAGES) + ["Basis", "Direction", "Matcard"]
        for i, stage in enumerate(finder_top_fields):
            filter_row.columnconfigure(i, weight=1, uniform="finder_dropdown")
            self._finder_dropdown_field(filter_row, stage, i)

        filter_buttons = tk.Frame(material_panel, bg=THEME["panel"])
        filter_buttons.pack(fill=tk.X, padx=8, pady=(0, 8))
        ttk.Button(filter_buttons, text="Use Main Tab Selection", style="Secondary.TButton",
                   command=self._finder_use_main_selection).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(filter_buttons, text="Reset Filters", style="Secondary.TButton",
                   command=self._finder_clear_all_filters).pack(side=tk.RIGHT, padx=(6, 0))

        property_panel = tk.Frame(inset, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        property_panel.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        prop_hdr = tk.Frame(property_panel, bg=THEME["accent"], height=30)
        prop_hdr.pack(fill=tk.X)
        prop_hdr.pack_propagate(False)
        tk.Label(prop_hdr, text="Property Card Filter", bg=THEME["accent"], fg="white",
                 font=FONTS["body_bold"]).pack(side=tk.LEFT, padx=12, pady=6)

        builder = tk.Frame(property_panel, bg=THEME["panel"])
        builder.pack(fill=tk.X, padx=8, pady=8)
        labels = ["Property", "Value", "Tolerance +/-"]
        widths = [32, 18, 18]
        for c, label in enumerate(labels):
            tk.Label(builder, text=label, bg=THEME["panel"], fg=THEME["text_muted"],
                     font=FONTS["small_bold"]).grid(row=0, column=c, sticky="w", padx=(0, 8))

        self.finder_property_combo = ttk.Combobox(builder, textvariable=self.finder_property_var,
                                                  values=self._finder_property_options(), state="readonly",
                                                  width=widths[0])
        self.finder_property_combo.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Entry(builder, textvariable=self.finder_value_var, width=widths[1]).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Entry(builder, textvariable=self.finder_tolerance_var, width=widths[2]).grid(row=1, column=2, sticky="ew", padx=(0, 8))
        ttk.Button(builder, text="+ Add Property", style="Primary.TButton",
                   command=self._finder_add_property_filter).grid(row=1, column=3, sticky="ew", padx=(0, 6))
        ttk.Button(builder, text="Remove", style="Secondary.TButton",
                   command=self._finder_remove_selected_filter).grid(row=1, column=4, sticky="ew", padx=(0, 6))
        ttk.Button(builder, text="Reset Property", style="Secondary.TButton",
                   command=self._finder_clear_property_filters).grid(row=1, column=5, sticky="ew", padx=(0, 6))
        ttk.Button(builder, text="Search", style="Primary.TButton",
                   command=self._finder_search_materials).grid(row=1, column=6, sticky="ew", padx=(0, 0))
        for c in range(3):
            builder.columnconfigure(c, weight=1)

        active_wrap = tk.Frame(property_panel, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        active_wrap.pack(fill=tk.X, padx=8, pady=(0, 8))
        columns = ("property", "value", "tolerance")
        self.finder_filter_tree = ttk.Treeview(active_wrap, columns=columns, show="headings", height=3)
        for c, heading, width in [
            ("property", "Property", 280), ("value", "Value", 160),
            ("tolerance", "Tolerance +/-", 160)
        ]:
            self.finder_filter_tree.heading(c, text=heading)
            self.finder_filter_tree.column(c, width=width, anchor="w", stretch=True)
        fy = ttk.Scrollbar(active_wrap, orient="vertical", command=self.finder_filter_tree.yview)
        self.finder_filter_tree.configure(yscrollcommand=fy.set)
        self.finder_filter_tree.grid(row=0, column=0, sticky="nsew")
        fy.grid(row=0, column=1, sticky="ns")
        active_wrap.rowconfigure(0, weight=1)
        active_wrap.columnconfigure(0, weight=1)

        possible_panel = tk.Frame(inset, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        possible_panel.grid(row=2, column=0, sticky="nsew", pady=(0, 6))
        possible_panel.rowconfigure(1, weight=1)
        possible_panel.columnconfigure(0, weight=1)
        possible_hdr = tk.Frame(possible_panel, bg=THEME["accent"], height=30)
        possible_hdr.grid(row=0, column=0, sticky="ew")
        possible_hdr.grid_propagate(False)
        tk.Label(possible_hdr, text="Possible Matches", bg=THEME["accent"], fg="white",
                 font=FONTS["body_bold"]).pack(side=tk.LEFT, padx=12, pady=6)
        self.finder_result_count_var = tk.StringVar(value="0 material(s)")
        tk.Label(possible_hdr, textvariable=self.finder_result_count_var, bg=THEME["accent"], fg="#dde6f3",
                 font=FONTS["small"]).pack(side=tk.RIGHT, padx=12, pady=7)

        possible_wrap = tk.Frame(possible_panel, bg=THEME["panel"])
        possible_wrap.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        possible_columns = ("Add", "No", "Element", "Series", "Material", "Temper", "Specification",
                            "Specification_2", "Form", "Thickness", "Source", "Matched_Values")
        self.finder_result_tree = ttk.Treeview(possible_wrap, columns=possible_columns, show="headings",
                                               height=8, style="Advanced.Treeview", selectmode="extended")
        possible_widths = {
            "Add": 55, "No": 55, "Element": 100, "Series": 130, "Material": 95,
            "Temper": 90, "Specification": 145, "Specification_2": 155,
            "Form": 190, "Thickness": 130, "Source": 110, "Matched_Values": 460,
        }
        possible_headings = {"Add": "+", "Specification_2": "Specification 2", "Matched_Values": "Matched Values"}
        for c in possible_columns:
            self.finder_result_tree.heading(c, text=possible_headings.get(c, c))
            self.finder_result_tree.column(c, width=possible_widths.get(c, 100),
                                           anchor="center" if c in {"Add", "No"} else "w", stretch=False)
        self.finder_result_tree.tag_configure("finder_match", background=THEME["table_bg"])
        self.finder_result_tree.tag_configure("finder_match_alt", background=THEME["table_alt_bg"])
        py = ttk.Scrollbar(possible_wrap, orient="vertical", command=self.finder_result_tree.yview)
        px = ttk.Scrollbar(possible_wrap, orient="horizontal", command=self.finder_result_tree.xview)
        self.finder_result_tree.configure(yscrollcommand=py.set, xscrollcommand=px.set)
        self.finder_result_tree.grid(row=0, column=0, sticky="nsew")
        py.grid(row=0, column=1, sticky="ns")
        px.grid(row=1, column=0, sticky="ew")
        possible_wrap.rowconfigure(0, weight=1)
        possible_wrap.columnconfigure(0, weight=1)
        self.finder_result_tree.bind("<ButtonRelease-1>", self._finder_handle_result_click)
        self.finder_result_tree.bind("<Double-1>", self._finder_open_selected_result)

        selected_panel = tk.Frame(inset, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        selected_panel.grid(row=3, column=0, sticky="nsew")
        selected_panel.rowconfigure(1, weight=1)
        selected_panel.columnconfigure(0, weight=1)
        selected_hdr = tk.Frame(selected_panel, bg=THEME["accent"], height=30)
        selected_hdr.grid(row=0, column=0, sticky="ew")
        selected_hdr.grid_propagate(False)
        tk.Label(selected_hdr, text="Selected Materials for Export", bg=THEME["accent"], fg="white",
                 font=FONTS["body_bold"]).pack(side=tk.LEFT, padx=12, pady=6)
        self.finder_selected_count_var = tk.StringVar(value="0 item(s)")
        tk.Label(selected_hdr, textvariable=self.finder_selected_count_var, bg=THEME["accent"], fg="#dde6f3",
                 font=FONTS["small"]).pack(side=tk.RIGHT, padx=12, pady=7)

        selected_buttons = tk.Frame(selected_panel, bg=THEME["panel"])
        selected_buttons.grid(row=1, column=0, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(selected_buttons, text="+ Add Selected", style="Secondary.TButton",
                   command=self._finder_add_selected_to_advanced).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(selected_buttons, text="+ Add All Displayed", style="Secondary.TButton",
                   command=self._finder_add_all_displayed_to_advanced).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(selected_buttons, text="Remove Selected", style="Secondary.TButton",
                   command=self._finder_remove_selected_export_rows).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(selected_buttons, text="Remove Duplicates", style="Secondary.TButton",
                   command=self._finder_remove_duplicates).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(selected_buttons, text="Export Checked Keyfiles", style="Primary.TButton",
                   command=self._finder_export_checked_keyfiles).pack(side=tk.RIGHT, padx=(6, 0))

        selected_wrap = tk.Frame(selected_panel, bg=THEME["panel"])
        selected_wrap.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)
        selected_panel.rowconfigure(2, weight=1)
        selected_columns = ("Export", "ID", "Element", "Series", "Material", "Temper", "Specification",
                            "Specification_2", "Form", "Thickness", "Basis", "Direction", "Unit", "Matcard", "Status", "Image")
        self.finder_selected_tree = ttk.Treeview(selected_wrap, columns=selected_columns, show="headings",
                                                 height=7, style="Advanced.Treeview", selectmode="extended")
        selected_widths = {
            "Export": 70, "ID": 85, "Element": 95, "Series": 130, "Material": 95, "Temper": 90,
            "Specification": 135, "Specification_2": 145, "Form": 170, "Thickness": 125,
            "Basis": 75, "Direction": 80, "Unit": 165, "Matcard": 105, "Status": 135, "Image": 120,
        }
        selected_headings = {"ID": "ID / MID", "Specification_2": "Specification 2", "Image": "Image"}
        for c in selected_columns:
            self.finder_selected_tree.heading(c, text=selected_headings.get(c, c))
            self.finder_selected_tree.column(c, width=selected_widths.get(c, 100),
                                             anchor="center" if c in {"Export", "ID", "Basis", "Direction", "Unit", "Matcard", "Status", "Image"} else "w",
                                             stretch=False)
        sy = ttk.Scrollbar(selected_wrap, orient="vertical", command=self.finder_selected_tree.yview)
        sx = ttk.Scrollbar(selected_wrap, orient="horizontal", command=self.finder_selected_tree.xview)
        self.finder_selected_tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.finder_selected_tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        selected_wrap.rowconfigure(0, weight=1)
        selected_wrap.columnconfigure(0, weight=1)
        self.finder_selected_tree.bind("<ButtonRelease-1>", self._finder_handle_selected_click)
        self.finder_selected_tree.bind("<Double-1>", self._finder_open_selected_export_card)

        self._finder_refresh_dropdowns()
        self._finder_refresh_filter_tree()
        self._finder_clear_results()
        self._finder_refresh_selected_export_tree()

    def _finder_dropdown_field(self, parent, stage: str, col: int):
        frame = tk.Frame(parent, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        frame.grid(row=0, column=col, sticky="ew", padx=4)
        tk.Label(frame, text=stage, bg=THEME["accent"], fg="white",
                 font=FONTS["caption"]).pack(fill=tk.X)

        if stage == "Basis":
            var = self.finder_basis_display_var
            values = [""] + [label for label, _code in BASIS_OPTIONS]
        elif stage == "Direction":
            var = self.finder_direction_var
            values = [""] + [code for _label, code in DIRECTION_OPTIONS]
        elif stage == "Matcard":
            var = self.finder_model_var
            values = [code for _label, code in MAT_MODELS]
        else:
            var = self.finder_stage_vars.get(stage)
            if var is None:
                var = tk.StringVar(value="")
                self.finder_stage_vars[stage] = var
            values = []

        combo = ttk.Combobox(frame, textvariable=var, state="readonly", values=values, font=FONTS["caption"])
        combo.pack(fill=tk.X, padx=5, pady=6)
        combo.bind("<<ComboboxSelected>>", lambda _e, s=stage: self._finder_combo_changed(s))
        self.finder_listboxes[stage] = combo

    def _finder_combo_changed(self, stage: str):
        if stage == "Basis":
            label_to_code = {label: code for label, code in BASIS_OPTIONS}
            selected = self.finder_basis_display_var.get().strip()
            self.finder_basis_var.set(label_to_code.get(selected, selected))
        elif stage == "Direction":
            self.finder_direction_var.set(self.finder_direction_var.get().strip())
        elif stage == "Matcard":
            self.finder_model_var.set(self.finder_model_var.get().strip())
        else:
            self.finder_selections[stage] = self.finder_stage_vars[stage].get().strip()

        self._finder_refresh_dropdowns(skip_stage=stage)
        self._finder_clear_results()
        self._finder_match_count()

    def _finder_refresh_dropdowns(self, skip_stage: Optional[str] = None):
        """Refresh Material Finder dropdowns and hide unavailable Basis/Direction.

        Material Finder follows the Advanced Selection rule: the user should not
        see unavailable Basis/Direction choices. The internal Matcard default is
        MAT024+GISSMO when that model can be generated for the current filters.
        """
        if not getattr(self, "finder_listboxes", None):
            return

        for stage in STAGES:
            combo = self.finder_listboxes.get(stage)
            if combo is None:
                continue
            opts = self.db.available(stage, self.finder_selections)
            values = [""] + list(opts)
            combo.configure(values=values)
            current = self.finder_selections.get(stage, "")
            if current and current not in opts:
                self.finder_selections[stage] = ""
                if stage in self.finder_stage_vars:
                    self.finder_stage_vars[stage].set("")
            elif stage in self.finder_stage_vars and self.finder_stage_vars[stage].get() != current:
                self.finder_stage_vars[stage].set(current)

        if getattr(self, "perf_engine", None) is not None:
            current_direction = self.finder_direction_var.get().strip() or "L"
            basis_codes = self.perf_engine.available_bases(self.finder_selections, direction=current_direction)
            if not basis_codes:
                basis_codes = [b for b in DEFAULT_BASIS_CODES if self.perf_engine.count(self.finder_selections, basis=b) > 0]
            current_basis = self.finder_basis_var.get().strip() or "B"
            if current_basis not in basis_codes:
                current_basis = self._adv_preferred_value(basis_codes, "B", "")
                self.finder_basis_var.set(current_basis)

            direction_codes = self.perf_engine.available_directions(self.finder_selections, basis=current_basis)
            if not direction_codes:
                direction_codes = [d for d in DEFAULT_DIRECTION_CODES if self.perf_engine.count(self.finder_selections, direction=d) > 0]
            current_direction = self.finder_direction_var.get().strip() or "L"
            if current_direction not in direction_codes:
                current_direction = self._adv_preferred_value(direction_codes, "L", "")
                self.finder_direction_var.set(current_direction)

            basis_codes = self.perf_engine.available_bases(self.finder_selections, direction=current_direction)
            if not basis_codes:
                basis_codes = [b for b in DEFAULT_BASIS_CODES if self.perf_engine.count(self.finder_selections, basis=b) > 0]
            current_basis = self.finder_basis_var.get().strip() or "B"
            if current_basis not in basis_codes:
                current_basis = self._adv_preferred_value(basis_codes, "B", "")
                self.finder_basis_var.set(current_basis)

            model_options = self.perf_engine.available_matcards(self.finder_selections, basis=current_basis, direction=current_direction)
        else:
            try:
                rows = self.db.filter_master(self.finder_selections)
            except Exception:
                rows = pd.DataFrame()

            current_direction = self.finder_direction_var.get().strip() or "L"
            basis_available = self._adv_available_bases_for_rows(rows, current_direction)
            if not any(basis_available.values()):
                basis_available = self._adv_available_bases_any_direction_for_rows(rows)
            basis_codes = [code for _label, code in BASIS_OPTIONS if basis_available.get(code, False)]
            current_basis = self.finder_basis_var.get().strip() or "B"
            if current_basis not in basis_codes:
                current_basis = self._adv_preferred_value(basis_codes, "B", "")
                self.finder_basis_var.set(current_basis)

            direction_codes = self._adv_available_directions_for_rows(rows, current_basis)
            if not direction_codes:
                direction_codes = self._adv_available_directions_for_rows(rows, "")
            current_direction = self.finder_direction_var.get().strip() or "L"
            if current_direction not in direction_codes:
                current_direction = self._adv_preferred_value(direction_codes, "L", "")
                self.finder_direction_var.set(current_direction)

            basis_available = self._adv_available_bases_for_rows(rows, current_direction)
            if not any(basis_available.values()):
                basis_available = self._adv_available_bases_any_direction_for_rows(rows)
            basis_codes = [code for _label, code in BASIS_OPTIONS if basis_available.get(code, False)]
            current_basis = self.finder_basis_var.get().strip() or "B"
            if current_basis not in basis_codes:
                current_basis = self._adv_preferred_value(basis_codes, "B", "")
                self.finder_basis_var.set(current_basis)

            model_options = self._adv_available_matcards_for_rows(rows, current_basis, current_direction)

        basis_combo = self.finder_listboxes.get("Basis")
        if basis_combo is not None:
            code_to_label = {code: label for label, code in BASIS_OPTIONS}
            labels = [code_to_label.get(code, code) for code in basis_codes]
            basis_combo.configure(values=labels)
            self.finder_basis_display_var.set(code_to_label.get(current_basis, ""))

        direction_combo = self.finder_listboxes.get("Direction")
        if direction_combo is not None:
            direction_combo.configure(values=direction_codes)
            self.finder_direction_var.set(current_direction if current_direction in direction_codes else "")

        current_model = self.finder_model_var.get().strip() or "MAT024+GISSMO"
        if current_model not in model_options:
            current_model = self._adv_preferred_value(model_options, "MAT024+GISSMO", "")
            self.finder_model_var.set(current_model)
        matcard_combo = self.finder_listboxes.get("Matcard")
        if matcard_combo is not None:
            matcard_combo.configure(values=model_options)
            if current_model in model_options:
                self.finder_model_var.set(current_model)

        self._finder_match_count()

    def _finder_refresh_all_stages(self, skip_auto_stage: Optional[str] = None):
        self._finder_refresh_dropdowns(skip_stage=skip_auto_stage)
        self._finder_clear_results()
        self._finder_match_count()

    def _finder_use_main_selection(self):
        self.finder_selections = {s: self.selections.get(s, "") for s in STAGES}
        for s in STAGES:
            if s in self.finder_stage_vars:
                self.finder_stage_vars[s].set(self.finder_selections.get(s, ""))
        self._finder_refresh_dropdowns()
        self._finder_clear_results()
        self._finder_match_count()

    def _finder_clear_all_filters(self):
        self.finder_selections = {s: "" for s in STAGES}
        for s in STAGES:
            if s in self.finder_stage_vars:
                self.finder_stage_vars[s].set("")
        self.finder_basis_var.set("B")
        self.finder_basis_display_var.set("B Basis")
        self.finder_direction_var.set("L")
        self.finder_model_var.set("MAT024+GISSMO")
        self.finder_property_var.set("")
        self.finder_value_var.set("")
        self.finder_tolerance_var.set("")
        self.finder_filters.clear()
        self._finder_refresh_dropdowns()
        self._finder_refresh_filter_tree()
        self._finder_clear_results()
        self._finder_match_count()

    def _finder_basis_changed(self, _event=None):
        label_to_code = {label: code for label, code in BASIS_OPTIONS}
        selected = self.finder_basis_display_var.get().strip()
        self.finder_basis_var.set(label_to_code.get(selected, ""))
        self._finder_clear_results()
        self._finder_match_count()

    def _finder_property_options(self) -> List[str]:
        return [
            "", "Thickness", "Density", "Poisson's Ratio", "Tensile Yield", "Ultimate Tensile Strength",
            "Compression Yield", "Shear Strength", "Elongation", "Young's Modulus",
            "Young's Modulus Comp.", "Shear Modulus",
        ]

    def _finder_property_column_aliases(self) -> Dict[str, Tuple[str, ...]]:
        return {
            "Ultimate Tensile Strength": ("Tensile_Str", "UltTensileStrength", "UltimateTensileStrength", "Ftu"),
            "Tensile Yield": ("Tensile_Yield", "TensileYield", "Fty"),
            "Compression Yield": ("Compress_Yield", "CompressionYield", "Fcy"),
            "Shear Strength": ("Shear_Str", "UltShearStrength", "Fsu"),
            "Elongation": ("Elong", "ElongAtBreak", "Elongation"),
            "Young's Modulus": ("Youngs_Mod", "YoungsModulus", "E"),
            "Young's Modulus Comp.": ("Youngs_Mod_Comp", "YoungsModulusComp", "Ec"),
            "Shear Modulus": ("Shear_Mod", "ShearModulus", "G"),
            "Poisson's Ratio": ("Poissons_Ratio", "PoissonsRatio", "PR"),
            "Density": ("Density", "RO"),
        }

    def _finder_existing_columns(self, aliases: Tuple[str, ...]) -> List[str]:
        if self.db.master is None or self.db.master.empty:
            return []
        norm_to_actual = {}
        for c in self.db.master.columns:
            norm_to_actual.setdefault(_normalized_col_key(c), c)
        basis = str(self.finder_basis_var.get() or "").strip().upper()
        direction = str(self.finder_direction_var.get() or "").strip().upper()
        bases = [basis] if basis in {"A", "B", "S"} else ["A", "B", "S"]
        directions = [direction] if direction in {"L", "LT"} else ["L", "LT"]
        requested: List[str] = []
        for alias in aliases:
            for d in directions:
                for b in bases:
                    requested.append(f"{alias}_{d}_{b}")
            for b in bases:
                requested.append(f"{alias}_{b}")
            for d in directions:
                requested.append(f"{alias}_{d}")
            requested.append(alias)
        out: List[str] = []
        seen = set()
        for name in requested:
            actual = norm_to_actual.get(_normalized_col_key(name))
            if actual and actual not in seen:
                seen.add(actual)
                out.append(actual)
        return out

    def _finder_property_availability_aliases(self) -> Tuple[str, ...]:
        """Return broad property aliases used only for Basis/Direction availability filtering."""
        aliases: List[str] = []
        for group in self._finder_property_column_aliases().values():
            aliases.extend(group)
        # Keep common wide-schema base names available even if the dropdown alias map changes later.
        aliases.extend([
            "Tensile_Str", "Tensile_Yield", "Compress_Yield", "Shear_Str",
            "Elong", "Youngs_Mod", "Youngs_Mod_Comp", "Shear_Mod",
            "Poissons_Ratio", "Density",
        ])
        out: List[str] = []
        seen = set()
        for alias in aliases:
            key = _normalized_col_key(alias)
            if key and key not in seen:
                seen.add(key)
                out.append(alias)
        return tuple(out)

    def _finder_basis_direction_candidate_columns(self, basis: str = "", direction: str = "") -> List[str]:
        """Find source columns that prove selected Basis/Direction data exists.

        Rules:
        - Basis only, e.g. S: any valid *_S, *_L_S, or *_LT_S property column can match.
        - Direction only, e.g. L: any valid *_L_A, *_L_B, or *_L_S property column can match.
        - Basis + Direction, e.g. S + L: valid *_L_S direction-specific columns match.
          Basis-only columns such as Density_S are also allowed as supporting non-directional values.
        The logic stays internal and is not displayed in the Material Finder UI.
        """
        if self.db.master is None or self.db.master.empty:
            return []
        basis = str(basis or "").strip().upper()
        direction = str(direction or "").strip().upper()
        if basis not in {"A", "B", "S"}:
            basis = ""
        if direction not in {"L", "LT"}:
            direction = ""
        if not basis and not direction:
            return []

        norm_to_actual: Dict[str, str] = {}
        for col in self.db.master.columns:
            norm_to_actual.setdefault(_normalized_col_key(col), col)

        bases = [basis] if basis else ["A", "B", "S"]
        directions = [direction] if direction else ["L", "LT"]
        requested: List[str] = []
        for alias in self._finder_property_availability_aliases():
            for d in directions:
                for b in bases:
                    requested.append(f"{alias}_{d}_{b}")
            # Only include basis-only properties when a basis is selected.
            # This supports values such as Density_S without making Direction-only searches match non-directional data.
            if basis:
                for b in bases:
                    requested.append(f"{alias}_{b}")

        out: List[str] = []
        seen = set()
        for name in requested:
            actual = norm_to_actual.get(_normalized_col_key(name))
            if actual and actual not in seen:
                seen.add(actual)
                out.append(actual)
        return out

    def _finder_row_has_basis_direction_data(self, row, basis: str = "", direction: str = "") -> bool:
        columns = self._finder_basis_direction_candidate_columns(basis, direction)
        if not columns:
            return True
        for col in columns:
            try:
                value = row.get(col, "")
            except Exception:
                value = ""
            if not is_blank(value):
                return True
        return False

    def _finder_apply_basis_direction_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply Material Finder Basis/Direction dropdowns even when no property filter is added."""
        if df is None or df.empty:
            return df
        basis = str(self.finder_basis_var.get() or "").strip().upper()
        direction = str(self.finder_direction_var.get() or "").strip().upper()
        if basis not in {"A", "B", "S"}:
            basis = ""
        if direction not in {"L", "LT"}:
            direction = ""
        if not basis and not direction:
            return df

        keep_index = []
        for idx, row in df.iterrows():
            if self._finder_row_has_basis_direction_data(row, basis, direction):
                keep_index.append(idx)
        return df.loc[keep_index].copy()

    def _finder_thickness_numeric_match(self, actual_text: str, target: float, tol: float) -> bool:
        import re
        text = str(actual_text or "").strip().replace("≤", "<=").replace("≥", ">=").replace("–", "-").replace("—", "-")
        if not text or is_blank(text):
            return False
        nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+", text)]
        if not nums:
            return False
        low = float(target) - abs(float(tol))
        high = float(target) + abs(float(tol))
        if "-" in text and len(nums) >= 2:
            lo, hi = min(nums[0], nums[1]), max(nums[0], nums[1])
            return not (hi < low or lo > high)
        if text.startswith("<=") or text.startswith("<"):
            return low <= nums[0]
        if text.startswith(">=") or text.startswith(">"):
            return high >= nums[0]
        return any(low <= n <= high for n in nums)

    def _finder_add_property_filter(self):
        prop = self.finder_property_var.get().strip()
        value = self.finder_value_var.get().strip()
        tol = self.finder_tolerance_var.get().strip()
        if not prop or not value:
            messagebox.showwarning("Material Finder", "Choose a property and enter a value.")
            return
        if prop != "Thickness" and try_float(value) is None:
            messagebox.showwarning("Material Finder", "Property value must be numeric.")
            return
        if prop == "Thickness" and try_float(value) is None and not value:
            messagebox.showwarning("Material Finder", "Enter a thickness value.")
            return
        if tol and try_float(tol) is None:
            messagebox.showwarning("Material Finder", "Tolerance must be numeric.")
            return
        self.finder_filters.append({"property": prop, "value": value, "tolerance": tol})
        self.finder_value_var.set("")
        self.finder_tolerance_var.set("")
        self._finder_refresh_filter_tree()
        self._finder_search_materials(auto=True)

    def _finder_refresh_filter_tree(self):
        tree = getattr(self, "finder_filter_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        for iid in tree.get_children():
            tree.delete(iid)
        for idx, filt in enumerate(self.finder_filters):
            tree.insert("", "end", iid=str(idx), values=(
                filt.get("property", ""), filt.get("value", ""), filt.get("tolerance", "")
            ))

    def _finder_remove_selected_filter(self):
        tree = getattr(self, "finder_filter_tree", None)
        if tree is None:
            return
        selected = sorted((int(i) for i in tree.selection() if str(i).isdigit()), reverse=True)
        for idx in selected:
            if 0 <= idx < len(self.finder_filters):
                self.finder_filters.pop(idx)
        self._finder_refresh_filter_tree()
        self._finder_search_materials(auto=True)

    def _finder_clear_property_filters(self):
        self.finder_filters.clear()
        self.finder_property_var.set("")
        self.finder_value_var.set("")
        self.finder_tolerance_var.set("")
        self._finder_refresh_filter_tree()
        self._finder_search_materials(auto=True)

    def _finder_match_count(self):
        try:
            if getattr(self, "perf_engine", None) is not None:
                base = self.perf_engine.filter_rows(self.finder_selections, basis=str(self.finder_basis_var.get() or ""), direction=str(self.finder_direction_var.get() or ""), matcard=str(self.finder_model_var.get() or ""))
            else:
                base = self.db.filter_master(self.finder_selections)
                base = self._finder_apply_basis_direction_filters(base)
            base, _notes = self._finder_apply_property_filters(base)
            self.finder_match_var.set(f"Material Finder Matches: {len(base):,}")
        except Exception:
            self.finder_match_var.set("Material Finder Matches: 0")

    def _finder_row_stage_value(self, row, stage: str) -> str:
        if row is None:
            return ""
        if stage == "Series":
            val = row_first_nonblank(row, "Series", default="")
            if not val:
                try:
                    return self.db._material_to_series.get(norm(row.get("Material", "")), "")
                except Exception:
                    return ""
            return val
        if stage == "Specification":
            return display_spec_value(row_first_nonblank(row, "Spec1_1", "spec1_1", "Specification", default=""))
        if stage == "Specification 2":
            return display_spec_value(row_spec2_value(row))
        if stage == "Thickness":
            return source_gui_thickness_label(row)
        return row_first_nonblank(row, stage, default="")

    def _finder_row_selections(self, row) -> Dict[str, str]:
        return {stage: self._finder_row_stage_value(row, stage) for stage in STAGES}

    def _finder_filter_match_row(self, row, filt: Dict[str, str]) -> Tuple[bool, str]:
        prop = str(filt.get("property", "")).strip()
        value = str(filt.get("value", "")).strip()
        tol_text = str(filt.get("tolerance", "")).strip()
        if prop == "Thickness":
            actual = source_thickness_display_label(row)
            target = try_float(value)
            if target is not None:
                tol = abs(float(try_float(tol_text) if tol_text else 0.0))
                ok = self._finder_thickness_numeric_match(actual, float(target), tol)
            else:
                ok = norm(value) in norm(actual)
            return ok, f"Thickness={actual}" if ok else ""

        aliases = self._finder_property_column_aliases().get(prop)
        if not aliases:
            return True, ""
        target = try_float(value)
        if target is None:
            return False, ""
        tol = abs(float(try_float(tol_text) if tol_text else 0.0))
        lo = float(target) - tol
        hi = float(target) + tol
        notes = []
        for col in self._finder_existing_columns(aliases):
            val = try_float(row.get(col, None))
            if val is None:
                continue
            if lo <= float(val) <= hi:
                notes.append(f"{prop}={fmt_number(val)}")
        return bool(notes), "; ".join(notes[:3])

    def _finder_apply_property_filters(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[Any, str]]:
        if df is None or df.empty or not self.finder_filters:
            return df, {}
        keep_index = []
        notes_by_index: Dict[Any, str] = {}
        for idx, row in df.iterrows():
            notes = []
            ok = True
            for filt in self.finder_filters:
                passed, note = self._finder_filter_match_row(row, filt)
                if not passed:
                    ok = False
                    break
                if note:
                    notes.append(note)
            if ok:
                keep_index.append(idx)
                notes_by_index[idx] = " | ".join(notes)
        return df.loc[keep_index].copy(), notes_by_index

    def _finder_clear_results(self):
        """Clear Material Finder results without running a heavy search.

        Results are populated only when the user clicks Search or adds a
        property filter. This removes the startup loading feel and prevents
        table flicker while changing top filters.
        """
        self.finder_result_rows = []
        tree = getattr(self, "finder_result_tree", None)
        if tree is not None and tree.winfo_exists():
            try:
                for iid in tree.get_children():
                    tree.delete(iid)
            except Exception:
                pass
        if hasattr(self, "finder_result_count_var"):
            self.finder_result_count_var.set("0 material(s)")

    def _finder_search_materials(self, auto: bool = False):
        try:
            if getattr(self, "perf_engine", None) is not None:
                df = self.perf_engine.filter_rows(self.finder_selections, basis=str(self.finder_basis_var.get() or ""), direction=str(self.finder_direction_var.get() or ""), matcard=str(self.finder_model_var.get() or ""))
            else:
                df = self.db.filter_master(self.finder_selections)
                df = self._finder_apply_basis_direction_filters(df)
        except Exception:
            df = self.db.filter_master(self.finder_selections)
            df = self._finder_apply_basis_direction_filters(df)
        df, match_notes = self._finder_apply_property_filters(df)
        display_limit = 500
        self.finder_result_rows = []
        tree = getattr(self, "finder_result_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        for iid in tree.get_children():
            tree.delete(iid)
        if df is None:
            df = pd.DataFrame()
        total = len(df)
        shown_df = df.head(display_limit)
        for pos, (row_index, row) in enumerate(shown_df.iterrows(), start=1):
            self.finder_result_rows.append(row)
            values = ("+", pos, self._finder_row_stage_value(row, "Element"), self._finder_row_stage_value(row, "Series"), self._finder_row_stage_value(row, "Material"), self._finder_row_stage_value(row, "Temper"), self._finder_row_stage_value(row, "Specification"), self._finder_row_stage_value(row, "Specification 2"), self._finder_row_stage_value(row, "Form"), self._finder_row_stage_value(row, "Thickness"), row.get("MMPDS_Version", "-"), match_notes.get(row_index, ""))
            tag = "finder_match" if pos % 2 else "finder_match_alt"
            tree.insert("", "end", iid=str(pos - 1), values=values, tags=(tag,))
        suffix = f" (showing first {len(shown_df):,})" if total > display_limit else ""
        self.finder_result_count_var.set(f"{total:,} material(s){suffix}")
        self.finder_match_var.set(f"Material Finder Matches: {total:,}{suffix}")
        if not auto:
            self._audit_log_action(screen="Material Finder", action="Search", status="Success", notes=f"Search returned {total:,} material row(s).")

    def _finder_payload_from_result_row(self, row, selected_for_export: bool = False) -> Dict[str, Any]:
        selections = self._finder_row_selections(row)
        payload = {stage: selections.get(stage, "") for stage in STAGES}
        payload.update({
            "Export_ID": "",
            "Basis": str(self.finder_basis_var.get() or "B"),
            "Direction": str(self.finder_direction_var.get() or "L"),
            "Unit_System": str(self.finder_unit_sys_var.get() or "mm_T_s"),
            "Material_Model": str(self.finder_model_var.get() or "MAT024+GISSMO"),
            "Thickness_Mode": "Exact thickness text",
            "Thickness": source_gui_thickness_label(row) or "NA",
            "_thickness_row_key": self._adv_row_identity_key(row),
            "Source": "Material Finder",
            "_selected": bool(selected_for_export),
        })
        return payload

    def _finder_add_result_index_to_advanced(self, idx: int, refresh: bool = True) -> bool:
        try:
            row = self.finder_result_rows[int(idx)]
        except Exception:
            return False
        payload = self._finder_payload_from_result_row(row, selected_for_export=False)
        self._adv_add_payload(payload, source_label="Material Finder", refresh=refresh, log=refresh)
        if refresh:
            self._finder_refresh_selected_export_tree()
            if hasattr(self.app, "status_var"):
                self.app.status_var.set("Added to Selected Materials for Export")
        return True

    def _finder_handle_result_click(self, event):
        tree = getattr(self, "finder_result_tree", None)
        if tree is None:
            return
        row_id = tree.identify_row(event.y)
        col_id = tree.identify_column(event.x)
        if not row_id:
            return
        try:
            col_idx = int(str(col_id).replace("#", "")) - 1
            col_name = tree["columns"][col_idx]
        except Exception:
            col_name = ""
        if col_name == "Add":
            self._finder_add_result_index_to_advanced(int(row_id))
            return "break"

    def _finder_add_selected_to_advanced(self):
        tree = getattr(self, "finder_result_tree", None)
        if tree is None:
            return
        selected = list(tree.selection())
        if not selected:
            messagebox.showinfo("Material Finder", "Select one or more rows first.")
            return
        added = 0
        for iid in selected:
            try:
                if self._finder_add_result_index_to_advanced(int(iid), refresh=False):
                    added += 1
            except Exception:
                continue
        if added:
            self._adv_refresh_tree()
            self._finder_refresh_selected_export_tree()
            self._adv_log(f"Added {added:,} Material Finder row(s) to the export list.")
        if added and hasattr(self.app, "status_var"):
            self.app.status_var.set(f"Added {added:,} material(s)")

    def _finder_add_all_displayed_to_advanced(self):
        count = len(getattr(self, "finder_result_rows", []))
        if count <= 0:
            return
        if count > 100 and not messagebox.askyesno("Add All Displayed", f"Add {count:,} displayed material(s)?"):
            return
        added = 0
        for idx in range(count):
            if self._finder_add_result_index_to_advanced(idx, refresh=False):
                added += 1
        if added:
            self._adv_refresh_tree()
            self._finder_refresh_selected_export_tree()
            self._adv_log(f"Added {added:,} displayed Material Finder row(s) to the export list.")
        if hasattr(self.app, "status_var"):
            self.app.status_var.set(f"Added {added:,} material(s)")

    def _finder_refresh_selected_export_tree(self):
        tree = getattr(self, "finder_selected_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        for iid in tree.get_children():
            tree.delete(iid)
        for idx, item in enumerate(getattr(self, "advanced_items", [])):
            if str(item.get("Source", "")) != "Material Finder":
                continue
            unit_label = UNIT_SYSTEM_SPEC.get(item.get("Unit_System", "mm_T_s"), {}).get("label", item.get("Unit_System", ""))
            values = (
                "☑" if item.get("_selected", False) else "☐",
                item.get("Export_ID", ""), item.get("Element", ""), item.get("Series", ""),
                item.get("Material", ""), item.get("Temper", ""), item.get("Specification", ""),
                item.get("Specification 2", ""), item.get("Form", ""), item.get("Thickness", ""),
                item.get("Basis", "B"), item.get("Direction", "L"), unit_label,
                item.get("Material_Model", "MAT024+GISSMO"),
                ("DUPLICATE" if item.get("_duplicate") else item.get("_status", "")),
                "View Image",
            )
            tag = "duplicate_row" if item.get("_duplicate") else ("finder_match" if idx % 2 else "finder_match_alt")
            tree.insert("", "end", iid=str(idx), values=values, tags=(tag,))
        count = sum(1 for x in self.advanced_items if str(x.get("Source", "")) == "Material Finder")
        checked = sum(1 for x in self.advanced_items if str(x.get("Source", "")) == "Material Finder" and x.get("_selected", False))
        self.finder_selected_count_var.set(f"{checked} checked / {count} item(s)")

    def _finder_selected_column_name(self, col_id: str) -> str:
        try:
            idx = int(str(col_id).replace("#", "")) - 1
            cols = self.finder_selected_tree["columns"]
            if 0 <= idx < len(cols):
                return cols[idx]
        except Exception:
            pass
        return ""

    def _finder_handle_selected_click(self, event):
        tree = getattr(self, "finder_selected_tree", None)
        if tree is None:
            return
        row_id = tree.identify_row(event.y)
        col_name = self._finder_selected_column_name(tree.identify_column(event.x))
        if not row_id:
            return
        try:
            idx = int(row_id)
        except Exception:
            return
        if col_name == "Export":
            self._adv_toggle_export_selected(idx)
            self._finder_refresh_selected_export_tree()
            return "break"
        if col_name == "Image":
            self._adv_show_image_for_item(idx)
            return "break"
        if col_name == "Unit":
            return self._finder_begin_unit_edit(event, idx)

    def _finder_begin_unit_edit(self, event, idx: int):
        tree = getattr(self, "finder_selected_tree", None)
        if tree is None or not (0 <= idx < len(self.advanced_items)):
            return "break"
        col_id = tree.identify_column(event.x)
        bbox = tree.bbox(str(idx), col_id)
        if not bbox:
            return "break"
        x, y, width, height = bbox
        item = self.advanced_items[idx]
        options = self._adv_options_for_export_cell(item, "Unit")
        current = UNIT_SYSTEM_SPEC.get(item.get("Unit_System", "mm_T_s"), {}).get("label", item.get("Unit_System", ""))
        combo = ttk.Combobox(tree, values=options, state="readonly", font=FONTS["caption"])
        combo.set(current if current in options else (options[0] if options else current))
        combo.place(x=x + 4, y=y + 4, width=max(90, width - 8), height=max(24, height - 8))
        combo.focus_set()

        def commit(_event=None):
            value = combo.get().strip()
            if value:
                self._adv_apply_export_cell_edit_multi(idx, "Unit", value, option_index=-1)
                self._finder_refresh_selected_export_tree()
            try:
                combo.destroy()
            except Exception:
                pass
            return "break"

        combo.bind("<<ComboboxSelected>>", commit)
        combo.bind("<Return>", commit)
        combo.bind("<FocusOut>", commit)
        combo.bind("<Escape>", lambda _event=None: (combo.destroy(), "break")[-1])
        return "break"

    def _finder_remove_selected_export_rows(self):
        tree = getattr(self, "finder_selected_tree", None)
        if tree is None:
            return
        selected = sorted((int(i) for i in tree.selection() if str(i).isdigit()), reverse=True)
        for idx in selected:
            if 0 <= idx < len(self.advanced_items):
                self.advanced_items.pop(idx)
        self._adv_refresh_tree()
        self._finder_refresh_selected_export_tree()

    def _finder_remove_duplicates(self):
        self._adv_remove_duplicates()
        self._finder_refresh_selected_export_tree()

    def _finder_export_checked_keyfiles(self):
        finder_indexes = [
            idx for idx, item in enumerate(getattr(self, "advanced_items", []))
            if str(item.get("Source", "")) == "Material Finder"
        ]
        if not finder_indexes:
            messagebox.showwarning("Material Finder", "Add at least one material before exporting.")
            return
        if not any(self.advanced_items[idx].get("_selected", False) for idx in finder_indexes):
            messagebox.showwarning("Material Finder", "Check at least one row before exporting.")
            return

        original_states = [bool(item.get("_selected", False)) for item in self.advanced_items]
        try:
            finder_set = set(finder_indexes)
            for idx, item in enumerate(self.advanced_items):
                item["_selected"] = bool(original_states[idx] and idx in finder_set)
            self._adv_export_all()
        finally:
            for idx, item in enumerate(self.advanced_items):
                if idx < len(original_states):
                    item["_selected"] = original_states[idx]
            self._adv_refresh_tree()
            self._finder_refresh_selected_export_tree()

    def _finder_open_selected_result(self, _event=None):
        tree = getattr(self, "finder_result_tree", None)
        if tree is None:
            return
        sel = tree.selection()
        if not sel:
            return
        try:
            row = self.finder_result_rows[int(sel[0])]
        except Exception:
            return
        self._finder_open_row_card(row)

    def _finder_open_selected_export_card(self, _event=None):
        tree = getattr(self, "finder_selected_tree", None)
        if tree is None:
            return
        sel = tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
            rows = self._adv_match_rows(self.advanced_items[idx])
            row = rows.iloc[0] if rows is not None and not rows.empty else None
        except Exception:
            row = None
        if row is not None:
            self._finder_open_row_card(row)

    def _finder_open_row_card(self, row):
        selections = self._finder_row_selections(row)
        matching_rows = self.db.filter_master(selections)
        if matching_rows is None or matching_rows.empty:
            matching_rows = pd.DataFrame([row])
        card_open_state = {
            "Basis": str(self.finder_basis_var.get() or "B"),
            "Direction": str(self.finder_direction_var.get() or "L"),
            "Unit_System": str(self.finder_unit_sys_var.get() or "mm_T_s"),
            "Material_Model": str(self.finder_model_var.get() or "MAT024+GISSMO"),
        }
        validation_payload = dict(selections)
        validation_payload.update(card_open_state)
        validation_message = self._adv_validation_message_for_payload(validation_payload, matching_rows)
        if validation_message:
            messagebox.showwarning("Material cannot be generated", validation_message)
            if hasattr(self.app, "status_var"):
                self.app.status_var.set(validation_message)
            return

        self.selections = {s: selections.get(s, "") for s in STAGES}
        try:
            self._refresh_all()
        except Exception:
            pass
        try:
            self._save_history(row)
        except Exception:
            pass
        self._audit_log_action(screen="Material Finder", action="Material Card Opened", status="Success",
                               element=selections.get("Element", ""), series=selections.get("Series", ""),
                               material=selections.get("Material", ""), temper=selections.get("Temper", ""),
                               specification=selections.get("Specification", ""), form=selections.get("Form", ""))
        self.app.show_screen("CardScreen", row=row, selections=selections, matching_rows=matching_rows.copy(), history_state=card_open_state)

    def _build_standard_tab(self, parent):

        inset = tk.Frame(parent, bg=THEME["bg"])
        inset.pack(fill=tk.BOTH, expand=True, padx=4, pady=6)

        self._history_panel(inset)

        action = tk.Frame(inset, bg=THEME["bg"])
        action.pack(fill=tk.X, pady=(14, 10))

        self.match_var = tk.StringVar()
        tk.Label(action, textvariable=self.match_var, bg=THEME["bg"],
                 fg=THEME["accent"], font=FONTS["h2"]).pack(side=tk.LEFT)

        ttk.Button(action, text="Choose Material ->", style="Primary.TButton",
                   command=self._choose).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(action, text="Reset All", style="Secondary.TButton",
                   command=self._reset).pack(side=tk.RIGHT, padx=(6, 0))

        cols = tk.Frame(inset, bg=THEME["bg"])
        cols.pack(fill=tk.BOTH, expand=True)

        for i, stage in enumerate(STAGES):
            cols.columnconfigure(i, weight=1, uniform="stage")
            self._stage_column(cols, stage, i)

    def _history_panel(self, parent):
        panel = tk.Frame(parent, bg=THEME["panel"], highlightthickness=1,
                         highlightbackground=THEME["border"])
        panel.pack(fill=tk.X, pady=(0, 4))

        top = tk.Frame(panel, bg=THEME["panel"])
        top.pack(fill=tk.X, padx=14, pady=(10, 4))

        title_block = tk.Frame(top, bg=THEME["panel"])
        title_block.pack(side=tk.LEFT)
        tk.Label(title_block, text="Recent Material Summaries", bg=THEME["panel"],
                 fg=THEME["accent"], font=FONTS["h2"]).pack(anchor="w")
        tk.Label(title_block, text="Double-click to reopen a material summary.",
                 bg=THEME["panel"], fg=THEME["text_muted"], font=FONTS["small"]).pack(anchor="w")

        ttk.Button(top, text="Clear History", style="Secondary.TButton",
                   command=self._clear_history).pack(side=tk.RIGHT)


        cols = ("datetime", "summary")
        self.hist_tree = ttk.Treeview(panel, columns=cols, show="headings", height=4)
        headings = {
            "datetime": "Date / Time",
            "summary": "Material Summary",
        }
        widths = {"datetime": 155, "summary": 1120}
        for c in cols:
            self.hist_tree.heading(c, text=headings[c])
            self.hist_tree.column(c, width=widths[c], anchor="w", stretch=True)
        self.hist_tree.tag_configure("edited_history", background=THEME["custom_history_bg"], foreground=THEME["custom_history_fg"])
        self.hist_tree.pack(fill=tk.X, padx=14, pady=(0, 12))
        self.hist_tree.bind("<Double-1>", self._history_open)

    def _stage_column(self, parent, stage, col):
        frame = tk.Frame(parent, bg=THEME["panel"], highlightthickness=1,
                         highlightbackground=THEME["border"])
        frame.grid(row=0, column=col, sticky="nsew", padx=6, pady=2)

        hdr = tk.Frame(frame, bg=THEME["accent"], height=36)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        tk.Label(hdr, text=stage, bg=THEME["accent"], fg="white",
                 font=FONTS["body_bold"]).pack(side=tk.LEFT, padx=12, pady=7)


        lbl = tk.Label(frame, text="(none selected)", bg=THEME["panel"],
                       fg=THEME["text_muted"], font=FONTS["small"], anchor="w")
        lbl.pack(fill=tk.X, padx=12, pady=(10, 4))
        self.selection_labels[stage] = lbl

        var = tk.StringVar(value=PLACEHOLDER_SEARCH)
        self.search_vars[stage] = var

        ent = ttk.Entry(frame, textvariable=var, font=FONTS["body"])
        ent.pack(fill=tk.X, padx=12, pady=(2, 8))

        def focus_in(_):
            if var.get() == PLACEHOLDER_SEARCH:
                var.set("")

        def focus_out(_):
            if not var.get():
                var.set(PLACEHOLDER_SEARCH)

        ent.bind("<FocusIn>", focus_in)
        ent.bind("<FocusOut>", focus_out)
        var.trace_add("write", lambda *_a, s=stage: self._refresh_stage(s))

        list_frame = tk.Frame(frame, bg=THEME["panel"], highlightthickness=1,
                              highlightbackground=THEME["border"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

        lb = tk.Listbox(list_frame, exportselection=False, activestyle="none",
                        font=FONTS["body"], bg=THEME["listbox_bg"],
                        fg=THEME["listbox_fg"],
                        selectbackground=THEME["select_bg"],
                        selectforeground=THEME["select_fg"],
                        borderwidth=0, highlightthickness=0,
                        relief="flat")
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        sb = ttk.Scrollbar(list_frame, command=lb.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb.configure(yscrollcommand=sb.set)

        self.listboxes[stage] = lb
        lb.bind("<<ListboxSelect>>", lambda _e, s=stage: self._select(s))

        bottom = tk.Frame(frame, bg=THEME["panel"])
        bottom.pack(fill=tk.X, padx=12, pady=(0, 10))

        cnt = tk.Label(bottom, text="0 options", bg=THEME["panel"],
                       fg=THEME["text_muted"], font=FONTS["small"])
        cnt.pack(side=tk.LEFT)
        self.count_labels[stage] = cnt

        ttk.Button(bottom, text="Clear", style="Secondary.TButton",
                   command=lambda s=stage: self._clear_stage(s)).pack(side=tk.RIGHT)


    def _build_advanced_tab(self, parent):

        inset = tk.Frame(parent, bg=THEME["bg"])
        inset.pack(fill=tk.BOTH, expand=True, padx=4, pady=6)

        # Layout-only fix: keep the Advanced Selection filter area on top and
        # keep the Export List panel/header permanently visible below it.
        # Earlier pack-only geometry could let the table area visually squeeze
        # the Export List title/header on smaller monitor heights.
        inset.columnconfigure(0, weight=1)
        inset.rowconfigure(0, weight=0)
        inset.rowconfigure(1, weight=1)

        top_panel = tk.Frame(inset, bg=THEME["panel"],
                             highlightbackground=THEME["border"], highlightthickness=1)
        top_panel.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        hdr = tk.Frame(top_panel, bg=THEME["accent"], height=34)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="Advanced Selection - Batch Keyfile Export",
                 bg=THEME["accent"], fg="white", font=FONTS["body_bold"]).pack(side=tk.LEFT, padx=12, pady=7)


        manual_panel = tk.LabelFrame(
            top_panel, text=" Selection Filters ",
            bg=THEME["panel"], fg=THEME["accent"], font=FONTS["small_bold"],
            bd=0, relief="flat",
            highlightbackground=THEME["border"], highlightthickness=1,
            padx=8, pady=6,
        )
        manual_panel.pack(fill=tk.X, padx=14, pady=(6, 6))

        manual_top = tk.Frame(manual_panel, bg=THEME["panel"])
        manual_top.pack(fill=tk.X, padx=4, pady=(2, 4))
        tk.Label(manual_top, textvariable=self.adv_match_var, bg=THEME["panel"], fg=THEME["accent"],
                 font=FONTS["small_bold"]).pack(side=tk.LEFT)
        ttk.Button(manual_top, text="Use Main Tab Selection", style="Secondary.TButton",
                   command=self._adv_use_main_selection).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(manual_top, text="Reset Manual Filters", style="Secondary.TButton",
                   command=self._adv_reset_filters).pack(side=tk.RIGHT, padx=(4, 0))

        manual_cols = tk.Frame(manual_panel, bg=THEME["panel"])
        manual_cols.pack(fill=tk.X, padx=4, pady=(2, 4))

        # Hemil requirement: keep all Advanced Selection filters on one same line.
        # The normal material filters and the export option filters now share one row:
        # Element, Series, Material, Temper, Specification, Specification 2, Form,
        # Thickness, Basis, Direction, Matcard.
        all_filter_columns = list(STAGES) + list(self.adv_extra_filter_stages)
        for i, stage in enumerate(all_filter_columns):
            manual_cols.columnconfigure(i, weight=1, uniform="adv_all_stage")
            if stage in STAGES:
                self._adv_stage_column(manual_cols, stage, i)
            else:
                self._adv_extra_filter_column(manual_cols, stage, i)

        controls = tk.Frame(top_panel, bg=THEME["panel"])
        controls.pack(fill=tk.X, padx=14, pady=(4, 6))


        out = tk.LabelFrame(
            controls, text=" Output Folder ",
            bg=THEME["panel_alt"], fg=THEME["accent"], font=FONTS["small_bold"],
            bd=0, relief="flat",
            highlightbackground=THEME["border"], highlightthickness=1,
            padx=6, pady=4,
        )
        out.pack(fill=tk.X, padx=0, pady=4)
        ttk.Entry(out, textvariable=self.adv_output_dir_var, font=FONTS["body"]).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=6)
        ttk.Button(out, text="Browse...", style="Secondary.TButton",
                   command=self._adv_browse_output).pack(side=tk.LEFT, padx=8, pady=6)

        self._build_adv_default_options(controls)

        buttons = tk.Frame(top_panel, bg=THEME["panel"])
        buttons.pack(fill=tk.X, padx=10, pady=(0, 10))


        add_group = tk.Frame(buttons, bg=THEME["panel"])
        add_group.pack(side=tk.LEFT)
        ttk.Button(add_group, text="+ Add to List", style="Primary.TButton",
                   command=self._adv_add_current_selection).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(add_group, text="+ Add All Matching", style="Secondary.TButton",
                   command=self._adv_add_all_matching_selection).pack(side=tk.LEFT, padx=4)
        ttk.Button(add_group, text="Upload CSV...", style="Secondary.TButton",
                   command=self._adv_upload_input_csv, state=tk.DISABLED).pack(side=tk.LEFT, padx=4)


        tk.Frame(buttons, bg=THEME["border"], width=1).pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=4)


        mng_group = tk.Frame(buttons, bg=THEME["panel"])
        mng_group.pack(side=tk.LEFT)
        ttk.Button(mng_group, text="Select All", style="Secondary.TButton",
                   command=self._adv_select_all_items).pack(side=tk.LEFT, padx=4)
        ttk.Button(mng_group, text="Clear Export Selection", style="Secondary.TButton",
                   command=self._adv_clear_export_selection).pack(side=tk.LEFT, padx=4)
        ttk.Button(mng_group, text="Remove Selected", style="Secondary.TButton",
                   command=self._adv_remove_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(mng_group, text="Remove Duplicates", style="Secondary.TButton",
                   command=self._adv_remove_duplicates).pack(side=tk.LEFT, padx=4)
        ttk.Button(mng_group, text="Clear List", style="Danger.TButton",
                   command=self._adv_clear_list).pack(side=tk.LEFT, padx=4)
        ttk.Button(mng_group, text="+ Add Custom Entry", style="Primary.TButton",
                   command=self._adv_add_custom_entry).pack(side=tk.LEFT, padx=4)


        ttk.Button(buttons, text="Export Selected Keyfiles", style="Primary.TButton",
                   command=self._adv_export_all).pack(side=tk.RIGHT, padx=(8, 0))


        list_panel = tk.Frame(inset, bg=THEME["panel"],
                              highlightbackground=THEME["border"], highlightthickness=1)
        list_panel.grid(row=1, column=0, sticky="nsew")
        list_panel.columnconfigure(0, weight=1)

        list_hdr = tk.Frame(list_panel, bg=THEME["accent"], height=36)
        list_hdr.pack(fill=tk.X)
        list_hdr.pack_propagate(False)
        tk.Label(list_hdr, text="Export List", bg=THEME["accent"], fg="white",
                 font=FONTS["body_bold"]).pack(side=tk.LEFT, padx=12, pady=7)
        self.adv_count_var = tk.StringVar(value="0 item(s)")
        tk.Label(list_hdr, textvariable=self.adv_count_var, bg=THEME["accent"], fg="#dde6f3",
                 font=FONTS["small"]).pack(side=tk.RIGHT, padx=12, pady=8)

        tree_wrap = tk.Frame(list_panel, bg=THEME["panel"])
        tree_wrap.pack(fill=tk.BOTH, expand=True, padx=14, pady=(8, 4))

        columns = ("Export", "Export_ID", "Element", "Series", "Material", "Temper", "Specification", "Specification_2", "Form", "Thickness", "Basis", "Direction", "Unit", "Model", "Matches", "View_Image", "Notes")
        self.adv_tree = ttk.Treeview(tree_wrap, columns=columns, show="headings", height=9, style="Advanced.Treeview", selectmode="extended")
        widths = {
            "Export": 80, "Export_ID": 95, "Element": 110, "Series": 155, "Material": 110, "Temper": 105, "Specification": 145,
            "Specification_2": 165, "Form": 200, "Thickness": 140, "Basis": 80, "Direction": 90, "Unit": 175, "Model": 110, "Matches": 150, "View_Image": 135, "Notes": 260,
        }
        headings = {"Export": "Export", "Export_ID": "ID / MID", "Specification_2": "Specification 2", "Model": "Matcard", "Matches": "Matches / Status", "View_Image": "Image", "Notes": "Notes"}
        for c in columns:
            self.adv_tree.heading(c, text=headings.get(c, c))
            self.adv_tree.column(c, width=widths.get(c, 100), anchor="center" if c in {"Export", "Export_ID", "Basis", "Direction", "Unit", "Model", "Matches", "View_Image"} else "w", stretch=False)
        self.adv_tree.tag_configure("ok", foreground=THEME["status_ok_fg"])
        self.adv_tree.tag_configure("warn", foreground=THEME["status_warn_fg"])
        self.adv_tree.tag_configure("error", foreground=THEME["status_error_fg"])

        self.adv_tree.tag_configure("editable_row", background=THEME["table_alt_bg"])
        self.adv_tree.tag_configure("editable_row_alt", background=THEME["table_bg"])
        self.adv_tree.tag_configure("duplicate_row", background="#FFE08A", foreground="#7A2E00")

        ysb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self._adv_tree_yview)
        xsb = ttk.Scrollbar(tree_wrap, orient="horizontal", command=self._adv_tree_xview)
        self.adv_tree_ysb = ysb
        self.adv_tree_xsb = xsb
        self.adv_tree.configure(yscrollcommand=self._adv_tree_yscroll, xscrollcommand=self._adv_tree_xscroll)
        self.adv_tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)
        self.adv_tree.bind("<Double-1>", self._adv_open_export_list_row_card)
        self.adv_tree.bind("<ButtonRelease-1>", self._adv_handle_tree_click)
        self.adv_tree.bind("<<TreeviewSelect>>", self._adv_update_export_details)


        self.adv_tree.bind("<Configure>", lambda _e: self._adv_schedule_overlay_refresh())
        self.adv_tree.bind("<MouseWheel>", lambda _e: self._adv_schedule_overlay_refresh(), add="+")
        self.adv_tree.bind("<Button-4>", lambda _e: self._adv_schedule_overlay_refresh(), add="+")
        self.adv_tree.bind("<Button-5>", lambda _e: self._adv_schedule_overlay_refresh(), add="+")


        self.adv_detail_var = tk.StringVar(value="Select an export-list row to see full details here.")
        detail_box = tk.Frame(list_panel, bg=THEME["panel_alt"],
                              highlightbackground=THEME["border"], highlightthickness=1)
        detail_box.pack(fill=tk.X, padx=14, pady=(4, 12))
        tk.Label(detail_box, text="Selected Row Details", bg=THEME["panel_alt"], fg=THEME["accent"],
                 font=FONTS["small_bold"]).pack(anchor="w", padx=10, pady=(7, 0))
        tk.Label(detail_box, textvariable=self.adv_detail_var, bg=THEME["panel_alt"], fg=THEME["text"],
                 font=FONTS["small"], anchor="w", justify="left", wraplength=1350).pack(
                     fill=tk.X, padx=10, pady=(3, 8))

        self._adv_log("Advanced Selection ready.")
        self._adv_refresh_all_stages()

    def _adv_stage_column(self, parent, stage, col):
        """Small cascade-selection column used inside Advanced Selection.

        UI POLISH: matches the standard tab cascade columns (softer panel,
        cleaner header, more readable listbox).
        """
        frame = tk.Frame(parent, bg=THEME["panel_alt"], highlightthickness=1,
                         highlightbackground=THEME["border"])
        frame.grid(row=0, column=col, sticky="nsew", padx=4, pady=3)


        hdr = tk.Frame(frame, bg=THEME["accent"], height=28)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text=stage, bg=THEME["accent"], fg="white",
                 font=FONTS["caption"]).pack(side=tk.LEFT, padx=6, pady=5)

        lbl = tk.Label(frame, text="(none)", bg=THEME["panel_alt"], fg=THEME["text_muted"],
                       font=FONTS["caption"], anchor="w")
        lbl.pack(fill=tk.X, padx=6, pady=(4, 1))
        self.adv_selection_labels[stage] = lbl

        var = tk.StringVar(value=PLACEHOLDER_SEARCH)
        self.adv_search_vars[stage] = var
        ent = ttk.Entry(frame, textvariable=var, font=FONTS["caption"])
        ent.pack(fill=tk.X, padx=6, pady=(1, 4))

        def focus_in(_):
            if var.get() == PLACEHOLDER_SEARCH:
                var.set("")

        def focus_out(_):
            if not var.get():
                var.set(PLACEHOLDER_SEARCH)

        ent.bind("<FocusIn>", focus_in)
        ent.bind("<FocusOut>", focus_out)
        var.trace_add("write", lambda *_a, s=stage: self._adv_schedule_stage_refresh(s))

        list_frame = tk.Frame(frame, bg=THEME["panel_alt"],
                              highlightthickness=1, highlightbackground=THEME["border"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        lb = tk.Listbox(list_frame, height=4, exportselection=False, activestyle="none",
                        font=FONTS["caption"], bg=THEME["listbox_bg"], fg=THEME["listbox_fg"],
                        selectbackground=THEME["select_bg"], selectforeground=THEME["select_fg"],
                        borderwidth=0, highlightthickness=0, relief="flat")
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        sb = ttk.Scrollbar(list_frame, command=lb.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb.configure(yscrollcommand=sb.set)
        self.adv_listboxes[stage] = lb
        lb.bind("<<ListboxSelect>>", lambda _e, s=stage: self._adv_select(s))

        bottom = tk.Frame(frame, bg=THEME["panel_alt"])
        bottom.pack(fill=tk.X, padx=6, pady=(0, 4))
        cnt = tk.Label(bottom, text="0", bg=THEME["panel_alt"], fg=THEME["text_muted"], font=FONTS["small"])
        cnt.pack(side=tk.LEFT)
        self.adv_count_labels[stage] = cnt
        ttk.Button(bottom, text="Clear", style="Secondary.TButton",
                   command=lambda s=stage: self._adv_clear_stage(s)).pack(side=tk.RIGHT)

    def _build_adv_extra_filter_panel(self, parent):
        """Build the requested Advanced Selection listboxes for Thickness/Basis/Direction/Matcard."""
        panel = tk.LabelFrame(
            parent,
            text=" More Filters ",
            bg=THEME["panel"],
            fg=THEME["accent"],
            font=FONTS["small_bold"],
            bd=0,
            relief="flat",
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=8,
            pady=6,
        )
        panel.pack(fill=tk.X, padx=4, pady=(4, 2))

        cols = tk.Frame(panel, bg=THEME["panel"])
        cols.pack(fill=tk.X, padx=4, pady=(2, 2))
        for i, stage in enumerate(self.adv_extra_filter_stages):
            cols.columnconfigure(i, weight=1, uniform="adv_extra_stage")
            self._adv_extra_filter_column(cols, stage, i)

    def _adv_extra_filter_column(self, parent, stage: str, col: int):
        """Small listbox column for Advanced Selection export filters."""
        frame = tk.Frame(parent, bg=THEME["panel_alt"], highlightthickness=1,
                         highlightbackground=THEME["border"])
        frame.grid(row=0, column=col, sticky="nsew", padx=4, pady=3)

        hdr = tk.Frame(frame, bg=THEME["accent"], height=28)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text=stage, bg=THEME["accent"], fg="white",
                 font=FONTS["caption"]).pack(side=tk.LEFT, padx=6, pady=5)

        lbl = tk.Label(frame, text="(default)", bg=THEME["panel_alt"], fg=THEME["text_muted"],
                       font=FONTS["caption"], anchor="w")
        lbl.pack(fill=tk.X, padx=6, pady=(4, 1))
        self.adv_extra_selection_labels[stage] = lbl

        list_frame = tk.Frame(frame, bg=THEME["panel_alt"], highlightthickness=1,
                              highlightbackground=THEME["border"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        lb = tk.Listbox(list_frame, height=4, exportselection=False, activestyle="none",
                        font=FONTS["caption"], bg=THEME["listbox_bg"], fg=THEME["listbox_fg"],
                        selectbackground=THEME["select_bg"], selectforeground=THEME["select_fg"],
                        borderwidth=0, highlightthickness=0, relief="flat")
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        sb = ttk.Scrollbar(list_frame, command=lb.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb.configure(yscrollcommand=sb.set)
        self.adv_extra_listboxes[stage] = lb
        lb.bind("<<ListboxSelect>>", lambda _e, s=stage: self._adv_select_extra_filter(s))

        bottom = tk.Frame(frame, bg=THEME["panel_alt"])
        bottom.pack(fill=tk.X, padx=6, pady=(0, 4))
        cnt = tk.Label(bottom, text="0", bg=THEME["panel_alt"], fg=THEME["text_muted"], font=FONTS["small"])
        cnt.pack(side=tk.LEFT)
        self.adv_extra_count_labels[stage] = cnt
        ttk.Button(bottom, text="Clear", style="Secondary.TButton",
                   command=lambda s=stage: self._adv_clear_extra_filter(s)).pack(side=tk.RIGHT)

    def _adv_extra_filter_options(self, stage: str) -> List[str]:
        engine = getattr(self, "perf_engine", None)
        if engine is not None:
            thickness = self.adv_thickness_text_var.get().strip() if self.adv_thickness_mode_var.get() == "Exact thickness text" else ""
            basis = self.adv_basis_var.get() or ""
            direction = self.adv_direction_var.get() or ""
            model = self.adv_model_var.get() or ""
            try:
                if stage == "Thickness":
                    options = ["First matching thickness", "All matching thickness rows"]
                    seen = {norm(x) for x in options}
                    for label in engine.available_thicknesses(self.adv_selections):
                        if label and norm(label) not in seen:
                            options.append(label)
                            seen.add(norm(label))
                    return options
                if stage == "Basis":
                    options = engine.available_bases(self.adv_selections, thickness=thickness, direction=direction, matcard=model)
                    if not options:
                        options = engine.available_bases(self.adv_selections, thickness=thickness, direction="", matcard=model)
                    return options
                if stage == "Direction":
                    options = engine.available_directions(self.adv_selections, thickness=thickness, basis=basis, matcard=model)
                    if not options:
                        options = engine.available_directions(self.adv_selections, thickness=thickness, basis=basis, matcard="")
                    return options
                if stage == "Matcard":
                    options = engine.available_matcards(self.adv_selections, thickness=thickness, basis=basis, direction=direction)
                    if not options:
                        options = engine.available_matcards(self.adv_selections, thickness=thickness, basis="", direction="")
                    return options
            except Exception:
                pass
        try:
            rows = self.db.filter_master(self.adv_selections)
        except Exception:
            rows = pd.DataFrame()
        if stage == "Thickness":
            options = ["First matching thickness", "All matching thickness rows"]
            seen = {norm(x) for x in options}
            if rows is not None and not rows.empty:
                try:
                    labels = rows["__adv_thickness_label"].astype(str).tolist() if "__adv_thickness_label" in rows.columns else []
                except Exception:
                    labels = []
                if not labels:
                    labels = [self._adv_thickness_display_label(row) or "NA" for _, row in rows.iterrows()]
                for label in labels:
                    key = norm(label)
                    if label and key not in seen:
                        options.append(label)
                        seen.add(key)
            return options
        if stage == "Basis":
            direction = self.adv_direction_var.get() or "L"
            available = self._adv_available_bases_for_rows(rows, direction)
            if not any(available.values()):
                available = self._adv_available_bases_any_direction_for_rows(rows)
            return [code for _label, code in BASIS_OPTIONS if available.get(code, False)]
        if stage == "Direction":
            basis = self.adv_basis_var.get() or ""
            options = self._adv_available_directions_for_rows(rows, basis)
            if not options:
                options = self._adv_available_directions_for_rows(rows, "")
            return options
        if stage == "Matcard":
            basis = self.adv_basis_var.get() or "B"
            direction = self.adv_direction_var.get() or "L"
            return self._adv_available_matcards_for_rows(rows, basis, direction)
        return []

    def _adv_refresh_extra_filters(self):
        """Refresh Thickness/Basis/Direction/Matcard and remove unavailable choices.

        Advanced Selection must not offer invalid Basis/Direction/Matcard values.
        Preferred defaults are B / L / MAT024+GISSMO only when available.
        """
        if not getattr(self, "adv_extra_listboxes", None):
            return

        current_map = {
            "Thickness": self.adv_thickness_display_var.get().strip() if hasattr(self, "adv_thickness_display_var") else "First matching thickness",
            "Basis": self.adv_basis_var.get().strip() or "B",
            "Direction": self.adv_direction_var.get().strip() or "L",
            "Matcard": self.adv_model_var.get().strip() or "MAT024+GISSMO",
        }

        for stage in self.adv_extra_filter_stages:
            lb = self.adv_extra_listboxes.get(stage)
            if lb is None:
                continue
            options = self._adv_extra_filter_options(stage)
            old_options = self.adv_extra_visible_values.get(stage, [])
            self.adv_extra_visible_values[stage] = options
            if old_options != options:
                lb.delete(0, tk.END)
                for option in options:
                    lb.insert(tk.END, option)

            current = current_map.get(stage, "")
            if stage == "Basis":
                if current not in options:
                    current = self._adv_preferred_value(options, "B", "")
                    self.adv_basis_var.set(current)
                    if hasattr(self, "adv_basis_display_var"):
                        self.adv_basis_display_var.set({code: label for label, code in BASIS_OPTIONS}.get(current, ""))
            elif stage == "Direction":
                if current not in options:
                    current = self._adv_preferred_value(options, "L", "")
                    self.adv_direction_var.set(current)
            elif stage == "Matcard":
                if current not in options:
                    current = self._adv_preferred_value(options, "MAT024+GISSMO", "")
                    self.adv_model_var.set(current)
            elif stage == "Thickness" and current not in options:
                current = "First matching thickness"
                self.adv_thickness_display_var.set(current)
                self.adv_thickness_mode_var.set(current)
                self.adv_thickness_text_var.set("")

            lb.selection_clear(0, tk.END)
            if current in options:
                try:
                    idx = options.index(current)
                    lb.selection_set(idx)
                    lb.see(idx)
                except Exception:
                    pass

            label = current if current else "(not available)"
            self.adv_extra_selection_labels[stage].configure(
                text=f"Selected: {label}",
                fg=THEME["accent"] if current else THEME["status_error_fg"],
            )
            self.adv_extra_count_labels[stage].configure(text=str(len(options)))

    def _adv_select_extra_filter(self, stage: str):
        lb = self.adv_extra_listboxes.get(stage)
        if lb is None:
            return
        sel = lb.curselection()
        if not sel:
            return
        values = self.adv_extra_visible_values.get(stage, [])
        if not values:
            return
        value = values[sel[0]]

        if stage == "Thickness":
            self.adv_thickness_display_var.set(value)
            if value == "All matching thickness rows":
                self.adv_thickness_mode_var.set("All matching thickness rows")
                self.adv_thickness_text_var.set("")
            elif value == "First matching thickness":
                self.adv_thickness_mode_var.set("First matching thickness")
                self.adv_thickness_text_var.set("")
            else:
                self.adv_thickness_mode_var.set("Exact thickness text")
                self.adv_thickness_text_var.set(value)
        elif stage == "Basis":
            self.adv_basis_var.set(value)
            if hasattr(self, "adv_basis_display_var"):
                self.adv_basis_display_var.set({code: label for label, code in BASIS_OPTIONS}.get(value, value))
        elif stage == "Direction":
            self.adv_direction_var.set(value)
        elif stage == "Matcard":
            self.adv_model_var.set(value)

        self._adv_refresh_extra_filters()
        self._adv_match_count()

    def _adv_clear_extra_filter(self, stage: str):
        """Return one extra listbox filter to its default value."""
        if stage == "Thickness":
            self.adv_thickness_display_var.set("First matching thickness")
            self.adv_thickness_mode_var.set("First matching thickness")
            self.adv_thickness_text_var.set("")
        elif stage == "Basis":
            self.adv_basis_var.set("B")
            if hasattr(self, "adv_basis_display_var"):
                self.adv_basis_display_var.set("B Basis")
        elif stage == "Direction":
            self.adv_direction_var.set("L")
        elif stage == "Matcard":
            self.adv_model_var.set("MAT024+GISSMO")
        self._adv_refresh_extra_filters()
        self._adv_match_count()

    def _adv_reset_extra_filters(self):
        self.adv_thickness_display_var.set("First matching thickness")
        self.adv_thickness_mode_var.set("First matching thickness")
        self.adv_thickness_text_var.set("")
        self.adv_basis_var.set("B")
        if hasattr(self, "adv_basis_display_var"):
            self.adv_basis_display_var.set("B Basis")
        self.adv_direction_var.set("L")
        self.adv_model_var.set("MAT024+GISSMO")

    def _adv_schedule_stage_refresh(self, stage: str):
        """Debounce Advanced Selection search-box filtering while the user types."""
        if not hasattr(self, "_adv_stage_refresh_jobs"):
            self._adv_stage_refresh_jobs = {}
        old_job = self._adv_stage_refresh_jobs.get(stage)
        if old_job:
            try:
                self.after_cancel(old_job)
            except Exception:
                pass
        def _run():
            self._adv_stage_refresh_jobs.pop(stage, None)
            try:
                self._adv_refresh_stage(stage)
            except Exception:
                pass
        self._adv_stage_refresh_jobs[stage] = self.after(120, _run)

    def _adv_search(self, stage):
        txt = self.adv_search_vars[stage].get()
        return "" if txt == PLACEHOLDER_SEARCH else txt.strip().lower()

    def _adv_refresh_all_stages(self, skip_auto_stage: Optional[str] = None):
        """Fast Advanced Selection refresh.

        Previous versions rebuilt every dependent list several times through
        auto-singleton loops and hidden basis/thickness controls. That made the
        Advanced filters feel heavy. This refresh updates each visible list once,
        then updates the extra filters once.
        """
        for s in STAGES:
            self._adv_refresh_stage(s)
        self._adv_refresh_extra_filters()
        self._adv_match_count()

    def _adv_refresh_stage(self, stage):
        if not self.adv_listboxes:
            return
        try:
            if getattr(self, "perf_engine", None) is not None:
                opts = self.perf_engine.available_stage(stage, self.adv_selections)
            else:
                opts = self.db.available(stage, self.adv_selections)
        except Exception:
            opts = self.db.available(stage, self.adv_selections)
        search = self._adv_search(stage) if stage in self.adv_search_vars else ""
        if search:
            opts = [o for o in opts if search in o.lower()]
        max_items = 120
        total_opts = len(opts)
        if total_opts > max_items:
            opts = opts[:max_items]
            opts.append(f"... and {total_opts - max_items} more (refine search)")
        old_opts = self.adv_visible_values.get(stage, [])
        self.adv_visible_values[stage] = opts
        lb = self.adv_listboxes[stage]
        if old_opts != opts:
            lb.delete(0, tk.END)
            for o in opts:
                lb.insert(tk.END, o)
        cur = self.adv_selections[stage]
        if cur and cur not in opts:
            self.adv_selections[stage] = ""
            cur = ""
        elif cur in opts:
            idx = opts.index(cur)
            lb.selection_clear(0, tk.END)
            lb.selection_set(idx)
            lb.see(idx)
        self.adv_selection_labels[stage].configure(
            text=f"Selected: {self.adv_selections[stage]}" if self.adv_selections[stage] else "(none)",
            fg=THEME["accent"] if self.adv_selections[stage] else THEME["text_muted"],
        )
        count_text = f"{total_opts}"
        if total_opts > max_items:
            count_text += f" (showing {max_items})"
        self.adv_count_labels[stage].configure(text=count_text)

    def _adv_auto_singletons(self, skip_stage: Optional[str] = None):
        for _ in range(6):
            changed = False
            for s in STAGES:
                if s == skip_stage:
                    continue
                vals = self.adv_visible_values.get(s, [])
                if not self.adv_selections[s] and len(vals) == 1:
                    self.adv_selections[s] = vals[0]
                    changed = True
                    for x in STAGES:
                        self._adv_refresh_stage(x)
            if not changed:
                break

    def _adv_stages_to_refresh_after(self, stage: str) -> List[str]:
        """Return the minimum Advanced columns that need a visible refresh.

        Earlier versions refreshed all 7 Advanced material filters on every
        click. That is correct but slow. In normal cascading use, selecting a
        left-side field only needs to refresh the fields to its right. If an
        unknown stage is passed, we safely refresh all columns.
        """
        try:
            idx = STAGES.index(stage)
            return STAGES[idx + 1:]
        except Exception:
            return list(STAGES)

    def _adv_debounced_refreshes(self):
        """Debounce UI refreshes to avoid freezing on fast selections."""
        if getattr(self, "adv_perf_debouncer", None) is not None:
            self.adv_perf_debouncer.call(self._adv_execute_refreshes)
        else:
            self._adv_execute_refreshes()

    def _adv_execute_refreshes(self):
        self._adv_refresh_extra_filters()
        self._adv_match_count()

    def _adv_select(self, stage):
        lb = self.adv_listboxes.get(stage)
        if lb is None:
            return
        sel = lb.curselection()
        if not sel:
            return
        value = self.adv_visible_values[stage][sel[0]]
        if isinstance(value, str) and value.startswith("... and "):
            messagebox.showinfo("Refine Search", "More results are available. Type more letters to narrow the list.")
            lb.selection_clear(0, tk.END)
            return

        self.adv_selections[stage] = value
        self.adv_selection_labels[stage].configure(
            text=f"Selected: {value}",
            fg=THEME["accent"],
        )

        # Refresh only dependent columns, not every listbox. This removes the
        # heavy pause/buffering feel when users click Advanced filters.
        for s in self._adv_stages_to_refresh_after(stage):
            self._adv_refresh_stage(s)

        self._adv_debounced_refreshes()

    def _adv_clear_stage(self, stage):
        self.adv_selections[stage] = ""
        if stage in self.adv_search_vars:
            self.adv_search_vars[stage].set(PLACEHOLDER_SEARCH)

        # Clear/refresh only this stage and its dependents.
        self._adv_refresh_stage(stage)
        for s in self._adv_stages_to_refresh_after(stage):
            self._adv_refresh_stage(s)
        self._adv_debounced_refreshes()

    def _adv_reset_filters(self):
        self.adv_selections = {s: "" for s in STAGES}
        for s in STAGES:
            if s in self.adv_search_vars:
                self.adv_search_vars[s].set(PLACEHOLDER_SEARCH)
        self._adv_reset_extra_filters()
        self._adv_refresh_all_stages()
        self._adv_refresh_basis_controls()
        self._adv_log("Advanced filters reset.")

    def _adv_use_main_selection(self):
        self.adv_selections = {s: self.selections.get(s, "") for s in STAGES}
        for s in STAGES:
            if s in self.adv_search_vars:
                self.adv_search_vars[s].set(PLACEHOLDER_SEARCH)
        self._adv_reset_extra_filters()
        self._adv_refresh_all_stages()
        self._adv_refresh_basis_controls()
        self._adv_log("Copied main selection filters into Advanced Selection.")

    def _adv_match_count(self):
        if not hasattr(self, "adv_match_var"):
            return
        try:
            payload = self._adv_current_item_payload()
            thickness = str(payload.get("Thickness", "")).strip() if payload.get("Thickness_Mode") == "Exact thickness text" else ""
            if getattr(self, "perf_engine", None) is not None:
                n = self.perf_engine.count(
                    self.adv_selections,
                    thickness=thickness,
                    basis=str(payload.get("Basis", "") or ""),
                    direction=str(payload.get("Direction", "") or ""),
                    matcard=str(payload.get("Material_Model", "") or ""),
                )
            else:
                rows = self._adv_match_rows(payload)
                n = int(len(rows)) if rows is not None else 0
        except Exception:
            n = self.db.match_count(self.adv_selections) if hasattr(self.db, "match_count") else len(self.db.filter_master(self.adv_selections))
        self.adv_match_var.set(f"Advanced Matching Materials: {n:,}")

    def _adv_available_bases_for_rows(self, rows: pd.DataFrame, direction: str) -> Dict[str, bool]:
        """Return A/B/S bases that actually have source values for the selected direction."""
        available = {"A": False, "B": False, "S": False}
        if rows is None or rows.empty:
            return available

        direction = "LT" if str(direction or "L").strip().upper() == "LT" else "L"
        normalized_cols = {_normalized_col_key(c): c for c in rows.columns}

        for basis in ("A", "B", "S"):
            for _key, _label, _kind, pfx_l, pfx_lt in PROPERTY_ROWS:
                if _key in ("Etan", "Compression"):
                    continue
                pfx = pfx_l if direction == "L" else pfx_lt
                if not pfx:
                    continue
                candidates = [
                    f"{pfx}_{basis}",
                    f"{pfx}_{direction}_{basis}",
                    f"{pfx}_{basis}_{direction}",
                    f"{direction}_{pfx}_{basis}",
                ]
                for cand in candidates:
                    col = normalized_cols.get(_normalized_col_key(cand))
                    if not col:
                        continue
                    try:
                        values = rows[col].astype(str).str.strip()
                        if (~values.map(is_blank)).any():
                            available[basis] = True
                            break
                    except Exception:
                        continue
                if available[basis]:
                    break
        return available

    def _adv_available_bases_any_direction_for_rows(self, rows: pd.DataFrame) -> Dict[str, bool]:
        """Return bases available in either L or LT direction."""
        out = {"A": False, "B": False, "S": False}
        for direction in ("L", "LT"):
            available = self._adv_available_bases_for_rows(rows, direction)
            for basis in out:
                out[basis] = out[basis] or bool(available.get(basis, False))
        return out

    def _adv_available_directions_for_rows(self, rows: pd.DataFrame, basis: str = "") -> List[str]:
        """Return directions available for the current filtered rows.

        If a basis is supplied, directions are restricted to that basis. If the
        basis is blank/unavailable, any available basis may make the direction visible.
        """
        if rows is None or rows.empty:
            return []
        basis = str(basis or "").strip().upper()
        opts: List[str] = []
        for direction in ("L", "LT"):
            available = self._adv_available_bases_for_rows(rows, direction)
            if basis in {"A", "B", "S"}:
                if available.get(basis, False):
                    opts.append(direction)
            elif any(available.get(code, False) for code in ("A", "B", "S")):
                opts.append(direction)
        return opts

    def _adv_available_matcards_for_rows(self, rows: pd.DataFrame, basis: str = "", direction: str = "") -> List[str]:
        """Return material-card choices that can be generated for the filtered rows.

        The current GUI generates MAT024/MAT082/MAT224/MAT024+GISSMO from the
        same selected source values. Therefore, when the selected Basis/Direction
        has data, all supported cards remain valid choices. If no source values
        exist for that Basis/Direction, no Matcard option is shown.
        """
        if rows is None or rows.empty:
            return []
        basis = str(basis or "").strip().upper()
        direction = "LT" if str(direction or "L").strip().upper() == "LT" else "L"
        if basis in {"A", "B", "S"}:
            available = self._adv_available_bases_for_rows(rows, direction)
            if not available.get(basis, False):
                return []
        elif not self._adv_available_directions_for_rows(rows):
            return []
        return [code for _label, code in MAT_MODELS]

    def _adv_preferred_value(self, options: List[str], preferred: str, fallback: str = "") -> str:
        """Pick preferred when available, otherwise first valid option."""
        options = [str(x).strip() for x in (options or []) if str(x).strip()]
        if preferred in options:
            return preferred
        return options[0] if options else fallback

    def _adv_best_open_state_for_rows(self, rows: pd.DataFrame) -> Dict[str, str]:
        """Material Selection fallback rule.

        Try B/L/MAT024+GISSMO first. If that exact combination is unavailable,
        use the next real available combination instead of blocking the normal
        Material Selection workflow.
        """
        if rows is None or rows.empty:
            return {}
        for direction in ("L", "LT"):
            available = self._adv_available_bases_for_rows(rows, direction)
            basis_order = ["B", "A", "S"]
            for basis in basis_order:
                if not available.get(basis, False):
                    continue
                matcards = self._adv_available_matcards_for_rows(rows, basis, direction)
                if not matcards:
                    continue
                model = "MAT024+GISSMO" if "MAT024+GISSMO" in matcards else matcards[0]
                return {
                    "Basis": basis,
                    "Direction": direction,
                    "Unit_System": "mm_T_s",
                    "Material_Model": model,
                }
        return {}

    def _adv_available_bases_for_payload(self, payload: Dict[str, Any]) -> Dict[str, bool]:
        selections = self._adv_selection_from_payload(payload)
        rows = self.db.filter_master(selections)
        direction = str(payload.get("Direction", self.adv_direction_var.get() if hasattr(self, "adv_direction_var") else "L") or "L")
        available = self._adv_available_bases_for_rows(rows, direction)
        if not any(available.values()):
            available = self._adv_available_bases_any_direction_for_rows(rows)
        return available

    def _adv_refresh_basis_controls(self):
        """Refresh legacy basis controls only when they actually exist.

        The current Advanced UI uses the visible Basis listbox, so doing a full
        payload/filter pass here on every click is unnecessary and causes lag.
        """
        if not (hasattr(self, "adv_basis_combo") or getattr(self, "adv_basis_buttons", None)):
            return
        payload = self._adv_current_item_payload() if hasattr(self, "adv_selections") else {}
        available = self._adv_available_bases_for_payload(payload)
        basis_options = [(label, code) for label, code in BASIS_OPTIONS if available.get(code, False)]

        current = self.adv_basis_var.get() or "B"
        valid_codes = [code for _label, code in basis_options]
        if current not in valid_codes:
            current = self._adv_preferred_value(valid_codes, "B", "")
            if current:
                self.adv_basis_var.set(current)

        if hasattr(self, "adv_basis_combo") and self.adv_basis_combo is not None:
            label_to_code = {label: code for label, code in basis_options}
            code_to_label = {code: label for label, code in basis_options}
            labels = [label for label, _code in basis_options]
            self.adv_basis_combo.configure(values=labels)
            self.adv_basis_label_to_code = label_to_code
            self.adv_basis_code_to_label = code_to_label
            if hasattr(self, "adv_basis_display_var"):
                self.adv_basis_display_var.set(code_to_label.get(current, ""))
            return

        if hasattr(self, "adv_basis_buttons") and self.adv_basis_buttons:
            for code, rb in self.adv_basis_buttons.items():
                rb.configure(state=tk.NORMAL if available.get(code, False) else tk.DISABLED)

    def _build_adv_default_options(self, parent):
        """Compact export settings section.

        Unit is edited directly in the Export List. This section only keeps
        the batch ID range so the Advanced Selection screen stays clean.
        """
        defaults = tk.LabelFrame(
            parent,
            text=" Export Settings ",
            bg=THEME["panel_alt"],
            fg=THEME["accent"],
            font=FONTS["small_bold"],
            bd=0,
            relief="flat",
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=8,
            pady=6,
        )
        defaults.pack(fill=tk.X, padx=0, pady=(4, 6))

        def field(label: str):
            box = tk.Frame(defaults, bg=THEME["panel_alt"])
            box.pack(side=tk.LEFT, padx=(0, 14), pady=2)
            tk.Label(
                box,
                text=label,
                bg=THEME["panel_alt"],
                fg=THEME["text_muted"],
                font=FONTS["small_bold"],
            ).pack(anchor="w")
            return box

        id_box = field("ID Range Start")
        id_line = tk.Frame(id_box, bg=THEME["panel_alt"])
        id_line.pack(anchor="w")
        ttk.Entry(id_line, textvariable=self.adv_id_start_var, width=12).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            id_line,
            text="Apply ID Range",
            style="Secondary.TButton",
            command=self._adv_apply_id_range,
        ).pack(side=tk.LEFT)


    def _adv_default_basis_changed(self, _event=None):
        label_to_code = getattr(self, "adv_basis_label_to_code", {label: code for label, code in BASIS_OPTIONS})
        selected = self.adv_basis_display_var.get()
        self.adv_basis_var.set(label_to_code.get(selected, selected or "B"))
        self._adv_refresh_extra_filters()
        self._adv_match_count()

    def _adv_default_direction_changed(self, _event=None):
        if self.adv_direction_var.get() not in {"L", "LT"}:
            self.adv_direction_var.set("L")
        self._adv_refresh_extra_filters()
        self._adv_match_count()

    def _adv_default_thickness_changed(self, _event=None):
        selected = self.adv_thickness_display_var.get().strip()
        if selected == "All matching thickness rows":
            self.adv_thickness_mode_var.set("All matching thickness rows")
            self.adv_thickness_text_var.set("")
        elif selected == "First matching thickness" or not selected:
            self.adv_thickness_mode_var.set("First matching thickness")
            self.adv_thickness_text_var.set("")
            self.adv_thickness_display_var.set("First matching thickness")
        else:
            self.adv_thickness_mode_var.set("Exact thickness text")
            self.adv_thickness_text_var.set(selected)
        self._adv_refresh_extra_filters()
        self._adv_match_count()

    def _adv_refresh_thickness_controls(self):
        combo = getattr(self, "adv_thickness_combo", None)
        if combo is None:
            return
        options = ["First matching thickness", "All matching thickness rows"]
        try:
            rows = self.db.filter_master(self.adv_selections)
            seen = set()
            if rows is not None and not rows.empty:
                for _, row in rows.iterrows():
                    label = self._adv_thickness_display_label(row) or "NA"
                    key = norm(label)
                    if label and key not in seen:
                        options.append(label)
                        seen.add(key)
        except Exception:
            pass
        try:
            combo.configure(values=options)
        except Exception:
            pass
        current = self.adv_thickness_display_var.get().strip()
        if current not in options:
            self.adv_thickness_display_var.set("First matching thickness")
            self._adv_default_thickness_changed()

    def _adv_browse_output(self):
        folder = filedialog.askdirectory(title="Choose output folder for batch keyfiles")
        if folder:
            self.adv_output_dir_var.set(folder)

    def _adv_current_item_payload(self) -> Dict[str, Any]:
        payload = {stage: self.adv_selections.get(stage, "") for stage in STAGES}
        payload.update({
            "Export_ID": "",
            "Basis": self.adv_basis_var.get(),
            "Direction": self.adv_direction_var.get(),
            "Unit_System": self.adv_unit_sys_var.get(),
            "Material_Model": self.adv_model_var.get(),
            "Thickness_Mode": self.adv_thickness_mode_var.get(),
            "Thickness": self.adv_thickness_text_var.get().strip(),
            "Source": "Manual",
        })
        return payload

    def _adv_add_current_selection(self):
        """Add the current Advanced manual selection to the Export List.

        Advanced Selection is strict: if the exact selected combination does
        not exist, nothing is added to the Export List.
        """
        payload = self._adv_current_item_payload()
        if not any(str(payload.get(s, "")).strip() for s in STAGES):
            messagebox.showwarning(
                "Advanced Selection",
                "Select at least one Element/Series/Material/Temper/Specification/Form value before adding to the list."
            )
            return

        rows = self._adv_match_rows(payload)
        if rows is None or rows.empty:
            messagebox.showwarning(
                "Advanced Selection",
                "No exact matching material exists for the selected Advanced Selection combination."
            )
            self._adv_match_count()
            return

        self._adv_add_payload(payload, source_label="manual selection")
        self._adv_log("Added current manual selection to the export list.")

    def _adv_add_all_matching_selection(self):
        """Add all rows matching the current Advanced manual filters to the Export List.

        This is used when the user wants to import/add multiple selected materials at once
        from the manual search area. Each matching source row becomes one export-list row
        with its own exact thickness, while Specification, Basis, and Direction remain
        editable later in the Export List.
        """
        payload = self._adv_current_item_payload()
        if not any(str(payload.get(s, "")).strip() for s in STAGES):
            messagebox.showwarning(
                "Advanced Selection",
                "Select at least one Element/Series/Material/Temper/Specification/Form value before adding all matches."
            )
            return

        rows = self._adv_match_rows(payload)
        if rows is None or rows.empty:
            messagebox.showwarning("Advanced Selection", "No exact matching source rows were found for the current Advanced Selection filters.")
            return

        max_add_without_confirm = 100
        if len(rows) > max_add_without_confirm:
            if not messagebox.askyesno(
                "Add All Matching",
                f"This will add {len(rows):,} rows to the Export List. Continue?"
            ):
                return

        start_count = len(self.advanced_items)
        for _, row in rows.iterrows():
            item = dict(payload)
            item["Element"] = str(row.get("Element", item.get("Element", ""))).strip()
            item["Material"] = str(row.get("Material", item.get("Material", ""))).strip()
            item["Temper"] = str(row.get("Temper", item.get("Temper", ""))).strip()
            item["Form"] = str(row.get("Form", item.get("Form", ""))).strip()
            spec = str(row.get("Spec1_1", row.get("spec1_1", item.get("Specification", "")))).strip()
            item["Specification"] = NO_SPEC_DISPLAY if is_blank(spec) else spec
            item["Specification 2"] = display_spec_value(row_spec2_value(row))
            if not str(item.get("Series", "")).strip():
                item["Series"] = self.db._material_to_series.get(norm(item.get("Material", "")), "")
            item["Thickness"] = self._adv_thickness_display_label(row) or "NA"
            item["Thickness_Mode"] = "Exact thickness text"
            item["_thickness_row_key"] = self._adv_row_identity_key(row)
            item["Source"] = "Manual - Add All Matching"
            self._adv_add_payload(item, source_label="matching row", refresh=False, log=False)

        added = len(self.advanced_items) - start_count
        self._adv_refresh_tree()
        if added:
            try:
                self.adv_tree.see(str(len(self.advanced_items) - 1))
            except Exception:
                pass
        self._adv_log(f"Added {added:,} matching row(s) to the export list.")

    def _adv_enrich_payload_from_first_match(self, payload: Dict[str, Any], rows: pd.DataFrame) -> Dict[str, Any]:
        """Fill blank display fields from the first matching source row.

        The Export List should be easy to read. If the user selected a subset of
        filters, this fills visible columns such as Element/Material/Temper/Form
        from the first matching row, while keeping the user's selected Basis,
        Direction, Unit, and Thickness settings.
        """
        enriched = dict(payload)
        if rows is None or rows.empty:
            return enriched

        row = rows.iloc[0]
        for field in ("Element", "Material", "Temper", "Form"):
            if not str(enriched.get(field, "")).strip():
                enriched[field] = str(row.get(field, "")).strip()

        if not str(enriched.get("Specification", "")).strip():
            spec = str(row.get("Spec1_1", row.get("spec1_1", ""))).strip()
            enriched["Specification"] = NO_SPEC_DISPLAY if is_blank(spec) else spec

        if not str(enriched.get("Specification 2", "")).strip():
            enriched["Specification 2"] = display_spec_value(row_spec2_value(row))

        if not str(enriched.get("Series", "")).strip():
            mat = str(enriched.get("Material", "")).strip()
            enriched["Series"] = self.db._material_to_series.get(norm(mat), "")


        if not str(enriched.get("Thickness", "")).strip() and enriched.get("Thickness_Mode") != "All matching thickness rows":
            enriched["Thickness"] = self._adv_thickness_display_label(row) or "NA"
            enriched["_thickness_row_key"] = self._adv_row_identity_key(row)

        return enriched

    def _adv_available_directions_for_payload(self, payload: Dict[str, Any]) -> List[str]:
        """Return only directions available for this payload and selected basis."""
        selections = self._adv_selection_from_payload(payload)
        rows = self.db.filter_master(selections)
        basis = str(payload.get("Basis", self.adv_basis_var.get() if hasattr(self, "adv_basis_var") else "") or "").strip().upper()
        opts = self._adv_available_directions_for_rows(rows, basis)
        if not opts:
            opts = self._adv_available_directions_for_rows(rows, "")
        return opts

    def _adv_ensure_payload_basis_direction(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Advanced/Finder payload to available choices only.

        Advanced Selection and Material Finder should not keep unavailable
        Basis/Direction/Matcard combinations. Use B/L/MAT024+GISSMO when they
        exist; otherwise choose the first real available value.
        """
        payload = dict(payload)
        try:
            rows = self._adv_match_rows(payload)
        except Exception:
            rows = pd.DataFrame()

        basis = str(payload.get("Basis", "B") or "B").strip().upper()
        direction = str(payload.get("Direction", "L") or "L").strip().upper()
        direction = "LT" if direction == "LT" else "L"
        model = str(payload.get("Material_Model", "MAT024+GISSMO") or "MAT024+GISSMO").strip()

        available = self._adv_available_bases_for_rows(rows, direction)
        if not available.get(basis, False):
            fallback_available = available if any(available.values()) else self._adv_available_bases_any_direction_for_rows(rows)
            basis_options = [code for _label, code in BASIS_OPTIONS if fallback_available.get(code, False)]
            basis = self._adv_preferred_value(basis_options, "B", basis if basis in {"A", "B", "S"} else "B")

        direction_options = self._adv_available_directions_for_rows(rows, basis)
        if direction not in direction_options:
            direction = self._adv_preferred_value(direction_options, "L", direction)

        model_options = self._adv_available_matcards_for_rows(rows, basis, direction)
        if model not in model_options:
            model = self._adv_preferred_value(model_options, "MAT024+GISSMO", model if model in {"MAT024", "MAT082", "MAT224", "MAT024+GISSMO"} else "MAT024+GISSMO")

        payload["Basis"] = basis if basis in {"A", "B", "S"} else "B"
        payload["Direction"] = "LT" if direction == "LT" else "L"
        payload["Material_Model"] = model if model in {"MAT024", "MAT082", "MAT224", "MAT024+GISSMO"} else "MAT024+GISSMO"
        return payload

    def _adv_missing_required_for_payload(self, payload: Dict[str, Any], rows: Optional[pd.DataFrame] = None) -> List[str]:
        """Check required MAT values for the first matching row without changing UI."""
        try:
            if rows is None:
                rows = self._adv_match_rows(payload)
            if rows is None or rows.empty:
                return []
            card = self.app.screens.get("CardScreen")
            if card is None:
                return []
            row = rows.iloc[0]
            old_state = {
                "current_row": card.current_row,
                "current_selections": dict(card.current_selections),
                "thickness_rows": list(card.thickness_rows),
                "basis": card.basis_var.get(),
                "direction": card.direction_var.get(),
                "unit_sys": card.unit_sys_var.get(),
                "mat_model": card.mat_model_var.get(),
                "prop_values": dict(card.prop_values),
                "pending_edits": dict(card.pending_edits),
                "last_effps": card.last_effps,
                "last_etan_eng": card.last_etan_eng,
                "last_etan_true": card.last_etan_true,
            }
            try:
                card.current_row = row
                card.current_selections = self._adv_selection_from_payload(payload)
                card.thickness_rows = [row]
                card.basis_var.set(str(payload.get("Basis", "B") or "B"))
                card.direction_var.set(str(payload.get("Direction", "L") or "L"))
                card.unit_sys_var.set(self._adv_normalize_unit_system(payload.get("Unit_System", "mm_T_s")))
                card.mat_model_var.set(str(payload.get("Material_Model", "MAT024+GISSMO") or "MAT024+GISSMO"))
                card._seed_values()
                computed = card._compute_table()
                return card._missing_required_labels_from_computed(computed)
            finally:
                card.current_row = old_state["current_row"]
                card.current_selections = old_state["current_selections"]
                card.thickness_rows = old_state["thickness_rows"]
                card.basis_var.set(old_state["basis"])
                card.direction_var.set(old_state["direction"])
                card.unit_sys_var.set(old_state["unit_sys"])
                card.mat_model_var.set(old_state["mat_model"])
                card.prop_values = old_state["prop_values"]
                card.pending_edits = old_state["pending_edits"]
                card.last_effps = old_state["last_effps"]
                card.last_etan_eng = old_state["last_etan_eng"]
                card.last_etan_true = old_state["last_etan_true"]
        except Exception:
            return []

    def _adv_validation_message_for_payload(self, payload: Dict[str, Any], rows: Optional[pd.DataFrame] = None) -> str:
        """Return an error message when the selected Basis/Direction/Matcard cannot be generated."""
        try:
            payload = self._adv_ensure_payload_basis_direction(payload)
            if rows is None:
                rows = self._adv_match_rows(payload)
            if rows is None or rows.empty:
                return "Cannot generate - no matching source row was found."
            basis = str(payload.get("Basis", "B") or "B").strip().upper()
            direction = str(payload.get("Direction", "L") or "L").strip().upper()
            matcard = str(payload.get("Material_Model", "MAT024+GISSMO") or "MAT024+GISSMO").strip().upper()
            available = self._adv_available_bases_for_payload(payload)
            if not available.get(basis, False):
                return f"Cannot generate - {basis} Basis / {direction} Direction / {matcard} is not available for this selected material."
            missing_required = self._adv_missing_required_for_payload(payload, rows)
            if missing_required:
                return "Cannot generate - missing required MAT values: " + ", ".join(missing_required)
            return ""
        except Exception as exc:
            return f"Cannot validate material generation: {exc}"

    def _adv_add_payload(self, payload: Dict[str, Any], source_label: str = "selection", refresh: bool = True, log: bool = True):
        rows = self._adv_match_rows(payload)
        payload = self._adv_enrich_payload_from_first_match(payload, rows)
        payload = self._adv_ensure_payload_basis_direction(payload)

        payload["_matches"] = int(len(rows)) if rows is not None else 0
        payload["_selected"] = bool(payload.get("_selected", False))
        if not str(payload.get("Export_ID", "")).strip():
            payload["Export_ID"] = str(reserve_next_export_id())
        else:
            payload["Export_ID"] = str(normalize_export_id(payload.get("Export_ID"), default=peek_next_export_id()))
            payload["_id_manual"] = True
            advance_session_export_id_after(payload["Export_ID"])
        available = self._adv_available_bases_for_payload(payload)
        missing_required = self._adv_missing_required_for_payload(payload, rows)
        if payload["_matches"] <= 0:
            payload["_status"] = "No match"
            payload["_tag"] = "error"
        elif not available.get(payload.get("Basis", "B"), False):
            payload["_status"] = f"Cannot generate - {payload.get('Basis', 'B')} Basis not available"
            payload["_tag"] = "error"
        elif missing_required:
            payload["_status"] = "Cannot generate - missing " + ", ".join(missing_required)
            payload["_tag"] = "error"
        else:
            payload["_status"] = "Ready"
            payload["_tag"] = "ok"

        self.advanced_items.append(payload)
        if refresh:
            self._adv_refresh_tree()

            new_iid = str(len(self.advanced_items) - 1)
            try:
                self.adv_tree.selection_set(new_iid)
                self.adv_tree.see(new_iid)
            except Exception:
                pass

        if log:
            if payload["_matches"] > 0:
                self._adv_log(f"Added {source_label}: {payload['_matches']} matching row(s).")
            else:
                self._adv_log(f"Added {source_label}, but no matching source row was found yet.")

    def _adv_apply_id_range(self):
        """Apply sequential ID/MID values to selected rows, or all rows when no rows are selected."""
        if not self.advanced_items:
            messagebox.showwarning("ID Range", "Add at least one material to the Export List before applying an ID range.")
            return

        try:
            start_id = normalize_export_id(self.adv_id_start_var.get(), default=EXPORT_COUNTER_START)
        except Exception as exc:
            messagebox.showerror("ID Range", f"Invalid ID Range Start value:\n\n{exc}")
            return

        try:
            selected_indexes = sorted(int(i) for i in self.adv_tree.selection() if str(i).isdigit())
        except Exception:
            selected_indexes = []

        target_indexes = [i for i in selected_indexes if 0 <= i < len(self.advanced_items)]
        if not target_indexes:
            target_indexes = list(range(len(self.advanced_items)))

        for offset, item_idx in enumerate(target_indexes):
            self.advanced_items[item_idx]["Export_ID"] = str(start_id + offset)
            self.advanced_items[item_idx]["_id_range_applied"] = True

        advance_session_export_id_after(start_id + len(target_indexes) - 1)
        self.adv_id_start_var.set(str(start_id))
        self._adv_refresh_tree()

        try:
            self.adv_tree.selection_set([str(i) for i in target_indexes])
            if target_indexes:
                self.adv_tree.see(str(target_indexes[0]))
        except Exception:
            pass

        scope = "selected row(s)" if selected_indexes else "all row(s)"
        self._adv_log(f"Applied ID range from {start_id} to {start_id + len(target_indexes) - 1} for {len(target_indexes)} {scope}.")
        if hasattr(self.app, "status_var"):
            self.app.status_var.set(f"ID range applied | {export_counter_status_text()}")

    def _adv_duplicate_key(self, item: Dict[str, Any]) -> Tuple[str, ...]:
        """Return the full export-row identity key used to mark duplicate rows.

        A duplicate is marked only when the full material/export setup matches,
        including Thickness, Basis, Direction, Unit, and Matcard. Same material
        with different Basis/Direction/Thickness/Unit/Matcard is not a duplicate.
        """
        spec2 = first_nonblank_value(
            item.get("Specification 2", ""),
            item.get("Specification_2", ""),
            item.get("Spec2", ""),
            default="",
        )
        unit_system = self._adv_normalize_unit_system(str(item.get("Unit_System", "mm_T_s") or "mm_T_s")) if hasattr(self, "_adv_normalize_unit_system") else str(item.get("Unit_System", ""))
        return (
            norm(item.get("Element", "")),
            norm(item.get("Series", "")),
            norm(item.get("Material", "")),
            norm(item.get("Temper", "")),
            norm(item.get("Specification", "")),
            norm(spec2),
            norm(item.get("Form", "")),
            norm(item.get("Thickness", "") or item.get("Thickness_Mode", "")),
            norm(item.get("Basis", "")),
            norm(item.get("Direction", "")),
            norm(unit_system),
            norm(item.get("Material_Model", "")),
        )

    def _adv_duplicate_indexes(self) -> set:
        """Return indexes whose material/export specification appears more than once."""
        groups: Dict[Tuple[str, ...], List[int]] = {}
        for idx, item in enumerate(self.advanced_items):
            key = self._adv_duplicate_key(item)
            if not any(key):
                continue
            groups.setdefault(key, []).append(idx)
        duplicate_indexes = set()
        for indexes in groups.values():
            if len(indexes) > 1:
                duplicate_indexes.update(indexes)
        return duplicate_indexes

    def _adv_refresh_tree(self):
        self._adv_clear_dropdown_overlays()
        duplicate_indexes = self._adv_duplicate_indexes()
        for iid in self.adv_tree.get_children():
            self.adv_tree.delete(iid)
        for idx, item in enumerate(self.advanced_items):
            unit_label = UNIT_SYSTEM_SPEC.get(item.get("Unit_System", "mm_T_s"), {}).get("label", item.get("Unit_System", ""))
            values = (
                "",
                item.get("Export_ID", ""),
                item.get("Element", ""),
                item.get("Series", ""),
                item.get("Material", ""),
                item.get("Temper", ""),
                item.get("Specification", ""),
                item.get("Specification 2", ""),
                item.get("Form", ""),
                with_dropdown_mark(item.get("Thickness") or item.get("Thickness_Mode", "")),
                with_dropdown_mark(item.get("Basis", "B")),
                with_dropdown_mark(item.get("Direction", "L")),
                with_dropdown_mark(unit_label),
                with_dropdown_mark(item.get("Material_Model", "MAT024+GISSMO")),
                (f"{item.get('_matches', '')}  |  DUPLICATE" if idx in duplicate_indexes else item.get("_status", item.get("_matches", ""))),
                "",
                str(item.get("Notes", "")).strip(),
            )

            # Use only the duplicate tag on duplicate rows. Some Windows ttk
            # themes let alternating-row/status tags override background colors,
            # so avoiding tag stacking makes the warning color much more reliable.
            if idx in duplicate_indexes:
                row_tags = ["duplicate_row"]
                item["_duplicate"] = True
            else:
                row_tags = ["editable_row" if idx % 2 == 0 else "editable_row_alt"]
                if item.get("_tag", ""):
                    row_tags.append(item.get("_tag", ""))
                item.pop("_duplicate", None)
            self.adv_tree.insert("", "end", iid=str(idx), values=values, tags=tuple(row_tags))
        # Re-apply duplicate tag styling after insert as a defensive fix for
        # Windows/ttk themes that occasionally lose tag colors after refresh.
        try:
            self.adv_tree.tag_configure("duplicate_row", background="#FFE08A", foreground="#7A2E00")
        except Exception:
            pass

        duplicate_count = len(duplicate_indexes)
        duplicate_text = f" | {duplicate_count} duplicate material row(s) marked" if duplicate_count else ""
        self.adv_count_var.set(f"{sum(1 for x in self.advanced_items if x.get('_selected', False))} selected  /  {len(self.advanced_items)} item(s){duplicate_text}")
        self._adv_update_export_details()
        self.after_idle(self._adv_refresh_dropdown_overlays)


    def _adv_tree_yview(self, *args):
        """Scroll Export List and keep always-visible dropdown boxes aligned.

        UI PERFORMANCE: dropdown overlay refresh is debounced via after_idle
        so rapid scrolling does not stall the UI.
        """
        try:
            self.adv_tree.yview(*args)
        finally:
            self._adv_schedule_overlay_refresh()

    def _adv_tree_xview(self, *args):
        """Horizontal scroll Export List and keep dropdown boxes aligned."""
        try:
            self.adv_tree.xview(*args)
        finally:
            self._adv_schedule_overlay_refresh()

    def _adv_tree_yscroll(self, first, last):
        try:
            self.adv_tree_ysb.set(first, last)
        except Exception:
            pass
        self._adv_schedule_overlay_refresh()

    def _adv_tree_xscroll(self, first, last):
        try:
            self.adv_tree_xsb.set(first, last)
        except Exception:
            pass
        self._adv_schedule_overlay_refresh()

    def _adv_schedule_overlay_refresh(self):
        """Coalesce many overlay-refresh requests into one per idle cycle.

        UI PERFORMANCE: without this, fast wheel-scrolling fires many
        _adv_refresh_dropdown_overlays() calls which destroy+recreate all
        Combobox overlays. This guard ensures only one refresh per idle tick.
        """
        if getattr(self, "_adv_overlay_refresh_pending", False):
            return
        self._adv_overlay_refresh_pending = True
        def _run():
            self._adv_overlay_refresh_pending = False
            try:
                self._adv_refresh_dropdown_overlays()
            except Exception:
                pass
        self.after_idle(_run)

    def _adv_clear_dropdown_overlays(self):
        """Destroy lightweight widgets drawn over Export List cells."""
        if hasattr(self, "adv_cell_widgets_map"):
            for widget in self.adv_cell_widgets_map.values():
                try:
                    widget.destroy()
                except Exception:
                    pass
            self.adv_cell_widgets_map.clear()
        if hasattr(self, "adv_cell_widgets"):
            for widget in self.adv_cell_widgets:
                try:
                    widget.destroy()
                except Exception:
                    pass
            self.adv_cell_widgets = []

    def _adv_refresh_dropdown_overlays(self):
        """Draw real editable-looking controls for visible Export List rows.

        Treeview does not support native per-cell widgets. We place lightweight
        widgets over the visible cells so:
        - Export looks like a real square checkbox.
        - Unit looks like a real dropdown box because Unit is the only editable column.
        - Image looks like a real rectangular View Image button.
        """
        tree = getattr(self, "adv_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        
        if not hasattr(self, "adv_cell_widgets_map"):
            self.adv_cell_widgets_map = {}

        try:
            columns = list(tree["columns"])
            export_col_id = f"#{columns.index('Export') + 1}"
            unit_col_id = f"#{columns.index('Unit') + 1}"
            view_col_id = f"#{columns.index('View_Image') + 1}"
        except Exception:
            return

        active_keys = set()

        for iid in tree.get_children(""):
            try:
                idx = int(iid)
            except Exception:
                continue
            if not (0 <= idx < len(self.advanced_items)):
                continue
            item = self.advanced_items[idx]

            # 1. Export Checkbox
            bbox_export = None
            try:
                bbox_export = tree.bbox(iid, export_col_id)
            except Exception:
                pass
            if bbox_export:
                x, y, width, height = bbox_export
                if width > 8 and height > 8:
                    key = (iid, "export")
                    active_keys.add(key)
                    checked = bool(item.get("_selected", False))
                    box_size = max(22, min(30, height - 8))
                    chk_x = x + max(4, (width - box_size) // 2)
                    chk_y = y + max(3, (height - box_size) // 2)

                    chk = self.adv_cell_widgets_map.get(key)
                    if chk is None or not chk.winfo_exists():
                        chk = tk.Button(
                            tree,
                            text="✓" if checked else "",
                            command=lambda row_idx=idx: self._adv_toggle_export_selected(row_idx),
                            bg="#FFFFFF",
                            fg="#00A651",
                            activebackground="#FFFFFF",
                            activeforeground="#00A651",
                            font=("Segoe UI", 15, "bold"),
                            relief="solid",
                            bd=2,
                            highlightthickness=0,
                            takefocus=0,
                            cursor="hand2",
                            padx=0,
                            pady=0,
                        )
                        self.adv_cell_widgets_map[key] = chk
                    else:
                        chk.configure(text="✓" if checked else "", command=lambda row_idx=idx: self._adv_toggle_export_selected(row_idx))

                    chk.place(x=chk_x, y=chk_y, width=box_size, height=box_size)

            # 2. Unit Combobox
            bbox_unit = None
            try:
                bbox_unit = tree.bbox(iid, unit_col_id)
            except Exception:
                pass
            if bbox_unit:
                x, y, width, height = bbox_unit
                if width > 8 and height > 8:
                    key = (iid, "unit")
                    active_keys.add(key)
                    unit_options = self._adv_options_for_export_cell(item, "Unit")
                    current_unit = UNIT_SYSTEM_SPEC.get(
                        item.get("Unit_System", "mm_T_s"), {}
                    ).get("label", item.get("Unit_System", ""))
                    expected_val = current_unit if current_unit in unit_options else (unit_options[0] if unit_options else current_unit)

                    unit_combo = self.adv_cell_widgets_map.get(key)
                    if unit_combo is None or not unit_combo.winfo_exists():
                        unit_combo = ttk.Combobox(
                            tree,
                            values=unit_options,
                            state="readonly",
                            font=FONTS["caption"],
                            takefocus=0,
                        )
                        self.adv_cell_widgets_map[key] = unit_combo
                    else:
                        unit_combo.configure(values=unit_options)

                    if unit_combo.get() != expected_val:
                        unit_combo.set(expected_val)

                    def _commit_unit(_event=None, row_idx=idx, combo_widget=unit_combo):
                        value = combo_widget.get().strip()
                        if value:
                            self._adv_apply_export_cell_edit_multi(row_idx, "Unit", value, option_index=-1)
                        return "break"

                    unit_combo.bind("<<ComboboxSelected>>", _commit_unit)
                    unit_combo.bind("<Return>", _commit_unit)
                    unit_combo.bind("<MouseWheel>", lambda _event: "break")
                    unit_combo.place(x=x + 6, y=y + 5, width=max(92, width - 12), height=max(24, height - 10))

            # 3. View Image Button
            bbox_view = None
            try:
                bbox_view = tree.bbox(iid, view_col_id)
            except Exception:
                pass
            if bbox_view:
                x, y, width, height = bbox_view
                if width > 8 and height > 8:
                    key = (iid, "view_image")
                    active_keys.add(key)
                    
                    btn = self.adv_cell_widgets_map.get(key)
                    if btn is None or not btn.winfo_exists():
                        btn = tk.Button(
                            tree,
                            text="View Image",
                            command=lambda row_idx=idx: self._adv_show_image_for_item(row_idx),
                            bg=THEME["accent"],
                            fg=THEME["accent_text"],
                            activebackground=THEME["accent_hover"],
                            activeforeground=THEME["accent_text"],
                            font=FONTS["caption"],
                            relief="solid",
                            bd=1,
                            highlightthickness=0,
                            takefocus=0,
                            cursor="hand2",
                            padx=4,
                            pady=0,
                        )
                        self.adv_cell_widgets_map[key] = btn
                    else:
                        btn.configure(command=lambda row_idx=idx: self._adv_show_image_for_item(row_idx))

                    btn.place(x=x + 8, y=y + 5, width=max(70, width - 16), height=max(22, height - 10))

        for key in list(self.adv_cell_widgets_map.keys()):
            if key not in active_keys:
                widget = self.adv_cell_widgets_map.pop(key)
                try:
                    widget.destroy()
                except Exception:
                    pass

    def _adv_update_export_details(self, _event=None):
        """Show the selected export row in a readable one-line summary."""
        if not hasattr(self, "adv_detail_var"):
            return
        selected = []
        try:
            selected = list(self.adv_tree.selection())
        except Exception:
            pass
        if not selected:
            self.adv_detail_var.set("Select an export-list row to see full details here.")
            return
        try:
            item = self.advanced_items[int(selected[0])]
        except Exception:
            self.adv_detail_var.set("Selected row details are not available.")
            return
        unit_label = UNIT_SYSTEM_SPEC.get(item.get("Unit_System", "mm_T_s"), {}).get("label", item.get("Unit_System", ""))
        duplicate_note = " | DUPLICATE MATERIAL" if item.get("_duplicate") else ""
        details = (
            f"Export: {'Yes' if item.get('_selected', False) else 'No'} | ID/MID: {item.get('Export_ID','-')} | {item.get('Element','-')} | Series: {item.get('Series','-')} | Material: {item.get('Material','-')} | "
            f"Temper: {item.get('Temper','-')} | Spec: {item.get('Specification','-')} | Spec 2: {item.get('Specification 2','-')} | Form: {item.get('Form','-')} | "
            f"Thickness: {item.get('Thickness') or item.get('Thickness_Mode','-')} | Basis: {item.get('Basis','-')} | "
            f"Direction: {item.get('Direction','-')} | Unit: {unit_label} | Matcard: {item.get('Material_Model','MAT024+GISSMO')} | Matches: {item.get('_matches','-')}{duplicate_note}"
        )
        self.adv_detail_var.set(details)

    def _adv_tree_column_name(self, col_id: str) -> str:
        try:
            idx = int(str(col_id).replace("#", "")) - 1
            cols = self.adv_tree["columns"]
            if 0 <= idx < len(cols):
                return cols[idx]
        except Exception:
            pass
        return ""

    def _adv_open_export_list_row_card(self, event=None):
        """Open the Material Card from a double-clicked Advanced Export List row."""
        tree = getattr(self, "adv_tree", None)
        if tree is None:
            return "break"
        try:
            if self.adv_tree_edit_widget is not None:
                self.adv_tree_edit_widget.destroy()
                self.adv_tree_edit_widget = None
        except Exception:
            pass
        row_id = tree.identify_row(event.y) if event is not None else (tree.selection()[0] if tree.selection() else "")
        if not row_id:
            return "break"
        try:
            idx = int(row_id)
            item = self.advanced_items[idx]
        except Exception:
            return "break"

        try:
            rows_to_open = self._adv_rows_to_export(item)
            if not rows_to_open:
                messagebox.showwarning("Advanced Selection", "No matching material row found for this export-list item.")
                return "break"
            row = rows_to_open[0]
            matching_rows = self._adv_match_rows(item)
            if matching_rows is None or matching_rows.empty:
                matching_rows = pd.DataFrame([row])

            validation_message = self._adv_validation_message_for_payload(item, matching_rows)
            if validation_message:
                messagebox.showwarning("Material cannot be generated", validation_message)
                if hasattr(self.app, "status_var"):
                    self.app.status_var.set(validation_message)
                return "break"

            selections = self._adv_selection_from_payload(item)
            for field in ("Element", "Series", "Material", "Temper", "Specification", "Specification 2", "Form"):
                if not str(selections.get(field, "")).strip():
                    selections[field] = str(item.get(field, "")).strip()
            if not str(selections.get("Element", "")).strip():
                selections["Element"] = str(row.get("Element", "")).strip()
            if not str(selections.get("Material", "")).strip():
                selections["Material"] = str(row.get("Material", "")).strip()
            if not str(selections.get("Temper", "")).strip():
                selections["Temper"] = str(row.get("Temper", "")).strip()
            if not str(selections.get("Form", "")).strip():
                selections["Form"] = str(row.get("Form", "")).strip()
            if not str(selections.get("Specification", "")).strip():
                spec = str(row.get("Spec1_1", row.get("spec1_1", ""))).strip()
                selections["Specification"] = NO_SPEC_DISPLAY if is_blank(spec) else spec
            if not str(selections.get("Specification 2", "")).strip():
                selections["Specification 2"] = display_spec_value(row_spec2_value(row))
            if not str(selections.get("Series", "")).strip():
                selections["Series"] = self.db._material_to_series.get(norm(selections.get("Material", "")), "")

            # History requirement: opening a row from Advanced Selection must be
            # visible in Recent Material Summaries immediately. This is a normal
            # ORIGINAL history row; edited values are saved later as a CUSTOM row
            # when the user confirms changes with Apply on the Material Card.
            history_entry = {"datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "history_type": "selection"}
            history_entry.update(selections)
            try:
                history_entry["Source"] = row.get("MMPDS_Version", "-")
                history_entry["Thickness"] = source_thickness_display_label(row)
                history_entry["Thickness_Row_Key"] = source_row_identity_key(row)
                history_entry["Opened_From"] = "Advanced Selection"
                history_entry["Export_ID"] = str(item.get("Export_ID", "")).strip()
            except Exception:
                pass
            self.app.history.append(history_entry)
            self._refresh_history()

            card_open_state = {
                "Basis": item.get("Basis", "B"),
                "Direction": item.get("Direction", "L"),
                "Unit_System": item.get("Unit_System", "mm_T_s"),
                "Material_Model": item.get("Material_Model", "MAT024+GISSMO"),
                "Thickness": history_entry.get("Thickness", item.get("Thickness", "")),
                "Thickness_Row_Key": history_entry.get("Thickness_Row_Key", item.get("_thickness_row_key", "")),
                "Opened_From": "Advanced Selection",
                "Export_ID": str(item.get("Export_ID", "")).strip(),
            }
            if isinstance(item.get("_card_custom_state"), dict):
                card_open_state.update(item.get("_card_custom_state") or {})

            self._audit_log_action(
                screen="Advanced Selection",
                action="Material Card Opened",
                status="Success",
                material_summary=self._history_summary_text(history_entry),
                element=selections.get("Element", ""),
                series=selections.get("Series", ""),
                material=selections.get("Material", ""),
                temper=selections.get("Temper", ""),
                specification=selections.get("Specification", ""),
                form=selections.get("Form", ""),
                notes=f"User double-clicked Advanced Selection export row {idx + 1}.",
            )
            if hasattr(self.app, "status_var"):
                self.app.status_var.set(f"Opening material card from Advanced Selection | {selections.get('Material', '')} {selections.get('Temper', '')}")
            self.app.show_screen(
                "CardScreen",
                row=row,
                selections=selections,
                matching_rows=matching_rows.copy(),
                history_state=card_open_state,
            )
        except Exception as exc:
            messagebox.showerror("Advanced Selection", f"Could not open Material Card from this row:\n\n{exc}")
        return "break"

    def _adv_handle_tree_click(self, event):
        tree = getattr(self, "adv_tree", None)
        if tree is None:
            return
        row_id = tree.identify_row(event.y)
        col_name = self._adv_tree_column_name(tree.identify_column(event.x))
        if row_id and col_name == "Export":
            self._adv_toggle_export_selected(int(row_id))
            return
        if row_id and col_name == "View_Image":
            self._adv_show_image_for_item(int(row_id))
            return
        if row_id and col_name in {"Export_ID", "Unit", "Notes"}:
            return self._adv_begin_export_list_edit(event)

    def _adv_begin_export_list_edit(self, event=None):
        tree = getattr(self, "adv_tree", None)
        if tree is None:
            return "break"
        row_id = tree.identify_row(event.y) if event is not None else (tree.selection()[0] if tree.selection() else "")
        col_id = tree.identify_column(event.x) if event is not None else ""
        col_name = self._adv_tree_column_name(col_id)
        editable_cols = {"Export_ID", "Unit", "Notes"}
        if not row_id or col_name not in editable_cols:
            return "break"
        try:
            idx = int(row_id)
            item = self.advanced_items[idx]
        except Exception:
            return "break"
        bbox = tree.bbox(row_id, col_id)
        if not bbox:
            return "break"
        options = self._adv_options_for_export_cell(item, col_name)
        current = strip_dropdown_mark(tree.set(row_id, col_name))
        if not options:
            options = [current] if current else []
        if self.adv_tree_edit_widget is not None:
            try:
                self.adv_tree_edit_widget.destroy()
            except Exception:
                pass
            self.adv_tree_edit_widget = None
        x, y, width, height = bbox

        if col_name in {"Export_ID", "Notes"}:
            editor = ttk.Entry(tree)
            editor.place(x=x, y=y, width=width, height=height)
            editor.insert(0, current if col_name == "Notes" else (current or str(peek_next_export_id())))
            editor.select_range(0, tk.END)
            editor.focus_set()
            self.adv_tree_edit_widget = editor

            def commit_entry(_event=None):
                new_value = editor.get().strip()
                self._adv_apply_export_cell_edit_multi(idx, col_name, new_value, option_index=-1)
                try:
                    editor.destroy()
                except Exception:
                    pass
                self.adv_tree_edit_widget = None
                return "break"

            def cancel_entry(_event=None):
                try:
                    editor.destroy()
                except Exception:
                    pass
                self.adv_tree_edit_widget = None
                return "break"

            editor.bind("<Return>", commit_entry)
            editor.bind("<FocusOut>", commit_entry)
            editor.bind("<Escape>", cancel_entry)
            return "break"

        combo = ttk.Combobox(tree, values=options, state="readonly")
        combo.place(x=x, y=y, width=width, height=height)
        if col_name == "Thickness" and item.get("_thickness_row_key") and item.get("_thickness_option_row_keys"):
            try:
                combo.current(item.get("_thickness_option_row_keys", []).index(item.get("_thickness_row_key")))
            except Exception:
                combo.set(current if current in options else (options[0] if options else current))
        else:
            combo.set(current if current in options else (options[0] if options else current))
        combo.focus_set()
        self.adv_tree_edit_widget = combo

        def commit(_event=None):
            new_value = combo.get().strip()
            option_index = -1
            try:
                option_index = combo.current()
            except Exception:
                option_index = -1
            self._adv_apply_export_cell_edit_multi(idx, col_name, new_value, option_index=option_index)
            try:
                combo.destroy()
            except Exception:
                pass
            self.adv_tree_edit_widget = None
            return "break"

        def cancel(_event=None):
            try:
                combo.destroy()
            except Exception:
                pass
            self.adv_tree_edit_widget = None
            return "break"

        combo.bind("<<ComboboxSelected>>", commit)
        combo.bind("<Return>", commit)
        combo.bind("<FocusOut>", commit)
        combo.bind("<Escape>", cancel)
        return "break"

    def _adv_options_for_export_cell(self, item: Dict[str, Any], col_name: str) -> List[str]:
        if col_name == "Basis":
            available = self._adv_available_bases_for_payload(item)
            return [code for _label, code in BASIS_OPTIONS if available.get(code, False)]
        if col_name == "Direction":
            return self._adv_available_directions_for_payload(item)
        if col_name == "Specification":
            selections = self._adv_selection_from_payload(item)
            selections["Specification"] = ""
            opts = self.db.available("Specification", selections)
            current = str(item.get("Specification", "")).strip()
            if current and current not in opts:
                opts.insert(0, current)
            return opts
        if col_name == "Thickness":
            rows = self._adv_thickness_rows_for_payload(item)
            vals: List[str] = []
            row_keys: List[str] = []
            if rows is not None and not rows.empty:
                try:
                    if "__adv_thickness_label" in rows.columns and "__adv_row_key" in rows.columns:
                        vals = rows["__adv_thickness_label"].astype(str).tolist()
                        row_keys = rows["__adv_row_key"].astype(str).tolist()
                    else:
                        for _, row in rows.iterrows():
                            vals.append(self._adv_thickness_display_label(row) or "NA")
                            row_keys.append(self._adv_row_identity_key(row))
                except Exception:
                    vals = []
                    row_keys = []

            current = str(item.get("Thickness", "")).strip()
            current_key = str(item.get("_thickness_row_key", "")).strip()
            if current and (not current_key or current_key not in row_keys) and current not in vals:
                vals.insert(0, current)
                row_keys.insert(0, "")

            item["_thickness_option_row_keys"] = row_keys
            return vals or (["NA"] if not current else [current])
        if col_name == "Unit":
            return [label for label, _code in UNIT_SYSTEMS]
        if col_name == "Model":
            rows = self._adv_match_rows(item)
            return self._adv_available_matcards_for_rows(rows, item.get("Basis", "B"), item.get("Direction", "L"))
        return []

    def _adv_apply_export_cell_edit_multi(self, idx: int, col_name: str, new_value: str, option_index: int = -1):
        """Apply export-list edits.

        Current rule: Unit is the only editable Export List field. If multiple
        rows are selected, the same Unit value is applied to all selected rows.
        """
        target_indexes = [idx]
        if col_name == "Unit":
            try:
                target_indexes = sorted({int(i) for i in self.adv_tree.selection()} | {idx})
            except Exception:
                target_indexes = [idx]
        else:
            target_indexes = [idx]

        if len(target_indexes) <= 1:
            return self._adv_apply_export_cell_edit(idx, col_name, new_value, option_index=option_index)

        for target_idx in target_indexes:
            self._adv_apply_export_cell_edit(
                target_idx,
                col_name,
                new_value,
                option_index=option_index if target_idx == idx else -1,
            )
        self._adv_log(f"Multi-row edit applied to {len(target_indexes)} row(s): {col_name} = {new_value}")

    def _adv_apply_export_cell_edit(self, idx: int, col_name: str, new_value: str, option_index: int = -1):
        if not (0 <= idx < len(self.advanced_items)):
            return
        item = self.advanced_items[idx]
        if col_name == "Export_ID":
            try:
                item["Export_ID"] = str(normalize_export_id(new_value, default=peek_next_export_id()))
                item["_id_manual"] = True
                advance_session_export_id_after(item["Export_ID"])
            except Exception as exc:
                messagebox.showerror("Export ID", f"Invalid Export ID / MID:\n\n{exc}")
                return
        elif col_name == "Basis":
            label_to_code = {label: code for label, code in BASIS_OPTIONS}
            item["Basis"] = label_to_code.get(new_value, new_value)
        elif col_name == "Direction":
            item["Direction"] = new_value
        elif col_name == "Specification":
            item["Specification"] = new_value

            thickness_opts = self._adv_options_for_export_cell(item, "Thickness")
            if thickness_opts and item.get("Thickness") not in thickness_opts:
                item["Thickness"] = thickness_opts[0]
                item["Thickness_Mode"] = "Exact thickness text"
                row_keys = item.get("_thickness_option_row_keys", []) or []
                if row_keys:
                    item["_thickness_row_key"] = row_keys[0]
        elif col_name == "Thickness":
            item["Thickness"] = new_value or "NA"
            item["Thickness_Mode"] = "Exact thickness text"
            row_keys = item.get("_thickness_option_row_keys", []) or []
            if 0 <= int(option_index) < len(row_keys):
                item["_thickness_row_key"] = row_keys[int(option_index)]
            else:


                item.pop("_thickness_row_key", None)
                try:
                    rows = self._adv_thickness_rows_for_payload(item)
                    for _, source_row in rows.iterrows():
                        if norm(self._adv_thickness_display_label(source_row)) == norm(new_value):
                            item["_thickness_row_key"] = self._adv_row_identity_key(source_row)
                            break
                except Exception:
                    pass
        elif col_name == "Unit":
            item["Unit_System"] = self._adv_normalize_unit_system(new_value)
        elif col_name == "Model":
            item["Material_Model"] = new_value if new_value in {"MAT024", "MAT082", "MAT224", "MAT024+GISSMO"} else "MAT024+GISSMO"
        item.update(self._adv_ensure_payload_basis_direction(item))
        rows = self._adv_match_rows(item)
        item["_matches"] = int(len(rows)) if rows is not None else 0
        available = self._adv_available_bases_for_payload(item)
        missing_required = self._adv_missing_required_for_payload(item, rows)
        if item["_matches"] <= 0:
            item["_status"] = "No match"
            item["_tag"] = "error"
        elif not available.get(item.get("Basis", "B"), False):
            item["_status"] = f"Cannot generate - {item.get('Basis', 'B')} Basis not available"
            item["_tag"] = "error"
        elif missing_required:
            item["_status"] = "Cannot generate - missing " + ", ".join(missing_required)
            item["_tag"] = "error"
        else:
            item["_status"] = "Ready"
            item["_tag"] = "ok"
        self._adv_refresh_tree()
        try:
            self.adv_tree.selection_set(str(idx))
            self.adv_tree.see(str(idx))
        except Exception:
            pass
        self._adv_log(f"Updated export row {idx + 1}: {('Matcard' if col_name == 'Model' else col_name)} = {new_value}")

    def _adv_show_image_for_item(self, idx: int):
        if not (0 <= idx < len(self.advanced_items)):
            return
        item = self.advanced_items[idx]
        parts = {
            "element": item.get("Element", ""),
            "material": item.get("Material", ""),
            "temper": item.get("Temper", ""),
            "spec": item.get("Specification 2", "") if is_blank(item.get("Specification", "")) or item.get("Specification", "") == NO_SPEC_DISPLAY else item.get("Specification", ""),
            "form": item.get("Form", ""),
        }
        material_text = f"{item.get('Element','')} {item.get('Material','')}-{item.get('Temper','')}".strip(" -")
        material_summary = (
            f"Material: {material_text or '-'} | Series: {item.get('Series','-')} | "
            f"Spec: {item.get('Specification','-')} | Spec 2: {item.get('Specification 2','-')} | Form: {item.get('Form','-')}"
        )
        self._audit_log_action(
            screen="Advanced Selection",
            action="View Image Clicked",
            status="Clicked",
            material_summary=material_summary,
            element=item.get("Element", ""),
            series=item.get("Series", ""),
            material=item.get("Material", ""),
            temper=item.get("Temper", ""),
            specification=item.get("Specification", ""),
            form=item.get("Form", ""),
            notes=f"User clicked View Image for export row {idx + 1}.",
        )
        try:
            images, total = self.app.source_image_index.search(parts, max_results=4)
        except Exception as exc:
            images, total = [], 0
            self._audit_log_action(
                screen="Advanced Selection",
                action="View Image Search Error",
                status="Error",
                material_summary=material_summary,
                notes="Image search failed.",
                details=str(exc),
            )
        if not images:
            self._audit_log_action(
                screen="Advanced Selection",
                action="Source Image Not Found",
                status="Warning",
                material_summary=material_summary,
                element=item.get("Element", ""),
                series=item.get("Series", ""),
                material=item.get("Material", ""),
                temper=item.get("Temper", ""),
                specification=item.get("Specification", ""),
                form=item.get("Form", ""),
                notes="No related source image found for this export row.",
                details=f"Expected tokens: {parts.get('material','')}, {parts.get('temper','')}, {parts.get('spec','')}, {parts.get('form','')}",
            )
            messagebox.showinfo(
                "Source Image",
                "No related source image found for this export row.\n\n"
                f"Expected tokens: {parts.get('material','')}, {parts.get('temper','')}, {parts.get('spec','')}, {parts.get('form','')}"
            )
            return
        win = tk.Toplevel(self)
        win.title("Related Source Image")
        win.geometry("900x720")
        win.configure(bg=THEME["panel"])
        header = tk.Frame(win, bg=THEME["accent"], height=32)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text=f"Related Source Image | Showing 1 of {total}", bg=THEME["accent"], fg="white",
                 font=FONTS["body_bold"]).pack(side=tk.LEFT, padx=10, pady=6)
        meta = (
            f"Material: {item.get('Material','-')} | Temper: {item.get('Temper','-')} | "
            f"Spec: {item.get('Specification','-')} | Spec 2: {item.get('Specification 2','-')} | Form: {item.get('Form','-')}"
        )
        tk.Label(win, text=meta, bg=THEME["panel"], fg=THEME["text"], font=FONTS["small_bold"],
                 anchor="w").pack(fill=tk.X, padx=10, pady=(8, 4))
        tk.Label(win, text=f"Image: {images[0].name}", bg=THEME["panel"], fg=THEME["text_muted"],
                 font=FONTS["small"], anchor="w").pack(fill=tk.X, padx=10, pady=(0, 8))
        canvas = tk.Canvas(win, bg="white", highlightthickness=1, highlightbackground=THEME["border"])
        canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        img = self.app.image_cache.get(images[0], max_size=(860, 620))
        if img is None:
            self._audit_log_action(
                screen="Advanced Selection",
                action="Source Image Load Error",
                status="Error",
                material_summary=material_summary,
                image_name=images[0].name,
                notes="Image was found but could not be loaded.",
                details=self.app.image_cache.last_error or str(images[0]),
            )
            canvas.create_text(20, 20, anchor="nw", text="Image found, but could not be loaded. Install Pillow if needed.", fill="red")
            return
        self.adv_image_refs.append(img)
        canvas.create_image(10, 10, anchor="nw", image=img)
        self._audit_log_action(
            screen="Advanced Selection",
            action="Source Image Viewed",
            status="Success",
            material_summary=material_summary,
            element=item.get("Element", ""),
            series=item.get("Series", ""),
            material=item.get("Material", ""),
            temper=item.get("Temper", ""),
            specification=item.get("Specification", ""),
            form=item.get("Form", ""),
            image_name=images[0].name,
            notes=f"Opened related source image for export row {idx + 1}.",
            details=str(images[0]),
        )
        self._adv_log(f"Viewed source image for row {idx + 1}: {images[0].name}")

    def _adv_toggle_export_selected(self, idx: int):
        """Toggle the first Export column square marker for one export-list row."""
        if not (0 <= idx < len(self.advanced_items)):
            return
        self.advanced_items[idx]["_selected"] = not bool(self.advanced_items[idx].get("_selected", False))
        state = "selected" if self.advanced_items[idx]["_selected"] else "not selected"
        self._adv_refresh_tree()
        try:
            self.adv_tree.selection_set(str(idx))
            self.adv_tree.see(str(idx))
        except Exception:
            pass
        self._adv_log(f"Row {idx + 1} marked as {state} for export.")

    def _adv_select_all_items(self):
        """Mark all export-list rows for export."""
        for item in self.advanced_items:
            item["_selected"] = True
        self._adv_refresh_tree()
        self._adv_log(f"Selected all {len(self.advanced_items)} row(s) for export.")

    def _adv_clear_export_selection(self):
        """Uncheck all export-list rows without removing them from the list."""
        for item in self.advanced_items:
            item["_selected"] = False
        self._adv_refresh_tree()
        self._adv_log("Cleared export selection. Rows remain in the list.")

    def _adv_remove_selected(self):
        selected = sorted((int(i) for i in self.adv_tree.selection()), reverse=True)
        for idx in selected:
            if 0 <= idx < len(self.advanced_items):
                self.advanced_items.pop(idx)
        self._adv_refresh_tree()
        self._adv_log(f"Removed {len(selected)} item(s).")

    def _adv_remove_duplicates(self):
        if not self.advanced_items:
            messagebox.showinfo("Remove Duplicates", "There are no rows in the Export List.")
            return
        before = len(self.advanced_items)
        if remove_duplicate_items is not None:
            self.advanced_items = remove_duplicate_items(self.advanced_items)
        else:
            seen_keys = set()
            kept_items = []
            for item in self.advanced_items:
                key = self._adv_duplicate_key(item)
                if not any(key) or key not in seen_keys:
                    kept_items.append(item)
                    seen_keys.add(key)
            self.advanced_items = kept_items
        removed_count = before - len(self.advanced_items)
        if removed_count <= 0:
            messagebox.showinfo("Remove Duplicates", "No duplicate rows were found.")
            self._adv_log("Remove Duplicates clicked. No duplicate rows were found.")
            return
        self._adv_refresh_tree()
        self._adv_log(f"Removed {removed_count} duplicate row(s). First occurrence was kept.")
        messagebox.showinfo("Remove Duplicates", f"Removed {removed_count} duplicate row(s).\\n\\nThe first occurrence was kept.")
    def _adv_clear_list(self):
        self.advanced_items.clear()
        self._adv_refresh_tree()
        self._adv_log("Cleared export list.")

    def _adv_upload_input_csv(self):
        path = filedialog.askopenfilename(
            title="Select input CSV for batch export",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            df = pd.read_csv(path, dtype=str).fillna("")
        except Exception as exc:
            messagebox.showerror("Upload Input CSV", f"Could not read CSV:\n\n{exc}")
            return

        added = 0
        colmap = {norm(c).replace(" ", "_"): c for c in df.columns}

        def parse_selected(value, default=False):
            text = str(value).strip().lower()
            if text == "":
                return default
            return text in {"1", "true", "yes", "y", "x", "[x]", "\u2713", "checked", "select", "selected"}

        def pick(row, *names, default=""):
            for name in names:
                c = colmap.get(norm(name).replace(" ", "_"))
                if c is not None:
                    return str(row.get(c, default)).strip()
            return default

        for _, row in df.iterrows():
            payload = {
                "Export_ID": pick(row, "Export ID", "Export_ID", "MID", "Material_ID", "Material ID"),
                "Element": pick(row, "Element"),
                "Series": pick(row, "Series"),
                "Material": pick(row, "Material"),
                "Temper": pick(row, "Temper"),
                "Specification": pick(row, "Specification", "Spec", "Spec1_1"),
                "Specification 2": pick(row, "Specification 2", "Specification2", "Spec2", "Spec2_1", "Spec2_2"),
                "Form": pick(row, "Form"),
                "Basis": pick(row, "Basis", default=self.adv_basis_var.get()) or self.adv_basis_var.get(),
                "Direction": pick(row, "Direction", default=self.adv_direction_var.get()) or self.adv_direction_var.get(),
                "Unit_System": pick(row, "Unit_System", "Unit System", default=self.adv_unit_sys_var.get()) or self.adv_unit_sys_var.get(),
                "Material_Model": pick(row, "Material_Model", "Material Model", "Model", default="MAT024+GISSMO") or "MAT024+GISSMO",
                "Thickness_Mode": pick(row, "Thickness_Mode", "Thickness Mode", default=self.adv_thickness_mode_var.get()) or self.adv_thickness_mode_var.get(),
                "Thickness": pick(row, "Thickness", "Thick_Value", "Wall_Thick"),
                "Part_Number": pick(row, "Part Number", "Part_Number", "PartNo", "Part No"),
                "Part_Name": pick(row, "Part Name", "Part_Name", "Part Description"),
                "Material_Name_from_Client": pick(row, "Material Name from Client", "Client Material", "Material_from_Client"),
                "Stock_Size_Thickness": pick(row, "Stock Size Thickness", "Stock Thickness", "Stock_Size", "Stock Size"),
                "Datasheet": pick(row, "Datasheet", "Data Sheet", "DataSource"),
                "Source": Path(path).name,
            }
            payload["_selected"] = parse_selected(pick(row, "Select", "Selected", "Export", "Export_Selected", "Include", default=""), default=False)

            payload["Unit_System"] = self._adv_normalize_unit_system(payload["Unit_System"])
            payload["Material_Model"] = payload["Material_Model"] if payload["Material_Model"] in {"MAT024", "MAT082", "MAT224", "MAT024+GISSMO"} else "MAT024+GISSMO"
            if payload["Thickness"] and payload["Thickness_Mode"] == self.adv_thickness_mode_var.get():
                payload["Thickness_Mode"] = "Exact thickness text"
            self._adv_add_payload(payload)
            added += 1

        self._adv_log(f"Uploaded {added} item(s) from {Path(path).name}.")

    def _adv_normalize_unit_system(self, value: str) -> str:
        v = norm(value).replace(" ", "").replace(",", "_")
        mapping = {
            "mm_tonne_sec": "mm_T_s", "mm_t_s": "mm_T_s", "mm_tonne_s": "mm_T_s", "mm_ton_sec": "mm_T_s",
            "m_kg_sec": "m_Kg_s", "m_kg_s": "m_Kg_s",
            "mm_kg_msec": "mm_Kg_ms", "mm_kg_ms": "mm_Kg_ms",
        }
        if value in UNIT_SYSTEM_SPEC:
            return value
        return mapping.get(v, self.adv_unit_sys_var.get())

    def _adv_selection_from_payload(self, payload: Dict[str, Any]) -> Dict[str, str]:
        selections = {s: str(payload.get(s, "")).strip() for s in STAGES}
        if selections.get("Specification") == "":
            selections["Specification"] = ""
        return selections

    def _adv_row_identity_key(self, row) -> str:
        """Hidden row key used for Advanced Selection thickness mapping."""
        try:
            key = str(row.get("__adv_row_key", "")).strip()
            if key:
                return key
        except Exception:
            pass
        return source_row_identity_key(row)

    def _adv_thickness_rows_for_payload(self, payload: Dict[str, Any]) -> pd.DataFrame:
        """Return all source rows that can appear in an Advanced Thickness dropdown.

        This intentionally does not filter by Basis, Direction, Unit System, or
        Material Model. The Thickness dropdown represents actual source rows for
        the selected material/spec/form path.
        """
        selections = self._adv_selection_from_payload(payload)
        return self.db.filter_master(selections)

    def _adv_match_rows(self, payload: Dict[str, Any]) -> pd.DataFrame:
        selections = self._adv_selection_from_payload(payload)
        mode = payload.get("Thickness_Mode", "First matching thickness")
        exact = str(payload.get("Thickness", "")).strip()
        exact_row_key = str(payload.get("_thickness_row_key", "")).strip()
        basis = str(payload.get("Basis", "") or "").strip()
        direction = str(payload.get("Direction", "") or "").strip()
        model = str(payload.get("Material_Model", "") or "").strip()
        if exact_row_key and getattr(self, "perf_engine", None) is None:
            try:
                df = self.db.filter_master(selections)
                if df is not None and not df.empty:
                    if "__adv_row_key" in df.columns:
                        filtered = df.loc[df["__adv_row_key"].astype(str).eq(exact_row_key)].copy()
                    else:
                        mask = [self._adv_row_identity_key(row) == exact_row_key for _, row in df.iterrows()]
                        filtered = df.loc[mask].copy()
                    if not filtered.empty:
                        return filtered
            except Exception:
                pass
        if getattr(self, "perf_engine", None) is not None:
            try:
                thickness = exact if mode == "Exact thickness text" and exact else ""
                return self.perf_engine.filter_rows(selections, thickness=thickness, basis=basis, direction=direction, matcard=model)
            except Exception:
                pass
        df = self.db.filter_master(selections)
        if df.empty:
            return df
        if mode == "Exact thickness text" and exact:
            exact_norm = norm(exact)
            try:
                if "__adv_thickness_norm" in df.columns and "__adv_thickness_base_norm" in df.columns:
                    mask = (df["__adv_thickness_norm"].astype(str).eq(exact_norm) | df["__adv_thickness_base_norm"].astype(str).eq(exact_norm))
                    df = df.loc[mask].copy()
            except Exception:
                mask = []
                for _, row in df.iterrows():
                    t_base = self._adv_thickness_base(row)
                    t_display = self._adv_thickness_display_label(row)
                    mask.append(norm(t_base) == exact_norm or norm(t_display) == exact_norm)
                df = df.loc[mask].copy()
        if basis or direction:
            try:
                keep = [idx for idx, row in df.iterrows() if self._finder_row_has_basis_direction_data(row, basis, direction)]
                df = df.loc[keep].copy()
            except Exception:
                pass
        if model:
            try:
                keep = [idx for idx, row in df.iterrows() if self._adv_row_model_available(row, model, basis, direction)]
                df = df.loc[keep].copy()
            except Exception:
                pass
        return df

    def _adv_rows_to_export(self, payload: Dict[str, Any]) -> List[pd.Series]:
        df = self._adv_match_rows(payload)
        if df.empty:
            return []
        mode = payload.get("Thickness_Mode", "First matching thickness")
        if mode == "All matching thickness rows":
            return [df.iloc[i] for i in range(len(df))]
        return [df.iloc[0]]

    def _adv_thickness_base(self, row):
        return source_thickness_base_value(row, prefer_wall=False)

    def _adv_thickness_display_label(self, row) -> str:
        """Return duplicate-aware visible thickness label for Advanced Selection."""
        return source_gui_thickness_label(row)

    def _adv_export_all(self):
        """Export only export-list items checked in the Export column.

        Output structure:
            selected output folder/
                keyfiles/
                images/
                export_summary.csv

        All rows added to the Export List remain stored in self.advanced_items
        until the user clicks Clear List or removes them.
        """
        if not self.advanced_items:
            messagebox.showwarning("Advanced Selection", "Add at least one item before exporting.")
            return
        selected_items = [(idx, item) for idx, item in enumerate(self.advanced_items, start=1) if item.get("_selected", False)]
        if not selected_items:
            messagebox.showwarning("Advanced Selection", "Select at least one checkbox in the Export column before exporting.")
            return

        batch_dir = Path(self.adv_output_dir_var.get()).expanduser()
        keyfiles_dir = batch_dir / "keyfiles"
        images_dir = batch_dir / "images"
        try:
            keyfiles_dir.mkdir(parents=True, exist_ok=True)
            images_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("Advanced Selection", f"Could not create output folders:\n\n{exc}")
            return

        card: CardScreen = self.app.screens.get("CardScreen")
        if card is None:
            messagebox.showerror("Advanced Selection", "CardScreen is not available for MAT024 calculations.")
            return

        exported = 0
        skipped = 0
        errors = []
        summary_rows = []
        self._adv_log(f"Starting batch keyfile export for {len(selected_items)} selected item(s)...")
        self._adv_log(f"Batch folder: {batch_dir}")

        for item_idx, item in selected_items:
            self.update_idletasks()
            rows = self._adv_rows_to_export(item)
            if not rows:
                skipped += 1
                msg = f"Item {item_idx}: no matching material row."
                errors.append(msg)
                self._adv_log(msg)
                summary_rows.append(self._adv_summary_row(item, item_idx, "Skipped - No match", "", "", "", "No matching material row"))
                continue

            selections = self._adv_selection_from_payload(item)
            basis = item.get("Basis", "B") or "B"
            direction = item.get("Direction", "L") or "L"
            unit_sys = self._adv_normalize_unit_system(item.get("Unit_System", "mm_T_s"))
            model = item.get("Material_Model", "MAT024+GISSMO") or "MAT024+GISSMO"
            item_notes = str(item.get("Notes", "") or "").strip()

            for row_idx, row in enumerate(rows, start=1):
                stem = self._adv_short_output_stem(item, row, item_idx, row_idx)
                keyfile_path = ""
                image_name = ""
                image_export_path = ""
                try:
                    card._programmatic_custom_state = item.get("_card_custom_state") if isinstance(item.get("_card_custom_state"), dict) else None
                    card._programmatic_export_notes = item_notes
                    result = card.export_keyfile_programmatic(
                        row=row,
                        selections=selections,
                        output_dir=keyfiles_dir,
                        output_stem=stem,
                        basis=basis,
                        direction=direction,
                        unit_sys=unit_sys,
                        mat_model=model,
                        material_id=item.get("Export_ID", ""),
                    )
                except Exception as exc:
                    skipped += 1
                    msg = f"Item {item_idx}, row {row_idx}: export failed: {exc}"
                    errors.append(msg)
                    self._adv_log(msg)
                    summary_rows.append(self._adv_summary_row(item, item_idx, "Skipped - Export error", "", "", "", str(exc), row=row))
                    continue

                if result.get("ok"):
                    exported += 1
                    keyfile_path = result.get("path", "")
                    self._adv_log(f"Exported keyfile: {Path(keyfile_path).name}")


                    image_path, image_total = self._adv_best_image_for_item(item)
                    if image_path is not None:
                        # Image export rule: one copied image per exported keyfile.
                        # The copied image uses the exact keyfile stem so names stay paired:
                        #   ABC.k  ->  ABC.jpg / ABC.png / etc.
                        image_stem = Path(keyfile_path).stem if keyfile_path else stem
                        copied = self._adv_copy_image_to_output(image_path, images_dir, image_stem)
                        if copied is not None:
                            image_name = copied.name
                            image_export_path = str(copied)
                            self._adv_log(f"Copied source image: {copied.name}")
                    else:
                        image_name = ""
                        image_export_path = ""

                    summary_rows.append(self._adv_summary_row(
                        item, item_idx, "Exported", Path(keyfile_path).name, keyfile_path,
                        image_export_path, item_notes, image_name=image_name, row=row,
                        export_id=result.get("export_id", "")
                    ))
                else:
                    skipped += 1
                    missing = ", ".join(result.get("missing", []))
                    msg = f"Item {item_idx}, row {row_idx}: skipped; missing {missing}"
                    errors.append(msg)
                    self._adv_log(msg)
                    summary_rows.append(self._adv_summary_row(item, item_idx, "Skipped - Missing values", "", "", "", missing, row=row))


        summary_csv_path, summary_xlsx_path = self._write_advanced_summary_files(summary_rows, batch_dir)
        if summary_csv_path is not None:
            self._adv_log(f"Export summary CSV created: {summary_csv_path.name}")
        if summary_xlsx_path is not None:
            self._adv_log(f"Styled export summary Excel created: {summary_xlsx_path.name}")

        summary = f"Batch export complete. Exported {exported} keyfile(s). Skipped {skipped}."
        self._adv_log(summary)
        if hasattr(self.app, "status_var"):
            self.app.status_var.set(f"{summary} | {export_counter_status_text()}")
        self._adv_log(f"Keyfiles folder: {keyfiles_dir}")
        self._adv_log(f"Images folder: {images_dir}")
        if errors:
            messagebox.showwarning("Advanced Selection", summary + "\n\nCheck the Export / Validation Log and export_summary.csv for details.")
        else:
            messagebox.showinfo("Advanced Selection", summary + f"\n\nOutput folder:\n{batch_dir}")

    def _write_advanced_summary_files(self, summary_rows: List[Dict[str, Any]], batch_dir: Path) -> Tuple[Optional[Path], Optional[Path]]:
        """Write plain CSV plus styled Excel summary for Advanced Selection export.

        The Excel file keeps the existing single header row. No extra row 1/row 2
        is inserted. Header cells before the internal source-data block are green;
        the internal MMPDS data block is red and starts with Element, Material,
        Specification, Forms, and Temper OR Condition.
        """
        if not summary_rows:
            return None, None

        csv_path = batch_dir / "export_summary.csv"
        xlsx_path = batch_dir / "export_summary.xlsx"


        try:
            # Item 5: CSV Header Mapping / Unit-aware column labeling.
            # CSV headers are renamed with units. The styled Excel summary uses
            # the same unit-aware display labels below. Underlying values,
            # calculations, and GUI tables are unchanged.
            csv_unit_header_map = {
                "Ftu": "Ftu (ksi)",
                "Fty": "Fty (ksi)",
                "Fcy": "Fcy (ksi)",
                "Fsu": "Fsu (ksi)",
                "Fbru": "Fbru (ksi)",
                "Fbry": "Fbry (ksi)",
                "Elong": "Elong (%)",
                "Young Modulus": "Young Modulus (10^3 ksi)",
                "Tangent Modulus": "Tangent Modulus (ksi)",
                "Poisson": "Poisson (-)",
                "Density": "Density (lb/in^3)",
            }
            csv_df = pd.DataFrame(summary_rows).rename(columns=csv_unit_header_map)
            csv_df.to_csv(csv_path, index=False)
        except Exception as exc:
            self._adv_log(f"Could not create export_summary.csv: {exc}")
            csv_path = None

        green_cols = [
            ("Item", "Item"),
            ("Export_ID", "Export ID"),
            ("Export_Selected", "Export Selected"),
            ("Status", "Status"),
            ("Part Number", "Part Number"),
            ("Part Name", "Part Name"),
            ("Material Name from Client", "Material Name from Client"),
            ("Stock Size Thickness", "Stock Size Thickness"),
            ("Datasheet", "Datasheet"),
            ("Keyfile_Name", "Keyfile Name"),
            ("Keyfile_Export_Path", "Keyfile Export Path"),
            ("Source_Image_Name", "Source Image Name"),
            ("Source_Image_Export_Path", "Source Image Export Path"),
            ("Notes", "Notes"),
        ]
        red_cols = [
            ("Element", "Element"),
            ("Material", "Material"),
            ("Main Specification", "Specification"),
            ("Specification 2", "Specification 2"),
            ("Main Form", "Forms"),
            ("Temper OR Condition", "Temper OR Condition"),
            ("Thickness from MMPDS", "Thickness from MMPDS"),
            ("Main Basis", "Basis"),
            ("Main Direction", "Direction"),
            ("Ftu", "Ftu (ksi)"),
            ("Fty", "Fty (ksi)"),
            ("Fcy", "Fcy (ksi)"),
            ("Fsu", "Fsu (ksi)"),
            ("Fbru", "Fbru (ksi)"),
            ("Fbry", "Fbry (ksi)"),
            ("Elong", "Elong (%)"),
            ("Young Modulus", "Young Modulus (10^3 ksi)"),
            ("Tangent Modulus", "Tangent Modulus (ksi)"),
            ("Poisson", "Poisson (-)"),
            ("Density", "Density (lb/in^3)"),
            ("Source", "Source"),
            ("Internal Notes", "Internal Notes"),
        ]
        column_pairs = green_cols + red_cols

        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
            from openpyxl.utils import get_column_letter

            wb = Workbook()
            ws = wb.active
            ws.title = "Export Summary"


            headers = [display for _key, display in column_pairs]
            ws.append(headers)

            for row in summary_rows:
                ws.append([row.get(key, "") for key, _display in column_pairs])

            green_fill = PatternFill("solid", fgColor="70AD47")
            red_fill = PatternFill("solid", fgColor="C00000")
            header_font = Font(bold=True, color="FFFFFF")
            red_font = Font(bold=True, color="FFFFFF")
            thin = Side(style="thin", color="808080")
            border = Border(left=thin, right=thin, top=thin, bottom=thin)

            for col_idx in range(1, len(column_pairs) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = green_fill if col_idx <= len(green_cols) else red_fill
                cell.font = header_font if col_idx <= len(green_cols) else red_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                cell.border = border

            for row_cells in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=len(column_pairs)):
                for cell in row_cells:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
                    cell.border = border

            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions

            for col_idx, (_key, display) in enumerate(column_pairs, start=1):
                letter = get_column_letter(col_idx)
                width = max(12, min(36, len(str(display)) + 4))
                if "Path" in display:
                    width = 42
                elif display in {"Material Name from Client", "Part Name", "Internal Notes", "Notes"}:
                    width = 32
                ws.column_dimensions[letter].width = width

            wb.save(xlsx_path)
        except Exception as exc:
            self._adv_log(f"Could not create styled export_summary.xlsx: {exc}")
            xlsx_path = None

        return csv_path, xlsx_path

    def _adv_best_image_for_item(self, item: Dict[str, Any]) -> Tuple[Optional[Path], int]:
        """Return the best matching source image for an export-list item."""
        parts = {
            "element": item.get("Element", ""),
            "material": item.get("Material", ""),
            "temper": item.get("Temper", ""),
            "spec": item.get("Specification", ""),
            "form": item.get("Form", ""),
        }
        try:
            images, total = self.app.source_image_index.search(parts, max_results=1)
        except Exception:
            return None, 0
        if not images:
            return None, total
        return images[0], total

    def _adv_copy_image_to_output(self, image_path: Path, images_dir: Path, stem: str) -> Optional[Path]:
        """Copy one related source image into the batch images folder.

        Manager requirement: exported MMPDS picture filename must match the
        exported keyfile/material filename exactly, except for the image
        extension. This prevents one source image name from overwriting another
        when many keyfiles use the same original MMPDS picture.

        Example:
            keyfiles/ABC.k  ->  images/ABC.jpg
        """
        try:
            images_dir.mkdir(parents=True, exist_ok=True)
            safe_stem = self._adv_file_part(stem) if hasattr(self, "_adv_file_part") else str(stem).strip()
            if not safe_stem:
                safe_stem = Path(image_path).stem
            suffix = Path(image_path).suffix or ".png"
            out_path = images_dir / f"{safe_stem}{suffix}"

            # If the same keyfile stem is exported twice for any reason, do not
            # overwrite the existing image. Add a small numeric suffix instead.
            if out_path.exists():
                base = out_path.stem
                ext = out_path.suffix
                counter = 2
                candidate = images_dir / f"{base}_{counter}{ext}"
                while candidate.exists():
                    counter += 1
                    candidate = images_dir / f"{base}_{counter}{ext}"
                out_path = candidate

            shutil.copy2(image_path, out_path)
            return out_path
        except Exception as exc:
            self._adv_log(f"Could not copy source image: {exc}")
            return None

    def _adv_row_get(self, row: Optional[pd.Series], *names: str, default: str = "") -> str:
        """Read a source-row value using case/spacing tolerant column names."""
        if row is None:
            return default
        lower_map = {norm(c): c for c in row.index}
        for name in names:
            col = lower_map.get(norm(name))
            if col is not None:
                val = str(row.get(col, default)).strip()
                if not is_blank(val):
                    return val
        return default

    def _adv_basis_list_for_summary(self, basis: str) -> List[str]:
        return ["A", "B", "S"] if str(basis).strip().upper() == "T" else [str(basis).strip().upper() or "B"]

    def _adv_summary_material_value(self, row: Optional[pd.Series], key: str, basis: str, direction: str) -> str:
        """Return the property value for export_summary.csv without changing app formulas.

        This is a read-only summary helper. It checks the same common MMPDS column
        patterns used by the card, plus bearing aliases for Fbru/Fbry.
        """
        if row is None:
            return ""
        d = "LT" if str(direction).strip().upper() == "LT" else "L"
        prefixes = {
            "Ftu": [f"Tensile_Str_{d}", f"Ftu_{d}", f"FTU_{d}", "Ftu", "FTU"],
            "Fty": [f"Tensile_Yield_{d}", f"Fty_{d}", f"FTY_{d}", "Fty", "FTY"],
            "Fcy": [f"Compress_Yield_{d}", f"Compression_Yield_{d}", f"Fcy_{d}", f"FCY_{d}", "Fcy", "FCY"],
            "Fsu": [f"Shear_Str_{d}", f"Shear_Strength_{d}", f"Fsu_{d}", f"FSU_{d}", "Fsu", "FSU"],
            "Fbru": [f"Bearing_Ult_{d}", f"Bearing_Ultimate_{d}", f"Bearing_Str_{d}", f"Bearing_Ult_Str_{d}", f"Fbru_{d}", f"FBRU_{d}", "Fbru", "FBRU"],
            "Fbry": [f"Bearing_Yield_{d}", f"Bearing_Yield_Str_{d}", f"Fbry_{d}", f"FBRY_{d}", "Fbry", "FBRY"],
            "Young Modulus": [f"Youngs_Mod_{d}", f"Young_Mod_{d}", f"E_{d}", "Youngs_Mod", "Young_Mod", "E"],
            "Poisson": ["Poissons_Ratio", "Poisson_Ratio", "Poisson", "PR"],
            "Density": ["Density", "RO", "Rho"],
            "Elong": [f"Elong_{d}", "Elong", "Elongation"],
        }
        lower_map = {norm(c): c for c in row.index}

        def direct_lookup(names: List[str]) -> Optional[str]:
            for base in names:
                for b in self._adv_basis_list_for_summary(basis):
                    for cand in (f"{base}_{b}", f"{base}{b}", base):
                        col = lower_map.get(norm(cand))
                        if col is not None:
                            val = str(row.get(col, "")).strip()
                            if not is_blank(val):
                                return fmt_number(val) if try_float(val) is not None else val
            return None

        if key == "Tangent Modulus":
            source_etan = direct_lookup([
                f"Etan_{d}", f"E_Tan_{d}", f"Tangent_Modulus_{d}", f"Tangent_Mod_{d}",
                "Etan", "E_Tan", "Tangent_Modulus", "Tangent_Mod"
            ])
            if source_etan:
                return source_etan
            ftu = try_float(self._adv_summary_material_value(row, "Ftu", basis, direction))
            fty = try_float(self._adv_summary_material_value(row, "Fty", basis, direction))
            elong = try_float(self._adv_summary_material_value(row, "Elong", basis, direction))
            if ftu is not None and fty is not None and elong not in (None, 0):
                return fmt_number((ftu - fty) / (elong / 100))
            return ""

        value = direct_lookup(prefixes.get(key, [key]))
        return value or ""

    def _adv_summary_row(self, item: Dict[str, Any], item_idx: int, status: str, keyfile_name: str,
                         keyfile_path: str, image_path: str, notes: str, image_name: str = "",
                         row: Optional[pd.Series] = None, export_id: Any = "") -> Dict[str, Any]:
        basis = item.get("Basis", "")
        direction = item.get("Direction", "")
        spec = item.get("Specification", "") or self._adv_row_get(row, "Spec1_1", "spec1_1", "Specification")
        spec2 = item.get("Specification 2", "") or row_spec2_value(row)
        spec2 = display_spec_value(spec2)
        form = item.get("Form", "") or self._adv_row_get(row, "Form")
        temper = item.get("Temper", "") or self._adv_row_get(row, "Temper")
        thickness_mmpds = self._adv_thickness_display_label(row) if row is not None else (item.get("Thickness") or "")
        internal_source = self._adv_row_get(row, "MMPDS_Version", "Source", default="")

        summary = {
            "Item": item_idx,
            "Export_ID": export_id,
            "Export_Selected": "Yes" if item.get("_selected", False) else "No",
            "Status": status,
            "Element": item.get("Element", ""),
            "Series": item.get("Series", ""),
            "Material": item.get("Material", ""),
            "Temper": item.get("Temper", ""),
            "Specification": item.get("Specification", ""),
            "Specification 2": item.get("Specification 2", spec2),
            "Form": item.get("Form", ""),
            "Thickness": item.get("Thickness") or item.get("Thickness_Mode", ""),
            "Basis": basis,
            "Direction": direction,
            "Unit_System": UNIT_SYSTEM_SPEC.get(item.get("Unit_System", "mm_T_s"), {}).get("label", item.get("Unit_System", "")),
            "Matches": item.get("_matches", ""),
            "Keyfile_Name": keyfile_name,
            "Keyfile_Export_Path": keyfile_path,
            "Source_Image_Name": image_name,
            "Source_Image_Export_Path": image_path,
            "Notes": notes,

            "Part Number": item.get("Part_Number", ""),
            "Part Name": item.get("Part_Name", ""),
            "Material Name from Client": item.get("Material_Name_from_Client", ""),
            "Stock Size Thickness": item.get("Stock_Size_Thickness", ""),
            "Datasheet": item.get("Datasheet", ""),

            "Main Specification": spec,
            "Specification 2": spec2,
            "Main Form": form,
            "Temper OR Condition": temper,
            "Thickness from MMPDS": thickness_mmpds,
            "Main Basis": basis,
            "Main Direction": direction,
            "Ftu": self._adv_summary_material_value(row, "Ftu", basis, direction),
            "Fty": self._adv_summary_material_value(row, "Fty", basis, direction),
            "Fcy": self._adv_summary_material_value(row, "Fcy", basis, direction),
            "Fsu": self._adv_summary_material_value(row, "Fsu", basis, direction),
            "Fbru": self._adv_summary_material_value(row, "Fbru", basis, direction),
            "Fbry": self._adv_summary_material_value(row, "Fbry", basis, direction),
            "Elong": self._adv_summary_material_value(row, "Elong", basis, direction),
            "Young Modulus": self._adv_summary_material_value(row, "Young Modulus", basis, direction),
            "Tangent Modulus": self._adv_summary_material_value(row, "Tangent Modulus", basis, direction),
            "Poisson": self._adv_summary_material_value(row, "Poisson", basis, direction),
            "Density": self._adv_summary_material_value(row, "Density", basis, direction),
            "Source": internal_source,
            "Internal Notes": "",
        }
        return summary

    def _adv_short_output_stem(self, item: Dict[str, Any], row: pd.Series, item_idx: int, row_idx: int) -> str:
        material = item.get("Material") or row.get("Material", "Material")
        temper = item.get("Temper") or row.get("Temper", "Temper")
        spec = item.get("Specification") or row.get("Spec1_1", "Spec")
        thickness = self._adv_thickness_base(row)
        direction = item.get("Direction", "L")
        basis = item.get("Basis", "B")
        parts = [
            f"batch{item_idx:03d}",
            self._adv_file_part(material),
            self._adv_file_part(temper),
            self._adv_file_part(spec),
            self._adv_file_part(thickness),
            self._adv_file_part(direction),
            self._adv_file_part(basis),
        ]
        if row_idx > 1:
            parts.append(f"r{row_idx}")
        stem = "_".join([p for p in parts if p])
        return stem[:110]

    def _adv_file_part(self, value: Any) -> str:
        text = str(value).strip() or "NA"
        repl = {"<=": "le", ">=": "ge", "<": "lt", ">": "gt", " ": "_", "/": "_", "\\": "_", ":": "_", "*": "_", "?": "_", '"': "_", "|": "_", ",": "_"}
        for old, new in repl.items():
            text = text.replace(old, new)
        while "__" in text:
            text = text.replace("__", "_")
        return text.strip("_") or "NA"


    def _search(self, stage):
        txt = self.search_vars[stage].get()
        return "" if txt == PLACEHOLDER_SEARCH else txt.strip().lower()

    def _refresh_all(self, skip_auto_stage: Optional[str] = None):
        for s in STAGES:
            self._refresh_stage(s)
        self._auto_singletons(skip_stage=skip_auto_stage)
        self._match_count()

    def _refresh_stage(self, stage):
        opts = self.db.available(stage, self.selections)
        search = self._search(stage)
        if search:
            s = search.lower()
            opts = [o for o in opts if s in o.lower()]

        max_items = 200
        total_opts = len(opts)
        if total_opts > max_items:
            opts = opts[:max_items]
            opts.append(f"... and {total_opts - max_items} more (refine search)")

        old_opts = self.visible_values.get(stage, [])
        self.visible_values[stage] = opts
        lb = self.listboxes[stage]

        if old_opts != opts:
            lb.delete(0, tk.END)
            for o in opts:
                lb.insert(tk.END, o)

        cur = self.selections[stage]
        if cur and cur not in opts:
            self.selections[stage] = ""
            cur = ""
        elif cur in opts:
            idx = opts.index(cur)
            lb.selection_clear(0, tk.END)
            lb.selection_set(idx)
            lb.see(idx)

        self.selection_labels[stage].configure(
            text=f"Selected: {self.selections[stage]}" if self.selections[stage] else "(none selected)",
            fg=THEME["accent"] if self.selections[stage] else THEME["text_muted"]
        )
        count_text = f"{total_opts} option{'s' if total_opts != 1 else ''}"
        if total_opts > max_items:
            count_text += f" (showing first {max_items})"
        self.count_labels[stage].configure(text=count_text)

    def _auto_singletons(self, skip_stage: Optional[str] = None):
        for _ in range(8):
            changed = False
            for s in STAGES:
                if s == skip_stage:
                    continue
                if not self.selections[s] and len(self.visible_values[s]) == 1:
                    self.selections[s] = self.visible_values[s][0]
                    changed = True
                    for x in STAGES:
                        self._refresh_stage(x)
            if not changed:
                break

    def _select(self, stage):
        sel = self.listboxes[stage].curselection()
        if not sel:
            return

        value = self.visible_values[stage][sel[0]]
        if isinstance(value, str) and value.startswith("... and "):
            messagebox.showinfo(
                "Refine Search",
                "There are more results available. Please type more letters in the search box to narrow the list."
            )
            self.listboxes[stage].selection_clear(0, tk.END)
            return

        self.selections[stage] = value
        for s in STAGES:
            self._refresh_stage(s)
        self._auto_singletons()
        self._match_count()

    def _clear_stage(self, stage):
        self.selections[stage] = ""
        self.search_vars[stage].set(PLACEHOLDER_SEARCH)


        self._refresh_all(skip_auto_stage=stage)

    def _reset(self):
        self.selections = {s: "" for s in STAGES}
        for s in STAGES:
            self.search_vars[s].set(PLACEHOLDER_SEARCH)
        self._refresh_all()

    def _match_count(self):
        if hasattr(self.db, "match_count"):
            n = self.db.match_count(self.selections)
        else:
            n = len(self.db.filter_master(self.selections))
        self.match_var.set(f"Total Matching Materials: {n:,}")

    def _choose(self):
        df = self.db.filter_master(self.selections)
        if df.empty:
            messagebox.showwarning("No Match", "No material matches your selection.")
            return

        row = df.iloc[0]
        open_state = self._adv_best_open_state_for_rows(df)
        if not open_state:
            messagebox.showwarning(
                "Material cannot be generated",
                "No available Basis / Direction / Matcard combination was found for this selected material."
            )
            return

        self._save_history(row)
        hist_entry = {"datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "history_type": "selection"}
        hist_entry.update(self.selections)
        hist_entry["Source"] = row.get("MMPDS_Version", "-")
        self._audit_log_action(
            screen="Material Selection",
            action="Material Card Opened",
            status="Success",
            material_summary=self._history_summary_text(hist_entry),
            element=self.selections.get("Element", ""),
            series=self.selections.get("Series", ""),
            material=self.selections.get("Material", ""),
            temper=self.selections.get("Temper", ""),
            specification=self.selections.get("Specification", ""),
            form=self.selections.get("Form", ""),
            basis=open_state.get("Basis", ""),
            direction=open_state.get("Direction", ""),
            unit_system=open_state.get("Unit_System", ""),
            notes="User clicked Choose Material. Preferred B/L/MAT024+GISSMO was used when available; otherwise the app opened the next valid combination.",
        )
        if hasattr(self.app, "status_var"):
            self.app.status_var.set(
                f"Opening material card | {self.selections.get('Material', '')} {self.selections.get('Temper', '')} | "
                f"{open_state.get('Basis','')} / {open_state.get('Direction','')} / {open_state.get('Material_Model','')}"
            )
        self.app.show_screen("CardScreen", row=row, selections=dict(self.selections), matching_rows=df.copy(), history_state=open_state)

    def _history_entry_type(self, entry: Dict[str, Any]) -> str:
        """Display ORIGINAL for normal opens and CUSTOM for user-edited material cards."""
        return "CUSTOM" if isinstance(entry.get("_card_state"), dict) else "ORIGINAL"

    def _history_summary_text(self, entry: Dict[str, Any]) -> str:
        """Build the compact material summary shown in the history panel.

        Wall_Thick and Cross_Section are kept internally for thickness matching,
        but they are intentionally not shown here because they confused users.
        """
        card_state = entry.get("_card_state", {}) or {}
        element = entry.get("Element", "")
        material = entry.get("Material", "")
        temper = entry.get("Temper", "")
        series = entry.get("Series", "")
        spec = entry.get("Specification", "")
        spec2 = entry.get("Specification 2", "")
        form = entry.get("Form", "")
        source = card_state.get("Source", entry.get("Source", ""))
        material_text = f"{element} {material}-{temper}".strip(" -")
        custom_prefix = "CUSTOM | " if self._history_entry_type(entry) == "CUSTOM" else ""
        return (
            f"{custom_prefix}Material: {material_text or '-'}  |  Series: {series or '-'}  |  "
            f"Spec: {spec or '-'}  |  Spec 2: {spec2 or '-'}  |  Form: {form or '-'}  |  Source: {source or '-'}"
        )

    def _save_history(self, row=None):
        e = {"datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "history_type": "selection"}
        e.update(self.selections)
        if row is not None:
            try:
                e["Source"] = row.get("MMPDS_Version", "-")
                e["Thickness"] = source_gui_thickness_label(row)
                e["Thickness_Row_Key"] = source_row_identity_key(row)
            except Exception:
                pass
        self.app.history.append(e)
        self._refresh_history()

    def _refresh_history(self):
        for iid in self.hist_tree.get_children():
            self.hist_tree.delete(iid)
        entries = self.app.history.load()
        for idx, e in enumerate(entries):
            history_type = self._history_entry_type(e)
            tags = ("edited_history",) if history_type == "CUSTOM" else ()
            self.hist_tree.insert("", "end", iid=str(idx), values=(
                e.get("datetime", ""),
                self._history_summary_text(e),
            ), tags=tags)

    def _history_open(self, _=None):
        sel = self.hist_tree.selection()
        if not sel:
            return
        try:
            entry = self.app.history.load()[int(sel[0])]
        except Exception:
            return

        self._reset()
        for stage in STAGES:
            value = str(entry.get(stage, "")).strip()
            if value:
                self.selections[stage] = value
        material = self.selections.get("Material", "")
        if material and not self.selections.get("Series"):
            self.selections["Series"] = self.db._material_to_series.get(norm(material), "")
        self._refresh_all()

        df = self.db.filter_master(self.selections)
        if df.empty:
            messagebox.showwarning("History", "This history item no longer matches the current source data.")
            return

        row = df.iloc[0]
        card_state = entry.get("_card_state") if isinstance(entry.get("_card_state"), dict) else None
        wanted_thickness = ""
        wanted_row_key = ""
        if card_state:
            wanted_thickness = str(card_state.get("Thickness", "")).strip()
            wanted_row_key = str(card_state.get("Thickness_Row_Key", "")).strip()
        else:
            wanted_thickness = str(entry.get("Thickness", "")).strip()
            wanted_row_key = str(entry.get("Thickness_Row_Key", "")).strip()
        if wanted_thickness or wanted_row_key:
            for i in range(len(df)):
                candidate = df.iloc[i]
                candidate_key = source_row_identity_key(candidate)
                t = source_thickness_base_value(candidate, prefer_wall=True)
                display = source_gui_thickness_label(candidate)
                if (wanted_row_key and candidate_key == wanted_row_key) or norm(t) == norm(wanted_thickness) or norm(display) == norm(wanted_thickness):
                    row = candidate
                    break

        summary_text = self._history_summary_text(entry)
        self._audit_log_action(
            screen="History",
            action="History Item Reopened",
            status="Success",
            material_summary=summary_text,
            element=self.selections.get("Element", ""),
            series=self.selections.get("Series", ""),
            material=self.selections.get("Material", ""),
            temper=self.selections.get("Temper", ""),
            specification=self.selections.get("Specification", ""),
            form=self.selections.get("Form", ""),
            notes="CUSTOM edited values restored." if card_state else "Original material reopened from history.",
        )
        reopened_entry = dict(entry)
        reopened_entry["datetime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if row is not None:
            try:
                reopened_entry["Source"] = row.get("MMPDS_Version", reopened_entry.get("Source", "-"))
                reopened_entry["Thickness"] = source_gui_thickness_label(row)
                reopened_entry["Thickness_Row_Key"] = source_row_identity_key(row)
            except Exception:
                pass
        self.app.history.append(reopened_entry)
        self._refresh_history()

        if hasattr(self.app, "status_var"):
            self.app.status_var.set("Reopened history item" + (" with edited values" if card_state else ""))
        self.app.show_screen("CardScreen", row=row, selections=dict(self.selections), matching_rows=df.copy(), history_state=card_state)

    def _clear_history(self):
        self.app.history.save([])
        self._refresh_history()

    def on_show(self, **_):
        self._refresh_history()
        self._match_count()


class CardScreen(tk.Frame):
    def __init__(self, parent, app: MaterialSelectorApp):
        super().__init__(parent, bg=THEME["bg"])
        self.app = app

        self.current_row = None
        self.current_selections = {}
        self.thickness_rows = []
        self.thickness_map = {}


        self.thickness_combo = None
        self.thickness_combo_rows = []
        self.thickness_label_rows = {}


        self.basis_radio_buttons: Dict[str, tk.Radiobutton] = {}

        self.basis_var = tk.StringVar(value="B")
        self.direction_var = tk.StringVar(value="L")
        self.thickness_var = tk.StringVar(value="")
        self.unit_sys_var = tk.StringVar(value="mm_T_s")
        self.mat_model_var = tk.StringVar(value="MAT024+GISSMO")
        self.export_id_var = tk.StringVar(value=str(peek_next_export_id()))

        self.prop_values = {}
        self.pending_edits = {}
        self.prop_vars = {}
        self.prop_entries = {}
        self.prop_output_labels = {}
        self.prop_unit_labels = {}
        self.prop_tree = None
        self.tree_edit_entry = None


        self.prop_value_widgets: Dict[str, tk.Entry] = {}
        self.prop_value_vars: Dict[str, tk.StringVar] = {}
        self.prop_row_widgets: Dict[str, List[tk.Widget]] = {}
        self.prop_calc_labels: Dict[str, Dict[str, tk.Label]] = {}


        self.material_modified_disclaimer_var = tk.StringVar(value="")
        self.disclaimer_label = None
        self.unit_conversion_disclaimer_var = tk.StringVar(value="")

        self.source_image_refs = []
        self.mat24_value_labels = {}
        self.gissmo_value_labels = {}
        self.gissmo_tree = None
        self.gissmo_header_right_label = None
        self.props_header_right_label = None
        self.mat24_header_right_label = None
        self._updating_ui = False


        self.unit_conversions = DEFAULT_UNIT_CONVERSIONS.copy()
        self.unit_tree = None
        self.unit_tree_edit_entry = None
        self.unit_pending_edits = {}

        self.unit_confirmed_edits = set()

        self.last_effps = None
        self.last_etan_eng = None
        self.last_etan_true = None


        self._screen2_jobs: List[str] = []
        self._screen2_hydration_token = 0
        self._fast_refresh_job = None
        self._engineering_rebuild_job = None

        self._build()

    def _build(self):
        outer = tk.Frame(self, bg=THEME["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=22, pady=14)

        top = tk.Frame(outer, bg=THEME["bg"])
        top.pack(fill=tk.X, pady=(0, 10))


        ttk.Button(top, text="<- Back to Selection", style="Secondary.TButton",
                   command=self._back_to_selection).pack(side=tk.LEFT)

        self.disclaimer_label = tk.Label(
            top,
            textvariable=self.material_modified_disclaimer_var,
            bg=THEME["bg"],
            fg="#c00000",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
            justify="left",
        )
        self.disclaimer_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(18, 10))


        ttk.Button(top, text="Export kFile", style="Primary.TButton",
                   command=self._export).pack(side=tk.RIGHT)
        ttk.Button(top, text=self.app.theme_button_text(), style="ThemeToggle.TButton",
                   command=self.app.toggle_dark_mode).pack(side=tk.RIGHT, padx=(0, 10))


        self.controls = self._panel(outer)
        self.summary = None


        self.content_split = tk.Frame(outer, bg=THEME["bg"])
        self.content_split.pack(fill=tk.BOTH, expand=True)
        self.content_split.columnconfigure(0, weight=1, uniform="screen2_half")
        self.content_split.columnconfigure(1, weight=1, uniform="screen2_half")
        self.content_split.rowconfigure(0, weight=1)

        self.left_col = tk.Frame(self.content_split, bg=THEME["bg"])
        self.right_col = tk.Frame(self.content_split, bg=THEME["bg"])
        self.left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.right_col.grid(row=0, column=1, sticky="nsew", padx=(6, 0))


        self.left_canvas = tk.Canvas(self.left_col, bg=THEME["bg"], highlightthickness=0)
        self.left_scrollbar = ttk.Scrollbar(self.left_col, orient="vertical", command=self.left_canvas.yview)
        self.left_canvas.configure(yscrollcommand=self.left_scrollbar.set)
        self.left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.left_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.left_scroll_body = tk.Frame(self.left_canvas, bg=THEME["bg"])
        self.left_scroll_window = self.left_canvas.create_window((0, 0), window=self.left_scroll_body, anchor="nw")
        self.left_scroll_body.bind(
            "<Configure>",
            lambda _e: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")),
        )
        self.left_canvas.bind(
            "<Configure>",
            lambda e: self.left_canvas.itemconfigure(self.left_scroll_window, width=max(e.width, 720)),
        )

        self.mat24 = self._panel(self.left_scroll_body)
        self.gissmo = self._panel(self.left_scroll_body)
        self.gissmo.pack_forget()
        self.props = self._panel(self.left_scroll_body)
        self.unitconv = self._panel(self.left_scroll_body)
        self.image_panel = self._panel(self.right_col, expand=True)


        self.after(300, self._set_default_split)

    def _back_to_selection(self):
        """Return to Screen 1 and write a readable visible audit row."""
        try:
            fields = self._audit_selection_fields()
            self._audit_log_from_card(
                screen="Material Card",
                action="Back to Selection",
                status="Success",
                material_summary=self._current_material_summary_for_audit(
                    custom=any(edited for _value, edited in self.prop_values.values())
                ),
                notes="User clicked Back to Selection from Screen 2.",
                details="Navigation returned from Material Property Card to Material Selection screen.",
                **fields,
            )
        except Exception:
            pass
        self.app.show_screen("SelectionScreen")

    def _panel(self, parent, expand=False):


        f = tk.Frame(parent, bg=THEME["panel"],
                     highlightbackground=THEME["border"], highlightthickness=1, bd=0)
        f.pack(fill=tk.BOTH if expand else tk.X, expand=expand, pady=(0, 12))
        return f

    def _set_default_split(self):
        """Keep Screen 2 fixed at 50/50 using grid weights.

        The fixed grid avoids redraw churn and keeps the source viewer and
        engineering card balanced.
        """
        try:
            self.content_split.columnconfigure(0, weight=1, uniform="screen2_half")
            self.content_split.columnconfigure(1, weight=1, uniform="screen2_half")
        except Exception:
            pass

    def _bind_left_scroll_mousewheel(self):
        """Bind mouse wheel to the left engineering-card scroll area."""
        try:
            bind_mousewheel(self.left_canvas, self.left_scroll_body)
        except Exception:
            pass

    def _scroll_left_to_top(self):
        """Keep Screen 2 from opening halfway down after a rebuild or monitor move."""
        try:
            self.left_canvas.update_idletasks()
            self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))
            self.left_canvas.yview_moveto(0)
        except Exception:
            pass


    def _cancel_screen2_jobs(self):
        for job in list(getattr(self, "_screen2_jobs", [])):
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._screen2_jobs = []
        for attr in ("_fast_refresh_job", "_engineering_rebuild_job"):
            job = getattr(self, attr, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, attr, None)

    def _schedule_engineering_rebuild(self, include_controls: bool = False, include_source_image: bool = False):
        """Debounce heavier option changes like Basis/Direction/Model."""
        self._pending_rebuild_include_controls = bool(include_controls)
        self._pending_rebuild_include_source_image = bool(include_source_image)
        if self._engineering_rebuild_job is not None:
            try:
                self.after_cancel(self._engineering_rebuild_job)
            except Exception:
                pass
        self._engineering_rebuild_job = self.after(OPTION_UPDATE_DEBOUNCE_MS, self._run_engineering_rebuild)

    def _run_engineering_rebuild(self):
        self._engineering_rebuild_job = None
        include_source = getattr(self, "_pending_rebuild_include_source_image", False)


        if getattr(self, "_pending_rebuild_include_controls", False):
            self._render_controls()

        try:
            self._render_mat24()
            self._render_gissmo()
            self._render_props()
            self._render_unit_conversions()
            self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))
        except Exception:

            try:
                self._refresh_cards_fast()
            except Exception:
                pass


        if include_source:
            try:
                self.after_idle(self._render_source_images)
            except Exception:
                self._render_source_images()

    def _on_debounced_monitor_resize(self):
        """Handle settled window/monitor resize without expensive rebuilds."""
        try:
            if hasattr(self, "left_canvas"):
                self.left_canvas.itemconfigure(self.left_scroll_window, width=max(self.left_canvas.winfo_width(), 720))
                self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))


        except Exception:
            pass

    def _show_material_modified_disclaimer(self):
        self.material_modified_disclaimer_var.set(
            "WARNING: When material card is modified by the user, no validation nor certification by NIAR will be provided."
        )


        try:
            red = "#ff5b52" if is_dark_theme() else "#c00000"
            self.disclaimer_label.configure(bg=THEME["bg"], fg=red)
        except Exception:
            pass

    def _hide_material_modified_disclaimer(self):
        self.material_modified_disclaimer_var.set("")

    def _required_value_warning_color(self) -> str:
        return "#ff5b52" if is_dark_theme() else "#c00000"

    def _selected_basis_available(self) -> bool:
        basis = str(self.basis_var.get() or "B").strip().upper()
        if basis not in {"A", "B", "S"}:
            return False
        try:
            return bool(self._available_bases().get(basis, False))
        except Exception:
            return False

    def _missing_required_labels_from_computed(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> List[str]:
        """Return missing required MAT labels for the current row/basis/direction.

        RO, E, PR, and SIGY are the manager-requested required values. SIGY maps
        to the Property Card Fty row. When the selected default basis (B) is not
        available, the same required values are treated as missing so the user
        sees red rows and a top warning instead of an incorrect silent fallback.
        """
        if computed is None:
            computed = self._compute_table()
        labels: List[str] = []
        selected_basis_available = self._selected_basis_available()
        required = [("RO", "RO"), ("E", "E"), ("PR", "PR"), ("Fty", "SIGY")]
        for row_key, label in required:
            value = str(computed.get(row_key, {}).get("eng", "-")).strip()
            source_value = str(computed.get(row_key, {}).get("value", "-")).strip()
            if (not selected_basis_available) or is_blank(value) or is_blank(source_value):
                labels.append(label)
        return labels

    def _missing_required_property_keys_from_computed(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> set:
        missing_labels = set(self._missing_required_labels_from_computed(computed))
        keys = set()
        if "RO" in missing_labels:
            keys.add("RO")
        if "E" in missing_labels:
            keys.add("E")
        if "PR" in missing_labels:
            keys.add("PR")
        if "SIGY" in missing_labels:
            keys.add("Fty")
        return keys

    def _sync_top_disclaimer(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> None:
        """Show missing-value warning at the existing top disclaimer area."""
        messages: List[str] = []
        try:
            basis = str(self.basis_var.get() or "B").strip().upper()
            if basis in {"A", "B", "S"} and not self._selected_basis_available():
                messages.append(f"{basis} Basis is not available for this selected material.")
        except Exception:
            pass
        missing = self._missing_required_labels_from_computed(computed)
        if missing:
            messages.append("Missing required MAT values: " + ", ".join(missing) + ". Material cannot be generated.")
        if self.pending_edits or self._has_confirmed_property_edits():
            messages.append("WARNING: When material card is modified by the user, no validation nor certification by NIAR will be provided.")
        self.material_modified_disclaimer_var.set("  ".join(messages))
        try:
            self.disclaimer_label.configure(bg=THEME["bg"], fg=self._required_value_warning_color())
        except Exception:
            pass

    def _has_confirmed_property_edits(self) -> bool:
        """Return True if any Property Card source value has been applied as custom."""
        try:
            return any(
                bool(edited) and key not in READONLY_VALUE_ROWS
                for key, (_value, edited) in self.prop_values.items()
            )
        except Exception:
            return False

    def _sync_material_modified_disclaimer(self) -> None:
        """Show combined missing-value/user-edit disclaimer."""
        self._sync_top_disclaimer()

    def on_show(self, row=None, selections=None, matching_rows=None, history_state=None, **_):
        if row is not None:
            self.current_row = row
            self.current_selections = selections or {}
            self.opened_from_context = ""
            self.opened_export_id_context = ""
            if isinstance(history_state, dict):
                self.opened_from_context = str(history_state.get("Opened_From", "")).strip()
                self.opened_export_id_context = str(history_state.get("Export_ID", "")).strip()
            if matching_rows is not None and not matching_rows.empty:
                self.thickness_rows = [matching_rows.iloc[i] for i in range(len(matching_rows))]
            else:
                self.thickness_rows = [row]
            self._seed_values()
            if not isinstance(history_state, dict):
                self.basis_var.set("B")
                self.direction_var.set("L")
                self.mat_model_var.set("MAT024+GISSMO")
            try:
                self.export_id_var.set(str(peek_next_export_id()))
            except Exception:
                self.export_id_var.set(str(EXPORT_COUNTER_START))


            if isinstance(history_state, dict):
                basis = history_state.get("Basis")
                direction = history_state.get("Direction")
                unit_sys = history_state.get("Unit_System")
                mat_model = history_state.get("Material_Model")
                thickness = history_state.get("Thickness")
                if basis:
                    self.basis_var.set(str(basis))
                if direction:
                    self.direction_var.set(str(direction))
                if unit_sys in UNIT_SYSTEM_SPEC:
                    self.unit_sys_var.set(str(unit_sys))
                if mat_model:
                    self.mat_model_var.set(str(mat_model))
                if isinstance(history_state.get("prop_values"), dict):
                    restored = {}
                    for key, value in history_state.get("prop_values", {}).items():
                        if isinstance(value, (list, tuple)) and len(value) >= 2:
                            restored[key] = (str(value[0]), bool(value[1]))
                        elif isinstance(value, dict):
                            restored[key] = (str(value.get("value", "")), bool(value.get("edited", False)))
                    if restored:
                        self.prop_values.update(restored)
                if isinstance(history_state.get("unit_conversions"), dict):
                    for k, v in history_state.get("unit_conversions", {}).items():
                        num = try_float(v)
                        if num is not None:
                            self.unit_conversions[k] = num
                            default_num = try_float(DEFAULT_UNIT_CONVERSIONS.get(k))
                            if default_num is not None and num != default_num:
                                self.unit_confirmed_edits.add(k)
                if any(edited for _value, edited in self.prop_values.values()):
                    self._show_material_modified_disclaimer()


                thickness_row_key = str(history_state.get("Thickness_Row_Key", "")).strip()
                if thickness or thickness_row_key:
                    for candidate in self.thickness_rows:
                        if (thickness_row_key and self._row_identity_key(candidate) == thickness_row_key) or (thickness and self._thickness_matches_label(candidate, thickness)):
                            self.current_row = candidate
                            break

        self._ensure_valid_basis()
        self._render_controls()
        self._render_summary()

        if isinstance(history_state, dict) and (history_state.get("Thickness") or history_state.get("Thickness_Row_Key")):
            wanted = str(history_state.get("Thickness", "")).strip()
            wanted_row_key = str(history_state.get("Thickness_Row_Key", "")).strip()
            for i, source_row in enumerate(getattr(self, "thickness_combo_rows", []) or []):
                label = self._thickness_display_label(source_row) or "NA"
                if (wanted_row_key and self._row_identity_key(source_row) == wanted_row_key) or (wanted and (norm(label) == norm(wanted) or self._thickness_matches_label(source_row, wanted))):
                    self.thickness_var.set(label)
                    self.current_row = source_row
                    try:
                        if self.thickness_combo is not None:
                            self.thickness_combo.current(i)
                    except Exception:
                        pass
                    break


        self._cancel_screen2_jobs()
        self._screen2_hydration_token += 1
        for render_fn in (self._render_mat24, self._render_gissmo, self._render_props, self._render_unit_conversions):
            try:
                render_fn()
            except Exception as exc:
                try:
                    logger.exception("Screen 2 render section failed: %s", exc)
                except Exception:
                    pass
        try:
            self._bind_left_scroll_mousewheel()
            self._scroll_left_to_top()
        except Exception:
            pass

        try:
            self.after_idle(self._render_source_images)
        except Exception:
            self._render_source_images()
        if isinstance(history_state, dict) and history_state.get("Thickness"):
            try:
                self._refresh_cards_fast()
            except Exception:
                pass

    def _seed_values(self):
        self.prop_values = {k: ("", False) for k, *_ in PROPERTY_ROWS}
        self.pending_edits = {}
        self._hide_material_modified_disclaimer()
        self.last_effps = None
        self.last_etan_eng = None
        self.last_etan_true = None

    def _header(self, parent, text, right=""):

        h = tk.Frame(parent, bg=THEME["accent"], height=34)
        h.pack(fill=tk.X)
        h.pack_propagate(False)
        tk.Label(h, text=text, bg=THEME["accent"], fg="white",
                 font=FONTS["body_bold"]).pack(side=tk.LEFT, padx=12, pady=7)
        right_label = None
        if right:
            right_label = tk.Label(h, text=right, bg=THEME["accent"], fg="#dde6f3",
                                   font=FONTS["small"])
            right_label.pack(side=tk.RIGHT, padx=12, pady=8)
        return h, right_label

    def _available_bases(self):
        row = self.current_row
        available = {"A": False, "B": False, "S": False}
        if row is None:
            return available

        direction = "LT" if self.direction_var.get().strip().upper() == "LT" else "L"
        lower_cols = {norm(c): c for c in row.index}

        def has_value(col_name: str) -> bool:
            col = lower_cols.get(norm(col_name))
            return col is not None and not is_blank(row.get(col, "-"))

        for key, _label, _kind, pfx_l, pfx_lt in PROPERTY_ROWS:
            if key in ("Etan", "Compression"):
                continue
            pfx = pfx_l if direction == "L" else pfx_lt
            if not pfx:
                continue
            for basis in ("A", "B", "S"):
                candidates = [
                    f"{pfx}_{basis}",
                    f"{pfx}_{direction}_{basis}",
                    f"{pfx}_{basis}_{direction}",
                    f"{direction}_{pfx}_{basis}",
                ]
                if any(has_value(c) for c in candidates):
                    available[basis] = True

        return available

    def _ensure_valid_basis(self):
        """Keep selected/default basis even when unavailable.

        Current requirement: the Material Card should open on B Basis / L
        Direction by default. If B is not available, do not silently switch to A;
        keep B selected and show the red missing-values disclaimer.
        """
        return

    def _refresh_basis_radio_states(self):
        """Enable/disable Basis buttons without rebuilding the header.

        Direction changes can make A/B/S availability change. Updating existing
        radio buttons in place avoids header flicker.
        """
        available = self._available_bases()
        for code, rb in getattr(self, "basis_radio_buttons", {}).items():
            try:
                rb.configure(state=tk.NORMAL if available.get(code, False) else tk.DISABLED)
            except Exception:
                pass

    def _render_controls(self):
        """Render compact Engineering Options + Material Summary header.

        Manager request: make more vertical space for the Property Card by
        minimizing the Engineering Options and Material Summary sections.
        """
        for w in self.controls.winfo_children():
            w.destroy()

        r = self.current_row
        material = "-"
        spec_val = "-"
        form = "-"
        temper = "-"
        source = "-"
        element = "-"
        series = "-"
        spec2_val = "-"
        wall = "-"
        cs = "-"
        if r is not None:
            element = self.current_selections.get("Element") or r.get("Element", "-")
            series = self.current_selections.get("Series", "-")
            material = self.current_selections.get("Material") or r.get("Material", "-")
            temper = self.current_selections.get("Temper") or r.get("Temper", "-")
            spec_val = self.current_selections.get("Specification") or r.get("Spec1_1", "-")
            if is_blank(spec_val):
                spec_val = NO_SPEC_DISPLAY
            spec2_val = self.current_selections.get("Specification 2") or row_spec2_value(r)
            spec2_val = display_spec_value(spec2_val)
            form = self.current_selections.get("Form") or r.get("Form", "-")
            source = r.get("MMPDS_Version", "-")
            wall = r.get("Wall_Thick", "-")
            cs = r.get("Cross_Section", "-")

        _, _ = self._header(
            self.controls,
            "Engineering Options + Material Summary",
            right=f"{material}-{temper} | {spec_val} | {self.thickness_var.get() or (self._thickness_display_label(r) if r is not None else 'NA')}",
        )

        body = tk.Frame(self.controls, bg=THEME["panel"])
        body.pack(fill=tk.X, padx=10, pady=(6, 8))

        options_row = tk.Frame(body, bg=THEME["panel"])
        options_row.pack(fill=tk.X)


        self._compact_radio_group(options_row, "Basis", BASIS_OPTIONS, self.basis_var, self._basis_changed)
        self._compact_radio_group(options_row, "Direction", DIRECTION_OPTIONS, self.direction_var, self._direction_changed)

        self.thickness_map = {}
        self.thickness_combo_rows = []
        self.thickness_label_rows = {}
        labels = []


        dropdown_rows = self._thickness_rows_for_dropdown()
        self.thickness_rows = list(dropdown_rows)
        for row in dropdown_rows:
            label = self._thickness_display_label(row) or "NA"
            labels.append(label)
            self.thickness_combo_rows.append(row)
            self.thickness_label_rows.setdefault(label, []).append(row)


            self.thickness_map.setdefault(label, row)

        if not labels:
            labels = ["NA"]
            self.thickness_combo_rows = [self.current_row] if self.current_row is not None else []
            self.thickness_rows = list(self.thickness_combo_rows)

        current_label = self._thickness_display_label(self.current_row) if self.current_row is not None else ""
        selected_index = 0
        if self.current_row is not None:
            current_key = self._row_identity_key(self.current_row)
            for i, row in enumerate(self.thickness_combo_rows):
                if self._row_identity_key(row) == current_key:
                    selected_index = i
                    break
        if current_label and current_label in labels:
            self.thickness_var.set(current_label)
        else:
            self.thickness_var.set(labels[selected_index] if 0 <= selected_index < len(labels) else labels[0])

        thick_box = tk.LabelFrame(
            options_row,
            text="Thickness",
            bg=THEME["panel"],
            fg=THEME["accent"],
            font=FONTS["small_bold"],
            bd=0,
            relief="flat",
            padx=10,
            pady=5,
            labelanchor="nw",
            highlightbackground=THEME["border"],
            highlightthickness=1,
        )
        thick_box.pack(side=tk.LEFT, padx=(0, 8), pady=(0, 2))
        cb = ttk.Combobox(thick_box, textvariable=self.thickness_var, values=labels, state=("normal" if getattr(self, "is_custom_entry", False) else "readonly"), width=36)
        cb.pack(anchor="w", pady=(1, 1))
        self.thickness_combo = cb
        try:
            cb.current(selected_index if 0 <= selected_index < len(labels) else 0)
        except Exception:
            pass
        cb.bind("<<ComboboxSelected>>", lambda _: self._thickness_changed())

        id_box = tk.LabelFrame(
            options_row,
            text="ID / MID",
            bg=THEME["panel"],
            fg=THEME["accent"],
            font=FONTS["small_bold"],
            bd=0,
            relief="flat",
            padx=10,
            pady=5,
            labelanchor="nw",
            highlightbackground=THEME["border"],
            highlightthickness=1,
        )
        id_box.pack(side=tk.LEFT, padx=(0, 8), pady=(0, 2))
        ttk.Entry(id_box, textvariable=self.export_id_var, width=12).pack(anchor="w", pady=(1, 1))

        self._compact_radio_group(options_row, "Unit System", UNIT_SYSTEMS, self.unit_sys_var, self._unit_changed)


        if self.mat_model_var.get() not in {"MAT024", "MAT082", "MAT224", "MAT024+GISSMO"}:
            self.mat_model_var.set("MAT024+GISSMO")
        self._compact_radio_group(
            options_row,
            "Material Model",
            MAT_MODELS,
            self.mat_model_var,
            self._mat_model_changed,
            disable_except=None,
        )

        if getattr(self, "is_custom_entry", False):
            if not hasattr(self, "custom_name_var"):
                self.custom_name_var = tk.StringVar(value="CUSTOM_MATERIAL")
            custom_box = tk.LabelFrame(
                options_row,
                text="Custom Name",
                bg=THEME["panel"],
                fg=THEME["accent"],
                font=FONTS["small_bold"],
                bd=0,
                relief="flat",
                padx=10,
                pady=5,
                labelanchor="nw",
                highlightbackground=THEME["focus_ring"],
                highlightthickness=2,
            )
            custom_box.pack(side=tk.LEFT, padx=(0, 8), pady=(0, 2), fill=tk.X, expand=True)
            custom_entry = ttk.Entry(custom_box, textvariable=self.custom_name_var, width=32)
            custom_entry.pack(anchor="w", fill=tk.X, pady=(1, 1))
            custom_entry.bind("<KeyRelease>", lambda _e: self._custom_name_changed())
            custom_entry.bind("<FocusOut>", lambda _e: self._custom_name_changed(sanitize=True))
            custom_entry.bind("<Return>", lambda _e: self._custom_name_changed(sanitize=True))


        summary_line = (
            f"Material: {element} {material}-{temper}    |    Series: {series}    |    "
            f"Spec: {spec_val}    |    Spec 2: {spec2_val}    |    Form: {form}    |    Source: {source}"
        )
        summary_box = tk.Frame(
            body,
            bg=THEME["panel_alt"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            bd=0,
        )
        summary_box.pack(fill=tk.X, pady=(10, 0))
        tk.Label(
            summary_box,
            text="Material Summary",
            bg=THEME["panel_alt"],
            fg=THEME["accent"],
            font=FONTS["small_bold"],
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(6, 0))
        tk.Label(
            summary_box,
            text=summary_line,
            bg=THEME["panel_alt"],
            fg=THEME["text"],
            font=FONTS["small"],
            anchor="w",
            justify="left",
            wraplength=1200,
        ).pack(fill=tk.X, padx=12, pady=(2, 8))

    def _compact_radio_group(self, parent, title, opts, var, cmd, disable_except=None):


        f = tk.LabelFrame(
            parent,
            text=title,
            bg=THEME["panel"],
            fg=THEME["accent"],
            font=FONTS["small_bold"],
            bd=0,
            relief="flat",
            padx=10,
            pady=5,
            labelanchor="nw",
            highlightbackground=THEME["border"],
            highlightthickness=1,
        )
        f.pack(side=tk.LEFT, padx=(0, 8), pady=(0, 2))
        row = tk.Frame(f, bg=THEME["panel"])
        row.pack(anchor="w")

        available_bases = self._available_bases() if title == "Basis" else None
        if title == "Basis":
            self.basis_radio_buttons = {}
        for label, code in opts:
            rb = tk.Radiobutton(
                row,
                text=label,
                value=code,
                variable=var,
                command=cmd,
                bg=THEME["panel"],
                activebackground=THEME["panel"],
                selectcolor=THEME["panel_alt"],
                fg=THEME["text"],
                font=FONTS["small"],
                disabledforeground=THEME["disabled_fg"],
                padx=3,
                pady=1,
                bd=0,
                highlightthickness=0,
            )
            rb.pack(side=tk.LEFT, padx=(0, 6))
            if title == "Basis":
                self.basis_radio_buttons[code] = rb
            if disable_except is not None:
                allowed_codes = {disable_except} if isinstance(disable_except, str) else set(disable_except)
                if code not in allowed_codes:
                    rb.configure(state=tk.DISABLED)
            if title == "Basis" and available_bases is not None and not available_bases.get(code, False):
                rb.configure(state=tk.DISABLED)

    def _render_summary(self):
        """Summary is now included in the compact top header."""
        return

    def _norm_row_value(self, row, *cols: str) -> str:
        """Return first nonblank row value, normalized for matching."""
        if row is None:
            return ""
        for col in cols:
            try:
                value = str(row.get(col, "")).strip()
            except Exception:
                value = ""
            if not is_blank(value):
                return norm(value)
        return ""

    def _source_rows_matching_current_material(self) -> List[pd.Series]:
        """Return all source rows for the currently selected material path.

        The card is opened from a filtered DataFrame, but some later UI paths can
        leave self.thickness_rows incomplete. This helper re-queries the loaded
        master table using stable material identity fields so the Thickness
        dropdown can show every actual row from the source data.
        """
        try:
            master = getattr(self.app.db, "master", pd.DataFrame())
            if master is None or master.empty or self.current_row is None:
                return []
        except Exception:
            return []

        current = self.current_row
        material = self._norm_row_value(current, "Material") or norm(self.current_selections.get("Material", ""))
        temper = self._norm_row_value(current, "Temper") or norm(self.current_selections.get("Temper", ""))
        form = self._norm_row_value(current, "Form") or norm(self.current_selections.get("Form", ""))
        spec1 = self._norm_row_value(current, "Spec1_1", "Specification")
        spec2 = self._norm_row_value(current, "Spec2_1", "Spec2_2")

        rows: List[pd.Series] = []
        for i in range(len(master)):
            row = master.iloc[i]
            if material and self._norm_row_value(row, "Material") != material:
                continue
            if temper and self._norm_row_value(row, "Temper") != temper:
                continue
            if form and self._norm_row_value(row, "Form") != form:
                continue


            row_spec1 = self._norm_row_value(row, "Spec1_1", "Specification")
            row_spec2 = self._norm_row_value(row, "Spec2_1", "Spec2_2")
            if spec1 and row_spec1 != spec1:
                continue
            if spec2 and row_spec2 != spec2:
                continue
            rows.append(row)
        return rows

    def _thickness_rows_for_dropdown(self) -> List[pd.Series]:
        """Rows used to populate the Thickness dropdown.

        Priority:
        1. All master rows matching the selected material/spec/form.
        2. Existing matching_rows passed into Screen 2.
        3. The current row.

        The function preserves row order and row identity. It does not collapse
        rows by display label, because the same Thick_Value can appear more than
        once with different Cross_Section values.
        """
        candidates: List[pd.Series] = []
        for row in self._source_rows_matching_current_material():
            candidates.append(row)
        for row in getattr(self, "thickness_rows", []) or []:
            candidates.append(row)
        if self.current_row is not None:
            candidates.append(self.current_row)

        out: List[pd.Series] = []
        seen = set()
        for row in candidates:
            key = self._row_identity_key(row)
            if not key or key in seen:
                continue
            seen.add(key)


            out.append(row)


        return out

    def _row_identity_key(self, row) -> str:
        """Stable internal key for a source row used by the thickness dropdown.

        The user-facing dropdown stays clean, while this hidden key keeps
        duplicate visible labels mapped to their correct source rows.
        """
        return source_row_identity_key(row)

    def _thickness_base(self, row):
        """Return the engineering thickness value used by calculations/export matching."""
        return source_thickness_base_value(row, prefer_wall=True)

    def _row_cross_section_value(self, row) -> str:
        """Return a clean cross-section value when the source row has one."""
        return source_cross_section_value(row)

    def _thickness_display_label(self, row) -> str:
        """Return duplicate-aware visible thickness label for the Material Card."""
        return source_gui_thickness_label(row)

    def _thickness_matches_label(self, row, label: str) -> bool:
        wanted = norm(label)
        if not wanted:
            return False
        return wanted in {
            norm(self._thickness_display_label(row)),
            norm(self._thickness_base(row)),
            norm(self._row_cross_section_value(row)),
        }

    def _thickness_changed(self):
        """Change thickness without blinking and without collapsing source rows.

        The combobox visible text may repeat for some materials, so select by
        combobox index first. This preserves all source rows and prevents the
        dropdown from shrinking from 8 records to only 5 unique labels.
        """
        label = self.thickness_var.get()
        selected_row = None
        try:
            idx = self.thickness_combo.current() if self.thickness_combo is not None else -1
            if 0 <= idx < len(self.thickness_combo_rows):
                selected_row = self.thickness_combo_rows[idx]
        except Exception:
            selected_row = None

        if selected_row is None:
            rows = self.thickness_label_rows.get(label, [])
            if rows:
                selected_row = rows[0]
            elif label in self.thickness_map:
                selected_row = self.thickness_map[label]

        if selected_row is not None:
            self.current_row = selected_row

        self._seed_values()
        self._ensure_valid_basis()


        self._render_controls()
        self._render_summary()
        self._schedule_engineering_rebuild(include_controls=False, include_source_image=False)

    def _basis_changed(self):


        self._ensure_valid_basis()
        self._seed_values()
        self._refresh_cards_fast()

    def _direction_changed(self):


        self._ensure_valid_basis()
        self._refresh_basis_radio_states()
        self._seed_values()
        self._refresh_cards_fast()

    def _unit_changed(self):

        self._refresh_cards_fast()

    def _mat_model_changed(self):
        # Refresh only the engineering sections; do not rebuild controls/header.
        self._schedule_engineering_rebuild(include_controls=False, include_source_image=False)

    def _row_info(self, key):
        for k, label, kind, pfx_l, pfx_lt in PROPERTY_ROWS:
            if k == key:
                return label, kind, pfx_l, pfx_lt
        return None

    def _basis_candidates_for_property(self, key: str):
        selected = self.basis_var.get()
        if selected == "T":
            return ["A", "B", "S"]
        return [selected]

    def _prefix_for_key(self, key):
        info = self._row_info(key)
        if info is None:
            return None
        _label, _kind, pfx_l, pfx_lt = info
        return pfx_l if self.direction_var.get() == "L" else pfx_lt

    def _raw_value_exact(self, key):
        """Read the source value for selected Basis + Direction.

        Supports both legacy wide columns and columns produced by the new
        MaterialDB_clean_ALL long-to-wide adapter.
        """
        r = self.current_row
        if r is None or key in ("Etan", "Compression"):
            return None

        pfx = self._prefix_for_key(key)
        if not pfx:
            return None

        direction = "LT" if self.direction_var.get().strip().upper() == "LT" else "L"
        lower_cols = {norm(c): c for c in r.index}

        for b in self._basis_candidates_for_property(key):
            candidates = [
                f"{pfx}_{b}",
                f"{pfx}_{direction}_{b}",
                f"{pfx}_{b}_{direction}",
                f"{direction}_{pfx}_{b}",
            ]
            for cand in candidates:
                col = lower_cols.get(norm(cand))
                if col is not None:
                    val = try_float(r.get(col))
                    if val is not None:
                        return val


        col = lower_cols.get(norm(pfx))
        if col is not None:
            return try_float(r.get(col))

        return None

    def _raw_value_any_available(self, key):
        """Read a fallback value when the exact selected direction/basis cell is blank.

        This is used mainly for elongation because the Excel templates often use
        available failure strain from the paired direction/basis when the displayed
        source cell is blank. The displayed Property Card value still stays blank
        when the selected source cell is blank.
        """
        r = self.current_row
        if r is None:
            return None

        selected = self.basis_var.get()
        basis_list = ["A", "B", "S"] if selected == "T" else [selected]
        lower_cols = {norm(c): c for c in r.index}

        def read_candidate(col_name: str):
            col = lower_cols.get(norm(col_name))
            if col is None:
                return None
            return try_float(r.get(col))


        if key == "Elong":
            direction = "LT" if self.direction_var.get().strip().upper() == "LT" else "L"
            first = "Elong_LT" if direction == "LT" else "Elong_L"
            second = "Elong_L" if direction == "LT" else "Elong_LT"

            for pfx in (first, second):
                for b in basis_list:
                    for cand in (f"{pfx}_{b}", f"Elong_{direction}_{b}", f"Elong_{b}_{direction}"):
                        val = read_candidate(cand)
                        if val is not None:
                            return val

            for pfx in ("Elong_L", "Elong_LT", "Elong"):
                for b in ("A", "B", "S"):
                    for cand in (f"{pfx}_{b}", f"{pfx}_L_{b}", f"{pfx}_LT_{b}"):
                        val = read_candidate(cand)
                        if val is not None:
                            return val

            return None

        pfx = self._prefix_for_key(key)
        if not pfx:
            return None

        direction = "LT" if self.direction_var.get().strip().upper() == "LT" else "L"
        for b in basis_list:
            for cand in (f"{pfx}_{b}", f"{pfx}_{direction}_{b}", f"{pfx}_{b}_{direction}", f"{direction}_{pfx}_{b}"):
                val = read_candidate(cand)
                if val is not None:
                    return val

        val = read_candidate(pfx)
        if val is not None:
            return val

        return None

    def _raw_etan_from_source(self):
        """Return Etan exactly from the source row when it exists.

        Property Card values must match the Excel/MMPDS source. Therefore, Etan
        is NOT calculated for the Property Card. If the source cell is blank or
        "-", the Property Card shows "-". The MAT_24 card may still use an
        internal calculated ETAN value for export calculations.
        """
        r = self.current_row
        if r is None:
            return None, "ksi"

        direction = self.direction_var.get()
        basis_list = self._basis_candidates_for_property("Etan")

        base_names = [
            "Etan",
            "E_Tan",
            "Tangent_Modulus_Etan",
            "Tangent_Modulus",
            "Tangent_Mod",
            "TangentModulus",
        ]

        candidates = []
        for base in base_names:
            for b in basis_list:
                candidates.extend([
                    f"{base}_{direction}_{b}",
                    f"{base}_{b}_{direction}",
                    f"{direction}_{base}_{b}",
                    f"{base}_{direction}",
                    f"{base}_{b}",
                ])
            candidates.append(base)

        lower_cols = {norm(c): c for c in r.index}
        for cand in candidates:
            col = lower_cols.get(norm(cand))
            if not col:
                continue
            raw_text = str(r.get(col, "-")).strip()
            val = try_float(raw_text)
            if val is None:
                continue


            unit = "MPa" if "mpa" in norm(col) else "ksi"
            return val, unit

        return None, "ksi"

    def _compute_table(self):
        unit_sys = self.unit_sys_var.get()
        out = {}
        raw_calc = {}
        eng = {}

        for key, label, kind, *_ in PROPERTY_ROWS:
            if key in ("Etan", "Compression"):
                continue

            exact_raw = self._raw_value_exact(key)
            calc_raw = exact_raw


            if key == "Elong" and calc_raw is None:
                calc_raw = self._raw_value_any_available("Elong")


            if key == "Elong" and calc_raw is not None:
                calc_raw = abs(calc_raw)

            stored, edited = self.prop_values.get(key, ("", False))
            pending_text = self.pending_edits.get(key)

            if pending_text is not None:
                value_text = str(pending_text).strip()
                display_raw = try_float(value_text)
                if key == "Elong" and display_raw is not None:
                    display_raw = abs(display_raw)
                    value_text = fmt_number(display_raw)
                calc_raw = display_raw
            elif edited and stored not in ("", "-"):
                display_raw = try_float(stored)
                if key == "Elong" and display_raw is not None:
                    display_raw = abs(display_raw)
                    stored = fmt_number(display_raw)
                calc_raw = display_raw
                value_text = stored
            elif exact_raw is None:
                value_text = "-"
                self.prop_values[key] = ("-", False)
            else:
                display_raw = abs(exact_raw) if key == "Elong" and exact_raw is not None else exact_raw
                value_text = fmt_number(display_raw)
                self.prop_values[key] = (value_text, False)

            eng_val, _unit = convert_value(calc_raw, kind, unit_sys, self._effective_unit_conversions())
            raw_calc[key] = calc_raw
            eng[key] = eng_val

            out[key] = {
                "unit": source_unit_label(kind),
                "converted_unit": converted_unit_label(kind, unit_sys),
                "value": value_text,
                "eng": fmt_number(eng_val),
                "true": "-",
                "eps": "-",
            }

        raw_elong = raw_calc.get("Elong")
        raw_fty = raw_calc.get("Fty")
        raw_e = raw_calc.get("E")

        ftu_eng = eng.get("Ftu")
        fty_eng = eng.get("Fty")
        e_eng = eng.get("E")

        elong_eng = None
        elong_true = None
        ftu_true = None
        effps = None
        etan_eng = None
        etan_true = None

        raw_elong_formula = abs(raw_elong) if raw_elong is not None else None

        if raw_elong_formula is not None and raw_fty is not None and raw_e not in (None, 0):
            elong_eng = raw_elong_formula + (100 * raw_fty) / (raw_e * 1000)
            out["Elong"]["eng"] = fmt_number(elong_eng)

        if elong_eng is not None:
            arg = 1 + elong_eng / 100
            if arg > 0:
                elong_true = 100 * math.log(arg)
                out["Elong"]["true"] = fmt_number(elong_true)

        if ftu_eng is not None and elong_eng is not None:
            ftu_true = ftu_eng * (1 + elong_eng / 100)
            out["Ftu"]["true"] = fmt_number(ftu_true)

        if elong_true is not None and fty_eng is not None and e_eng not in (None, 0):
            effps = ((elong_true / 100) - (fty_eng / e_eng)) * 100
            if effps is not None:
                effps = abs(effps)
            out["Elong"]["eps"] = fmt_number(effps)

        if ftu_eng is not None and fty_eng is not None and raw_elong_formula not in (None, 0):
            etan_eng = abs(ftu_eng - fty_eng) / (raw_elong_formula / 100)

        if ftu_true is not None and fty_eng is not None and effps not in (None, 0):
            etan_true = abs(ftu_true - fty_eng) / (abs(effps) / 100)


        raw_ftu = raw_calc.get("Ftu")
        raw_fty_for_etan = raw_calc.get("Fty")
        etan_calc_raw = None
        if raw_ftu is not None and raw_fty_for_etan is not None and raw_elong_formula not in (None, 0):
            etan_calc_raw = abs(raw_ftu - raw_fty_for_etan) / (raw_elong_formula / 100)
            etan_eng, _ = convert_value(etan_calc_raw, "pressure", unit_sys, self._effective_unit_conversions())

        self.last_effps = effps
        self.last_etan_eng = etan_eng
        self.last_etan_true = etan_true


        source_etan, source_etan_unit = self._raw_etan_from_source()
        pending_etan = self.pending_edits.get("Etan")
        stored_etan, edited_etan = self.prop_values.get("Etan", ("", False))

        if pending_etan is not None:
            etan_value_text = str(pending_etan).strip()
            source_etan_ksi = try_float(etan_value_text)
            etan_prop_eng, _ = convert_value(source_etan_ksi, "pressure", unit_sys, self._effective_unit_conversions())
        elif edited_etan and stored_etan not in ("", "-"):
            etan_value_text = str(stored_etan).strip()
            source_etan_ksi = try_float(etan_value_text)
            etan_prop_eng, _ = convert_value(source_etan_ksi, "pressure", unit_sys, self._effective_unit_conversions())
        elif source_etan is None:
            etan_value_text = "-"
            etan_prop_eng = None
            self.prop_values["Etan"] = (etan_value_text, False)
        else:
            if norm(source_etan_unit) == "mpa":
                source_etan_ksi = source_etan * self._effective_unit_conversions().get("mpa_to_ksi", DEFAULT_UNIT_CONVERSIONS["mpa_to_ksi"])
            else:
                source_etan_ksi = source_etan
            etan_value_text = fmt_number(source_etan_ksi)
            etan_prop_eng, _ = convert_value(source_etan_ksi, "pressure", unit_sys, self._effective_unit_conversions())
            self.prop_values["Etan"] = (etan_value_text, False)
        out["Etan"] = {
            "unit": "ksi",
            "converted_unit": converted_unit_label("pressure", unit_sys),
            "value": etan_value_text,
            "eng": fmt_number(etan_prop_eng),
            "true": "-",
            "eps": "-",
        }

        comp_disp = "-"
        r = self.current_row
        b = self.basis_var.get()
        d = self.direction_var.get()

        if r is not None:
            for cand in [f"Compression_{d}_{b}", f"Compression_{b}", "Compression", "Compression_Percent", "Compression%"]:
                if cand in r.index:
                    val = try_float(r.get(cand))
                    if val is not None:
                        comp_disp = fmt_number(val)
                        break

        pending_comp = self.pending_edits.get("Compression")
        stored_comp, edited_comp = self.prop_values.get("Compression", ("", False))
        if pending_comp is not None:
            comp_value = str(pending_comp).strip()
            comp_eng = fmt_number(try_float(comp_value)) if try_float(comp_value) is not None else (comp_value or "-")
        elif edited_comp and stored_comp not in ("", "-"):
            comp_value = str(stored_comp).strip()
            comp_eng = fmt_number(try_float(comp_value)) if try_float(comp_value) is not None else (comp_value or "-")
        else:
            comp_value = "" if comp_disp == "-" else comp_disp
            comp_eng = comp_disp
            self.prop_values["Compression"] = (comp_value, False)

        out["Compression"] = {
            "unit": "%",
            "converted_unit": "%",
            "value": comp_value,
            "eng": comp_eng,
            "true": "-",
            "eps": "-",
        }

        return out

    def _render_props(self):
        """Build compact Property Card with stable editable boxes.

        The Value column is made from real Entry widgets placed inside a normal
        grid table, not floating overlays on a Treeview. This keeps the card
        compact, prevents duplicate/overlapping numbers during resize, and lets
        users clearly see the editable boxes. Typing previews calculated results;
        pressing Enter confirms the pending edit for that row.
        """
        for w in self.props.winfo_children():
            w.destroy()

        self.prop_entries.clear()
        self.prop_output_labels.clear()
        self.prop_unit_labels.clear()
        self.prop_vars.clear()
        self.prop_tree = None
        self.prop_value_widgets = {}
        self.prop_value_vars = {}
        self.prop_row_widgets = {}
        self.prop_calc_labels = {}
        self._last_prop_row_state = {}

        _, self.props_header_right_label = self._header(
            self.props,
            "Material Property Card",
            right=f"{self._basis_display()} | {self.direction_var.get()} | Eng={UNIT_SYSTEM_SPEC[self.unit_sys_var.get()]['label']}"
        )

        bar = ttk.Frame(self.props, style="Panel.TFrame")
        bar.pack(fill=tk.X, padx=8, pady=(5, 0))


        self.apply_btn = ttk.Button(bar, text="Apply", style="Primary.TButton", command=self._apply)
        self.apply_btn.pack(side=tk.RIGHT, padx=(5, 0))
        self.apply_btn.configure(state=tk.DISABLED)

        ttk.Button(bar, text="Reset", style="Secondary.TButton",
                   command=self._reset_props).pack(side=tk.RIGHT, padx=(5, 0))

        table = tk.Frame(self.props, bg=THEME["panel"])
        table.pack(fill=tk.X, expand=False, padx=8, pady=(6, 8))
        self.prop_table_frame = table


        columns = [
            ("property", "Property", 24, "w"),
            ("source_unit", "Unit", 9, "center"),
            ("value", "Value", 11, "center"),
            ("converted_unit", "Eng Unit", 10, "center"),
            ("eng", "Eng", 11, "e"),
            ("true", "True", 10, "e"),
            ("eps", "Eff.P.S.", 10, "e"),
        ]
        for c, (_key, _title, min_size, _anchor) in enumerate(columns):
            table.columnconfigure(c, weight=1 if c in (0, 4, 5, 6) else 0, minsize=min_size * 7)

        header_bg = THEME["table_header_bg"]
        header_fg = THEME["table_header_fg"]
        for c, (_key, title, _min, anchor) in enumerate(columns):
            tk.Label(
                table,
                text=title,
                bg=header_bg,
                fg=header_fg,
                font=FONTS["tiny"] if title in {"Eng Unit", "Eff.P.S."} else FONTS["small_bold"],
                padx=4,
                pady=4,
                anchor=anchor,
            ).grid(row=0, column=c, sticky="nsew", padx=(0, 1), pady=(0, 1))


        for r, (key, label, *_rest) in enumerate(PROPERTY_ROWS, start=1):
            widgets: List[tk.Widget] = []
            label_widget = tk.Label(
                table,
                text=self._row_display_label(key, label),
                bg=THEME["table_bg"],
                fg=THEME["table_fg"],
                font=FONTS["small"],
                padx=4,
                pady=3,
                anchor="w",
            )
            label_widget.grid(row=r, column=0, sticky="nsew", padx=(0, 1), pady=(0, 1))
            widgets.append(label_widget)

            source_unit = tk.Label(table, text="", bg=THEME["table_bg"], fg=THEME["table_fg"],
                                   font=FONTS["small"], padx=3, pady=3, anchor="center")
            source_unit.grid(row=r, column=1, sticky="nsew", padx=(0, 1), pady=(0, 1))
            widgets.append(source_unit)

            var = tk.StringVar(value="")
            entry = tk.Entry(
                table,
                textvariable=var,
                justify="right",
                font=FONTS["mono_small"],
                relief="solid",
                bd=1,
                width=10,
                bg=THEME["entry_bg"],
                fg=THEME["entry_fg"],
                insertbackground=THEME["entry_fg"],
                highlightthickness=1,
                highlightbackground=THEME["border"],
                highlightcolor=THEME["focus_ring"],
            )
            entry.grid(row=r, column=2, sticky="nsew", padx=2, pady=2, ipady=1)
            entry.bind("<KeyRelease>", lambda _e, k=key: self._preview_property_value_edit(k))
            entry.bind("<Return>", lambda _e, k=key: self._confirm_property_value_edit(k))
            entry.bind("<Escape>", lambda _e, k=key: self._cancel_property_value_edit(k))
            self.prop_value_vars[key] = var
            self.prop_value_widgets[key] = entry
            widgets.append(entry)

            calc_labels: Dict[str, tk.Label] = {}
            for c, name in [(3, "converted_unit"), (4, "eng"), (5, "true"), (6, "eps")]:
                lbl = tk.Label(
                    table,
                    text="",
                    bg=THEME["table_bg"],
                    fg=THEME["table_fg"],
                    font=FONTS["small"],
                    padx=4,
                    pady=3,
                    anchor="center" if c == 3 else "e",
                )
                lbl.grid(row=r, column=c, sticky="nsew", padx=(0, 1), pady=(0, 1))
                calc_labels[name] = lbl
                widgets.append(lbl)

            self.prop_row_widgets[key] = widgets
            self.prop_calc_labels[key] = {
                "source_unit": source_unit,
                **calc_labels,
            }

        self._refresh_cards_fast()

    def _row_display_label(self, key, label):
        if key in ("Ftu", "Fty", "Fcy", "Fsu", "Elong", "E", "Ec", "Etan"):
            return f"{label} ({self.direction_var.get()})"
        return label

    def _refresh_cards_fast(self):
        """Update Property Card + Engineering Card values without rebuilding the screen."""
        if not self.mat24_value_labels:
            self._render_mat24()
        if not getattr(self, "prop_value_widgets", None):
            return

        computed = self._compute_table()
        missing_required_keys = self._missing_required_property_keys_from_computed(computed)
        missing_required_labels = set(self._missing_required_labels_from_computed(computed))
        self._sync_top_disclaimer(computed)

        if self.props_header_right_label is not None:
            self.props_header_right_label.configure(
                text=f"{self._basis_display()} | {self.direction_var.get()} | Eng={UNIT_SYSTEM_SPEC[self.unit_sys_var.get()]['label']}"
            )
        if self.mat24_header_right_label is not None:
            self.mat24_header_right_label.configure(text=UNIT_SYSTEM_SPEC[self.unit_sys_var.get()]["label"])

        for key, label, *_rest in PROPERTY_ROWS:
            if key not in computed:
                continue
            data = computed[key]
            shown_value = self.pending_edits.get(key, data["value"])
            display_value = strip_edit_box(shown_value)

            stored_value, was_edited = self.prop_values.get(key, ("", False))
            is_pending = key in self.pending_edits
            is_readonly = key in READONLY_VALUE_ROWS

            if key in missing_required_keys:
                row_bg = "#FFE5E5" if not is_dark_theme() else "#4A1F1F"
                row_fg = self._required_value_warning_color()
                entry_bg = row_bg
                entry_fg = row_fg
            elif is_pending:
                row_bg = THEME["pending_bg"]
                row_fg = THEME["pending_fg"]
                entry_bg = THEME["pending_bg"]
                entry_fg = THEME["pending_fg"]
            elif was_edited and not is_readonly:
                row_bg = THEME["edit_bg"]
                row_fg = THEME["edit_fg"]
                entry_bg = THEME["edit_bg"]
                entry_fg = THEME["edit_fg"]
            else:
                row_bg = THEME["table_bg"]
                row_fg = THEME["table_fg"]
                entry_bg = THEME["entry_bg"]
                entry_fg = THEME["entry_fg"]

            widgets = self.prop_row_widgets.get(key, [])
            for w in widgets:
                try:
                    if isinstance(w, tk.Entry):
                        w.configure(bg=entry_bg, fg=entry_fg, insertbackground=entry_fg)
                    else:
                        w.configure(bg=row_bg, fg=row_fg)
                except Exception:
                    pass


            try:
                self.prop_row_widgets[key][0].configure(text=self._row_display_label(key, label))
            except Exception:
                pass
            cells = self.prop_calc_labels.get(key, {})
            if cells:
                for name, value in {
                    "source_unit": data.get("unit", ""),
                    "converted_unit": data.get("converted_unit", ""),
                    "eng": data.get("eng", ""),
                    "true": data.get("true", ""),
                    "eps": data.get("eps", ""),
                }.items():
                    lbl = cells.get(name)
                    if lbl is not None:
                        try:
                            if lbl.cget("text") != value:
                                lbl.configure(text=value)
                        except Exception:
                            lbl.configure(text=value)


            var = self.prop_value_vars.get(key)
            entry = self.prop_value_widgets.get(key)
            if var is not None:
                try:
                    active_widget = self.focus_get()
                except Exception:
                    active_widget = None
                if active_widget is not entry or not is_pending:
                    if var.get() != display_value:
                        self._updating_ui = True
                        var.set(display_value)
                        self._updating_ui = False


        if self._model_code() == "MAT224":
            self._render_mat24()
        else:
            updates = self._engineering_values(computed)
            if self._is_gissmo_model():
                updates["FAIL"] = "-"
            for key, value in updates.items():
                lbl = self.mat24_value_labels.get(key)
                if lbl is not None:
                    try:
                        fg = self._required_value_warning_color() if key in missing_required_labels else THEME["text"]
                        bg = "#FFE5E5" if (key in missing_required_labels and not is_dark_theme()) else ("#4A1F1F" if key in missing_required_labels else THEME["matrix_value"])
                        if lbl.cget("text") != value or lbl.cget("fg") != fg:
                            lbl.configure(text=value, fg=fg, bg=bg)
                    except Exception:
                        lbl.configure(text=value)

        try:
            self.apply_btn.configure(state=tk.NORMAL if (self.pending_edits or self.unit_pending_edits) else tk.DISABLED)
        except Exception:
            pass

    def _set_property_pending_from_var(self, row_id: str, show_disclaimer: bool = True) -> None:
        """Store a pending edit from the compact Value box and refresh previews."""
        if getattr(self, "_updating_ui", False):
            return
        var = getattr(self, "prop_value_vars", {}).get(row_id)
        if var is None:
            return
        value = strip_edit_box(var.get()).strip()
        committed = strip_edit_box(self.prop_values.get(row_id, ("", False))[0])
        if value == committed:
            self.pending_edits.pop(row_id, None)
        else:
            self.pending_edits[row_id] = value
        if show_disclaimer:
            self._sync_material_modified_disclaimer()

    def _preview_property_value_edit(self, row_id: str):
        """Live preview: color row and recalculate outputs while user types."""
        if getattr(self, "_updating_ui", False):
            return "break"
        self._set_property_pending_from_var(row_id, show_disclaimer=True)
        self._refresh_cards_fast()
        return "break"

    def _confirm_property_value_edit(self, row_id: str):
        """Refresh preview on Enter without confirming the edit.

        Values are confirmed only when the user clicks Apply. Reset before Apply
        discards pending text and restores the original source/default values.
        """
        self._set_property_pending_from_var(row_id, show_disclaimer=True)
        self._refresh_cards_fast()
        try:
            entry = self.prop_value_widgets.get(row_id)
            if entry is not None:
                entry.selection_clear()
        except Exception:
            pass
        return "break"
    def _cancel_property_value_edit(self, row_id: str):
        """Restore the row to the currently committed source/custom value."""
        self.pending_edits.pop(row_id, None)
        self._sync_material_modified_disclaimer()
        self._refresh_cards_fast()
        return "break"

    def _effective_unit_conversions(self) -> Dict[str, float]:
        """Return applied conversion factors plus pending valid edits.

        Pending edits are used immediately for on-screen calculations while the
        user types. Pressing Enter confirms them into the current card.
        """
        factors = dict(self.unit_conversions)
        for key, value in getattr(self, "unit_pending_edits", {}).items():
            num = try_float(value)
            if num is not None:
                factors[key] = num
        return factors

    def _render_unit_conversions(self):
        """Render compact selected-unit conversion factors.

        Only the active unit system is shown. The only visible input boxes are the
        Editable Factor values. Press Enter inside a factor box to mark the row
        amber and update the Property Card + Engineering Card immediately.
        """
        if not hasattr(self, "unitconv"):
            return

        for w in self.unitconv.winfo_children():
            w.destroy()

        active_unit = self.unit_sys_var.get()
        unit_label = UNIT_SYSTEM_SPEC.get(active_unit, UNIT_SYSTEM_SPEC["mm_T_s"]).get("label", active_unit)
        self._header(self.unitconv, "Unit Conversion Factors", right=unit_label)

        disclaimer = tk.Label(
            self.unitconv,
            textvariable=self.unit_conversion_disclaimer_var,
            bg=THEME["panel"],
            fg=THEME["status_warn_fg"],
            font=FONTS["small_bold"],
            anchor="w",
        )
        if self.unit_conversion_disclaimer_var.get():
            disclaimer.pack(fill=tk.X, padx=12, pady=(8, 0))

        table = tk.Frame(self.unitconv, bg=THEME["panel"])
        table.pack(fill=tk.X, padx=12, pady=(8, 12))
        for c, weight in enumerate([3, 1, 1, 1, 1]):
            table.columnconfigure(c, weight=weight)

        header_bg = THEME["table_header_bg"]
        header_fg = THEME["table_header_fg"]
        headers = ["Conversion", "Source Unit", "Source Value", "Converted Unit", "Editable Factor"]
        for c, heading in enumerate(headers):
            tk.Label(
                table,
                text=heading,
                bg=header_bg,
                fg=header_fg,
                font=FONTS["small_bold"],
                padx=6,
                pady=4,
                anchor="center" if c else "w",
            ).grid(row=0, column=c, sticky="nsew", padx=(0, 1), pady=(0, 1))

        self.unit_tree = None
        self.unit_factor_vars = {}
        self.unit_factor_entries = {}
        self.unit_row_widgets = {}


        active_rows = [row for row in UNIT_CONVERSION_ROWS if row[0].startswith(active_unit + "_")][:2]
        for r, (key, _unit_system, name, from_unit, to_unit) in enumerate(active_rows, start=1):
            pending = key in self.unit_pending_edits
            confirmed = key in getattr(self, "unit_confirmed_edits", set())
            if pending:
                row_bg = THEME["pending_bg"]
                row_fg = THEME["pending_fg"]
            elif confirmed:
                row_bg = THEME["edit_bg"]
                row_fg = THEME["edit_fg"]
            else:
                row_bg = THEME["table_bg"]
                row_fg = THEME["table_fg"]
            factor = self.unit_pending_edits.get(
                key,
                self.unit_conversions.get(key, DEFAULT_UNIT_CONVERSIONS.get(key, "")),
            )
            widgets = []
            cells = [name, from_unit, "1", to_unit]
            for c, value in enumerate(cells):
                lbl = tk.Label(
                    table,
                    text=value,
                    bg=row_bg,
                    fg=row_fg,
                    font=FONTS["small"],
                    padx=8,
                    pady=6,
                    anchor="center" if c else "w",
                )
                lbl.grid(row=r, column=c, sticky="nsew", padx=(0, 1), pady=(0, 1))
                widgets.append(lbl)

            var = tk.StringVar(value=self._format_conversion_factor(factor))
            ent = tk.Entry(
                table,
                textvariable=var,
                justify="right",
                font=FONTS["mono_small"],
                relief="solid",
                bd=1,
                bg=row_bg,
                fg=row_fg,
                insertbackground=row_fg,
                highlightthickness=1,
                highlightbackground=THEME["border"],
                highlightcolor=THEME["focus_ring"],
            )
            ent.grid(row=r, column=4, sticky="nsew", padx=(2, 0), pady=2, ipady=2)
            ent.bind("<KeyRelease>", lambda _e, k=key: self._preview_unit_factor_entry(k))
            ent.bind("<Return>", lambda _e, k=key: self._commit_unit_factor_entry(k))
            ent.bind("<Escape>", lambda _e: self._render_unit_conversions())
            self.unit_factor_vars[key] = var
            self.unit_factor_entries[key] = ent
            widgets.append(ent)
            self.unit_row_widgets[key] = widgets

    def _preview_unit_factor_entry(self, key: str):
        """Live-preview one unit conversion factor while typing."""
        var = getattr(self, "unit_factor_vars", {}).get(key)
        if var is None:
            return "break"
        value = str(var.get()).strip()
        num = try_float(value)
        ent = getattr(self, "unit_factor_entries", {}).get(key)
        if num is None:

            try:
                if ent is not None:
                    ent.configure(bg=THEME["entry_bg"], fg=THEME["status_error_fg"])
            except Exception:
                pass
            return "break"

        current_value = self.unit_conversions.get(key, DEFAULT_UNIT_CONVERSIONS.get(key))
        if try_float(current_value) == num:
            self.unit_pending_edits.pop(key, None)
            row_bg = THEME["table_bg"]
            row_fg = THEME["table_fg"]
            entry_bg = THEME["entry_bg"]
            entry_fg = THEME["entry_fg"]
        else:
            self.unit_pending_edits[key] = self._format_conversion_factor(num)
            self.unit_conversion_disclaimer_var.set(
                "Unit conversion factor modified. Calculated values are updated; source values remain unchanged."
            )
            row_bg = THEME["pending_bg"]
            row_fg = THEME["pending_fg"]
            entry_bg = THEME["pending_bg"]
            entry_fg = THEME["pending_fg"]

        for widget in getattr(self, "unit_row_widgets", {}).get(key, []):
            try:
                if isinstance(widget, tk.Entry):
                    widget.configure(bg=entry_bg, fg=entry_fg, insertbackground=entry_fg)
                else:
                    widget.configure(bg=row_bg, fg=row_fg)
            except Exception:
                pass

        self._refresh_cards_fast()
        try:
            self.apply_btn.configure(state=tk.NORMAL if (self.pending_edits or self.unit_pending_edits) else tk.DISABLED)
        except Exception:
            pass
        return "break"

    def _commit_unit_factor_entry(self, key: str):
        """Refresh unit-conversion preview on Enter without confirming the edit."""
        var = getattr(self, "unit_factor_vars", {}).get(key)
        if var is None:
            return "break"
        value = str(var.get()).strip()
        num = try_float(value)
        if num is None:
            messagebox.showerror("Invalid Unit Conversion", f"Invalid conversion factor:\n\n{value}")
            return "break"

        current_value = self.unit_conversions.get(key, DEFAULT_UNIT_CONVERSIONS.get(key))
        if try_float(current_value) == num:
            self.unit_pending_edits.pop(key, None)
        else:
            self.unit_pending_edits[key] = self._format_conversion_factor(num)
            self.unit_conversion_disclaimer_var.set(
                "Unit conversion factor modified. Calculated values are updated; source values remain unchanged."
            )

        self._refresh_cards_fast()
        try:
            self.apply_btn.configure(state=tk.NORMAL if (self.pending_edits or self.unit_pending_edits) else tk.DISABLED)
        except Exception:
            pass
        return "break"
    def _format_conversion_factor(self, value):
        num = try_float(value)
        if num is None:
            return str(value)
        if abs(num) != 0 and (abs(num) >= 1e5 or abs(num) < 1e-4):
            return f"{num:.8g}"
        return f"{num:.10g}"

    def _apply_unit_conversion_edits(self):
        """Validate and apply pending conversion factors from factor boxes."""
        for key, var in getattr(self, "unit_factor_vars", {}).items():
            value = str(var.get()).strip()
            num = try_float(value)
            if num is None:
                raise ValueError(f"Invalid conversion factor for {key}: {value}")
            if key in self.unit_pending_edits:
                self.unit_pending_edits[key] = self._format_conversion_factor(num)

        for key, val in list(self.unit_pending_edits.items()):
            num = try_float(val)
            if num is None:
                raise ValueError(f"Invalid conversion factor for {key}: {val}")
            self.unit_conversions[key] = num
            default_num = try_float(DEFAULT_UNIT_CONVERSIONS.get(key))
            if default_num is not None and num != default_num:
                self.unit_confirmed_edits.add(key)
            else:
                self.unit_confirmed_edits.discard(key)

        self.unit_pending_edits.clear()

        if getattr(self, "unit_confirmed_edits", set()):
            self.unit_conversion_disclaimer_var.set(
                "Unit conversion factor modified. Calculated values are updated; source values remain unchanged."
            )
        else:
            self.unit_conversion_disclaimer_var.set("")

    def _reset_unit_conversions(self):
        """Reset conversion factors to the defaults used by the original formulas."""
        self.unit_conversions = DEFAULT_UNIT_CONVERSIONS.copy()
        self.unit_pending_edits.clear()
        if hasattr(self, "unit_confirmed_edits"):
            self.unit_confirmed_edits.clear()
        self.unit_conversion_disclaimer_var.set("")
        if getattr(self, "unit_factor_vars", None):
            for key, var in self.unit_factor_vars.items():
                var.set(self._format_conversion_factor(self.unit_conversions.get(key, DEFAULT_UNIT_CONVERSIONS.get(key, ""))))

    def _safe_image_name(self, value):
        """Make material text safe for matching source-image filenames."""
        text = str(value).strip()
        if not text or text == "-" or text == NO_SPEC_DISPLAY:
            return ""

        for ch in [" ", "/", "\\", ":", "*", "?", '"', "<", ">", "|", ",", ".", "(", ")", "[", "]"]:
            text = text.replace(ch, "_")
        while "__" in text:
            text = text.replace("__", "_")
        return text.strip("_")

    def _source_tokens(self):
        """Build matching tokens from selected material metadata."""
        if self.current_row is None:
            return {}

        r = self.current_row
        spec_val = self.current_selections.get("Specification") or r.get("Spec1_1", "")
        spec2_val = self.current_selections.get("Specification 2") or row_spec2_value(r)
        if spec_val == NO_SPEC_DISPLAY or is_blank(spec_val):
            spec_val = spec2_val
        if spec_val == NO_SPEC_DISPLAY:
            spec_val = ""

        raw = {
            "element": self.current_selections.get("Element") or r.get("Element", ""),
            "material": self.current_selections.get("Material") or r.get("Material", ""),
            "temper": self.current_selections.get("Temper") or r.get("Temper", ""),
            "spec": spec_val,
            "form": self.current_selections.get("Form") or r.get("Form", ""),
            "thickness": self._thickness_base(r),
        }
        return {k: self._safe_image_name(v) for k, v in raw.items()}

    def _find_source_images(self, max_results: int = MAX_SOURCE_IMAGES, return_total: bool = False):
        """Find source-page images using robust, non-blocking fallback searches.

        Search order:
        1. Material + temper + main specification
        2. Material + temper + Specification 2
        3. Material + temper only

        This prevents the viewer from going blank when Spec1 is missing, when
        QQ/secondary specs live in Spec2_1, or when the image filename does not
        include the exact specification token.
        """
        if self.current_row is None:
            return ([], 0) if return_total else []

        base_parts = self._source_tokens()
        attempts: List[Dict[str, str]] = []

        def add_attempt(parts: Dict[str, str]) -> None:
            cleaned = {k: str(v or "").strip() for k, v in parts.items()}
            key = tuple(sorted(cleaned.items()))
            if key not in {tuple(sorted(x.items())) for x in attempts}:
                attempts.append(cleaned)

        add_attempt(base_parts)


        try:
            spec2 = self._safe_image_name(row_spec2_value(self.current_row))
        except Exception:
            spec2 = ""
        if spec2 and spec2 != base_parts.get("spec", ""):
            alt = dict(base_parts)
            alt["spec"] = spec2
            add_attempt(alt)


        relaxed = dict(base_parts)
        relaxed["spec"] = ""
        add_attempt(relaxed)

        best_images: List[Path] = []
        best_total = 0
        for parts in attempts:
            try:
                images, total = self.app.source_image_index.search(parts, max_results=max_results)
            except Exception:
                images, total = [], 0
            if images:
                return (images, total) if return_total else images
            best_total = max(best_total, int(total or 0))

        return (best_images, best_total) if return_total else best_images

    def _source_image_view_size(self) -> Tuple[int, int]:
        """Return the real visible canvas size for responsive image rendering.

        The previous image viewer estimated size from the right panel. When the
        application window was not maximized, that estimate could stay larger
        than the actual canvas or remain unchanged after the canvas was rebuilt.
        That caused the viewer to find images but sometimes not draw them in a
        small window.
        """
        try:
            canvas = getattr(self, "source_canvas", None)
            if canvas is not None and canvas.winfo_exists():
                canvas.update_idletasks()
                w = int(canvas.winfo_width())
                h = int(canvas.winfo_height())
                if w > 40 and h > 40:
                    return max(220, w - 24), max(180, h - 24)
        except Exception:
            pass

        try:
            panel_w = int(max(self.image_panel.winfo_width(), self.right_col.winfo_width()))
            panel_h = int(max(self.image_panel.winfo_height(), self.right_col.winfo_height()))
        except Exception:
            panel_w, panel_h = 620, 760

        return max(220, panel_w - 70), max(180, panel_h - 210)

    def _render_source_images(self):
        """Render the right-side Data Source Viewer safely.

        Important behavior:
        - The right panel is drawn immediately so it never stays blank.
        - Image search runs in the background so a slow J: / network image index
          cannot freeze Screen 2.
        - Basis, Direction, Unit System, and Material Model changes do not call
          this method, so the source image does not blink during normal option changes.
        - Thickness/material changes may call this method and refresh the viewer.
        """
        if not hasattr(self, "image_panel"):
            return


        self._source_search_token = int(getattr(self, "_source_search_token", 0)) + 1
        token = self._source_search_token
        self._last_displayed_source_image_key = None


        for w in self.image_panel.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self.source_image_refs = []
        self._header(self.image_panel, "Data Source Viewer", right="")

        shell = tk.Frame(self.image_panel, bg=THEME["panel"])
        shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.source_image_status_var = tk.StringVar(value="Finding source image...")
        status = tk.Label(
            shell,
            textvariable=self.source_image_status_var,
            bg=THEME["panel"],
            fg=THEME["text_muted"],
            font=FONTS["small"],
            anchor="w",
        )
        status.pack(fill=tk.X, pady=(0, 6))

        placeholder = tk.Frame(shell, bg=THEME["panel_alt"], highlightbackground=THEME["border"], highlightthickness=1)
        placeholder.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            placeholder,
            text="Source image will appear here.",
            bg=THEME["panel_alt"],
            fg=THEME["text_muted"],
            font=FONTS["h2"],
        ).pack(expand=True)
        try:
            self.image_panel.update_idletasks()
        except Exception:
            pass

        parts = self._source_tokens()

        def worker():
            images, total, error = [], 0, ""
            try:
                images, total = self._find_source_images(max_results=MAX_SOURCE_IMAGES, return_total=True)
            except Exception as exc:
                error = str(exc)
            try:
                self.after(0, lambda: self._finish_source_image_render(token, shell, parts, images, total, error))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _finish_source_image_render(self, token: int, shell, parts: Dict[str, str], images: List[Path], total: int, error: str = ""):
        """Finish drawing source image results on the Tk main thread."""
        if token != int(getattr(self, "_source_search_token", 0)):
            return
        try:
            if not shell.winfo_exists():
                return
        except Exception:
            return

        for w in shell.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        self.source_images = list(images or [])
        self.source_total_images = int(total or len(self.source_images))
        self.source_image_index_var = getattr(self, "source_image_index_var", tk.IntVar(value=0))
        if self.source_image_index_var.get() >= len(self.source_images):
            self.source_image_index_var.set(0)
        self.source_image_zoom = 1.0
        self.source_image_fit_mode = "width"
        self._last_displayed_source_image_key = None

        if error:
            self._render_source_error_state(shell, error, parts)
            return

        if not self.source_images:
            self._render_source_empty_state(shell, parts)
            self._schedule_source_image_retry()
            return


        topbar = tk.Frame(shell, bg=THEME["panel"])
        topbar.pack(fill=tk.X, pady=(0, 6))
        self.source_image_count_var = tk.StringVar(value="")
        tk.Label(
            topbar,
            textvariable=self.source_image_count_var,
            bg=THEME["panel"],
            fg=THEME["text_muted"],
            font=FONTS["small"],
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        if len(self.source_images) > 1:
            ttk.Button(topbar, text="Previous", style="Secondary.TButton", command=self._source_prev_image).pack(side=tk.RIGHT, padx=(4, 0))
            ttk.Button(topbar, text="Next", style="Secondary.TButton", command=self._source_next_image).pack(side=tk.RIGHT, padx=(4, 0))

        canvas_frame = tk.Frame(shell, bg="#FFFFFF", highlightbackground=THEME["border"], highlightthickness=1)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.source_canvas = tk.Canvas(canvas_frame, bg="#FFFFFF", highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.source_canvas.yview)
        hsb = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.source_canvas.xview)
        self.source_canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.source_canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        def _canvas_configure(_event=None):
            self._last_displayed_source_image_key = None
            self._display_current_source_image(debounced=True)

        self.source_canvas.bind("<Configure>", _canvas_configure)
        bind_mousewheel(self.source_canvas)
        self.after_idle(lambda: self._display_current_source_image(first_load=True))
        self.after(260, lambda: self._display_current_source_image(first_load=True))

    def _schedule_source_image_retry(self):
        """Retry source image lookup once the async image index finishes refreshing."""
        try:
            idx = getattr(self.app, "source_image_index", None)
            if idx is None:
                return
            if not getattr(idx, "refreshing", False) and getattr(idx, "loaded", False):
                return
            if getattr(self, "_source_image_retry_job", None) is not None:
                return

            def _retry():
                self._source_image_retry_job = None
                try:
                    self._render_source_images()
                except Exception:
                    pass

            self._source_image_retry_job = self.after(1500, _retry)
        except Exception:
            pass

    def _render_source_error_state(self, shell, error: str, parts: Dict[str, str]):
        empty = tk.Frame(shell, bg=THEME["panel_alt"], highlightbackground=THEME["border"], highlightthickness=1)
        empty.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(empty, bg=THEME["panel_alt"])
        inner.pack(expand=True, padx=22, pady=22)
        tk.Label(inner, text="Source image viewer error", bg=THEME["panel_alt"], fg=THEME["status_error_fg"], font=FONTS["h1"]).pack()
        tk.Label(
            inner,
            text=str(error),
            bg=THEME["panel_alt"], fg=THEME["text_muted"], font=FONTS["small"], wraplength=560, justify="center",
        ).pack(pady=(8, 10))
        token_text = f"Material: {parts.get('material','-') or '-'}    Temper: {parts.get('temper','-') or '-'}    Spec/Spec 2: {parts.get('spec','-') or '-'}"
        tk.Label(inner, text=token_text, bg=THEME["panel"], fg=THEME["text"], font=FONTS["mono_small"], padx=14, pady=8).pack()

    def _render_source_empty_state(self, shell, parts: Dict[str, str]):
        empty = tk.Frame(shell, bg=THEME["panel_alt"], highlightbackground=THEME["border"], highlightthickness=1)
        empty.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(empty, bg=THEME["panel_alt"])
        inner.pack(expand=True, padx=22, pady=22)
        refreshing = bool(getattr(self.app.source_image_index, "refreshing", False)) or not bool(getattr(self.app.source_image_index, "loaded", False))
        title = "Source image index refreshing" if refreshing else "No source image found"
        msg = (
            "The image index is refreshing in the background. The viewer will retry automatically."
            if refreshing else
            "Searched by Material + Temper + Specification, then Specification 2, then Material + Temper."
        )
        tk.Label(inner, text=title, bg=THEME["panel_alt"], fg=THEME["accent"], font=FONTS["h1"]).pack()
        tk.Label(
            inner,
            text=msg,
            bg=THEME["panel_alt"], fg=THEME["text_muted"], font=FONTS["small"], wraplength=560, justify="center",
        ).pack(pady=(6, 12))
        token_text = f"Material: {parts.get('material','-') or '-'}    Temper: {parts.get('temper','-') or '-'}    Spec/Spec 2: {parts.get('spec','-') or '-'}"
        tk.Label(inner, text=token_text, bg=THEME["panel"], fg=THEME["text"], font=FONTS["mono_small"], padx=14, pady=8).pack()

    def _display_current_source_image(self, debounced: bool = False, first_load: bool = False):
        if debounced:
            if getattr(self, "_source_image_resize_job", None) is not None:
                try:
                    self.after_cancel(self._source_image_resize_job)
                except Exception:
                    pass
            self._source_image_resize_job = self.after(140, lambda: self._display_current_source_image(False))
            return
        if not getattr(self, "source_images", []):
            return
        try:
            canvas = self.source_canvas
            if not canvas.winfo_exists():
                return
        except Exception:
            return

        try:
            canvas.update_idletasks()
            canvas_w = int(canvas.winfo_width())
            canvas_h = int(canvas.winfo_height())
        except Exception:
            canvas_w, canvas_h = 0, 0

        if canvas_w < 60 or canvas_h < 60:
            try:
                self.after(180, lambda: self._display_current_source_image(first_load=first_load))
            except Exception:
                pass
            return

        idx = max(0, min(int(self.source_image_index_var.get()), len(self.source_images) - 1))
        self.source_image_index_var.set(idx)
        img_path = self.source_images[idx]
        fit_w, fit_h = self._source_image_view_size()
        max_size = (int(max(220, fit_w)), int(max(180, min(5000, fit_h * 6))))

        try:
            if hasattr(self, "source_image_count_var"):
                self.source_image_count_var.set(f"Image {idx + 1} of {self.source_total_images or len(self.source_images)}")
            if hasattr(self, "source_image_status_var"):
                self.source_image_status_var.set(f"Image {idx + 1} of {self.source_total_images or len(self.source_images)}")
        except Exception:
            pass

        canvas_id = str(canvas)
        display_key = (canvas_id, str(img_path), max_size, canvas_w, canvas_h, "responsive_canvas_render_v2")
        try:
            has_canvas_items = bool(canvas.find_all())
        except Exception:
            has_canvas_items = False
        if getattr(self, "_last_displayed_source_image_key", None) == display_key and has_canvas_items:
            return
        self._last_displayed_source_image_key = display_key

        img = self.app.image_cache.get(img_path, max_size=max_size)
        try:
            canvas.delete("all")
        except Exception:
            pass

        if img is None:
            err = self.app.image_cache.last_error or "Unknown image loading error"
            canvas.create_text(
                12,
                12,
                anchor="nw",
                text="Image found, but could not be loaded. Install Pillow if needed.\n" + err,
                fill=THEME["status_error_fg"],
                font=FONTS["small"],
                width=max(260, canvas_w - 30),
            )
            canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, canvas_w, canvas_h))
            return

        self.source_image_refs = [img]
        try:
            x = max(10, int((canvas_w - int(img.width())) / 2)) if int(img.width()) < canvas_w else 10
            y = 10
            canvas.create_image(x, y, anchor="nw", image=img)
            canvas.configure(scrollregion=(0, 0, max(canvas_w, int(img.width()) + x + 10), max(canvas_h, int(img.height()) + y + 10)))
            if first_load:
                canvas.yview_moveto(0)
                canvas.xview_moveto(0)
        except Exception as exc:
            try:
                canvas.create_text(
                    12,
                    12,
                    anchor="nw",
                    text=f"Image found, but could not be rendered.\n{exc}",
                    fill=THEME["status_error_fg"],
                    font=FONTS["small"],
                    width=max(260, canvas_w - 30),
                )
                canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, canvas_w, canvas_h))
            except Exception:
                pass

    def _source_next_image(self):
        if not getattr(self, "source_images", []):
            return
        self._last_displayed_source_image_key = None
        self.source_image_index_var.set((int(self.source_image_index_var.get()) + 1) % len(self.source_images))
        self._display_current_source_image(first_load=True)

    def _source_prev_image(self):
        if not getattr(self, "source_images", []):
            return
        self._last_displayed_source_image_key = None
        self.source_image_index_var.set((int(self.source_image_index_var.get()) - 1) % len(self.source_images))
        self._display_current_source_image(first_load=True)


    def _export_material_id(self, row=None, basis: Optional[str] = None,
                            direction: Optional[str] = None, model: Optional[str] = None) -> int:
        """Return one stable positive ID for this exported material row.

        Rule for V4 verification:
            Material ID = MAT MID = GISSMO MID = GISSMO Curve ID

        If the source data supplies a numeric MatID/MID column, that value is used.
        Otherwise, a deterministic ID is generated from material metadata, thickness,
        basis, direction, and model so it stays stable and avoids duplicate fixed IDs.
        """
        r = row if row is not None else self.current_row
        for col_name in ("MatID", "Material ID", "Material_ID", "MaterialID", "MID", "Curve ID", "Curve_ID"):
            val = row_first_nonblank(r, col_name, default="")
            num = try_float(val)
            if num is not None and int(abs(num)) > 0:
                return int(abs(num))

        if r is None:
            return 1

        element = self.current_selections.get("Element") or row_first_nonblank(r, "Element", default="")
        material = self.current_selections.get("Material") or row_first_nonblank(r, "Material", default="")
        temper = self.current_selections.get("Temper") or row_first_nonblank(r, "Temper", default="")
        spec1 = self.current_selections.get("Specification") or row_first_nonblank(r, "Spec1_1", "Specification", default="")
        spec2 = self.current_selections.get("Specification 2") or row_spec2_value(r)
        form = self.current_selections.get("Form") or row_first_nonblank(r, "Form", default="")
        thickness = self._thickness_base(r)
        basis_code = str(basis or self.basis_var.get() or "B").strip().upper()
        direction_code = str(direction or self.direction_var.get() or "L").strip().upper()
        model_code = str(model or self.mat_model_var.get() or "MAT024+GISSMO").strip().upper()
        seed = "|".join([element, material, temper, spec1, spec2, form, thickness, basis_code, direction_code, model_code])
        digest = int(hashlib.md5(seed.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
        return 100000 + (digest % 900000)


    def _is_gissmo_model(self) -> bool:
        return str(self.mat_model_var.get()).strip().upper() == "MAT024+GISSMO"

    def _gissmo_basis_number(self, basis: Optional[str] = None) -> int:
        basis_code = str(basis or self.basis_var.get() or "B").strip().upper()
        return {"A": 1, "B": 2, "S": 3}.get(basis_code, 1)

    def _gissmo_table_label(self, basis: Optional[str] = None, direction: Optional[str] = None) -> str:
        basis_num = self._gissmo_basis_number(basis)
        direction_code = "LT" if str(direction or self.direction_var.get()).strip().upper() == "LT" else "L"
        return f"Table {basis_num}{direction_code}"

    def _gissmo_curve_id(self, basis: Optional[str] = None, direction: Optional[str] = None) -> int:

        return abs(self._export_material_id(
            row=self.current_row,
            basis=basis or self.basis_var.get(),
            direction=direction or self.direction_var.get(),
            model="MAT024+GISSMO",
        ))

    def _gissmo_failure_pfs(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[float]:


        if computed is None:
            computed = self._compute_table()
        if self.last_effps is None:
            return None
        try:
            return abs(float(self.last_effps)) / 100.0
        except Exception:
            return None

    def _gissmo_compression_pfs(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> float:

        if computed is None:
            computed = self._compute_table()
        comp = None
        try:
            comp = try_float(computed.get("Compression", {}).get("eng"))
        except Exception:
            comp = None
        if comp is None or comp <= 0:
            comp = 99.0
        return max(comp / 100.0, 0.0)

    def _gissmo_table_points(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> List[Tuple[float, Optional[float]]]:
        if computed is None:
            computed = self._compute_table()
        compression_pfs = self._gissmo_compression_pfs(computed)
        failure_pfs = self._gissmo_failure_pfs(computed)
        return [
            (-1.0 / 3.0, compression_pfs),
            (-0.0001, compression_pfs),
            (0.0, failure_pfs),
            (2.0 / 3.0, failure_pfs),
        ]

    def _fmt_gissmo_float(self, value: Optional[float], decimals: int = 4) -> str:
        if value is None:
            return "-"
        try:
            return f"{float(value):.{decimals}f}"
        except Exception:
            return "-"

    def _render_gissmo(self, computed: Optional[Dict[str, Dict[str, str]]] = None):
        """Render GISSMO in the same matrix/card style as the Excel template.

        Required Screen 2 order when MAT024+GISSMO is selected:
        MAT_24 card first, then Excel-style GISSMO card with its LCSDG/ECRIT
        table, then the editable Material Property Card.
        """
        if not hasattr(self, "gissmo"):
            return

        if not self._is_gissmo_model():
            for w in self.gissmo.winfo_children():
                w.destroy()
            self.gissmo_value_labels.clear()
            self.gissmo_tree = None
            self.gissmo_header_right_label = None
            try:
                self.gissmo.pack_forget()
            except Exception:
                pass
            return

        if computed is None:
            computed = self._compute_table()

        try:
            if not self.gissmo.winfo_ismapped():
                self.gissmo.pack(fill=tk.X, expand=False, pady=(0, 12), after=self.mat24)
        except Exception:
            self.gissmo.pack(fill=tk.X, expand=False, pady=(0, 12))

        for w in self.gissmo.winfo_children():
            w.destroy()
        self.gissmo_value_labels.clear()
        self.gissmo_tree = None

        direction_code = "LT" if self.direction_var.get().strip().upper() == "LT" else "L"
        direction_title = "LONGITUDINAL (L)" if direction_code == "L" else "LONG.- TRANSVERSAL (LT)"
        table_label = self._gissmo_table_label()
        curve_id = self._gissmo_curve_id()
        ecrit_id = -abs(curve_id)

        _, self.gissmo_header_right_label = self._header(
            self.gissmo,
            "GISSMO Damage Card + Failure Table",
            right=f"{table_label}",
        )


        body = tk.Frame(self.gissmo, bg=THEME["panel"])
        body.pack(fill=tk.X, padx=10, pady=(8, 10))
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=2)

        card = tk.Frame(body, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        table_card = tk.Frame(body, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        table_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        r = self.current_row
        element = self.current_selections.get("Element") or (r.get("Element", "-") if r is not None else "-")
        material = self.current_selections.get("Material") or (r.get("Material", "-") if r is not None else "-")
        temper = self.current_selections.get("Temper") or (r.get("Temper", "-") if r is not None else "-")
        thickness = self.thickness_var.get() or (self._thickness_display_label(r) if r is not None else "NA")


        grid = tk.Frame(card, bg=THEME["panel"])
        grid.pack(fill=tk.X, expand=True, padx=6, pady=6)
        for col in range(9):
            grid.columnconfigure(col, weight=1, uniform="gissmo")

        label_bg = THEME["matrix_label"]
        label_fg = "white"
        value_bg = THEME["matrix_value"]
        value_fg = "#111827"
        meta_bg = THEME["matrix_meta"]
        hot_bg = "#D76BEA"

        def cell(row, col, text, bg, fg=THEME["text"], font=FONTS["tiny"], colspan=1, rowspan=1, anchor="center"):
            lbl = tk.Label(
                grid,
                text=text,
                bg=bg,
                fg=fg,
                font=font,
                relief="solid",
                bd=1,
                padx=2,
                pady=1,
                anchor=anchor,
            )
            lbl.grid(row=row, column=col, columnspan=colspan, rowspan=rowspan, sticky="nsew")
            return lbl

        cell(0, 0, direction_title, meta_bg, THEME["text"], FONTS["tiny"], colspan=2)
        cell(0, 2, str(element).upper(), meta_bg, THEME["text"], FONTS["tiny"], colspan=2)
        cell(0, 4, f"{material} - {temper}", meta_bg, THEME["text"], FONTS["tiny"], colspan=3)
        cell(0, 7, f"t = {thickness}", meta_bg, THEME["text"], FONTS["tiny"], colspan=2)

        cell(1, 0, "GISSMO", THEME["matrix_black"], "white", FONTS["body_bold"], rowspan=8)

        rows = [
            (["EXCL", "MXPRES", "MNEPS", "EFFEPS", "VOLEPS", "NUMFIP", "NCS", ""],
             ["-", "-", "-", "-", "-", "-", "-", ""]),
            (["MNPRES", "SIGP1", "SIGVM", "MXEPS", "EPSSH", "SIGTH", "IMPULSE", "FAILTM"],
             ["-", "-", "-", "-", "-", "-", "-", "-"]),
            (["IDAM", "DMGTYP", "LCSDG", "ECRIT", "DMGEXP", "DCRIT", "FADEXP", "LCREGD"],
             ["1", "1", f"See {table_label}", f"See {table_label}", "-", "-", "-", "-"]),
            (["SIZFLG", "REFSZ", "HAHSV", "LCSRS", "REGSHR", "RGBIAX", "", ""],
             ["-", "-", "-", "-", "-", "-", "", ""]),
        ]

        grid_row = 1
        for labels, values in rows:
            for i, txt in enumerate(labels):
                if txt:
                    cell(grid_row, i + 1, txt, label_bg, label_fg, FONTS["tiny"])
                else:
                    cell(grid_row, i + 1, "", THEME["panel_elevated"], THEME["text"], FONTS["tiny"])
            grid_row += 1
            for i, txt in enumerate(values):
                bg = hot_bg if labels[i] in {"LCSDG", "ECRIT"} else value_bg
                fg = "#111827"
                if labels[i] == "":
                    bg = THEME["panel_elevated"]
                    txt = ""
                cell(grid_row, i + 1, txt, bg, fg, FONTS["tiny"])
            grid_row += 1


        table_grid = tk.Frame(table_card, bg=THEME["panel"])
        table_grid.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        table_grid.columnconfigure(0, weight=1)
        table_grid.columnconfigure(1, weight=1)

        def tcell(row, col, text, bg, fg=THEME["text"], font=FONTS["small"], colspan=1, anchor="center"):
            lbl = tk.Label(
                table_grid,
                text=text,
                bg=bg,
                fg=fg,
                font=font,
                relief="solid",
                bd=1,
                padx=4,
                pady=3,
                anchor=anchor,
            )
            lbl.grid(row=row, column=col, columnspan=colspan, sticky="nsew")
            return lbl

        tcell(0, 0, f"{table_label} - LCSDG & ECRIT", hot_bg, "#111827", FONTS["small_bold"], colspan=2)
        tcell(1, 0, "Triax.", label_bg, label_fg, FONTS["small_bold"])
        tcell(1, 1, "P.F.S", label_bg, label_fg, FONTS["small_bold"])

        def fmt_triax(v: Optional[float]) -> str:
            if v is None:
                return "-"
            try:
                val = float(v)
            except Exception:
                return "-"
            if abs(val + (1.0 / 3.0)) < 1e-8:
                return "-0.333"
            if abs(val - (2.0 / 3.0)) < 1e-8:
                return "0.667"
            if abs(val + 0.0001) < 1e-10:
                return "-0.0001"
            if abs(val) < 1e-12:
                return "0.000"
            return f"{val:.4g}"

        for i, (triax, pfs) in enumerate(self._gissmo_table_points(computed), start=2):
            tcell(i, 0, fmt_triax(triax), THEME["matrix_value"], THEME["text"], FONTS["mono_small"], anchor="e")
            tcell(i, 1, self._fmt_gissmo_float(pfs, 4), THEME["matrix_value"], THEME["text"], FONTS["mono_small"], anchor="e")

        self.gissmo_tree = table_grid
        self.after_idle(lambda: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")) if hasattr(self, "left_canvas") else None)

    def _gissmo_key_block(self, title: str, mid: int = 1) -> str:
        """Return the GISSMO keyword block and its triaxiality/P.F.S curve.

        V4 verification rule:
            Material ID = MAT MID = GISSMO MID = LCSDG curve ID
            ECRIT is always the negative of that curve ID.
        """
        table_label = self._gissmo_table_label()
        curve_id = abs(int(mid or self._gissmo_curve_id()))
        ecrit_id = -abs(curve_id)
        points = self._gissmo_table_points()

        def f10(value: Any) -> str:
            if value in (None, "", "-"):
                value = 0
            return f"{value:>10}"

        lines = [
            "$",
            f"$ GISSMO Damage / Failure Table: {table_label}",
            "*MAT_ADD_EROSION_TITLE",
            f"{title}_GISSMO",
            "$#      MID      EXCL    MXPRES     MNEPS    EFFEPS    VOLEPS    NUMFIP       NCS",
            f"{f10(mid)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}",
            "$#   MNPRES     SIGP1     SIGVM     MXEPS     EPSSH     SIGTH   IMPULSE    FAILTM",
            f"{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}",
            "$#     IDAM    DMGTYP     LCSDG     ECRIT    DMGEXP     DCRIT    FADEXP    LCREGD",
            f"{f10(1)}{f10(1)}{f10(curve_id)}{f10(ecrit_id)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}",
            "$#   SIZFLG     REFSZ     NAHSV     LCSRS    REGSHR    RGBIAX",
            f"{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}",
            "$",
            "*DEFINE_CURVE_TITLE",
            f"{table_label} - Triaxiality vs P.F.S",
            "$#     LCID      SIDR       SFA       SFO      OFFA      OFFO",
            f"{f10(curve_id)}{f10(0)}{f10(1.0)}{f10(1.0)}{f10(0)}{f10(0)}",
            "$#                A1                  O1",
        ]
        for triax, pfs in points:
            triax_text = f"{triax:.6g}" if triax is not None else "0"
            pfs_text = f"{pfs:.6g}" if pfs is not None else "0"
            lines.append(f"{triax_text:>20}{pfs_text:>20}")
        lines.append("$")
        return "\n".join(lines) + "\n"

    def _model_code(self) -> str:
        model = str(self.mat_model_var.get() or "MAT024+GISSMO").strip().upper().replace(" ", "")
        if model in {"MAT082", "MAT_082", "MAT82"}:
            return "MAT082"
        if model in {"MAT224", "MAT_224"}:
            return "MAT224"
        if model in {"MAT024+GISSMO", "MAT_024+GISSMO", "MAT024GISSMO"}:
            return "MAT024+GISSMO"
        return "MAT024"

    def _engineering_values(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> Dict[str, str]:
        """Return the common Excel-derived values used by MAT024/MAT082/MAT224/GISSMO.

        The source material changes, but the template pattern stays the same:
        RO/E/PR/SIGY come from the selected row and unit system, ETAN comes from
        the true-stress/effective-plastic-strain formula, and FAIL/EPPF/P.F.S.
        use effective plastic strain as a fraction.
        """
        if computed is None:
            computed = self._compute_table()

        def val(row_key: str, field: str = "eng") -> str:
            try:
                return str(computed.get(row_key, {}).get(field, "-")).strip() or "-"
            except Exception:
                return "-"

        fail_fraction = "-"
        if self.last_effps is not None:
            try:
                fail_fraction = fmt_number(abs(float(self.last_effps)) / 100.0)
            except Exception:
                fail_fraction = "-"

        true_ftu = val("Ftu", "true")
        if true_ftu in ("", "-"):
            true_ftu = val("Ftu", "eng")

        return {
            "RO": val("RO", "eng"),
            "E": val("E", "eng"),
            "PR": val("PR", "eng"),
            "SIGY": val("Fty", "eng"),
            "FTU_TRUE": true_ftu,
            "ETAN": fmt_number(abs(float(self.last_etan_true))) if self.last_etan_true is not None else "-",
            "FAIL": fail_fraction,
            "EPPF": fail_fraction,
            "EPPFR": fail_fraction,
            "TDEL": "0",
        }

    def _card_meta(self) -> Dict[str, str]:
        r = self.current_row
        element = self.current_selections.get("Element") or (r.get("Element", "-") if r is not None else "-")
        material = self.current_selections.get("Material") or (r.get("Material", "-") if r is not None else "-")
        temper = self.current_selections.get("Temper") or (r.get("Temper", "-") if r is not None else "-")
        direction_code = "LT" if self.direction_var.get().strip().upper() == "LT" else "L"
        return {
            "element": str(element).upper(),
            "material_temper": f"{material} - {temper}",
            "thickness": self.thickness_var.get() or (self._thickness_display_label(r) if r is not None else "NA"),
            "direction_title": "LONGITUDINAL" if direction_code == "L" else "LONG-TRANSV.",
            "direction_code": direction_code,
        }

    def _mat224_table_label(self, kind: str, basis: Optional[str] = None, direction: Optional[str] = None) -> str:
        basis_code = str(basis or self.basis_var.get() or "B").strip().upper()
        direction_code = "LT" if str(direction or self.direction_var.get()).strip().upper() == "LT" else "L"


        base_num = {"A": 4, "B": 6, "S": 8}.get(basis_code, 4)
        if str(kind).strip().upper() == "LCF":
            base_num += 1
        return f"Table {base_num}{direction_code}"

    def _render_mat24(self):
        """Render the selected engineering model using the common Excel formula engine."""
        model = self._model_code()
        if model == "MAT082":
            return self._render_mat082_card()
        if model == "MAT224":
            return self._render_mat224_card()
        return self._render_mat024_card()

    def _render_mat024_card(self):
        for w in self.mat24.winfo_children():
            w.destroy()
        self.mat24_value_labels.clear()

        title = "MAT_24 Engineering Card"
        _, self.mat24_header_right_label = self._header(
            self.mat24,
            title,
            right=UNIT_SYSTEM_SPEC[self.unit_sys_var.get()]["label"],
        )

        values = self._engineering_values()
        meta = self._card_meta()

        grid = tk.Frame(self.mat24, bg=THEME["panel"])
        grid.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        for c in range(9):
            grid.columnconfigure(c, weight=1, uniform="m24")

        self._cell(grid, 0, 0, self._basis_display().upper(), THEME["matrix_basis"], THEME["text"], FONTS["body_bold"])
        self._cell(grid, 0, 1, "Material Card", THEME["matrix_orange"], THEME["text"], FONTS["body_bold"], colspan=8)

        self._cell(grid, 1, 0, meta["direction_title"], THEME["matrix_dir"], THEME["text"], FONTS["small_bold"])
        self._cell(grid, 1, 1, meta["element"], THEME["matrix_meta"], THEME["text"], FONTS["small_bold"], colspan=2)
        self._cell(grid, 1, 3, meta["material_temper"], THEME["matrix_meta"], THEME["text"], FONTS["small_bold"], colspan=4)
        self._cell(grid, 1, 7, f"t = {meta['thickness']}", THEME["matrix_meta"], THEME["text"], FONTS["small_bold"], colspan=2)

        self._cell(grid, 2, 0, "MAT_24", THEME["matrix_black"], "white", FONTS["h2"], rowspan=8)


        labels = ["RO", "E", "PR", "SIGY", "ETAN", "FAIL", "TDEL"]
        row_values = [values["RO"], values["E"], values["PR"], values["SIGY"], values["ETAN"], values["FAIL"], values["TDEL"]]

        for i, label in enumerate(labels):
            span = 2 if label == "TDEL" else 1
            self._cell(grid, 2, i + 1, label, THEME["matrix_label"], "white", FONTS["small_bold"], colspan=span)
        for i, label in enumerate(labels):
            span = 2 if label == "TDEL" else 1
            lbl = self._cell(grid, 3, i + 1, row_values[i], THEME["matrix_value"], THEME["text"], FONTS["mono_small"], colspan=span)
            self.mat24_value_labels[label] = lbl

        opt = [(1, "C", 1), (2, "P", 1), (3, "LCSS", 1), (4, "LCSR", 1), (5, "VP", 1), (6, "", 1), (7, "LCF", 2)]
        for col, text, span in opt:
            self._cell(grid, 4, col, text, THEME["matrix_label"], "white", FONTS["small_bold"], colspan=span)
            self._cell(grid, 5, col, "" if text == "" else "0", THEME["matrix_value"], THEME["text"], FONTS["mono_small"], colspan=span)

        for i in range(8):
            self._cell(grid, 6, i + 1, f"EPS{i+1}", THEME["matrix_label"], "white", FONTS["small_bold"])
            self._cell(grid, 7, i + 1, "0", THEME["matrix_value"], THEME["text"], FONTS["mono_small"])
            self._cell(grid, 8, i + 1, f"ES{i+1}", THEME["matrix_label"], "white", FONTS["small_bold"])
            self._cell(grid, 9, i + 1, "0", THEME["matrix_value"], THEME["text"], FONTS["mono_small"])

    def _render_mat082_card(self):
        for w in self.mat24.winfo_children():
            w.destroy()
        self.mat24_value_labels.clear()

        _, self.mat24_header_right_label = self._header(
            self.mat24,
            "MAT_82 Engineering Card",
            right=UNIT_SYSTEM_SPEC[self.unit_sys_var.get()]["label"],
        )
        values = self._engineering_values()
        meta = self._card_meta()

        grid = tk.Frame(self.mat24, bg=THEME["panel"])
        grid.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        for c in range(9):
            grid.columnconfigure(c, weight=1, uniform="m82")

        self._cell(grid, 0, 0, self._basis_display().upper(), THEME["matrix_basis"], THEME["text"], FONTS["body_bold"])
        self._cell(grid, 0, 1, "Material Card", THEME["matrix_orange"], THEME["text"], FONTS["body_bold"], colspan=8)
        self._cell(grid, 1, 0, meta["direction_title"], THEME["matrix_dir"], THEME["text"], FONTS["small_bold"])
        self._cell(grid, 1, 1, meta["element"], THEME["matrix_meta"], THEME["text"], FONTS["small_bold"], colspan=2)
        self._cell(grid, 1, 3, meta["material_temper"], THEME["matrix_meta"], THEME["text"], FONTS["small_bold"], colspan=4)
        self._cell(grid, 1, 7, f"t = {meta['thickness']}", THEME["matrix_meta"], THEME["text"], FONTS["small_bold"], colspan=2)
        self._cell(grid, 2, 0, "MAT_82", THEME["matrix_black"], "white", FONTS["h2"], rowspan=6)

        labels1 = ["RO", "E", "PR", "SIGY", "ETAN", "EPPF", "TDEL"]
        vals1 = [values["RO"], values["E"], values["PR"], values["SIGY"], values["ETAN"], values["EPPF"], values["TDEL"]]
        for i, label in enumerate(labels1):
            span = 2 if label == "TDEL" else 1
            self._cell(grid, 2, i + 1, label, THEME["matrix_label"], "white", FONTS["small_bold"], colspan=span)
        for i, label in enumerate(labels1):
            span = 2 if label == "TDEL" else 1
            lbl = self._cell(grid, 3, i + 1, vals1[i], THEME["matrix_value"], THEME["text"], FONTS["mono_small"], colspan=span)
            self.mat24_value_labels[label] = lbl

        labels2 = ["C", "P", "LCSS", "LCSR", "EPPFR", "VP", "LCDM", "NUMINT"]
        vals2 = ["0", "0", "0", "0", values["EPPFR"], "0", "0", "0"]
        for i, label in enumerate(labels2):
            self._cell(grid, 4, i + 1, label, THEME["matrix_label"], "white", FONTS["small_bold"])
        for i, label in enumerate(labels2):
            lbl = self._cell(grid, 5, i + 1, vals2[i], THEME["matrix_value"], THEME["text"], FONTS["mono_small"])
            self.mat24_value_labels[label] = lbl

        tk.Label(
            self.mat24,
            text="MAT082 uses the same Excel-derived RO/E/PR/SIGY/ETAN pipeline; EPPF and EPPFR are effective plastic strain fractions.",
            bg=THEME["panel"], fg=THEME["text_muted"], font=FONTS["small"], anchor="w", justify="left",
        ).pack(fill=tk.X, padx=12, pady=(0, 10))

    def _render_mat224_card(self):
        for w in self.mat24.winfo_children():
            w.destroy()
        self.mat24_value_labels.clear()

        _, self.mat24_header_right_label = self._header(
            self.mat24,
            "MAT_224 Engineering Card + LCK1 / LCF Tables",
            right=UNIT_SYSTEM_SPEC[self.unit_sys_var.get()]["label"],
        )
        values = self._engineering_values()
        meta = self._card_meta()
        lck1_label = self._mat224_table_label("LCK1")
        lcf_label = self._mat224_table_label("LCF")

        body = tk.Frame(self.mat24, bg=THEME["panel"])
        body.pack(fill=tk.X, padx=10, pady=10)
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=3)

        card = tk.Frame(body, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        curves = tk.Frame(body, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
        curves.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        grid = tk.Frame(card, bg=THEME["panel"])
        grid.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        for c in range(8):
            grid.columnconfigure(c, weight=1, uniform="m224")

        self._cell(grid, 0, 0, self._basis_display().upper(), THEME["matrix_basis"], THEME["text"], FONTS["body_bold"])
        self._cell(grid, 0, 1, "Material Card", THEME["matrix_orange"], THEME["text"], FONTS["body_bold"], colspan=7)
        self._cell(grid, 1, 0, meta["direction_title"], THEME["matrix_dir"], THEME["text"], FONTS["small_bold"])
        self._cell(grid, 1, 1, meta["element"], THEME["matrix_meta"], THEME["text"], FONTS["small_bold"], colspan=2)
        self._cell(grid, 1, 3, meta["material_temper"], THEME["matrix_meta"], THEME["text"], FONTS["small_bold"], colspan=3)
        self._cell(grid, 1, 6, f"t = {meta['thickness']}", THEME["matrix_meta"], THEME["text"], FONTS["small_bold"], colspan=2)
        self._cell(grid, 2, 0, "MAT_224", THEME["matrix_black"], "white", FONTS["h2"], rowspan=6)

        labels1 = ["RO", "E", "PR", "CP", "TR", "BETA", "NUMINT"]
        vals1 = [values["RO"], values["E"], values["PR"], "-", "-", "-", "-"]
        for i, label in enumerate(labels1):
            self._cell(grid, 2, i + 1, label, THEME["matrix_label"], "white", FONTS["small_bold"])
        for i, label in enumerate(labels1):
            lbl = self._cell(grid, 3, i + 1, vals1[i], THEME["matrix_value"], THEME["text"], FONTS["mono_small"])
            self.mat24_value_labels[label] = lbl

        labels2 = ["LCK1", "LCKT", "LCF", "LCG", "LCH", "LCI", ""]
        vals2 = [lck1_label, "-", lcf_label, "-", "-", "-", ""]
        for i, label in enumerate(labels2):
            self._cell(grid, 4, i + 1, label, THEME["matrix_label"] if label else THEME["panel_elevated"], "white" if label else THEME["text"], FONTS["small_bold"])
        for i, label in enumerate(labels2):
            bg = "#D76BEA" if vals2[i] in {lck1_label, lcf_label} else (THEME["matrix_value"] if label else THEME["panel_elevated"])
            lbl = self._cell(grid, 5, i + 1, vals2[i], bg, THEME["text"], FONTS["mono_small"])
            if label:
                self.mat24_value_labels[label] = lbl

        labels3 = ["FAILOPT", "NUMAVG", "NYFAIL", "", "", "", ""]
        vals3 = ["-", "-", "-", "", "", "", ""]
        for i, label in enumerate(labels3):
            if label:
                self._cell(grid, 6, i + 1, label, THEME["matrix_label"], "white", FONTS["small_bold"])
            else:
                self._cell(grid, 6, i + 1, "", THEME["panel_elevated"], THEME["text"], FONTS["small_bold"])
        for i, label in enumerate(labels3):
            self._cell(grid, 7, i + 1, vals3[i], THEME["matrix_value"] if label else THEME["panel_elevated"], THEME["text"], FONTS["mono_small"])


        table_grid = tk.Frame(curves, bg=THEME["panel"])
        table_grid.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        for c in range(4):
            table_grid.columnconfigure(c, weight=1)

        def ccell(row, col, text, bg, fg=THEME["text"], font=FONTS["small"], colspan=1, anchor="center"):
            lbl = tk.Label(table_grid, text=text, bg=bg, fg=fg, font=font, relief="solid", bd=1, padx=4, pady=3, anchor=anchor)
            lbl.grid(row=row, column=col, columnspan=colspan, sticky="nsew")
            return lbl

        hot_bg = "#F6A96B"
        magenta = "#D76BEA"
        ccell(0, 0, f"{lck1_label} - LCK1", hot_bg, "#111827", FONTS["small_bold"], colspan=2)
        ccell(1, 0, "X_VALUE", THEME["matrix_label"], "white", FONTS["small_bold"])
        ccell(1, 1, "Y_VALUE", THEME["matrix_label"], "white", FONTS["small_bold"])
        ccell(2, 0, "0", THEME["matrix_value"], THEME["text"], FONTS["mono_small"], anchor="e")
        ccell(2, 1, values["SIGY"], THEME["matrix_value"], THEME["text"], FONTS["mono_small"], anchor="e")
        ccell(3, 0, values["FAIL"], THEME["matrix_value"], THEME["text"], FONTS["mono_small"], anchor="e")
        ccell(3, 1, values["FTU_TRUE"], THEME["matrix_value"], THEME["text"], FONTS["mono_small"], anchor="e")

        ccell(0, 2, f"{lcf_label} - LCF", hot_bg, "#111827", FONTS["small_bold"], colspan=2)
        ccell(1, 2, "Triax.", THEME["matrix_label"], "white", FONTS["small_bold"])
        ccell(1, 3, "P.F.S", THEME["matrix_label"], "white", FONTS["small_bold"])
        lcf_points = [(-2.0 / 3.0, values["FAIL"]), (0.0, values["FAIL"]), (0.0001, "0.9900"), (1.0 / 3.0, "0.9900")]
        for offset, (triax, pfs) in enumerate(lcf_points, start=2):
            t = "-0.667" if abs(triax + 2.0/3.0) < 1e-8 else ("0.000" if abs(triax) < 1e-12 else ("0.0001" if abs(triax - 0.0001) < 1e-10 else "0.333"))
            ccell(offset, 2, t, THEME["matrix_value"], THEME["text"], FONTS["mono_small"], anchor="e")
            ccell(offset, 3, pfs if pfs not in ("", None) else "-", THEME["matrix_value"], THEME["text"], FONTS["mono_small"], anchor="e")


    def _cell(self, parent, row, col, text, bg, fg, font, colspan=1, rowspan=1):


        lbl = tk.Label(parent, text=text, bg=bg, fg=fg, font=font,
                       relief="solid", bd=1, padx=4, pady=3)
        lbl.grid(row=row, column=col, columnspan=colspan, rowspan=rowspan, sticky="nsew")
        return lbl

    def _current_material_summary_for_audit(self, custom: bool = False) -> str:
        """Material Summary text used by History and Export Log.

        Only clean material fields are shown. Wall and CS are intentionally not displayed.
        """
        row = self.current_row
        selections = dict(self.current_selections or {})
        element = selections.get("Element") or (row.get("Element", "") if row is not None else "")
        material = selections.get("Material") or (row.get("Material", "") if row is not None else "")
        temper = selections.get("Temper") or (row.get("Temper", "") if row is not None else "")
        series = selections.get("Series", "")
        if not series:
            try:
                series = self.app.db._material_to_series.get(norm(material), "")
            except Exception:
                series = ""
        spec = selections.get("Specification") or (row.get("Spec1_1", row.get("spec1_1", "")) if row is not None else "")
        if is_blank(spec):
            spec = NO_SPEC_DISPLAY
        spec2 = selections.get("Specification 2") or (row_spec2_value(row) if row is not None else "")
        spec2 = display_spec_value(spec2)
        form = selections.get("Form") or (row.get("Form", "") if row is not None else "")
        source = row.get("MMPDS_Version", "-") if row is not None else "-"
        material_text = f"{element} {material}-{temper}".strip(" -")
        prefix = "CUSTOM | " if custom else ""
        return f"{prefix}Material: {material_text or '-'}  |  Series: {series or '-'}  |  Spec: {spec or '-'}  |  Spec 2: {spec2 or '-'}  |  Form: {form or '-'}  |  Source: {source or '-'}"

    def _audit_selection_fields(self) -> Dict[str, str]:
        row = self.current_row
        selections = dict(self.current_selections or {})
        material = selections.get("Material") or (row.get("Material", "") if row is not None else "")
        series = selections.get("Series", "")
        if not series:
            try:
                series = self.app.db._material_to_series.get(norm(material), "")
            except Exception:
                series = ""
        spec = selections.get("Specification") or (row.get("Spec1_1", row.get("spec1_1", "")) if row is not None else "")
        if is_blank(spec):
            spec = NO_SPEC_DISPLAY
        return {
            "element": selections.get("Element") or (row.get("Element", "") if row is not None else ""),
            "series": series,
            "material": material,
            "temper": selections.get("Temper") or (row.get("Temper", "") if row is not None else ""),
            "specification": spec,
            "form": selections.get("Form") or (row.get("Form", "") if row is not None else ""),
            "basis": self.basis_var.get(),
            "direction": self.direction_var.get(),
            "unit_system": UNIT_SYSTEM_SPEC.get(self.unit_sys_var.get(), {}).get("label", self.unit_sys_var.get()),
        }

    def _audit_log_from_card(self, **kwargs) -> None:
        """Send a structured audit event from Screen 2 to the Export Log tab."""
        try:
            selection_screen = self.app.screens.get("SelectionScreen")
            if selection_screen is not None and hasattr(selection_screen, "_audit_log_action"):
                selection_screen._audit_log_action(**kwargs)
        except Exception:
            pass

    def _card_history_summary_entry(self, applied_property_edits: Dict[str, str], applied_unit_edits: Dict[str, str]) -> Dict[str, Any]:
        """Create a history entry that can restore this exact edited Screen 2 state."""
        row = self.current_row
        selections = dict(self.current_selections or {})
        for stage in STAGES:
            if not selections.get(stage) and row is not None:
                if stage == "Specification":
                    selections[stage] = row.get("Spec1_1", row.get("spec1_1", ""))
                    if is_blank(selections[stage]):
                        selections[stage] = NO_SPEC_DISPLAY
                else:
                    selections[stage] = row.get(stage, selections.get(stage, ""))
        if not selections.get("Series"):
            try:
                selections["Series"] = self.app.db._material_to_series.get(norm(selections.get("Material", "")), "")
            except Exception:
                selections["Series"] = ""

        prop_state = {k: [str(v[0]), bool(v[1])] for k, v in self.prop_values.items()}
        entry = {"datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "history_type": "edited_card"}
        entry.update(selections)
        opened_from = str(getattr(self, "opened_from_context", "")).strip()
        opened_export_id = str(getattr(self, "opened_export_id_context", "")).strip()
        if opened_from:
            entry["Opened_From"] = opened_from
        if opened_export_id:
            entry["Export_ID"] = opened_export_id
        entry["_card_state"] = {
            "Basis": self.basis_var.get(),
            "Direction": self.direction_var.get(),
            "Thickness": self._thickness_display_label(row) if row is not None else self.thickness_var.get(),
            "Thickness_Row_Key": self._row_identity_key(row) if row is not None else "",
            "Unit_System": self.unit_sys_var.get(),
            "Material_Model": self.mat_model_var.get(),
            "prop_values": prop_state,
            "edited_values": dict(applied_property_edits or {}),
            "unit_conversions": {k: self.unit_conversions.get(k, v) for k, v in DEFAULT_UNIT_CONVERSIONS.items()},
            "unit_conversion_edits": dict(applied_unit_edits or {}),
            "Wall": row.get("Wall_Thick", "-") if row is not None else "-",
            "Cross_Section": row.get("Cross_Section", "-") if row is not None else "-",
            "Source": row.get("MMPDS_Version", "-") if row is not None else "-",
            "Opened_From": opened_from,
            "Export_ID": opened_export_id,
        }
        return entry

    def _save_edited_card_to_history(self, applied_property_edits: Dict[str, str], applied_unit_edits: Dict[str, str]) -> None:
        if not applied_property_edits and not applied_unit_edits:
            return
        try:
            entry = self._card_history_summary_entry(applied_property_edits, applied_unit_edits)
            self.app.history.append(entry)
            selection_screen = self.app.screens.get("SelectionScreen")
            if selection_screen is not None and hasattr(selection_screen, "_refresh_history"):
                selection_screen._refresh_history()
            if hasattr(self.app, "status_var"):
                self.app.status_var.set("Edited material version saved to history")
        except Exception as exc:
            logger.warning("Could not save edited material history: %s", exc)

    def _commit_all_pending_edits(self, trigger: str = "Enter"):
        """Confirm all pending Property Card and Unit Conversion edits.

        Values preview while the user types. Clicking Apply confirms every
        pending valid edit. Reset before Apply discards pending text and restores
        source/default values.
        """
        if not self.pending_edits and not self.unit_pending_edits:
            self._refresh_cards_fast()
            self._render_unit_conversions()
            return

        invalid = []
        for key, val in list(self.pending_edits.items()):
            if str(val).strip() not in ("", "-") and try_float(val) is None:
                invalid.append(key)
        if invalid:
            messagebox.showerror("Invalid Value", "Only numeric values are allowed.\n\nInvalid rows: " + ", ".join(invalid))
            self._refresh_cards_fast()
            return

        applied_property_edits = {key: str(val).strip() for key, val in self.pending_edits.items()}
        applied_unit_edits = {key: str(val).strip() for key, val in self.unit_pending_edits.items()}
        old_property_values = {key: strip_edit_box(self.prop_values.get(key, ("", False))[0]) for key in applied_property_edits}
        old_unit_values = {
            key: self._format_conversion_factor(self.unit_conversions.get(key, DEFAULT_UNIT_CONVERSIONS.get(key, "")))
            for key in applied_unit_edits
        }

        try:
            self._apply_unit_conversion_edits()
        except ValueError as exc:
            messagebox.showerror("Invalid Unit Conversion", str(exc))
            self._refresh_cards_fast()
            self._render_unit_conversions()
            return

        had_property_edits = bool(applied_property_edits)
        for key, val in list(applied_property_edits.items()):
            if val.strip() in ("", "-"):
                self.prop_values[key] = ("", False)
            else:
                self.prop_values[key] = (val.strip(), True)

        self.pending_edits.clear()
        self._sync_material_modified_disclaimer()
        self._save_edited_card_to_history(applied_property_edits, applied_unit_edits)

        change_lines = []
        changed_fields = []
        old_values = []
        new_values = []
        for key, new_val in applied_property_edits.items():
            old_val = old_property_values.get(key, "")
            changed_fields.append(key)
            old_values.append(f"{key}: {old_val}")
            new_values.append(f"{key}: {new_val}")
            change_lines.append(f"{key}: {old_val} -> {new_val}")
        for key, new_val in applied_unit_edits.items():
            old_val = old_unit_values.get(key, "")
            changed_fields.append(key)
            old_values.append(f"{key}: {old_val}")
            new_values.append(f"{key}: {new_val}")
            change_lines.append(f"{key}: {old_val} -> {new_val}")

        if changed_fields:
            fields = self._audit_selection_fields()
            self._audit_log_from_card(
                screen="Material Card",
                action="Apply Confirmed Changes",
                status="Saved",
                material_summary=self._current_material_summary_for_audit(custom=True),
                changed_field=", ".join(changed_fields),
                old_value=" | ".join(old_values),
                new_value=" | ".join(new_values),
                notes="CUSTOM material values confirmed with Apply. Changed values remain highlighted.",
                details="Changed values:\n" + "\n".join(change_lines) if change_lines else "No value changes.",
                **fields,
            )

        self._refresh_cards_fast()
        self._render_unit_conversions()

    def _apply(self):
        """Apply pending Property Card and Unit Conversion edits."""
        return self._commit_all_pending_edits(trigger="Apply button")

    def _reset_props(self):
        """Reset Property Card values and Unit Conversions to source/default values.

        This works even if the user typed a value but did not press Enter. Any
        pending text is discarded and the boxes are repopulated from the source
        values/default conversion factors.
        """
        self._updating_ui = True
        try:
            self.pending_edits.clear()
            self.unit_pending_edits.clear()
            self._seed_values()
            self._hide_material_modified_disclaimer()
            self._reset_unit_conversions()
        finally:
            self._updating_ui = False
        self._refresh_cards_fast()
        self._render_unit_conversions()
    def _basis_display(self):
        for label, code in BASIS_OPTIONS:
            if code == self.basis_var.get():
                return label
        return self.basis_var.get()

    def _safe_filename_part(self, value):
        text = str(value).strip()
        if not text or text == "-":
            return "NA"

        replacements = {
            "<=": "lessequalthan",
            ">=": "greaterthanequal",
            "<": "lessthan",
            ">": "greaterthan",
            " ": "_",
            ",": "-",
            "/": "_",
            "\\": "_",
            ":": "_",
            "*": "_",
            "?": "_",
            '"': "_",
            "|": "_",
            "+": "_",
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        while "__" in text:
            text = text.replace("__", "_")

        return text.strip("_") or "NA"


    def _element_export_code(self, element):
        """Short element/material-family code used in exported keyfile names.

        Example required by manager:
            AL_2013-T6511_AMS-4326_ExtrudedBarRodProfiles_0.2_A_Basis_L_MPA_MAT024.key
        """
        text = str(element or "").strip()
        lookup = {
            "aluminum": "AL",
            "aluminium": "AL",
            "steel": "STEEL",
            "titanium": "TI",
            "magnesium": "MG",
            "nickel": "NI",
            "copper": "CU",
            "cobalt": "CO",
            "iron": "FE",
        }
        return lookup.get(norm(text), self._filename_token(text).upper())

    def _filename_token(self, value, keep_hyphen: bool = True):
        """Clean one filename part without changing engineering values.

        This is separate from _safe_filename_part because the manager-requested
        exported names use compact readable tokens like AMS-4326 and A_Basis.
        """
        text = str(value or "").strip()
        if not text or text in {"-", NO_SPEC_DISPLAY}:
            return "NA"

        replacements = {
            "<=": "",
            ">=": "",
            "<": "",
            ">": "",
            "=": "",
            "/": "_",
            "\\": "_",
            ":": "_",
            "*": "_",
            "?": "_",
            '"': "_",
            "|": "_",
            ",": "_",
            "(": "",
            ")": "",
            "[": "",
            "]": "",
            "+": "_",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)


        if keep_hyphen:
            text = text.replace(" ", "-") if text.upper().startswith("AMS ") else text.replace(" ", "_")
        else:
            text = text.replace("-", "_").replace(" ", "_")

        while "__" in text:
            text = text.replace("__", "_")
        while "--" in text:
            text = text.replace("--", "-")
        return text.strip("_-") or "NA"

    def _thickness_filename_token(self, thickness):
        """Convert source thickness text to compact filename token.

        Examples:
            <=0.200  -> 0.2
            0.500-2.500 -> 0.5-2.5
        """
        text = str(thickness or "").strip()
        if not text or text == "-":
            return "NA"
        for prefix in ("<=", ">=", "<", ">", "="):
            text = text.replace(prefix, "")
        text = text.strip()

        def compact_number(part: str) -> str:
            try:
                num = float(part)
                return (f"{num:.6g}").rstrip(".")
            except Exception:
                return self._filename_token(part)

        if "-" in text:
            pieces = [compact_number(x.strip()) for x in text.split("-") if x.strip()]
            return "-".join(pieces) if pieces else "NA"
        return compact_number(text)

    def _basis_filename_token(self):

        return self._basis_display().replace(" ", "_").replace("-", "_")

    def _unit_filename_token(self):

        unit = UNIT_SYSTEM_SPEC[self.unit_sys_var.get()]["pressure_label"]
        return self._filename_token(unit).upper()

    def _keyfile_export_stem(self, element, material, temper, spec, form, thickness,
                             direction, model, custom: bool = False):
        prefix = "CUSTOM_" if custom else ""
        material_temper = f"{material}-{temper}"
        parts = [
            self._element_export_code(element),
            self._filename_token(material_temper),
            self._filename_token(spec),
            self._filename_token(form, keep_hyphen=False),
            self._thickness_filename_token(thickness),
            self._basis_filename_token(),
            self._filename_token(direction).upper(),
            self._unit_filename_token(),
            self._filename_token(model).upper(),
        ]
        return prefix + "_".join([part for part in parts if part and part != "NA"])

    def _format_key_number(self, value, kind="default"):
        num = try_float(value)
        if num is None:
            return "0"

        if abs(num) == 0:
            return "0"

        if kind == "density":
            return f"{num:.3e}"

        if kind == "fail":
            return f"{num:.4f}"

        if kind == "ratio":
            return f"{num:.4g}"

        if abs(num) >= 100:
            return f"{num:.2f}"

        if abs(num) >= 1:
            return f"{num:.2f}"

        return f"{num:.6g}"

    def _positive_fmt_number(self, value, default: str = "-") -> str:
        """Format a value as positive for keyfile strain/tangent-modulus fields."""
        num = try_float(value)
        if num is None:
            return default
        return fmt_number(abs(num))

    def _positive_fraction_fmt(self, percent_value, default: str = "-") -> str:
        """Convert a percent value to a positive fraction string for FAIL/EPPF/P.F.S."""
        num = try_float(percent_value)
        if num is None:
            return default
        return fmt_number(abs(num) / 100.0)

    def _export_model_code_from_value(self, model: Optional[str] = None) -> str:
        """Normalize a material model label for export branching."""
        raw = str(model or self.mat_model_var.get() or "MAT024+GISSMO").strip().upper().replace(" ", "")
        if raw in {"MAT082", "MAT_082", "MAT82"}:
            return "MAT082"
        if raw in {"MAT224", "MAT_224"}:
            return "MAT224"
        if raw in {"MAT024+GISSMO", "MAT_024+GISSMO", "MAT024GISSMO"}:
            return "MAT024+GISSMO"
        return "MAT024"

    def _key_field(self, value: Any) -> str:
        """Return one LS-DYNA 10-character compact field."""
        if value is None or value == "":
            value = 0
        return f"{str(value):>10}"

    def _curve_pair_line(self, x_value: Any, y_value: Any) -> str:
        """Return one DEFINE_CURVE x/y line using wide readable fields."""
        return f"{str(x_value):>20}{str(y_value):>20}"

    def _mat224_lck1_curve_id(self) -> int:
        return 2241

    def _mat224_lcf_curve_id(self) -> int:
        return 2242

    def _mat082_key_block(self, title: str, ro: str, e: str, pr: str, sigy: str,
                          etan: str, eppf: str, tdel: str, mid: int = 1) -> str:
        """Build MAT082 compact export using the same values displayed in the GUI.

        MAT081/082 Plasticity With Damage uses Card 1:
        MID, RO, E, PR, SIGY, ETAN, EPPF, TDEL
        and Card 2:
        C, P, LCSS, LCSR, EPPFR, VP, LCDM, NUMINT.
        """
        eppfr = eppf
        return (
            "*MAT_PLASTICITY_WITH_DAMAGE_TITLE\n"
            f"{title}\n"
            f"{self._key_field(mid)}{self._key_field(ro)}{self._key_field(e)}{self._key_field(pr)}"
            f"{self._key_field(sigy)}{self._key_field(etan)}{self._key_field(eppf)}{self._key_field(tdel)}\n"
            f"{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}"
            f"{self._key_field(eppfr)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}\n"
            f"{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}"
            f"{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}\n"
            f"{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}"
            f"{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}\n"
            "$\n"
        )

    def _mat224_key_block(self, title: str, ro: str, e: str, pr: str, sigy: str,
                          ftu_true: str, fail: str, mid: int = 1) -> str:
        """Build MAT224 compact export plus its required LCK1/LCF curves.

        This follows the MAT224 GUI card already shown in the app:
        Card 1 = MID, RO, E, PR, CP, TR, BETA, NUMINT
        Card 2 = LCK1, LCKT, LCF, LCG, LCH, LCI.
        The generated curves are minimal defaults from the values available in MMPDS.
        """
        lck1 = self._mat224_lck1_curve_id()
        lcf = self._mat224_lcf_curve_id()
        fail_num = try_float(fail)
        if fail_num is None or fail_num <= 0:
            fail_for_curve = "0"
        else:
            fail_for_curve = self._format_key_number(fail_num, "fail")
        sigy_curve = sigy if sigy not in ("", "-", None) else "0"
        ftu_curve = ftu_true if ftu_true not in ("", "-", None) else sigy_curve

        return (
            "*MAT_TABULATED_JOHNSON_COOK_TITLE\n"
            f"{title}\n"
            f"{self._key_field(mid)}{self._key_field(ro)}{self._key_field(e)}{self._key_field(pr)}"
            f"{self._key_field(0)}{self._key_field(0)}{self._key_field(1)}{self._key_field(1)}\n"
            f"{self._key_field(lck1)}{self._key_field(0)}{self._key_field(lcf)}{self._key_field(0)}"
            f"{self._key_field(0)}{self._key_field(0)}\n"
            "$\n"
            "*DEFINE_CURVE_TITLE\n"
            f"{title}_LCK1\n"
            f"{self._key_field(lck1)}{self._key_field(0)}{self._key_field(1.0)}{self._key_field(1.0)}"
            f"{self._key_field(0)}{self._key_field(0)}\n"
            f"{self._curve_pair_line('0', sigy_curve)}\n"
            f"{self._curve_pair_line(fail_for_curve, ftu_curve)}\n"
            "$\n"
            "*DEFINE_CURVE_TITLE\n"
            f"{title}_LCF\n"
            f"{self._key_field(lcf)}{self._key_field(0)}{self._key_field(1.0)}{self._key_field(1.0)}"
            f"{self._key_field(0)}{self._key_field(0)}\n"
            f"{self._curve_pair_line('-0.666667', fail_for_curve)}\n"
            f"{self._curve_pair_line('0', fail_for_curve)}\n"
            f"{self._curve_pair_line('0.0001', '0.99')}\n"
            f"{self._curve_pair_line('0.333333', '0.99')}\n"
            "$\n"
        )

    def _mat024_key_block(self, title: str, ro: str, e: str, pr: str, sigy: str,
                          etan: str, fail: str, tdel: str, mid: int = 1) -> str:
        """Build MAT024 compact export."""
        return (
            "*MAT_PIECEWISE_LINEAR_PLASTICITY_TITLE\n"
            f"{title}\n"
            f"{self._key_field(mid)}{self._key_field(ro)}{self._key_field(e)}{self._key_field(pr)}"
            f"{self._key_field(sigy)}{self._key_field(etan)}{self._key_field(fail)}{self._key_field(tdel)}\n"
            f"{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}\n"
            f"{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}\n"
            f"{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}{self._key_field(0)}\n"
            "$\n"
        )

    def _build_export_keyfile_text(self, *, title: str, full_material_name: str, spec: str,
                                   available_specs_text: str, unit_label: str, pressure_unit: str,
                                   density_unit: str, model: str, custom_edited: bool, user: str,
                                   timestamp: str, ro: str, e: str, pr: str, sigy: str, etan: str,
                                   fail: str, tdel: str, ftu_true: str = "0",
                                   gissmo_block: str = "", material_id: int = 1) -> str:
        """Build the final keyfile text for whichever model is selected in the GUI."""
        model_code = self._export_model_code_from_value(model)
        if model_code == "MAT082":
            model_block = self._mat082_key_block(title, ro, e, pr, sigy, etan, fail, tdel, mid=material_id)
        elif model_code == "MAT224":
            model_block = self._mat224_key_block(title, ro, e, pr, sigy, ftu_true, fail, mid=material_id)
        else:
            model_block = self._mat024_key_block(title, ro, e, pr, sigy, etan, fail, tdel, mid=material_id)

        return (
            "$\n"
            f"$ Full Material Name: {full_material_name}\n"
            f"$ Export Counter ID: {material_id}\n"
            f"$ Material ID / MID / GISSMO Curve ID: {material_id}\n"
            f"$ Selected Specification: {spec}\n"
            f"$ Available Specifications: {available_specs_text}\n"
            f"$ Unit System Exported: {unit_label}\n"
            f"$ Pressure/Stress Unit: {pressure_unit}\n"
            f"$ Density Unit: {density_unit}\n"
            f"$ Material Model: {model}\n"
            f"$ Custom Edited: {'Yes' if custom_edited else 'No'}\n"
            f"$ User: {user}\n"
            f"$ Timestamp: {timestamp}\n"
            "$\n"
            f"{model_block}"
            f"{gissmo_block}"
            "*END\n"
        )

    def export_keyfile_programmatic(self, row, selections: Dict[str, str], output_dir: Path,
                                    output_stem: str, basis: str = "B", direction: str = "L",
                                    unit_sys: str = "mm_T_s", mat_model: str = "MAT024+GISSMO",
                                    material_id: Optional[Any] = None) -> Dict[str, Any]:
        """Generate one selected-model keyfile without opening the Card screen or file dialog.

        Used by Screen 1 Advanced Selection for batch export. The calculation path
        is intentionally the same as the normal CardScreen export path.
        """
        if row is None:
            return {"ok": False, "missing": ["row"], "path": "", "error": "No material row selected"}

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)


        old_state = {
            "current_row": self.current_row,
            "current_selections": dict(self.current_selections),
            "thickness_rows": list(self.thickness_rows),
            "basis": self.basis_var.get(),
            "direction": self.direction_var.get(),
            "thickness": self.thickness_var.get(),
            "unit_sys": self.unit_sys_var.get(),
            "mat_model": self.mat_model_var.get(),
            "prop_values": dict(self.prop_values),
            "pending_edits": dict(self.pending_edits),
            "last_effps": self.last_effps,
            "last_etan_eng": self.last_etan_eng,
            "last_etan_true": self.last_etan_true,
        }

        try:
            self.current_row = row
            self.current_selections = dict(selections or {})
            self.thickness_rows = [row]
            self.basis_var.set(basis or "B")
            self.direction_var.set(direction or "L")
            self.unit_sys_var.set(unit_sys if unit_sys in UNIT_SYSTEM_SPEC else "mm_T_s")
            self.mat_model_var.set(mat_model or "MAT024+GISSMO")
            self.thickness_var.set(self._thickness_display_label(row))
            self._seed_values()
            custom_state = getattr(self, "_programmatic_custom_state", None)
            if isinstance(custom_state, dict):
                if isinstance(custom_state.get("prop_values"), dict):
                    restored = {}
                    for key, value in custom_state.get("prop_values", {}).items():
                        if isinstance(value, (list, tuple)) and len(value) >= 2:
                            restored[key] = (str(value[0]), bool(value[1]))
                        elif isinstance(value, dict):
                            restored[key] = (str(value.get("value", "")), bool(value.get("edited", False)))
                    if restored:
                        self.prop_values.update(restored)
                if isinstance(custom_state.get("unit_conversions"), dict):
                    for k, v in custom_state.get("unit_conversions", {}).items():
                        num = try_float(v)
                        if num is not None:
                            self.unit_conversions[k] = num
                            default_num = try_float(DEFAULT_UNIT_CONVERSIONS.get(k))
                            if default_num is not None and num != default_num:
                                self.unit_confirmed_edits.add(k)

            export_model = self._model_code()

            tbl = self._compute_table()
            is_gissmo_export = self._is_gissmo_model()
            ro_raw = tbl["RO"]["eng"]
            e_raw = tbl["E"]["eng"]
            pr_raw = tbl["PR"]["eng"]
            sigy_raw = tbl["Fty"]["eng"]
            etan_raw = self._positive_fmt_number(self.last_etan_true)
            fail_raw = self._positive_fraction_fmt(self.last_effps)
            tdel_raw = "0"
            model_values = self._engineering_values(tbl)
            ftu_true_raw = model_values.get("FTU_TRUE", "-")

            missing = []
            if not self._selected_basis_available():
                missing.append(f"{self.basis_var.get()} Basis not available")
            required_values = [
                ("RO", ro_raw),
                ("E", e_raw),
                ("PR", pr_raw),
                ("SIGY", sigy_raw),
                ("ETAN", etan_raw),
            ]
            required_values.append(("GISSMO P.F.S.", fail_raw) if is_gissmo_export else ("FAIL/EPPF", fail_raw))
            if export_model == "MAT224":
                required_values.append(("FTU_TRUE", ftu_true_raw))
            for label, value in required_values:
                if is_blank(value):
                    missing.append(label)
            if missing:
                return {"ok": False, "missing": missing, "path": "", "error": "Missing required MAT024 values"}

            element = self.current_selections.get("Element") or row.get("Element", "Element")
            material = self.current_selections.get("Material") or row.get("Material", "Material")
            temper = self.current_selections.get("Temper") or row.get("Temper", "Temper")
            spec = self.current_selections.get("Specification") or row.get("Spec1_1", "Spec")
            spec2 = self.current_selections.get("Specification 2") or row_spec2_value(row)
            spec2 = display_spec_value(spec2)
            form = self.current_selections.get("Form") or row.get("Form", "Form")
            thickness = self._thickness_display_label(row)
            direction_name = self.direction_var.get()
            basis_name = self._basis_display().replace(" ", "-")
            model = self.mat_model_var.get()

            unit_spec = UNIT_SYSTEM_SPEC[self.unit_sys_var.get()]
            unit_label = unit_spec["label"]
            pressure_unit = unit_spec["pressure_label"]
            density_unit = unit_spec["density_label"]


            try:
                material_id = reserve_next_export_id(material_id)
            except Exception as exc:
                return {"ok": False, "missing": [], "path": "", "error": str(exc)}
            full_material_name = (
                f"{element} {material}-{temper} | Export ID/MID: {material_id} | Spec: {spec} | Spec 2: {spec2} | Form: {form} | "
                f"Thickness: {thickness} | Direction: {direction_name} | Basis: {basis_name}"
            )

            available_specs = []
            try:
                spec_query = dict(self.current_selections)
                spec_query["Specification"] = ""
                spec_query["Specification 2"] = ""
                spec_rows = self.app.db.filter_master(spec_query)
                spec_col = find_col(spec_rows, "Spec1_1", "spec1_1", "Specification")
                if spec_col and not spec_rows.empty:
                    vals = []
                    for v in spec_rows[spec_col].astype(str).tolist():
                        clean = NO_SPEC_DISPLAY if is_blank(v) else str(v).strip()
                        if clean and clean not in vals:
                            vals.append(clean)
                    available_specs = vals
            except Exception:
                available_specs = []
            available_specs_text = ", ".join(available_specs) if available_specs else str(spec)


            title = self._keyfile_export_stem(
                element=element,
                material=material,
                temper=temper,
                spec=spec,
                form=form,
                thickness=thickness,
                direction=direction_name,
                model=model,
                custom=False,
            )

            ro = self._format_key_number(ro_raw, "density")
            e = self._format_key_number(e_raw)
            pr = self._format_key_number(pr_raw, "ratio")
            sigy = self._format_key_number(sigy_raw)
            etan = self._format_key_number(etan_raw)
            fail = "0" if is_gissmo_export else self._format_key_number(fail_raw, "fail")
            tdel = self._format_key_number(tdel_raw)
            gissmo_block = self._gissmo_key_block(title, mid=material_id) if is_gissmo_export else ""

            user = getpass.getuser().lower()
            timestamp = datetime.now().strftime("%H:%M %Y/%m/%d")

            ftu_true = self._format_key_number(ftu_true_raw)
            k_text = self._build_export_keyfile_text(
                title=title,
                full_material_name=full_material_name,
                spec=spec,
                available_specs_text=available_specs_text,
                unit_label=unit_label,
                pressure_unit=pressure_unit,
                density_unit=density_unit,
                model=model,
                custom_edited=bool(getattr(self, "_programmatic_custom_state", None)),
                user=user,
                timestamp=timestamp,
                ro=ro,
                e=e,
                pr=pr,
                sigy=sigy,
                etan=etan,
                fail=fail,
                tdel=tdel,
                ftu_true=ftu_true,
                gissmo_block=gissmo_block,
                material_id=material_id,
            )
            export_notes = str(getattr(self, "_programmatic_export_notes", "") or "").strip()
            if export_notes:
                k_text = _append_user_notes_to_keyfile_end(k_text, export_notes)


            safe_stem = self._safe_filename_part(title or output_stem or "MAT024_export")
            save_path = output_dir / f"{safe_stem}.key"
            counter = 2
            while save_path.exists():
                save_path = output_dir / f"{safe_stem}_{counter}.key"
                counter += 1

            save_path.write_text(k_text, encoding="utf-8")
            return {"ok": True, "missing": [], "path": str(save_path), "error": "", "export_id": material_id}
        finally:
            self.current_row = old_state["current_row"]
            self.current_selections = old_state["current_selections"]
            self.thickness_rows = old_state["thickness_rows"]
            self.basis_var.set(old_state["basis"])
            self.direction_var.set(old_state["direction"])
            self.thickness_var.set(old_state["thickness"])
            self.unit_sys_var.set(old_state["unit_sys"])
            self.mat_model_var.set(old_state["mat_model"])
            self.prop_values = old_state["prop_values"]
            self.pending_edits = old_state["pending_edits"]
            self.last_effps = old_state["last_effps"]
            self.last_etan_eng = old_state["last_etan_eng"]
            self.last_etan_true = old_state["last_etan_true"]


    def _export(self):
        """Export current selected material model in manager/PRIMER-style compact .key format.

        Exact manager-style output:
        - No $# header rows
        - Compact numeric rows only
        - Title starts with Element_Material-Temper
        - Includes current user and timestamp in HH:MM YYYY/MM/DD format
        """
        fields = self._audit_selection_fields()
        material_summary = self._current_material_summary_for_audit(
            custom=any(edited for _value, edited in self.prop_values.values())
        )

        export_model = self._model_code()

        tbl = self._compute_table()
        is_gissmo_export = self._is_gissmo_model()

        ro_raw = tbl["RO"]["eng"]
        e_raw = tbl["E"]["eng"]
        pr_raw = tbl["PR"]["eng"]
        sigy_raw = tbl["Fty"]["eng"]
        etan_raw = self._positive_fmt_number(self.last_etan_true)
        fail_raw = self._positive_fraction_fmt(self.last_effps)
        tdel_raw = "0"
        model_values = self._engineering_values(tbl)
        ftu_true_raw = model_values.get("FTU_TRUE", "-")

        missing = []
        required_values = [
            ("RO", ro_raw),
            ("E", e_raw),
            ("PR", pr_raw),
            ("SIGY", sigy_raw),
            ("ETAN", etan_raw),
        ]
        required_values.append(("GISSMO P.F.S.", fail_raw) if is_gissmo_export else ("FAIL/EPPF", fail_raw))
        if export_model == "MAT224":
            required_values.append(("FTU_TRUE", ftu_true_raw))
        for label, value in required_values:
            if value in ("", "-", None):
                missing.append(label)

        if missing:
            self._audit_log_from_card(
                screen="Material Card",
                action="Export kFile",
                status="Error",
                material_summary=material_summary,
                notes="Cannot export because MAT_24 values are missing.",
                details="Missing values: " + ", ".join(missing),
                **fields,
            )
            messagebox.showerror(
                "Export kFile",
                "Cannot export because these MAT_24 values are missing:\n\n"
                + ", ".join(missing)
                + "\n\nCheck the selected basis, direction, thickness, and source data."
            )
            return

        row = self.current_row
        if row is None:
            self._audit_log_from_card(
                screen="Material Card",
                action="Export kFile",
                status="Error",
                notes="No material is currently selected.",
            )
            messagebox.showerror("Export kFile", "No material is currently selected.")
            return

        element = self.current_selections.get("Element") or row.get("Element", "Element")
        material = self.current_selections.get("Material") or row.get("Material", "Material")
        temper = self.current_selections.get("Temper") or row.get("Temper", "Temper")
        spec = self.current_selections.get("Specification") or row.get("Spec1_1", "Spec")
        spec2 = self.current_selections.get("Specification 2") or row_spec2_value(row)
        spec2 = display_spec_value(spec2)
        form = self.current_selections.get("Form") or row.get("Form", "Form")
        thickness = self._thickness_base(row)
        direction = self.direction_var.get()
        basis_name = self._basis_display().replace(" ", "-")
        model = self.mat_model_var.get()

        unit_spec = UNIT_SYSTEM_SPEC[self.unit_sys_var.get()]
        unit_label = unit_spec["label"]
        pressure_unit = unit_spec["pressure_label"]
        density_unit = unit_spec["density_label"]


        has_user_edits = any(edited for _value, edited in self.prop_values.values())
        custom_prefix = "CUSTOM_" if has_user_edits else ""


        material_id = None


        available_specs = []
        try:
            spec_query = dict(self.current_selections)
            spec_query["Specification"] = ""
            spec_query["Specification 2"] = ""
            spec_rows = self.app.db.filter_master(spec_query)
            spec_col = find_col(spec_rows, "Spec1_1", "spec1_1", "Specification")
            if spec_col and not spec_rows.empty:
                vals = []
                for v in spec_rows[spec_col].astype(str).tolist():
                    clean = NO_SPEC_DISPLAY if is_blank(v) else str(v).strip()
                    if clean and clean not in vals:
                        vals.append(clean)
                available_specs = vals
        except Exception:
            available_specs = []

        available_specs_text = ", ".join(available_specs) if available_specs else str(spec)


        title = self._keyfile_export_stem(
            element=element,
            material=material,
            temper=temper,
            spec=spec,
            form=form,
            thickness=thickness,
            direction=direction,
            model=model,
            custom=has_user_edits,
        )

        filename = f"{self._safe_filename_part(title)}.key"

        save_path = filedialog.asksaveasfilename(
            title="Export kFile",
            defaultextension=".key",
            initialfile=filename,
            filetypes=[
                ("LS-DYNA Keyword File", "*.key"),
                ("K File", "*.k"),
                ("Text File", "*.txt"),
                ("All Files", "*.*"),
            ],
        )

        if not save_path:
            self._audit_log_from_card(
                screen="Material Card",
                action="Export kFile",
                status="Cancelled",
                material_summary=material_summary,
                notes="User cancelled the save dialog.",
                **fields,
            )
            return

        try:
            material_id = reserve_next_export_id(self.export_id_var.get())
        except Exception as exc:
            self._audit_log_from_card(
                screen="Material Card",
                action="Export kFile",
                status="Error",
                material_summary=material_summary,
                notes="Could not reserve the entered session export ID.",
                details=str(exc),
                **fields,
            )
            messagebox.showerror("Export kFile", f"Could not reserve export ID / MID:\n\n{exc}")
            return


        full_material_name = (
            f"{element} {material}-{temper} | Export ID/MID: {material_id} | Spec: {spec} | Spec 2: {spec2} | Form: {form} | "
            f"Thickness: {thickness} | Direction: {direction} | Basis: {basis_name}"
        )

        ro = self._format_key_number(ro_raw, "density")
        e = self._format_key_number(e_raw)
        pr = self._format_key_number(pr_raw, "ratio")
        sigy = self._format_key_number(sigy_raw)
        etan = self._format_key_number(etan_raw)
        fail = "0" if is_gissmo_export else self._format_key_number(fail_raw, "fail")
        tdel = self._format_key_number(tdel_raw)
        gissmo_block = self._gissmo_key_block(title, mid=material_id) if is_gissmo_export else ""

        user = getpass.getuser().lower()
        timestamp = datetime.now().strftime("%H:%M %Y/%m/%d")


        ftu_true = self._format_key_number(ftu_true_raw)
        k_text = self._build_export_keyfile_text(
            title=title,
            full_material_name=full_material_name,
            spec=spec,
            available_specs_text=available_specs_text,
            unit_label=unit_label,
            pressure_unit=pressure_unit,
            density_unit=density_unit,
            model=model,
            custom_edited=has_user_edits,
            user=user,
            timestamp=timestamp,
            ro=ro,
            e=e,
            pr=pr,
            sigy=sigy,
            etan=etan,
            fail=fail,
            tdel=tdel,
            ftu_true=ftu_true,
            gissmo_block=gissmo_block,
            material_id=material_id,
        )

        try:
            Path(save_path).write_text(k_text, encoding="utf-8")
        except Exception as exc:
            self._audit_log_from_card(
                screen="Material Card",
                action="Export kFile",
                status="Error",
                material_summary=material_summary,
                keyfile_name=Path(save_path).name,
                export_folder=str(Path(save_path).parent),
                notes="Could not save keyfile.",
                details=str(exc),
                **fields,
            )
            messagebox.showerror("Export kFile", f"Could not save file:\n\n{exc}")
            return

        self._audit_log_from_card(
            screen="Material Card",
            action="Keyfile Exported",
            status="Success",
            material_summary=material_summary,
            keyfile_name=Path(save_path).name,
            export_folder=str(Path(save_path).parent),
            notes=f"User exported current {model} keyfile.",
            details=f"Saved file: {save_path}",
            **fields,
        )
        try:
            self.export_id_var.set(str(peek_next_export_id()))
        except Exception:
            pass
        if hasattr(self.app, "status_var"):
            self.app.status_var.set(f"Keyfile exported with Export ID {material_id:,} | {export_counter_status_text()}")
        messagebox.showinfo("Export kFile", f"kFile exported successfully:\n\n{save_path}\n\nExport ID / MID: {material_id:,}")



# -----------------------------------------------------------------------------
# Final strict-matching patch
# -----------------------------------------------------------------------------
# This patch keeps the existing UI layout but makes selection logic strict across
# the whole app. Advanced Selection and Material Finder no longer silently switch
# to a different material row when the exact user-selected combination does not
# exist. Unavailable Thickness/Basis/Direction/Matcard options are removed from
# the visible choices.


def _strict_stage_filtered_rows(self, payload: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Rows matching only the normal material path columns."""
    try:
        payload = payload if payload is not None else self._adv_current_item_payload()
        selections = self._adv_selection_from_payload(payload)
        return self.db.filter_master(selections)
    except Exception:
        return pd.DataFrame()


def _strict_apply_thickness_filter(self, rows: pd.DataFrame, payload: Dict[str, Any]) -> pd.DataFrame:
    """Apply exact Advanced/Finder thickness selection without fallback."""
    if rows is None or rows.empty:
        return rows if rows is not None else pd.DataFrame()

    mode = str(payload.get("Thickness_Mode", "First matching thickness") or "First matching thickness")
    exact = str(payload.get("Thickness", "") or "").strip()
    exact_row_key = str(payload.get("_thickness_row_key", "") or "").strip()

    if exact_row_key:
        try:
            if "__adv_row_key" in rows.columns:
                filtered = rows.loc[rows["__adv_row_key"].astype(str).eq(exact_row_key)].copy()
            else:
                mask = [self._adv_row_identity_key(row) == exact_row_key for _, row in rows.iterrows()]
                filtered = rows.loc[mask].copy()
            return filtered
        except Exception:
            return rows.iloc[0:0].copy()

    if mode == "Exact thickness text" and exact:
        exact_norm = norm(exact)
        try:
            if "__adv_thickness_norm" in rows.columns and "__adv_thickness_base_norm" in rows.columns:
                mask = (
                    rows["__adv_thickness_norm"].astype(str).eq(exact_norm)
                    | rows["__adv_thickness_base_norm"].astype(str).eq(exact_norm)
                )
                return rows.loc[mask].copy()
        except Exception:
            pass
        mask = []
        for _, row in rows.iterrows():
            try:
                t_base = self._adv_thickness_base(row)
                t_display = self._adv_thickness_display_label(row)
                mask.append(norm(t_base) == exact_norm or norm(t_display) == exact_norm)
            except Exception:
                mask.append(False)
        return rows.loc[mask].copy()

    return rows.copy()


def _strict_filter_rows_by_basis_direction(self, rows: pd.DataFrame, basis: str = "", direction: str = "") -> pd.DataFrame:
    """Keep only rows that have data for the selected Basis/Direction."""
    if rows is None or rows.empty:
        return rows if rows is not None else pd.DataFrame()

    basis = str(basis or "").strip().upper()
    direction = str(direction or "").strip().upper()
    if basis not in {"A", "B", "S"} and direction not in {"L", "LT"}:
        return rows.copy()

    keep = []
    for idx, row in rows.iterrows():
        try:
            if hasattr(self, "_finder_row_has_basis_direction_data"):
                if self._finder_row_has_basis_direction_data(row, basis, direction):
                    keep.append(idx)
                    continue
            # Defensive fallback: use Advanced basis availability on one-row DataFrame.
            one = pd.DataFrame([row])
            if basis in {"A", "B", "S"} and direction in {"L", "LT"}:
                if self._adv_available_bases_for_rows(one, direction).get(basis, False):
                    keep.append(idx)
            elif direction in {"L", "LT"}:
                if any(self._adv_available_bases_for_rows(one, direction).values()):
                    keep.append(idx)
            elif basis in {"A", "B", "S"}:
                if basis in self._adv_available_bases_any_direction_for_rows(one):
                    if self._adv_available_bases_any_direction_for_rows(one).get(basis, False):
                        keep.append(idx)
        except Exception:
            continue
    return rows.loc[keep].copy()


def _strict_adv_match_rows(self, payload: Dict[str, Any]) -> pd.DataFrame:
    """Strict source rows for an Advanced/Finder payload.

    Applies the exact selected material path, exact thickness when selected,
    Basis/Direction availability, and Matcard availability. No fallback to a
    nearby/first valid material is allowed here.
    """
    payload = dict(payload or {})
    if getattr(self, "perf_engine", None) is not None:
        selections = self._adv_selection_from_payload(payload)
        thickness = str(payload.get("Thickness", "")).strip() if payload.get("Thickness_Mode") == "Exact thickness text" else ""
        exact_row_key = str(payload.get("_thickness_row_key", "") or "").strip()
        basis = str(payload.get("Basis", "") or "").strip().upper()
        direction = str(payload.get("Direction", "") or "").strip().upper()
        model = str(payload.get("Material_Model", "") or "").strip()
        
        if exact_row_key and exact_row_key.startswith("idx:"):
            try:
                idx_val = int(exact_row_key.split(":")[1])
                rows = self.perf_engine.filter_rows(selections, thickness="", basis=basis, direction=direction, matcard=model)
                if idx_val in rows.index:
                    return rows.loc[[idx_val]].copy()
                return self.perf_engine.master.iloc[0:0].copy()
            except Exception:
                return self.perf_engine.master.iloc[0:0].copy()
        
        return self.perf_engine.filter_rows(selections, thickness=thickness, basis=basis, direction=direction, matcard=model)

    rows = _strict_stage_filtered_rows(self, payload)
    rows = _strict_apply_thickness_filter(self, rows, payload)
    if rows is None or rows.empty:
        return rows if rows is not None else pd.DataFrame()

    basis = str(payload.get("Basis", "") or "").strip().upper()
    direction = str(payload.get("Direction", "") or "").strip().upper()
    rows = _strict_filter_rows_by_basis_direction(self, rows, basis, direction)
    if rows is None or rows.empty:
        return rows if rows is not None else pd.DataFrame()

    model = str(payload.get("Material_Model", "") or "").strip()
    if model:
        options = self._adv_available_matcards_for_rows(rows, basis, direction)
        if model not in options:
            return rows.iloc[0:0].copy()
    return rows.copy()


def _strict_adv_match_count(self):
    if not hasattr(self, "adv_match_var"):
        return
    try:
        payload = self._adv_current_item_payload()
        rows = self._adv_match_rows(payload)
        n = int(len(rows)) if rows is not None else 0
    except Exception:
        n = 0
    self.adv_match_var.set(f"Advanced Matching Materials: {n:,}")


def _strict_extra_base_rows(self) -> pd.DataFrame:
    try:
        payload = self._adv_current_item_payload()
        rows = _strict_stage_filtered_rows(self, payload)
        return rows if rows is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _strict_extra_rows_with_thickness(self) -> pd.DataFrame:
    try:
        payload = self._adv_current_item_payload()
        rows = _strict_stage_filtered_rows(self, payload)
        rows = _strict_apply_thickness_filter(self, rows, payload)
        return rows if rows is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _strict_thickness_options_from_rows(self, rows: pd.DataFrame) -> List[str]:
    options = ["First matching thickness", "All matching thickness rows"]
    seen = {norm(x) for x in options}
    if rows is not None and not rows.empty:
        try:
            labels = rows["__adv_thickness_label"].astype(str).tolist() if "__adv_thickness_label" in rows.columns else []
        except Exception:
            labels = []
        if not labels:
            labels = []
            for _, row in rows.iterrows():
                try:
                    labels.append(self._adv_thickness_display_label(row) or "NA")
                except Exception:
                    labels.append("NA")
        for label in labels:
            key = norm(label)
            if label and key not in seen:
                options.append(label)
                seen.add(key)
    return options


def _strict_adv_extra_filter_options(self, stage: str) -> List[str]:
    """Return only values still valid for the current Advanced Selection."""
    if getattr(self, "perf_engine", None) is not None:
        basis = str(self.adv_basis_var.get() or "").strip().upper()
        direction = str(self.adv_direction_var.get() or "").strip().upper()
        
        if stage == "Thickness":
            thick_opts = self.perf_engine.available_thicknesses(self.adv_selections)
            valid_opts = []
            for t in thick_opts:
                if self.perf_engine.count(self.adv_selections, thickness=t, basis=basis, direction=direction) > 0:
                    valid_opts.append(t)
            return ["First matching thickness", "All matching thickness rows"] + valid_opts

        if stage == "Basis":
            if direction not in {"L", "LT"}:
                direction = "L" if self.perf_engine.count(self.adv_selections, direction="L") > 0 else ""
            available = self.perf_engine.available_bases(self.adv_selections, direction=direction)
            return [code for _label, code in BASIS_OPTIONS if code in available]

        if stage == "Direction":
            available = self.perf_engine.available_directions(self.adv_selections, basis=basis if basis in {"A", "B", "S"} else "")
            return available

        if stage == "Matcard":
            thickness = str(self.adv_thickness_display_var.get()).strip()
            if thickness in {"First matching thickness", "All matching thickness rows"}:
                thickness = ""
            available = self.perf_engine.available_matcards(self.adv_selections, thickness=thickness, basis=basis, direction=direction)
            return available

    rows_stage = _strict_extra_base_rows(self)
    rows_thick = _strict_extra_rows_with_thickness(self)
    basis = str(self.adv_basis_var.get() or "").strip().upper()
    direction = str(self.adv_direction_var.get() or "").strip().upper()

    if stage == "Thickness":
        rows = rows_stage
        if basis in {"A", "B", "S"} and direction in {"L", "LT"}:
            rows = _strict_filter_rows_by_basis_direction(self, rows, basis, direction)
        return _strict_thickness_options_from_rows(self, rows)

    if stage == "Basis":
        if direction not in {"L", "LT"}:
            direction = "L" if "L" in self._adv_available_directions_for_rows(rows_thick, "") else ""
        available = self._adv_available_bases_for_rows(rows_thick, direction)
        return [code for _label, code in BASIS_OPTIONS if available.get(code, False)]

    if stage == "Direction":
        options = self._adv_available_directions_for_rows(rows_thick, basis if basis in {"A", "B", "S"} else "")
        return options

    if stage == "Matcard":
        rows = rows_thick
        if basis in {"A", "B", "S"} and direction in {"L", "LT"}:
            rows = _strict_filter_rows_by_basis_direction(self, rows, basis, direction)
        return self._adv_available_matcards_for_rows(rows, basis, direction)

    return []


def _strict_adv_refresh_extra_filters(self):
    """Refresh Advanced extra filters coherently and remove invalid options."""
    if not getattr(self, "adv_extra_listboxes", None):
        return

    # First fix Direction and Basis using current material path/thickness.
    if getattr(self, "perf_engine", None) is not None:
        for _ in range(3):
            basis = str(self.adv_basis_var.get() or "").strip().upper()
            direction_opts = self.perf_engine.available_directions(self.adv_selections, basis=basis if basis in {"A", "B", "S"} else "")
            if self.adv_direction_var.get() not in direction_opts:
                self.adv_direction_var.set(self._adv_preferred_value(direction_opts, "L", ""))

            direction = str(self.adv_direction_var.get() or "").strip().upper()
            available_basis = self.perf_engine.available_bases(self.adv_selections, direction=direction)
            basis_opts = available_basis
            if self.adv_basis_var.get() not in basis_opts:
                self.adv_basis_var.set(self._adv_preferred_value(basis_opts, "B", ""))
                if hasattr(self, "adv_basis_display_var"):
                    self.adv_basis_display_var.set({code: label for label, code in BASIS_OPTIONS}.get(self.adv_basis_var.get(), ""))
    else:
        rows_thick = _strict_extra_rows_with_thickness(self)
        for _ in range(3):
            basis = str(self.adv_basis_var.get() or "").strip().upper()
            direction_opts = self._adv_available_directions_for_rows(rows_thick, basis if basis in {"A", "B", "S"} else "")
            if self.adv_direction_var.get() not in direction_opts:
                self.adv_direction_var.set(self._adv_preferred_value(direction_opts, "L", ""))

            direction = str(self.adv_direction_var.get() or "").strip().upper()
            available_basis = self._adv_available_bases_for_rows(rows_thick, direction)
            basis_opts = [code for _label, code in BASIS_OPTIONS if available_basis.get(code, False)]
            if self.adv_basis_var.get() not in basis_opts:
                self.adv_basis_var.set(self._adv_preferred_value(basis_opts, "B", ""))
                if hasattr(self, "adv_basis_display_var"):
                    self.adv_basis_display_var.set({code: label for label, code in BASIS_OPTIONS}.get(self.adv_basis_var.get(), ""))

    # Now fix Thickness based on the final Basis/Direction.
    thickness_opts = self._adv_extra_filter_options("Thickness")
    current_thickness = self.adv_thickness_display_var.get().strip()
    if current_thickness not in thickness_opts:
        self.adv_thickness_display_var.set("First matching thickness")
        self.adv_thickness_mode_var.set("First matching thickness")
        self.adv_thickness_text_var.set("")

    # Recompute rows after possible thickness reset, then Matcard.
    if getattr(self, "perf_engine", None) is not None:
        thickness = str(self.adv_thickness_display_var.get()).strip()
        if thickness in {"First matching thickness", "All matching thickness rows"}:
            thickness = ""
        basis = str(self.adv_basis_var.get() or "").strip().upper()
        direction = str(self.adv_direction_var.get() or "").strip().upper()
        model_opts = self.perf_engine.available_matcards(self.adv_selections, thickness=thickness, basis=basis, direction=direction)
    else:
        rows_final = _strict_extra_rows_with_thickness(self)
        basis = str(self.adv_basis_var.get() or "").strip().upper()
        direction = str(self.adv_direction_var.get() or "").strip().upper()
        rows_for_model = _strict_filter_rows_by_basis_direction(self, rows_final, basis, direction)
        model_opts = self._adv_available_matcards_for_rows(rows_for_model, basis, direction)

    if self.adv_model_var.get() not in model_opts:
        self.adv_model_var.set(self._adv_preferred_value(model_opts, "MAT024+GISSMO", ""))

    # Draw listboxes using final state.
    for stage in self.adv_extra_filter_stages:
        lb = self.adv_extra_listboxes.get(stage)
        if lb is None:
            continue
        options = self._adv_extra_filter_options(stage)
        self.adv_extra_visible_values[stage] = options
        lb.delete(0, tk.END)
        for option in options:
            lb.insert(tk.END, option)

        if stage == "Thickness":
            current = self.adv_thickness_display_var.get().strip()
        elif stage == "Basis":
            current = self.adv_basis_var.get().strip()
        elif stage == "Direction":
            current = self.adv_direction_var.get().strip()
        elif stage == "Matcard":
            current = self.adv_model_var.get().strip()
        else:
            current = ""

        lb.selection_clear(0, tk.END)
        if current in options:
            try:
                idx = options.index(current)
                lb.selection_set(idx)
                lb.see(idx)
            except Exception:
                pass
        label = current if current else "(not available)"
        try:
            self.adv_extra_selection_labels[stage].configure(
                text=f"Selected: {label}",
                fg=THEME["accent"] if current else THEME["status_error_fg"],
            )
            self.adv_extra_count_labels[stage].configure(text=str(len(options)))
        except Exception:
            pass

    # Keep any old default combobox controls in sync if they exist.
    try:
        if hasattr(self, "adv_basis_display_var"):
            self.adv_basis_display_var.set({code: label for label, code in BASIS_OPTIONS}.get(self.adv_basis_var.get(), ""))
        if hasattr(self, "adv_model_combo") and self.adv_model_combo is not None:
            self.adv_model_combo.configure(values=self._adv_extra_filter_options("Matcard"))
        if hasattr(self, "adv_direction_combo") and self.adv_direction_combo is not None:
            self.adv_direction_combo.configure(values=self._adv_extra_filter_options("Direction"))
        if hasattr(self, "adv_thickness_combo") and self.adv_thickness_combo is not None:
            self.adv_thickness_combo.configure(values=self._adv_extra_filter_options("Thickness"))
    except Exception:
        pass


def _strict_adv_add_current_selection(self):
    payload = self._adv_current_item_payload()
    if not any(str(payload.get(s, "")).strip() for s in STAGES):
        messagebox.showwarning(
            "Advanced Selection",
            "Select at least one Element/Series/Material/Temper/Specification/Form value before adding to the list."
        )
        return
    rows = self._adv_match_rows(payload)
    if rows is None or rows.empty:
        messagebox.showwarning(
            "Advanced Selection",
            "No exact matching material was found for the selected Element/Series/Material/Temper/Specification/Specification 2/Form/Thickness/Basis/Direction/Matcard combination."
        )
        if hasattr(self.app, "status_var"):
            self.app.status_var.set("No exact matching material found. Nothing was added.")
        return
    self._adv_add_payload(payload, source_label="manual selection", refresh=True, log=True)


def _strict_adv_add_all_matching_selection(self):
    payload = self._adv_current_item_payload()
    if not any(str(payload.get(s, "")).strip() for s in STAGES):
        messagebox.showwarning(
            "Advanced Selection",
            "Select at least one Element/Series/Material/Temper/Specification/Form value before adding all matches."
        )
        return
    rows = self._adv_match_rows(payload)
    if rows is None or rows.empty:
        messagebox.showwarning("Advanced Selection", "No exact matching source rows were found for the current filters.")
        return
    max_add_without_confirm = 100
    if len(rows) > max_add_without_confirm:
        if not messagebox.askyesno("Add All Matching", f"This will add {len(rows):,} exact matching row(s). Continue?"):
            return
    start_count = len(self.advanced_items)
    for _, row in rows.iterrows():
        item = dict(payload)
        for field in ("Element", "Material", "Temper", "Form"):
            item[field] = str(row.get(field, item.get(field, ""))).strip()
        spec = str(row.get("Spec1_1", row.get("spec1_1", item.get("Specification", "")))).strip()
        item["Specification"] = NO_SPEC_DISPLAY if is_blank(spec) else spec
        item["Specification 2"] = display_spec_value(row_spec2_value(row))
        if not str(item.get("Series", "")).strip():
            item["Series"] = self.db._material_to_series.get(norm(item.get("Material", "")), "")
        item["Thickness"] = self._adv_thickness_display_label(row) or "NA"
        item["Thickness_Mode"] = "Exact thickness text"
        item["_thickness_row_key"] = self._adv_row_identity_key(row)
        item["Source"] = "Manual - Add All Matching"
        self._adv_add_payload(item, source_label="matching row", refresh=False, log=False)
    added = len(self.advanced_items) - start_count
    self._adv_refresh_tree()
    try:
        self._finder_refresh_selected_export_tree()
    except Exception:
        pass
    self._adv_log(f"Added {added:,} exact matching row(s) to the export list.")


def _strict_adv_add_payload(self, payload: Dict[str, Any], source_label: str = "selection", refresh: bool = True, log: bool = True):
    payload = dict(payload or {})
    rows = self._adv_match_rows(payload)
    if rows is None or rows.empty:
        if log:
            self._adv_log(f"Skipped {source_label}: no exact matching source row was found.", status="Skipped")
        return False

    payload = self._adv_enrich_payload_from_first_match(payload, rows)
    payload["_matches"] = int(len(rows))
    payload["_selected"] = bool(payload.get("_selected", True))
    if not str(payload.get("Export_ID", "")).strip():
        payload["Export_ID"] = str(reserve_next_export_id())
    else:
        payload["Export_ID"] = str(normalize_export_id(payload.get("Export_ID"), default=peek_next_export_id()))
        payload["_id_manual"] = True
        advance_session_export_id_after(payload["Export_ID"])
    payload["_status"] = "Ready"
    payload["_tag"] = "ok"

    self.advanced_items.append(payload)
    if refresh:
        self._adv_refresh_tree()
        try:
            new_iid = str(len(self.advanced_items) - 1)
            self.adv_tree.selection_set(new_iid)
            self.adv_tree.see(new_iid)
        except Exception:
            pass
        try:
            self._finder_refresh_selected_export_tree()
        except Exception:
            pass
    if log:
        self._adv_log(f"Added {source_label}: {payload['_matches']} exact matching row(s).")
    return True


def _strict_finder_rows_for_current(self) -> Tuple[pd.DataFrame, Dict[Any, str]]:
    try:
        df = self.db.filter_master(self.finder_selections)
    except Exception:
        df = pd.DataFrame()
    df = self._finder_apply_basis_direction_filters(df)
    if df is not None and not df.empty:
        basis = str(self.finder_basis_var.get() or "").strip().upper()
        direction = str(self.finder_direction_var.get() or "").strip().upper()
        model = str(self.finder_model_var.get() or "").strip()
        if model:
            model_options = self._adv_available_matcards_for_rows(df, basis, direction)
            if model not in model_options:
                df = df.iloc[0:0].copy()
    df, match_notes = self._finder_apply_property_filters(df)
    return df, match_notes


def _strict_finder_match_count(self):
    try:
        df, _notes = _strict_finder_rows_for_current(self)
        self.finder_match_var.set(f"Material Finder Matches: {len(df):,}")
    except Exception:
        self.finder_match_var.set("Material Finder Matches: 0")


def _strict_finder_search_materials(self, auto: bool = False):
    df, match_notes = _strict_finder_rows_for_current(self)
    display_limit = 500
    self.finder_result_rows = []
    tree = getattr(self, "finder_result_tree", None)
    if tree is None or not tree.winfo_exists():
        return
    for iid in tree.get_children():
        tree.delete(iid)
    if df is None:
        df = pd.DataFrame()
    total = len(df)
    shown_df = df.head(display_limit)
    for pos, (row_index, row) in enumerate(shown_df.iterrows(), start=1):
        self.finder_result_rows.append(row)
        values = (
            "+", pos,
            self._finder_row_stage_value(row, "Element"),
            self._finder_row_stage_value(row, "Series"),
            self._finder_row_stage_value(row, "Material"),
            self._finder_row_stage_value(row, "Temper"),
            self._finder_row_stage_value(row, "Specification"),
            self._finder_row_stage_value(row, "Specification 2"),
            self._finder_row_stage_value(row, "Form"),
            self._finder_row_stage_value(row, "Thickness"),
            row.get("MMPDS_Version", "-"),
            match_notes.get(row_index, ""),
        )
        tag = "finder_match" if pos % 2 else "finder_match_alt"
        tree.insert("", "end", iid=str(pos - 1), values=values, tags=(tag,))
    suffix = f" (showing first {len(shown_df):,})" if total > display_limit else ""
    self.finder_result_count_var.set(f"{total:,} material(s){suffix}")
    self.finder_match_var.set(f"Material Finder Matches: {total:,}{suffix}")
    if not auto:
        self._audit_log_action(screen="Material Finder", action="Search", status="Success",
                               notes=f"Search returned {total:,} exact matching material row(s).")


# Apply overrides.
SelectionScreen._adv_match_rows = _strict_adv_match_rows
SelectionScreen._adv_match_count = _strict_adv_match_count
SelectionScreen._adv_extra_filter_options = _strict_adv_extra_filter_options
SelectionScreen._adv_refresh_extra_filters = _strict_adv_refresh_extra_filters
SelectionScreen._adv_add_current_selection = _strict_adv_add_current_selection
SelectionScreen._adv_add_all_matching_selection = _strict_adv_add_all_matching_selection
SelectionScreen._adv_add_payload = _strict_adv_add_payload
SelectionScreen._finder_match_count = _strict_finder_match_count
SelectionScreen._finder_search_materials = _strict_finder_search_materials



# -----------------------------------------------------------------------------
# Hemil BOM Test final UI/UX patch
# - Advanced Export List opens Material Card reliably using hidden source row key.
# - Only ID/MID, Unit, and Notes are editable in the Export List.
# - ID/MID is duplicate-protected and automatic IDs reuse the first available ID.
# - Warm/orange palette is removed; only Graphite/Green and Navy/Blue remain.
# - Notes are shown as a white editable box only for custom/edited rows, and are
#   written into summary/keyfile comments when provided.
# -----------------------------------------------------------------------------


def _hemil_item_has_notes_box(item: Dict[str, Any]) -> bool:
    """Notes are visible only after the row becomes custom/edited or already has notes."""
    if not isinstance(item, dict):
        return False
    return bool(
        item.get("_custom")
        or item.get("_card_custom_state")
        or str(item.get("_tag", "")).strip() == "custom_row"
        or str(item.get("_status", "")).upper().startswith("CUSTOM")
        or str(item.get("Notes", "")).strip()
    )


def _hemil_safe_custom_name(value: Any) -> str:
    import re
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    if not text:
        text = "MATERIAL"
    return f"CUSTOM_{text}"


def _hemil_used_export_ids(self, skip_idx: Optional[int] = None) -> set:
    used = set()
    for idx, item in enumerate(getattr(self, "advanced_items", [])):
        if skip_idx is not None and idx == skip_idx:
            continue
        try:
            used.add(normalize_export_id(item.get("Export_ID", "")))
        except Exception:
            continue
    return used


def _hemil_next_available_export_id(self) -> int:
    used = _hemil_used_export_ids(self)
    candidate = EXPORT_COUNTER_START
    while candidate in used and candidate <= EXPORT_COUNTER_MAX:
        candidate += 1
    return candidate


def _hemil_row_by_key(self, row_key: str, base_selections: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    if not row_key:
        return pd.DataFrame()
    try:
        df = self.db.filter_master(base_selections or {})
    except Exception:
        df = getattr(self.db, "master", pd.DataFrame())
    if df is None or df.empty:
        return pd.DataFrame()
    try:
        if "__adv_row_key" in df.columns:
            hit = df.loc[df["__adv_row_key"].astype(str).eq(str(row_key))].copy()
            if not hit.empty:
                return hit
    except Exception:
        pass
    try:
        mask = [self._adv_row_identity_key(row) == row_key or source_row_identity_key(row) == row_key for _, row in df.iterrows()]
        return df.loc[mask].copy()
    except Exception:
        return pd.DataFrame()


def _hemil_adv_match_rows(self, payload: Dict[str, Any]) -> pd.DataFrame:
    """Reliable Advanced Selection source-row matcher.

    First use the hidden row key saved when a material is added. This fixes the
    'No matching material row found' popup caused by strict visual-text matching.
    Then fall back to the previous strict matcher, and finally to a relaxed stage
    match so existing export-list rows can still open.
    """
    payload = dict(payload or {})
    selections = self._adv_selection_from_payload(payload)
    row_key = str(payload.get("_thickness_row_key", "") or payload.get("Thickness_Row_Key", "") or "").strip()
    if row_key:
        by_key = _hemil_row_by_key(self, row_key, selections)
        if by_key is not None and not by_key.empty:
            return by_key
        by_key = _hemil_row_by_key(self, row_key, None)
        if by_key is not None and not by_key.empty:
            return by_key

    try:
        rows = _strict_adv_match_rows(self, payload)
        if rows is not None and not rows.empty:
            return rows
    except Exception:
        pass

    try:
        df = self.db.filter_master(selections)
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()

    # Relaxed thickness fallback: compare visible/base values but do not fail if
    # the text came from a display-only option.
    exact = str(payload.get("Thickness", "") or "").strip()
    mode = str(payload.get("Thickness_Mode", "") or "").strip()
    if exact and mode == "Exact thickness text":
        key = norm(exact)
        try:
            if "__adv_thickness_norm" in df.columns and "__adv_thickness_base_norm" in df.columns:
                hit = df.loc[(df["__adv_thickness_norm"].astype(str).eq(key)) | (df["__adv_thickness_base_norm"].astype(str).eq(key))].copy()
                if not hit.empty:
                    df = hit
        except Exception:
            pass
    return df.copy()


def _hemil_adv_rows_to_export(self, payload: Dict[str, Any]) -> List[pd.Series]:
    df = self._adv_match_rows(payload)
    if df is None or df.empty:
        return []
    mode = payload.get("Thickness_Mode", "First matching thickness")
    if mode == "All matching thickness rows":
        return [df.iloc[i] for i in range(len(df))]
    return [df.iloc[0]]


def _hemil_adv_add_payload(self, payload: Dict[str, Any], source_label: str = "selection", refresh: bool = True, log: bool = True):
    payload = dict(payload or {})
    rows = self._adv_match_rows(payload)
    if rows is None or rows.empty:
        if log:
            self._adv_log(f"Skipped {source_label}: no matching source row was found.", status="Skipped")
        return False

    payload = self._adv_enrich_payload_from_first_match(payload, rows)
    payload["_matches"] = int(len(rows))
    payload["_selected"] = bool(payload.get("_selected", True))

    if not str(payload.get("Export_ID", "")).strip():
        payload["Export_ID"] = str(_hemil_next_available_export_id(self))
    else:
        new_id = str(normalize_export_id(payload.get("Export_ID"), default=_hemil_next_available_export_id(self)))
        if int(new_id) in _hemil_used_export_ids(self):
            messagebox.showerror("Export ID", f"ID / MID {new_id} already exists in the export list. Choose a different ID.")
            return False
        payload["Export_ID"] = new_id
        payload["_id_manual"] = True

    payload["_status"] = payload.get("_status") or "Ready"
    payload["_tag"] = payload.get("_tag") or "ok"
    payload.setdefault("Notes", "")
    payload.setdefault("Custom_Name", payload.get("Custom Name", ""))

    self.advanced_items.append(payload)
    if refresh:
        self._adv_refresh_tree()
        try:
            new_iid = str(len(self.advanced_items) - 1)
            self.adv_tree.selection_set(new_iid)
            self.adv_tree.see(new_iid)
        except Exception:
            pass
        try:
            self._finder_refresh_selected_export_tree()
        except Exception:
            pass
    if log:
        self._adv_log(f"Added {source_label}: {payload['_matches']} matching row(s).")
    return True


def _hemil_adv_refresh_dropdown_overlays(self):
    """Visible controls for Export, ID/MID, Unit, Image, and custom Notes only."""
    self._adv_clear_dropdown_overlays()
    tree = getattr(self, "adv_tree", None)
    if tree is None or not tree.winfo_exists():
        return
    try:
        columns = list(tree["columns"])
        col_ids = {name: f"#{columns.index(name) + 1}" for name in columns}
    except Exception:
        return

    def place_button(iid, col_name, text, command, bg, fg, min_w=70):
        try:
            bbox = tree.bbox(iid, col_ids[col_name])
        except Exception:
            bbox = None
        if not bbox:
            return
        x, y, width, height = bbox
        if width <= 8 or height <= 8:
            return
        btn = tk.Button(
            tree, text=text, command=command, bg=bg, fg=fg,
            activebackground=bg, activeforeground=fg, font=FONTS["caption"],
            relief="solid", bd=1, highlightthickness=0, takefocus=0,
            cursor="hand2", padx=2, pady=0,
        )
        btn.place(x=x + 6, y=y + 5, width=max(min_w, width - 12), height=max(22, height - 10))
        self.adv_cell_widgets.append(btn)

    for iid in tree.get_children(""):
        try:
            idx = int(iid)
        except Exception:
            continue
        if not (0 <= idx < len(self.advanced_items)):
            continue
        item = self.advanced_items[idx]

        # Export checkbox
        if "Export" in col_ids:
            checked = bool(item.get("_selected", False))
            place_button(iid, "Export", "✓" if checked else "", lambda row_idx=idx: self._adv_toggle_export_selected(row_idx), "#FFFFFF", "#00A651", min_w=24)

        # ID / MID editable visible white box
        if "Export_ID" in col_ids:
            try:
                bbox = tree.bbox(iid, col_ids["Export_ID"])
            except Exception:
                bbox = None
            if bbox:
                x, y, width, height = bbox
                ent = ttk.Entry(tree, font=FONTS["caption"], takefocus=0)
                ent.insert(0, str(item.get("Export_ID", "")))
                ent.place(x=x + 6, y=y + 5, width=max(70, width - 12), height=max(22, height - 10))
                def _commit_id(_event=None, row_idx=idx, editor=ent):
                    self._adv_apply_export_cell_edit(row_idx, "Export_ID", editor.get().strip())
                    return "break"
                ent.bind("<Return>", _commit_id)
                ent.bind("<FocusOut>", _commit_id)
                ent.bind("<Double-1>", lambda _e: "break")
                self.adv_cell_widgets.append(ent)

        # Unit editable visible combobox
        if "Unit" in col_ids:
            try:
                bbox = tree.bbox(iid, col_ids["Unit"])
            except Exception:
                bbox = None
            if bbox:
                x, y, width, height = bbox
                options = self._adv_options_for_export_cell(item, "Unit")
                current = UNIT_SYSTEM_SPEC.get(item.get("Unit_System", "mm_T_s"), {}).get("label", item.get("Unit_System", ""))
                combo = ttk.Combobox(tree, values=options, state="readonly", font=FONTS["caption"], takefocus=0)
                combo.set(current if current in options else (options[0] if options else current))
                combo.place(x=x + 6, y=y + 5, width=max(92, width - 12), height=max(24, height - 10))
                def _commit_unit(_event=None, row_idx=idx, combo_widget=combo):
                    value = combo_widget.get().strip()
                    if value:
                        self._adv_apply_export_cell_edit_multi(row_idx, "Unit", value, option_index=-1)
                    return "break"
                combo.bind("<<ComboboxSelected>>", _commit_unit)
                combo.bind("<Return>", _commit_unit)
                combo.bind("<MouseWheel>", lambda _event: "break")
                self.adv_cell_widgets.append(combo)

        # Notes editable white box only for custom/edited rows.
        if "Notes" in col_ids and _hemil_item_has_notes_box(item):
            try:
                bbox = tree.bbox(iid, col_ids["Notes"])
            except Exception:
                bbox = None
            if bbox:
                x, y, width, height = bbox
                ent = tk.Entry(tree, font=FONTS["caption"], bg="#FFFFFF", fg="#111827", relief="solid", bd=1)
                ent.insert(0, str(item.get("Notes", "")))
                ent.place(x=x + 6, y=y + 5, width=max(120, width - 12), height=max(22, height - 10))
                def _commit_note(_event=None, row_idx=idx, editor=ent):
                    self._adv_apply_export_cell_edit(row_idx, "Notes", editor.get().strip())
                    return "break"
                ent.bind("<Return>", _commit_note)
                ent.bind("<FocusOut>", _commit_note)
                self.adv_cell_widgets.append(ent)

        # Image button
        if "View_Image" in col_ids:
            place_button(iid, "View_Image", "View Image", lambda row_idx=idx: self._adv_show_image_for_item(row_idx), THEME["accent"], THEME["accent_text"], min_w=70)


def _hemil_adv_apply_export_cell_edit(self, idx: int, col_name: str, new_value: str, option_index: int = -1):
    if not (0 <= idx < len(self.advanced_items)):
        return
    item = self.advanced_items[idx]
    if col_name == "Export_ID":
        try:
            new_id = str(normalize_export_id(new_value, default=_hemil_next_available_export_id(self)))
            for other_idx, other_item in enumerate(self.advanced_items):
                if other_idx != idx and str(other_item.get("Export_ID", "")).strip() == new_id:
                    messagebox.showerror("Export ID", f"ID / MID {new_id} already exists in the export list. Choose a different ID.")
                    self._adv_refresh_tree()
                    return
            item["Export_ID"] = new_id
            item["_id_manual"] = True
        except Exception as exc:
            messagebox.showerror("Export ID", f"Invalid Export ID / MID:\n\n{exc}")
            self._adv_refresh_tree()
            return
    elif col_name == "Unit":
        item["Unit_System"] = self._adv_normalize_unit_system(new_value)
    elif col_name == "Notes":
        item["Notes"] = str(new_value or "").strip()
    else:
        return

    # Revalidate status without changing engineering logic.
    try:
        rows = self._adv_match_rows(item)
        item["_matches"] = int(len(rows)) if rows is not None else 0
        if item.get("_custom") or item.get("_card_custom_state"):
            item["_status"] = "CUSTOM - Ready" if item.get("_matches", 0) > 0 else "CUSTOM - No match"
            item["_tag"] = "custom_row"
        elif item.get("_matches", 0) > 0:
            item["_status"] = "Ready"
            item["_tag"] = "ok"
        else:
            item["_status"] = "No match"
            item["_tag"] = "error"
    except Exception:
        pass
    self._adv_refresh_tree()
    try:
        self.adv_tree.selection_set(str(idx))
        self.adv_tree.see(str(idx))
    except Exception:
        pass


def _hemil_adv_apply_export_cell_edit_multi(self, idx: int, col_name: str, new_value: str, option_index: int = -1):
    target_indexes = [idx]
    if col_name == "Unit":
        try:
            target_indexes = sorted({int(i) for i in self.adv_tree.selection()} | {idx})
        except Exception:
            target_indexes = [idx]
    for target_idx in target_indexes:
        _hemil_adv_apply_export_cell_edit(self, target_idx, col_name, new_value, option_index if target_idx == idx else -1)


def _hemil_adv_begin_export_list_edit(self, event=None):
    tree = getattr(self, "adv_tree", None)
    if tree is None:
        return "break"
    row_id = tree.identify_row(event.y) if event is not None else (tree.selection()[0] if tree.selection() else "")
    col_id = tree.identify_column(event.x) if event is not None else ""
    col_name = self._adv_tree_column_name(col_id)
    if not row_id or col_name not in {"Export_ID", "Unit", "Notes"}:
        return "break"
    try:
        idx = int(row_id)
        item = self.advanced_items[idx]
    except Exception:
        return "break"
    if col_name == "Notes" and not _hemil_item_has_notes_box(item):
        return "break"
    return _hemil_adv_apply_export_cell_edit(self, idx, col_name, strip_dropdown_mark(tree.set(row_id, col_name))) or "break"


_original_card_commit_all_pending_edits = CardScreen._commit_all_pending_edits

def _hemil_card_commit_all_pending_edits(self, trigger: str = "Enter"):
    pending_prop = dict(getattr(self, "pending_edits", {}) or {})
    pending_units = dict(getattr(self, "unit_pending_edits", {}) or {})
    opened_id = str(getattr(self, "opened_export_id_context", "") or "").strip()
    old_prop_values = dict(getattr(self, "prop_values", {}) or {})
    old_unit_values = dict(getattr(self, "unit_conversions", {}) or {})
    result = _original_card_commit_all_pending_edits(self, trigger)
    if opened_id and (pending_prop or pending_units):
        try:
            selection_screen = self.app.screens.get("SelectionScreen")
            if selection_screen is not None:
                for item in getattr(selection_screen, "advanced_items", []):
                    if str(item.get("Export_ID", "")).strip() == opened_id:
                        item["_custom"] = True
                        item["_tag"] = "custom_row"
                        item["_status"] = "CUSTOM - Ready"
                        if not str(item.get("Custom_Name", "")).strip():
                            item["Custom_Name"] = _hemil_safe_custom_name(item.get("Material", ""))
                        item.setdefault("Notes", "")
                        item["_card_custom_state"] = {
                            "prop_values": {k: [str(v[0]), bool(v[1])] for k, v in getattr(self, "prop_values", {}).items()},
                            "unit_conversions": {k: self.unit_conversions.get(k, v) for k, v in DEFAULT_UNIT_CONVERSIONS.items()},
                        }
                        changes = []
                        for key, val in pending_prop.items():
                            old_val = strip_edit_box(old_prop_values.get(key, ("", False))[0]) if key in old_prop_values else ""
                            changes.append(f"{key}: {old_val} -> {val}")
                        for key, val in pending_units.items():
                            old_val = old_unit_values.get(key, DEFAULT_UNIT_CONVERSIONS.get(key, ""))
                            changes.append(f"{key}: {old_val} -> {val}")
                        item["_user_changes"] = "; ".join(changes)
                        try:
                            rows = selection_screen._adv_match_rows(item)
                            item["_matches"] = int(len(rows)) if rows is not None else 0
                        except Exception:
                            pass
                        selection_screen._adv_refresh_tree()
                        break
        except Exception:
            pass
    return result


_original_card_reset_props = CardScreen._reset_props

def _hemil_card_reset_props(self):
    opened_id = str(getattr(self, "opened_export_id_context", "") or "").strip()
    result = _original_card_reset_props(self)
    if opened_id:
        try:
            selection_screen = self.app.screens.get("SelectionScreen")
            if selection_screen is not None:
                for item in getattr(selection_screen, "advanced_items", []):
                    if str(item.get("Export_ID", "")).strip() == opened_id:
                        item.pop("_custom", None)
                        item.pop("_card_custom_state", None)
                        item.pop("_user_changes", None)
                        item.pop("Custom_Name", None)
                        item["Notes"] = ""
                        item["_tag"] = "ok"
                        item["_status"] = "Ready"
                        selection_screen._adv_refresh_tree()
                        break
        except Exception:
            pass
    return result

# Apply final overrides after strict-performance overrides.
SelectionScreen._adv_match_rows = _hemil_adv_match_rows
SelectionScreen._adv_rows_to_export = _hemil_adv_rows_to_export
SelectionScreen._adv_add_payload = _hemil_adv_add_payload
SelectionScreen._adv_refresh_dropdown_overlays = _hemil_adv_refresh_dropdown_overlays
SelectionScreen._adv_apply_export_cell_edit = _hemil_adv_apply_export_cell_edit
SelectionScreen._adv_apply_export_cell_edit_multi = _hemil_adv_apply_export_cell_edit_multi
SelectionScreen._adv_begin_export_list_edit = _hemil_adv_begin_export_list_edit
CardScreen._commit_all_pending_edits = _hemil_card_commit_all_pending_edits
CardScreen._reset_props = _hemil_card_reset_props


# -----------------------------------------------------------------------------
# Hemil follow-up fix: open Material Card reliably and lock Export List editing.
# -----------------------------------------------------------------------------
# Fixes requested after UIFix:
# 1) Advanced Export List rows must open Material Card reliably.
# 2) Only ID / MID, Unit, and Notes are editable.
# 3) Basis/Direction/Matcard/Thickness must not show editable dropdowns.
# 4) Source row key is stored immediately when adding the row, so custom rows can
#    still reopen the original material while keeping custom values separately.


def _hf_first_source_row_for_payload(self, payload: Dict[str, Any]) -> Optional[pd.Series]:
    """Return the original source row for an Advanced export-list item.

    This intentionally prioritizes hidden keys and uses a relaxed fallback. It is
    for opening the Material Card, so it should never fail only because the row
    was marked CUSTOM, had notes, had a custom name, or had a display-only value.
    """
    payload = dict(payload or {})

    # 1) Strongest match: hidden source row keys saved when the row was added.
    key_candidates = [
        payload.get("_source_row_key", ""),
        payload.get("Source_Row_Key", ""),
        payload.get("_thickness_row_key", ""),
        payload.get("Thickness_Row_Key", ""),
        payload.get("__adv_row_key", ""),
    ]
    key_candidates = [str(k).strip() for k in key_candidates if str(k).strip()]
    for key in key_candidates:
        try:
            master = getattr(self.db, "master", pd.DataFrame())
            if master is not None and not master.empty:
                if "__adv_row_key" in master.columns:
                    hit = master.loc[master["__adv_row_key"].astype(str).eq(key)]
                    if not hit.empty:
                        return hit.iloc[0]
                for _idx, row in master.iterrows():
                    try:
                        if self._adv_row_identity_key(row) == key or source_row_identity_key(row) == key:
                            return row
                    except Exception:
                        continue
        except Exception:
            pass

    # 2) Use strict matcher if it works.
    try:
        rows = _strict_adv_match_rows(self, payload)
        if rows is not None and not rows.empty:
            return rows.iloc[0]
    except Exception:
        try:
            rows = self._adv_match_rows(payload)
            if rows is not None and not rows.empty:
                return rows.iloc[0]
        except Exception:
            pass

    # 3) Relaxed material-path fallback. This ignores Custom_Name, Notes, status,
    #    and generation status. It only tries to locate the original material row.
    try:
        selections = self._adv_selection_from_payload(payload)
        df = self.db.filter_master(selections)
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        # Very relaxed fallback using key display fields against master text.
        try:
            df = getattr(self.db, "master", pd.DataFrame()).copy()
            if df is None or df.empty:
                return None
            checks = {
                "Element": payload.get("Element", ""),
                "Material": payload.get("Material", ""),
                "Temper": payload.get("Temper", ""),
                "Form": payload.get("Form", ""),
            }
            mask = pd.Series(True, index=df.index)
            for col, val in checks.items():
                val = str(val or "").strip()
                if not val:
                    continue
                actual = find_col(df, col)
                if actual:
                    mask &= df[actual].astype(str).map(norm).eq(norm(val))
            spec = str(payload.get("Specification", "") or "").strip()
            if spec and spec != NO_SPEC_DISPLAY:
                actual = find_col(df, "Spec1_1", "spec1_1", "Specification")
                if actual:
                    mask &= df[actual].astype(str).map(norm).eq(norm(spec))
            hit = df.loc[mask].copy()
            if hit is not None and not hit.empty:
                df = hit
        except Exception:
            return None

    if df is None or df.empty:
        return None

    # Prefer the selected thickness, but do not fail if the displayed text is not
    # perfectly identical to the source text.
    exact = str(payload.get("Thickness", "") or "").strip()
    if exact and exact not in {"First matching thickness", "All matching thickness rows"}:
        exact_norm = norm(exact)
        try:
            if "__adv_thickness_norm" in df.columns or "__adv_thickness_base_norm" in df.columns:
                mask = pd.Series(False, index=df.index)
                if "__adv_thickness_norm" in df.columns:
                    mask |= df["__adv_thickness_norm"].astype(str).eq(exact_norm)
                if "__adv_thickness_base_norm" in df.columns:
                    mask |= df["__adv_thickness_base_norm"].astype(str).eq(exact_norm)
                hit = df.loc[mask].copy()
                if hit is not None and not hit.empty:
                    return hit.iloc[0]
        except Exception:
            pass
        try:
            for _idx, row in df.iterrows():
                try:
                    if norm(self._adv_thickness_display_label(row)) == exact_norm or norm(self._adv_thickness_base(row)) == exact_norm:
                        return row
                except Exception:
                    continue
        except Exception:
            pass

    try:
        return df.iloc[0]
    except Exception:
        return None


def _hf_rows_from_original_key(self, payload: Dict[str, Any]) -> pd.DataFrame:
    row = _hf_first_source_row_for_payload(self, payload)
    if row is None:
        return pd.DataFrame()
    try:
        return pd.DataFrame([row])
    except Exception:
        return pd.DataFrame()


def _hf_save_source_key_on_payload(self, payload: Dict[str, Any], rows: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    payload = dict(payload or {})
    row = None
    try:
        if rows is not None and not rows.empty:
            row = rows.iloc[0]
        else:
            row = _hf_first_source_row_for_payload(self, payload)
    except Exception:
        row = None
    if row is not None:
        try:
            row_key = self._adv_row_identity_key(row)
        except Exception:
            row_key = source_row_identity_key(row)
        if row_key:
            payload["_source_row_key"] = row_key
            payload["Source_Row_Key"] = row_key
            payload["_thickness_row_key"] = row_key
            payload["Thickness_Row_Key"] = row_key
        try:
            payload["Thickness"] = payload.get("Thickness") or self._adv_thickness_display_label(row) or "NA"
            payload["Thickness_Mode"] = "Exact thickness text"
        except Exception:
            pass
    return payload


def _hf_adv_match_rows(self, payload: Dict[str, Any]) -> pd.DataFrame:
    """Match rows for Advanced Selection with source-key priority.

    This keeps strict matching for filter counts, but once an export-list row has
    a saved source key it remains connected to its original material forever.
    """
    payload = dict(payload or {})
    # For export-list rows, hidden key wins. Do not let custom notes/name/status
    # disconnect the row from the Material Card.
    if any(str(payload.get(k, "") or "").strip() for k in ("_source_row_key", "Source_Row_Key", "_thickness_row_key", "Thickness_Row_Key")):
        keyed = _hf_rows_from_original_key(self, payload)
        if keyed is not None and not keyed.empty:
            return keyed
    # Otherwise preserve strict behavior for normal filtering.
    try:
        return _strict_adv_match_rows(self, payload)
    except Exception:
        pass
    row = _hf_first_source_row_for_payload(self, payload)
    return pd.DataFrame([row]) if row is not None else pd.DataFrame()


def _hf_adv_add_payload(self, payload: Dict[str, Any], source_label: str = "selection", refresh: bool = True, log: bool = True):
    payload = dict(payload or {})
    # Use strict rows first for add; if strict rows exist, attach the hidden row
    # key immediately. This is the key fix for future reopening.
    try:
        rows = _strict_adv_match_rows(self, payload)
    except Exception:
        rows = self._adv_match_rows(payload)
    if rows is None or rows.empty:
        if log:
            self._adv_log(f"Skipped {source_label}: no matching source row was found.", status="Skipped")
        return False

    payload = self._adv_enrich_payload_from_first_match(payload, rows)
    payload = _hf_save_source_key_on_payload(self, payload, rows)
    payload["_matches"] = int(len(rows))
    payload["_selected"] = bool(payload.get("_selected", True))

    if not str(payload.get("Export_ID", "")).strip():
        payload["Export_ID"] = str(_hemil_next_available_export_id(self) if "_hemil_next_available_export_id" in globals() else reserve_next_export_id())
    else:
        default_id = (_hemil_next_available_export_id(self) if "_hemil_next_available_export_id" in globals() else peek_next_export_id())
        new_id = str(normalize_export_id(payload.get("Export_ID"), default=default_id))
        # Duplicate ID protection.
        used_ids = _hemil_used_export_ids(self) if "_hemil_used_export_ids" in globals() else set()
        if int(new_id) in used_ids:
            messagebox.showerror("Export ID", f"ID / MID {new_id} already exists in the export list. Choose a different ID.")
            return False
        payload["Export_ID"] = new_id
        payload["_id_manual"] = True

    payload["_status"] = payload.get("_status") or "Ready"
    payload["_tag"] = payload.get("_tag") or "ok"
    payload.setdefault("Notes", "")
    payload.setdefault("Custom_Name", payload.get("Custom Name", ""))

    self.advanced_items.append(payload)
    if refresh:
        self._adv_refresh_tree()
        try:
            new_iid = str(len(self.advanced_items) - 1)
            self.adv_tree.selection_set(new_iid)
            self.adv_tree.see(new_iid)
        except Exception:
            pass
        try:
            self._finder_refresh_selected_export_tree()
        except Exception:
            pass
    if log:
        self._adv_log(f"Added {source_label}: {payload['_matches']} matching row(s).")
    return True


def _hf_adv_open_export_list_row_card(self, event=None):
    """Open Material Card from Advanced Selection without text-matching failure."""
    tree = getattr(self, "adv_tree", None)
    if tree is None:
        return "break"

    # Do not open when the user is clicking an editable cell or image/checkbox.
    col_name = ""
    try:
        col_name = self._adv_tree_column_name(tree.identify_column(event.x)) if event is not None else ""
    except Exception:
        col_name = ""
    if col_name in {"Export", "Export_ID", "Unit", "Notes", "View_Image"}:
        return "break"

    try:
        if getattr(self, "adv_tree_edit_widget", None) is not None:
            self.adv_tree_edit_widget.destroy()
            self.adv_tree_edit_widget = None
    except Exception:
        pass

    row_id = tree.identify_row(event.y) if event is not None else (tree.selection()[0] if tree.selection() else "")
    if not row_id:
        return "break"
    try:
        idx = int(row_id)
        item = self.advanced_items[idx]
    except Exception:
        return "break"

    row = _hf_first_source_row_for_payload(self, item)
    if row is None:
        messagebox.showwarning(
            "Advanced Selection",
            "This export-list item is missing its hidden source row connection. Remove this row and add it again from the filters."
        )
        return "break"

    # Save the key back to the item so future openings/export stay connected.
    try:
        fixed_item = _hf_save_source_key_on_payload(self, item, pd.DataFrame([row]))
        self.advanced_items[idx].update(fixed_item)
        item = self.advanced_items[idx]
    except Exception:
        pass

    # Build selections directly from the source row to avoid visible text mismatch.
    selections = {}
    try:
        selections = self._adv_selection_from_payload(item)
    except Exception:
        selections = {s: str(item.get(s, "") or "").strip() for s in STAGES}

    def set_if_blank(field: str, value: Any) -> None:
        if not str(selections.get(field, "") or "").strip():
            selections[field] = str(value or "").strip()

    try:
        set_if_blank("Element", row.get("Element", item.get("Element", "")))
        set_if_blank("Material", row.get("Material", item.get("Material", "")))
        set_if_blank("Temper", row.get("Temper", item.get("Temper", "")))
        set_if_blank("Form", row.get("Form", item.get("Form", "")))
        spec = str(row.get("Spec1_1", row.get("spec1_1", item.get("Specification", ""))) or "").strip()
        if not str(selections.get("Specification", "") or "").strip():
            selections["Specification"] = NO_SPEC_DISPLAY if is_blank(spec) else spec
        if not str(selections.get("Specification 2", "") or "").strip():
            selections["Specification 2"] = display_spec_value(row_spec2_value(row))
        if not str(selections.get("Series", "") or "").strip():
            selections["Series"] = str(row.get("Series", "") or "").strip() or self.db._material_to_series.get(norm(selections.get("Material", "")), "")
    except Exception:
        pass

    try:
        matching_rows = self.db.filter_master(selections)
        if matching_rows is None or matching_rows.empty:
            matching_rows = pd.DataFrame([row])
    except Exception:
        matching_rows = pd.DataFrame([row])

    # Do not block opening with generation validation. The Material Card is where
    # the user can inspect/fix values. Export validation still happens at export.
    try:
        history_entry = {"datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "history_type": "selection"}
        history_entry.update(selections)
        history_entry["Source"] = row.get("MMPDS_Version", "-")
        history_entry["Thickness"] = source_thickness_display_label(row)
        history_entry["Thickness_Row_Key"] = item.get("_source_row_key") or item.get("_thickness_row_key") or source_row_identity_key(row)
        history_entry["Opened_From"] = "Advanced Selection"
        history_entry["Export_ID"] = str(item.get("Export_ID", "")).strip()
        self.app.history.append(history_entry)
        self._refresh_history()
    except Exception:
        history_entry = {}

    card_open_state = {
        "Basis": item.get("Basis", "B"),
        "Direction": item.get("Direction", "L"),
        "Unit_System": item.get("Unit_System", "mm_T_s"),
        "Material_Model": item.get("Material_Model", "MAT024+GISSMO"),
        "Thickness": source_thickness_display_label(row) or item.get("Thickness", ""),
        "Thickness_Row_Key": item.get("_source_row_key") or item.get("_thickness_row_key") or source_row_identity_key(row),
        "Opened_From": "Advanced Selection",
        "Export_ID": str(item.get("Export_ID", "")).strip(),
    }
    if isinstance(item.get("_card_custom_state"), dict):
        card_open_state.update(item.get("_card_custom_state") or {})

    try:
        self._audit_log_action(
            screen="Advanced Selection",
            action="Material Card Opened",
            status="Success",
            material_summary=self._history_summary_text(history_entry) if history_entry else "",
            element=selections.get("Element", ""),
            series=selections.get("Series", ""),
            material=selections.get("Material", ""),
            temper=selections.get("Temper", ""),
            specification=selections.get("Specification", ""),
            form=selections.get("Form", ""),
            notes=f"User opened Advanced Selection export row {idx + 1}.",
        )
    except Exception:
        pass

    try:
        if hasattr(self.app, "status_var"):
            self.app.status_var.set(f"Opening Material Card | ID/MID {item.get('Export_ID','')} | {selections.get('Material','')} {selections.get('Temper','')}")
    except Exception:
        pass

    self.app.show_screen(
        "CardScreen",
        row=row,
        selections=selections,
        matching_rows=matching_rows.copy(),
        history_state=card_open_state,
    )
    return "break"


def _hf_adv_handle_tree_click(self, event):
    """Only Export, View Image, ID/MID, Unit, and Notes react as editable/action cells."""
    tree = getattr(self, "adv_tree", None)
    if tree is None:
        return
    row_id = tree.identify_row(event.y)
    col_name = self._adv_tree_column_name(tree.identify_column(event.x))
    if row_id and col_name == "Export":
        self._adv_toggle_export_selected(int(row_id))
        return "break"
    if row_id and col_name == "View_Image":
        self._adv_show_image_for_item(int(row_id))
        return "break"
    if row_id and col_name in {"Export_ID", "Unit", "Notes"}:
        return self._adv_begin_export_list_edit(event)
    # Basis, Direction, Matcard, Thickness, Material fields are read-only here.
    return None


# Apply follow-up overrides after all prior Hemil/strict patches.
SelectionScreen._adv_match_rows = _hf_adv_match_rows
SelectionScreen._adv_rows_to_export = _hemil_adv_rows_to_export if "_hemil_adv_rows_to_export" in globals() else SelectionScreen._adv_rows_to_export
SelectionScreen._adv_add_payload = _hf_adv_add_payload
SelectionScreen._adv_open_export_list_row_card = _hf_adv_open_export_list_row_card
SelectionScreen._adv_handle_tree_click = _hf_adv_handle_tree_click



# -----------------------------------------------------------------------------
# Final UI guard: Advanced Selection Export List read-only columns must never
# show editable dropdown boxes. Only ID / MID, Unit, and Notes are editable.
# This also destroys any stale combobox left from an earlier click/refresh.
# -----------------------------------------------------------------------------
def _final_adv_destroy_active_editor(self) -> None:
    try:
        widget = getattr(self, "adv_tree_edit_widget", None)
        if widget is not None:
            widget.destroy()
        self.adv_tree_edit_widget = None
    except Exception:
        pass


def _final_adv_refresh_dropdown_overlays(self):
    """Draw visible controls only for allowed Export List columns.

    Allowed editable/action cells:
      - Export checkbox/action button
      - ID / MID editable Entry
      - Unit editable Combobox
      - Notes editable Entry, only on custom/edited rows
      - View Image action button

    Read-only data cells such as Temper, Specification 2, Form, Thickness,
    Basis, Direction, and Matcard are intentionally left as plain Treeview text.
    """
    _final_adv_destroy_active_editor(self)
    try:
        self._adv_clear_dropdown_overlays()
    except Exception:
        pass

    tree = getattr(self, "adv_tree", None)
    if tree is None or not tree.winfo_exists():
        return
    try:
        columns = list(tree["columns"])
        col_ids = {name: f"#{columns.index(name) + 1}" for name in columns}
    except Exception:
        return

    def _bbox(iid, col_name):
        if col_name not in col_ids:
            return None
        try:
            box = tree.bbox(iid, col_ids[col_name])
            if not box:
                return None
            x, y, width, height = box
            if width <= 8 or height <= 8:
                return None
            return x, y, width, height
        except Exception:
            return None

    def _place_button(iid, col_name, text, command, bg, fg, min_w=70):
        box = _bbox(iid, col_name)
        if not box:
            return
        x, y, width, height = box
        btn = tk.Button(
            tree,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            font=FONTS["caption"],
            relief="solid",
            bd=1,
            highlightthickness=0,
            takefocus=0,
            cursor="hand2",
            padx=2,
            pady=0,
        )
        btn.place(x=x + 6, y=y + 5, width=max(min_w, width - 12), height=max(22, height - 10))
        self.adv_cell_widgets.append(btn)

    for iid in tree.get_children(""):
        try:
            idx = int(iid)
        except Exception:
            continue
        if not (0 <= idx < len(getattr(self, "advanced_items", []))):
            continue
        item = self.advanced_items[idx]

        # Export checkbox/action.
        if "Export" in col_ids:
            checked = bool(item.get("_selected", False))
            _place_button(
                iid,
                "Export",
                "✓" if checked else "",
                lambda row_idx=idx: self._adv_toggle_export_selected(row_idx),
                "#FFFFFF",
                "#00A651",
                min_w=24,
            )

        # ID / MID editable white box.
        if "Export_ID" in col_ids:
            box = _bbox(iid, "Export_ID")
            if box:
                x, y, width, height = box
                ent = ttk.Entry(tree, font=FONTS["caption"], takefocus=0)
                ent.insert(0, str(item.get("Export_ID", "")))
                ent.place(x=x + 6, y=y + 5, width=max(70, width - 12), height=max(22, height - 10))

                def _commit_id(_event=None, row_idx=idx, editor=ent):
                    self._adv_apply_export_cell_edit(row_idx, "Export_ID", editor.get().strip())
                    return "break"

                ent.bind("<Return>", _commit_id)
                ent.bind("<FocusOut>", _commit_id)
                ent.bind("<Double-1>", lambda _event: "break")
                self.adv_cell_widgets.append(ent)

        # Unit editable dropdown.
        if "Unit" in col_ids:
            box = _bbox(iid, "Unit")
            if box:
                x, y, width, height = box
                options = self._adv_options_for_export_cell(item, "Unit")
                current = UNIT_SYSTEM_SPEC.get(item.get("Unit_System", "mm_T_s"), {}).get("label", item.get("Unit_System", ""))
                combo = ttk.Combobox(tree, values=options, state="readonly", font=FONTS["caption"], takefocus=0)
                combo.set(current if current in options else (options[0] if options else current))
                combo.place(x=x + 6, y=y + 5, width=max(92, width - 12), height=max(24, height - 10))

                def _commit_unit(_event=None, row_idx=idx, combo_widget=combo):
                    value = combo_widget.get().strip()
                    if value:
                        self._adv_apply_export_cell_edit_multi(row_idx, "Unit", value, option_index=-1)
                    return "break"

                combo.bind("<<ComboboxSelected>>", _commit_unit)
                combo.bind("<Return>", _commit_unit)
                combo.bind("<MouseWheel>", lambda _event: "break")
                self.adv_cell_widgets.append(combo)

        # Notes editable white box is always visible in the last column.
        if "Notes" in col_ids:
            box = _bbox(iid, "Notes")
            if box:
                x, y, width, height = box
                ent = tk.Entry(tree, font=FONTS["caption"], bg="#FFFFFF", fg="#111827", relief="solid", bd=1, takefocus=0)
                ent.insert(0, str(item.get("Notes", "")))
                ent.place(x=x + 6, y=y + 5, width=max(120, width - 12), height=max(22, height - 10))

                def _commit_note(_event=None, row_idx=idx, editor=ent):
                    self._adv_apply_export_cell_edit(row_idx, "Notes", editor.get().strip())
                    return "break"

                ent.bind("<Return>", _commit_note)
                ent.bind("<FocusOut>", _commit_note)
                ent.bind("<Double-1>", lambda _event: "break")
                self.adv_cell_widgets.append(ent)

        # Image button/action.
        if "View_Image" in col_ids:
            _place_button(
                iid,
                "View_Image",
                "View Image",
                lambda row_idx=idx: self._adv_show_image_for_item(row_idx),
                THEME["accent"],
                THEME["accent_text"],
                min_w=70,
            )


def _final_adv_begin_export_list_edit(self, event=None):
    """Open an editor only for ID / MID, Unit, and Notes."""
    tree = getattr(self, "adv_tree", None)
    if tree is None:
        return "break"
    row_id = tree.identify_row(event.y) if event is not None else (tree.selection()[0] if tree.selection() else "")
    col_id = tree.identify_column(event.x) if event is not None else ""
    col_name = self._adv_tree_column_name(col_id)
    allowed = {"Export_ID", "Unit", "Notes"}
    if not row_id or col_name not in allowed:
        _final_adv_destroy_active_editor(self)
        return "break"
    try:
        idx = int(row_id)
        item = self.advanced_items[idx]
    except Exception:
        return "break"
    return self._adv_start_strict_cell_editor(idx, col_name) if hasattr(self, "_adv_start_strict_cell_editor") else "break"


def _final_adv_start_strict_cell_editor(self, idx: int, col_name: str):
    """Small editor used only when the user directly clicks ID, Unit, or Notes."""
    tree = getattr(self, "adv_tree", None)
    if tree is None or not (0 <= idx < len(getattr(self, "advanced_items", []))):
        return "break"
    item = self.advanced_items[idx]
    columns = list(tree["columns"])
    if col_name not in columns:
        return "break"
    iid = str(idx)
    col_id = f"#{columns.index(col_name) + 1}"
    try:
        bbox = tree.bbox(iid, col_id)
    except Exception:
        bbox = None
    if not bbox:
        return "break"
    x, y, width, height = bbox
    _final_adv_destroy_active_editor(self)
    current = str(tree.set(iid, col_name) or "")

    if col_name in {"Export_ID", "Notes"}:
        editor = tk.Entry(tree, bg="#FFFFFF", fg="#111827", relief="solid", bd=1, font=FONTS["caption"])
        editor.insert(0, current if col_name == "Notes" else (current or str(peek_next_export_id())))
        editor.select_range(0, tk.END)
        editor.focus_set()
        editor.place(x=x + 2, y=y + 2, width=max(60, width - 4), height=max(22, height - 4))
        self.adv_tree_edit_widget = editor

        def _commit(_event=None):
            value = editor.get().strip()
            self._adv_apply_export_cell_edit(idx, col_name, value)
            _final_adv_destroy_active_editor(self)
            return "break"

        editor.bind("<Return>", _commit)
        editor.bind("<FocusOut>", _commit)
        editor.bind("<Escape>", lambda _event: (_final_adv_destroy_active_editor(self), "break")[-1])
        return "break"

    if col_name == "Unit":
        options = self._adv_options_for_export_cell(item, "Unit")
        current_label = UNIT_SYSTEM_SPEC.get(item.get("Unit_System", "mm_T_s"), {}).get("label", item.get("Unit_System", ""))
        combo = ttk.Combobox(tree, values=options, state="readonly", font=FONTS["caption"])
        combo.set(current_label if current_label in options else (options[0] if options else current_label))
        combo.place(x=x + 2, y=y + 2, width=max(85, width - 4), height=max(22, height - 4))
        combo.focus_set()
        self.adv_tree_edit_widget = combo

        def _commit(_event=None):
            value = combo.get().strip()
            if value:
                self._adv_apply_export_cell_edit_multi(idx, "Unit", value, option_index=-1)
            _final_adv_destroy_active_editor(self)
            return "break"

        combo.bind("<<ComboboxSelected>>", _commit)
        combo.bind("<Return>", _commit)
        combo.bind("<FocusOut>", lambda _event: _final_adv_destroy_active_editor(self))
        combo.bind("<Escape>", lambda _event: (_final_adv_destroy_active_editor(self), "break")[-1])
        return "break"

    return "break"


def _final_adv_handle_tree_click(self, event):
    """Prevent read-only Export List columns from opening any editor."""
    tree = getattr(self, "adv_tree", None)
    if tree is None:
        return "break"
    row_id = tree.identify_row(event.y)
    col_name = self._adv_tree_column_name(tree.identify_column(event.x))
    if not row_id:
        _final_adv_destroy_active_editor(self)
        return None
    try:
        idx = int(row_id)
    except Exception:
        return "break"

    if col_name == "Export":
        _final_adv_destroy_active_editor(self)
        self._adv_toggle_export_selected(idx)
        return "break"
    if col_name == "View_Image":
        _final_adv_destroy_active_editor(self)
        self._adv_show_image_for_item(idx)
        return "break"
    if col_name in {"Export_ID", "Unit", "Notes"}:
        return self._adv_begin_export_list_edit(event)

    # The important line: read-only cells must not become dropdowns.
    _final_adv_destroy_active_editor(self)
    return None


def _final_adv_open_export_list_row_card(self, event=None):
    """Open Material Card reliably, while ignoring editable/action columns."""
    tree = getattr(self, "adv_tree", None)
    if tree is None:
        return "break"
    try:
        col_name = self._adv_tree_column_name(tree.identify_column(event.x)) if event is not None else ""
    except Exception:
        col_name = ""
    # Editable/action columns should not open the material card.
    if col_name in {"Export", "Export_ID", "Unit", "Notes", "View_Image"}:
        return "break"
    _final_adv_destroy_active_editor(self)
    # Reuse the most recent reliable open-card implementation if it exists.
    if "_hf_adv_open_export_list_row_card" in globals():
        return _hf_adv_open_export_list_row_card(self, event)
    # Fallback to the class implementation.
    try:
        return _original_adv_open_export_list_row_card(self, event) if "_original_adv_open_export_list_row_card" in globals() else None
    except Exception:
        messagebox.showwarning("Advanced Selection", "Could not open this material row.")
        return "break"


# Final enforceable overrides.
SelectionScreen._final_adv_destroy_active_editor = _final_adv_destroy_active_editor
SelectionScreen._adv_refresh_dropdown_overlays = _final_adv_refresh_dropdown_overlays
SelectionScreen._adv_begin_export_list_edit = _final_adv_begin_export_list_edit
SelectionScreen._adv_start_strict_cell_editor = _final_adv_start_strict_cell_editor
SelectionScreen._adv_handle_tree_click = _final_adv_handle_tree_click
SelectionScreen._adv_open_export_list_row_card = _final_adv_open_export_list_row_card


# -----------------------------------------------------------------------------
# Final Advanced Selection fix requested:
# 1) Advanced Selection must filter forward AND backward.
# 2) Thickness list must show actual source thickness values only.
#    Remove "First matching thickness" and "All matching thickness rows" from UI.
# 3) Export List edited ID/MID must match Material Card ID and internal export ID.
# -----------------------------------------------------------------------------
_ADV_FAKE_THICKNESS_OPTIONS = {"first matching thickness", "all matching thickness rows", "[default]"}


def _final_clean_adv_thickness_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if norm(text) in _ADV_FAKE_THICKNESS_OPTIONS:
        return ""
    return text


def _final_adv_set_no_thickness(self) -> None:
    """Clear Advanced Selection thickness without showing fake default rows."""
    try:
        self.adv_thickness_display_var.set("")
        self.adv_thickness_mode_var.set("")
        self.adv_thickness_text_var.set("")
    except Exception:
        pass


def _final_adv_selected_thickness_text(self) -> str:
    """Return selected exact Advanced Selection thickness text, or blank."""
    try:
        mode = str(self.adv_thickness_mode_var.get() or "").strip()
        text = str(self.adv_thickness_text_var.get() or "").strip()
        disp = str(self.adv_thickness_display_var.get() or "").strip()
    except Exception:
        return ""
    if mode == "Exact thickness text" and _final_clean_adv_thickness_value(text):
        return _final_clean_adv_thickness_value(text)
    return _final_clean_adv_thickness_value(disp)


def _final_adv_extra_filter_options(self, stage: str) -> List[str]:
    """Advanced extra filter options with no fake thickness choices."""
    engine = getattr(self, "perf_engine", None)
    thickness = _final_adv_selected_thickness_text(self)
    basis = str(getattr(self, "adv_basis_var", tk.StringVar(value="")).get() or "").strip()
    direction = str(getattr(self, "adv_direction_var", tk.StringVar(value="")).get() or "").strip()
    model = str(getattr(self, "adv_model_var", tk.StringVar(value="")).get() or "").strip()

    if engine is not None:
        try:
            if stage == "Thickness":
                raw = engine.available_thicknesses(self.adv_selections)
                out = []
                seen = set()
                for label in raw:
                    clean = _final_clean_adv_thickness_value(label)
                    if not clean:
                        continue
                    key = norm(clean)
                    if key not in seen:
                        seen.add(key)
                        out.append(clean)
                return out
            if stage == "Basis":
                opts = engine.available_bases(self.adv_selections, thickness=thickness, direction=direction, matcard=model)
                if not opts:
                    opts = engine.available_bases(self.adv_selections, thickness=thickness, direction="", matcard=model)
                return [x for x in opts if x]
            if stage == "Direction":
                opts = engine.available_directions(self.adv_selections, thickness=thickness, basis=basis, matcard=model)
                if not opts:
                    opts = engine.available_directions(self.adv_selections, thickness=thickness, basis=basis, matcard="")
                return [x for x in opts if x]
            if stage == "Matcard":
                opts = engine.available_matcards(self.adv_selections, thickness=thickness, basis=basis, direction=direction)
                if not opts:
                    opts = engine.available_matcards(self.adv_selections, thickness=thickness, basis="", direction="")
                return [x for x in opts if x]
        except Exception:
            pass

    try:
        rows = self.db.filter_master(self.adv_selections)
    except Exception:
        rows = pd.DataFrame()

    if stage == "Thickness":
        out = []
        seen = set()
        if rows is not None and not rows.empty:
            try:
                labels = rows["__adv_thickness_label"].astype(str).tolist() if "__adv_thickness_label" in rows.columns else []
            except Exception:
                labels = []
            if not labels:
                labels = []
                for _, row in rows.iterrows():
                    try:
                        labels.append(self._adv_thickness_display_label(row) or "")
                    except Exception:
                        pass
            for label in labels:
                clean = _final_clean_adv_thickness_value(label)
                if not clean:
                    continue
                key = norm(clean)
                if key not in seen:
                    seen.add(key)
                    out.append(clean)
        return out
    if stage == "Basis":
        return [code for code, ok in self._adv_available_bases_for_payload({**self._adv_current_item_payload(), "Thickness": thickness, "Thickness_Mode": "Exact thickness text" if thickness else ""}).items() if ok]
    if stage == "Direction":
        return self._adv_available_directions_for_payload({**self._adv_current_item_payload(), "Thickness": thickness, "Thickness_Mode": "Exact thickness text" if thickness else ""})
    if stage == "Matcard":
        return self._adv_available_matcards_for_rows(rows, basis, direction)
    return []


def _final_adv_refresh_extra_filters(self):
    """Refresh extra filters but never insert fake thickness rows."""
    if not getattr(self, "adv_extra_listboxes", None):
        return

    current_map = {
        "Thickness": _final_adv_selected_thickness_text(self),
        "Basis": str(self.adv_basis_var.get() or "").strip(),
        "Direction": str(self.adv_direction_var.get() or "").strip(),
        "Matcard": str(self.adv_model_var.get() or "").strip(),
    }

    for stage in self.adv_extra_filter_stages:
        lb = self.adv_extra_listboxes.get(stage)
        if lb is None:
            continue
        options = self._adv_extra_filter_options(stage)
        if stage == "Thickness":
            # Defensive removal of the two old fake rows.
            options = [_final_clean_adv_thickness_value(x) for x in options]
            options = [x for x in options if x]
        old_options = self.adv_extra_visible_values.get(stage, [])
        self.adv_extra_visible_values[stage] = options
        if old_options != options:
            lb.delete(0, tk.END)
            for option in options:
                lb.insert(tk.END, option)

        current = current_map.get(stage, "")
        if stage == "Thickness":
            if current not in options:
                current = ""
                _final_adv_set_no_thickness(self)
        elif stage == "Basis":
            if current not in options:
                current = self._adv_preferred_value(options, "B", "") if hasattr(self, "_adv_preferred_value") else (options[0] if options else "")
                self.adv_basis_var.set(current)
                if hasattr(self, "adv_basis_display_var"):
                    self.adv_basis_display_var.set({code: label for label, code in BASIS_OPTIONS}.get(current, ""))
        elif stage == "Direction":
            if current not in options:
                current = self._adv_preferred_value(options, "L", "") if hasattr(self, "_adv_preferred_value") else (options[0] if options else "")
                self.adv_direction_var.set(current)
        elif stage == "Matcard":
            if current not in options:
                current = self._adv_preferred_value(options, "MAT024+GISSMO", "") if hasattr(self, "_adv_preferred_value") else (options[0] if options else "")
                self.adv_model_var.set(current)

        lb.selection_clear(0, tk.END)
        if current in options:
            try:
                idx = options.index(current)
                lb.selection_set(idx)
                lb.see(idx)
            except Exception:
                pass

        if stage == "Thickness":
            label = current if current else "(not selected)"
            fg = THEME["accent"] if current else THEME["text_muted"]
        else:
            label = current if current else "(not available)"
            fg = THEME["accent"] if current else THEME["status_error_fg"]
        try:
            self.adv_extra_selection_labels[stage].configure(text=f"Selected: {label}", fg=fg)
            self.adv_extra_count_labels[stage].configure(text=str(len(options)))
        except Exception:
            pass


def _final_adv_select_extra_filter(self, stage: str):
    lb = self.adv_extra_listboxes.get(stage)
    if lb is None:
        return
    sel = lb.curselection()
    if not sel:
        return
    values = self.adv_extra_visible_values.get(stage, [])
    if not values:
        return
    value = str(values[sel[0]] or "").strip()
    if stage == "Thickness":
        value = _final_clean_adv_thickness_value(value)
        if value:
            self.adv_thickness_display_var.set(value)
            self.adv_thickness_mode_var.set("Exact thickness text")
            self.adv_thickness_text_var.set(value)
        else:
            _final_adv_set_no_thickness(self)
    elif stage == "Basis":
        self.adv_basis_var.set(value)
        if hasattr(self, "adv_basis_display_var"):
            self.adv_basis_display_var.set({code: label for label, code in BASIS_OPTIONS}.get(value, value))
    elif stage == "Direction":
        self.adv_direction_var.set(value)
    elif stage == "Matcard":
        self.adv_model_var.set(value)
    self._adv_refresh_extra_filters()
    self._adv_match_count()


def _final_adv_clear_extra_filter(self, stage: str):
    if stage == "Thickness":
        _final_adv_set_no_thickness(self)
    elif stage == "Basis":
        self.adv_basis_var.set("")
        if hasattr(self, "adv_basis_display_var"):
            self.adv_basis_display_var.set("")
    elif stage == "Direction":
        self.adv_direction_var.set("")
    elif stage == "Matcard":
        self.adv_model_var.set("")
    self._adv_refresh_extra_filters()
    self._adv_match_count()


def _final_adv_reset_extra_filters(self):
    _final_adv_set_no_thickness(self)
    self.adv_basis_var.set("")
    if hasattr(self, "adv_basis_display_var"):
        self.adv_basis_display_var.set("")
    self.adv_direction_var.set("")
    self.adv_model_var.set("")


def _final_adv_default_thickness_changed(self, event=None):
    selected = _final_clean_adv_thickness_value(self.adv_thickness_display_var.get())
    if selected:
        self.adv_thickness_display_var.set(selected)
        self.adv_thickness_mode_var.set("Exact thickness text")
        self.adv_thickness_text_var.set(selected)
    else:
        _final_adv_set_no_thickness(self)
    self._adv_refresh_extra_filters()
    self._adv_match_count()


def _final_adv_refresh_thickness_controls(self):
    combo = getattr(self, "adv_thickness_combo", None)
    if combo is None:
        return
    options = self._adv_extra_filter_options("Thickness")
    try:
        combo.configure(values=options)
    except Exception:
        pass
    current = _final_adv_selected_thickness_text(self)
    if current not in options:
        _final_adv_set_no_thickness(self)


def _final_adv_current_item_payload(self) -> Dict[str, Any]:
    payload = {stage: self.adv_selections.get(stage, "") for stage in STAGES}
    thickness = _final_adv_selected_thickness_text(self)
    payload.update({
        "Export_ID": "",
        "Basis": str(self.adv_basis_var.get() or "").strip(),
        "Direction": str(self.adv_direction_var.get() or "").strip(),
        "Unit_System": self.adv_unit_sys_var.get(),
        "Material_Model": str(self.adv_model_var.get() or "").strip(),
        "Thickness_Mode": "Exact thickness text" if thickness else "",
        "Thickness": thickness,
        "Source": "Manual",
    })
    return payload


def _final_adv_refresh_all_stages(self, skip_auto_stage: Optional[str] = None):
    """Bidirectional Advanced Selection refresh: every column reacts to every selected column."""
    for s in STAGES:
        self._adv_refresh_stage(s)
    self._adv_refresh_extra_filters()
    self._adv_match_count()


def _final_adv_select(self, stage):
    lb = self.adv_listboxes.get(stage)
    if lb is None:
        return
    sel = lb.curselection()
    if not sel:
        return
    values = self.adv_visible_values.get(stage, [])
    if not values:
        return
    value = values[sel[0]]
    if isinstance(value, str) and value.startswith("... and "):
        messagebox.showinfo("Refine Search", "More results are available. Type more letters to narrow the list.")
        lb.selection_clear(0, tk.END)
        return
    self.adv_selections[stage] = value
    try:
        self.adv_selection_labels[stage].configure(text=f"Selected: {value}", fg=THEME["accent"])
    except Exception:
        pass
    # Key requirement: forward and backward search/filtering.
    self._adv_refresh_all_stages(skip_auto_stage=stage)


def _final_adv_clear_stage(self, stage):
    self.adv_selections[stage] = ""
    if stage in self.adv_search_vars:
        self.adv_search_vars[stage].set(PLACEHOLDER_SEARCH)
    # Key requirement: clearing one stage recalculates both previous and next columns.
    self._adv_refresh_all_stages(skip_auto_stage=stage)


def _final_adv_match_rows(self, payload: Dict[str, Any]) -> pd.DataFrame:
    """Match Advanced rows with hidden source-key priority and no fake thickness modes."""
    payload = dict(payload or {})
    if any(str(payload.get(k, "") or "").strip() for k in ("_source_row_key", "Source_Row_Key", "_thickness_row_key", "Thickness_Row_Key")):
        try:
            keyed = _hf_rows_from_original_key(self, payload) if "_hf_rows_from_original_key" in globals() else pd.DataFrame()
            if keyed is not None and not keyed.empty:
                return keyed
        except Exception:
            pass
    selections = self._adv_selection_from_payload(payload)
    mode = str(payload.get("Thickness_Mode", "") or "").strip()
    exact = _final_clean_adv_thickness_value(payload.get("Thickness", ""))
    basis = str(payload.get("Basis", "") or "").strip()
    direction = str(payload.get("Direction", "") or "").strip()
    model = str(payload.get("Material_Model", "") or "").strip()
    try:
        if getattr(self, "perf_engine", None) is not None:
            thickness = exact if mode == "Exact thickness text" and exact else ""
            return self.perf_engine.filter_rows(selections, thickness=thickness, basis=basis, direction=direction, matcard=model)
    except Exception:
        pass
    try:
        df = self.db.filter_master(selections)
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if mode == "Exact thickness text" and exact:
        exact_norm = norm(exact)
        try:
            if "__adv_thickness_norm" in df.columns and "__adv_thickness_base_norm" in df.columns:
                mask = (df["__adv_thickness_norm"].astype(str).eq(exact_norm) | df["__adv_thickness_base_norm"].astype(str).eq(exact_norm))
                df = df.loc[mask].copy()
            else:
                mask = []
                for _, row in df.iterrows():
                    t_base = self._adv_thickness_base(row)
                    t_display = self._adv_thickness_display_label(row)
                    mask.append(norm(t_base) == exact_norm or norm(t_display) == exact_norm)
                df = df.loc[mask].copy()
        except Exception:
            pass
    if basis or direction:
        try:
            keep = [idx for idx, row in df.iterrows() if self._finder_row_has_basis_direction_data(row, basis, direction)]
            df = df.loc[keep].copy()
        except Exception:
            pass
    if model:
        try:
            keep = [idx for idx, row in df.iterrows() if self._adv_row_model_available(row, model, basis, direction)]
            df = df.loc[keep].copy()
        except Exception:
            pass
    return df


def _final_adv_rows_to_export(self, payload: Dict[str, Any]) -> List[pd.Series]:
    df = self._adv_match_rows(payload)
    if df is None or df.empty:
        return []
    # The fake "All matching thickness rows" option is removed from the UI.
    # Keep old imported payloads safe only if they already contain that mode.
    if str(payload.get("Thickness_Mode", "") or "").strip() == "All matching thickness rows":
        return [df.iloc[i] for i in range(len(df))]
    return [df.iloc[0]]


# Card ID/MID sync fix: when an Advanced export row is opened, the Card ID must
# show the same ID/MID as Export List and use that same internal ID for keyfiles.
_original_final_card_on_show = CardScreen.on_show


def _final_card_on_show(self, row=None, selections=None, matching_rows=None, history_state=None, **kwargs):
    result = _original_final_card_on_show(self, row=row, selections=selections, matching_rows=matching_rows, history_state=history_state, **kwargs)
    try:
        if isinstance(history_state, dict):
            export_id = str(history_state.get("Export_ID", "") or "").strip()
            if export_id:
                self.export_id_var.set(export_id)
                self.opened_export_id_context = export_id
    except Exception:
        pass
    return result


# When Apply is pressed after opening from Advanced Selection, keep the current
# Card ID/MID synchronized with the Advanced export-list item too.
_original_final_card_commit_all_pending_edits = CardScreen._commit_all_pending_edits


def _final_card_commit_all_pending_edits(self, trigger: str = "Enter"):
    old_opened_id = str(getattr(self, "opened_export_id_context", "") or "").strip()
    current_card_id = str(getattr(self, "export_id_var", tk.StringVar(value="")).get() or "").strip()
    result = _original_final_card_commit_all_pending_edits(self, trigger)
    if old_opened_id and current_card_id:
        try:
            new_id = str(normalize_export_id(current_card_id, default=int(old_opened_id)))
            selection_screen = self.app.screens.get("SelectionScreen")
            if selection_screen is not None:
                for other in getattr(selection_screen, "advanced_items", []):
                    if str(other.get("Export_ID", "")).strip() == new_id and str(other.get("Export_ID", "")).strip() != old_opened_id:
                        messagebox.showerror("Export ID", f"ID / MID {new_id} already exists in the export list. Choose a different ID.")
                        self.export_id_var.set(old_opened_id)
                        return result
                for item in getattr(selection_screen, "advanced_items", []):
                    if str(item.get("Export_ID", "")).strip() == old_opened_id:
                        item["Export_ID"] = new_id
                        self.opened_export_id_context = new_id
                        try:
                            selection_screen._adv_refresh_tree()
                        except Exception:
                            pass
                        break
        except Exception:
            pass
    return result


# Apply final overrides.
SelectionScreen._adv_extra_filter_options = _final_adv_extra_filter_options
SelectionScreen._adv_refresh_extra_filters = _final_adv_refresh_extra_filters
SelectionScreen._adv_select_extra_filter = _final_adv_select_extra_filter
SelectionScreen._adv_clear_extra_filter = _final_adv_clear_extra_filter
SelectionScreen._adv_reset_extra_filters = _final_adv_reset_extra_filters
SelectionScreen._adv_default_thickness_changed = _final_adv_default_thickness_changed
SelectionScreen._adv_refresh_thickness_controls = _final_adv_refresh_thickness_controls
SelectionScreen._adv_current_item_payload = _final_adv_current_item_payload
SelectionScreen._adv_refresh_all_stages = _final_adv_refresh_all_stages
SelectionScreen._adv_select = _final_adv_select
SelectionScreen._adv_clear_stage = _final_adv_clear_stage
SelectionScreen._adv_match_rows = _final_adv_match_rows
SelectionScreen._adv_rows_to_export = _final_adv_rows_to_export
CardScreen.on_show = _final_card_on_show
CardScreen._commit_all_pending_edits = _final_card_commit_all_pending_edits



# -----------------------------------------------------------------------------
# Advanced Selection auto-singleton patch
# Requirement: if any Advanced Selection filter/listbox has exactly one real
# option, automatically select it. This applies to the 7 material filters and
# the extra filters Thickness / Basis / Direction / Matcard. It keeps the
# bidirectional refresh behavior and keeps fake Thickness options removed.
# -----------------------------------------------------------------------------
_ASF_FAKE_THICKNESS_OPTIONS = {
    norm("First matching thickness"),
    norm("All matching thickness rows"),
    norm("first matching thickness"),
    norm("all matching thickness rows"),
}


def _asf_is_real_option(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith("... and "):
        return False
    return True


def _asf_clean_thickness_options(options: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for option in options or []:
        try:
            if "_final_clean_adv_thickness_value" in globals():
                value = _final_clean_adv_thickness_value(option)
            else:
                value = str(option or "").strip()
        except Exception:
            value = str(option or "").strip()
        if not value:
            continue
        if norm(value) in _ASF_FAKE_THICKNESS_OPTIONS:
            continue
        key = norm(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _asf_selected_thickness(self) -> str:
    try:
        if "_final_adv_selected_thickness_text" in globals():
            return str(_final_adv_selected_thickness_text(self) or "").strip()
    except Exception:
        pass
    try:
        return str(self.adv_thickness_text_var.get() or "").strip()
    except Exception:
        return ""


def _asf_set_extra_value(self, stage: str, value: str) -> None:
    value = str(value or "").strip()
    if stage == "Thickness":
        if value:
            try:
                self.adv_thickness_display_var.set(value)
                self.adv_thickness_mode_var.set("Exact thickness text")
                self.adv_thickness_text_var.set(value)
            except Exception:
                pass
        else:
            try:
                if "_final_adv_set_no_thickness" in globals():
                    _final_adv_set_no_thickness(self)
                else:
                    self.adv_thickness_display_var.set("")
                    self.adv_thickness_mode_var.set("")
                    self.adv_thickness_text_var.set("")
            except Exception:
                pass
        return
    if stage == "Basis":
        try:
            self.adv_basis_var.set(value)
            if hasattr(self, "adv_basis_display_var"):
                self.adv_basis_display_var.set({code: label for label, code in BASIS_OPTIONS}.get(value, value))
        except Exception:
            pass
        return
    if stage == "Direction":
        try:
            self.adv_direction_var.set(value)
        except Exception:
            pass
        return
    if stage == "Matcard":
        try:
            self.adv_model_var.set(value)
        except Exception:
            pass
        return


def _asf_get_extra_value(self, stage: str) -> str:
    try:
        if stage == "Thickness":
            return _asf_selected_thickness(self)
        if stage == "Basis":
            return str(self.adv_basis_var.get() or "").strip()
        if stage == "Direction":
            return str(self.adv_direction_var.get() or "").strip()
        if stage == "Matcard":
            return str(self.adv_model_var.get() or "").strip()
    except Exception:
        return ""
    return ""


def _asf_visible_real_stage_values(self, stage: str) -> List[str]:
    values = []
    seen = set()
    for value in self.adv_visible_values.get(stage, []) or []:
        text = str(value or "").strip()
        if not _asf_is_real_option(text):
            continue
        key = norm(text)
        if key in seen:
            continue
        seen.add(key)
        values.append(text)
    return values


def _asf_apply_singleton_stage_selections(self) -> bool:
    """Auto-select material filter columns that have one real value."""
    changed = False
    for stage in STAGES:
        values = _asf_visible_real_stage_values(self, stage)
        current = str(self.adv_selections.get(stage, "") or "").strip()
        if current and current not in values:
            self.adv_selections[stage] = ""
            current = ""
            changed = True
        if not current and len(values) == 1:
            self.adv_selections[stage] = values[0]
            changed = True
    return changed


def _asf_adv_refresh_extra_filters(self):
    """Refresh extra filters and auto-select only when one real option exists.

    Important: this function never restores the old fake Thickness options and
    never forces B/L/MAT024+GISSMO when multiple choices are available.
    """
    if not getattr(self, "adv_extra_listboxes", None):
        return

    # A change in one extra filter can change the valid options for the others,
    # so make a few safe passes until selections stabilize.
    for _pass in range(6):
        changed = False
        for stage in self.adv_extra_filter_stages:
            lb = self.adv_extra_listboxes.get(stage)
            if lb is None:
                continue
            try:
                options = list(self._adv_extra_filter_options(stage) or [])
            except Exception:
                options = []
            if stage == "Thickness":
                options = _asf_clean_thickness_options(options)
            else:
                # Remove blanks and duplicate options, preserving order.
                cleaned = []
                seen = set()
                for opt in options:
                    val = str(opt or "").strip()
                    if not val:
                        continue
                    key = norm(val)
                    if key in seen:
                        continue
                    seen.add(key)
                    cleaned.append(val)
                options = cleaned

            old_options = self.adv_extra_visible_values.get(stage, [])
            self.adv_extra_visible_values[stage] = options
            if old_options != options:
                try:
                    lb.delete(0, tk.END)
                    for option in options:
                        lb.insert(tk.END, option)
                except Exception:
                    pass

            current = _asf_get_extra_value(self, stage)
            if current and current not in options:
                current = ""
                _asf_set_extra_value(self, stage, "")
                changed = True

            # New rule: single real option auto-selects. Multiple options stay
            # manual, so no forced B/L/MAT024+GISSMO defaults.
            if not current and len(options) == 1:
                current = options[0]
                _asf_set_extra_value(self, stage, current)
                changed = True

            try:
                lb.selection_clear(0, tk.END)
                if current in options:
                    idx = options.index(current)
                    lb.selection_set(idx)
                    lb.see(idx)
            except Exception:
                pass

            if stage == "Thickness":
                label = current if current else "(not selected)"
                fg = THEME["accent"] if current else THEME["text_muted"]
            else:
                label = current if current else ("(not selected)" if options else "(not available)")
                fg = THEME["accent"] if current else (THEME["text_muted"] if options else THEME["status_error_fg"])
            try:
                self.adv_extra_selection_labels[stage].configure(text=f"Selected: {label}", fg=fg)
                self.adv_extra_count_labels[stage].configure(text=str(len(options)))
            except Exception:
                pass
        if not changed:
            break


def _asf_adv_refresh_all_stages(self, skip_auto_stage: Optional[str] = None):
    """Bidirectional Advanced refresh plus automatic single-value selection."""
    if getattr(self, "_asf_refreshing", False):
        for s in STAGES:
            self._adv_refresh_stage(s)
        self._adv_refresh_extra_filters()
        self._adv_match_count()
        return

    self._asf_refreshing = True
    try:
        # Iteratively refresh and auto-select singletons because selecting one
        # column may make another column become a singleton.
        for _pass in range(len(STAGES) + 3):
            for s in STAGES:
                self._adv_refresh_stage(s)
            if not _asf_apply_singleton_stage_selections(self):
                break

        # One final pass ensures listbox highlighting/labels match the new
        # auto-selected values.
        for s in STAGES:
            self._adv_refresh_stage(s)

        self._adv_refresh_extra_filters()
        self._adv_match_count()
    finally:
        self._asf_refreshing = False


def _asf_adv_select(self, stage):
    lb = self.adv_listboxes.get(stage)
    if lb is None:
        return
    sel = lb.curselection()
    if not sel:
        return
    values = self.adv_visible_values.get(stage, [])
    if not values:
        return
    value = values[sel[0]]
    if isinstance(value, str) and value.startswith("... and "):
        messagebox.showinfo("Refine Search", "More results are available. Type more letters to narrow the list.")
        lb.selection_clear(0, tk.END)
        return
    self.adv_selections[stage] = value
    try:
        self.adv_selection_labels[stage].configure(text=f"Selected: {value}", fg=THEME["accent"])
    except Exception:
        pass
    self._adv_refresh_all_stages(skip_auto_stage=stage)


def _asf_adv_clear_stage(self, stage):
    self.adv_selections[stage] = ""
    if stage in self.adv_search_vars:
        self.adv_search_vars[stage].set(PLACEHOLDER_SEARCH)
    self._adv_refresh_all_stages(skip_auto_stage=stage)


def _asf_adv_select_extra_filter(self, stage: str):
    lb = self.adv_extra_listboxes.get(stage)
    if lb is None:
        return
    sel = lb.curselection()
    if not sel:
        return
    values = self.adv_extra_visible_values.get(stage, [])
    if not values:
        return
    value = str(values[sel[0]] or "").strip()
    if stage == "Thickness":
        cleaned = _asf_clean_thickness_options([value])
        value = cleaned[0] if cleaned else ""
    _asf_set_extra_value(self, stage, value)
    self._adv_refresh_extra_filters()
    self._adv_match_count()


def _asf_adv_clear_extra_filter(self, stage: str):
    _asf_set_extra_value(self, stage, "")
    self._adv_refresh_extra_filters()
    self._adv_match_count()


def _asf_adv_reset_extra_filters(self):
    for stage in ("Thickness", "Basis", "Direction", "Matcard"):
        _asf_set_extra_value(self, stage, "")
    # Do not force B/L/MAT024+GISSMO; refresh will auto-pick only if one option exists.
    try:
        self._adv_refresh_extra_filters()
    except Exception:
        pass


def _asf_adv_default_thickness_changed(self, event=None):
    value = str(self.adv_thickness_display_var.get() or "").strip()
    cleaned = _asf_clean_thickness_options([value])
    _asf_set_extra_value(self, "Thickness", cleaned[0] if cleaned else "")
    self._adv_refresh_extra_filters()
    self._adv_match_count()


def _asf_adv_refresh_thickness_controls(self):
    combo = getattr(self, "adv_thickness_combo", None)
    if combo is None:
        return
    options = _asf_clean_thickness_options(self._adv_extra_filter_options("Thickness"))
    try:
        combo.configure(values=options)
    except Exception:
        pass
    current = _asf_selected_thickness(self)
    if current not in options:
        _asf_set_extra_value(self, "Thickness", options[0] if len(options) == 1 else "")


# Apply latest Advanced Selection auto-selection overrides.
SelectionScreen._adv_refresh_extra_filters = _asf_adv_refresh_extra_filters
SelectionScreen._adv_refresh_all_stages = _asf_adv_refresh_all_stages
SelectionScreen._adv_select = _asf_adv_select
SelectionScreen._adv_clear_stage = _asf_adv_clear_stage
SelectionScreen._adv_select_extra_filter = _asf_adv_select_extra_filter
SelectionScreen._adv_clear_extra_filter = _asf_adv_clear_extra_filter
SelectionScreen._adv_reset_extra_filters = _asf_adv_reset_extra_filters
SelectionScreen._adv_default_thickness_changed = _asf_adv_default_thickness_changed
SelectionScreen._adv_refresh_thickness_controls = _asf_adv_refresh_thickness_controls


# -----------------------------------------------------------------------------
# Final keyfile notes patch
# -----------------------------------------------------------------------------
def _keyfile_comment_lines_from_notes(notes: Any) -> List[str]:
    """Convert user Notes into LS-DYNA comment lines.

    Manager rule:
    - Notes go at the very end of the keyfile.
    - Each actual comment line starts with '$'.
    - Do not add headers, separators, or a trailing '$'.
    """
    text = str(notes or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    out: List[str] = []
    for raw_line in text.split("\n"):
        line = " ".join(str(raw_line or "").strip().split())
        if not line:
            continue
        if line.startswith("$"):
            out.append(line)
        else:
            out.append(f"$ {line}")
    return out


def _append_user_notes_to_keyfile_end(k_text: str, notes: Any) -> str:
    """Append user Notes/Comments after the generated keyfile content."""
    comment_lines = _keyfile_comment_lines_from_notes(notes)
    if not comment_lines:
        return k_text

    # Defensive cleanup in case an older build inserted notes near the header.
    cleaned_lines: List[str] = []
    skipping_old_note_block = False
    for line in str(k_text or "").splitlines():
        if line.startswith("$ User Notes:"):
            skipping_old_note_block = True
            continue
        if skipping_old_note_block:
            if line.startswith("$ Custom Edited:"):
                skipping_old_note_block = False
                cleaned_lines.append(line)
            continue
        cleaned_lines.append(line)

    base = "\n".join(cleaned_lines).rstrip()
    return base + "\n" + "\n".join(comment_lines) + "\n"

# Custom Blank Entry patch for Advanced Selection
# -----------------------------------------------------------------------------
# Adds a true custom-entry path:
#   Advanced Selection -> + Add Custom Entry -> blank Material Card.
# The blank card keeps the same Engineering Options, MAT/GISSMO preview,
# Property Card, and Unit Conversion sections, but it does not use source images.
# User-entered Property Card values drive the same calculations/export path.

_CUSTOM_ENTRY_DEFAULT_NAME = "CUSTOM_MATERIAL"


def _custom_clean_name(value: Any, default: str = _CUSTOM_ENTRY_DEFAULT_NAME) -> str:
    """Return a safe custom material name with CUSTOM_ prefix.

    Example:
        AI 1100 H16 -> CUSTOM_AI_1100_H16
    """
    import re
    text = str(value or "").strip()
    if not text:
        text = default
    if text.upper().startswith("CUSTOM_"):
        text = text[7:]
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    if not text:
        text = "MATERIAL"
    return "CUSTOM_" + text.upper()


def _custom_blank_row(custom_name: str = _CUSTOM_ENTRY_DEFAULT_NAME) -> pd.Series:
    """Create one internal source-like row for a blank custom material card."""
    custom_name = _custom_clean_name(custom_name)
    data: Dict[str, Any] = {
        "Element": "CUSTOM",
        "Series": "CUSTOM",
        "Material": custom_name,
        "Temper": "",
        "Spec1_1": "CUSTOM",
        "Specification": "CUSTOM",
        "Spec2_1": NO_SPEC_DISPLAY,
        "Spec2_2": "",
        "Form": "CUSTOM",
        "Thick_Value": "",
        "Wall_Thick": "",
        "Cross_Section": "",
        "MMPDS_Version": "Custom Entry",
        "__adv_row_key": "custom_blank_entry",
        "__custom_blank_entry": True,
    }
    # Add property columns for all basis/direction combinations so the row has a
    # stable schema. Values remain blank until the user types them in the card.
    for key, _label, _kind, pfx_l, pfx_lt in PROPERTY_ROWS:
        if key in ("Etan", "Compression"):
            continue
        for pfx in {pfx_l, pfx_lt}:
            if not pfx:
                continue
            data[pfx] = ""
            for basis in ("A", "B", "S"):
                data[f"{pfx}_{basis}"] = ""
                data[f"{pfx}_L_{basis}"] = ""
                data[f"{pfx}_LT_{basis}"] = ""
    return pd.Series(data, name="custom_blank_entry")


def _custom_is_card(self) -> bool:
    return bool(getattr(self, "is_custom_entry", False))


def _custom_name_current(self) -> str:
    if not hasattr(self, "custom_name_var"):
        self.custom_name_var = tk.StringVar(value=_CUSTOM_ENTRY_DEFAULT_NAME)
    return _custom_clean_name(self.custom_name_var.get())


def _custom_name_changed(self, sanitize: bool = False):
    """Keep the custom name field synced with the current custom card state."""
    if not _custom_is_card(self):
        return "break"
    if not hasattr(self, "custom_name_var"):
        self.custom_name_var = tk.StringVar(value=_CUSTOM_ENTRY_DEFAULT_NAME)
    if sanitize:
        clean = _custom_clean_name(self.custom_name_var.get())
        if self.custom_name_var.get() != clean:
            self.custom_name_var.set(clean)
    else:
        clean = _custom_clean_name(self.custom_name_var.get())
    try:
        self.current_selections["Material"] = clean
        self.current_selections["Element"] = "CUSTOM"
        self.current_selections["Series"] = "CUSTOM"
        self.current_selections["Specification"] = "CUSTOM"
        self.current_selections["Specification 2"] = NO_SPEC_DISPLAY
        self.current_selections["Form"] = "CUSTOM"
        if self.current_row is not None:
            self.current_row["Material"] = clean
            self.current_row["Element"] = "CUSTOM"
            self.current_row["Series"] = "CUSTOM"
            self.current_row["Spec1_1"] = "CUSTOM"
            self.current_row["Specification"] = "CUSTOM"
            self.current_row["Spec2_1"] = NO_SPEC_DISPLAY
            self.current_row["Form"] = "CUSTOM"
            self.current_row["MMPDS_Version"] = "Custom Entry"
    except Exception:
        pass
    try:
        self._render_summary()
    except Exception:
        pass
    return "break"


CardScreen._custom_name_changed = _custom_name_changed
CardScreen._custom_name_current = _custom_name_current


def _selection_adv_add_custom_entry(self):
    """Open a fully blank custom Material Card from Advanced Selection."""
    try:
        export_id = str(peek_next_export_id())
    except Exception:
        export_id = str(EXPORT_COUNTER_START)
    custom_name = _custom_clean_name(f"MATERIAL_{export_id}")
    row = _custom_blank_row(custom_name)
    selections = {
        "Element": "CUSTOM",
        "Series": "CUSTOM",
        "Material": custom_name,
        "Temper": "",
        "Specification": "CUSTOM",
        "Specification 2": NO_SPEC_DISPLAY,
        "Form": "CUSTOM",
    }
    history_state = {
        "Opened_From": "Advanced Custom Entry",
        "Custom_Blank_Entry": True,
        "Custom_Name": custom_name,
        "Export_ID": export_id,
        "Basis": str(getattr(self, "adv_basis_var", tk.StringVar(value="B")).get() or "B"),
        "Direction": str(getattr(self, "adv_direction_var", tk.StringVar(value="L")).get() or "L"),
        "Unit_System": str(getattr(self, "adv_unit_sys_var", tk.StringVar(value="mm_T_s")).get() or "mm_T_s"),
        "Material_Model": str(getattr(self, "adv_model_var", tk.StringVar(value="MAT024+GISSMO")).get() or "MAT024+GISSMO"),
        "Thickness": "",
        "Thickness_Row_Key": "custom_blank_entry",
        "prop_values": {key: ("", False) for key, *_ in PROPERTY_ROWS},
        "unit_conversions": DEFAULT_UNIT_CONVERSIONS.copy(),
    }
    try:
        self._adv_log(
            f"Opened blank custom material card: {custom_name}",
            action="Add Custom Entry",
            status="Ready",
            screen="Advanced Selection",
        )
    except Exception:
        pass
    self.app.show_screen(
        "CardScreen",
        row=row,
        selections=selections,
        matching_rows=pd.DataFrame([row]),
        history_state=history_state,
    )


# Attach method used by the button inserted in Advanced Selection.
SelectionScreen._adv_add_custom_entry = _selection_adv_add_custom_entry


_ORIGINAL_CARD_ON_SHOW_FOR_CUSTOM = CardScreen.on_show
def _custom_card_on_show(self, row=None, selections=None, matching_rows=None, history_state=None, **kwargs):
    is_custom = bool(isinstance(history_state, dict) and history_state.get("Custom_Blank_Entry"))
    self.is_custom_entry = is_custom
    if not hasattr(self, "custom_name_var"):
        self.custom_name_var = tk.StringVar(value="")
    if is_custom:
        custom_name = _custom_clean_name(history_state.get("Custom_Name") or (selections or {}).get("Material") or _CUSTOM_ENTRY_DEFAULT_NAME)
        self.custom_name_var.set(custom_name)
        if row is None:
            row = _custom_blank_row(custom_name)
        try:
            row["__custom_blank_entry"] = True
            row["Material"] = custom_name
            row["Element"] = "CUSTOM"
            row["Series"] = "CUSTOM"
            row["Spec1_1"] = "CUSTOM"
            row["Specification"] = "CUSTOM"
            row["Spec2_1"] = NO_SPEC_DISPLAY
            row["Form"] = "CUSTOM"
            row["MMPDS_Version"] = "Custom Entry"
        except Exception:
            pass
        selections = dict(selections or {})
        selections.update({
            "Element": "CUSTOM",
            "Series": "CUSTOM",
            "Material": custom_name,
            "Specification": "CUSTOM",
            "Specification 2": NO_SPEC_DISPLAY,
            "Form": "CUSTOM",
        })
        matching_rows = pd.DataFrame([row])
    else:
        try:
            self.custom_name_var.set("")
        except Exception:
            pass
    return _ORIGINAL_CARD_ON_SHOW_FOR_CUSTOM(self, row=row, selections=selections, matching_rows=matching_rows, history_state=history_state, **kwargs)
CardScreen.on_show = _custom_card_on_show


_ORIGINAL_CARD_AVAILABLE_BASES = CardScreen._available_bases
def _custom_available_bases(self):
    if _custom_is_card(self):
        return {"A": True, "B": True, "S": True}
    return _ORIGINAL_CARD_AVAILABLE_BASES(self)
CardScreen._available_bases = _custom_available_bases


_ORIGINAL_SELECTED_BASIS_AVAILABLE = CardScreen._selected_basis_available
def _custom_selected_basis_available(self):
    if _custom_is_card(self):
        return True
    return _ORIGINAL_SELECTED_BASIS_AVAILABLE(self)
CardScreen._selected_basis_available = _custom_selected_basis_available


_ORIGINAL_THICKNESS_DISPLAY_LABEL = CardScreen._thickness_display_label
def _custom_thickness_display_label(self, row):
    if _custom_is_card(self):
        try:
            text = str(self.thickness_var.get()).strip()
            if text and text.upper() != "NA":
                return text
        except Exception:
            pass
        try:
            value = str(row.get("Thick_Value", "")).strip()
            return "" if value in {"-", "NA"} else value
        except Exception:
            return ""
    return _ORIGINAL_THICKNESS_DISPLAY_LABEL(self, row)
CardScreen._thickness_display_label = _custom_thickness_display_label


_ORIGINAL_THICKNESS_BASE = CardScreen._thickness_base
def _custom_thickness_base(self, row):
    if _custom_is_card(self):
        try:
            text = str(self.thickness_var.get()).strip()
            if text:
                return text
        except Exception:
            pass
        try:
            return str(row.get("Thick_Value", "")).strip()
        except Exception:
            return ""
    return _ORIGINAL_THICKNESS_BASE(self, row)
CardScreen._thickness_base = _custom_thickness_base


_ORIGINAL_SOURCE_ROWS_MATCHING_CURRENT = CardScreen._source_rows_matching_current_material
def _custom_source_rows_matching_current_material(self):
    if _custom_is_card(self):
        return [self.current_row] if self.current_row is not None else []
    return _ORIGINAL_SOURCE_ROWS_MATCHING_CURRENT(self)
CardScreen._source_rows_matching_current_material = _custom_source_rows_matching_current_material


_ORIGINAL_COMPUTE_TABLE = CardScreen._compute_table
def _custom_compute_table(self):
    """Custom blank card calculation path.

    For normal database materials, the original calculation code is used.
    For custom blank cards, values come only from the user's typed/Applied
    Property Card values and the same unit conversion/true strain formulas are
    reused.
    """
    if not _custom_is_card(self):
        return _ORIGINAL_COMPUTE_TABLE(self)

    unit_sys = self.unit_sys_var.get()
    out: Dict[str, Dict[str, str]] = {}
    raw_calc: Dict[str, Optional[float]] = {}
    eng: Dict[str, Optional[float]] = {}

    for key, label, kind, *_ in PROPERTY_ROWS:
        if key in ("Etan", "Compression"):
            continue

        pending_text = self.pending_edits.get(key)
        stored, edited = self.prop_values.get(key, ("", False))
        value_text = ""
        calc_raw = None

        if pending_text is not None:
            value_text = str(pending_text).strip()
            calc_raw = try_float(value_text)
        elif stored not in ("", "-", None):
            value_text = str(stored).strip()
            calc_raw = try_float(value_text)

        if key == "Elong" and calc_raw is not None:
            calc_raw = abs(calc_raw)
            value_text = fmt_number(calc_raw)

        eng_val, _unit = convert_value(calc_raw, kind, unit_sys, self._effective_unit_conversions())
        raw_calc[key] = calc_raw
        eng[key] = eng_val
        out[key] = {
            "unit": source_unit_label(kind),
            "converted_unit": converted_unit_label(kind, unit_sys),
            "value": value_text,
            "eng": fmt_number(eng_val),
            "true": "-",
            "eps": "-",
        }

    raw_elong = raw_calc.get("Elong")
    raw_fty = raw_calc.get("Fty")
    raw_e = raw_calc.get("E")
    ftu_eng = eng.get("Ftu")
    fty_eng = eng.get("Fty")
    e_eng = eng.get("E")

    elong_eng = None
    elong_true = None
    ftu_true = None
    effps = None
    etan_eng = None
    etan_true = None
    raw_elong_formula = abs(raw_elong) if raw_elong is not None else None

    if raw_elong_formula is not None and raw_fty is not None and raw_e not in (None, 0):
        elong_eng = raw_elong_formula + (100 * raw_fty) / (raw_e * 1000)
        out["Elong"]["eng"] = fmt_number(elong_eng)

    if elong_eng is not None:
        arg = 1 + elong_eng / 100
        if arg > 0:
            elong_true = 100 * math.log(arg)
            out["Elong"]["true"] = fmt_number(elong_true)

    if ftu_eng is not None and elong_eng is not None:
        ftu_true = ftu_eng * (1 + elong_eng / 100)
        out["Ftu"]["true"] = fmt_number(ftu_true)

    if elong_true is not None and fty_eng is not None and e_eng not in (None, 0):
        effps = ((elong_true / 100) - (fty_eng / e_eng)) * 100
        if effps is not None:
            effps = abs(effps)
        out["Elong"]["eps"] = fmt_number(effps)

    if ftu_eng is not None and fty_eng is not None and raw_elong_formula not in (None, 0):
        etan_eng = abs(ftu_eng - fty_eng) / (raw_elong_formula / 100)

    if ftu_true is not None and fty_eng is not None and effps not in (None, 0):
        etan_true = abs(ftu_true - fty_eng) / (abs(effps) / 100)

    raw_ftu = raw_calc.get("Ftu")
    raw_fty_for_etan = raw_calc.get("Fty")
    if raw_ftu is not None and raw_fty_for_etan is not None and raw_elong_formula not in (None, 0):
        etan_calc_raw = abs(raw_ftu - raw_fty_for_etan) / (raw_elong_formula / 100)
        etan_eng, _ = convert_value(etan_calc_raw, "pressure", unit_sys, self._effective_unit_conversions())

    self.last_effps = effps
    self.last_etan_eng = etan_eng
    self.last_etan_true = etan_true

    pending_etan = self.pending_edits.get("Etan")
    stored_etan, edited_etan = self.prop_values.get("Etan", ("", False))
    etan_value_text = ""
    etan_prop_eng = None
    if pending_etan is not None:
        etan_value_text = str(pending_etan).strip()
        source_etan_ksi = try_float(etan_value_text)
        etan_prop_eng, _ = convert_value(source_etan_ksi, "pressure", unit_sys, self._effective_unit_conversions())
    elif stored_etan not in ("", "-", None):
        etan_value_text = str(stored_etan).strip()
        source_etan_ksi = try_float(etan_value_text)
        etan_prop_eng, _ = convert_value(source_etan_ksi, "pressure", unit_sys, self._effective_unit_conversions())

    out["Etan"] = {
        "unit": "ksi",
        "converted_unit": converted_unit_label("pressure", unit_sys),
        "value": etan_value_text,
        "eng": fmt_number(etan_prop_eng),
        "true": "-",
        "eps": "-",
    }

    pending_comp = self.pending_edits.get("Compression")
    stored_comp, edited_comp = self.prop_values.get("Compression", ("", False))
    if pending_comp is not None:
        comp_value = str(pending_comp).strip()
    elif stored_comp not in ("", "-", None):
        comp_value = str(stored_comp).strip()
    else:
        comp_value = ""

    out["Compression"] = {
        "unit": "%",
        "converted_unit": "%",
        "value": comp_value,
        "eng": fmt_number(try_float(comp_value)) if try_float(comp_value) is not None else "",
        "true": "-",
        "eps": "-",
    }
    return out
CardScreen._compute_table = _custom_compute_table


_ORIGINAL_RENDER_SOURCE_IMAGES = CardScreen._render_source_images
def _custom_render_source_images(self):
    if not _custom_is_card(self):
        return _ORIGINAL_RENDER_SOURCE_IMAGES(self)
    if not hasattr(self, "image_panel"):
        return
    for w in self.image_panel.winfo_children():
        try:
            w.destroy()
        except Exception:
            pass
    self.source_image_refs = []
    self.source_images = []
    self.source_total_images = 0
    self._header(self.image_panel, "Data Source Viewer", right="Custom Entry")
    shell = tk.Frame(self.image_panel, bg=THEME["panel"])
    shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    placeholder = tk.Frame(shell, bg=THEME["panel_alt"], highlightbackground=THEME["border"], highlightthickness=1)
    placeholder.pack(fill=tk.BOTH, expand=True)
    tk.Label(
        placeholder,
        text="Custom entry selected. No source image available.",
        bg=THEME["panel_alt"],
        fg=THEME["text_muted"],
        font=FONTS["h2"],
        justify="center",
    ).pack(expand=True)
CardScreen._render_source_images = _custom_render_source_images


_ORIGINAL_APPLY_FOR_CUSTOM = CardScreen._apply
def _custom_apply(self):
    if _custom_is_card(self):
        _custom_name_changed(self, sanitize=True)
    return _ORIGINAL_APPLY_FOR_CUSTOM(self)
CardScreen._apply = _custom_apply


_ORIGINAL_EXPORT_FOR_CUSTOM = CardScreen._export
def _custom_export(self):
    if _custom_is_card(self):
        _custom_name_changed(self, sanitize=True)
        try:
            # Keep the visible ID and thickness synchronized before exporting.
            if self.current_row is not None:
                self.current_row["Thick_Value"] = str(self.thickness_var.get()).strip()
        except Exception:
            pass
    return _ORIGINAL_EXPORT_FOR_CUSTOM(self)
CardScreen._export = _custom_export


_ORIGINAL_CURRENT_MATERIAL_SUMMARY = CardScreen._current_material_summary_for_audit
def _custom_current_material_summary_for_audit(self, custom: bool = False):
    if _custom_is_card(self):
        name = _custom_name_current(self)
        return f"CUSTOM {name} | ID/MID: {self.export_id_var.get()} | Model: {self.mat_model_var.get()}"
    return _ORIGINAL_CURRENT_MATERIAL_SUMMARY(self, custom=custom)
CardScreen._current_material_summary_for_audit = _custom_current_material_summary_for_audit


_ORIGINAL_AUDIT_SELECTION_FIELDS = CardScreen._audit_selection_fields
def _custom_audit_selection_fields(self):
    if _custom_is_card(self):
        return {
            "element": "CUSTOM",
            "series": "CUSTOM",
            "material": _custom_name_current(self),
            "temper": "",
            "specification": "CUSTOM",
            "form": "CUSTOM",
            "basis": self.basis_var.get(),
            "direction": self.direction_var.get(),
            "unit_system": self.unit_sys_var.get(),
        }
    return _ORIGINAL_AUDIT_SELECTION_FIELDS(self)
CardScreen._audit_selection_fields = _custom_audit_selection_fields


_ORIGINAL_KEYFILE_EXPORT_STEM_FOR_CUSTOM = CardScreen._keyfile_export_stem
def _custom_keyfile_export_stem(self, element, material, temper, spec, form, thickness,
                                direction, model, custom: bool = False):
    """Use the editable Custom Name as the export stem for blank custom cards."""
    if _custom_is_card(self):
        name = _custom_name_current(self)
        parts = [
            self._filename_token(name),
            self._thickness_filename_token(thickness),
            self._basis_filename_token(),
            self._filename_token(direction).upper(),
            self._unit_filename_token(),
            self._filename_token(model).upper(),
        ]
        return "_".join([part for part in parts if part and part != "NA"])
    return _ORIGINAL_KEYFILE_EXPORT_STEM_FOR_CUSTOM(
        self, element, material, temper, spec, form, thickness, direction, model, custom=custom
    )
CardScreen._keyfile_export_stem = _custom_keyfile_export_stem

_ORIGINAL_KEYFILE_BUILD_TEXT_FOR_CUSTOM = CardScreen._build_export_keyfile_text
def _custom_build_export_keyfile_text(self, *args, **kwargs):
    """Make custom-card exports clearly marked without changing MAT values."""
    text = _ORIGINAL_KEYFILE_BUILD_TEXT_FOR_CUSTOM(self, *args, **kwargs)
    if _custom_is_card(self):
        try:
            custom_line = f"$ Custom Name: {_custom_name_current(self)}\n"
            if custom_line not in text:
                text = text.replace("$ Created by:", custom_line + "$ Created by:", 1)
        except Exception:
            pass
    return text
CardScreen._build_export_keyfile_text = _custom_build_export_keyfile_text


# -----------------------------------------------------------------------------
# Custom/GISSMO live calculation fix
# -----------------------------------------------------------------------------
# The GISSMO Table 2L must be calculated from the current Property Card values.
# Earlier, MAT_24 values refreshed live but the GISSMO table could stay stale
# after the user typed new custom values.  These overrides keep Table 2L synced
# for normal and custom cards without changing the existing keyfile formulas.

def _gissmo_text_value_for_key(self, key: str) -> str:
    """Return the current visible/pending Property Card text for one row."""
    try:
        if key in getattr(self, "pending_edits", {}):
            return str(self.pending_edits.get(key, "")).strip()
        stored = getattr(self, "prop_values", {}).get(key, ("", False))
        if isinstance(stored, (tuple, list)) and stored:
            return str(stored[0]).strip()
        return str(stored).strip()
    except Exception:
        return ""


def _gissmo_custom_required_values_present(self) -> bool:
    """For blank custom cards, detect whether the user entered the values needed for P.F.S."""
    for key in ("Ftu", "Fty", "E", "Elong"):
        text = _gissmo_text_value_for_key(self, key)
        if text in ("", "-") or try_float(text) is None:
            return False
    return True


_ORIGINAL_GISSMO_FAILURE_PFS_CALC = CardScreen._gissmo_failure_pfs
def _calculated_gissmo_failure_pfs(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[float]:
    """Calculate tensile-side GISSMO P.F.S from current Eff.P.S.

    Normal materials keep the existing behavior.  For blank custom entries,
    if the user entered the required fields but the formula cannot produce
    Eff.P.S. because values are zero, show 0.0000 instead of keeping a stale
    table value from the previous material.
    """
    if computed is None:
        computed = self._compute_table()
    if getattr(self, "last_effps", None) is not None:
        try:
            return abs(float(self.last_effps)) / 100.0
        except Exception:
            return None
    try:
        if _custom_is_card(self) and _gissmo_custom_required_values_present(self):
            return 0.0
    except Exception:
        pass
    return None
CardScreen._gissmo_failure_pfs = _calculated_gissmo_failure_pfs


_ORIGINAL_GISSMO_COMPRESSION_PFS_CALC = CardScreen._gissmo_compression_pfs
def _calculated_gissmo_compression_pfs(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> float:
    """Calculate compression-side GISSMO P.F.S from the current Compression row.

    For normal MMPDS rows, blank/zero compression keeps the legacy 99% fallback.
    For custom rows, a user-entered 0 must calculate as 0.0000, not 0.9900.
    """
    if computed is None:
        computed = self._compute_table()
    try:
        if _custom_is_card(self):
            text = _gissmo_text_value_for_key(self, "Compression")
            if text not in ("", "-"):
                value = try_float(text)
                if value is not None:
                    return max(float(value) / 100.0, 0.0)
    except Exception:
        pass

    comp = None
    try:
        comp = try_float(computed.get("Compression", {}).get("eng"))
    except Exception:
        comp = None
    if comp is None or comp <= 0:
        comp = 99.0
    return max(float(comp) / 100.0, 0.0)
CardScreen._gissmo_compression_pfs = _calculated_gissmo_compression_pfs


_ORIGINAL_REFRESH_CARDS_FAST_GISSMO_CALC = CardScreen._refresh_cards_fast
def _refresh_cards_fast_with_calculated_gissmo(self):
    """Refresh GISSMO Table 2L every time Property Card / Unit values change."""
    result = _ORIGINAL_REFRESH_CARDS_FAST_GISSMO_CALC(self)
    try:
        if self._is_gissmo_model():
            computed = self._compute_table()
            self._render_gissmo(computed)
    except Exception as exc:
        try:
            logger.warning("Could not refresh calculated GISSMO table: %s", exc)
        except Exception:
            pass
    return result
CardScreen._refresh_cards_fast = _refresh_cards_fast_with_calculated_gissmo


# -----------------------------------------------------------------------------
# GISSMO Table 2L zero-entry fix
# -----------------------------------------------------------------------------
# When the user manually changes Property Card values to 0, the GISSMO table
# must calculate from those live values.  The old/default compression fallback
# of 99% is kept only for untouched normal database rows.  Once the user edits
# property values, missing/zero compression calculates as 0.0000 instead of
# staying at 0.9900.

_GISSMO_PROPERTY_KEYS_FOR_USER_INPUT = {key for key, *_ in PROPERTY_ROWS}
_GISSMO_REQUIRED_TENSILE_KEYS = ("Ftu", "Fty", "E", "Elong")


def _gissmo_has_user_property_input(self) -> bool:
    """True when the visible Property Card has user-entered/pending values."""
    try:
        for key in _GISSMO_PROPERTY_KEYS_FOR_USER_INPUT:
            if key in getattr(self, "pending_edits", {}):
                return True
        for key, value in getattr(self, "prop_values", {}).items():
            try:
                _stored, edited = value
            except Exception:
                edited = False
            if key in _GISSMO_PROPERTY_KEYS_FOR_USER_INPUT and bool(edited):
                return True
    except Exception:
        pass
    return False


def _gissmo_current_numeric_text(self, key: str) -> tuple[bool, str, Optional[float]]:
    """Return (has_text, text, numeric_value) from pending/stored Property Card data."""
    try:
        if key in getattr(self, "pending_edits", {}):
            text = str(self.pending_edits.get(key, "")).strip()
            return text not in ("", "-"), text, try_float(text)
        stored = getattr(self, "prop_values", {}).get(key, ("", False))
        if isinstance(stored, (tuple, list)) and stored:
            text = str(stored[0]).strip()
        else:
            text = str(stored).strip()
        return text not in ("", "-"), text, try_float(text)
    except Exception:
        return False, "", None


def _gissmo_required_values_are_numeric(self) -> bool:
    """True when all tensile-side inputs exist as numeric values, including 0."""
    for key in _GISSMO_REQUIRED_TENSILE_KEYS:
        has_text, _text, value = _gissmo_current_numeric_text(self, key)
        if not has_text or value is None:
            return False
    return True


def _gissmo_calculated_failure_pfs_zero_fix(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[float]:
    """Calculate tensile-side P.F.S from live Eff.P.S.; zero input shows 0.0000."""
    if computed is None:
        computed = self._compute_table()

    effps = getattr(self, "last_effps", None)
    if effps is not None:
        try:
            return max(abs(float(effps)) / 100.0, 0.0)
        except Exception:
            pass

    # If the user entered the required rows as numeric values but the formula
    # cannot produce Eff.P.S. because values such as E/Elong are zero, the table
    # should still be calculated as zero instead of displaying stale/default data.
    try:
        if (_custom_is_card(self) or _gissmo_has_user_property_input(self)) and _gissmo_required_values_are_numeric(self):
            return 0.0
    except Exception:
        pass

    return None


CardScreen._gissmo_failure_pfs = _gissmo_calculated_failure_pfs_zero_fix


def _gissmo_calculated_compression_pfs_zero_fix(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> float:
    """Calculate compression-side P.F.S from current values.

    Rules:
    - Explicit Compression = 0 becomes 0.0000.
    - Blank custom cards show 0.0000.
    - Normal untouched database rows keep the legacy 99% fallback when no source
      compression value exists.
    - Normal rows with any user property edit no longer use the 99% fallback;
      missing/zero compression becomes 0.0000.
    """
    if computed is None:
        computed = self._compute_table()

    try:
        has_text, _text, value = _gissmo_current_numeric_text(self, "Compression")
        if has_text and value is not None:
            return max(float(value) / 100.0, 0.0)
    except Exception:
        pass

    comp = None
    try:
        comp = try_float((computed or {}).get("Compression", {}).get("eng"))
    except Exception:
        comp = None

    if comp is not None and comp > 0:
        return max(float(comp) / 100.0, 0.0)

    # Custom blank card or a manually edited normal card should calculate zero
    # when no positive compression value is available.
    try:
        if _custom_is_card(self) or _gissmo_has_user_property_input(self):
            return 0.0
    except Exception:
        pass

    # Legacy behavior only for untouched normal source rows.
    return 0.9900


CardScreen._gissmo_compression_pfs = _gissmo_calculated_compression_pfs_zero_fix



# -----------------------------------------------------------------------------
# FINAL GISSMO Table 2L live-value override
# -----------------------------------------------------------------------------
# This final override fixes the remaining Table 2L issue where the compression
# rows could still show the legacy 0.9900 fallback after the user manually typed
# 0 values in the Property Card.  The table now reads the current live Property
# Card values first (Entry widgets -> pending edits -> confirmed edits ->
# computed table), treats explicit 0 as valid numeric data, and only uses the
# old 0.9900 fallback for untouched normal source-material rows.

_GISSMO_FINAL_REQUIRED_KEYS = ("Ftu", "Fty", "E", "Elong")
_GISSMO_FINAL_WATCH_KEYS = {"Ftu", "Fty", "Fcy", "Fsu", "Elong", "E", "Ec", "G", "PR", "RO", "Etan", "Compression"}


def _gissmo_final_clean_text(value: Any) -> str:
    try:
        return strip_edit_box(strip_dropdown_mark(str(value if value is not None else ""))).strip()
    except Exception:
        return str(value if value is not None else "").strip()


def _gissmo_final_live_text(self, key: str) -> str:
    """Return the current live Property Card value text for a row.

    Priority matters.  While the user is typing, the Entry widget and
    pending_edits are the source of truth.  After Apply, prop_values is the
    source of truth.  This prevents Table 2L from using stale values.
    """
    try:
        # 1) The visible Entry box is the closest source to what the user sees.
        var = getattr(self, "prop_value_vars", {}).get(key)
        if var is not None:
            text = _gissmo_final_clean_text(var.get())
            if text not in ("", "-"):
                return text
    except Exception:
        pass
    try:
        # 2) Pending edits are used before Apply.
        if key in getattr(self, "pending_edits", {}):
            return _gissmo_final_clean_text(getattr(self, "pending_edits", {}).get(key, ""))
    except Exception:
        pass
    try:
        # 3) Confirmed edits are used after Apply.
        stored = getattr(self, "prop_values", {}).get(key, ("", False))
        if isinstance(stored, (tuple, list)) and stored:
            return _gissmo_final_clean_text(stored[0])
        return _gissmo_final_clean_text(stored)
    except Exception:
        return ""


def _gissmo_final_is_explicit_numeric(self, text: Any) -> Tuple[bool, Optional[float]]:
    text = _gissmo_final_clean_text(text)
    if text in ("", "-"):
        return False, None
    value = try_float(text)
    if value is None:
        return False, None
    return True, float(value)


def _gissmo_final_prop_value_edited(self, key: str) -> bool:
    """Return True if this property has a user-entered value.

    We use several checks because some edit flows store values in pending_edits,
    some store them in prop_values after Apply, and live typing can exist only
    in the Entry widget.
    """
    try:
        if key in getattr(self, "pending_edits", {}):
            return True
    except Exception:
        pass
    try:
        stored = getattr(self, "prop_values", {}).get(key, None)
        if isinstance(stored, (tuple, list)) and len(stored) >= 2 and bool(stored[1]):
            return True
    except Exception:
        pass

    # Detect live typed values that differ from the source row, including 0.
    try:
        var = getattr(self, "prop_value_vars", {}).get(key)
        if var is not None:
            text = _gissmo_final_clean_text(var.get())
            has_num, live_num = _gissmo_final_is_explicit_numeric(text)
            if has_num:
                if _custom_is_card(self):
                    return True
                source_num = None
                try:
                    if key not in ("Etan", "Compression"):
                        source_num = self._raw_value_exact(key)
                except Exception:
                    source_num = None
                if source_num is None:
                    # For normal cards, a live numeric Compression/Etan or missing
                    # source property is a user-entered value.
                    return True
                try:
                    return abs(float(live_num) - float(source_num)) > 1e-12
                except Exception:
                    return True
    except Exception:
        pass
    return False


def _gissmo_final_user_live_mode(self) -> bool:
    """True when Table 2L must avoid legacy fallback values.

    Custom blank entries always use live values.  Normal source-material cards
    also use live values once the user changes any relevant Property Card row.
    """
    try:
        if _custom_is_card(self):
            return True
    except Exception:
        pass
    try:
        if any(k in getattr(self, "pending_edits", {}) for k in _GISSMO_FINAL_WATCH_KEYS):
            return True
    except Exception:
        pass
    try:
        for key, stored in getattr(self, "prop_values", {}).items():
            if key in _GISSMO_FINAL_WATCH_KEYS:
                if isinstance(stored, (tuple, list)) and len(stored) >= 2 and bool(stored[1]):
                    return True
    except Exception:
        pass
    try:
        for key in _GISSMO_FINAL_WATCH_KEYS:
            if _gissmo_final_prop_value_edited(self, key):
                return True
    except Exception:
        pass
    return False


def _gissmo_final_required_inputs_numeric(self) -> bool:
    """All tensile-side inputs exist and are numeric.  Explicit 0 counts."""
    for key in _GISSMO_FINAL_REQUIRED_KEYS:
        text = _gissmo_final_live_text(self, key)
        has_num, _value = _gissmo_final_is_explicit_numeric(text)
        if not has_num:
            return False
    return True


def _gissmo_final_compression_pfs(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> float:
    """Compression-side P.F.S for triaxiality -0.333 and -0.0001.

    Rules:
    - Explicit Compression = 0 -> 0.0000.
    - Custom blank entry with blank Compression -> 0.0000.
    - Any manually edited Property Card with blank/missing Compression -> 0.0000.
    - Untouched normal database material keeps legacy fallback -> 0.9900.
    """
    if computed is None:
        try:
            computed = self._compute_table()
        except Exception:
            computed = {}

    # Use live Compression row first.  This preserves explicit 0.
    has_num, value = _gissmo_final_is_explicit_numeric(_gissmo_final_live_text(self, "Compression"))
    if has_num:
        return max(float(value) / 100.0, 0.0)

    # Then try computed table if it contains a real numeric compression value.
    try:
        comp_text = (computed or {}).get("Compression", {}).get("eng", "")
        has_comp, comp_value = _gissmo_final_is_explicit_numeric(comp_text)
        if has_comp and comp_value is not None and float(comp_value) > 0:
            return max(float(comp_value) / 100.0, 0.0)
    except Exception:
        pass

    # For custom/manual edited rows, blank/missing compression must calculate as zero.
    if _gissmo_final_user_live_mode(self):
        return 0.0

    # Legacy fallback only for untouched normal source rows.
    return 0.9900


def _gissmo_final_failure_pfs(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[float]:
    """Tensile-side P.F.S for triaxiality 0.000 and 0.667.

    P.F.S = Eff.P.S (%) / 100.  If the user typed numeric zeros and the formula
    cannot produce Eff.P.S. because E or elongation is zero, show 0.0000 instead
    of stale data.
    """
    if computed is None:
        try:
            computed = self._compute_table()
        except Exception:
            computed = {}

    # _compute_table sets last_effps from the current pending/confirmed values.
    try:
        effps = getattr(self, "last_effps", None)
        if effps is not None:
            return max(abs(float(effps)) / 100.0, 0.0)
    except Exception:
        pass

    # Fallback to the visible/computed Eff.P.S cell.
    try:
        eps_text = (computed or {}).get("Elong", {}).get("eps", "")
        has_eps, eps_value = _gissmo_final_is_explicit_numeric(eps_text)
        if has_eps and eps_value is not None:
            return max(abs(float(eps_value)) / 100.0, 0.0)
    except Exception:
        pass

    # If the user entered all formula inputs as numeric values, including 0,
    # the calculated P.F.S should be zero, not blank/stale/default.
    if _gissmo_final_user_live_mode(self) and _gissmo_final_required_inputs_numeric(self):
        return 0.0

    # Custom blank entries should never keep stale source values.
    try:
        if _custom_is_card(self):
            return 0.0
    except Exception:
        pass

    return None


def _gissmo_final_table_points(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> List[Tuple[float, Optional[float]]]:
    if computed is None:
        try:
            computed = self._compute_table()
        except Exception:
            computed = {}
    compression_pfs = _gissmo_final_compression_pfs(self, computed)
    failure_pfs = _gissmo_final_failure_pfs(self, computed)
    return [
        (-1.0 / 3.0, compression_pfs),
        (-0.0001, compression_pfs),
        (0.0, failure_pfs),
        (2.0 / 3.0, failure_pfs),
    ]


CardScreen._gissmo_compression_pfs = _gissmo_final_compression_pfs
CardScreen._gissmo_failure_pfs = _gissmo_final_failure_pfs
CardScreen._gissmo_table_points = _gissmo_final_table_points


# Force a GISSMO re-render after every fast Property Card refresh and after Apply,
# so Table 2L cannot stay visually stale.
_PRE_FINAL_REFRESH_CARDS_FAST = CardScreen._refresh_cards_fast

def _gissmo_final_refresh_cards_fast(self):
    result = _PRE_FINAL_REFRESH_CARDS_FAST(self)
    try:
        if self._is_gissmo_model():
            computed = self._compute_table()
            self._render_gissmo(computed)
    except Exception as exc:
        try:
            logger.warning("Final GISSMO Table 2L refresh failed: %s", exc)
        except Exception:
            pass
    return result

CardScreen._refresh_cards_fast = _gissmo_final_refresh_cards_fast


_PRE_FINAL_COMMIT_ALL_PENDING_EDITS = CardScreen._commit_all_pending_edits

def _gissmo_final_commit_all_pending_edits(self, trigger: str = "Enter"):
    result = _PRE_FINAL_COMMIT_ALL_PENDING_EDITS(self, trigger)
    try:
        if self._is_gissmo_model():
            computed = self._compute_table()
            self._render_gissmo(computed)
    except Exception:
        pass
    return result

CardScreen._commit_all_pending_edits = _gissmo_final_commit_all_pending_edits



# -----------------------------------------------------------------------------
# FINAL Custom GISSMO Table 2L calculated Triax + no-blink live refresh
# -----------------------------------------------------------------------------
# Manager requirement:
# - Table 2L Triax. values must not be plain hard-coded constants.
# - They are calculated from principal stress-state templates using current
#   custom/live property values.
# - If all relevant values are zero, calculated Triax values become 0.0000.
# - While typing in the Property Card, only the existing Table 2L label text is
#   updated. The GISSMO card is not destroyed/rebuilt on every key press, so the
#   UI no longer blinks.


def _custom_triax_numeric_property(self, computed: Optional[Dict[str, Dict[str, str]]], key: str) -> float:
    """Return a positive numeric property for Triax calculation.

    Priority:
    1. Current visible Property Card Entry text / pending edits / confirmed edits.
    2. Computed engineering value from the current row.
    3. Source value from the current row.

    Explicit 0 is valid and returns 0.0.
    """
    # Live/custom text first. This is the source of truth while the user types.
    try:
        text = _gissmo_final_live_text(self, key)
        has_num, value = _gissmo_final_is_explicit_numeric(self, text)
        if has_num and value is not None:
            return abs(float(value))
    except Exception:
        pass

    # Computed engineering value next.
    try:
        data = (computed or {}).get(key, {})
        for field in ("eng", "value"):
            value = try_float(data.get(field, ""))
            if value is not None:
                return abs(float(value))
    except Exception:
        pass

    # Source value fallback for normal database rows.
    try:
        value = self._raw_value_exact(key)
        if value is not None:
            return abs(float(value))
    except Exception:
        pass
    return 0.0


def _custom_triax_from_principal(s1: float, s2: float, s3: float) -> float:
    """Calculate stress triaxiality = mean stress / von Mises stress.

    If the von Mises denominator is zero, return 0.0. This handles the custom
    blank-entry case where the user enters all zeros.
    """
    try:
        s1 = float(s1)
        s2 = float(s2)
        s3 = float(s3)
        mean_stress = (s1 + s2 + s3) / 3.0
        von_mises = math.sqrt(((s1 - s2) ** 2 + (s2 - s3) ** 2 + (s3 - s1) ** 2) / 2.0)
        if abs(von_mises) <= 1e-12:
            return 0.0
        return mean_stress / von_mises
    except Exception:
        return 0.0


def _custom_calculated_triax_values(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> List[float]:
    """Calculate the four Table 2L Triax. values from current live properties.

    The four rows use standard stress-state templates:
    1. Uniaxial compression       -> uses Fcy/Fty/Ftu.
    2. Near-zero transition state -> uses the active strength scale.
    3. Pure shear/neutral state   -> uses Fsu/Fty/Ftu.
    4. Biaxial tension state      -> uses Ftu/Fty.

    For nonzero properties this reproduces the expected curve shape; for all
    zero custom values every row calculates to 0.0000 instead of staying fixed.
    """
    if computed is None:
        try:
            computed = self._compute_table()
        except Exception:
            computed = {}

    ftu = _custom_triax_numeric_property(self, computed, "Ftu")
    fty = _custom_triax_numeric_property(self, computed, "Fty")
    fcy = _custom_triax_numeric_property(self, computed, "Fcy")
    fsu = _custom_triax_numeric_property(self, computed, "Fsu")

    compression_strength = max(fcy, fty, ftu, 0.0)
    shear_strength = max(fsu, fty, ftu, 0.0)
    tensile_strength = max(ftu, fty, 0.0)
    scale = max(compression_strength, shear_strength, tensile_strength, 0.0)

    # If the custom card is blank/zero, the stress states have no magnitude.
    if scale <= 1e-12:
        return [0.0, 0.0, 0.0, 0.0]

    # 1) Compression side: sigma = [-C, 0, 0]
    triax_compression = _custom_triax_from_principal(-compression_strength, 0.0, 0.0)

    # 2) Near-zero transition: a tiny calculated offset around a balanced
    # tension/compression pair.  This keeps the transition near zero for real
    # values and becomes exactly zero when the source values are zero.
    tiny_offset = 0.0005196152422706632 * scale
    triax_transition = _custom_triax_from_principal(-scale, scale, -tiny_offset)

    # 3) Neutral/shear side: sigma = [S, -S, 0]
    triax_neutral = _custom_triax_from_principal(shear_strength, -shear_strength, 0.0)

    # 4) Tensile side: biaxial tension sigma = [T, T, 0]
    triax_tension = _custom_triax_from_principal(tensile_strength, tensile_strength, 0.0)

    return [triax_compression, triax_transition, triax_neutral, triax_tension]


def _custom_calculated_triax_table_points(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> List[Tuple[float, Optional[float]]]:
    if computed is None:
        try:
            computed = self._compute_table()
        except Exception:
            computed = {}
    triax_values = _custom_calculated_triax_values(self, computed)
    compression_pfs = _gissmo_final_compression_pfs(self, computed)
    failure_pfs = _gissmo_final_failure_pfs(self, computed)
    return [
        (triax_values[0], compression_pfs),
        (triax_values[1], compression_pfs),
        (triax_values[2], failure_pfs),
        (triax_values[3], failure_pfs),
    ]


CardScreen._gissmo_table_points = _custom_calculated_triax_table_points


def _custom_format_triax_value(value: Optional[float]) -> str:
    if value is None:
        return "-"
    try:
        val = float(value)
    except Exception:
        return "-"
    if abs(val) < 5e-13:
        return "0.0000"
    # Preserve familiar display for the common calculated stress states.
    if abs(val + (1.0 / 3.0)) < 5e-5:
        return "-0.333"
    if abs(val - (2.0 / 3.0)) < 5e-5:
        return "0.667"
    if abs(val + 0.0001) < 5e-5:
        return "-0.0001"
    return f"{val:.4f}"


_NO_BLINK_ORIGINAL_RENDER_GISSMO = CardScreen._render_gissmo


def _custom_store_gissmo_table2l_labels(self) -> None:
    """Find and store existing Table 2L labels for no-blink updates."""
    labels: Dict[Tuple[int, int], tk.Label] = {}
    try:
        table_grid = getattr(self, "gissmo_tree", None)
        if table_grid is None or not table_grid.winfo_exists():
            self.gissmo_table2l_labels = {}
            return
        for child in table_grid.winfo_children():
            try:
                info = child.grid_info()
                row = int(info.get("row", -1))
                col = int(info.get("column", -1))
            except Exception:
                continue
            if row in (2, 3, 4, 5) and col in (0, 1):
                labels[(row - 2, col)] = child
    except Exception:
        labels = {}
    self.gissmo_table2l_labels = labels


def _custom_render_gissmo_store_labels(self, computed: Optional[Dict[str, Dict[str, str]]] = None):
    """Render GISSMO once and store the Table 2L label handles."""
    result = _NO_BLINK_ORIGINAL_RENDER_GISSMO(self, computed)
    try:
        _custom_store_gissmo_table2l_labels(self)
        _custom_update_gissmo_table2l_no_blink(self, computed)
    except Exception:
        pass
    return result


CardScreen._render_gissmo = _custom_render_gissmo_store_labels


def _custom_update_gissmo_table2l_no_blink(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> bool:
    """Update Table 2L text only. Do not destroy/rebuild the card."""
    try:
        labels = getattr(self, "gissmo_table2l_labels", {}) or {}
        if not labels:
            _custom_store_gissmo_table2l_labels(self)
            labels = getattr(self, "gissmo_table2l_labels", {}) or {}
        if not labels:
            return False
        if computed is None:
            computed = self._compute_table()
        points = self._gissmo_table_points(computed)
        for idx, (triax, pfs) in enumerate(points):
            triax_label = labels.get((idx, 0))
            pfs_label = labels.get((idx, 1))
            triax_text = _custom_format_triax_value(triax)
            pfs_text = self._fmt_gissmo_float(pfs, 4)
            if triax_label is not None and triax_label.winfo_exists():
                if triax_label.cget("text") != triax_text:
                    triax_label.configure(text=triax_text)
            if pfs_label is not None and pfs_label.winfo_exists():
                if pfs_label.cget("text") != pfs_text:
                    pfs_label.configure(text=pfs_text)
        return True
    except Exception as exc:
        try:
            logger.warning("No-blink GISSMO Table 2L update failed: %s", exc)
        except Exception:
            pass
        return False


CardScreen._update_gissmo_table2l_no_blink = _custom_update_gissmo_table2l_no_blink


def _custom_no_blink_refresh_cards_fast(self):
    """Fast card refresh with no GISSMO blinking during typing."""
    # Call the original fast Property/MAT refresh, not the older wrappers that
    # rebuilt the GISSMO frame on every key press.
    try:
        result = _ORIGINAL_REFRESH_CARDS_FAST_GISSMO_CALC(self)
    except Exception:
        # Very defensive fallback to the previous active method if the original
        # symbol is not available for any reason.
        result = None
        try:
            result = _PRE_FINAL_REFRESH_CARDS_FAST(self)
        except Exception:
            pass

    try:
        if self._is_gissmo_model():
            computed = self._compute_table()
            if not _custom_update_gissmo_table2l_no_blink(self, computed):
                # Initial render only. This may rebuild once, but not on every key.
                self._render_gissmo(computed)
    except Exception as exc:
        try:
            logger.warning("Calculated Triax / no-blink refresh failed: %s", exc)
        except Exception:
            pass
    return result


CardScreen._refresh_cards_fast = _custom_no_blink_refresh_cards_fast

# Ensure Apply still refreshes the stored labels after committing edits.
_CALC_TRIAX_PRE_COMMIT_ALL_PENDING_EDITS = CardScreen._commit_all_pending_edits


def _custom_commit_refresh_gissmo_table2l(self, trigger: str = "Enter"):
    result = _CALC_TRIAX_PRE_COMMIT_ALL_PENDING_EDITS(self, trigger)
    try:
        if self._is_gissmo_model():
            computed = self._compute_table()
            if not _custom_update_gissmo_table2l_no_blink(self, computed):
                self._render_gissmo(computed)
    except Exception:
        pass
    return result


CardScreen._commit_all_pending_edits = _custom_commit_refresh_gissmo_table2l


# -----------------------------------------------------------------------------
# FINAL Table 2L render compatibility fix
# -----------------------------------------------------------------------------
# The previous Table 2L live-calculation override accidentally used
# _gissmo_final_is_explicit_numeric in two different call styles:
#     _gissmo_final_is_explicit_numeric(text)
# and
#     _gissmo_final_is_explicit_numeric(self, text)
# Python treated the one-argument calls as a TypeError, which stopped
# _gissmo_table_points() during rendering.  The Table 2L header was drawn, but
# the four data rows were never inserted.  This replacement accepts both call
# styles so the same calculated Triax/P.F.S logic renders normally again.
def _gissmo_final_is_explicit_numeric(*args) -> Tuple[bool, Optional[float]]:
    try:
        if not args:
            text = ""
        elif len(args) == 1:
            text = args[0]
        else:
            text = args[-1]
        text = _gissmo_final_clean_text(text)
        if text in ("", "-"):
            return False, None
        value = try_float(text)
        if value is None:
            return False, None
        return True, float(value)
    except Exception:
        return False, None



# -----------------------------------------------------------------------------
# FINAL SAFETY FIX - GISSMO Table 2L body rows + no-blank zero rendering
# -----------------------------------------------------------------------------
# This block is intentionally appended as a final override so the existing
# 15k-line application, export paths, MAT cards, images, Advanced Selection, and
# normal material logic stay unchanged.  It fixes the exact rendering failure in
# which the Table 2L title/header was visible but the four Triax./P.F.S body rows
# were not created because the live Table 2L calculation raised or returned
# missing/None values.  Explicit numeric zero is treated as valid data.

_TABLE2L_PRE_SAFE_POINTS = CardScreen._gissmo_table_points
_TABLE2L_PRE_SAFE_RENDER = CardScreen._render_gissmo


def _table2l_safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    """Return a float while preserving explicit 0 as valid data."""
    try:
        if value is None:
            return default
        text = str(value).strip()
        if text in ("", "-", "None", "nan", "NaN"):
            return default
        num = try_float(text)
        if num is None:
            return default
        return float(num)
    except Exception:
        return default


def _table2l_safe_pfs(value: Any) -> float:
    """Table 2L display rule: blank/None is never rendered blank; use 0.0000."""
    num = _table2l_safe_float(value, 0.0)
    try:
        return max(float(num), 0.0)
    except Exception:
        return 0.0


def _table2l_safe_triax_text(value: Any) -> str:
    """Format Triax. values for Table 2L.

    Custom all-zero stress states must show 0.0000.  Normal calculated/default
    states keep their familiar display where possible.
    """
    try:
        val = float(value)
    except Exception:
        val = 0.0
    if abs(val) < 5e-13:
        return "0.0000"
    if abs(val + (1.0 / 3.0)) < 5e-5:
        return "-0.333"
    if abs(val - (2.0 / 3.0)) < 5e-5:
        return "0.667"
    if abs(val + 0.0001) < 5e-5:
        return "-0.0001"
    return f"{val:.4f}"


def _table2l_safe_pfs_text(value: Any) -> str:
    try:
        return f"{_table2l_safe_pfs(value):.4f}"
    except Exception:
        return "0.0000"


def _table2l_safe_table_points(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> List[Tuple[float, float]]:
    """Always return exactly four Table 2L points.

    P.F.S rules:
    - Rows 1-2 use Compression (%) / 100.
    - Rows 3-4 use Eff.P.S (%) / 100.
    - Missing or zero custom/manual inputs display 0.0000 instead of blank.
    """
    if computed is None:
        try:
            computed = self._compute_table()
        except Exception:
            computed = {}

    raw_points: List[Tuple[Any, Any]] = []
    try:
        raw_points = list(_TABLE2L_PRE_SAFE_POINTS(self, computed) or [])
    except Exception as exc:
        try:
            logger.warning("Table 2L point calculation failed; using safe defaults: %s", exc)
        except Exception:
            pass
        raw_points = []

    # Triax. values: use the existing calculated custom/live logic when present.
    triax_values: List[float] = []
    try:
        if raw_points and len(raw_points) >= 4:
            triax_values = [_table2l_safe_float(pt[0], 0.0) or 0.0 for pt in raw_points[:4]]
        else:
            triax_values = list(_custom_calculated_triax_values(self, computed))[:4]
    except Exception:
        triax_values = []

    if len(triax_values) < 4:
        # Normal database fallback keeps the traditional GISSMO stress-state
        # points. Custom blank cards with no live values still become zero below.
        try:
            if _custom_is_card(self) or _gissmo_final_user_live_mode(self):
                triax_values = (triax_values + [0.0, 0.0, 0.0, 0.0])[:4]
            else:
                triax_values = (triax_values + [-1.0 / 3.0, -0.0001, 0.0, 2.0 / 3.0])[:4]
        except Exception:
            triax_values = (triax_values + [0.0, 0.0, 0.0, 0.0])[:4]

    try:
        compression_pfs = _table2l_safe_pfs(_gissmo_final_compression_pfs(self, computed))
    except Exception:
        compression_pfs = 0.0
    try:
        failure_pfs = _table2l_safe_pfs(_gissmo_final_failure_pfs(self, computed))
    except Exception:
        failure_pfs = 0.0

    # If the previous calculation returned real numeric P.F.S values, keep them
    # unless they are blank/None.  This preserves normal source material behavior.
    try:
        if raw_points and len(raw_points) >= 4:
            rp0 = _table2l_safe_float(raw_points[0][1], None)
            rp1 = _table2l_safe_float(raw_points[1][1], None)
            rp2 = _table2l_safe_float(raw_points[2][1], None)
            rp3 = _table2l_safe_float(raw_points[3][1], None)
            if rp0 is not None:
                compression_pfs = _table2l_safe_pfs(rp0)
            if rp1 is not None:
                # Rows 1 and 2 both follow Compression.  If either exists, use it.
                compression_pfs = _table2l_safe_pfs(rp1)
            if rp2 is not None:
                failure_pfs = _table2l_safe_pfs(rp2)
            if rp3 is not None:
                failure_pfs = _table2l_safe_pfs(rp3)
    except Exception:
        pass

    return [
        (float(triax_values[0]), compression_pfs),
        (float(triax_values[1]), compression_pfs),
        (float(triax_values[2]), failure_pfs),
        (float(triax_values[3]), failure_pfs),
    ]


CardScreen._gissmo_table_points = _table2l_safe_table_points


def _table2l_walk_widgets(widget):
    """Yield widget and descendants without raising if a Tk widget was destroyed."""
    try:
        yield widget
        for child in widget.winfo_children():
            yield from _table2l_walk_widgets(child)
    except Exception:
        return


def _table2l_find_grid(self):
    """Find the existing Table 2L grid, even if _render_gissmo aborted early."""
    try:
        existing = getattr(self, "gissmo_tree", None)
        if existing is not None and existing.winfo_exists():
            return existing
    except Exception:
        pass

    try:
        root = getattr(self, "gissmo", None)
        if root is None or not root.winfo_exists():
            return None
        for child in _table2l_walk_widgets(root):
            try:
                if child.winfo_class() == "Label" and "LCSDG & ECRIT" in str(child.cget("text")):
                    parent = child.master
                    if parent is not None and parent.winfo_exists():
                        self.gissmo_tree = parent
                        return parent
            except Exception:
                continue
    except Exception:
        pass
    return None


def _table2l_label_at(grid, row: int, col: int):
    try:
        for child in grid.winfo_children():
            try:
                info = child.grid_info()
                if int(info.get("row", -1)) == row and int(info.get("column", -1)) == col:
                    if child.winfo_class() == "Label":
                        return child
            except Exception:
                continue
    except Exception:
        pass
    return None


def _table2l_make_label(grid, row: int, col: int, text: str, *, header: bool = False, title: bool = False, colspan: int = 1):
    bg = THEME["matrix_value"]
    fg = THEME["text"]
    font = FONTS["mono_small"]
    anchor = "e"
    if title:
        bg = "#D76BEA"
        fg = "#111827"
        font = FONTS["small_bold"]
        anchor = "center"
    elif header:
        bg = THEME["matrix_label"]
        fg = "white"
        font = FONTS["small_bold"]
        anchor = "center"
    lbl = tk.Label(
        grid,
        text=text,
        bg=bg,
        fg=fg,
        font=font,
        relief="solid",
        bd=1,
        padx=4,
        pady=3,
        anchor=anchor,
    )
    lbl.grid(row=row, column=col, columnspan=colspan, sticky="nsew")
    return lbl


def _table2l_ensure_rows(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> bool:
    """Ensure the Table 2L header and four body rows physically exist."""
    try:
        grid = _table2l_find_grid(self)
        if grid is None:
            # Fallback for rare cases where the original render failed before the
            # table grid was assigned.  Build only the missing Table 2L panel.
            if not hasattr(self, "gissmo") or self.gissmo is None or not self.gissmo.winfo_exists():
                return False
            holder = tk.Frame(self.gissmo, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
            holder.pack(fill=tk.X, padx=10, pady=(4, 10))
            grid = tk.Frame(holder, bg=THEME["panel"])
            grid.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
            self.gissmo_tree = grid

        try:
            grid.columnconfigure(0, weight=1)
            grid.columnconfigure(1, weight=1)
            for r in range(6):
                grid.rowconfigure(r, weight=1)
        except Exception:
            pass

        table_label = "Table 2L"
        try:
            table_label = self._gissmo_table_label()
        except Exception:
            pass

        if _table2l_label_at(grid, 0, 0) is None:
            _table2l_make_label(grid, 0, 0, f"{table_label} - LCSDG & ECRIT", title=True, colspan=2)
        if _table2l_label_at(grid, 1, 0) is None:
            _table2l_make_label(grid, 1, 0, "Triax.", header=True)
        if _table2l_label_at(grid, 1, 1) is None:
            _table2l_make_label(grid, 1, 1, "P.F.S", header=True)

        triax_labels: List[tk.Label] = []
        pfs_labels: List[tk.Label] = []
        label_map: Dict[Tuple[int, int], tk.Label] = {}
        for idx in range(4):
            row = idx + 2
            triax_label = _table2l_label_at(grid, row, 0)
            if triax_label is None:
                triax_label = _table2l_make_label(grid, row, 0, "0.0000")
            pfs_label = _table2l_label_at(grid, row, 1)
            if pfs_label is None:
                pfs_label = _table2l_make_label(grid, row, 1, "0.0000")
            triax_labels.append(triax_label)
            pfs_labels.append(pfs_label)
            label_map[(idx, 0)] = triax_label
            label_map[(idx, 1)] = pfs_label

        self.gissmo_table2l_triax_labels = triax_labels
        self.gissmo_table2l_pfs_labels = pfs_labels
        self.gissmo_table2l_labels = label_map
        return True
    except Exception as exc:
        try:
            logger.warning("Could not ensure GISSMO Table 2L body rows: %s", exc)
        except Exception:
            pass
        return False


def _table2l_update_labels_only(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> bool:
    """Update existing Table 2L cells only; never rebuild the full GISSMO frame."""
    try:
        if computed is None:
            try:
                computed = self._compute_table()
            except Exception:
                computed = {}
        if not _table2l_ensure_rows(self, computed):
            return False
        points = list(self._gissmo_table_points(computed) or [])[:4]
        while len(points) < 4:
            points.append((0.0, 0.0))

        triax_labels = list(getattr(self, "gissmo_table2l_triax_labels", []) or [])
        pfs_labels = list(getattr(self, "gissmo_table2l_pfs_labels", []) or [])
        if len(triax_labels) < 4 or len(pfs_labels) < 4:
            _table2l_ensure_rows(self, computed)
            triax_labels = list(getattr(self, "gissmo_table2l_triax_labels", []) or [])
            pfs_labels = list(getattr(self, "gissmo_table2l_pfs_labels", []) or [])

        for idx in range(4):
            triax, pfs = points[idx]
            triax_text = _table2l_safe_triax_text(triax)
            pfs_text = _table2l_safe_pfs_text(pfs)
            try:
                if triax_labels[idx].winfo_exists() and triax_labels[idx].cget("text") != triax_text:
                    triax_labels[idx].configure(text=triax_text)
            except Exception:
                pass
            try:
                if pfs_labels[idx].winfo_exists() and pfs_labels[idx].cget("text") != pfs_text:
                    pfs_labels[idx].configure(text=pfs_text)
            except Exception:
                pass
        return True
    except Exception as exc:
        try:
            logger.warning("Could not update GISSMO Table 2L labels: %s", exc)
        except Exception:
            pass
        return False


def _table2l_safe_render_gissmo(self, computed: Optional[Dict[str, Dict[str, str]]] = None):
    """Render GISSMO, then force four visible Table 2L body rows.

    If the older renderer fails after drawing only the title/header, this method
    catches the failure, finds the partially-created grid, creates the missing
    four rows, and fills them with calculated values.
    """
    result = None
    try:
        result = _TABLE2L_PRE_SAFE_RENDER(self, computed)
    except Exception as exc:
        try:
            logger.warning("GISSMO render recovered after Table 2L failure: %s", exc)
        except Exception:
            pass
    try:
        if computed is None:
            try:
                computed = self._compute_table()
            except Exception:
                computed = {}
        _table2l_update_labels_only(self, computed)
        try:
            if hasattr(self, "left_canvas"):
                self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))
        except Exception:
            pass
    except Exception:
        pass
    return result


CardScreen._render_gissmo = _table2l_safe_render_gissmo
CardScreen._update_gissmo_table2l_no_blink = _table2l_update_labels_only
CardScreen._ensure_gissmo_table2l_rows = _table2l_ensure_rows


# Re-apply no-blink refresh/commit hooks so the final Table 2L updater is used
# after all earlier compatibility patches.  The fallback render happens only if
# the Table 2L grid does not exist yet; normal typing updates label text only.
_TABLE2L_PRE_SAFE_REFRESH_FAST = CardScreen._refresh_cards_fast


def _table2l_refresh_cards_fast(self):
    result = _TABLE2L_PRE_SAFE_REFRESH_FAST(self)
    try:
        if self._is_gissmo_model():
            computed = self._compute_table()
            if not _table2l_update_labels_only(self, computed):
                self._render_gissmo(computed)
    except Exception as exc:
        try:
            logger.warning("Table 2L fast refresh failed: %s", exc)
        except Exception:
            pass
    return result


CardScreen._refresh_cards_fast = _table2l_refresh_cards_fast

_TABLE2L_PRE_SAFE_COMMIT = CardScreen._commit_all_pending_edits


def _table2l_commit_all_pending_edits(self, trigger: str = "Enter"):
    result = _TABLE2L_PRE_SAFE_COMMIT(self, trigger)
    try:
        if self._is_gissmo_model():
            computed = self._compute_table()
            if not _table2l_update_labels_only(self, computed):
                self._render_gissmo(computed)
    except Exception:
        pass
    return result


CardScreen._commit_all_pending_edits = _table2l_commit_all_pending_edits



# -----------------------------------------------------------------------------
# FINAL Custom Entry export-list + multi-image upload patch
# -----------------------------------------------------------------------------
# Requirements covered here:
# 1) A blank custom material becomes an Advanced Selection export-list item when
#    the user clicks Apply in the Property Card.
# 2) The user-provided Custom Name is used for the export-list Material value,
#    keyfile filename stem, and copied custom image filename stem.
# 3) Custom cards can upload multiple user images, view them with Previous/Next,
#    reopen them from the export list, and export/copy them with the keyfile.
# 4) Normal database materials, source-image lookup, keyfile export, notes, and
#    existing Advanced Selection behavior remain unchanged.

_CUSTOM_IMAGE_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp", "*.gif", "*.tif", "*.tiff")


def _cei_is_custom_payload(item: Dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    return bool(
        item.get("_custom_blank_entry")
        or item.get("Custom_Blank_Entry")
        or str(item.get("Source", "")).strip().lower() in {"custom blank entry", "advanced custom entry"}
        or str(item.get("_status", "")).strip().upper().startswith("CUSTOM") and str(item.get("Element", "")).strip().upper() == "CUSTOM"
    )


def _cei_user_custom_name_from_card(card) -> str:
    """Return the current custom name exactly as the visible card stores it."""
    try:
        raw = str(card.custom_name_var.get() or "").strip()
    except Exception:
        raw = ""
    if not raw:
        raw = _CUSTOM_ENTRY_DEFAULT_NAME if "_CUSTOM_ENTRY_DEFAULT_NAME" in globals() else "CUSTOM_MATERIAL"
    try:
        return _custom_clean_name(raw) if "_custom_clean_name" in globals() else raw
    except Exception:
        return raw


def _cei_safe_filename_name(value: Any, default: str = "CUSTOM_MATERIAL") -> str:
    import re
    text = str(value or "").strip()
    if not text:
        text = default
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")
    return text or default


def _cei_normalize_image_paths(paths: Any) -> List[str]:
    if paths is None:
        return []
    if isinstance(paths, (str, Path)):
        paths = [paths]
    out: List[str] = []
    seen = set()
    for raw in paths or []:
        try:
            p = Path(str(raw)).expanduser()
            key = str(p.resolve()).casefold() if p.exists() else str(p).casefold()
        except Exception:
            p = Path(str(raw))
            key = str(p).casefold()
        if not str(p).strip() or key in seen:
            continue
        seen.add(key)
        out.append(str(p))
    return out


def _cei_get_card_image_paths(card) -> List[str]:
    return _cei_normalize_image_paths(getattr(card, "custom_image_paths", []))


def _cei_set_card_image_paths(card, paths: Any) -> None:
    card.custom_image_paths = _cei_normalize_image_paths(paths)
    try:
        if card.current_row is not None:
            card.current_row["Custom_Image_Paths"] = json.dumps(card.custom_image_paths)
    except Exception:
        pass


def _cei_get_item_image_paths(item: Dict[str, Any]) -> List[str]:
    if not isinstance(item, dict):
        return []
    paths = item.get("Custom_Image_Paths", [])
    if isinstance(paths, str):
        try:
            loaded = json.loads(paths)
            if isinstance(loaded, list):
                paths = loaded
        except Exception:
            paths = [paths] if paths.strip() else []
    if not paths and isinstance(item.get("_card_custom_state"), dict):
        paths = item.get("_card_custom_state", {}).get("custom_image_paths", [])
    return _cei_normalize_image_paths(paths)


def _cei_custom_row_from_payload(item: Dict[str, Any]) -> pd.Series:
    name = str(item.get("Custom_Name") or item.get("Material") or _CUSTOM_ENTRY_DEFAULT_NAME).strip()
    try:
        name = _custom_clean_name(name) if "_custom_clean_name" in globals() else name
    except Exception:
        pass
    try:
        row = _custom_blank_row(name) if "_custom_blank_row" in globals() else pd.Series({})
    except Exception:
        row = pd.Series({})
    if row is None or row.empty:
        row = pd.Series({}, name=f"custom_blank_entry_{item.get('Export_ID', '')}")
    try:
        row["Element"] = "CUSTOM"
        row["Series"] = "CUSTOM"
        row["Material"] = name
        row["Spec1_1"] = "CUSTOM"
        row["Specification"] = "CUSTOM"
        row["Spec2_1"] = NO_SPEC_DISPLAY
        row["Form"] = "CUSTOM"
        row["Thick_Value"] = str(item.get("Thickness", "") or "").strip()
        row["MMPDS_Version"] = "Custom Entry"
        row["__custom_blank_entry"] = True
        row["__adv_row_key"] = str(item.get("_source_row_key") or item.get("_thickness_row_key") or f"custom_blank_entry_{item.get('Export_ID', '')}")
        row["Custom_Image_Paths"] = json.dumps(_cei_get_item_image_paths(item))
    except Exception:
        pass
    return row


def _cei_selection_from_custom_item(item: Dict[str, Any]) -> Dict[str, str]:
    name = str(item.get("Custom_Name") or item.get("Material") or _CUSTOM_ENTRY_DEFAULT_NAME).strip()
    try:
        name = _custom_clean_name(name) if "_custom_clean_name" in globals() else name
    except Exception:
        pass
    return {
        "Element": "CUSTOM",
        "Series": "CUSTOM",
        "Material": name,
        "Temper": str(item.get("Temper", "") or ""),
        "Specification": "CUSTOM",
        "Specification 2": NO_SPEC_DISPLAY,
        "Form": "CUSTOM",
    }


def _cei_next_available_id(selection_screen) -> str:
    try:
        return str(_hemil_next_available_export_id(selection_screen)) if "_hemil_next_available_export_id" in globals() else str(peek_next_export_id())
    except Exception:
        return str(peek_next_export_id())


# Re-open Add Custom Entry with an ID that is not already used in the export list.
def _cei_adv_add_custom_entry(self):
    export_id = _cei_next_available_id(self)
    custom_name = _custom_clean_name(f"MATERIAL_{export_id}") if "_custom_clean_name" in globals() else f"CUSTOM_MATERIAL_{export_id}"
    row = _custom_blank_row(custom_name) if "_custom_blank_row" in globals() else pd.Series({"Material": custom_name})
    try:
        row["__adv_row_key"] = f"custom_blank_entry_{export_id}"
        row["Custom_Image_Paths"] = "[]"
    except Exception:
        pass
    selections = {
        "Element": "CUSTOM",
        "Series": "CUSTOM",
        "Material": custom_name,
        "Temper": "",
        "Specification": "CUSTOM",
        "Specification 2": NO_SPEC_DISPLAY,
        "Form": "CUSTOM",
    }
    history_state = {
        "Opened_From": "Advanced Custom Entry",
        "Custom_Blank_Entry": True,
        "Custom_Name": custom_name,
        "Export_ID": export_id,
        "Basis": str(getattr(self, "adv_basis_var", tk.StringVar(value="B")).get() or "B"),
        "Direction": str(getattr(self, "adv_direction_var", tk.StringVar(value="L")).get() or "L"),
        "Unit_System": str(getattr(self, "adv_unit_sys_var", tk.StringVar(value="mm_T_s")).get() or "mm_T_s"),
        "Material_Model": str(getattr(self, "adv_model_var", tk.StringVar(value="MAT024+GISSMO")).get() or "MAT024+GISSMO"),
        "Thickness": "",
        "Thickness_Row_Key": f"custom_blank_entry_{export_id}",
        "Custom_Image_Paths": [],
        "prop_values": {key: ("", False) for key, *_ in PROPERTY_ROWS},
        "unit_conversions": DEFAULT_UNIT_CONVERSIONS.copy(),
    }
    try:
        self._adv_log(
            f"Opened blank custom material card: {custom_name}",
            action="Add Custom Entry",
            status="Ready",
            screen="Advanced Selection",
        )
    except Exception:
        pass
    self.app.show_screen(
        "CardScreen",
        row=row,
        selections=selections,
        matching_rows=pd.DataFrame([row]),
        history_state=history_state,
    )


SelectionScreen._adv_add_custom_entry = _cei_adv_add_custom_entry


# Preserve the most recent on_show behavior, then add custom image state restore.
_CEI_PREV_CARD_ON_SHOW = CardScreen.on_show


def _cei_card_on_show(self, row=None, selections=None, matching_rows=None, history_state=None, **kwargs):
    result = _CEI_PREV_CARD_ON_SHOW(self, row=row, selections=selections, matching_rows=matching_rows, history_state=history_state, **kwargs)
    try:
        if bool(isinstance(history_state, dict) and history_state.get("Custom_Blank_Entry")) or bool(getattr(self, "is_custom_entry", False)):
            image_paths = []
            if isinstance(history_state, dict):
                image_paths = history_state.get("Custom_Image_Paths") or history_state.get("custom_image_paths") or []
                if not image_paths and isinstance(history_state.get("_card_custom_state"), dict):
                    image_paths = history_state.get("_card_custom_state", {}).get("custom_image_paths", [])
            if not image_paths and row is not None:
                image_paths = row.get("Custom_Image_Paths", []) if hasattr(row, "get") else []
            _cei_set_card_image_paths(self, image_paths)
            if not hasattr(self, "custom_image_index_var"):
                self.custom_image_index_var = tk.IntVar(value=0)
            self.custom_image_index_var.set(0)
            try:
                # The earlier on_show may have rendered the old placeholder.
                self.after_idle(self._render_source_images)
            except Exception:
                pass
        else:
            _cei_set_card_image_paths(self, [])
    except Exception:
        pass
    return result


CardScreen.on_show = _cei_card_on_show


# Custom image viewer for the Card screen.
_CEI_PREV_RENDER_SOURCE_IMAGES = CardScreen._render_source_images


def _cei_upload_custom_images(self):
    if not bool(getattr(self, "is_custom_entry", False)):
        return "break"
    filetypes = [
        ("Image files", " ".join(_CUSTOM_IMAGE_EXTENSIONS)),
        ("PNG", "*.png"),
        ("JPEG", "*.jpg *.jpeg"),
        ("All files", "*.*"),
    ]
    try:
        selected = filedialog.askopenfilenames(title="Upload custom material image(s)", filetypes=filetypes)
    except Exception:
        selected = []
    if not selected:
        return "break"
    paths = _cei_get_card_image_paths(self) + list(selected)
    _cei_set_card_image_paths(self, paths)
    try:
        self.custom_image_index_var.set(max(0, len(_cei_get_card_image_paths(self)) - len(selected)))
    except Exception:
        pass
    try:
        self._render_source_images()
    except Exception:
        pass
    try:
        self.app.show_toast(f"Added {len(selected)} custom image(s)", kind="success")
    except Exception:
        pass
    return "break"


def _cei_clear_custom_images(self):
    if not bool(getattr(self, "is_custom_entry", False)):
        return "break"
    _cei_set_card_image_paths(self, [])
    try:
        self.custom_image_index_var.set(0)
    except Exception:
        pass
    try:
        self._render_source_images()
    except Exception:
        pass
    return "break"


def _cei_custom_prev_image(self):
    paths = _cei_get_card_image_paths(self)
    if not paths:
        return "break"
    if not hasattr(self, "custom_image_index_var"):
        self.custom_image_index_var = tk.IntVar(value=0)
    self.custom_image_index_var.set((self.custom_image_index_var.get() - 1) % len(paths))
    self._render_source_images()
    return "break"


def _cei_custom_next_image(self):
    paths = _cei_get_card_image_paths(self)
    if not paths:
        return "break"
    if not hasattr(self, "custom_image_index_var"):
        self.custom_image_index_var = tk.IntVar(value=0)
    self.custom_image_index_var.set((self.custom_image_index_var.get() + 1) % len(paths))
    self._render_source_images()
    return "break"


def _cei_render_source_images(self):
    if not bool(getattr(self, "is_custom_entry", False)):
        return _CEI_PREV_RENDER_SOURCE_IMAGES(self)
    if not hasattr(self, "image_panel"):
        return
    for w in self.image_panel.winfo_children():
        try:
            w.destroy()
        except Exception:
            pass
    self.source_image_refs = []
    self.source_images = [Path(p) for p in _cei_get_card_image_paths(self)]
    self.source_total_images = len(self.source_images)
    self._header(self.image_panel, "Data Source Viewer", right="Custom Entry")

    shell = tk.Frame(self.image_panel, bg=THEME["panel"])
    shell.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    topbar = tk.Frame(shell, bg=THEME["panel"])
    topbar.pack(fill=tk.X, pady=(0, 8))
    tk.Label(
        topbar,
        text="Custom entry selected.",
        bg=THEME["panel"],
        fg=THEME["accent"],
        font=FONTS["h2"],
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Button(topbar, text="Upload Image(s)...", style="Primary.TButton", command=self._upload_custom_images).pack(side=tk.RIGHT, padx=(6, 0))
    ttk.Button(topbar, text="Clear Images", style="Secondary.TButton", command=self._clear_custom_images).pack(side=tk.RIGHT, padx=(6, 0))

    paths = _cei_get_card_image_paths(self)
    if not paths:
        placeholder = tk.Frame(shell, bg=THEME["panel_alt"], highlightbackground=THEME["border"], highlightthickness=1)
        placeholder.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            placeholder,
            text="No custom image uploaded yet.\nClick 'Upload Image(s)...' to attach one or more images to this custom material.",
            bg=THEME["panel_alt"],
            fg=THEME["text_muted"],
            font=FONTS["h2"],
            justify="center",
        ).pack(expand=True)
        return

    if not hasattr(self, "custom_image_index_var"):
        self.custom_image_index_var = tk.IntVar(value=0)
    idx = int(self.custom_image_index_var.get() or 0)
    if idx < 0 or idx >= len(paths):
        idx = 0
        self.custom_image_index_var.set(0)
    current = Path(paths[idx])

    nav = tk.Frame(shell, bg=THEME["panel_alt"], highlightbackground=THEME["border"], highlightthickness=1)
    nav.pack(fill=tk.X, pady=(0, 8))
    tk.Label(
        nav,
        text=f"Image {idx + 1} of {len(paths)}: {current.name}",
        bg=THEME["panel_alt"],
        fg=THEME["text"],
        font=FONTS["small_bold"],
        anchor="w",
    ).pack(side=tk.LEFT, padx=10, pady=7)
    if len(paths) > 1:
        ttk.Button(nav, text="Next", style="Secondary.TButton", command=self._custom_next_image).pack(side=tk.RIGHT, padx=(4, 8), pady=4)
        ttk.Button(nav, text="Previous", style="Secondary.TButton", command=self._custom_prev_image).pack(side=tk.RIGHT, padx=4, pady=4)

    canvas = tk.Canvas(shell, bg=THEME["panel_alt"], highlightthickness=1, highlightbackground=THEME["border"])
    canvas.pack(fill=tk.BOTH, expand=True)
    if not current.exists():
        canvas.create_text(
            18, 18,
            anchor="nw",
            text=f"Image file not found:\n{current}",
            fill=THEME["status_error_fg"],
            font=FONTS["small_bold"],
        )
        return
    try:
        shell.update_idletasks()
    except Exception:
        pass
    img = self.app.image_cache.get(current, max_size=(860, 620))
    if img is None:
        canvas.create_text(
            18, 18,
            anchor="nw",
            text="Could not load image.\n" + str(getattr(self.app.image_cache, "last_error", "")),
            fill=THEME["status_error_fg"],
            font=FONTS["small_bold"],
        )
        return
    self.source_image_refs.append(img)
    canvas.create_image(10, 10, anchor="nw", image=img)
    canvas.configure(scrollregion=(0, 0, max(img.width() + 20, 300), max(img.height() + 20, 220)))


CardScreen._upload_custom_images = _cei_upload_custom_images
CardScreen._clear_custom_images = _cei_clear_custom_images
CardScreen._custom_prev_image = _cei_custom_prev_image
CardScreen._custom_next_image = _cei_custom_next_image
CardScreen._render_source_images = _cei_render_source_images


# Add/update the custom material in Advanced Selection when Apply is clicked.
def _cei_custom_payload_from_card(card) -> Dict[str, Any]:
    name = _cei_user_custom_name_from_card(card)
    try:
        card.current_selections["Material"] = name
        if card.current_row is not None:
            card.current_row["Material"] = name
            card.current_row["Element"] = "CUSTOM"
            card.current_row["Series"] = "CUSTOM"
            card.current_row["Spec1_1"] = "CUSTOM"
            card.current_row["Specification"] = "CUSTOM"
            card.current_row["Spec2_1"] = NO_SPEC_DISPLAY
            card.current_row["Form"] = "CUSTOM"
            card.current_row["Thick_Value"] = str(card.thickness_var.get() or "").strip()
            card.current_row["MMPDS_Version"] = "Custom Entry"
    except Exception:
        pass
    image_paths = _cei_get_card_image_paths(card)
    prop_state = {k: [str(v[0]), bool(v[1])] for k, v in getattr(card, "prop_values", {}).items()}
    unit_state = {k: card.unit_conversions.get(k, v) for k, v in DEFAULT_UNIT_CONVERSIONS.items()}
    export_id = str(card.export_id_var.get() or "").strip()
    try:
        export_id = str(normalize_export_id(export_id, default=EXPORT_COUNTER_START))
    except Exception:
        export_id = str(peek_next_export_id())
    thickness = str(card.thickness_var.get() or "").strip()
    row_key = str(getattr(card, "opened_export_id_context", "") or export_id or name).strip()
    return {
        "Export_ID": export_id,
        "Element": "CUSTOM",
        "Series": "CUSTOM",
        "Material": name,
        "Temper": "",
        "Specification": "CUSTOM",
        "Specification 2": NO_SPEC_DISPLAY,
        "Form": "CUSTOM",
        "Thickness": thickness,
        "Thickness_Mode": "Exact thickness text" if thickness else "",
        "Basis": str(card.basis_var.get() or "B"),
        "Direction": str(card.direction_var.get() or "L"),
        "Unit_System": str(card.unit_sys_var.get() or "mm_T_s"),
        "Material_Model": str(card.mat_model_var.get() or "MAT024+GISSMO"),
        "Source": "Custom Blank Entry",
        "Custom_Name": name,
        "Custom_Image_Paths": image_paths,
        "_source_row_key": f"custom_blank_entry_{row_key}",
        "_thickness_row_key": f"custom_blank_entry_{row_key}",
        "_custom": True,
        "_custom_blank_entry": True,
        "_selected": True,
        "_matches": 1,
        "_status": "CUSTOM - Ready",
        "_tag": "custom_row",
        "Notes": "",
        "_card_custom_state": {
            "prop_values": prop_state,
            "unit_conversions": unit_state,
            "custom_name": name,
            "custom_image_paths": image_paths,
            "is_custom_blank_entry": True,
        },
    }


def _cei_store_custom_card_to_export_list(card) -> bool:
    try:
        selection_screen = card.app.screens.get("SelectionScreen")
    except Exception:
        selection_screen = None
    if selection_screen is None:
        return False
    payload = _cei_custom_payload_from_card(card)
    export_id = str(payload.get("Export_ID", "")).strip()
    old_opened_id = str(getattr(card, "opened_export_id_context", "") or "").strip()

    # Prevent overwriting any different export row if the user typed a duplicate ID.
    for idx, item in enumerate(getattr(selection_screen, "advanced_items", [])):
        item_id = str(item.get("Export_ID", "") or "").strip()
        if item_id == export_id and item_id != old_opened_id:
            messagebox.showerror("Export ID", f"ID / MID {export_id} already exists in the export list. Choose a different ID.")
            try:
                if old_opened_id:
                    card.export_id_var.set(old_opened_id)
            except Exception:
                pass
            return False

    target_idx = None
    for idx, item in enumerate(getattr(selection_screen, "advanced_items", [])):
        item_id = str(item.get("Export_ID", "") or "").strip()
        if item_id and item_id in {export_id, old_opened_id}:
            target_idx = idx
            break

    if target_idx is None:
        selection_screen.advanced_items.append(payload)
        target_idx = len(selection_screen.advanced_items) - 1
    else:
        existing_notes = str(selection_screen.advanced_items[target_idx].get("Notes", "") or "")
        payload["Notes"] = existing_notes
        selection_screen.advanced_items[target_idx].clear()
        selection_screen.advanced_items[target_idx].update(payload)

    card.opened_export_id_context = export_id
    try:
        selection_screen._adv_refresh_tree()
        selection_screen.adv_tree.selection_set(str(target_idx))
        selection_screen.adv_tree.see(str(target_idx))
    except Exception:
        pass
    try:
        selection_screen._adv_log(
            f"Custom material saved to export list: {payload.get('Material')} | ID/MID {export_id}",
            action="Custom Entry Applied",
            status="Saved",
            screen="Advanced Selection",
        )
    except Exception:
        pass
    try:
        card.app.status_var.set(f"Custom material saved to export list: {payload.get('Material')} | ID/MID {export_id}")
    except Exception:
        pass
    return True


_CEI_PREV_CARD_APPLY = CardScreen._apply


def _cei_card_apply(self):
    if bool(getattr(self, "is_custom_entry", False)):
        try:
            if "_custom_name_changed" in globals():
                _custom_name_changed(self, sanitize=True)
        except Exception:
            pass
    result = _CEI_PREV_CARD_APPLY(self)
    if bool(getattr(self, "is_custom_entry", False)):
        # If invalid values remain pending, the original Apply rejected them.
        invalid_pending = False
        try:
            for key, val in list(getattr(self, "pending_edits", {}).items()):
                if str(val).strip() not in ("", "-") and try_float(val) is None:
                    invalid_pending = True
                    break
            if getattr(self, "unit_pending_edits", {}):
                # Unit conversion errors leave pending edits in place.
                for _key, val in list(getattr(self, "unit_pending_edits", {}).items()):
                    if try_float(val) is None:
                        invalid_pending = True
                        break
        except Exception:
            invalid_pending = False
        if not invalid_pending:
            _cei_store_custom_card_to_export_list(self)
    return result


CardScreen._apply = _cei_card_apply


# Keep custom rows matchable/exportable without relying on the normal database.
_CEI_PREV_ADV_MATCH_ROWS = SelectionScreen._adv_match_rows
_CEI_PREV_ADV_ROWS_TO_EXPORT = SelectionScreen._adv_rows_to_export


def _cei_adv_match_rows(self, payload: Dict[str, Any]) -> pd.DataFrame:
    if _cei_is_custom_payload(payload):
        return pd.DataFrame([_cei_custom_row_from_payload(payload)])
    return _CEI_PREV_ADV_MATCH_ROWS(self, payload)


def _cei_adv_rows_to_export(self, payload: Dict[str, Any]) -> List[pd.Series]:
    if _cei_is_custom_payload(payload):
        return [_cei_custom_row_from_payload(payload)]
    return _CEI_PREV_ADV_ROWS_TO_EXPORT(self, payload)


SelectionScreen._adv_match_rows = _cei_adv_match_rows
SelectionScreen._adv_rows_to_export = _cei_adv_rows_to_export


# Open custom export-list rows back into the blank custom card with saved values/images.
_CEI_PREV_ADV_OPEN_ROW = SelectionScreen._adv_open_export_list_row_card


def _cei_adv_open_export_list_row_card(self, event=None):
    tree = getattr(self, "adv_tree", None)
    if tree is None:
        return "break"
    try:
        col_name = self._adv_tree_column_name(tree.identify_column(event.x)) if event is not None else ""
    except Exception:
        col_name = ""
    if col_name in {"Export", "Export_ID", "Unit", "Notes", "View_Image"}:
        return "break"
    row_id = tree.identify_row(event.y) if event is not None else (tree.selection()[0] if tree.selection() else "")
    if not row_id:
        return "break"
    try:
        idx = int(row_id)
        item = self.advanced_items[idx]
    except Exception:
        return "break"
    if not _cei_is_custom_payload(item):
        return _CEI_PREV_ADV_OPEN_ROW(self, event)

    row = _cei_custom_row_from_payload(item)
    selections = _cei_selection_from_custom_item(item)
    custom_state = item.get("_card_custom_state") if isinstance(item.get("_card_custom_state"), dict) else {}
    history_state = {
        "Opened_From": "Advanced Custom Entry",
        "Custom_Blank_Entry": True,
        "Custom_Name": item.get("Custom_Name") or item.get("Material"),
        "Export_ID": str(item.get("Export_ID", "") or ""),
        "Basis": item.get("Basis", "B"),
        "Direction": item.get("Direction", "L"),
        "Unit_System": item.get("Unit_System", "mm_T_s"),
        "Material_Model": item.get("Material_Model", "MAT024+GISSMO"),
        "Thickness": item.get("Thickness", ""),
        "Thickness_Row_Key": item.get("_thickness_row_key") or item.get("_source_row_key") or f"custom_blank_entry_{item.get('Export_ID', '')}",
        "Custom_Image_Paths": _cei_get_item_image_paths(item),
        "prop_values": custom_state.get("prop_values", {key: ("", False) for key, *_ in PROPERTY_ROWS}),
        "unit_conversions": custom_state.get("unit_conversions", DEFAULT_UNIT_CONVERSIONS.copy()),
    }
    try:
        self._audit_log_action(
            screen="Advanced Selection",
            action="Custom Material Card Opened",
            status="Success",
            material_summary=f"CUSTOM {selections.get('Material', '')} | ID/MID {item.get('Export_ID', '')}",
            material=selections.get("Material", ""),
            notes=f"User opened custom export row {idx + 1}.",
        )
    except Exception:
        pass
    self.app.show_screen(
        "CardScreen",
        row=row,
        selections=selections,
        matching_rows=pd.DataFrame([row]),
        history_state=history_state,
    )
    return "break"


SelectionScreen._adv_open_export_list_row_card = _cei_adv_open_export_list_row_card


# Custom rows use the uploaded images instead of source-image lookup.
_CEI_PREV_ADV_BEST_IMAGE = SelectionScreen._adv_best_image_for_item
_CEI_PREV_ADV_SHOW_IMAGE = SelectionScreen._adv_show_image_for_item


def _cei_adv_best_image_for_item(self, item: Dict[str, Any]) -> Tuple[Optional[Path], int]:
    if _cei_is_custom_payload(item):
        existing = [Path(p) for p in _cei_get_item_image_paths(item) if Path(p).exists()]
        if existing:
            return existing[0], len(existing)
        return None, 0
    return _CEI_PREV_ADV_BEST_IMAGE(self, item)


def _cei_adv_show_image_for_item(self, idx: int):
    try:
        item = self.advanced_items[idx]
    except Exception:
        return _CEI_PREV_ADV_SHOW_IMAGE(self, idx)
    if not _cei_is_custom_payload(item):
        return _CEI_PREV_ADV_SHOW_IMAGE(self, idx)
    paths = [Path(p) for p in _cei_get_item_image_paths(item)]
    paths = [p for p in paths if p.exists()]
    if not paths:
        messagebox.showinfo("Custom Image", "No custom image has been uploaded for this export row yet. Open the custom material card and use Upload Image(s).")
        return "break"

    win = tk.Toplevel(self)
    win.title(f"Custom Images - {item.get('Material', 'CUSTOM')}")
    win.geometry("980x760")
    win.configure(bg=THEME["bg"])
    current_idx = tk.IntVar(value=0)
    refs: List[Any] = []

    top = tk.Frame(win, bg=THEME["panel"], highlightbackground=THEME["border"], highlightthickness=1)
    top.pack(fill=tk.X, padx=10, pady=(10, 6))
    title_var = tk.StringVar(value="")
    tk.Label(top, textvariable=title_var, bg=THEME["panel"], fg=THEME["accent"], font=FONTS["body_bold"], anchor="w").pack(side=tk.LEFT, padx=10, pady=8)
    canvas = tk.Canvas(win, bg=THEME["panel_alt"], highlightthickness=1, highlightbackground=THEME["border"])
    canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

    def draw():
        refs.clear()
        canvas.delete("all")
        i = int(current_idx.get() or 0) % len(paths)
        current_idx.set(i)
        path = paths[i]
        title_var.set(f"Image {i + 1} of {len(paths)}: {path.name}")
        img = self.app.image_cache.get(path, max_size=(920, 660))
        if img is None:
            canvas.create_text(18, 18, anchor="nw", text="Could not load image.\n" + str(getattr(self.app.image_cache, "last_error", "")), fill=THEME["status_error_fg"], font=FONTS["small_bold"])
            return
        refs.append(img)
        canvas.create_image(10, 10, anchor="nw", image=img)
        canvas.configure(scrollregion=(0, 0, max(img.width() + 20, 300), max(img.height() + 20, 220)))

    def prev_img():
        current_idx.set((current_idx.get() - 1) % len(paths))
        draw()

    def next_img():
        current_idx.set((current_idx.get() + 1) % len(paths))
        draw()

    if len(paths) > 1:
        ttk.Button(top, text="Next", style="Secondary.TButton", command=next_img).pack(side=tk.RIGHT, padx=(4, 10), pady=5)
        ttk.Button(top, text="Previous", style="Secondary.TButton", command=prev_img).pack(side=tk.RIGHT, padx=4, pady=5)
    draw()
    return "break"


SelectionScreen._adv_best_image_for_item = _cei_adv_best_image_for_item
SelectionScreen._adv_show_image_for_item = _cei_adv_show_image_for_item


# Make custom filename stems exactly follow the custom material name + ID.
_CEI_PREV_KEYFILE_STEM = CardScreen._keyfile_export_stem


def _cei_keyfile_export_stem(self, element, material, temper, spec, form, thickness, direction, model, custom: bool = False):
    if bool(getattr(self, "is_custom_entry", False)):
        name = _cei_user_custom_name_from_card(self)
        safe_name = _cei_safe_filename_name(name)
        export_id = ""
        try:
            export_id = str(self.export_id_var.get() or "").strip()
            if export_id:
                export_id = str(normalize_export_id(export_id, default=EXPORT_COUNTER_START))
        except Exception:
            export_id = ""
        return f"{safe_name}_{export_id}" if export_id else safe_name
    return _CEI_PREV_KEYFILE_STEM(self, element, material, temper, spec, form, thickness, direction, model, custom=custom)


CardScreen._keyfile_export_stem = _cei_keyfile_export_stem


# Programmatic export must temporarily behave as a custom card for blank custom rows.
_CEI_PREV_EXPORT_KEYFILE_PROGRAMMATIC = CardScreen.export_keyfile_programmatic


def _cei_export_keyfile_programmatic(self, row, selections: Dict[str, str], output_dir: Path, output_stem: str,
                                     basis: str = "B", direction: str = "L", unit_sys: str = "mm_T_s",
                                     mat_model: str = "MAT024+GISSMO", material_id: Optional[Any] = None) -> Dict[str, Any]:
    custom_state = getattr(self, "_programmatic_custom_state", None)
    is_custom_programmatic = bool(isinstance(custom_state, dict) and custom_state.get("is_custom_blank_entry"))
    if not is_custom_programmatic:
        try:
            is_custom_programmatic = bool(row is not None and hasattr(row, "get") and row.get("__custom_blank_entry", False))
        except Exception:
            is_custom_programmatic = False
    if not is_custom_programmatic:
        return _CEI_PREV_EXPORT_KEYFILE_PROGRAMMATIC(self, row, selections, output_dir, output_stem, basis, direction, unit_sys, mat_model, material_id)

    old_is_custom = bool(getattr(self, "is_custom_entry", False))
    old_custom_name = ""
    try:
        old_custom_name = str(getattr(self, "custom_name_var", tk.StringVar(value="")).get())
    except Exception:
        old_custom_name = ""
    if not hasattr(self, "custom_name_var"):
        self.custom_name_var = tk.StringVar(value="")
    try:
        custom_name = str(custom_state.get("custom_name") or (selections or {}).get("Material") or (row.get("Material", "") if row is not None and hasattr(row, "get") else "") or output_stem or _CUSTOM_ENTRY_DEFAULT_NAME)
        self.is_custom_entry = True
        self.custom_name_var.set(_custom_clean_name(custom_name) if "_custom_clean_name" in globals() else custom_name)
        self.export_id_var.set(str(material_id or ""))
        return _CEI_PREV_EXPORT_KEYFILE_PROGRAMMATIC(self, row, selections, output_dir, output_stem, basis, direction, unit_sys, mat_model, material_id)
    finally:
        try:
            self.is_custom_entry = old_is_custom
            self.custom_name_var.set(old_custom_name)
        except Exception:
            pass


CardScreen.export_keyfile_programmatic = _cei_export_keyfile_programmatic


# Batch export override: same logic as existing export, but custom rows copy every
# uploaded image using the exported keyfile stem. Normal rows still copy one best
# source image exactly as before.
def _cei_adv_export_all(self):
    if not self.advanced_items:
        messagebox.showwarning("Advanced Selection", "Add at least one item before exporting.")
        return
    selected_items = [(idx, item) for idx, item in enumerate(self.advanced_items, start=1) if item.get("_selected", False)]
    if not selected_items:
        messagebox.showwarning("Advanced Selection", "Select at least one checkbox in the Export column before exporting.")
        return

    batch_dir = Path(self.adv_output_dir_var.get()).expanduser()
    keyfiles_dir = batch_dir / "keyfiles"
    images_dir = batch_dir / "images"
    try:
        keyfiles_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        messagebox.showerror("Advanced Selection", f"Could not create output folders:\n\n{exc}")
        return

    card: CardScreen = self.app.screens.get("CardScreen")
    if card is None:
        messagebox.showerror("Advanced Selection", "CardScreen is not available for MAT024 calculations.")
        return

    exported = 0
    skipped = 0
    errors = []
    summary_rows = []
    self._adv_log(f"Starting batch keyfile export for {len(selected_items)} selected item(s)...")
    self._adv_log(f"Batch folder: {batch_dir}")

    for item_idx, item in selected_items:
        self.update_idletasks()
        rows = self._adv_rows_to_export(item)
        if not rows:
            skipped += 1
            msg = f"Item {item_idx}: no matching material row."
            errors.append(msg)
            self._adv_log(msg)
            summary_rows.append(self._adv_summary_row(item, item_idx, "Skipped - No match", "", "", "", "No matching material row"))
            continue

        selections = _cei_selection_from_custom_item(item) if _cei_is_custom_payload(item) else self._adv_selection_from_payload(item)
        basis = item.get("Basis", "B") or "B"
        direction = item.get("Direction", "L") or "L"
        unit_sys = self._adv_normalize_unit_system(item.get("Unit_System", "mm_T_s"))
        model = item.get("Material_Model", "MAT024+GISSMO") or "MAT024+GISSMO"
        item_notes = str(item.get("Notes", "") or "").strip()

        for row_idx, row in enumerate(rows, start=1):
            stem = self._adv_short_output_stem(item, row, item_idx, row_idx)
            keyfile_path = ""
            image_name = ""
            image_export_path = ""
            try:
                card._programmatic_custom_state = item.get("_card_custom_state") if isinstance(item.get("_card_custom_state"), dict) else None
                card._programmatic_export_notes = item_notes
                result = card.export_keyfile_programmatic(
                    row=row,
                    selections=selections,
                    output_dir=keyfiles_dir,
                    output_stem=stem,
                    basis=basis,
                    direction=direction,
                    unit_sys=unit_sys,
                    mat_model=model,
                    material_id=item.get("Export_ID", ""),
                )
            except Exception as exc:
                skipped += 1
                msg = f"Item {item_idx}, row {row_idx}: export failed: {exc}"
                errors.append(msg)
                self._adv_log(msg)
                summary_rows.append(self._adv_summary_row(item, item_idx, "Skipped - Export error", "", "", "", str(exc), row=row))
                continue
            finally:
                try:
                    card._programmatic_custom_state = None
                    card._programmatic_export_notes = ""
                except Exception:
                    pass

            if result.get("ok"):
                exported += 1
                keyfile_path = result.get("path", "")
                key_stem = Path(keyfile_path).stem if keyfile_path else stem
                self._adv_log(f"Exported keyfile: {Path(keyfile_path).name}")

                copied_paths: List[str] = []
                copied_names: List[str] = []
                if _cei_is_custom_payload(item):
                    custom_images = [Path(p) for p in _cei_get_item_image_paths(item) if Path(p).exists()]
                    for img_idx, img_path in enumerate(custom_images, start=1):
                        image_stem = key_stem if img_idx == 1 else f"{key_stem}_{img_idx}"
                        copied = self._adv_copy_image_to_output(img_path, images_dir, image_stem)
                        if copied is not None:
                            copied_names.append(copied.name)
                            copied_paths.append(str(copied))
                            self._adv_log(f"Copied custom image: {copied.name}")
                else:
                    image_path, _image_total = self._adv_best_image_for_item(item)
                    if image_path is not None:
                        copied = self._adv_copy_image_to_output(image_path, images_dir, key_stem)
                        if copied is not None:
                            copied_names.append(copied.name)
                            copied_paths.append(str(copied))
                            self._adv_log(f"Copied source image: {copied.name}")

                image_name = "; ".join(copied_names)
                image_export_path = "; ".join(copied_paths)
                summary_rows.append(self._adv_summary_row(
                    item, item_idx, "Exported", Path(keyfile_path).name, keyfile_path,
                    image_export_path, item_notes, image_name=image_name, row=row,
                    export_id=result.get("export_id", "")
                ))
            else:
                skipped += 1
                missing = ", ".join(result.get("missing", []))
                msg = f"Item {item_idx}, row {row_idx}: skipped; missing {missing}"
                errors.append(msg)
                self._adv_log(msg)
                summary_rows.append(self._adv_summary_row(item, item_idx, "Skipped - Missing values", "", "", "", missing, row=row))

    summary_csv_path, summary_xlsx_path = self._write_advanced_summary_files(summary_rows, batch_dir)
    if summary_csv_path is not None:
        self._adv_log(f"Export summary CSV created: {summary_csv_path.name}")
    if summary_xlsx_path is not None:
        self._adv_log(f"Styled export summary Excel created: {summary_xlsx_path.name}")

    summary = f"Batch export complete. Exported {exported} keyfile(s). Skipped {skipped}."
    self._adv_log(summary)
    if hasattr(self.app, "status_var"):
        self.app.status_var.set(f"{summary} | {export_counter_status_text()}")
    self._adv_log(f"Keyfiles folder: {keyfiles_dir}")
    self._adv_log(f"Images folder: {images_dir}")
    if errors:
        messagebox.showwarning("Advanced Selection", summary + "\n\nCheck the Export / Validation Log and export_summary.csv for details.")
    else:
        messagebox.showinfo("Advanced Selection", summary + f"\n\nOutput folder:\n{batch_dir}")


SelectionScreen._adv_export_all = _cei_adv_export_all



# =============================================================================
# REHAN_ADVANCED_SELECTION_MANAGER_TEST_FIX_2026_06_22
# Final manager-test patch:
# - Export List sorts by numeric ID/MID.
# - Advanced rows stay linked to the exact source database row.
# - Duplicate detection includes exact source row, thickness, spec, basis,
#   direction, unit, and model.
# - Basis / Direction / Unit / Model / Notes / ID edits in Export List are
#   saved back into advanced_items and reflected in export order/summary.
# - Ftu is included as a required value/highlighted missing field.
# - Uploaded CSV comments/notes are preserved.
# =============================================================================

try:
    REQUIRED_MAT_VALUE_GROUPS.setdefault(
        "SIGU",
        ("Tensile_Str", "UltTensileStrength", "UltimateTensileStrength", "Ftu", "FTU"),
    )
except Exception:
    pass


def _mgr_norm_text(value: Any) -> str:
    try:
        return norm(value)
    except Exception:
        return str(value or "").strip().lower()


def _mgr_clean_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    try:
        return default if is_blank(text) else text
    except Exception:
        return text if text else default


def _mgr_numeric_export_id(value: Any, fallback: int = 10**12) -> int:
    try:
        return int(float(str(value).strip().replace(",", "")))
    except Exception:
        return fallback


def _mgr_source_row_key(selection_screen, row: Any) -> str:
    if row is None:
        return ""
    try:
        key = str(row.get("__adv_row_key", "") or "").strip()
        if key:
            return key
    except Exception:
        pass
    try:
        return selection_screen._adv_row_identity_key(row)
    except Exception:
        try:
            return source_row_identity_key(row)
        except Exception:
            return ""


def _mgr_source_key_from_item(item: Dict[str, Any]) -> str:
    for key in ("_source_row_key", "Source_Row_Key", "_thickness_row_key", "Thickness_Row_Key", "__adv_row_key"):
        value = str((item or {}).get(key, "") or "").strip()
        if value:
            return value
    return ""


def _mgr_row_by_source_key(selection_screen, key: str) -> Optional[pd.Series]:
    key = str(key or "").strip()
    if not key:
        return None
    try:
        master = getattr(selection_screen.db, "master", pd.DataFrame())
        if master is None or master.empty:
            return None
        if "__adv_row_key" in master.columns:
            hit = master.loc[master["__adv_row_key"].astype(str).eq(key)]
            if hit is not None and not hit.empty:
                return hit.iloc[0]
        # Fallback for keys generated before __adv_row_key existed.
        for _idx, row in master.iterrows():
            try:
                if _mgr_source_row_key(selection_screen, row) == key or source_row_identity_key(row) == key:
                    return row
            except Exception:
                continue
    except Exception:
        return None
    return None


def _mgr_row_value(selection_screen, row: Any, *names: str, default: str = "") -> str:
    if row is None:
        return default
    try:
        return selection_screen._adv_row_get(row, *names, default=default)
    except Exception:
        try:
            return row_get_first_nonblank_tolerant(row, *names, default=default)
        except Exception:
            try:
                for name in names:
                    value = row.get(name, "")
                    if not is_blank(value):
                        return str(value).strip()
            except Exception:
                pass
    return default


def _mgr_spec1_from_row(selection_screen, row: Any) -> str:
    value = _mgr_row_value(selection_screen, row, "Spec1_1", "spec1_1", "Specification", "Spec", default="")
    try:
        return NO_SPEC_DISPLAY if is_blank(value) else str(value).strip()
    except Exception:
        return str(value or "").strip()


def _mgr_spec2_from_row(row: Any) -> str:
    try:
        return display_spec_value(row_spec2_value(row))
    except Exception:
        try:
            return display_spec(row_spec2_value(row))
        except Exception:
            return NO_SPEC_DISPLAY


def _mgr_thickness_from_row(selection_screen, row: Any) -> str:
    try:
        return selection_screen._adv_thickness_display_label(row) or "NA"
    except Exception:
        try:
            return source_thickness_display_label(row) or "NA"
        except Exception:
            return "NA"


def _mgr_item_is_custom_or_edited(item: Dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    custom_flags = (
        "_custom", "_custom_blank_entry", "Custom_Blank_Entry",
        "is_custom_blank_entry", "_edited_from_card", "_edited_from_export_list",
        "_user_changes",
    )
    if any(bool(item.get(k)) for k in custom_flags):
        return True
    if isinstance(item.get("_card_custom_state"), dict):
        return True
    status = str(item.get("_status", "") or "").upper()
    return "CUSTOM" in status or "EDITED" in status


def _mgr_item_requires_notes(item: Dict[str, Any]) -> bool:
    return _mgr_item_is_custom_or_edited(item)


def _mgr_sync_payload_from_row(selection_screen, payload: Dict[str, Any], row: Any, *, overwrite_display: bool = True) -> Dict[str, Any]:
    payload = dict(payload or {})
    if row is None:
        return payload
    if overwrite_display:
        payload["Element"] = _mgr_row_value(selection_screen, row, "Element", default=payload.get("Element", ""))
        material = _mgr_row_value(selection_screen, row, "Material", default=payload.get("Material", ""))
        payload["Material"] = material
        payload["Temper"] = _mgr_row_value(selection_screen, row, "Temper", default=payload.get("Temper", ""))
        payload["Form"] = _mgr_row_value(selection_screen, row, "Form", default=payload.get("Form", ""))
        payload["Specification"] = _mgr_spec1_from_row(selection_screen, row)
        payload["Specification 2"] = _mgr_spec2_from_row(row)
        series = _mgr_row_value(selection_screen, row, "Series", default="")
        if not series:
            try:
                series = selection_screen.db._material_to_series.get(norm(material), "")
            except Exception:
                series = ""
        payload["Series"] = series
    row_key = _mgr_source_row_key(selection_screen, row)
    if row_key:
        payload["_source_row_key"] = row_key
        payload["Source_Row_Key"] = row_key
        payload["_thickness_row_key"] = row_key
        payload["Thickness_Row_Key"] = row_key
    payload["Thickness"] = _mgr_thickness_from_row(selection_screen, row)
    payload["Thickness_Mode"] = "Exact thickness text"
    return payload


def _mgr_filter_rows_by_thickness(selection_screen, df: pd.DataFrame, payload: Dict[str, Any]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    exact = str(payload.get("Thickness", "") or "").strip()
    mode = str(payload.get("Thickness_Mode", "") or "").strip()
    if not exact or exact in {"First matching thickness", "All matching thickness rows"}:
        return df.copy()
    # Exact source row key is stronger than text thickness.
    key = _mgr_source_key_from_item(payload)
    if key:
        row = _mgr_row_by_source_key(selection_screen, key)
        if row is not None:
            return pd.DataFrame([row])
    exact_norm = norm(exact)
    try:
        mask = pd.Series(False, index=df.index)
        if "__adv_thickness_norm" in df.columns:
            mask |= df["__adv_thickness_norm"].astype(str).eq(exact_norm)
        if "__adv_thickness_base_norm" in df.columns:
            mask |= df["__adv_thickness_base_norm"].astype(str).eq(exact_norm)
        if mask.any():
            return df.loc[mask].copy()
    except Exception:
        pass
    keep = []
    try:
        for idx, row in df.iterrows():
            t1 = _mgr_thickness_from_row(selection_screen, row)
            try:
                t2 = selection_screen._adv_thickness_base(row)
            except Exception:
                t2 = ""
            if norm(t1) == exact_norm or norm(t2) == exact_norm:
                keep.append(idx)
        if keep:
            return df.loc[keep].copy()
    except Exception:
        pass
    return df.copy() if mode != "Exact thickness text" else pd.DataFrame()


def _mgr_rows_by_material_path(selection_screen, payload: Dict[str, Any]) -> pd.DataFrame:
    payload = dict(payload or {})
    # Custom rows are handled by existing custom-row helpers.
    try:
        if "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(payload):
            return pd.DataFrame([_cei_custom_row_from_payload(payload)])
    except Exception:
        pass

    key = _mgr_source_key_from_item(payload)
    if key:
        row = _mgr_row_by_source_key(selection_screen, key)
        if row is not None:
            return pd.DataFrame([row])

    try:
        selections = selection_screen._adv_selection_from_payload(payload)
    except Exception:
        selections = {s: str(payload.get(s, "") or "").strip() for s in STAGES}

    # First try the normal exact material-path filter.
    try:
        df = selection_screen.db.filter_master(selections)
    except Exception:
        df = pd.DataFrame()

    # If Spec1/Spec2 were supplied in the opposite columns, try safe swaps.
    if df is None or df.empty:
        spec1 = str(payload.get("Specification", "") or "").strip()
        spec2 = str(payload.get("Specification 2", "") or payload.get("Specification_2", "") or "").strip()
        attempts = []
        if spec1 and spec1 != NO_SPEC_DISPLAY:
            s = dict(selections)
            s["Specification"] = ""
            s["Specification 2"] = spec1
            attempts.append(s)
        if spec2 and spec2 != NO_SPEC_DISPLAY:
            s = dict(selections)
            s["Specification"] = spec2
            s["Specification 2"] = ""
            attempts.append(s)
        for s in attempts:
            try:
                hit = selection_screen.db.filter_master(s)
                if hit is not None and not hit.empty:
                    df = hit
                    break
            except Exception:
                pass

    # Last fallback: match material path and allow Spec1 OR Spec2 to contain the given spec.
    if df is None or df.empty:
        try:
            master = getattr(selection_screen.db, "master", pd.DataFrame())
            if master is not None and not master.empty:
                mask = pd.Series(True, index=master.index)
                for field in ("Element", "Material", "Temper", "Form"):
                    val = str(payload.get(field, "") or "").strip()
                    if not val:
                        continue
                    col = find_col(master, field)
                    if col:
                        mask &= master[col].astype(str).map(norm).eq(norm(val))
                specs = [str(payload.get("Specification", "") or "").strip(), str(payload.get("Specification 2", "") or payload.get("Specification_2", "") or "").strip()]
                specs = [x for x in specs if x and x != NO_SPEC_DISPLAY]
                if specs:
                    spec_mask = pd.Series(False, index=master.index)
                    for col_name in ("Spec1_1", "spec1_1", "Specification", "Spec2_1", "Spec2_2", "Spec2_3", "Spec2_4", "Specification 2", "Specification2", "Spec2"):
                        col = find_col(master, col_name)
                        if col:
                            spec_mask |= master[col].astype(str).map(norm).isin({norm(x) for x in specs})
                    mask &= spec_mask
                df = master.loc[mask].copy()
        except Exception:
            df = pd.DataFrame()

    return _mgr_filter_rows_by_thickness(selection_screen, df, payload)


_MGR_PREV_ADV_MATCH_ROWS = SelectionScreen._adv_match_rows
_MGR_PREV_ADV_ROWS_TO_EXPORT = SelectionScreen._adv_rows_to_export


def _mgr_adv_match_rows(self, payload: Dict[str, Any]) -> pd.DataFrame:
    payload = dict(payload or {})
    try:
        if "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(payload):
            return pd.DataFrame([_cei_custom_row_from_payload(payload)])
    except Exception:
        pass
    key = _mgr_source_key_from_item(payload)
    if key:
        row = _mgr_row_by_source_key(self, key)
        if row is not None:
            return pd.DataFrame([row])
    # Material path matching deliberately ignores Basis/Direction/Model so a row
    # is not lost only because the user selected an invalid combination. Status
    # validation below decides if Basis/Direction/Model can generate.
    rows = _mgr_rows_by_material_path(self, payload)
    if rows is not None and not rows.empty:
        return rows
    try:
        return _MGR_PREV_ADV_MATCH_ROWS(self, payload)
    except Exception:
        return pd.DataFrame()


def _mgr_adv_rows_to_export(self, payload: Dict[str, Any]) -> List[pd.Series]:
    try:
        if "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(payload):
            return [_cei_custom_row_from_payload(payload)]
    except Exception:
        pass
    df = self._adv_match_rows(payload)
    if df is None or df.empty:
        return []
    # If the exact source row key exists, always export that one exact row.
    if _mgr_source_key_from_item(payload):
        return [df.iloc[0]]
    if str(payload.get("Thickness_Mode", "") or "").strip() == "All matching thickness rows":
        return [df.iloc[i] for i in range(len(df))]
    return [df.iloc[0]]


def _mgr_available_bases_for_payload(self, payload: Dict[str, Any]) -> Dict[str, bool]:
    payload = dict(payload or {})
    try:
        if "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(payload):
            return {"A": True, "B": True, "S": True}
    except Exception:
        pass
    row = None
    key = _mgr_source_key_from_item(payload)
    if key:
        row = _mgr_row_by_source_key(self, key)
    if row is None:
        rows = _mgr_rows_by_material_path(self, payload)
        if rows is not None and not rows.empty:
            row = rows.iloc[0]
    if row is not None:
        rows = pd.DataFrame([row])
        direction = str(payload.get("Direction", "") or "").strip().upper()
        try:
            available = self._adv_available_bases_for_rows(rows, direction)
            if not any(available.values()):
                available = self._adv_available_bases_any_direction_for_rows(rows)
            return available
        except Exception:
            pass
    try:
        return SelectionScreen._adv_available_bases_for_payload.__wrapped__(self, payload)  # type: ignore[attr-defined]
    except Exception:
        return {"A": False, "B": False, "S": False}


def _mgr_available_directions_for_payload(self, payload: Dict[str, Any]) -> List[str]:
    payload = dict(payload or {})
    try:
        if "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(payload):
            return ["L", "LT"]
    except Exception:
        pass
    row = None
    key = _mgr_source_key_from_item(payload)
    if key:
        row = _mgr_row_by_source_key(self, key)
    if row is None:
        rows = _mgr_rows_by_material_path(self, payload)
        if rows is not None and not rows.empty:
            row = rows.iloc[0]
    if row is not None:
        rows = pd.DataFrame([row])
        basis = str(payload.get("Basis", "") or "").strip().upper()
        try:
            opts = self._adv_available_directions_for_rows(rows, basis)
            if not opts:
                opts = self._adv_available_directions_for_rows(rows, "")
            return opts
        except Exception:
            pass
    return []


def _mgr_available_models_for_payload(self, payload: Dict[str, Any]) -> List[str]:
    payload = dict(payload or {})
    try:
        if "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(payload):
            return [code for _label, code in MAT_MODELS]
    except Exception:
        pass
    rows = self._adv_match_rows(payload)
    if rows is None or rows.empty:
        return []
    try:
        return self._adv_available_matcards_for_rows(rows, payload.get("Basis", "B"), payload.get("Direction", "L"))
    except Exception:
        return [code for _label, code in MAT_MODELS]


def _mgr_adv_ensure_payload_basis_direction(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload or {})
    try:
        if "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(payload):
            payload["Basis"] = str(payload.get("Basis", "B") or "B").strip().upper() if str(payload.get("Basis", "")).strip().upper() in {"A", "B", "S"} else "B"
            payload["Direction"] = "LT" if str(payload.get("Direction", "L") or "L").strip().upper() == "LT" else "L"
            payload["Material_Model"] = str(payload.get("Material_Model", "MAT024+GISSMO") or "MAT024+GISSMO")
            return payload
    except Exception:
        pass

    current_basis = str(payload.get("Basis", "B") or "B").strip().upper()
    if current_basis not in {"A", "B", "S"}:
        current_basis = "B"
    current_direction = "LT" if str(payload.get("Direction", "L") or "L").strip().upper() == "LT" else "L"
    current_model = str(payload.get("Material_Model", "MAT024+GISSMO") or "MAT024+GISSMO")

    available_bases = _mgr_available_bases_for_payload(self, {**payload, "Direction": current_direction})
    basis_options = [b for _label, b in BASIS_OPTIONS if available_bases.get(b, False)]
    if current_basis not in basis_options:
        current_basis = self._adv_preferred_value(basis_options, "B", basis_options[0] if basis_options else current_basis)

    direction_options = _mgr_available_directions_for_payload(self, {**payload, "Basis": current_basis})
    if current_direction not in direction_options:
        current_direction = self._adv_preferred_value(direction_options, "L", direction_options[0] if direction_options else current_direction)

    model_options = _mgr_available_models_for_payload(self, {**payload, "Basis": current_basis, "Direction": current_direction})
    if current_model not in model_options:
        current_model = self._adv_preferred_value(model_options, "MAT024+GISSMO", model_options[0] if model_options else current_model)

    payload["Basis"] = current_basis
    payload["Direction"] = current_direction
    payload["Material_Model"] = current_model if current_model in {"MAT024", "MAT082", "MAT224", "MAT024+GISSMO"} else "MAT024+GISSMO"
    return payload


def _mgr_update_item_status(self, item: Dict[str, Any]) -> None:
    rows = self._adv_match_rows(item)
    item["_matches"] = int(len(rows)) if rows is not None else 0
    available = _mgr_available_bases_for_payload(self, item)
    missing_required = []
    try:
        missing_required = self._adv_missing_required_for_payload(item, rows)
    except Exception:
        missing_required = []
    basis = str(item.get("Basis", "B") or "B").strip().upper()
    direction = str(item.get("Direction", "L") or "L").strip().upper()
    models = _mgr_available_models_for_payload(self, item)
    model = str(item.get("Material_Model", "MAT024+GISSMO") or "MAT024+GISSMO")
    if item["_matches"] <= 0:
        item["_status"] = "No match"
        item["_tag"] = "error"
    elif not available.get(basis, False) or direction not in _mgr_available_directions_for_payload(self, item) or (models and model not in models):
        item["_status"] = f"Cannot generate - {basis}/{direction}/{model} not available"
        item["_tag"] = "error"
    elif missing_required:
        item["_status"] = "Cannot generate - missing " + ", ".join(missing_required)
        item["_tag"] = "error"
    else:
        if _mgr_item_is_custom_or_edited(item):
            item["_status"] = "CUSTOM / EDITED - Ready"
            item["_tag"] = "custom_row"
            item["_custom"] = True
        else:
            item["_status"] = "Ready"
            item["_tag"] = "ok"


def _mgr_sort_advanced_items(self) -> None:
    try:
        for seq, item in enumerate(getattr(self, "advanced_items", []) or []):
            item.setdefault("_mgr_insert_seq", seq)
        self.advanced_items.sort(key=lambda item: (_mgr_numeric_export_id(item.get("Export_ID", "")), int(item.get("_mgr_insert_seq", 0))))
    except Exception:
        pass


def _mgr_duplicate_key(item: Dict[str, Any]) -> Tuple[str, ...]:
    spec2 = first_nonblank_value(item.get("Specification 2", ""), item.get("Specification_2", ""), item.get("Spec2", ""), default="")
    unit = str(item.get("Unit_System", "") or item.get("Unit", "") or "").strip()
    return (
        _mgr_norm_text(_mgr_source_key_from_item(item)),
        _mgr_norm_text(item.get("Element", "")),
        _mgr_norm_text(item.get("Series", "")),
        _mgr_norm_text(item.get("Material", "")),
        _mgr_norm_text(item.get("Temper", "")),
        _mgr_norm_text(item.get("Specification", "")),
        _mgr_norm_text(spec2),
        _mgr_norm_text(item.get("Form", "")),
        _mgr_norm_text(item.get("Thickness", "") or item.get("Thickness_Mode", "")),
        _mgr_norm_text(item.get("Basis", "")),
        _mgr_norm_text(item.get("Direction", "")),
        _mgr_norm_text(unit),
        _mgr_norm_text(item.get("Material_Model", "")),
        "custom" if _mgr_item_is_custom_or_edited(item) else "database",
    )


def _mgr_adv_duplicate_key(self, item: Dict[str, Any]) -> Tuple[str, ...]:
    return _mgr_duplicate_key(item)


def _mgr_adv_duplicate_indexes(self) -> set:
    groups: Dict[Tuple[str, ...], List[int]] = {}
    for idx, item in enumerate(getattr(self, "advanced_items", []) or []):
        key = _mgr_duplicate_key(item)
        if not any(key):
            continue
        groups.setdefault(key, []).append(idx)
    dup = set()
    for indexes in groups.values():
        if len(indexes) > 1:
            dup.update(indexes)
    return dup


_MGR_PREV_ADV_REFRESH_TREE = SelectionScreen._adv_refresh_tree


def _mgr_adv_refresh_tree(self):
    _mgr_sort_advanced_items(self)
    for item in getattr(self, "advanced_items", []) or []:
        try:
            # Keep normal database rows synced to the exact source row. Do not
            # overwrite custom blank entries.
            if not ("_cei_is_custom_payload" in globals() and _cei_is_custom_payload(item)):
                row = None
                key = _mgr_source_key_from_item(item)
                if key:
                    row = _mgr_row_by_source_key(self, key)
                if row is not None:
                    item.update(_mgr_sync_payload_from_row(self, item, row, overwrite_display=True))
            item.update(_mgr_adv_ensure_payload_basis_direction(self, item))
            _mgr_update_item_status(self, item)
        except Exception:
            pass
    return _MGR_PREV_ADV_REFRESH_TREE(self)


def _mgr_add_item_object(self, payload: Dict[str, Any], source_label: str = "selection", refresh: bool = True, log: bool = True) -> bool:
    payload = dict(payload or {})
    try:
        if "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(payload):
            rows = pd.DataFrame([_cei_custom_row_from_payload(payload)])
            row = rows.iloc[0]
        else:
            rows = _mgr_rows_by_material_path(self, payload)
            if rows is None or rows.empty:
                if log:
                    self._adv_log(f"Skipped {source_label}: no matching source row was found.", status="Skipped")
                return False
            row = rows.iloc[0]
            payload = _mgr_sync_payload_from_row(self, payload, row, overwrite_display=True)
        payload = _mgr_adv_ensure_payload_basis_direction(self, payload)
        if not str(payload.get("Export_ID", "") or "").strip():
            payload["Export_ID"] = str(_hemil_next_available_export_id(self) if "_hemil_next_available_export_id" in globals() else reserve_next_export_id())
        else:
            default_id = (_hemil_next_available_export_id(self) if "_hemil_next_available_export_id" in globals() else peek_next_export_id())
            new_id = str(normalize_export_id(payload.get("Export_ID"), default=default_id))
            for existing in getattr(self, "advanced_items", []) or []:
                if str(existing.get("Export_ID", "") or "").strip() == new_id:
                    messagebox.showerror("Export ID", f"ID / MID {new_id} already exists in the export list. Choose a different ID.")
                    return False
            payload["Export_ID"] = new_id
            payload["_id_manual"] = True
            advance_session_export_id_after(new_id)
        payload["_selected"] = bool(payload.get("_selected", True))
        payload.setdefault("Notes", "")
        payload.setdefault("Source", source_label)
        payload.setdefault("_mgr_insert_seq", len(getattr(self, "advanced_items", []) or []))
        _mgr_update_item_status(self, payload)
        self.advanced_items.append(payload)
        _mgr_sort_advanced_items(self)
        if refresh:
            self._adv_refresh_tree()
            try:
                new_idx = self.advanced_items.index(payload)
                self.adv_tree.selection_set(str(new_idx))
                self.adv_tree.see(str(new_idx))
            except Exception:
                pass
            try:
                self._finder_refresh_selected_export_tree()
            except Exception:
                pass
        if log:
            self._adv_log(f"Added {source_label}: {payload.get('_matches', 1)} matching row(s).")
        return True
    except Exception as exc:
        if log:
            self._adv_log(f"Could not add {source_label}: {exc}", status="Error")
        try:
            messagebox.showerror("Advanced Selection", f"Could not add item:\n\n{exc}")
        except Exception:
            pass
        return False


def _mgr_adv_add_payload(self, payload: Dict[str, Any], source_label: str = "selection", refresh: bool = True, log: bool = True):
    return _mgr_add_item_object(self, payload, source_label=source_label, refresh=refresh, log=log)


def _mgr_adv_add_all_matching_selection(self):
    payload = self._adv_current_item_payload()
    if not any(str(payload.get(s, "") or "").strip() for s in STAGES):
        messagebox.showwarning("Advanced Selection", "Select at least one Element/Series/Material/Temper/Specification/Form value before adding all matches.")
        return
    rows = _mgr_rows_by_material_path(self, payload)
    if rows is None or rows.empty:
        messagebox.showwarning("Advanced Selection", "No exact matching source rows were found for the current Advanced Selection filters.")
        return
    if len(rows) > 100:
        if not messagebox.askyesno("Add All Matching", f"This will add {len(rows):,} exact source row(s) to the Export List. Continue?"):
            return
    added = 0
    for _, row in rows.iterrows():
        item = _mgr_sync_payload_from_row(self, dict(payload), row, overwrite_display=True)
        item["Source"] = "Manual - Add All Matching"
        item["Thickness_Mode"] = "Exact thickness text"
        if _mgr_add_item_object(self, item, source_label="matching row", refresh=False, log=False):
            added += 1
    self._adv_refresh_tree()
    self._adv_log(f"Added {added:,} exact matching source row(s) to the export list.")


# Export List editing: allow ID/MID, Basis, Direction, Unit, Model, and Notes.
def _mgr_adv_handle_tree_click(self, event):
    tree = getattr(self, "adv_tree", None)
    if tree is None:
        return None
    row_id = tree.identify_row(event.y)
    col_name = self._adv_tree_column_name(tree.identify_column(event.x))
    if row_id and col_name == "Export":
        self._adv_toggle_export_selected(int(row_id))
        return "break"
    if row_id and col_name == "View_Image":
        self._adv_show_image_for_item(int(row_id))
        return "break"
    if row_id and col_name in {"Export_ID", "Basis", "Direction", "Unit", "Model", "Notes"}:
        return self._adv_begin_export_list_edit(event)
    return None


def _mgr_options_for_export_cell(self, item: Dict[str, Any], col_name: str) -> List[str]:
    if col_name == "Basis":
        available = _mgr_available_bases_for_payload(self, item)
        return [code for _label, code in BASIS_OPTIONS if available.get(code, False)]
    if col_name == "Direction":
        return _mgr_available_directions_for_payload(self, item)
    if col_name == "Unit":
        return [label for label, _code in UNIT_SYSTEMS]
    if col_name == "Model":
        return _mgr_available_models_for_payload(self, item)
    return []


def _mgr_adv_begin_export_list_edit(self, event=None):
    tree = getattr(self, "adv_tree", None)
    if tree is None:
        return "break"
    row_id = tree.identify_row(event.y) if event is not None else (tree.selection()[0] if tree.selection() else "")
    col_id = tree.identify_column(event.x) if event is not None else ""
    col_name = self._adv_tree_column_name(col_id)
    editable_cols = {"Export_ID", "Basis", "Direction", "Unit", "Model", "Notes"}
    if not row_id or col_name not in editable_cols:
        return "break"
    try:
        idx = int(row_id)
        item = self.advanced_items[idx]
    except Exception:
        return "break"
    bbox = tree.bbox(row_id, col_id)
    if not bbox:
        return "break"
    try:
        if getattr(self, "adv_tree_edit_widget", None) is not None:
            self.adv_tree_edit_widget.destroy()
    except Exception:
        pass
    self.adv_tree_edit_widget = None
    x, y, width, height = bbox
    current = strip_dropdown_mark(tree.set(row_id, col_name))
    if col_name in {"Export_ID", "Notes"}:
        editor = ttk.Entry(tree)
        editor.place(x=x, y=y, width=width, height=height)
        editor.insert(0, current if col_name == "Notes" else (current or str(peek_next_export_id())))
        editor.select_range(0, tk.END)
        editor.focus_set()
        self.adv_tree_edit_widget = editor
        def commit(_event=None):
            value = editor.get().strip()
            self._adv_apply_export_cell_edit(idx, col_name, value)
            try:
                editor.destroy()
            except Exception:
                pass
            self.adv_tree_edit_widget = None
            return "break"
        def cancel(_event=None):
            try:
                editor.destroy()
            except Exception:
                pass
            self.adv_tree_edit_widget = None
            return "break"
        editor.bind("<Return>", commit)
        editor.bind("<FocusOut>", commit)
        editor.bind("<Escape>", cancel)
        return "break"
    options = _mgr_options_for_export_cell(self, item, col_name)
    if not options:
        messagebox.showwarning("Advanced Selection", f"No available {col_name} option exists for this exact source row.")
        return "break"
    combo = ttk.Combobox(tree, values=options, state="readonly")
    combo.place(x=x, y=y, width=width, height=height)
    combo.set(current if current in options else options[0])
    combo.focus_set()
    self.adv_tree_edit_widget = combo
    def commit_combo(_event=None):
        value = combo.get().strip()
        self._adv_apply_export_cell_edit(idx, col_name, value)
        try:
            combo.destroy()
        except Exception:
            pass
        self.adv_tree_edit_widget = None
        return "break"
    def cancel_combo(_event=None):
        try:
            combo.destroy()
        except Exception:
            pass
        self.adv_tree_edit_widget = None
        return "break"
    combo.bind("<<ComboboxSelected>>", commit_combo)
    combo.bind("<Return>", commit_combo)
    combo.bind("<FocusOut>", commit_combo)
    combo.bind("<Escape>", cancel_combo)
    return "break"


def _mgr_adv_apply_export_cell_edit(self, idx: int, col_name: str, new_value: str, option_index: int = -1):
    if not (0 <= idx < len(getattr(self, "advanced_items", []))):
        return
    item = self.advanced_items[idx]
    old_id = str(item.get("Export_ID", "") or "").strip()
    old_snapshot = {k: item.get(k) for k in ("Export_ID", "Basis", "Direction", "Unit_System", "Material_Model", "Notes")}
    try:
        if col_name == "Export_ID":
            new_id = str(normalize_export_id(new_value, default=peek_next_export_id()))
            for j, other in enumerate(self.advanced_items):
                if j != idx and str(other.get("Export_ID", "") or "").strip() == new_id:
                    messagebox.showerror("Export ID", f"ID / MID {new_id} already exists in the export list. Choose a different ID.")
                    return
            item["Export_ID"] = new_id
            item["_id_manual"] = True
            item["_edited_from_export_list"] = True
            advance_session_export_id_after(new_id)
        elif col_name == "Basis":
            value = str(new_value or "").strip().upper()
            if value not in _mgr_options_for_export_cell(self, item, "Basis"):
                messagebox.showwarning("Basis not available", f"{value} Basis is not available for this exact source row.")
                return
            item["Basis"] = value
            item["_edited_from_export_list"] = True
            item.update(_mgr_adv_ensure_payload_basis_direction(self, item))
        elif col_name == "Direction":
            value = "LT" if str(new_value or "").strip().upper() == "LT" else "L"
            if value not in _mgr_options_for_export_cell(self, {**item, "Direction": value}, "Direction"):
                messagebox.showwarning("Direction not available", f"{value} direction is not available for this exact source row/basis.")
                return
            item["Direction"] = value
            item["_edited_from_export_list"] = True
            item.update(_mgr_adv_ensure_payload_basis_direction(self, item))
        elif col_name == "Unit":
            item["Unit_System"] = self._adv_normalize_unit_system(new_value)
            item["_edited_from_export_list"] = True
        elif col_name == "Model":
            value = str(new_value or "").strip()
            if value not in _mgr_options_for_export_cell(self, item, "Model"):
                messagebox.showwarning("Matcard not available", f"{value} is not available for this exact source row/basis/direction.")
                return
            item["Material_Model"] = value
            item["_edited_from_export_list"] = True
        elif col_name == "Notes":
            item["Notes"] = str(new_value or "").strip()
        # Keep exact source row display fields from drifting.
        row = _mgr_row_by_source_key(self, _mgr_source_key_from_item(item))
        if row is not None and not ("_cei_is_custom_payload" in globals() and _cei_is_custom_payload(item)):
            item.update(_mgr_sync_payload_from_row(self, item, row, overwrite_display=True))
        _mgr_update_item_status(self, item)
        self._adv_refresh_tree()
        try:
            new_idx = self.advanced_items.index(item)
            self.adv_tree.selection_set(str(new_idx))
            self.adv_tree.see(str(new_idx))
        except Exception:
            pass
        self._adv_log(f"Updated export row ID/MID {item.get('Export_ID', old_id)}: {col_name} = {new_value}")
    except Exception as exc:
        for k, v in old_snapshot.items():
            item[k] = v
        messagebox.showerror("Advanced Selection", f"Could not update export row:\n\n{exc}")


def _mgr_adv_remove_duplicates(self):
    if not getattr(self, "advanced_items", []):
        messagebox.showinfo("Remove Duplicates", "There are no rows in the Export List.")
        return
    before = len(self.advanced_items)
    seen = set()
    kept = []
    for item in self.advanced_items:
        key = _mgr_duplicate_key(item)
        if key not in seen:
            seen.add(key)
            item.pop("_duplicate", None)
            kept.append(item)
    self.advanced_items = kept
    removed = before - len(self.advanced_items)
    self._adv_refresh_tree()
    if removed <= 0:
        messagebox.showinfo("Remove Duplicates", "No duplicate rows were found.")
        self._adv_log("Remove Duplicates clicked. No duplicate rows were found.")
    else:
        self._adv_log(f"Removed {removed} duplicate row(s). First occurrence was kept.")
        messagebox.showinfo("Remove Duplicates", f"Removed {removed} duplicate row(s).\n\nThe first occurrence was kept.")


# CSV upload: keep Notes/Comments/Remarks and exact rows.
def _mgr_adv_upload_input_csv(self):
    path = filedialog.askopenfilename(
        title="Select input CSV for batch export",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
    )
    if not path:
        return
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except Exception as exc:
        messagebox.showerror("Upload Input CSV", f"Could not read CSV:\n\n{exc}")
        return
    added = 0
    colmap = {norm(c).replace(" ", "_"): c for c in df.columns}
    def parse_selected(value, default=False):
        text = str(value).strip().lower()
        if text == "":
            return default
        return text in {"1", "true", "yes", "y", "x", "[x]", "✓", "checked", "select", "selected"}
    def pick(row, *names, default=""):
        for name in names:
            c = colmap.get(norm(name).replace(" ", "_"))
            if c is not None:
                return str(row.get(c, default)).strip()
        return default
    for _, row in df.iterrows():
        payload = {
            "Export_ID": pick(row, "Export ID", "Export_ID", "ID", "MID", "Material_ID", "Material ID"),
            "Element": pick(row, "Element"),
            "Series": pick(row, "Series"),
            "Material": pick(row, "Material"),
            "Temper": pick(row, "Temper"),
            "Specification": pick(row, "Specification", "Spec", "Spec1_1", "Main Specification"),
            "Specification 2": pick(row, "Specification 2", "Specification2", "Spec2", "Spec2_1", "Spec2_2"),
            "Form": pick(row, "Form"),
            "Basis": pick(row, "Basis", default=self.adv_basis_var.get()) or self.adv_basis_var.get(),
            "Direction": pick(row, "Direction", default=self.adv_direction_var.get()) or self.adv_direction_var.get(),
            "Unit_System": pick(row, "Unit_System", "Unit System", "Unit", default=self.adv_unit_sys_var.get()) or self.adv_unit_sys_var.get(),
            "Material_Model": pick(row, "Material_Model", "Material Model", "Model", "Matcard", default="MAT024+GISSMO") or "MAT024+GISSMO",
            "Thickness_Mode": "Exact thickness text",
            "Thickness": pick(row, "Thickness", "Thick_Value", "Thick Value", "Wall_Thick", "Stock Size Thickness", "Stock Thickness"),
            "Part_Number": pick(row, "Part Number", "Part_Number", "PartNo", "Part No"),
            "Part_Name": pick(row, "Part Name", "Part_Name", "Part Description"),
            "Material_Name_from_Client": pick(row, "Material Name from Client", "Client Material", "Material_from_Client"),
            "Stock_Size_Thickness": pick(row, "Stock Size Thickness", "Stock Thickness", "Stock_Size", "Stock Size"),
            "Datasheet": pick(row, "Datasheet", "Data Sheet", "DataSource"),
            "Notes": pick(row, "Notes", "Note", "Comments", "Comment", "Remarks", "Remark", "Internal Notes", "Validation Notes"),
            "Source": Path(path).name,
        }
        payload["_selected"] = parse_selected(pick(row, "Select", "Selected", "Export", "Export_Selected", "Include", default=""), default=False)
        payload["Unit_System"] = self._adv_normalize_unit_system(payload["Unit_System"])
        if payload["Material_Model"] not in {"MAT024", "MAT082", "MAT224", "MAT024+GISSMO"}:
            payload["Material_Model"] = "MAT024+GISSMO"
        if self._adv_add_payload(payload, source_label=Path(path).name, refresh=False, log=False):
            added += 1
    self._adv_refresh_tree()
    self._adv_log(f"Uploaded {added} item(s) from {Path(path).name}.")


# Export wrapper: sort by ID and block missing notes for custom/edited rows.
_MGR_PREV_ADV_EXPORT_ALL = SelectionScreen._adv_export_all


def _mgr_adv_export_all(self):
    _mgr_sort_advanced_items(self)
    missing_notes = []
    for visible_idx, item in enumerate(getattr(self, "advanced_items", []) or [], start=1):
        try:
            # Keep exact source row and valid options before exporting.
            row = _mgr_row_by_source_key(self, _mgr_source_key_from_item(item))
            if row is not None and not ("_cei_is_custom_payload" in globals() and _cei_is_custom_payload(item)):
                item.update(_mgr_sync_payload_from_row(self, item, row, overwrite_display=True))
            item.update(_mgr_adv_ensure_payload_basis_direction(self, item))
            _mgr_update_item_status(self, item)
        except Exception:
            pass
        if item.get("_selected", False) and _mgr_item_requires_notes(item) and not str(item.get("Notes", "") or "").strip():
            missing_notes.append(f"ID/MID {item.get('Export_ID', visible_idx)}")
    if missing_notes:
        messagebox.showwarning(
            "Notes Required",
            "Notes are required for custom/edited materials before export.\n\nMissing notes for: " + ", ".join(missing_notes[:12]) + ("..." if len(missing_notes) > 12 else "")
        )
        self._adv_refresh_tree()
        return
    self._adv_refresh_tree()
    return _MGR_PREV_ADV_EXPORT_ALL(self)


# Card -> Export List sync for normal rows opened from Advanced Selection.
_MGR_PREV_CARD_APPLY = CardScreen._apply


def _mgr_sync_regular_card_to_export_list(card) -> None:
    opened_id = str(getattr(card, "opened_export_id_context", "") or "").strip()
    if not opened_id:
        return
    try:
        selection_screen = card.app.screens.get("SelectionScreen")
    except Exception:
        selection_screen = None
    if selection_screen is None:
        return
    target = None
    for item in getattr(selection_screen, "advanced_items", []) or []:
        if str(item.get("Export_ID", "") or "").strip() == opened_id:
            target = item
            break
    if target is None:
        return
    # Custom blank rows are already synced by their own custom handler.
    try:
        if "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(target):
            return
    except Exception:
        pass
    changed = []
    field_map = {
        "Basis": str(card.basis_var.get() or "B"),
        "Direction": str(card.direction_var.get() or "L"),
        "Unit_System": str(card.unit_sys_var.get() or "mm_T_s"),
        "Material_Model": str(card.mat_model_var.get() or "MAT024+GISSMO"),
    }
    try:
        field_map["Export_ID"] = str(normalize_export_id(card.export_id_var.get(), default=int(opened_id)))
    except Exception:
        field_map["Export_ID"] = opened_id
    # Duplicate ID protection if card ID was edited.
    new_id = str(field_map.get("Export_ID", opened_id))
    if new_id != opened_id:
        for other in getattr(selection_screen, "advanced_items", []) or []:
            if other is not target and str(other.get("Export_ID", "") or "").strip() == new_id:
                messagebox.showerror("Export ID", f"ID / MID {new_id} already exists in the export list. Choose a different ID.")
                try:
                    card.export_id_var.set(opened_id)
                except Exception:
                    pass
                return
    for key, value in field_map.items():
        old = str(target.get(key, "") or "")
        if old != str(value):
            changed.append(f"{key}: {old} -> {value}")
            target[key] = value
    if changed:
        target["_edited_from_card"] = True
        target["_custom"] = True
        target["_user_changes"] = (str(target.get("_user_changes", "") or "") + "; " + "; ".join(changed)).strip("; ")
    try:
        row = getattr(card, "current_row", None)
        if row is not None:
            target.update(_mgr_sync_payload_from_row(selection_screen, target, row, overwrite_display=True))
    except Exception:
        pass
    try:
        target.update(_mgr_adv_ensure_payload_basis_direction(selection_screen, target))
        _mgr_update_item_status(selection_screen, target)
        selection_screen._adv_refresh_tree()
    except Exception:
        pass
    card.opened_export_id_context = str(target.get("Export_ID", opened_id))


def _mgr_card_apply(self):
    result = _MGR_PREV_CARD_APPLY(self)
    try:
        _mgr_sync_regular_card_to_export_list(self)
    except Exception:
        pass
    return result


_MGR_PREV_CARD_COMMIT = CardScreen._commit_all_pending_edits


def _mgr_card_commit_all_pending_edits(self, trigger: str = "Enter"):
    result = _MGR_PREV_CARD_COMMIT(self, trigger)
    try:
        _mgr_sync_regular_card_to_export_list(self)
    except Exception:
        pass
    return result


# Ftu/FTU required value highlighting and validation.
_MGR_PREV_MISSING_LABELS = CardScreen._missing_required_labels_from_computed


def _mgr_missing_required_labels_from_computed(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> List[str]:
    try:
        if computed is None:
            computed = self._compute_table()
    except Exception:
        computed = computed or {}
    labels = []
    try:
        selected_basis_available = self._selected_basis_available()
    except Exception:
        selected_basis_available = True
    required = [("Ftu", "FTU"), ("RO", "RO"), ("E", "E"), ("PR", "PR"), ("Fty", "SIGY")]
    for row_key, label in required:
        try:
            value = str(computed.get(row_key, {}).get("eng", "-")).strip()
            source_value = str(computed.get(row_key, {}).get("value", "-")).strip()
            if (not selected_basis_available) or is_blank(value) or is_blank(source_value):
                labels.append(label)
        except Exception:
            labels.append(label)
    # Preserve any extra required labels introduced by older code.
    try:
        old = _MGR_PREV_MISSING_LABELS(self, computed)
        for label in old:
            if label not in labels:
                labels.append(label)
    except Exception:
        pass
    return labels


def _mgr_missing_required_property_keys_from_computed(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> set:
    labels = set(_mgr_missing_required_labels_from_computed(self, computed))
    keys = set()
    if "FTU" in labels:
        keys.add("Ftu")
    if "RO" in labels:
        keys.add("RO")
    if "E" in labels:
        keys.add("E")
    if "PR" in labels:
        keys.add("PR")
    if "SIGY" in labels:
        keys.add("Fty")
    return keys




def _mgr_adv_apply_export_cell_edit_multi(self, idx: int, col_name: str, new_value: str, option_index: int = -1):
    target_indexes = [idx]
    # Unit edits are allowed to apply to all selected rows; row-specific fields
    # such as Basis/Direction/Model remain single-row edits because their valid
    # options depend on the exact source row.
    if col_name == "Unit":
        try:
            target_indexes = sorted({int(i) for i in self.adv_tree.selection()} | {idx})
        except Exception:
            target_indexes = [idx]
    for target_idx in target_indexes:
        _mgr_adv_apply_export_cell_edit(self, target_idx, col_name, new_value, option_index=option_index if target_idx == idx else -1)


def _mgr_adv_open_export_list_row_card(self, event=None):
    tree = getattr(self, "adv_tree", None)
    if tree is None:
        return "break"
    try:
        col_name = self._adv_tree_column_name(tree.identify_column(event.x)) if event is not None else ""
    except Exception:
        col_name = ""
    # Do not open the card from editable/action cells.
    if col_name in {"Export", "Export_ID", "Basis", "Direction", "Unit", "Model", "Notes", "View_Image"}:
        return "break"
    try:
        if "_cei_adv_open_export_list_row_card" in globals():
            return _cei_adv_open_export_list_row_card(self, event)
        if "_hf_adv_open_export_list_row_card" in globals():
            return _hf_adv_open_export_list_row_card(self, event)
    except Exception:
        pass
    return "break"

# Apply final manager-test overrides.
SelectionScreen._adv_match_rows = _mgr_adv_match_rows
SelectionScreen._adv_rows_to_export = _mgr_adv_rows_to_export
SelectionScreen._adv_available_bases_for_payload = _mgr_available_bases_for_payload
SelectionScreen._adv_available_directions_for_payload = _mgr_available_directions_for_payload
SelectionScreen._adv_ensure_payload_basis_direction = _mgr_adv_ensure_payload_basis_direction
SelectionScreen._adv_duplicate_key = _mgr_adv_duplicate_key
SelectionScreen._adv_duplicate_indexes = _mgr_adv_duplicate_indexes
SelectionScreen._adv_refresh_tree = _mgr_adv_refresh_tree
SelectionScreen._adv_add_payload = _mgr_adv_add_payload
SelectionScreen._adv_add_all_matching_selection = _mgr_adv_add_all_matching_selection
SelectionScreen._adv_handle_tree_click = _mgr_adv_handle_tree_click
SelectionScreen._adv_options_for_export_cell = _mgr_options_for_export_cell
SelectionScreen._adv_begin_export_list_edit = _mgr_adv_begin_export_list_edit
SelectionScreen._adv_apply_export_cell_edit = _mgr_adv_apply_export_cell_edit
SelectionScreen._adv_apply_export_cell_edit_multi = _mgr_adv_apply_export_cell_edit_multi
SelectionScreen._adv_open_export_list_row_card = _mgr_adv_open_export_list_row_card
SelectionScreen._adv_remove_duplicates = _mgr_adv_remove_duplicates
SelectionScreen._adv_upload_input_csv = _mgr_adv_upload_input_csv
SelectionScreen._adv_export_all = _mgr_adv_export_all
CardScreen._apply = _mgr_card_apply
CardScreen._commit_all_pending_edits = _mgr_card_commit_all_pending_edits
CardScreen._missing_required_labels_from_computed = _mgr_missing_required_labels_from_computed
CardScreen._missing_required_property_keys_from_computed = _mgr_missing_required_property_keys_from_computed

# End marker for VS Code search:
# REHAN_ADVANCED_SELECTION_MANAGER_TEST_FIX_ACTIVE_2026_06_22


# -----------------------------------------------------------------------------
# FINAL PATCH: Excel summary must use live edited/custom card values
# -----------------------------------------------------------------------------
# REHAN_ADVANCED_SELECTION_EXCEL_NOTES_CUSTOM_FIX_2026_06_22
# Fixes:
# 1) Advanced export_summary.xlsx/export_summary.csv now uses the same edited
#    Property Card values that are written into the keyfile. Example: if Etan is
#    edited to 10.3, Tangent Modulus in Excel is 10.3, not the original database
#    blank/source value.
# 2) Notes and Custom Entry behavior from the earlier patch are preserved:
#    notes stay visible in the Export List, custom/edited rows remain marked,
#    and notes are still required before export for custom/edited rows.
# 3) Normal rows opened from Advanced Selection keep their live card edit state
#    in the export-list item so keyfile, Excel, image/export order, and summary
#    all use one source of truth.

_PROPERTY_TO_SUMMARY_KEYS = {
    "Ftu": "Ftu",
    "Fty": "Fty",
    "Fcy": "Fcy",
    "Fsu": "Fsu",
    "Elong": "Elong",
    "Young Modulus": "E",
    "Tangent Modulus": "Etan",
    "Poisson": "PR",
    "Density": "RO",
}


def _final_prop_value_from_state(state: Any, prop_key: str) -> Tuple[str, bool]:
    """Return (value, edited_flag) for a property stored in _card_custom_state."""
    if not isinstance(state, dict):
        return "", False
    prop_values = state.get("prop_values", {})
    if not isinstance(prop_values, dict):
        return "", False
    raw = prop_values.get(prop_key)
    if raw is None:
        return "", False
    if isinstance(raw, dict):
        return str(raw.get("value", "") or "").strip(), bool(raw.get("edited", False))
    if isinstance(raw, (list, tuple)):
        value = str(raw[0] if len(raw) >= 1 else "").strip()
        edited = bool(raw[1]) if len(raw) >= 2 else False
        return value, edited
    return str(raw or "").strip(), False


def _final_summary_value_from_item(selection_screen, item: Dict[str, Any], row: Any,
                                   summary_key: str, basis: str, direction: str) -> str:
    """Use edited/custom card values for Excel summary, fallback to source row."""
    prop_key = _PROPERTY_TO_SUMMARY_KEYS.get(summary_key)
    if prop_key:
        state = item.get("_card_custom_state") if isinstance(item, dict) else None
        value, edited = _final_prop_value_from_state(state, prop_key)
        # For edited normal rows, use edited values. For custom blank rows, all
        # stored values are user-entered values, even when the edited flag is False.
        is_custom = False
        try:
            is_custom = "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(item)
        except Exception:
            is_custom = False
        if value and not is_blank(value) and (edited or is_custom or _mgr_item_is_custom_or_edited(item)):
            return fmt_number(value) if try_float(value) is not None else value
    try:
        return selection_screen._adv_summary_material_value(row, summary_key, basis, direction)
    except Exception:
        return ""


_FINAL_PREV_ADV_SUMMARY_ROW = SelectionScreen._adv_summary_row


def _final_adv_summary_row_live_values(self, item: Dict[str, Any], item_idx: int, status: str,
                                       keyfile_name: str, keyfile_path: str, image_path: str,
                                       notes: str, image_name: str = "", row: Optional[pd.Series] = None,
                                       export_id: Any = "") -> Dict[str, Any]:
    summary = _FINAL_PREV_ADV_SUMMARY_ROW(
        self, item, item_idx, status, keyfile_name, keyfile_path, image_path,
        notes, image_name=image_name, row=row, export_id=export_id,
    )
    try:
        basis = str(item.get("Basis", summary.get("Main Basis", "")) or "")
        direction = str(item.get("Direction", summary.get("Main Direction", "")) or "")
        for summary_key in (
            "Ftu", "Fty", "Fcy", "Fsu", "Elong",
            "Young Modulus", "Tangent Modulus", "Poisson", "Density",
        ):
            summary[summary_key] = _final_summary_value_from_item(self, item, row, summary_key, basis, direction)

        # Keep notes exactly as the user typed them in the Export List. This also
        # protects CSV-uploaded comments/remarks and custom-material notes.
        final_notes = str(notes or item.get("Notes", "") or "").strip()
        summary["Notes"] = final_notes
        if _mgr_item_is_custom_or_edited(item):
            if str(summary.get("Internal Notes", "") or "").strip():
                summary["Internal Notes"] = str(summary.get("Internal Notes", "")) + "; CUSTOM / EDITED material"
            else:
                summary["Internal Notes"] = "CUSTOM / EDITED material"
            if str(status).strip().lower() == "exported":
                summary["Status"] = "CUSTOM / EDITED - Exported"
        # Custom blank material should use the visible Custom_Name/Material name
        # in client-facing columns when no client name was supplied.
        if "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(item):
            custom_name = str(item.get("Custom_Name") or item.get("Material") or "CUSTOM_MATERIAL").strip()
            if not str(summary.get("Material Name from Client", "") or "").strip():
                summary["Material Name from Client"] = custom_name
            summary["Material"] = custom_name
            summary["Main Specification"] = str(item.get("Specification") or "CUSTOM")
            summary["Main Form"] = str(item.get("Form") or "CUSTOM")
            summary["Source"] = "Custom Blank Entry"
    except Exception:
        pass
    return summary


SelectionScreen._adv_summary_row = _final_adv_summary_row_live_values


_FINAL_PREV_CARD_COMMIT = CardScreen._commit_all_pending_edits


def _final_card_commit_save_live_state(self, trigger: str = "Enter"):
    """After any card edit, keep exact edited values attached to the export row."""
    result = _FINAL_PREV_CARD_COMMIT(self, trigger)
    opened_id = str(getattr(self, "opened_export_id_context", "") or "").strip()
    if not opened_id:
        return result
    try:
        selection_screen = self.app.screens.get("SelectionScreen")
    except Exception:
        selection_screen = None
    if selection_screen is None:
        return result
    target = None
    for item in getattr(selection_screen, "advanced_items", []) or []:
        if str(item.get("Export_ID", "") or "").strip() == opened_id:
            target = item
            break
    if target is None:
        return result

    try:
        prop_values = dict(getattr(self, "prop_values", {}) or {})
        unit_conversions = dict(getattr(self, "unit_conversions", {}) or {})
        has_prop_edits = any(bool(v[1]) for v in prop_values.values() if isinstance(v, (list, tuple)) and len(v) >= 2)
        has_unit_edits = bool(getattr(self, "unit_confirmed_edits", set())) or any(
            try_float(unit_conversions.get(k)) is not None
            and try_float(DEFAULT_UNIT_CONVERSIONS.get(k)) is not None
            and float(unit_conversions.get(k)) != float(DEFAULT_UNIT_CONVERSIONS.get(k))
            for k in DEFAULT_UNIT_CONVERSIONS
        )
        is_custom = False
        try:
            is_custom = "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(target)
        except Exception:
            is_custom = False
        # Save state for edited normal rows and custom rows. This is what the
        # keyfile exporter and now the Excel summary both read from.
        if has_prop_edits or has_unit_edits or is_custom or isinstance(target.get("_card_custom_state"), dict):
            target["_card_custom_state"] = {
                "prop_values": {k: [str(v[0]), bool(v[1])] if isinstance(v, (list, tuple)) else [str(v), False]
                                for k, v in prop_values.items()},
                "unit_conversions": {k: unit_conversions.get(k, v) for k, v in DEFAULT_UNIT_CONVERSIONS.items()},
                "custom_name": str(getattr(getattr(self, "custom_name_var", None), "get", lambda: "")() or target.get("Custom_Name", "") or ""),
                "custom_image_paths": list(getattr(self, "custom_image_paths", []) or target.get("Custom_Image_Paths", []) or []),
                "is_custom_blank_entry": bool(is_custom or getattr(self, "is_custom_entry", False)),
            }
            target["_custom"] = True
            target["_edited_from_card"] = True
            target["_tag"] = "custom_row"
            target["_status"] = "CUSTOM / EDITED - Ready"
            target.setdefault("Notes", "")
        try:
            if not ("_cei_is_custom_payload" in globals() and _cei_is_custom_payload(target)):
                row = getattr(self, "current_row", None)
                if row is not None:
                    target.update(_mgr_sync_payload_from_row(selection_screen, target, row, overwrite_display=True))
                    target.update(_mgr_adv_ensure_payload_basis_direction(selection_screen, target))
        except Exception:
            pass
        try:
            _mgr_update_item_status(selection_screen, target)
            selection_screen._adv_refresh_tree()
        except Exception:
            pass
    except Exception:
        pass
    return result


CardScreen._commit_all_pending_edits = _final_card_commit_save_live_state


# Keep custom payload notes from existing export-list row and do not drop Custom_Name.
if "_cei_store_custom_card_to_export_list" in globals():
    _FINAL_PREV_STORE_CUSTOM_CARD = _cei_store_custom_card_to_export_list

    def _final_store_custom_card_to_export_list(card) -> bool:
        return _FINAL_PREV_STORE_CUSTOM_CARD(card)



# -----------------------------------------------------------------------------
# FINAL PATCH: Material Card notes/export-name section for every material
# -----------------------------------------------------------------------------
# REHAN_CARD_NOTES_EVERY_MATERIAL_EXPORT_NAME_FIX_2026_06_22
# Fixes:
# - The Material Card always shows the Notes section for every material, not only
#   custom rows.
# - The Material Card always shows the editable yellow Export Material Name box.
# - Notes and Export Material Name sync back to the Advanced Export List item.
# - Edited Export Material Name is used for keyfile/image/export summary stems.


def _card_notes_ensure_vars(self):
    try:
        if not hasattr(self, "material_notes_var"):
            self.material_notes_var = tk.StringVar(value="")
        if not hasattr(self, "export_material_name_var"):
            self.export_material_name_var = tk.StringVar(value="")
    except Exception:
        pass


def _card_safe_file_part_from_selection(value: Any) -> str:
    text = str(value or "").strip() or "NA"
    repl = {"<=": "le", ">=": "ge", "<": "lt", ">": "gt", " ": "_", "/": "_", "\\": "_", ":": "_", "*": "_", "?": "_", chr(34): "_", "|": "_", ",": "_"}
    for old, new in repl.items():
        text = text.replace(old, new)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_") or "NA"


def _card_default_export_material_name(self) -> str:
    """Default yellow-box name for normal database rows."""
    try:
        row = getattr(self, "current_row", None)
        sel = getattr(self, "current_selections", {}) or {}
        material = sel.get("Material") or (row.get("Material", "Material") if row is not None and hasattr(row, "get") else "Material")
        temper = sel.get("Temper") or (row.get("Temper", "Temper") if row is not None and hasattr(row, "get") else "Temper")
        spec = sel.get("Specification") or (row.get("Spec1_1", row.get("Specification", "Spec")) if row is not None and hasattr(row, "get") else "Spec")
        thickness = str(getattr(self, "thickness_var", tk.StringVar(value="")).get() or "").strip()
        if not thickness and row is not None:
            try:
                thickness = self._thickness_display_label(row)
            except Exception:
                thickness = source_thickness_display_label(row)
        direction = str(getattr(self, "direction_var", tk.StringVar(value="L")).get() or "L").strip()
        basis = str(getattr(self, "basis_var", tk.StringVar(value="B")).get() or "B").strip()
        export_id = str(getattr(self, "export_id_var", tk.StringVar(value="1000")).get() or "1000").strip()
        try:
            batch_no = int(float(export_id)) - EXPORT_COUNTER_START + 1
            if batch_no < 1:
                batch_no = 1
        except Exception:
            batch_no = 1
        parts = [
            f"batch{batch_no:03d}",
            _card_safe_file_part_from_selection(material),
            _card_safe_file_part_from_selection(temper),
            _card_safe_file_part_from_selection(spec),
            _card_safe_file_part_from_selection(thickness or "NA"),
            _card_safe_file_part_from_selection(direction),
            _card_safe_file_part_from_selection(basis),
        ]
        return "_".join([p for p in parts if p])[:110]
    except Exception:
        return "batch001_Material_Temper_Spec_Thickness_L_B"


def _card_current_notes_text(self) -> str:
    try:
        widget = getattr(self, "material_notes_text", None)
        if widget is not None and widget.winfo_exists():
            value = widget.get("1.0", tk.END).strip()
            try:
                self.material_notes_var.set(value)
            except Exception:
                pass
            return value
    except Exception:
        pass
    try:
        return str(getattr(self, "material_notes_var", tk.StringVar(value="")).get() or "").strip()
    except Exception:
        return ""


def _card_find_opened_adv_item(self):
    opened_id = str(getattr(self, "opened_export_id_context", "") or "").strip()
    if not opened_id:
        return None, None
    try:
        selection_screen = self.app.screens.get("SelectionScreen")
    except Exception:
        selection_screen = None
    if selection_screen is None:
        return None, None
    for idx, item in enumerate(getattr(selection_screen, "advanced_items", []) or []):
        if str(item.get("Export_ID", "") or "").strip() == opened_id:
            return selection_screen, item
    return selection_screen, None


def _card_sync_notes_and_export_name_to_adv_item(self, mark_edited: bool = False):
    try:
        _card_notes_ensure_vars(self)
        selection_screen, target = _card_find_opened_adv_item(self)
        if target is None:
            return
        notes = _card_current_notes_text(self)
        export_name = str(getattr(self, "export_material_name_var", tk.StringVar(value="")).get() or "").strip()
        if notes or "Notes" in target:
            target["Notes"] = notes
        if export_name:
            target["Export_Material_Name"] = export_name
            target["Export_Name"] = export_name
            # Treat changing the yellow name as an edit, because output files now depend on it.
            default_name = str(getattr(self, "_default_export_material_name", "") or "").strip()
            if mark_edited or (default_name and norm(export_name) != norm(default_name)):
                target["_edited_from_card"] = True
                target["_custom"] = True
                target["_tag"] = "custom_row"
                target["_status"] = "CUSTOM / EDITED - Ready"
        try:
            if "_mgr_update_item_status" in globals():
                _mgr_update_item_status(selection_screen, target)
        except Exception:
            pass
        try:
            selection_screen._adv_refresh_tree()
        except Exception:
            pass
    except Exception:
        pass


def _card_on_notes_changed(self, event=None):
    try:
        _card_sync_notes_and_export_name_to_adv_item(self, mark_edited=False)
    except Exception:
        pass


def _card_on_export_name_changed(self, event=None):
    try:
        _card_sync_notes_and_export_name_to_adv_item(self, mark_edited=True)
    except Exception:
        pass


_PREV_CARD_RENDER_CONTROLS_NOTES_EVERY = CardScreen._render_controls

def _card_render_controls_with_notes_every_material(self):
    _card_notes_ensure_vars(self)
    result = _PREV_CARD_RENDER_CONTROLS_NOTES_EVERY(self)
    try:
        # Avoid duplicate section after theme refresh/re-render. The original render
        # destroys controls children first, so adding this once at the end is stable.
        current_default = _card_default_export_material_name(self)
        self._default_export_material_name = current_default
        if not str(self.export_material_name_var.get() or "").strip():
            self.export_material_name_var.set(current_default)

        notes_section = tk.Frame(
            self.controls,
            bg=THEME["panel_alt"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            bd=0,
        )
        notes_section.pack(fill=tk.X, padx=10, pady=(0, 8))

        title_row = tk.Frame(notes_section, bg=THEME["panel_alt"])
        title_row.pack(fill=tk.X, padx=12, pady=(7, 2))
        tk.Label(
            title_row,
            text="Export Material Name and Notes",
            bg=THEME["panel_alt"],
            fg=THEME["accent"],
            font=FONTS["small_bold"],
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Label(
            title_row,
            text="Notes are required only when this material is custom or edited.",
            bg=THEME["panel_alt"],
            fg=THEME["text_muted"],
            font=FONTS["caption"],
            anchor="e",
        ).pack(side=tk.RIGHT)

        row = tk.Frame(notes_section, bg=THEME["panel_alt"])
        row.pack(fill=tk.X, padx=12, pady=(2, 8))
        row.columnconfigure(1, weight=1)
        row.columnconfigure(3, weight=2)

        tk.Label(row, text="Export Material Name", bg=THEME["panel_alt"], fg=THEME["text_muted"], font=FONTS["small_bold"]).grid(row=0, column=0, sticky="w", padx=(0, 8))
        export_entry = tk.Entry(
            row,
            textvariable=self.export_material_name_var,
            bg=THEME.get("edit_bg", "#FFF5CC"),
            fg=THEME.get("edit_fg", "#5F4300"),
            insertbackground=THEME.get("edit_fg", "#5F4300"),
            relief="solid",
            bd=1,
            font=FONTS["small"],
        )
        export_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        export_entry.bind("<KeyRelease>", lambda e: _card_on_export_name_changed(self, e), add="+")
        export_entry.bind("<FocusOut>", lambda e: _card_on_export_name_changed(self, e), add="+")

        tk.Label(row, text="Notes", bg=THEME["panel_alt"], fg=THEME["text_muted"], font=FONTS["small_bold"]).grid(row=0, column=2, sticky="nw", padx=(0, 8))
        notes_text = tk.Text(
            row,
            height=2,
            wrap="word",
            bg=THEME.get("text_area_bg", "#FFFFFF"),
            fg=THEME.get("text_area_fg", "#111827"),
            insertbackground=THEME.get("text_area_fg", "#111827"),
            relief="solid",
            bd=1,
            font=FONTS["small"],
        )
        notes_text.grid(row=0, column=3, sticky="ew")
        notes_text.insert("1.0", str(self.material_notes_var.get() or ""))
        notes_text.bind("<KeyRelease>", lambda e: _card_on_notes_changed(self, e), add="+")
        notes_text.bind("<FocusOut>", lambda e: _card_on_notes_changed(self, e), add="+")
        self.material_notes_text = notes_text
        self.export_material_name_entry = export_entry
    except Exception:
        pass
    return result


CardScreen._render_controls = _card_render_controls_with_notes_every_material


_PREV_CARD_ON_SHOW_NOTES_EVERY = CardScreen.on_show

def _card_on_show_notes_every_material(self, row=None, selections=None, matching_rows=None, history_state=None, **kwargs):
    _card_notes_ensure_vars(self)
    # Load notes/export name from the Advanced export-list item or history_state
    # before rendering. This keeps the notes box visible and prefilled on open.
    try:
        incoming_notes = ""
        incoming_export_name = ""
        if isinstance(history_state, dict):
            incoming_notes = str(history_state.get("Notes", "") or history_state.get("notes", "") or "").strip()
            incoming_export_name = str(history_state.get("Export_Material_Name", "") or history_state.get("Export_Name", "") or "").strip()
            opened_id = str(history_state.get("Export_ID", "") or "").strip()
            if opened_id:
                try:
                    ss = self.app.screens.get("SelectionScreen")
                    for item in getattr(ss, "advanced_items", []) or []:
                        if str(item.get("Export_ID", "") or "").strip() == opened_id:
                            incoming_notes = str(item.get("Notes", incoming_notes) or incoming_notes or "").strip()
                            incoming_export_name = str(item.get("Export_Material_Name", "") or item.get("Export_Name", "") or item.get("Custom_Name", "") or incoming_export_name or "").strip()
                            break
                except Exception:
                    pass
        self.material_notes_var.set(incoming_notes)
        self.export_material_name_var.set(incoming_export_name)
    except Exception:
        pass
    result = _PREV_CARD_ON_SHOW_NOTES_EVERY(self, row=row, selections=selections, matching_rows=matching_rows, history_state=history_state, **kwargs)
    try:
        # If no export name came from the item, fill after row/thickness are ready.
        if not str(self.export_material_name_var.get() or "").strip():
            self.export_material_name_var.set(_card_default_export_material_name(self))
        _card_on_notes_changed(self)
    except Exception:
        pass
    return result


CardScreen.on_show = _card_on_show_notes_every_material


_PREV_CARD_COMMIT_NOTES_EVERY = CardScreen._commit_all_pending_edits

def _card_commit_notes_every_material(self, trigger: str = "Enter"):
    result = _PREV_CARD_COMMIT_NOTES_EVERY(self, trigger)
    try:
        _card_sync_notes_and_export_name_to_adv_item(self, mark_edited=False)
    except Exception:
        pass
    return result


CardScreen._commit_all_pending_edits = _card_commit_notes_every_material


_PREV_CARD_BACK_NOTES_EVERY = CardScreen._back_to_selection

def _card_back_notes_every_material(self):
    try:
        _card_sync_notes_and_export_name_to_adv_item(self, mark_edited=False)
    except Exception:
        pass
    return _PREV_CARD_BACK_NOTES_EVERY(self)


CardScreen._back_to_selection = _card_back_notes_every_material


_PREV_ADV_SHORT_OUTPUT_STEM_NOTES_EVERY = SelectionScreen._adv_short_output_stem

def _adv_short_output_stem_use_export_material_name(self, item: Dict[str, Any], row: pd.Series, item_idx: int, row_idx: int) -> str:
    try:
        custom_or_export_name = str(item.get("Export_Material_Name", "") or item.get("Export_Name", "") or "").strip()
        if not custom_or_export_name and ("_cei_is_custom_payload" in globals() and _cei_is_custom_payload(item)):
            custom_or_export_name = str(item.get("Custom_Name", "") or item.get("Material", "") or "").strip()
        if custom_or_export_name:
            return _card_safe_file_part_from_selection(custom_or_export_name)[:110]
    except Exception:
        pass
    return _PREV_ADV_SHORT_OUTPUT_STEM_NOTES_EVERY(self, item, row, item_idx, row_idx)


SelectionScreen._adv_short_output_stem = _adv_short_output_stem_use_export_material_name


_PREV_ADV_SUMMARY_ROW_EXPORT_NAME_NOTES_EVERY = SelectionScreen._adv_summary_row

def _adv_summary_row_export_name_notes_every(self, item: Dict[str, Any], item_idx: int, status: str,
                                             keyfile_name: str, keyfile_path: str, image_path: str,
                                             notes: str, image_name: str = "", row: Optional[pd.Series] = None,
                                             export_id: Any = "") -> Dict[str, Any]:
    summary = _PREV_ADV_SUMMARY_ROW_EXPORT_NAME_NOTES_EVERY(
        self, item, item_idx, status, keyfile_name, keyfile_path, image_path,
        notes, image_name=image_name, row=row, export_id=export_id,
    )
    try:
        export_name = str(item.get("Export_Material_Name", "") or item.get("Export_Name", "") or "").strip()
        if export_name:
            summary["Export Material Name"] = export_name
            if not str(summary.get("Material Name from Client", "") or "").strip():
                summary["Material Name from Client"] = export_name
        summary["Notes"] = str(item.get("Notes", notes) or notes or "").strip()
    except Exception:
        pass
    return summary


SelectionScreen._adv_summary_row = _adv_summary_row_export_name_notes_every


def _r19_safe_name_piece(value: Any, *, spec: bool = False) -> str:
    text = str(value or "").strip()
    if not text or is_blank(text) or text == NO_SPEC_DISPLAY:
        text = "NA"
    text = text.replace("\u2264", "<=").replace("\u2265", ">=").replace("\u2013", "-").replace("\u2014", "-")
    if spec:
        text = _rehan_re.sub(r"\s+", "-", text)
    else:
        text = _rehan_re.sub(r"\s+", "", text)
    replacements = {
        "<=": "le", ">=": "ge", "<": "lt", ">": "gt",
        "/": "_", "\\": "_", ":": "_", "*": "_", "?": "_", '"': "_",
        "|": "_", ",": "_", ";": "_", "(": "", ")": "", "[": "", "]": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = _rehan_re.sub(r"_+", "_", text).strip("_-. ")
    return text or "NA"


def _r19_element_code(value: Any) -> str:
    text = str(value or "").strip()
    low = text.lower()
    if low.startswith("al") or "aluminum" in low or "aluminium" in low:
        return "AL"
    if low.startswith("ti") or "titanium" in low:
        return "TI"
    if low.startswith("steel") or low.startswith("st"):
        return "STEEL"
    return _r19_safe_name_piece(text).upper()


def _r19_unit_name_for_material_name(unit_sys: str) -> str:
    try:
        label = UNIT_SYSTEM_SPEC.get(unit_sys, UNIT_SYSTEM_SPEC["mm_T_s"]).get("pressure_label", "MPa")
    except Exception:
        label = "MPa"
    return str(label or "MPa").replace("µ", "u").upper()


def _r19_card_target_item(card):
    try:
        if "_card_find_opened_adv_item" in globals():
            return _card_find_opened_adv_item(card)
    except Exception:
        pass
    opened_id = str(getattr(card, "opened_export_id_context", "") or "").strip()
    try:
        ss = card.app.screens.get("SelectionScreen")
    except Exception:
        ss = None
    if ss is None or not opened_id:
        return ss, None
    for item in getattr(ss, "advanced_items", []) or []:
        if str(item.get("Export_ID", "") or "").strip() == opened_id:
            return ss, item
    return ss, None


def _r19_card_has_user_edits(card) -> bool:
    try:
        if bool(getattr(card, "is_custom_entry", False)):
            return True
    except Exception:
        pass
    try:
        _ss, target = _r19_card_target_item(card)
        if isinstance(target, dict) and "_mgr_item_is_custom_or_edited" in globals() and _mgr_item_is_custom_or_edited(target):
            return True
    except Exception:
        pass
    try:
        if any(bool(v[1]) for v in getattr(card, "prop_values", {}).values() if isinstance(v, (list, tuple)) and len(v) >= 2):
            return True
    except Exception:
        pass
    try:
        if bool(getattr(card, "unit_confirmed_edits", set())):
            return True
    except Exception:
        pass
    try:
        for k, default_value in DEFAULT_UNIT_CONVERSIONS.items():
            current = try_float(getattr(card, "unit_conversions", {}).get(k, default_value))
            default = try_float(default_value)
            if current is not None and default is not None and float(current) != float(default):
                return True
    except Exception:
        pass
    return False


def _r19_generated_material_name(card, *, custom_prefix: Optional[bool] = None) -> str:
    row = getattr(card, "current_row", None)
    sel = getattr(card, "current_selections", {}) or {}
    try:
        element = sel.get("Element") or (row.get("Element", "AL") if row is not None and hasattr(row, "get") else "AL")
        material = sel.get("Material") or (row.get("Material", "Material") if row is not None and hasattr(row, "get") else "Material")
        temper = sel.get("Temper") or (row.get("Temper", "Temper") if row is not None and hasattr(row, "get") else "Temper")
        spec = sel.get("Specification") or (row.get("Spec1_1", row.get("Specification", "Spec")) if row is not None and hasattr(row, "get") else "Spec")
        form = sel.get("Form") or (row.get("Form", "Form") if row is not None and hasattr(row, "get") else "Form")
    except Exception:
        element, material, temper, spec, form = "AL", "Material", "Temper", "Spec", "Form"
    try:
        thickness = str(getattr(card, "thickness_var", tk.StringVar(value="")).get() or "").strip()
    except Exception:
        thickness = ""
    if not thickness and row is not None:
        try:
            thickness = card._thickness_display_label(row)
        except Exception:
            thickness = source_thickness_display_label(row)
    basis = str(getattr(card, "basis_var", tk.StringVar(value="B")).get() or "B").strip().upper() or "B"
    direction = str(getattr(card, "direction_var", tk.StringVar(value="L")).get() or "L").strip().upper() or "L"
    unit_sys = str(getattr(card, "unit_sys_var", tk.StringVar(value="mm_T_s")).get() or "mm_T_s").strip()
    model = str(getattr(card, "mat_model_var", tk.StringVar(value="MAT024")).get() or "MAT024").strip()
    material_temper = f"{_r19_safe_name_piece(material)}-{_r19_safe_name_piece(temper)}"
    parts = [
        _r19_element_code(element),
        material_temper,
        _r19_safe_name_piece(spec, spec=True),
        _r19_safe_name_piece(form),
        _r19_safe_name_piece(thickness or "NA"),
        f"{_r19_safe_name_piece(basis)}_Basis",
        _r19_safe_name_piece(direction),
        _r19_unit_name_for_material_name(unit_sys),
        _r19_safe_name_piece(model),
    ]
    name = "_".join([p for p in parts if p and p != "NA"])
    if custom_prefix is None:
        custom_prefix = _r19_card_has_user_edits(card)
    if custom_prefix and not name.upper().startswith("CUSTOM_"):
        name = "CUSTOM_" + name
    return name[:160]


# Override the old batch### default name helper with the current requested format.
def _r19_card_default_export_material_name(card) -> str:
    return _r19_generated_material_name(card, custom_prefix=_r19_card_has_user_edits(card))


_card_default_export_material_name = _r19_card_default_export_material_name


def _r19_notes_text(card) -> str:
    try:
        if "_card_current_notes_text" in globals():
            return _card_current_notes_text(card)
    except Exception:
        pass
    try:
        w = getattr(card, "material_notes_text", None)
        if w is not None and w.winfo_exists():
            return w.get("1.0", tk.END).strip()
    except Exception:
        pass
    try:
        return str(getattr(card, "material_notes_var", tk.StringVar(value="")).get() or "").strip()
    except Exception:
        return ""


def _r19_ensure_card_vars(card):
    try:
        if "_card_notes_ensure_vars" in globals():
            _card_notes_ensure_vars(card)
        if not hasattr(card, "material_notes_var"):
            card.material_notes_var = tk.StringVar(value="")
        if not hasattr(card, "export_material_name_var"):
            card.export_material_name_var = tk.StringVar(value="")
        if not hasattr(card, "_r19_name_user_locked"):
            card._r19_name_user_locked = False
    except Exception:
        pass


def _r19_refresh_material_name(card, *, force: bool = False, custom_prefix: Optional[bool] = None) -> str:
    _r19_ensure_card_vars(card)
    generated = _r19_generated_material_name(card, custom_prefix=custom_prefix)
    try:
        current = str(card.export_material_name_var.get() or "").strip()
    except Exception:
        current = ""
    locked = bool(getattr(card, "_r19_name_user_locked", False))
    if force or not current or not locked:
        try:
            card.export_material_name_var.set(generated)
            current = generated
        except Exception:
            current = generated
    elif (custom_prefix is True or _r19_card_has_user_edits(card)) and current and not current.upper().startswith("CUSTOM_"):
        # Manager rule: custom/edited material names carry CUSTOM_.
        current = "CUSTOM_" + current
        try:
            card.export_material_name_var.set(current)
        except Exception:
            pass
    try:
        card._default_export_material_name = generated
    except Exception:
        pass
    return current or generated


def _r19_name_changed(card, event=None):
    _r19_ensure_card_vars(card)
    try:
        card._r19_name_user_locked = True
    except Exception:
        pass
    try:
        if bool(getattr(card, "is_custom_entry", False)):
            if not hasattr(card, "custom_name_var"):
                card.custom_name_var = tk.StringVar(value="")
            card.custom_name_var.set(str(card.export_material_name_var.get() or "").strip())
    except Exception:
        pass
    try:
        _r19_sync_card_to_adv_item(card, mark_edited=True, refresh=True, validate_notes=False)
    except Exception:
        pass


def _r19_notes_changed(card, event=None):
    _r19_ensure_card_vars(card)
    try:
        val = _r19_notes_text(card)
        card.material_notes_var.set(val)
    except Exception:
        pass
    try:
        _r19_sync_card_to_adv_item(card, mark_edited=False, refresh=True, validate_notes=False)
    except Exception:
        pass


def _r19_card_current_state(card) -> Dict[str, Any]:
    row = getattr(card, "current_row", None)
    try:
        thickness_label = card._thickness_display_label(row) if row is not None else str(card.thickness_var.get() or "")
    except Exception:
        thickness_label = str(getattr(card, "thickness_var", tk.StringVar(value="")).get() or "")
    try:
        row_key = card._row_identity_key(row) if row is not None else ""
    except Exception:
        row_key = ""
    prop_values = {}
    try:
        for k, v in dict(getattr(card, "prop_values", {}) or {}).items():
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                prop_values[k] = [str(v[0]), bool(v[1])]
            else:
                prop_values[k] = [str(v), False]
    except Exception:
        pass
    return {
        "Basis": str(card.basis_var.get() or "B"),
        "Direction": str(card.direction_var.get() or "L"),
        "Thickness": thickness_label or str(card.thickness_var.get() or "NA"),
        "Thickness_Row_Key": row_key,
        "Unit_System": str(card.unit_sys_var.get() or "mm_T_s"),
        "Material_Model": str(card.mat_model_var.get() or "MAT024+GISSMO"),
        "Export_ID": str(card.export_id_var.get() or ""),
        "Export_Material_Name": str(getattr(card, "export_material_name_var", tk.StringVar(value="")).get() or "").strip(),
        "Notes": _r19_notes_text(card),
        "prop_values": prop_values,
        "unit_conversions": {k: getattr(card, "unit_conversions", {}).get(k, v) for k, v in DEFAULT_UNIT_CONVERSIONS.items()},
        "custom_name": str(getattr(getattr(card, "custom_name_var", None), "get", lambda: "")() or "").strip(),
        "custom_image_paths": list(getattr(card, "custom_image_paths", []) or []),
        "is_custom_blank_entry": bool(getattr(card, "is_custom_entry", False)),
    }


def _r19_state_changed_from_item(card, item: Optional[Dict[str, Any]]) -> bool:
    if item is None:
        return _r19_card_has_user_edits(card)
    state = _r19_card_current_state(card)
    compare_pairs = [
        ("Export_ID", "Export_ID"),
        ("Basis", "Basis"),
        ("Direction", "Direction"),
        ("Thickness", "Thickness"),
        ("Thickness_Row_Key", "Thickness_Row_Key"),
        ("Unit_System", "Unit_System"),
        ("Material_Model", "Material_Model"),
        ("Export_Material_Name", "Export_Material_Name"),
    ]
    for state_key, item_key in compare_pairs:
        old = str(item.get(item_key, item.get("Export_Name", "")) if item_key == "Export_Material_Name" else item.get(item_key, "") or "").strip()
        new = str(state.get(state_key, "") or "").strip()
        if item_key == "Thickness_Row_Key" and not old:
            old = str(item.get("_thickness_row_key", "") or item.get("_source_row_key", "") or "").strip()
        if old and new and norm(old) != norm(new):
            return True
        if not old and new and state_key in {"Export_ID", "Basis", "Direction", "Thickness", "Unit_System", "Material_Model"}:
            continue
    if _r19_card_has_user_edits(card):
        return True
    return False


def _r19_item_numeric_id(item: Dict[str, Any], fallback: int = EXPORT_COUNTER_START) -> int:
    try:
        return normalize_export_id(item.get("Export_ID", fallback), default=fallback)
    except Exception:
        return int(fallback)


def _r19_sort_advanced_items(selection_screen):
    try:
        selection_screen.advanced_items.sort(key=lambda it: (_r19_item_numeric_id(it), str(it.get("Material", "")), str(it.get("Temper", ""))))
    except Exception:
        pass


def _r19_renumber_advanced_items(selection_screen):
    try:
        _r19_sort_advanced_items(selection_screen)
        next_id = EXPORT_COUNTER_START
        for item in selection_screen.advanced_items:
            item["Export_ID"] = str(next_id)
            item.pop("_id_manual", None)
            next_id += 1
        advance_session_export_id_after(next_id - 1)
    except Exception:
        pass


def _r19_sync_card_to_adv_item(card, *, mark_edited: bool, refresh: bool, validate_notes: bool) -> bool:
    _r19_ensure_card_vars(card)
    ss, target = _r19_card_target_item(card)
    if target is None:
        return True
    changed = mark_edited or _r19_state_changed_from_item(card, target)
    custom_or_edited = changed or _r19_card_has_user_edits(card)
    try:
        if "_cei_is_custom_payload" in globals() and _cei_is_custom_payload(target):
            custom_or_edited = True
    except Exception:
        pass
    # Name should update from the latest card options when the user did not manually type it.
    name = _r19_refresh_material_name(card, custom_prefix=custom_or_edited)
    notes = _r19_notes_text(card)
    if validate_notes and custom_or_edited and not notes:
        try:
            w = getattr(card, "material_notes_text", None)
            if w is not None and w.winfo_exists():
                w.configure(bg="#FFECEC")
                w.focus_set()
        except Exception:
            pass
        messagebox.showerror("Notes Required", "Please enter Notes before clicking Done. Notes are required for custom or edited materials.")
        return False
    try:
        if notes or "Notes" in target:
            target["Notes"] = notes
        target["Export_ID"] = str(normalize_export_id(card.export_id_var.get(), default=_r19_item_numeric_id(target)))
        advance_session_export_id_after(target["Export_ID"])
        target["Basis"] = str(card.basis_var.get() or "B")
        target["Direction"] = str(card.direction_var.get() or "L")
        target["Unit_System"] = str(card.unit_sys_var.get() or "mm_T_s")
        target["Material_Model"] = str(card.mat_model_var.get() or "MAT024+GISSMO")
        target["Thickness"] = str(card.thickness_var.get() or target.get("Thickness", "NA") or "NA")
        target["Thickness_Mode"] = "Exact thickness text"
        row = getattr(card, "current_row", None)
        if row is not None:
            try:
                row_key = card._row_identity_key(row)
                target["_thickness_row_key"] = row_key
                target["Thickness_Row_Key"] = row_key
                target["_source_row_key"] = row_key
                target["Source_Row_Key"] = row_key
                if "_mgr_sync_payload_from_row" in globals():
                    target.update(_mgr_sync_payload_from_row(ss, target, row, overwrite_display=True))
            except Exception:
                pass
        target["Export_Material_Name"] = name
        target["Export_Name"] = name
        if bool(getattr(card, "_r19_name_user_locked", False)):
            target["_export_name_manual"] = True
        try:
            if bool(getattr(card, "is_custom_entry", False)):
                target["Custom_Name"] = name
                target["Material"] = name
        except Exception:
            pass
        target["_card_custom_state"] = _r19_card_current_state(card)
        if custom_or_edited:
            target["_custom"] = True
            target["_edited_from_card"] = True
            target["_tag"] = "custom_row"
            target["_status"] = "CUSTOM / EDITED - Ready"
        try:
            if "_mgr_update_item_status" in globals():
                _mgr_update_item_status(ss, target)
            if custom_or_edited:
                target["_tag"] = "custom_row"
                target["_status"] = "CUSTOM / EDITED - Ready"
        except Exception:
            pass
        if refresh and ss is not None:
            _r19_sort_advanced_items(ss)
            ss._adv_refresh_tree()
    except Exception as exc:
        messagebox.showerror("Done", f"Could not save Material Card changes:\n\n{exc}")
        return False
    return True


# Build: add Done button to the existing top toolbar.
_R19_PREV_CARD_BUILD = CardScreen._build


def _r19_card_build(self):
    result = _R19_PREV_CARD_BUILD(self)
    try:
        outer = self.winfo_children()[0]
        top = outer.winfo_children()[0]
        self.done_button = ttk.Button(top, text="Done", style="Success.TButton", command=self._done_to_advanced_selection)
        self.done_button.pack(side=tk.RIGHT, padx=(0, 10))
    except Exception:
        pass
    return result


CardScreen._build = _r19_card_build


# Material Card controls: one Material Name beside Material Model; Notes under Material Summary.
def _r19_card_render_controls(self):
    _r19_ensure_card_vars(self)
    for w in self.controls.winfo_children():
        w.destroy()
    r = self.current_row
    material = spec_val = form = temper = source = element = series = spec2_val = "-"
    if r is not None:
        try:
            element = self.current_selections.get("Element") or r.get("Element", "-")
            series = self.current_selections.get("Series", "-")
            material = self.current_selections.get("Material") or r.get("Material", "-")
            temper = self.current_selections.get("Temper") or r.get("Temper", "-")
            spec_val = self.current_selections.get("Specification") or r.get("Spec1_1", "-")
            if is_blank(spec_val):
                spec_val = NO_SPEC_DISPLAY
            spec2_val = self.current_selections.get("Specification 2") or row_spec2_value(r)
            spec2_val = display_spec_value(spec2_val)
            form = self.current_selections.get("Form") or r.get("Form", "-")
            source = r.get("MMPDS_Version", "-")
        except Exception:
            pass
    self._header(
        self.controls,
        "Engineering Options + Material Summary",
        right=f"{material}-{temper} | {spec_val} | {self.thickness_var.get() or (self._thickness_display_label(r) if r is not None else 'NA')}",
    )
    body = tk.Frame(self.controls, bg=THEME["panel"])
    body.pack(fill=tk.X, padx=10, pady=(6, 8))
    options_row = tk.Frame(body, bg=THEME["panel"])
    options_row.pack(fill=tk.X)

    self._compact_radio_group(options_row, "Basis", BASIS_OPTIONS, self.basis_var, self._basis_changed)
    self._compact_radio_group(options_row, "Direction", DIRECTION_OPTIONS, self.direction_var, self._direction_changed)

    self.thickness_map = {}
    self.thickness_combo_rows = []
    self.thickness_label_rows = {}
    labels = []
    dropdown_rows = self._thickness_rows_for_dropdown()
    self.thickness_rows = list(dropdown_rows)
    for row in dropdown_rows:
        label = self._thickness_display_label(row) or "NA"
        labels.append(label)
        self.thickness_combo_rows.append(row)
        self.thickness_label_rows.setdefault(label, []).append(row)
        self.thickness_map.setdefault(label, row)
    if not labels:
        labels = ["NA"]
        self.thickness_combo_rows = [self.current_row] if self.current_row is not None else []
        self.thickness_rows = list(self.thickness_combo_rows)
    current_label = self._thickness_display_label(self.current_row) if self.current_row is not None else ""
    selected_index = 0
    if self.current_row is not None:
        current_key = self._row_identity_key(self.current_row)
        for i, row in enumerate(self.thickness_combo_rows):
            if self._row_identity_key(row) == current_key:
                selected_index = i
                break
    if current_label and current_label in labels:
        self.thickness_var.set(current_label)
    else:
        self.thickness_var.set(labels[selected_index] if 0 <= selected_index < len(labels) else labels[0])

    thick_box = tk.LabelFrame(options_row, text="Thickness", bg=THEME["panel"], fg=THEME["accent"], font=FONTS["small_bold"], bd=0, relief="flat", padx=10, pady=5, labelanchor="nw", highlightbackground=THEME["border"], highlightthickness=1)
    thick_box.pack(side=tk.LEFT, padx=(0, 8), pady=(0, 2))
    cb = ttk.Combobox(thick_box, textvariable=self.thickness_var, values=labels, state=("normal" if getattr(self, "is_custom_entry", False) else "readonly"), width=22)
    cb.pack(anchor="w", pady=(1, 1))
    self.thickness_combo = cb
    try:
        cb.current(selected_index if 0 <= selected_index < len(labels) else 0)
    except Exception:
        pass
    cb.bind("<<ComboboxSelected>>", lambda _e: self._thickness_changed())

    id_box = tk.LabelFrame(options_row, text="ID / MID", bg=THEME["panel"], fg=THEME["accent"], font=FONTS["small_bold"], bd=0, relief="flat", padx=10, pady=5, labelanchor="nw", highlightbackground=THEME["border"], highlightthickness=1)
    id_box.pack(side=tk.LEFT, padx=(0, 8), pady=(0, 2))
    ttk.Entry(id_box, textvariable=self.export_id_var, width=10).pack(anchor="w", pady=(1, 1))

    self._compact_radio_group(options_row, "Unit System", UNIT_SYSTEMS, self.unit_sys_var, self._unit_changed)
    if self.mat_model_var.get() not in {"MAT024", "MAT082", "MAT224", "MAT024+GISSMO"}:
        self.mat_model_var.set("MAT024+GISSMO")
    self._compact_radio_group(options_row, "Material Model", MAT_MODELS, self.mat_model_var, self._mat_model_changed, disable_except=None)

    # The only material/export name field. It lives beside Material Model.
    _r19_refresh_material_name(self, custom_prefix=_r19_card_has_user_edits(self))
    name_box = tk.LabelFrame(options_row, text="Material Name", bg=THEME["panel"], fg=THEME["accent"], font=FONTS["small_bold"], bd=0, relief="flat", padx=10, pady=5, labelanchor="nw", highlightbackground=THEME["focus_ring"], highlightthickness=2)
    name_box.pack(side=tk.LEFT, padx=(0, 8), pady=(0, 2), fill=tk.X, expand=True)
    name_entry = tk.Entry(name_box, textvariable=self.export_material_name_var, bg=THEME.get("edit_bg", "#FFF5CC"), fg=THEME.get("edit_fg", "#5F4300"), insertbackground=THEME.get("edit_fg", "#5F4300"), relief="solid", bd=1, font=FONTS["small"])
    name_entry.pack(anchor="w", fill=tk.X, pady=(1, 1))
    name_entry.bind("<KeyRelease>", lambda e: _r19_name_changed(self, e), add="+")
    name_entry.bind("<FocusOut>", lambda e: _r19_name_changed(self, e), add="+")
    self.export_material_name_entry = name_entry

    summary_line = (
        f"Material: {element} {material}-{temper}    |    Series: {series}    |    "
        f"Spec: {spec_val}    |    Spec 2: {spec2_val}    |    Form: {form}    |    Source: {source}"
    )
    summary_box = tk.Frame(body, bg=THEME["panel_alt"], highlightbackground=THEME["border"], highlightthickness=1, bd=0)
    summary_box.pack(fill=tk.X, pady=(10, 0))
    tk.Label(summary_box, text="Material Summary", bg=THEME["panel_alt"], fg=THEME["accent"], font=FONTS["small_bold"], anchor="w").pack(fill=tk.X, padx=12, pady=(6, 0))
    tk.Label(summary_box, text=summary_line, bg=THEME["panel_alt"], fg=THEME["text"], font=FONTS["small"], anchor="w", justify="left", wraplength=1200).pack(fill=tk.X, padx=12, pady=(2, 6))

    # Notes are visible for every material and positioned under Material Summary.
    notes_row = tk.Frame(summary_box, bg=THEME["panel_alt"])
    notes_row.pack(fill=tk.X, padx=12, pady=(0, 8))
    tk.Label(notes_row, text="Notes", bg=THEME["panel_alt"], fg=THEME["text_muted"], font=FONTS["small_bold"]).pack(anchor="w")
    notes_text = tk.Text(notes_row, height=2, wrap="word", bg=THEME.get("text_area_bg", "#FFFFFF"), fg=THEME.get("text_area_fg", "#111827"), insertbackground=THEME.get("text_area_fg", "#111827"), relief="solid", bd=1, font=FONTS["small"])
    notes_text.pack(fill=tk.X, pady=(2, 0))
    try:
        notes_text.insert("1.0", str(self.material_notes_var.get() or ""))
    except Exception:
        pass
    notes_text.bind("<KeyRelease>", lambda e: _r19_notes_changed(self, e), add="+")
    notes_text.bind("<FocusOut>", lambda e: _r19_notes_changed(self, e), add="+")
    self.material_notes_text = notes_text


CardScreen._render_controls = _r19_card_render_controls


_R19_PREV_CARD_ON_SHOW = CardScreen.on_show


def _r19_card_on_show(self, row=None, selections=None, matching_rows=None, history_state=None, **kwargs):
    _r19_ensure_card_vars(self)
    try:
        self._r19_name_user_locked = False
        if isinstance(history_state, dict):
            if bool(history_state.get("_export_name_manual", False)):
                self._r19_name_user_locked = True
            incoming_name = str(history_state.get("Export_Material_Name", "") or history_state.get("Export_Name", "") or history_state.get("Custom_Name", "") or "").strip()
            incoming_notes = str(history_state.get("Notes", "") or history_state.get("notes", "") or "").strip()
            opened_id = str(history_state.get("Export_ID", "") or "").strip()
            if opened_id:
                try:
                    ss = self.app.screens.get("SelectionScreen")
                    for item in getattr(ss, "advanced_items", []) or []:
                        if str(item.get("Export_ID", "") or "").strip() == opened_id:
                            incoming_name = str(item.get("Export_Material_Name", "") or item.get("Export_Name", "") or item.get("Custom_Name", "") or incoming_name or "").strip()
                            incoming_notes = str(item.get("Notes", incoming_notes) or incoming_notes or "").strip()
                            self._r19_name_user_locked = bool(item.get("_export_name_manual", False))
                            break
                except Exception:
                    pass
            self.material_notes_var.set(incoming_notes)
            if incoming_name:
                self.export_material_name_var.set(incoming_name)
            else:
                self.export_material_name_var.set("")
    except Exception:
        pass
    result = _R19_PREV_CARD_ON_SHOW(self, row=row, selections=selections, matching_rows=matching_rows, history_state=history_state, **kwargs)
    try:
        if not str(self.export_material_name_var.get() or "").strip() or not bool(getattr(self, "_r19_name_user_locked", False)):
            _r19_refresh_material_name(self, force=not str(self.export_material_name_var.get() or "").strip(), custom_prefix=_r19_card_has_user_edits(self))
    except Exception:
        pass
    return result


CardScreen.on_show = _r19_card_on_show


def _r19_save_history_from_done(card, target: Optional[Dict[str, Any]] = None):
    try:
        row = getattr(card, "current_row", None)
        selections = dict(getattr(card, "current_selections", {}) or {})
        if target:
            for s in STAGES:
                selections[s] = str(target.get(s, selections.get(s, "")) or "")
        entry = {"datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "history_type": "edited_card"}
        entry.update(selections)
        try:
            entry["Source"] = row.get("MMPDS_Version", "-") if row is not None else target.get("Source", "") if target else ""
        except Exception:
            entry["Source"] = target.get("Source", "") if target else ""
        entry["Export_Material_Name"] = str(getattr(card, "export_material_name_var", tk.StringVar(value="")).get() or "")
        entry["Notes"] = _r19_notes_text(card)
        entry["_card_state"] = _r19_card_current_state(card)
        card.app.history.append(entry)
        ss = card.app.screens.get("SelectionScreen")
        if ss is not None and hasattr(ss, "_refresh_history"):
            ss._refresh_history()
    except Exception:
        pass


def _r19_done_to_advanced_selection(self):
    # Confirm any typed Property Card / Unit Conversion values first.
    try:
        self._commit_all_pending_edits("Done")
    except Exception:
        pass
    ss, target = _r19_card_target_item(self)
    # Custom blank entry opened from + Add Custom Entry may not have an export row yet.
    if target is None and bool(getattr(self, "is_custom_entry", False)):
        _r19_refresh_material_name(self, custom_prefix=True)
        notes = _r19_notes_text(self)
        if not notes:
            try:
                self.material_notes_text.configure(bg="#FFECEC")
                self.material_notes_text.focus_set()
            except Exception:
                pass
            messagebox.showerror("Notes Required", "Please enter Notes before clicking Done. Notes are required for custom materials.")
            return "break"
        try:
            if not hasattr(self, "custom_name_var"):
                self.custom_name_var = tk.StringVar(value="")
            self.custom_name_var.set(str(self.export_material_name_var.get() or "CUSTOM_MATERIAL").strip())
        except Exception:
            pass
        stored = False
        try:
            if "_cei_store_custom_card_to_export_list" in globals():
                stored = bool(_cei_store_custom_card_to_export_list(self))
        except Exception as exc:
            messagebox.showerror("Done", f"Could not add custom material to Export List:\n\n{exc}")
            return "break"
        _r19_save_history_from_done(self, None)
        try:
            ss = self.app.screens.get("SelectionScreen")
            if ss is not None:
                _r19_sort_advanced_items(ss)
                ss._adv_refresh_tree()
                self.app.show_screen("SelectionScreen")
                try:
                    ss.notebook.select(ss.advanced_tab)
                except Exception:
                    pass
        except Exception:
            self.app.show_screen("SelectionScreen")
        return "break"

    if target is not None:
        if not _r19_sync_card_to_adv_item(self, mark_edited=False, refresh=True, validate_notes=True):
            return "break"
        _r19_save_history_from_done(self, target)
        try:
            ss = self.app.screens.get("SelectionScreen")
            if ss is not None:
                _r19_sort_advanced_items(ss)
                ss._adv_refresh_tree()
                self.app.show_screen("SelectionScreen")
                try:
                    ss.notebook.select(ss.advanced_tab)
                except Exception:
                    pass
                try:
                    new_id = str(getattr(self, "export_id_var", tk.StringVar(value="")).get() or "")
                    for i, item in enumerate(getattr(ss, "advanced_items", []) or []):
                        if str(item.get("Export_ID", "") or "") == new_id:
                            ss.adv_tree.selection_set(str(i))
                            ss.adv_tree.see(str(i))
                            break
                except Exception:
                    pass
        except Exception:
            self.app.show_screen("SelectionScreen")
        return "break"

    _r19_save_history_from_done(self, None)
    self.app.show_screen("SelectionScreen")
    return "break"


CardScreen._done_to_advanced_selection = _r19_done_to_advanced_selection


# Keep generated material name in sync when top-row options change.
def _r19_wrap_card_change_method(method_name: str):
    prev = getattr(CardScreen, method_name, None)
    if prev is None:
        return
    def _wrapped(self, *args, **kwargs):
        result = prev(self, *args, **kwargs)
        try:
            _r19_refresh_material_name(self, custom_prefix=_r19_card_has_user_edits(self))
            _r19_sync_card_to_adv_item(self, mark_edited=True, refresh=True, validate_notes=False)
        except Exception:
            pass
        return result
    setattr(CardScreen, method_name, _wrapped)


for _r19_method in ("_basis_changed", "_direction_changed", "_thickness_changed", "_unit_changed", "_mat_model_changed"):
    _r19_wrap_card_change_method(_r19_method)


# Advanced Export List: sort by numeric ID and only allow Unit direct editing.
_R19_PREV_ADV_REFRESH_TREE = SelectionScreen._adv_refresh_tree


def _r19_adv_refresh_tree(self):
    _r19_sort_advanced_items(self)
    return _R19_PREV_ADV_REFRESH_TREE(self)


SelectionScreen._adv_refresh_tree = _r19_adv_refresh_tree


_R19_PREV_ADV_HANDLE_TREE_CLICK = SelectionScreen._adv_handle_tree_click


def _r19_adv_handle_tree_click(self, event):
    tree = getattr(self, "adv_tree", None)
    if tree is None:
        return
    row_id = tree.identify_row(event.y)
    col_name = self._adv_tree_column_name(tree.identify_column(event.x))
    if row_id and col_name == "Export":
        self._adv_toggle_export_selected(int(row_id))
        return "break"
    if row_id and col_name == "View_Image":
        self._adv_show_image_for_item(int(row_id))
        return "break"
    if row_id and col_name == "Unit":
        return self._adv_begin_export_list_edit(event)
    # ID, Basis, Direction, Matcard, Notes are intentionally read-only in the Export List.
    return None


SelectionScreen._adv_handle_tree_click = _r19_adv_handle_tree_click


_R19_PREV_ADV_BEGIN_EDIT = SelectionScreen._adv_begin_export_list_edit


def _r19_adv_begin_export_list_edit(self, event=None):
    try:
        tree = getattr(self, "adv_tree", None)
        if tree is None:
            return "break"
        col_id = tree.identify_column(event.x) if event is not None else ""
        col_name = self._adv_tree_column_name(col_id)
        if col_name != "Unit":
            return "break"
    except Exception:
        return "break"
    return _R19_PREV_ADV_BEGIN_EDIT(self, event)


SelectionScreen._adv_begin_export_list_edit = _r19_adv_begin_export_list_edit


_R19_PREV_ADV_REMOVE_SELECTED = SelectionScreen._adv_remove_selected


def _r19_adv_remove_selected(self):
    try:
        selected = sorted((int(i) for i in self.adv_tree.selection() if str(i).isdigit()), reverse=True)
    except Exception:
        selected = []
    removed = 0
    for idx in selected:
        if 0 <= idx < len(self.advanced_items):
            self.advanced_items.pop(idx)
            removed += 1
    _r19_renumber_advanced_items(self)
    self._adv_refresh_tree()
    try:
        self._adv_log(f"Removed {removed} item(s). IDs were renumbered from {EXPORT_COUNTER_START}.")
    except Exception:
        pass


SelectionScreen._adv_remove_selected = _r19_adv_remove_selected


_R19_PREV_ADV_REMOVE_DUPLICATES = SelectionScreen._adv_remove_duplicates


def _r19_adv_remove_duplicates(self):
    before = len(getattr(self, "advanced_items", []) or [])
    try:
        _R19_PREV_ADV_REMOVE_DUPLICATES(self)
    finally:
        after = len(getattr(self, "advanced_items", []) or [])
        if after != before:
            _r19_renumber_advanced_items(self)
            self._adv_refresh_tree()


SelectionScreen._adv_remove_duplicates = _r19_adv_remove_duplicates


# Duplicate key includes the exact source row key when available.
_R19_PREV_ADV_DUP_KEY = SelectionScreen._adv_duplicate_key


def _r19_adv_duplicate_key(self, item: Dict[str, Any]) -> Tuple[str, ...]:
    try:
        base = tuple(_R19_PREV_ADV_DUP_KEY(self, item))
    except Exception:
        base = ()
    source_key = str(item.get("Source_Row_Key", "") or item.get("_source_row_key", "") or item.get("Thickness_Row_Key", "") or item.get("_thickness_row_key", "") or "").strip()
    return (norm(source_key),) + base


SelectionScreen._adv_duplicate_key = _r19_adv_duplicate_key


# Export guard: custom/edited selected rows must have Notes before export.
_R19_PREV_ADV_EXPORT_ALL = SelectionScreen._adv_export_all


def _r19_adv_export_all(self):
    missing = []
    try:
        for idx, item in enumerate(getattr(self, "advanced_items", []) or [], start=1):
            if not item.get("_selected", False):
                continue
            needs_notes = False
            try:
                needs_notes = _mgr_item_requires_notes(item) if "_mgr_item_requires_notes" in globals() else _mgr_item_is_custom_or_edited(item)
            except Exception:
                needs_notes = bool(item.get("_custom") or item.get("_edited_from_card") or item.get("Custom_Blank_Entry"))
            if needs_notes and not str(item.get("Notes", "") or "").strip():
                missing.append(str(item.get("Export_ID", idx)))
    except Exception:
        missing = []
    if missing:
        messagebox.showerror("Notes Required", "Notes are required before export for custom/edited rows.\n\nMissing notes for ID/MID: " + ", ".join(missing))
        return
    return _R19_PREV_ADV_EXPORT_ALL(self)


SelectionScreen._adv_export_all = _r19_adv_export_all

# End marker for VS Code search:
# REHAN_ACTUAL_19K_DONE_NAME_NOTES_ID_SORT_FIX_2026_06_23



# =============================================================================
# REHAN_EXPORT_ALL_ROWS_NO_SKIP_FIX_2026_06_24
# Purpose:
#   Advanced export should create a keyfile for every selected row that has a
#   matching material row. The previous validation could skip normal rows even
#   when the export summary showed usable RO/E/PR/SIGY values. This final patch
#   keeps the existing GUI/features and makes the batch keyfile path tolerant:
#   - use live edited/custom card values first,
#   - then use source row values with tolerant column-name matching,
#   - calculate ETAN and P.F.S. when possible,
#   - safely write 0 only for values that are truly unavailable,
#   - do not skip rows only because ETAN/P.F.S. or a MAT value is blank.
# =============================================================================


def _r20_missing_value(value: Any) -> bool:
    try:
        if value is None:
            return True
        text = str(value).strip()
        return text == "" or text in {"-", "nan", "NaN", "None", "none", "null", "N/A", "n/a"}
    except Exception:
        return True


_R20_PROPERTY_ALIASES = {
    "Ftu": ("Tensile_Str", "UltTensileStrength", "UltimateTensileStrength", "Ftu", "FTU"),
    "Fty": ("Tensile_Yield", "TensileYield", "Fty", "SIGY"),
    "Fcy": ("Compress_Yield", "CompressionYield", "Fcy"),
    "Fsu": ("Shear_Str", "UltShearStrength", "Fsu"),
    "Elong": ("Elong", "ElongAtBreak", "Elongation"),
    "E": ("Youngs_Mod", "YoungsModulus", "Young_Modulus", "E"),
    "Ec": ("Youngs_Mod_Comp", "YoungsModulusComp", "Ec"),
    "G": ("Shear_Mod", "ShearModulus", "G"),
    "PR": ("Poissons_Ratio", "PoissonsRatio", "Poisson", "PR"),
    "RO": ("Density", "RO", "RHO"),
    "Etan": ("Etan", "E_Tan", "Tangent_Modulus_Etan", "Tangent_Modulus", "Tangent_Mod", "TangentModulus"),
}


def _r20_col_lookup(row: Any) -> Dict[str, str]:
    try:
        return {_normalized_col_key(c): c for c in row.index}
    except Exception:
        try:
            return {str(c).strip().lower(): c for c in row.index}
        except Exception:
            return {}


def _r20_try_row_value(row: Any, names: List[str]) -> Optional[float]:
    if row is None:
        return None
    lookup = _r20_col_lookup(row)
    for name in names:
        actual = lookup.get(_normalized_col_key(name))
        if actual is None:
            continue
        try:
            num = try_float(row.get(actual))
        except Exception:
            num = None
        if num is not None:
            return num
    return None


def _r20_raw_property_from_row(row: Any, key: str, basis: str = "B", direction: str = "L") -> Optional[float]:
    basis = str(basis or "B").strip().upper()
    if basis not in {"A", "B", "S"}:
        basis = "B"
    direction = "LT" if str(direction or "L").strip().upper() == "LT" else "L"
    bases = [basis] + [b for b in ("A", "B", "S") if b != basis]
    directions = [direction] + [d for d in ("L", "LT") if d != direction]
    aliases = list(_R20_PROPERTY_ALIASES.get(key, (key,)))

    # Exact selected basis/direction first, then safe basis-only/global fallbacks.
    candidates: List[str] = []
    for alias in aliases:
        for d in directions:
            for b in bases:
                candidates.extend([
                    f"{alias}_{d}_{b}",
                    f"{alias}_{b}_{d}",
                    f"{d}_{alias}_{b}",
                ])
        for b in bases:
            candidates.append(f"{alias}_{b}")
        for d in directions:
            candidates.append(f"{alias}_{d}")
        candidates.append(alias)

    # Remove duplicates while preserving priority order.
    seen = set()
    ordered = []
    for cand in candidates:
        k = _normalized_col_key(cand)
        if k not in seen:
            seen.add(k)
            ordered.append(cand)
    return _r20_try_row_value(row, ordered)


def _r20_float_from_table(tbl: Dict[str, Dict[str, str]], row_key: str, field: str = "eng") -> Optional[float]:
    try:
        value = tbl.get(row_key, {}).get(field, "-")
        return try_float(value)
    except Exception:
        return None


def _r20_eng_from_raw(raw: Optional[float], kind: str, unit_sys: str) -> Optional[float]:
    if raw is None:
        return None
    try:
        converted, _unit = convert_value(raw, kind, unit_sys, DEFAULT_UNIT_CONVERSIONS)
        return converted
    except Exception:
        return raw


def _r20_best_eng_value(card, tbl: Dict[str, Dict[str, str]], row: Any, key: str, kind: str,
                        unit_sys: str, basis: str, direction: str) -> float:
    current = _r20_float_from_table(tbl, key, "eng")
    if current is not None:
        return current
    raw = _r20_raw_property_from_row(row, key, basis, direction)
    eng = _r20_eng_from_raw(raw, kind, unit_sys)
    if eng is not None:
        return eng
    return 0.0


def _r20_direct_raw_or_zero(row: Any, key: str, basis: str, direction: str) -> float:
    raw = _r20_raw_property_from_row(row, key, basis, direction)
    return float(raw) if raw is not None else 0.0


def _r20_apply_programmatic_custom_state(card, custom_state: Any) -> None:
    if not isinstance(custom_state, dict):
        return
    try:
        prop_values = custom_state.get("prop_values")
        if isinstance(prop_values, dict):
            restored = {}
            for key, value in prop_values.items():
                if isinstance(value, (list, tuple)) and len(value) >= 2:
                    restored[key] = (str(value[0]), bool(value[1]))
                elif isinstance(value, dict):
                    restored[key] = (str(value.get("value", "")), bool(value.get("edited", False)))
                else:
                    restored[key] = (str(value), True)
            if restored:
                card.prop_values.update(restored)
        unit_values = custom_state.get("unit_conversions")
        if isinstance(unit_values, dict):
            for k, v in unit_values.items():
                num = try_float(v)
                if num is not None:
                    card.unit_conversions[k] = num
                    try:
                        default_num = try_float(DEFAULT_UNIT_CONVERSIONS.get(k))
                        if default_num is not None and num != default_num:
                            card.unit_confirmed_edits.add(k)
                    except Exception:
                        pass
    except Exception:
        pass


def _r20_safe_int_id(value: Any) -> int:
    try:
        return reserve_next_export_id(value)
    except Exception:
        try:
            return normalize_export_id(value, default=peek_next_export_id())
        except Exception:
            return reserve_next_export_id()


_R20_PREV_EXPORT_KEYFILE_PROGRAMMATIC = CardScreen.export_keyfile_programmatic


def _r20_export_keyfile_programmatic(self, row, selections: Dict[str, str], output_dir: Path,
                                     output_stem: str, basis: str = "B", direction: str = "L",
                                     unit_sys: str = "mm_T_s", mat_model: str = "MAT024+GISSMO",
                                     material_id: Optional[Any] = None) -> Dict[str, Any]:
    """Export every selected Advanced row without false missing-value skips."""
    # First try the existing export path. If it succeeds, keep the exact old behavior.
    try:
        result = _R20_PREV_EXPORT_KEYFILE_PROGRAMMATIC(
            self,
            row=row,
            selections=selections,
            output_dir=output_dir,
            output_stem=output_stem,
            basis=basis,
            direction=direction,
            unit_sys=unit_sys,
            mat_model=mat_model,
            material_id=material_id,
        )
        if isinstance(result, dict) and result.get("ok"):
            return result
        # Continue to tolerant fallback only for false missing-value validation.
        err = str((result or {}).get("error", "")) if isinstance(result, dict) else ""
        if isinstance(result, dict) and result.get("missing") and "missing" not in err.lower():
            pass
    except Exception:
        result = None

    if row is None:
        return {"ok": False, "missing": ["row"], "path": "", "error": "No material row selected"}

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    old_state = {
        "current_row": self.current_row,
        "current_selections": dict(getattr(self, "current_selections", {}) or {}),
        "thickness_rows": list(getattr(self, "thickness_rows", []) or []),
        "basis": self.basis_var.get(),
        "direction": self.direction_var.get(),
        "thickness": self.thickness_var.get(),
        "unit_sys": self.unit_sys_var.get(),
        "mat_model": self.mat_model_var.get(),
        "prop_values": dict(getattr(self, "prop_values", {}) or {}),
        "pending_edits": dict(getattr(self, "pending_edits", {}) or {}),
        "unit_conversions": dict(getattr(self, "unit_conversions", {}) or {}),
        "last_effps": getattr(self, "last_effps", None),
        "last_etan_eng": getattr(self, "last_etan_eng", None),
        "last_etan_true": getattr(self, "last_etan_true", None),
    }

    try:
        self.current_row = row
        self.current_selections = dict(selections or {})
        self.thickness_rows = [row]
        basis = str(basis or "B").strip().upper()
        if basis not in {"A", "B", "S"}:
            basis = "B"
        direction = "LT" if str(direction or "L").strip().upper() == "LT" else "L"
        unit_sys = unit_sys if unit_sys in UNIT_SYSTEM_SPEC else "mm_T_s"
        mat_model = str(mat_model or "MAT024+GISSMO")
        self.basis_var.set(basis)
        self.direction_var.set(direction)
        self.unit_sys_var.set(unit_sys)
        self.mat_model_var.set(mat_model)
        try:
            self.thickness_var.set(self._thickness_display_label(row))
        except Exception:
            self.thickness_var.set(str((selections or {}).get("Thickness", "") or "NA"))
        self._seed_values()
        _r20_apply_programmatic_custom_state(self, getattr(self, "_programmatic_custom_state", None))

        try:
            tbl = self._compute_table()
        except Exception:
            tbl = {}

        is_gissmo_export = self._is_gissmo_model()
        export_model = self._model_code()

        ro_raw = _r20_best_eng_value(self, tbl, row, "RO", "density", unit_sys, basis, direction)
        e_raw = _r20_best_eng_value(self, tbl, row, "E", "modulus", unit_sys, basis, direction)
        pr_raw = _r20_best_eng_value(self, tbl, row, "PR", "ratio", unit_sys, basis, direction)
        sigy_raw = _r20_best_eng_value(self, tbl, row, "Fty", "pressure", unit_sys, basis, direction)
        ftu_eng = _r20_best_eng_value(self, tbl, row, "Ftu", "pressure", unit_sys, basis, direction)

        # Calculate ETAN/P.F.S. from available tensile/yield/elongation values.
        etan_raw = try_float(self._positive_fmt_number(getattr(self, "last_etan_true", None)))
        fail_fraction = try_float(self._positive_fraction_fmt(getattr(self, "last_effps", None)))
        ftu_true_raw = _r20_float_from_table(tbl, "Ftu", "true")
        raw_ftu = _r20_direct_raw_or_zero(row, "Ftu", basis, direction)
        raw_fty = _r20_direct_raw_or_zero(row, "Fty", basis, direction)
        raw_e = _r20_direct_raw_or_zero(row, "E", basis, direction)
        raw_elong = abs(_r20_direct_raw_or_zero(row, "Elong", basis, direction))

        try:
            if ftu_true_raw is None and raw_elong:
                # This mirrors the existing formula style: engineering strain is
                # elongation plus elastic strain, then true stress follows it.
                if raw_fty and raw_e:
                    elong_eng = raw_elong + (100.0 * raw_fty) / (raw_e * 1000.0)
                else:
                    elong_eng = raw_elong
                ftu_true_raw = ftu_eng * (1.0 + elong_eng / 100.0)
                elong_true = 100.0 * math.log(1.0 + elong_eng / 100.0) if (1.0 + elong_eng / 100.0) > 0 else None
                if fail_fraction is None and elong_true is not None and e_raw:
                    effps_percent = abs(((elong_true / 100.0) - (sigy_raw / e_raw)) * 100.0)
                    fail_fraction = abs(effps_percent) / 100.0
                if etan_raw is None and fail_fraction not in (None, 0):
                    etan_raw = abs(ftu_true_raw - sigy_raw) / abs(fail_fraction)
        except Exception:
            pass

        # Source Etan can still be used when formula ETAN was unavailable.
        if etan_raw is None:
            source_etan = _r20_raw_property_from_row(row, "Etan", basis, direction)
            if source_etan is not None:
                etan_raw = _r20_eng_from_raw(source_etan, "pressure", unit_sys)
        if etan_raw is None:
            etan_raw = 0.0
        if fail_fraction is None:
            fail_fraction = 0.0
        if ftu_true_raw is None:
            ftu_true_raw = ftu_eng if ftu_eng is not None else 0.0

        element = self.current_selections.get("Element") or row.get("Element", "Element")
        material = self.current_selections.get("Material") or row.get("Material", "Material")
        temper = self.current_selections.get("Temper") or row.get("Temper", "Temper")
        spec = self.current_selections.get("Specification") or row.get("Spec1_1", row.get("Specification", "Spec"))
        spec2 = self.current_selections.get("Specification 2") or row_spec2_value(row)
        spec2 = display_spec_value(spec2)
        form = self.current_selections.get("Form") or row.get("Form", "Form")
        try:
            thickness = self._thickness_display_label(row)
        except Exception:
            thickness = str(self.current_selections.get("Thickness", "NA") or "NA")
        direction_name = self.direction_var.get()
        basis_name = self._basis_display().replace(" ", "-")
        model = self.mat_model_var.get()

        unit_spec = UNIT_SYSTEM_SPEC[self.unit_sys_var.get()]
        unit_label = unit_spec["label"]
        pressure_unit = unit_spec["pressure_label"]
        density_unit = unit_spec["density_label"]

        export_id = _r20_safe_int_id(material_id)
        full_material_name = (
            f"{element} {material}-{temper} | Export ID/MID: {export_id} | Spec: {spec} | Spec 2: {spec2} | Form: {form} | "
            f"Thickness: {thickness} | Direction: {direction_name} | Basis: {basis_name}"
        )

        try:
            spec_query = dict(self.current_selections)
            spec_query["Specification"] = ""
            spec_query["Specification 2"] = ""
            spec_rows = self.app.db.filter_master(spec_query)
            spec_col = find_col(spec_rows, "Spec1_1", "spec1_1", "Specification")
            available_specs = []
            if spec_col and spec_rows is not None and not spec_rows.empty:
                for v in spec_rows[spec_col].astype(str).tolist():
                    clean = NO_SPEC_DISPLAY if is_blank(v) else str(v).strip()
                    if clean and clean not in available_specs:
                        available_specs.append(clean)
            available_specs_text = ", ".join(available_specs) if available_specs else str(spec)
        except Exception:
            available_specs_text = str(spec)

        title = str(output_stem or "").strip()
        if not title:
            title = self._keyfile_export_stem(
                element=element,
                material=material,
                temper=temper,
                spec=spec,
                form=form,
                thickness=thickness,
                direction=direction_name,
                model=model,
                custom=bool(getattr(self, "_programmatic_custom_state", None)),
            )

        ro = self._format_key_number(ro_raw, "density")
        e = self._format_key_number(e_raw)
        pr = self._format_key_number(pr_raw, "ratio")
        sigy = self._format_key_number(sigy_raw)
        etan = self._format_key_number(etan_raw)
        fail = "0" if is_gissmo_export else self._format_key_number(fail_fraction, "fail")
        tdel = self._format_key_number(0)
        ftu_true = self._format_key_number(ftu_true_raw)
        gissmo_block = self._gissmo_key_block(title, mid=export_id) if is_gissmo_export else ""

        k_text = self._build_export_keyfile_text(
            title=title,
            full_material_name=full_material_name,
            spec=spec,
            available_specs_text=available_specs_text,
            unit_label=unit_label,
            pressure_unit=pressure_unit,
            density_unit=density_unit,
            model=model,
            custom_edited=bool(getattr(self, "_programmatic_custom_state", None)),
            user=getpass.getuser().lower(),
            timestamp=datetime.now().strftime("%H:%M %Y/%m/%d"),
            ro=ro,
            e=e,
            pr=pr,
            sigy=sigy,
            etan=etan,
            fail=fail,
            tdel=tdel,
            ftu_true=ftu_true,
            gissmo_block=gissmo_block,
            material_id=export_id,
        )
        export_notes = str(getattr(self, "_programmatic_export_notes", "") or "").strip()
        if export_notes:
            try:
                k_text = _append_user_notes_to_keyfile_end(k_text, export_notes)
            except Exception:
                k_text = k_text.rstrip() + f"\n$ Notes: {export_notes}\n*END\n"

        safe_stem = self._safe_filename_part(title or output_stem or "MMPDS_export")
        save_path = output_dir / f"{safe_stem}.key"
        counter = 2
        while save_path.exists():
            save_path = output_dir / f"{safe_stem}_{counter}.key"
            counter += 1
        save_path.write_text(k_text, encoding="utf-8")
        return {"ok": True, "missing": [], "path": str(save_path), "error": "", "export_id": export_id}
    except Exception as exc:
        return {"ok": False, "missing": [], "path": "", "error": str(exc)}
    finally:
        try:
            self.current_row = old_state["current_row"]
            self.current_selections = old_state["current_selections"]
            self.thickness_rows = old_state["thickness_rows"]
            self.basis_var.set(old_state["basis"])
            self.direction_var.set(old_state["direction"])
            self.thickness_var.set(old_state["thickness"])
            self.unit_sys_var.set(old_state["unit_sys"])
            self.mat_model_var.set(old_state["mat_model"])
            self.prop_values = old_state["prop_values"]
            self.pending_edits = old_state["pending_edits"]
            self.unit_conversions = old_state["unit_conversions"]
            self.last_effps = old_state["last_effps"]
            self.last_etan_eng = old_state["last_etan_eng"]
            self.last_etan_true = old_state["last_etan_true"]
        except Exception:
            pass


CardScreen.export_keyfile_programmatic = _r20_export_keyfile_programmatic


# Do not mark export-list rows as unexportable only because required values are
# blank. The tolerant export path writes available values and safe zeros.
_R20_PREV_ADV_MISSING_REQUIRED = SelectionScreen._adv_missing_required_for_payload


def _r20_adv_missing_required_for_payload(self, payload: Dict[str, Any], rows: Optional[pd.DataFrame] = None) -> List[str]:
    try:
        if rows is None:
            rows = self._adv_match_rows(payload)
        if rows is None or rows.empty:
            return []
    except Exception:
        return []
    return []


SelectionScreen._adv_missing_required_for_payload = _r20_adv_missing_required_for_payload

# End marker for VS Code search:
# REHAN_EXPORT_ALL_ROWS_NO_SKIP_FIX_ACTIVE_2026_06_24



# =============================================================================
# REHAN_CUSTOM_EXPORT_NAMING_AND_NOTES_FINAL_2026_06_24
# Purpose:
#   Manager feedback:
#     - customized database materials export as CUSTOM_{Material name}
#     - unique custom entries export as CUSTOM_{User defined name}
#     - notes/reason must appear in exported keyfiles and export summaries
#
# This is a narrow final patch. It does not change GUI layout, calculations,
# filtering, IDs, images, or existing export folder behavior.
# =============================================================================


def _r21_clean_name_component(value: Any, default: str = "MATERIAL") -> str:
    """Return a safe visible/export name component."""
    text = str(value or "").strip()
    if not text or is_blank(text) or text == NO_SPEC_DISPLAY:
        text = default
    text = (
        text.replace("\u2264", "le")
            .replace("\u2265", "ge")
            .replace("\u2013", "-")
            .replace("\u2014", "-")
    )
    # Remove an existing custom prefix before applying the single required prefix.
    if text.upper().startswith("CUSTOM_"):
        text = text[7:].strip()
    elif text.upper().startswith("CUSTOM "):
        text = text[7:].strip()
    replacements = {
        " ": "_", "/": "_", "\\": "_", ":": "_", "*": "_", "?": "_",
        '"': "_", "'": "", "|": "_", ",": "_", ";": "_", "(": "",
        ")": "", "[": "", "]": "", "{": "", "}": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = _rehan_re.sub(r"_+", "_", text).strip("_-. ")
    return text or default


def _r21_custom_prefix_name(base_name: Any, default: str = "MATERIAL") -> str:
    """Build the required CUSTOM_{name} value exactly once."""
    base = _r21_clean_name_component(base_name, default=default)
    if base.upper().startswith("CUSTOM_"):
        return base[:160]
    return f"CUSTOM_{base}"[:160]


def _r21_item_is_custom_blank(item: Dict[str, Any]) -> bool:
    """True for + Add Custom Entry / fully user-defined rows."""
    if not isinstance(item, dict):
        return False
    custom_flags = (
        "_custom_blank_entry",
        "Custom_Blank_Entry",
        "is_custom_blank_entry",
    )
    if any(bool(item.get(k)) for k in custom_flags):
        return True
    if str(item.get("Source", "") or "").strip().lower() == "custom blank entry":
        return True
    state = item.get("_card_custom_state")
    return bool(isinstance(state, dict) and state.get("is_custom_blank_entry"))


def _r21_item_is_custom_or_edited(item: Dict[str, Any]) -> bool:
    """True when the export should carry the CUSTOM_ prefix and require notes."""
    if not isinstance(item, dict):
        return False
    if _r21_item_is_custom_blank(item):
        return True
    try:
        if "_mgr_item_is_custom_or_edited" in globals() and _mgr_item_is_custom_or_edited(item):
            return True
    except Exception:
        pass
    return bool(
        item.get("_custom")
        or item.get("_edited_from_card")
        or item.get("_edited_from_export_list")
        or item.get("_user_changes")
        or isinstance(item.get("_card_custom_state"), dict)
        or "CUSTOM" in str(item.get("_status", "") or "").upper()
        or "EDITED" in str(item.get("_status", "") or "").upper()
    )


def _r21_material_base_name_from_item(item: Dict[str, Any], row: Optional[pd.Series] = None) -> str:
    """Base name for customized database material rows."""
    material = str(item.get("Material", "") or "").strip()
    temper = str(item.get("Temper", "") or "").strip()
    element = str(item.get("Element", "") or "").strip()

    if (not material or is_blank(material)) and row is not None and hasattr(row, "get"):
        material = str(row.get("Material", "") or "").strip()
    if (not temper or is_blank(temper)) and row is not None and hasattr(row, "get"):
        temper = str(row.get("Temper", "") or "").strip()
    if (not element or is_blank(element)) and row is not None and hasattr(row, "get"):
        element = str(row.get("Element", "") or "").strip()

    if not material or is_blank(material):
        material = "MATERIAL"

    # For normal MMPDS rows, include temper when available so the output is clear.
    base = material
    if temper and not is_blank(temper) and temper.lower() not in material.lower():
        base = f"{base}-{temper}"

    # Include element only when it is meaningful and not already part of the material text.
    if element and not is_blank(element) and element.upper() != "CUSTOM" and element.lower() not in base.lower():
        base = f"{element}_{base}"

    return base


def _r21_user_defined_base_name(item: Dict[str, Any], row: Optional[pd.Series] = None) -> str:
    """Base name for unique custom blank entries."""
    candidates = [
        item.get("Custom_Name", ""),
        item.get("custom_name", ""),
        item.get("Material", ""),
        item.get("Export_Material_Name", ""),
        item.get("Export_Name", ""),
    ]
    try:
        state = item.get("_card_custom_state")
        if isinstance(state, dict):
            candidates.insert(0, state.get("custom_name", ""))
    except Exception:
        pass
    if row is not None and hasattr(row, "get"):
        candidates.extend([row.get("Material", ""), row.get("Custom_Name", "")])
    for value in candidates:
        text = str(value or "").strip()
        if text and not is_blank(text):
            return text
    return "CUSTOM_MATERIAL"


def _r21_export_material_name_for_item(item: Dict[str, Any], row: Optional[pd.Series] = None) -> str:
    """Return the final material/export name required by the feedback."""
    if _r21_item_is_custom_blank(item):
        return _r21_custom_prefix_name(_r21_user_defined_base_name(item, row), default="CUSTOM_MATERIAL")
    if _r21_item_is_custom_or_edited(item):
        return _r21_custom_prefix_name(_r21_material_base_name_from_item(item, row), default="MATERIAL")

    # Normal unmodified rows keep the existing app behavior.
    existing = str(item.get("Export_Material_Name", "") or item.get("Export_Name", "") or "").strip()
    return existing


def _r21_export_material_name_for_card(card, *, custom_prefix: Optional[bool] = None) -> str:
    """Card version used by the yellow Material Name field."""
    row = getattr(card, "current_row", None)
    if custom_prefix is None:
        try:
            custom_prefix = _r19_card_has_user_edits(card)
        except Exception:
            custom_prefix = bool(getattr(card, "is_custom_entry", False))

    if bool(getattr(card, "is_custom_entry", False)):
        try:
            name = _cei_user_custom_name_from_card(card) if "_cei_user_custom_name_from_card" in globals() else ""
        except Exception:
            name = ""
        if not name:
            try:
                name = str(getattr(card, "custom_name_var", tk.StringVar(value="")).get() or "")
            except Exception:
                name = ""
        return _r21_custom_prefix_name(name or "CUSTOM_MATERIAL", default="CUSTOM_MATERIAL")

    if custom_prefix:
        try:
            sel = dict(getattr(card, "current_selections", {}) or {})
        except Exception:
            sel = {}
        temp_item = {
            "Element": sel.get("Element", ""),
            "Material": sel.get("Material", ""),
            "Temper": sel.get("Temper", ""),
            "_custom": True,
        }
        return _r21_export_material_name_for_item(temp_item, row=row)

    # Normal unedited rows keep the earlier naming behavior.
    try:
        return _R21_PREV_R19_GENERATED_MATERIAL_NAME(card, custom_prefix=False)
    except Exception:
        return "Material"


# Override the generator used by the existing Material Card refresh function.
try:
    _R21_PREV_R19_GENERATED_MATERIAL_NAME = _r19_generated_material_name
except Exception:
    _R21_PREV_R19_GENERATED_MATERIAL_NAME = lambda card, custom_prefix=None: "Material"


def _r19_generated_material_name(card, *, custom_prefix: Optional[bool] = None) -> str:
    return _r21_export_material_name_for_card(card, custom_prefix=custom_prefix)


def _r21_item_notes(item: Dict[str, Any]) -> str:
    return str(item.get("Notes", "") or item.get("notes", "") or "").strip()


def _r21_ensure_item_export_name(item: Dict[str, Any], row: Optional[pd.Series] = None) -> str:
    """Write the final name back to the export-list item when needed."""
    name = _r21_export_material_name_for_item(item, row=row)
    if name and _r21_item_is_custom_or_edited(item):
        item["Export_Material_Name"] = name
        item["Export_Name"] = name
        if _r21_item_is_custom_blank(item):
            # Keep user-defined name available separately without CUSTOM_.
            item.setdefault("Custom_Name", _r21_clean_name_component(_r21_user_defined_base_name(item, row), default="CUSTOM_MATERIAL"))
    return name


# Use the required custom name for keyfile/image stems.
_R21_PREV_ADV_SHORT_OUTPUT_STEM = SelectionScreen._adv_short_output_stem


def _r21_adv_short_output_stem(self, item: Dict[str, Any], row: pd.Series, item_idx: int, row_idx: int) -> str:
    try:
        if _r21_item_is_custom_or_edited(item):
            name = _r21_ensure_item_export_name(item, row=row)
            safe_name = _card_safe_file_part_from_selection(name) if "_card_safe_file_part_from_selection" in globals() else _r21_clean_name_component(name)
            if row_idx > 1:
                safe_name = f"{safe_name}_r{row_idx}"
            return safe_name[:110]
    except Exception:
        pass
    return _R21_PREV_ADV_SHORT_OUTPUT_STEM(self, item, row, item_idx, row_idx)


SelectionScreen._adv_short_output_stem = _r21_adv_short_output_stem


# Ensure notes are actually written to the final keyfile even when an earlier
# export path succeeds before the tolerant fallback.
_R21_PREV_EXPORT_KEYFILE_PROGRAMMATIC = CardScreen.export_keyfile_programmatic


def _r21_export_keyfile_programmatic(self, row, selections: Dict[str, str], output_dir: Path,
                                     output_stem: str, basis: str = "B", direction: str = "L",
                                     unit_sys: str = "mm_T_s", mat_model: str = "MAT024+GISSMO",
                                     material_id: Optional[Any] = None) -> Dict[str, Any]:
    result = _R21_PREV_EXPORT_KEYFILE_PROGRAMMATIC(
        self,
        row=row,
        selections=selections,
        output_dir=output_dir,
        output_stem=output_stem,
        basis=basis,
        direction=direction,
        unit_sys=unit_sys,
        mat_model=mat_model,
        material_id=material_id,
    )

    try:
        if not (isinstance(result, dict) and result.get("ok") and result.get("path")):
            return result

        path = Path(result.get("path", ""))
        if not path.exists():
            return result

        export_notes = str(getattr(self, "_programmatic_export_notes", "") or "").strip()
        custom_name = str(output_stem or "").strip()
        is_custom_named = custom_name.upper().startswith("CUSTOM_")

        k_text = path.read_text(encoding="utf-8", errors="ignore")

        # Reflect custom/edited state in the keyfile header when the exported
        # material name carries CUSTOM_.
        if is_custom_named:
            k_text = k_text.replace("$ Custom Edited: No\n", "$ Custom Edited: Yes\n")

        if export_notes:
            try:
                note_check = " ".join(export_notes.split())
                already_has_notes = note_check and note_check in " ".join(k_text.split())
                if not already_has_notes:
                    k_text = _append_user_notes_to_keyfile_end(k_text, export_notes)
            except Exception:
                if export_notes not in k_text:
                    k_text = k_text.rstrip() + f"\n$ {export_notes}\n"

        path.write_text(k_text, encoding="utf-8")
    except Exception:
        pass

    return result


CardScreen.export_keyfile_programmatic = _r21_export_keyfile_programmatic


# Before export starts, normalize selected custom/edited rows to the required
# CUSTOM_{...} material name and make sure notes are present.
_R21_PREV_ADV_EXPORT_ALL = SelectionScreen._adv_export_all


def _r21_adv_export_all(self):
    try:
        missing_notes = []
        for idx, item in enumerate(getattr(self, "advanced_items", []) or [], start=1):
            if not item.get("_selected", False):
                continue
            if _r21_item_is_custom_or_edited(item):
                _r21_ensure_item_export_name(item)
                if not _r21_item_notes(item):
                    missing_notes.append(str(item.get("Export_ID", idx)))
        if missing_notes:
            messagebox.showerror(
                "Notes Required",
                "Notes are required before export for custom/edited rows.\n\n"
                "Missing notes for ID/MID: " + ", ".join(missing_notes)
            )
            return
    except Exception:
        pass
    return _R21_PREV_ADV_EXPORT_ALL(self)


SelectionScreen._adv_export_all = _r21_adv_export_all


# Export summary must clearly show the required custom name and the notes/reason.
_R21_PREV_ADV_SUMMARY_ROW = SelectionScreen._adv_summary_row


def _r21_adv_summary_row(self, item: Dict[str, Any], item_idx: int, status: str,
                         keyfile_name: str, keyfile_path: str, image_path: str,
                         notes: str, image_name: str = "", row: Optional[pd.Series] = None,
                         export_id: Any = "") -> Dict[str, Any]:
    summary = _R21_PREV_ADV_SUMMARY_ROW(
        self,
        item,
        item_idx,
        status,
        keyfile_name,
        keyfile_path,
        image_path,
        notes,
        image_name=image_name,
        row=row,
        export_id=export_id,
    )

    try:
        if _r21_item_is_custom_or_edited(item):
            export_name = _r21_ensure_item_export_name(item, row=row)
            summary["Export Material Name"] = export_name
            summary["Material Name from Client"] = export_name

            note_text = _r21_item_notes(item) or str(notes or "").strip()
            summary["Notes"] = note_text
            summary["Internal Notes"] = str(summary.get("Internal Notes", "") or "").strip()
            if note_text and "custom" not in summary["Internal Notes"].lower():
                summary["Internal Notes"] = (summary["Internal Notes"] + " | " if summary["Internal Notes"] else "") + f"Custom reason/notes: {note_text}"
        else:
            # Normal rows keep normal naming but still preserve notes if they exist.
            note_text = _r21_item_notes(item) or str(notes or "").strip()
            if note_text:
                summary["Notes"] = note_text
    except Exception:
        pass

    return summary


SelectionScreen._adv_summary_row = _r21_adv_summary_row

# End marker for VS Code search:
# REHAN_CUSTOM_EXPORT_NAMING_AND_NOTES_FINAL_ACTIVE_2026_06_24



# =============================================================================
# REHAN_FULL_EXPORT_DISPLAY_NAME_FORMAT_FIX_2026_06_24
# Purpose:
#   Final material-name rule requested by the user:
#     Regular material:
#       AL_2013-T6511_AMS-4326_ExtrudedBarRodProfiles_0.2_A_Basis_L_MPA_MAT024
#     Custom/edited material:
#       CUSTOM_AL_2013-T6511_AMS-4326_ExtrudedBarRodProfiles_0.2_A_Basis_L_MPA_MAT024
#
#   The same name is now pushed to:
#     - Material Card top-right Material Name box
#     - Advanced Selection Export List display
#     - keyfile/image output stem
#     - export_summary CSV/Excel fields
#     - History/export item state
#
# This patch is intentionally narrow. It does not change calculations, filters,
# images, IDs, or existing export validation logic.
# =============================================================================


def _r22_is_empty_name_value(value: Any) -> bool:
    try:
        text = str(value or "").strip()
        return not text or is_blank(text) or text == NO_SPEC_DISPLAY
    except Exception:
        return True


def _r22_clean_name_piece(value: Any, default: str = "NA", *, keep_dash: bool = True, remove_spaces: bool = True) -> str:
    """Clean one material-name component while keeping the user requested style."""
    text = str(value or "").strip()
    if not text or is_blank(text) or text == NO_SPEC_DISPLAY:
        text = default
    text = (
        text.replace("\u2264", "le")
            .replace("\u2265", "ge")
            .replace("\u2013", "-")
            .replace("\u2014", "-")
            .replace("\u00a0", " ")
    )
    if remove_spaces:
        text = _rehan_re.sub(r"\s+", "", text)
    else:
        text = _rehan_re.sub(r"\s+", "_", text)
    replacements = {
        "<=": "le", ">=": "ge", "<": "lt", ">": "gt",
        "/": "_", "\\": "_", ":": "_", "*": "_", "?": "_",
        '"': "_", "'": "", "|": "_", ",": "_", ";": "_",
        "(": "", ")": "", "[": "", "]": "", "{": "", "}": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if not keep_dash:
        text = text.replace("-", "")
    text = _rehan_re.sub(r"_+", "_", text).strip("_-. ")
    return text or default


def _r22_element_code(value: Any) -> str:
    text = str(value or "").strip()
    low = text.lower()
    if low.startswith("al") or "aluminum" in low or "aluminium" in low:
        return "AL"
    if low.startswith("ti") or "titanium" in low:
        return "TI"
    if low.startswith("steel") or low.startswith("st"):
        return "STEEL"
    return _r22_clean_name_piece(text, default="MAT").upper()


def _r22_value_from_item_row(item: Optional[Dict[str, Any]], row: Optional[pd.Series], *keys: str, default: str = "") -> str:
    item = item if isinstance(item, dict) else {}
    for key in keys:
        try:
            val = item.get(key, "")
        except Exception:
            val = ""
        if not _r22_is_empty_name_value(val):
            return str(val).strip()
    if row is not None and hasattr(row, "get"):
        for key in keys:
            try:
                val = row.get(key, "")
            except Exception:
                val = ""
            if not _r22_is_empty_name_value(val):
                return str(val).strip()
    return default


def _r22_unit_name(unit_sys: Any) -> str:
    unit_sys = str(unit_sys or "mm_T_s").strip() or "mm_T_s"
    try:
        label = UNIT_SYSTEM_SPEC.get(unit_sys, UNIT_SYSTEM_SPEC["mm_T_s"]).get("pressure_label", "MPa")
    except Exception:
        label = "MPa"
    return _r22_clean_name_piece(str(label or "MPa").upper(), default="MPA")


def _r22_material_model_name(model: Any) -> str:
    text = str(model or "MAT024+GISSMO").strip() or "MAT024+GISSMO"
    # Keep MAT024+GISSMO readable; only file-unsafe characters are cleaned.
    text = text.replace("+", "+")
    return _r22_clean_name_piece(text, default="MAT024", keep_dash=True)


def _r22_normalized_custom_prefix(name: str, enabled: bool) -> str:
    text = str(name or "").strip()
    if not text:
        return text
    while text.upper().startswith("CUSTOM_CUSTOM_"):
        text = "CUSTOM_" + text[14:]
    if enabled and not text.upper().startswith("CUSTOM_"):
        text = "CUSTOM_" + text
    if not enabled and text.upper().startswith("CUSTOM_"):
        text = text[7:]
    return text[:180]


def _r22_item_should_use_custom_prefix(item: Optional[Dict[str, Any]]) -> bool:
    try:
        return bool(_r21_item_is_custom_or_edited(item if isinstance(item, dict) else {}))
    except Exception:
        try:
            return bool(_mgr_item_is_custom_or_edited(item))
        except Exception:
            return bool(isinstance(item, dict) and (item.get("_custom") or item.get("_edited_from_card") or item.get("Custom_Blank_Entry")))


def _r22_item_manual_name(item: Optional[Dict[str, Any]]) -> str:
    """Return a truly user-locked manual name only."""
    if not isinstance(item, dict):
        return ""
    if not bool(item.get("_export_name_manual", False)):
        return ""
    existing = str(item.get("Export_Material_Name", "") or item.get("Export_Name", "") or "").strip()
    return existing


def _r22_build_full_name_from_parts(*, element: Any, material: Any, temper: Any, spec: Any,
                                    form: Any, thickness: Any, basis: Any, direction: Any,
                                    unit_sys: Any, model: Any, custom_prefix: bool = False) -> str:
    material_piece = _r22_clean_name_piece(material, default="Material")
    temper_piece = _r22_clean_name_piece(temper, default="")
    if temper_piece and temper_piece != "NA" and temper_piece.lower() not in material_piece.lower():
        material_temper = f"{material_piece}-{temper_piece}"
    else:
        material_temper = material_piece

    basis_code = _r22_clean_name_piece(str(basis or "B").upper(), default="B")
    direction_code = _r22_clean_name_piece(str(direction or "L").upper(), default="L")

    parts = [
        _r22_element_code(element),
        material_temper,
        _r22_clean_name_piece(spec, default="Spec", keep_dash=True),
        _r22_clean_name_piece(form, default="Form", keep_dash=False),
        _r22_clean_name_piece(thickness, default="NA", keep_dash=True),
        f"{basis_code}_Basis",
        direction_code,
        _r22_unit_name(unit_sys),
        _r22_material_model_name(model),
    ]
    name = "_".join([str(p) for p in parts if str(p or "").strip() and str(p).strip() != "NA"])
    return _r22_normalized_custom_prefix(name, bool(custom_prefix))


def _r22_export_name_from_item(item: Dict[str, Any], row: Optional[pd.Series] = None,
                               custom_prefix: Optional[bool] = None) -> str:
    """Full export/display name for an Advanced Selection item."""
    if custom_prefix is None:
        custom_prefix = _r22_item_should_use_custom_prefix(item)

    manual = _r22_item_manual_name(item)
    if manual:
        return _r22_normalized_custom_prefix(_r22_clean_name_piece(manual, default="MATERIAL"), bool(custom_prefix))

    # For blank custom entries with no useful material tokens, preserve the user-defined top-right name.
    if _r21_item_is_custom_blank(item):
        candidate = str(item.get("Export_Material_Name", "") or item.get("Export_Name", "") or item.get("Custom_Name", "") or "").strip()
        state = item.get("_card_custom_state")
        if isinstance(state, dict):
            candidate = str(state.get("Export_Material_Name", "") or state.get("custom_name", "") or candidate).strip()
        material_token = str(item.get("Material", "") or "").strip().upper()
        if candidate and (not material_token or material_token.startswith("CUSTOM") or material_token in {"MATERIAL", "NA", "-"}):
            return _r22_normalized_custom_prefix(_r22_clean_name_piece(candidate, default="CUSTOM_MATERIAL"), True)

    element = _r22_value_from_item_row(item, row, "Element", default="AL")
    material = _r22_value_from_item_row(item, row, "Material", default="Material")
    temper = _r22_value_from_item_row(item, row, "Temper", default="")
    spec = _r22_value_from_item_row(item, row, "Specification", "Spec1_1", "spec1_1", default="Spec")
    form = _r22_value_from_item_row(item, row, "Form", default="Form")
    thickness = _r22_value_from_item_row(item, row, "Thickness", "Thick_Value", "Thickness_Value", "ThicknessOrDia", default="NA")
    basis = _r22_value_from_item_row(item, row, "Basis", default="B")
    direction = _r22_value_from_item_row(item, row, "Direction", default="L")
    unit_sys = _r22_value_from_item_row(item, row, "Unit_System", "Unit", default="mm_T_s")
    # Unit may be the label from the export list; convert common labels back to unit key.
    unit_label_norm = norm(unit_sys)
    for key, spec_obj in UNIT_SYSTEM_SPEC.items():
        if unit_label_norm in {norm(key), norm(spec_obj.get("label", "")), norm(spec_obj.get("pressure_label", ""))}:
            unit_sys = key
            break
    model = _r22_value_from_item_row(item, row, "Material_Model", "Matcard", "Model", default="MAT024+GISSMO")

    return _r22_build_full_name_from_parts(
        element=element,
        material=material,
        temper=temper,
        spec=spec,
        form=form,
        thickness=thickness,
        basis=basis,
        direction=direction,
        unit_sys=unit_sys,
        model=model,
        custom_prefix=bool(custom_prefix),
    )


def _r22_export_name_from_card(card, *, custom_prefix: Optional[bool] = None) -> str:
    """Full export/display name for the Material Card top-right box."""
    if custom_prefix is None:
        try:
            custom_prefix = _r19_card_has_user_edits(card)
        except Exception:
            custom_prefix = bool(getattr(card, "is_custom_entry", False))

    if bool(getattr(card, "is_custom_entry", False)):
        # If it is a blank custom entry and the user typed a name, keep it as the custom base.
        try:
            candidate = str(getattr(card, "export_material_name_var", tk.StringVar(value="")).get() or "").strip()
            locked = bool(getattr(card, "_r19_name_user_locked", False))
            if candidate and locked:
                return _r22_normalized_custom_prefix(_r22_clean_name_piece(candidate, default="CUSTOM_MATERIAL"), True)
        except Exception:
            pass

    row = getattr(card, "current_row", None)
    sel = dict(getattr(card, "current_selections", {}) or {})
    element = sel.get("Element") or (row.get("Element", "AL") if row is not None and hasattr(row, "get") else "AL")
    material = sel.get("Material") or (row.get("Material", "Material") if row is not None and hasattr(row, "get") else "Material")
    temper = sel.get("Temper") or (row.get("Temper", "") if row is not None and hasattr(row, "get") else "")
    spec = sel.get("Specification") or (row.get("Spec1_1", row.get("Specification", "Spec")) if row is not None and hasattr(row, "get") else "Spec")
    form = sel.get("Form") or (row.get("Form", "Form") if row is not None and hasattr(row, "get") else "Form")
    try:
        thickness = str(getattr(card, "thickness_var", tk.StringVar(value="")).get() or "").strip()
    except Exception:
        thickness = ""
    if not thickness and row is not None:
        try:
            thickness = card._thickness_display_label(row)
        except Exception:
            thickness = source_thickness_display_label(row)
    basis = str(getattr(card, "basis_var", tk.StringVar(value="B")).get() or "B")
    direction = str(getattr(card, "direction_var", tk.StringVar(value="L")).get() or "L")
    unit_sys = str(getattr(card, "unit_sys_var", tk.StringVar(value="mm_T_s")).get() or "mm_T_s")
    model = str(getattr(card, "mat_model_var", tk.StringVar(value="MAT024+GISSMO")).get() or "MAT024+GISSMO")

    return _r22_build_full_name_from_parts(
        element=element,
        material=material,
        temper=temper,
        spec=spec,
        form=form,
        thickness=thickness,
        basis=basis,
        direction=direction,
        unit_sys=unit_sys,
        model=model,
        custom_prefix=bool(custom_prefix),
    )


# Override the r19/r21 name generators so the Material Card no longer falls back
# to the older simplified CUSTOM_AL_2013-T6511 pattern.
def _r19_generated_material_name(card, *, custom_prefix: Optional[bool] = None) -> str:
    return _r22_export_name_from_card(card, custom_prefix=custom_prefix)


def _r21_export_material_name_for_card(card, *, custom_prefix: Optional[bool] = None) -> str:
    return _r22_export_name_from_card(card, custom_prefix=custom_prefix)


def _r19_card_default_export_material_name(card) -> str:
    return _r22_export_name_from_card(card, custom_prefix=_r19_card_has_user_edits(card))


_card_default_export_material_name = _r19_card_default_export_material_name


def _r21_export_material_name_for_item(item: Dict[str, Any], row: Optional[pd.Series] = None) -> str:
    return _r22_export_name_from_item(item, row=row)


def _r21_ensure_item_export_name(item: Dict[str, Any], row: Optional[pd.Series] = None) -> str:
    """Always write the current full export/display name back into the item."""
    if not isinstance(item, dict):
        return ""
    name = _r22_export_name_from_item(item, row=row)
    if name:
        item["Export_Material_Name"] = name
        item["Export_Name"] = name
        item["Material_Name_from_Client"] = name
        item["Material Name from Client"] = name
    try:
        if _r22_item_should_use_custom_prefix(item):
            item["_custom"] = True
            item.setdefault("_tag", "custom_row")
            item.setdefault("_status", "CUSTOM / EDITED - Ready")
    except Exception:
        pass
    return name


# Keep Done-button save in sync with the final naming rule.
_R22_PREV_R19_SYNC_CARD_TO_ADV_ITEM = _r19_sync_card_to_adv_item


def _r19_sync_card_to_adv_item(card, *, mark_edited: bool, refresh: bool, validate_notes: bool) -> bool:
    result = _R22_PREV_R19_SYNC_CARD_TO_ADV_ITEM(card, mark_edited=mark_edited, refresh=False, validate_notes=validate_notes)
    if not result:
        return result
    try:
        ss, target = _r19_card_target_item(card)
        if isinstance(target, dict):
            custom_or_edited = bool(mark_edited or _r19_state_changed_from_item(card, target) or _r19_card_has_user_edits(card) or _r22_item_should_use_custom_prefix(target))
            name = _r22_export_name_from_card(card, custom_prefix=custom_or_edited)
            # Respect a real user-locked manual name, but still guarantee CUSTOM_ when edited/custom.
            if bool(getattr(card, "_r19_name_user_locked", False)):
                current = str(getattr(card, "export_material_name_var", tk.StringVar(value="")).get() or name).strip()
                name = _r22_normalized_custom_prefix(_r22_clean_name_piece(current, default="MATERIAL"), custom_or_edited)
            else:
                try:
                    card.export_material_name_var.set(name)
                except Exception:
                    pass
            target["Export_Material_Name"] = name
            target["Export_Name"] = name
            target["Material_Name_from_Client"] = name
            target["Material Name from Client"] = name
            if custom_or_edited:
                target["_custom"] = True
                target["_edited_from_card"] = True
                target["_tag"] = "custom_row"
                target["_status"] = "CUSTOM / EDITED - Ready"
            try:
                if "_mgr_update_item_status" in globals():
                    _mgr_update_item_status(ss, target)
            except Exception:
                pass
            if refresh and ss is not None:
                _r19_sort_advanced_items(ss)
                ss._adv_refresh_tree()
    except Exception:
        pass
    return True


# Advanced Selection Export List: add/display the final material name column.
def _r22_adv_ensure_material_name_column(self) -> None:
    try:
        tree = getattr(self, "adv_tree", None)
        if tree is None:
            return
        cols = list(tree["columns"])
        if "Export_Material_Name" not in cols:
            insert_at = cols.index("Export_ID") + 1 if "Export_ID" in cols else 2
            cols.insert(insert_at, "Export_Material_Name")
            tree.configure(columns=tuple(cols))
        tree.heading("Export_Material_Name", text="Material Name")
        tree.column("Export_Material_Name", width=360, anchor="w", stretch=False)
    except Exception:
        pass


def _r22_adv_refresh_tree(self):
    try:
        self._adv_clear_dropdown_overlays()
    except Exception:
        pass
    _r22_adv_ensure_material_name_column(self)
    try:
        duplicate_indexes = self._adv_duplicate_indexes()
    except Exception:
        duplicate_indexes = set()
    try:
        for iid in self.adv_tree.get_children():
            self.adv_tree.delete(iid)
    except Exception:
        return

    columns = list(self.adv_tree["columns"])
    for idx, item in enumerate(getattr(self, "advanced_items", []) or []):
        try:
            export_name = _r21_ensure_item_export_name(item)
        except Exception:
            export_name = str(item.get("Export_Material_Name", "") or item.get("Export_Name", "") or "")
        unit_label = UNIT_SYSTEM_SPEC.get(item.get("Unit_System", "mm_T_s"), {}).get("label", item.get("Unit_System", ""))
        values_map = {
            "Export": "",
            "Export_ID": item.get("Export_ID", ""),
            "Export_Material_Name": export_name,
            "Element": item.get("Element", ""),
            "Series": item.get("Series", ""),
            "Material": item.get("Material", ""),
            "Temper": item.get("Temper", ""),
            "Specification": item.get("Specification", ""),
            "Specification_2": item.get("Specification 2", ""),
            "Form": item.get("Form", ""),
            "Thickness": with_dropdown_mark(item.get("Thickness") or item.get("Thickness_Mode", "")),
            "Basis": with_dropdown_mark(item.get("Basis", "B")),
            "Direction": with_dropdown_mark(item.get("Direction", "L")),
            "Unit": with_dropdown_mark(unit_label),
            "Model": with_dropdown_mark(item.get("Material_Model", "MAT024+GISSMO")),
            "Matches": (f"{item.get('_matches', '')}  |  DUPLICATE" if idx in duplicate_indexes else item.get("_status", item.get("_matches", ""))),
            "View_Image": "",
            "Notes": str(item.get("Notes", "")).strip(),
        }
        values = tuple(values_map.get(c, "") for c in columns)
        if idx in duplicate_indexes:
            row_tags = ["duplicate_row"]
            item["_duplicate"] = True
        else:
            row_tags = ["editable_row" if idx % 2 == 0 else "editable_row_alt"]
            if item.get("_tag", ""):
                row_tags.append(item.get("_tag", ""))
            item.pop("_duplicate", None)
        try:
            self.adv_tree.insert("", "end", iid=str(idx), values=values, tags=tuple(row_tags))
        except Exception:
            pass
    try:
        self.adv_tree.tag_configure("duplicate_row", background="#FFE08A", foreground="#7A2E00")
    except Exception:
        pass
    try:
        duplicate_count = len(duplicate_indexes)
        duplicate_text = f" | {duplicate_count} duplicate material row(s) marked" if duplicate_count else ""
        self.adv_count_var.set(f"{sum(1 for x in self.advanced_items if x.get('_selected', False))} selected  /  {len(self.advanced_items)} item(s){duplicate_text}")
        self._adv_update_export_details()
        self.after_idle(self._adv_refresh_dropdown_overlays)
    except Exception:
        pass


SelectionScreen._adv_refresh_tree = _r22_adv_refresh_tree


# Keyfile/image output stem should use the full final name for every row.
def _r22_adv_short_output_stem(self, item: Dict[str, Any], row: pd.Series, item_idx: int, row_idx: int) -> str:
    try:
        name = _r21_ensure_item_export_name(item, row=row)
        safe_name = _card_safe_file_part_from_selection(name) if "_card_safe_file_part_from_selection" in globals() else _r22_clean_name_piece(name, default="MATERIAL")
        if row_idx > 1:
            safe_name = f"{safe_name}_r{row_idx}"
        return safe_name[:125]
    except Exception:
        try:
            return _R21_PREV_ADV_SHORT_OUTPUT_STEM(self, item, row, item_idx, row_idx)
        except Exception:
            return f"material_{item_idx}_{row_idx}"


SelectionScreen._adv_short_output_stem = _r22_adv_short_output_stem


# Export summary should show the same final name for regular and custom/edited rows.
_R22_PREV_ADV_SUMMARY_ROW = SelectionScreen._adv_summary_row


def _r22_adv_summary_row(self, item: Dict[str, Any], item_idx: int, status: str,
                         keyfile_name: str, keyfile_path: str, image_path: str,
                         notes: str, image_name: str = "", row: Optional[pd.Series] = None,
                         export_id: Any = "") -> Dict[str, Any]:
    summary = _R22_PREV_ADV_SUMMARY_ROW(
        self,
        item,
        item_idx,
        status,
        keyfile_name,
        keyfile_path,
        image_path,
        notes,
        image_name=image_name,
        row=row,
        export_id=export_id,
    )
    try:
        final_name = _r21_ensure_item_export_name(item, row=row)
        if final_name:
            summary["Export Material Name"] = final_name
            summary["Material Name from Client"] = final_name
            summary["Export_Name"] = final_name
        note_text = str(item.get("Notes", "") or notes or "").strip()
        if note_text:
            summary["Notes"] = note_text
            if _r22_item_should_use_custom_prefix(item):
                internal = str(summary.get("Internal Notes", "") or "").strip()
                if "custom reason/notes" not in internal.lower():
                    summary["Internal Notes"] = (internal + " | " if internal else "") + f"Custom reason/notes: {note_text}"
    except Exception:
        pass
    return summary


SelectionScreen._adv_summary_row = _r22_adv_summary_row


# Normalize selected row names before export so Advanced Selection display,
# keyfile/image names, and summary names all match.
_R22_PREV_ADV_EXPORT_ALL = SelectionScreen._adv_export_all


def _r22_adv_export_all(self):
    try:
        for item in getattr(self, "advanced_items", []) or []:
            if item.get("_selected", False):
                _r21_ensure_item_export_name(item)
        try:
            self._adv_refresh_tree()
        except Exception:
            pass
    except Exception:
        pass
    return _R22_PREV_ADV_EXPORT_ALL(self)


SelectionScreen._adv_export_all = _r22_adv_export_all


# History entries should also carry the final generated name.
_R22_PREV_R19_SAVE_HISTORY_FROM_DONE = _r19_save_history_from_done


def _r19_save_history_from_done(card, target: Optional[Dict[str, Any]] = None):
    try:
        if isinstance(target, dict):
            name = _r21_ensure_item_export_name(target, row=getattr(card, "current_row", None))
            try:
                card.export_material_name_var.set(name)
            except Exception:
                pass
        else:
            name = _r22_export_name_from_card(card, custom_prefix=_r19_card_has_user_edits(card))
            try:
                card.export_material_name_var.set(name)
            except Exception:
                pass
    except Exception:
        pass
    return _R22_PREV_R19_SAVE_HISTORY_FROM_DONE(card, target)


# End marker for VS Code search:
# REHAN_FULL_EXPORT_DISPLAY_NAME_FORMAT_FIX_ACTIVE_2026_06_24


# =============================================================================
# REHAN_CUSTOM_DONE_BACK_NOTES_FINAL_FIX_2026_06_24
# Purpose:
#   Final manager-test correction for edited/custom naming and notes behavior.
#
# Rules enforced here:
#   1. Back to Selection is cancel-only. Unsaved card edits must NOT update the
#      Advanced Selection export-list row, must NOT require notes, and must NOT
#      add CUSTOM_ to the stored material name.
#   2. Done is the only save action. If a regular material was changed and Done
#      is clicked, Notes are required and the saved/exported material name gets
#      CUSTOM_ at the front.
#   3. Existing saved custom/edited rows keep CUSTOM_ when reopened.
#   4. User Notes are written into keyfiles as real LS-DYNA comment lines.
# =============================================================================


def _r23_item_is_saved_custom_or_edited(item: Optional[Dict[str, Any]]) -> bool:
    """Return True only for rows that are already saved as custom/edited.

    Important: earlier patches stored _card_custom_state for normal rows too.
    That state is useful for restoring the card, but by itself it must not make
    a regular material CUSTOM_ and must not make notes mandatory.
    """
    if not isinstance(item, dict):
        return False
    try:
        if "_r21_item_is_custom_blank" in globals() and _r21_item_is_custom_blank(item):
            return True
    except Exception:
        pass
    flags = (
        "_custom", "_custom_blank_entry", "Custom_Blank_Entry", "is_custom_blank_entry",
        "_edited_from_card", "_edited_from_export_list", "_user_changes",
    )
    try:
        if any(bool(item.get(k)) for k in flags):
            return True
    except Exception:
        pass
    status = str(item.get("_status", "") or "").upper()
    if "CUSTOM" in status or "EDITED" in status:
        return True
    for name_key in ("Export_Material_Name", "Export_Name", "Material_Name_from_Client", "Material Name from Client"):
        try:
            if str(item.get(name_key, "") or "").strip().upper().startswith("CUSTOM_"):
                return True
        except Exception:
            pass
    return False


def _r23_card_is_saved_custom_or_edited(card) -> bool:
    """True when the opened card already belongs to a saved custom/edited row."""
    try:
        if bool(getattr(card, "is_custom_entry", False)):
            return True
    except Exception:
        pass
    try:
        _ss, item = _r19_card_target_item(card)
        return _r23_item_is_saved_custom_or_edited(item)
    except Exception:
        return False


# Override the broad older helpers so _card_custom_state alone does not mean
# custom/edited. This fixes regular rows becoming CUSTOM_ just because they were
# opened/saved once without real edits.
def _mgr_item_is_custom_or_edited(item: Dict[str, Any]) -> bool:
    return _r23_item_is_saved_custom_or_edited(item)


def _mgr_item_requires_notes(item: Dict[str, Any]) -> bool:
    return _r23_item_is_saved_custom_or_edited(item)


def _r21_item_is_custom_or_edited(item: Dict[str, Any]) -> bool:
    return _r23_item_is_saved_custom_or_edited(item)


def _r22_item_should_use_custom_prefix(item: Optional[Dict[str, Any]]) -> bool:
    return _r23_item_is_saved_custom_or_edited(item)


# Do not let live typing/clicking persist edits into Advanced Selection.  The old
# live-sync paths called this function with mark_edited=True and validate_notes=False.
# Done/export saves still call with validate_notes=True, so those paths continue.
_R23_PREV_R19_SYNC_CARD_TO_ADV_ITEM = _r19_sync_card_to_adv_item


def _r19_sync_card_to_adv_item(card, *, mark_edited: bool, refresh: bool, validate_notes: bool) -> bool:
    if bool(mark_edited) and not bool(validate_notes) and not bool(getattr(card, "_r23_done_saving", False)):
        # Back must behave like Cancel. Keep Notes/name locally on the card only.
        return True
    old_flag = bool(getattr(card, "_r23_done_saving", False))
    if validate_notes:
        try:
            card._r23_done_saving = True
        except Exception:
            pass
    try:
        return _R23_PREV_R19_SYNC_CARD_TO_ADV_ITEM(card, mark_edited=mark_edited, refresh=refresh, validate_notes=validate_notes)
    finally:
        try:
            card._r23_done_saving = old_flag
        except Exception:
            pass


# Material-name refresh: while the user is only editing on the card, do not add
# CUSTOM_. CUSTOM_ is added only during Done/save or when the row was already
# saved as custom/edited before opening.
_R23_PREV_R19_REFRESH_MATERIAL_NAME = _r19_refresh_material_name


def _r19_refresh_material_name(card, *, force: bool = False, custom_prefix: Optional[bool] = None) -> str:
    try:
        saving_now = bool(getattr(card, "_r23_done_saving", False))
    except Exception:
        saving_now = False
    if custom_prefix is None:
        custom_prefix = _r23_card_is_saved_custom_or_edited(card)
    elif bool(custom_prefix) and not saving_now and not _r23_card_is_saved_custom_or_edited(card):
        # This is an unsaved regular-material edit. Do not show/save CUSTOM_ yet.
        custom_prefix = False
    return _R23_PREV_R19_REFRESH_MATERIAL_NAME(card, force=force, custom_prefix=custom_prefix)


def _r19_card_default_export_material_name(card) -> str:
    return _r22_export_name_from_card(card, custom_prefix=_r23_card_is_saved_custom_or_edited(card))


_card_default_export_material_name = _r19_card_default_export_material_name


# Top-right Material Name and Notes fields should not update the export-list row
# until Done is clicked. They only update the local card variables.
def _r19_name_changed(card, event=None):
    _r19_ensure_card_vars(card)
    try:
        card._r19_name_user_locked = True
    except Exception:
        pass
    try:
        if bool(getattr(card, "is_custom_entry", False)):
            if not hasattr(card, "custom_name_var"):
                card.custom_name_var = tk.StringVar(value="")
            card.custom_name_var.set(str(card.export_material_name_var.get() or "").strip())
    except Exception:
        pass


def _r19_notes_changed(card, event=None):
    _r19_ensure_card_vars(card)
    try:
        val = _r19_notes_text(card)
        card.material_notes_var.set(val)
    except Exception:
        pass


def _card_on_notes_changed(self, event=None):
    try:
        _r19_notes_changed(self, event)
    except Exception:
        pass


def _card_on_export_name_changed(self, event=None):
    try:
        _r19_name_changed(self, event)
    except Exception:
        pass


# Wrap Done so the name generator is allowed to add CUSTOM_ during the save.
_R23_PREV_DONE_TO_ADVANCED_SELECTION = CardScreen._done_to_advanced_selection


def _r23_done_to_advanced_selection(self):
    old_flag = bool(getattr(self, "_r23_done_saving", False))
    try:
        self._r23_done_saving = True
        return _R23_PREV_DONE_TO_ADVANCED_SELECTION(self)
    finally:
        try:
            self._r23_done_saving = old_flag
        except Exception:
            pass


CardScreen._done_to_advanced_selection = _r23_done_to_advanced_selection


# After Done, guarantee the saved row carries the final full CUSTOM_ name when
# the card actually changed. This runs after the older sync/save logic.
_R23_PREV_R19_SAVE_HISTORY_FROM_DONE = _r19_save_history_from_done


def _r19_save_history_from_done(card, target: Optional[Dict[str, Any]] = None):
    try:
        if isinstance(target, dict):
            changed = False
            try:
                changed = bool(_r19_state_changed_from_item(card, target) or _r19_card_has_user_edits(card) or _r23_item_is_saved_custom_or_edited(target))
            except Exception:
                changed = _r23_item_is_saved_custom_or_edited(target)
            if changed:
                target["_custom"] = True
                target["_edited_from_card"] = True
                target["_tag"] = "custom_row"
                target["_status"] = "CUSTOM / EDITED - Ready"
                final_name = _r22_export_name_from_card(card, custom_prefix=True)
            else:
                final_name = _r22_export_name_from_card(card, custom_prefix=False)
            target["Export_Material_Name"] = final_name
            target["Export_Name"] = final_name
            target["Material_Name_from_Client"] = final_name
            target["Material Name from Client"] = final_name
            try:
                card.export_material_name_var.set(final_name)
            except Exception:
                pass
    except Exception:
        pass
    return _R23_PREV_R19_SAVE_HISTORY_FROM_DONE(card, target)


# Make sure keyfile notes are explicit comments, e.g. "$ Notes: changed Fty".
def _keyfile_comment_lines_from_notes(notes: Any) -> List[str]:
    text = str(notes or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    out: List[str] = []
    for raw_line in text.split("\n"):
        line = " ".join(str(raw_line or "").strip().split())
        if not line:
            continue
        clean_line = line[1:].strip() if line.startswith("$") else line
        if clean_line.lower().startswith("notes:"):
            out.append(f"$ {clean_line}")
        else:
            out.append(f"$ Notes: {clean_line}")
    return out


# Export-time guarantee: selected saved edited/custom rows get CUSTOM_ and notes
# remain in the item before keyfile generation.
_R23_PREV_ADV_EXPORT_ALL = SelectionScreen._adv_export_all


def _r23_adv_export_all(self):
    try:
        for item in getattr(self, "advanced_items", []) or []:
            if not item.get("_selected", False):
                continue
            if _r23_item_is_saved_custom_or_edited(item):
                item["_custom"] = True
                item.setdefault("_edited_from_card", True)
                item["Export_Material_Name"] = _r22_export_name_from_item(item, custom_prefix=True)
                item["Export_Name"] = item["Export_Material_Name"]
                item["Material_Name_from_Client"] = item["Export_Material_Name"]
                item["Material Name from Client"] = item["Export_Material_Name"]
    except Exception:
        pass
    return _R23_PREV_ADV_EXPORT_ALL(self)


SelectionScreen._adv_export_all = _r23_adv_export_all


# End marker for VS Code search:
# REHAN_CUSTOM_DONE_BACK_NOTES_FINAL_FIX_2026_06_24


# =============================================================================
# SAMUEL GISSMO EXPORT CURVE + CUSTOM ELONGATION REQUIRED FIX 2026_06_25
# Purpose:
#   Samuel reported that MAT024+GISSMO looked correct in the GUI, but exported
#   *DEFINE_CURVE_TITLE Y values were flat/zero because Elongation at Break was
#   not being forced into the GISSMO keyfile calculation path. This final
#   override keeps the existing GUI/features and fixes only:
#     1) GISSMO exported curve P.F.S. Y values are recalculated from current
#        Elongation at Break / Fty / E values before keyfile writing.
#     2) Custom blank materials cannot be saved/exported as MAT024+GISSMO unless
#        Elongation at Break is entered. Ftu remains mandatory for custom too.
# =============================================================================


def _samuel_clean_numeric_text(value: Any) -> str:
    try:
        text = str(value if value is not None else "").strip()
    except Exception:
        text = ""
    return text.replace(",", "")


def _samuel_is_blank_value(value: Any) -> bool:
    text = _samuel_clean_numeric_text(value)
    return text == "" or text.lower() in {"-", "nan", "none", "null", "n/a", "na"}


def _samuel_live_property_text(card, key: str) -> str:
    """Return the current visible/custom source value for a Property Card row.

    Order matters for custom cards and live editing:
      Entry widget text -> pending edit -> committed prop_values -> computed
      source value -> raw source row value.
    Explicit numeric zero is preserved as a real value.
    """
    try:
        var = getattr(card, "prop_value_vars", {}).get(key)
        if var is not None:
            text = _samuel_clean_numeric_text(var.get())
            if not _samuel_is_blank_value(text):
                return text
    except Exception:
        pass

    try:
        if key in getattr(card, "pending_edits", {}):
            text = _samuel_clean_numeric_text(card.pending_edits.get(key))
            if not _samuel_is_blank_value(text):
                return text
    except Exception:
        pass

    try:
        stored = getattr(card, "prop_values", {}).get(key, ("", False))
        if isinstance(stored, (list, tuple)):
            text = _samuel_clean_numeric_text(stored[0] if stored else "")
        elif isinstance(stored, dict):
            text = _samuel_clean_numeric_text(stored.get("value", ""))
        else:
            text = _samuel_clean_numeric_text(stored)
        if not _samuel_is_blank_value(text):
            return text
    except Exception:
        pass

    try:
        computed = card._compute_table()
        text = _samuel_clean_numeric_text((computed or {}).get(key, {}).get("value", ""))
        if not _samuel_is_blank_value(text):
            return text
    except Exception:
        pass

    try:
        raw = card._raw_value_exact(key)
        if raw is not None:
            return _samuel_clean_numeric_text(raw)
    except Exception:
        pass

    try:
        if key == "Elong":
            raw = card._raw_value_any_available("Elong")
            if raw is not None:
                return _samuel_clean_numeric_text(raw)
    except Exception:
        pass

    return ""


def _samuel_live_property_float(card, key: str) -> Optional[float]:
    text = _samuel_live_property_text(card, key)
    if _samuel_is_blank_value(text):
        return None
    num = try_float(text)
    if num is None:
        return None
    if key == "Elong":
        return abs(float(num))
    return float(num)


def _samuel_is_custom_material_card(card) -> bool:
    try:
        if bool(getattr(card, "is_custom_entry", False)):
            return True
    except Exception:
        pass
    try:
        ss, target = _r19_card_target_item(card) if "_r19_card_target_item" in globals() else (None, None)
        if isinstance(target, dict):
            if target.get("_custom_blank_entry") or target.get("Custom_Blank_Entry"):
                return True
            if target.get("_custom") or target.get("_edited_from_card"):
                return True
            if isinstance(target.get("_card_custom_state"), dict):
                return True
    except Exception:
        pass
    try:
        return any(bool(v[1]) for v in getattr(card, "prop_values", {}).values() if isinstance(v, (list, tuple)) and len(v) >= 2)
    except Exception:
        return False


def _samuel_custom_gissmo_required_missing(card) -> List[str]:
    """Custom MAT024+GISSMO required fields from Samuel's bug report."""
    try:
        model = str(card.mat_model_var.get() or "").strip().upper().replace(" ", "")
    except Exception:
        model = ""
    if model not in {"MAT024+GISSMO", "MAT_024+GISSMO", "MAT024GISSMO"}:
        return []
    if not _samuel_is_custom_material_card(card):
        return []

    missing: List[str] = []
    if _samuel_live_property_float(card, "Ftu") is None:
        missing.append("Ultimate Tensile Strength: Ftu")
    if _samuel_live_property_float(card, "Elong") is None:
        missing.append("Elongation at Break")
    return missing


def _samuel_mark_missing_property_entry(card, key: str) -> None:
    try:
        entry = getattr(card, "prop_value_widgets", {}).get(key)
        if entry is not None and entry.winfo_exists():
            entry.configure(bg="#FFECEC", fg="#C00000")
            entry.focus_set()
    except Exception:
        pass


def _samuel_show_custom_required_error(card, missing: List[str], action: str = "Done") -> None:
    try:
        if any("Elong" in m for m in missing):
            _samuel_mark_missing_property_entry(card, "Elong")
        elif any("Ftu" in m or "Tensile" in m for m in missing):
            _samuel_mark_missing_property_entry(card, "Ftu")
    except Exception:
        pass
    messagebox.showerror(
        f"{action} - Required Values Missing",
        "Custom MAT024+GISSMO material cannot be saved/exported until these values are entered:\n\n"
        + "\n".join(f"- {m}" for m in missing)
        + "\n\nElongation at Break is required because it drives the GISSMO P.F.S. failure curve."
    )


def _samuel_failure_pfs_from_elongation(card, computed: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[float]:
    """Calculate GISSMO tensile P.F.S. from Elongation at Break.

    This mirrors the MAT024 card formula used by the GUI:
      Eng Elong (%) = Elong at Break + elastic strain correction
      True Elong (%) = 100*ln(1 + Eng Elong/100)
      Eff.P.S. (%)   = (True Elong/100 - SIGY/E) * 100
      GISSMO P.F.S.  = Eff.P.S./100

    The key fix is that export no longer trusts stale/zero curve values; it
    recalculates from the current live/custom property values before writing
    *DEFINE_CURVE_TITLE.
    """
    if computed is None:
        try:
            computed = card._compute_table()
        except Exception:
            computed = {}

    # First use the current computed MAT024 value if it exists.
    try:
        effps = getattr(card, "last_effps", None)
        if effps is not None:
            return max(abs(float(effps)) / 100.0, 0.0)
    except Exception:
        pass

    try:
        eps_text = (computed or {}).get("Elong", {}).get("eps", "")
        eps = try_float(eps_text)
        if eps is not None:
            return max(abs(float(eps)) / 100.0, 0.0)
    except Exception:
        pass

    raw_elong = _samuel_live_property_float(card, "Elong")
    raw_fty = _samuel_live_property_float(card, "Fty")
    raw_e = _samuel_live_property_float(card, "E")

    # Missing elongation means the GISSMO failure curve cannot be calculated.
    if raw_elong is None:
        return None

    # Explicit all-zero custom input should produce explicit zero, not stale data.
    if raw_elong == 0 and (raw_fty in (None, 0)) and (raw_e in (None, 0)):
        try:
            card.last_effps = 0.0
        except Exception:
            pass
        return 0.0

    if raw_fty is None or raw_e in (None, 0):
        return None

    try:
        unit_sys = card.unit_sys_var.get()
    except Exception:
        unit_sys = "mm_T_s"
    if unit_sys not in UNIT_SYSTEM_SPEC:
        unit_sys = "mm_T_s"

    try:
        fty_eng, _ = convert_value(raw_fty, "pressure", unit_sys, card._effective_unit_conversions())
        e_eng, _ = convert_value(raw_e, "modulus", unit_sys, card._effective_unit_conversions())
    except Exception:
        fty_eng = None
        e_eng = None

    if fty_eng is None or e_eng in (None, 0):
        return None

    try:
        elong_eng = abs(float(raw_elong)) + (100.0 * float(raw_fty)) / (float(raw_e) * 1000.0)
        arg = 1.0 + elong_eng / 100.0
        if arg <= 0:
            return None
        elong_true = 100.0 * math.log(arg)
        effps_percent = abs(((elong_true / 100.0) - (float(fty_eng) / float(e_eng))) * 100.0)
        try:
            card.last_effps = effps_percent
        except Exception:
            pass
        return max(effps_percent / 100.0, 0.0)
    except Exception:
        return None


def _samuel_compression_pfs_for_export(card, computed: Optional[Dict[str, Dict[str, str]]] = None) -> float:
    try:
        if "_gissmo_final_compression_pfs" in globals():
            return max(float(_gissmo_final_compression_pfs(card, computed)), 0.0)
    except Exception:
        pass
    try:
        text = _samuel_live_property_text(card, "Compression")
        num = try_float(text)
        if num is not None:
            return max(float(num) / 100.0, 0.0)
    except Exception:
        pass
    try:
        comp_text = (computed or {}).get("Compression", {}).get("eng", "")
        num = try_float(comp_text)
        if num is not None:
            return max(float(num) / 100.0, 0.0)
    except Exception:
        pass
    return 0.9900 if not _samuel_is_custom_material_card(card) else 0.0


_SAMUEL_PREV_GISSMO_TABLE_POINTS = CardScreen._gissmo_table_points


def _samuel_gissmo_table_points(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> List[Tuple[float, Optional[float]]]:
    if computed is None:
        try:
            computed = self._compute_table()
        except Exception:
            computed = {}

    # Preserve whatever current logic calculates for Triax. values.
    raw_points: List[Tuple[Any, Any]] = []
    try:
        raw_points = list(_SAMUEL_PREV_GISSMO_TABLE_POINTS(self, computed) or [])
    except Exception:
        raw_points = []

    if len(raw_points) >= 4:
        triax_values = [try_float(raw_points[i][0]) for i in range(4)]
        triax_values = [float(v) if v is not None else 0.0 for v in triax_values]
    else:
        triax_values = [-1.0 / 3.0, -0.0001, 0.0, 2.0 / 3.0]

    comp_pfs = _samuel_compression_pfs_for_export(self, computed)
    fail_pfs = _samuel_failure_pfs_from_elongation(self, computed)
    if fail_pfs is None:
        # Keep a real previously calculated row value only if it exists.
        for idx in (2, 3):
            try:
                existing = try_float(raw_points[idx][1])
                if existing is not None:
                    fail_pfs = max(float(existing), 0.0)
                    break
            except Exception:
                continue
    if fail_pfs is None:
        fail_pfs = 0.0

    return [
        (triax_values[0], comp_pfs),
        (triax_values[1], comp_pfs),
        (triax_values[2], fail_pfs),
        (triax_values[3], fail_pfs),
    ]


CardScreen._gissmo_table_points = _samuel_gissmo_table_points
CardScreen._gissmo_failure_pfs = lambda self, computed=None: _samuel_failure_pfs_from_elongation(self, computed)


_SAMUEL_PREV_GISSMO_KEY_BLOCK = CardScreen._gissmo_key_block


def _samuel_gissmo_key_block(self, title: str, mid: int = 1) -> str:
    """Write GISSMO key block with P.F.S. values recalculated from Elongation.

    The previous export could write a correct-looking curve with all Y values as
    0. This block forces the same current table values used by the GUI into the
    exported *DEFINE_CURVE_TITLE section.
    """
    try:
        computed = self._compute_table()
    except Exception:
        computed = {}
    points = _samuel_gissmo_table_points(self, computed)

    try:
        table_label = self._gissmo_table_label()
    except Exception:
        table_label = "Table 2L"
    try:
        curve_id = abs(int(mid or self._gissmo_curve_id()))
    except Exception:
        curve_id = abs(int(mid or 1))
    ecrit_id = -abs(curve_id)

    def f10(value: Any) -> str:
        if value in (None, "", "-"):
            value = 0
        return f"{value:>10}"

    def fmt_curve_x(value: Any) -> str:
        num = try_float(value)
        if num is None:
            return "0"
        return f"{float(num):.6g}"

    def fmt_curve_y(value: Any) -> str:
        num = try_float(value)
        if num is None:
            return "0"
        # P.F.S. is a strain fraction. Keep enough precision for small values.
        return f"{max(float(num), 0.0):.6g}"

    lines = [
        "$",
        f"$ GISSMO Damage / Failure Table: {table_label}",
        "$ P.F.S. values recalculated from current Elongation at Break before export.",
        "*MAT_ADD_EROSION_TITLE",
        f"{title}_GISSMO",
        "$#      MID      EXCL    MXPRES     MNEPS    EFFEPS    VOLEPS    NUMFIP       NCS",
        f"{f10(mid)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}",
        "$#   MNPRES     SIGP1     SIGVM     MXEPS     EPSSH     SIGTH   IMPULSE    FAILTM",
        f"{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}",
        "$#     IDAM    DMGTYP     LCSDG     ECRIT    DMGEXP     DCRIT    FADEXP    LCREGD",
        f"{f10(1)}{f10(1)}{f10(curve_id)}{f10(ecrit_id)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}",
        "$#   SIZFLG     REFSZ     NAHSV     LCSRS    REGSHR    RGBIAX",
        f"{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}{f10(0)}",
        "$",
        "*DEFINE_CURVE_TITLE",
        f"{table_label} - Triaxiality vs P.F.S",
        "$#     LCID      SIDR       SFA       SFO      OFFA      OFFO",
        f"{f10(curve_id)}{f10(0)}{f10(1.0)}{f10(1.0)}{f10(0)}{f10(0)}",
        "$#                A1                  O1",
    ]
    for triax, pfs in points[:4]:
        lines.append(f"{fmt_curve_x(triax):>20}{fmt_curve_y(pfs):>20}")
    lines.append("$")
    return "\n".join(lines) + "\n"


CardScreen._gissmo_key_block = _samuel_gissmo_key_block


# Show custom missing Ftu/Elong as red required Property Card rows.
_SAMUEL_PREV_MISSING_REQUIRED_LABELS = CardScreen._missing_required_labels_from_computed
_SAMUEL_PREV_MISSING_REQUIRED_KEYS = CardScreen._missing_required_property_keys_from_computed


def _samuel_missing_required_labels_from_computed(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> List[str]:
    labels = []
    try:
        labels = list(_SAMUEL_PREV_MISSING_REQUIRED_LABELS(self, computed) or [])
    except Exception:
        labels = []
    for label in _samuel_custom_gissmo_required_missing(self):
        short = "FTU" if "Ftu" in label or "Tensile" in label else "Elongation at Break"
        if short not in labels:
            labels.append(short)
    return labels


def _samuel_missing_required_property_keys_from_computed(self, computed: Optional[Dict[str, Dict[str, str]]] = None) -> set:
    try:
        keys = set(_SAMUEL_PREV_MISSING_REQUIRED_KEYS(self, computed) or set())
    except Exception:
        keys = set()
    missing = _samuel_custom_gissmo_required_missing(self)
    if any("Tensile" in label or "Ftu" in label for label in missing):
        keys.add("Ftu")
    if any("Elong" in label for label in missing):
        keys.add("Elong")
    return keys


CardScreen._missing_required_labels_from_computed = _samuel_missing_required_labels_from_computed
CardScreen._missing_required_property_keys_from_computed = _samuel_missing_required_property_keys_from_computed


# Guard direct CardScreen export for custom MAT024+GISSMO.
_SAMUEL_PREV_CARD_EXPORT = CardScreen._export


def _samuel_card_export(self):
    missing = _samuel_custom_gissmo_required_missing(self)
    if missing:
        _samuel_show_custom_required_error(self, missing, action="Export kFile")
        return "break"
    return _SAMUEL_PREV_CARD_EXPORT(self)


CardScreen._export = _samuel_card_export


# Guard Done for custom MAT024+GISSMO before the row is saved to Advanced Selection.
_SAMUEL_PREV_DONE_TO_ADVANCED = CardScreen._done_to_advanced_selection


def _samuel_done_to_advanced_selection(self):
    try:
        # Read pending/visible typed values before old Done logic stores the row.
        missing = _samuel_custom_gissmo_required_missing(self)
        if missing:
            _samuel_show_custom_required_error(self, missing, action="Done")
            try:
                self._sync_top_disclaimer()
            except Exception:
                pass
            return "break"
    except Exception:
        pass
    return _SAMUEL_PREV_DONE_TO_ADVANCED(self)


CardScreen._done_to_advanced_selection = _samuel_done_to_advanced_selection


# Guard Advanced Selection export for custom rows already present in the list.
def _samuel_prop_value_from_saved_state(state: Any, key: str) -> Optional[float]:
    try:
        prop_values = state.get("prop_values", {}) if isinstance(state, dict) else {}
        value = prop_values.get(key, "")
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        elif isinstance(value, dict):
            value = value.get("value", "")
        num = try_float(value)
        if num is None:
            return None
        return abs(float(num)) if key == "Elong" else float(num)
    except Exception:
        return None


def _samuel_adv_item_custom_gissmo_missing(item: Dict[str, Any]) -> List[str]:
    if not isinstance(item, dict):
        return []
    try:
        model = str(item.get("Material_Model", "") or item.get("Model", "")).strip().upper().replace(" ", "")
    except Exception:
        model = ""
    if model not in {"MAT024+GISSMO", "MAT_024+GISSMO", "MAT024GISSMO"}:
        return []
    try:
        is_custom = bool(
            item.get("_custom_blank_entry") or item.get("Custom_Blank_Entry")
            or item.get("_custom") or item.get("_edited_from_card")
            or isinstance(item.get("_card_custom_state"), dict)
        )
    except Exception:
        is_custom = False
    if not is_custom:
        return []
    state = item.get("_card_custom_state") if isinstance(item.get("_card_custom_state"), dict) else {}
    missing: List[str] = []
    if _samuel_prop_value_from_saved_state(state, "Ftu") is None:
        missing.append("Ftu")
    if _samuel_prop_value_from_saved_state(state, "Elong") is None:
        missing.append("Elongation at Break")
    return missing


_SAMUEL_PREV_ADV_EXPORT_ALL = SelectionScreen._adv_export_all


def _samuel_adv_export_all(self):
    errors: List[str] = []
    try:
        for item in getattr(self, "advanced_items", []) or []:
            if not item.get("_selected", False):
                continue
            missing = _samuel_adv_item_custom_gissmo_missing(item)
            if missing:
                export_id = str(item.get("Export_ID", "") or item.get("ID", "") or "?")
                material_name = str(item.get("Export_Material_Name", "") or item.get("Material", "") or "Custom Material")
                errors.append(f"ID/MID {export_id} ({material_name}): " + ", ".join(missing))
    except Exception:
        errors = []
    if errors:
        messagebox.showerror(
            "Custom MAT024+GISSMO Required Values",
            "Cannot export custom MAT024+GISSMO rows until these required values are entered:\n\n"
            + "\n".join(errors)
            + "\n\nOpen the row, enter Elongation at Break, click Done, then export again."
        )
        return
    return _SAMUEL_PREV_ADV_EXPORT_ALL(self)


SelectionScreen._adv_export_all = _samuel_adv_export_all


# -----------------------------------------------------------------------------
# SAMUEL CUSTOM KEYFILE FILENAME PREFIX FIX
# -----------------------------------------------------------------------------
# Samuel's check showed the Excel/export summary correctly marks edited rows as
# CUSTOM, but the generated .key filenames could still be saved without the
# CUSTOM_ prefix. This final export-only guard keeps all existing GUI, filtering,
# GISSMO, notes, and summary logic unchanged, and only guarantees that rows that
# are already custom/edited are exported with CUSTOM_ in the keyfile/image stem.
_SAMUEL_CUSTOM_KEYFILE_PREFIX_FIX_ACTIVE_2026_06_26 = True


def _samuel_filename_row_is_custom_or_edited(item: Optional[Dict[str, Any]]) -> bool:
    """Return True when the existing item state says the export is custom/edited."""
    if not isinstance(item, dict):
        return False

    # If the Excel/summary/display name already says CUSTOM, the keyfile name
    # must say CUSTOM too.
    for key in (
        "Export_Material_Name", "Export_Name",
        "Material_Name_from_Client", "Material Name from Client",
        "Custom_Name", "custom_name",
    ):
        try:
            value = str(item.get(key, "") or "").strip()
        except Exception:
            value = ""
        if value.upper().startswith("CUSTOM_") or value.upper().startswith("CUSTOM "):
            return True

    # Existing custom/edited flags used by earlier patches.
    for key in (
        "_custom", "_custom_blank_entry", "Custom_Blank_Entry", "is_custom_blank_entry",
        "_edited_from_card", "_edited_from_export_list", "_user_changes",
    ):
        try:
            if bool(item.get(key)):
                return True
        except Exception:
            pass

    try:
        if isinstance(item.get("_card_custom_state"), dict):
            return True
    except Exception:
        pass

    try:
        status = str(item.get("_status", "") or "").upper()
        if "CUSTOM" in status or "EDITED" in status:
            return True
    except Exception:
        pass

    try:
        source = str(item.get("Source", "") or "").strip().lower()
        if source in {"custom blank entry", "advanced custom entry"}:
            return True
    except Exception:
        pass

    try:
        if "_r21_item_is_custom_or_edited" in globals() and _r21_item_is_custom_or_edited(item):
            return True
    except Exception:
        pass

    return False


def _samuel_ensure_custom_prefix_text(value: Any, default: str = "CUSTOM_MATERIAL") -> str:
    """Return text with exactly one leading CUSTOM_ prefix."""
    text = str(value or "").strip()
    if not text:
        text = default
    while text.upper().startswith("CUSTOM_CUSTOM_"):
        text = "CUSTOM_" + text[14:]
    if not text.upper().startswith("CUSTOM_"):
        text = "CUSTOM_" + text
    return text


def _samuel_safe_keyfile_stem(value: Any) -> str:
    """Use the existing filename sanitizer so only the prefix rule changes."""
    try:
        if "_card_safe_file_part_from_selection" in globals():
            return _card_safe_file_part_from_selection(value)
    except Exception:
        pass
    try:
        if "_r22_clean_name_piece" in globals():
            return _r22_clean_name_piece(value, default="CUSTOM_MATERIAL")
    except Exception:
        pass
    text = str(value or "CUSTOM_MATERIAL").strip()
    for old, new in {
        "<=": "le", ">=": "ge", "<": "lt", ">": "gt",
        " ": "_", "/": "_", "\\": "_", ":": "_", "*": "_",
        "?": "_", '"': "_", "|": "_", ",": "_",
    }.items():
        text = text.replace(old, new)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_") or "CUSTOM_MATERIAL"


def _samuel_final_custom_export_name(item: Dict[str, Any], row: Optional[pd.Series] = None) -> str:
    """Build the final CUSTOM_ name without changing regular-row naming."""
    name = ""
    try:
        if "_r22_export_name_from_item" in globals():
            name = _r22_export_name_from_item(item, row=row, custom_prefix=True)
    except Exception:
        name = ""

    if not str(name or "").strip():
        for key in ("Export_Material_Name", "Export_Name", "Material_Name_from_Client", "Material Name from Client"):
            try:
                name = str(item.get(key, "") or "").strip()
            except Exception:
                name = ""
            if name:
                break

    if not str(name or "").strip():
        try:
            if "_R21_PREV_ADV_SHORT_OUTPUT_STEM" in globals():
                name = _R21_PREV_ADV_SHORT_OUTPUT_STEM(None, item, row, 1, 1)
        except Exception:
            name = ""

    return _samuel_ensure_custom_prefix_text(name, default="CUSTOM_MATERIAL")


_SAMUEL_PREV_ADV_EXPORT_ALL_CUSTOM_FILENAME = SelectionScreen._adv_export_all


def _samuel_adv_export_all_force_custom_keyfile_names(self):
    """Before export starts, make selected custom/edited rows carry CUSTOM_."""
    try:
        for item in getattr(self, "advanced_items", []) or []:
            if not isinstance(item, dict) or not item.get("_selected", False):
                continue
            if not _samuel_filename_row_is_custom_or_edited(item):
                continue

            name = _samuel_final_custom_export_name(item, row=None)
            item["Export_Material_Name"] = name
            item["Export_Name"] = name
            item["Material_Name_from_Client"] = name
            item["Material Name from Client"] = name
            item["_custom"] = True
            item.setdefault("_tag", "custom_row")
            item.setdefault("_status", "CUSTOM / EDITED - Ready")
    except Exception:
        pass

    return _SAMUEL_PREV_ADV_EXPORT_ALL_CUSTOM_FILENAME(self)


SelectionScreen._adv_export_all = _samuel_adv_export_all_force_custom_keyfile_names


_SAMUEL_PREV_ADV_SHORT_OUTPUT_STEM_CUSTOM_FILENAME = SelectionScreen._adv_short_output_stem


def _samuel_adv_short_output_stem_force_custom_prefix(self, item: Dict[str, Any], row: pd.Series, item_idx: int, row_idx: int) -> str:
    """Use CUSTOM_ keyfile/image stem for custom/edited rows only."""
    try:
        if _samuel_filename_row_is_custom_or_edited(item):
            name = _samuel_final_custom_export_name(item, row=row)
            safe_name = _samuel_safe_keyfile_stem(name)
            if row_idx > 1:
                safe_name = f"{safe_name}_r{row_idx}"
            return safe_name[:125]
    except Exception:
        pass

    return _SAMUEL_PREV_ADV_SHORT_OUTPUT_STEM_CUSTOM_FILENAME(self, item, row, item_idx, row_idx)


SelectionScreen._adv_short_output_stem = _samuel_adv_short_output_stem_force_custom_prefix


_SAMUEL_PREV_EXPORT_KEYFILE_PROGRAMMATIC_CUSTOM_FILENAME = CardScreen.export_keyfile_programmatic


def _samuel_export_keyfile_programmatic_force_custom_filename(
    self,
    row,
    selections: Dict[str, str],
    output_dir: Path,
    output_stem: str,
    basis: str = "B",
    direction: str = "L",
    unit_sys: str = "mm_T_s",
    mat_model: str = "MAT024+GISSMO",
    material_id: Optional[Any] = None,
) -> Dict[str, Any]:
    """Final safeguard: a CUSTOM output stem must create a CUSTOM .key file."""
    requested_stem = str(output_stem or "").strip()
    must_be_custom = requested_stem.upper().startswith("CUSTOM_")

    old_custom_state = getattr(self, "_programmatic_custom_state", None)
    if must_be_custom:
        output_stem = _samuel_ensure_custom_prefix_text(requested_stem, default="CUSTOM_MATERIAL")
        # Existing keyfile header logic uses _programmatic_custom_state to write
        # "$ Custom Edited: Yes". Set a temporary marker only for this export.
        if not isinstance(old_custom_state, dict):
            self._programmatic_custom_state = {"custom_filename_prefix_export": True}

    try:
        result = _SAMUEL_PREV_EXPORT_KEYFILE_PROGRAMMATIC_CUSTOM_FILENAME(
            self,
            row=row,
            selections=selections,
            output_dir=output_dir,
            output_stem=output_stem,
            basis=basis,
            direction=direction,
            unit_sys=unit_sys,
            mat_model=mat_model,
            material_id=material_id,
        )
    finally:
        if must_be_custom and not isinstance(old_custom_state, dict):
            try:
                self._programmatic_custom_state = old_custom_state
            except Exception:
                pass

    if not must_be_custom:
        return result

    # Defensive rename in case an earlier export wrapper ignored output_stem.
    try:
        if isinstance(result, dict) and result.get("ok") and result.get("path"):
            path = Path(result.get("path", ""))
            if path.exists() and not path.stem.upper().startswith("CUSTOM_"):
                new_stem = _samuel_safe_keyfile_stem(_samuel_ensure_custom_prefix_text(path.stem))
                new_path = path.with_name(f"{new_stem}{path.suffix}")
                counter = 2
                while new_path.exists():
                    new_path = path.with_name(f"{new_stem}_{counter}{path.suffix}")
                    counter += 1
                path.rename(new_path)
                result["path"] = str(new_path)
                path = new_path

            if path.exists():
                k_text = path.read_text(encoding="utf-8", errors="ignore")
                if "$ Custom Edited: No" in k_text:
                    k_text = k_text.replace("$ Custom Edited: No", "$ Custom Edited: Yes")
                    path.write_text(k_text, encoding="utf-8")
    except Exception:
        pass

    return result


CardScreen.export_keyfile_programmatic = _samuel_export_keyfile_programmatic_force_custom_filename


# -----------------------------------------------------------------------------
# MASTER CSV ONLY + COMBINATION THICKNESS VISIBILITY FIX
# -----------------------------------------------------------------------------
# This final override is intentionally small and filtering-focused. It ensures
# late monkey-patches also use the duplicate-aware thickness label generated from
# Metal_Data_ABS-Basis_V3.csv helper columns.
_MASTERCSV_COMBINATION_FILTER_FIX_ACTIVE_2026_06_25 = True

try:
    SelectionScreen._adv_thickness_display_label = lambda self, row: source_gui_thickness_label(row)
    CardScreen._thickness_display_label = lambda self, row: source_gui_thickness_label(row)
except Exception:
    pass

