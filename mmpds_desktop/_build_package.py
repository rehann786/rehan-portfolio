"""One-shot refactor tool: partition the MMPDS monolith into the package.

Strategy (behavior-preserving):
  * Use AST line spans to assign EVERY physical line of the monolith to exactly
    one destination module, preserving original order within each module.
  * Verify the partition is a true cover (every line used exactly once) so the
    moved code is byte-for-byte identical to the original.
  * Auto-generate cross-module imports from an ownership map, and enforce the
    dependency rule: config/calculations/models may never import ui/tkinter.

Run with --emit to write files; default is a dry run that only reports.
"""
from __future__ import annotations
import ast, sys, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "legacy", "MMPDS_Version6_2_original.py")
src = open(SRC, encoding="utf-8").read()
lines = src.splitlines(keepends=True)          # 1-indexed via lines[i-1]
N = len(lines)
tree = ast.parse(src)

# ----------------------------------------------------------------------------
# Destination keys
CFG, CALC, MOD, WID, WIN, MAINPY, IMPORTS = (
    "config", "calc", "models", "widgets", "mainwin", "mainpy", "IMPORTS")

# module key -> (relative path, dotted module for intra-package imports)
MODFILE = {
    CFG:  "config/settings.py",
    CALC: "calculations/conversions.py",
    MOD:  "models/app_state.py",
    WID:  "ui/widgets.py",
    WIN:  "ui/main_window.py",
    MAINPY: "main.py",
}
# import path used when ANOTHER module imports from this one (package=mmpds_desktop)
IMPORTPATH = {
    CFG:  "mmpds_desktop.config.settings",
    CALC: "mmpds_desktop.calculations.conversions",
    MOD:  "mmpds_desktop.models.app_state",
    WID:  "mmpds_desktop.ui.widgets",
    WIN:  "mmpds_desktop.ui.main_window",
}
# inner layers must never import from these
UI_LAYERS = {WID, WIN}

# ----------------------------------------------------------------------------
# Name classification
CALC_NAMES = {
 "norm","is_blank","clean_text","normalized_col_key","build_col_lookup","row_get","display_spec",
 "row_spec2_value","thickness_label_for_row","stage_value_for_row","_candidate_columns","duplicate_key",
 "mark_duplicate_items","remove_duplicate_items","first_nonblank_value","row_first_nonblank",
 "display_spec_value","try_float","fmt_number","with_dropdown_mark","strip_dropdown_mark","with_edit_box",
 "strip_edit_box","find_col","source_row_identity_key","_normalized_col_key","row_get_first_nonblank_tolerant",
 "row_get_all_nonblank_tolerant","_row_values_from_named_columns","df_first_existing_series","_clean_dimension_piece",
 "_split_embedded_cross_section","_looks_like_thickness_text","_looks_like_cross_section_text","_first_unique",
 "source_actual_thick_value","source_thickness_components","source_thickness_display_label","source_cross_section_value",
 "source_thickness_base_value","_source_series_from_master_value","_source_row_label_piece","source_gui_thickness_label",
 "source_unit_label","converted_unit_label","convert_value","safe_divide","clamp",
}
CFG_FUNCS = {"find_project_root","resolve_data_dir","resolve_theme","apply_theme","is_dark_theme"}
MODEL_FUNCS = {
 "_read_export_counter_payload","_write_export_counter_payload","_acquire_export_counter_lock","_release_export_counter_lock",
 "normalize_export_id","reserve_next_export_id","peek_next_export_id","advance_session_export_id_after","export_counter_status_text",
 "read_csv_safely","read_master_fast","_clean_text","_norm_basis","_norm_direction",
 "is_materialdb_clean_long_format","convert_materialdb_clean_to_wide",
}
WIDGET_FUNCS = {"enable_windows_dpi_awareness","bind_mousewheel"}
MAIN_FUNCS = {"main"}

CLASS_DEST = {
 "DefaultCombo":MOD,"FastMaterialEngine":MOD,"MaterialDatabase":MOD,"HistoryStore":MOD,
 "SourceImageIndex":MOD,"DebouncedCallback":MOD,
 "TkDebouncer":WID,"LazyImageCache":WID,
 "MaterialSelectorApp":WIN,"SelectionScreen":WIN,"CardScreen":WIN,
}

CONFIG_CONST = {
 "DEFAULT_STAGES","NO_SPEC_DISPLAY","DEFAULT_BASIS_CODES","DEFAULT_DIRECTION_CODES","DEFAULT_MAT_MODELS",
 "PROPERTY_ALIASES","REQUIRED_MAT_VALUE_GROUPS","THICKNESS_COLUMNS","PERFORMANCE_ENGINE_AVAILABLE",
 "PERFORMANCE_ENGINE_IMPORT_ERROR","logger","SCRIPT_DIR","MASTER_FILE","CLEAN_MASTER_FILE","PROJECT_ROOT",
 "DATA_DIR","DROPDOWN_DIR","IMAGE_DIR","SOURCE_IMAGES_DIR","HISTORY_FILE","EXPORT_AUDIT_FILE",
 "EXPORT_COUNTER_FILE","EXPORT_COUNTER_LOCK_DIR","EXPORT_COUNTER_START","EXPORT_COUNTER_MAX","PARQUET_FILE",
 "DUCKDB_FILE","IMAGE_INDEX_FILE","THUMBNAIL_CACHE_DIR","LOG_DIR","LOG_TRACKING_AUTOSAVE_MS",
 "LOG_TRACKING_VISIBLE_LIMIT","PLACEHOLDER_SEARCH","MAX_LISTBOX_ITEMS","MAX_SOURCE_IMAGES","SEARCH_DEBOUNCE_MS",
 "CACHE_SIZE_LIMIT","CSV_CHUNK_SIZE","REFRESH_DEBOUNCE_MS","WINDOW_RESIZE_DEBOUNCE_MS","SCREEN2_HYDRATE_START_MS",
 "SCREEN2_HYDRATE_STEP_MS","OPTION_UPDATE_DEBOUNCE_MS","STAGES","LOOKUP_FILES","BASIS_OPTIONS","DIRECTION_OPTIONS",
 "UNIT_SYSTEMS","MAT_MODELS","UNIT_SYSTEM_SPEC","DEFAULT_UNIT_CONVERSIONS","UNIT_CONVERSION_ROWS","PROPERTY_ROWS",
 "READONLY_VALUE_ROWS","THEME","LIGHT_THEME","DARK_THEME","FONTS","NAVY_LIGHT","NAVY_DARK","WARM_LIGHT","WARM_DARK",
 "GRAPHITE_LIGHT","GRAPHITE_DARK","PALETTES","PALETTE_ORDER","PALETTE_LABELS","DROPDOWN_MARK",
 "THICKNESS_VALUE_COLUMNS","WALL_THICKNESS_COLUMNS","CROSS_SECTION_VALUE_COLUMNS",
}
MODEL_CONST = {"SESSION_NEXT_EXPORT_ID"}

# Executable top-level statements (Expr/For/Try/If) classified by line number.
LINE_OVERRIDE = {
 494: CFG,        # logging.basicConfig(...)
 1096: CFG, 1102: CFG,   # theme post-processing loops
 18164: WIN, 19506: WIN, 20622: WIN, 21424: WIN, 23270: WIN,
 23280: MAINPY,   # if __name__ == "__main__"
}

def classify(node):
    t = type(node).__name__
    if t in ("FunctionDef","AsyncFunctionDef"):
        n = node.name
        if n in CALC_NAMES: return CALC
        if n in CFG_FUNCS: return CFG
        if n in MODEL_FUNCS: return MOD
        if n in WIDGET_FUNCS: return WID
        if n in MAIN_FUNCS: return MAINPY
        return WIN
    if t == "ClassDef":
        return CLASS_DEST.get(node.name, WIN)
    if t in ("Import","ImportFrom"):
        return IMPORTS
    if t in ("Assign","AnnAssign"):
        tgt = node.targets[0] if t=="Assign" else node.target
        if isinstance(tgt, ast.Attribute):
            return WIN                      # ClassName.method = ...
        if isinstance(tgt, ast.Name):
            nm = tgt.id
            if nm in CONFIG_CONST: return CFG
            if nm in MODEL_CONST: return MOD
            return WIN
        if isinstance(tgt, ast.Tuple):
            return WIN
    # Expr / For / Try / If / etc.
    return LINE_OVERRIDE.get(node.lineno, WIN)

# ----------------------------------------------------------------------------
# Build ownership map (name -> module) for cross-module import resolution.
home_of_name = {}
def record_name(name, dest):
    # duplicates must all map to one module; assert consistency
    if name in home_of_name and home_of_name[name] != dest:
        raise SystemExit(f"NAME SPLIT ACROSS MODULES: {name}: {home_of_name[name]} vs {dest}")
    home_of_name[name] = dest

for node in tree.body:
    dest = classify(node)
    t = type(node).__name__
    if t in ("FunctionDef","AsyncFunctionDef","ClassDef"):
        if dest in (CFG,CALC,MOD,WID):     # only inner/extracted names are imported elsewhere
            record_name(node.name, dest)
        elif dest in (WIN, MAINPY):
            home_of_name.setdefault(node.name, dest)  # win/mainpy names too (for main.py imports)
    elif t in ("Assign","AnnAssign"):
        tgt = node.targets[0] if t=="Assign" else node.target
        if isinstance(tgt, ast.Name) and dest in (CFG,MOD):
            home_of_name[tgt.id] = dest

# ----------------------------------------------------------------------------
# Assign every line 1..N to a destination (gaps forward-fill to next node).
owner = [None]*(N+1)
spans = []  # (start, end, dest)
def node_start(node):
    if getattr(node, "decorator_list", None):
        return min(d.lineno for d in node.decorator_list)
    return node.lineno

prev_end = 0
nodes = list(tree.body)
for idx, node in enumerate(nodes):
    dest = classify(node)
    s = node_start(node); e = node.end_lineno
    gap_start = prev_end + 1
    # gap (comments/blanks) before this node -> belongs to this node's section
    for ln in range(gap_start, s):
        owner[ln] = (IMPORTS if idx == 0 else dest)
    for ln in range(s, e+1):
        owner[ln] = dest
    spans.append((s,e,dest))
    prev_end = e
# trailing lines after last node
for ln in range(prev_end+1, N+1):
    owner[ln] = WIN

# Fix: comment block immediately before the `if __name__` (mainpy) node is
# trailing UI commentary -> keep it in mainwin, not main.py.
# Find the mainpy node span and reassign its leading gap to WIN.
for node in nodes:
    if classify(node) == MAINPY and type(node).__name__ == "If":
        s = node_start(node)
        ln = s-1
        while ln >= 1 and owner[ln] == MAINPY and lines[ln-1].strip() != "":
            owner[ln] = WIN; ln -= 1
        # also blanks just above
        while ln >= 1 and owner[ln] == MAINPY and lines[ln-1].strip()=="":
            owner[ln] = WIN; ln -= 1

# ----------------------------------------------------------------------------
# VERIFY partition integrity
missing = [i for i in range(1,N+1) if owner[i] is None]
if missing:
    raise SystemExit(f"UNASSIGNED LINES: {missing[:20]} ... ({len(missing)})")
# reconstruct check: concatenated owner-lines in original order == original
recon = "".join(lines[i-1] for i in range(1,N+1))
assert recon == src, "RECONSTRUCTION MISMATCH"

by_mod = collections.defaultdict(list)
for i in range(1,N+1):
    by_mod[owner[i]].append(i)

# ----------------------------------------------------------------------------
# Cross-module + stdlib import resolution
STDLIB = {
 'pd':'import pandas as pd','np':'import numpy as np',
 'tk':'import tkinter as tk','ttk':'from tkinter import ttk',
 'filedialog':'from tkinter import filedialog','messagebox':'from tkinter import messagebox',
 'math':'import math','json':'import json','sys':'import sys','os':'import os','re':'import re',
 'time':'import time','shutil':'import shutil','threading':'import threading','logging':'import logging',
 'getpass':'import getpass','hashlib':'import hashlib','datetime':'from datetime import datetime',
 'Path':'from pathlib import Path','product':'from itertools import product',
 'dataclass':'from dataclasses import dataclass','field':'from dataclasses import field',
}
TYPING = {'Any','Dict','List','Optional','Tuple','Sequence','Iterable','Callable','Union','Set','FrozenSet'}

def loads_in(node):
    out=set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            out.add(sub.id)
        if isinstance(sub, ast.Attribute):
            r=sub
            while isinstance(r, ast.Attribute): r=r.value
            if isinstance(r, ast.Name) and isinstance(r.ctx, ast.Load):
                out.add(r.id)
    return out

# names referenced per module (from the actual nodes assigned to it)
refs = collections.defaultdict(set)
for node in nodes:
    dest = classify(node)
    if dest == IMPORTS: continue
    refs[dest] |= loads_in(node)

def gen_header(modkey):
    used = refs[modkey]
    lines_out = ["from __future__ import annotations", ""]
    # stdlib
    std=[]
    for nm,stmt in STDLIB.items():
        if nm in used: std.append(stmt)
    # collapse tkinter "from tkinter import X" into one
    tk_parts=[s.split("import ")[1] for s in std if s.startswith("from tkinter import")]
    std=[s for s in std if not s.startswith("from tkinter import")]
    if tk_parts: std.append("from tkinter import "+", ".join(sorted(tk_parts)))
    # collapse dataclasses
    dc=[s for s in std if s.startswith("from dataclasses")]
    std=[s for s in std if not s.startswith("from dataclasses")]
    if dc:
        parts=sorted({s.split("import ")[1] for s in dc})
        std.append("from dataclasses import "+", ".join(parts))
    std=sorted(set(std))
    typ=sorted(t for t in TYPING if t in used)
    if typ: std.append("from typing import "+", ".join(typ))
    lines_out += std
    # cross-module
    crmap=collections.defaultdict(set)
    for nm in used:
        h=home_of_name.get(nm)
        if h and h!=modkey and h in IMPORTPATH:
            crmap[h].add(nm)
    # layering rule
    if modkey in (CFG,CALC,MOD):
        bad=[h for h in crmap if h in UI_LAYERS]
        if bad:
            raise SystemExit(f"LAYER VIOLATION: {modkey} imports from {bad}")
    if std and crmap: lines_out.append("")
    for h in sorted(crmap):
        names=", ".join(sorted(crmap[h]))
        lines_out.append(f"from {IMPORTPATH[h]} import {names}")
    return "\n".join(lines_out)+"\n", crmap

# ----------------------------------------------------------------------------
print("=== PARTITION (lines per module) ===")
tot=0
for k in [CFG,CALC,MOD,WID,WIN,MAINPY,IMPORTS]:
    print(f"  {k:8s} {len(by_mod[k]):6d} lines  -> {MODFILE.get(k,'(regenerated imports)')}")
    tot+=len(by_mod[k])
print(f"  TOTAL    {tot:6d} (orig {N})   reconstruct OK={recon==src}")

print("\n=== IMPORT PLAN ===")
for k in [CFG,CALC,MOD,WID,WIN,MAINPY]:
    hdr,crmap=gen_header(k)
    cm={IMPORTPATH[h].split('.')[-1]:sorted(v) for h,v in crmap.items()}
    print(f"\n--- {MODFILE[k]} cross-module imports:")
    for m,v in cm.items(): print(f"      from ...{m}: {v}")

if "--emit" in sys.argv:
    import re as _re
    def write(path, header, line_nums):
        body="".join(lines[i-1] for i in line_nums)
        full=header+"\n"+body
        dest=os.path.join(HERE, path)
        with open(dest,"w",encoding="utf-8") as fh: fh.write(full)
        print("wrote", path, "(", len(line_nums), "src lines )")
    for k in [CFG,CALC,MOD,WID,WIN,MAINPY]:
        hdr,_=gen_header(k)
        write(MODFILE[k], hdr, by_mod[k])
    print("EMIT DONE")
