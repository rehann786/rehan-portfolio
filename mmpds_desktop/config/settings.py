from __future__ import annotations

from pathlib import Path
import logging
from typing import Any, Dict




DEFAULT_STAGES = ["Element", "Series", "Material", "Temper", "Specification", "Specification 2", "Form"]
NO_SPEC_DISPLAY = "(No Specification)"
DEFAULT_BASIS_CODES = ["A", "B", "S"]
DEFAULT_DIRECTION_CODES = ["L", "LT"]
DEFAULT_MAT_MODELS = ["MAT024", "MAT082", "MAT224", "MAT024+GISSMO"]

PROPERTY_ALIASES = (
    "Tensile_Str", "UltTensileStrength", "UltimateTensileStrength", "Ftu",
    "Tensile_Yield", "TensileYield", "Fty",
    "Compress_Yield", "CompressionYield", "Fcy",
    "Shear_Str", "UltShearStrength", "Fsu",
    "Elong", "ElongAtBreak", "Elongation",
    "Youngs_Mod", "YoungsModulus", "E",
    "Youngs_Mod_Comp", "YoungsModulusComp", "Ec",
    "Shear_Mod", "ShearModulus", "G",
    "Poissons_Ratio", "PoissonsRatio", "PR",
    "Density", "RO",
)

REQUIRED_MAT_VALUE_GROUPS = {
    "SIGY": ("Tensile_Yield", "TensileYield", "Fty"),
    "E": ("Youngs_Mod", "YoungsModulus", "E"),
    "PR": ("Poissons_Ratio", "PoissonsRatio", "PR"),
    "RO": ("Density", "RO"),
}

THICKNESS_COLUMNS = (
    "__adv_thickness_label", "Thick_Value", "Thick Value", "ThickValue",
    "Thickness_Value", "Thickness Value", "ThicknessOrDia", "Thickness Or Dia",
    "ThicknessOrDiameter", "Thickness Or Diameter", "Thickness/Dia", "Thickness / Dia",
    "Thickness Range", "Thickness_Range", "Thick_Range", "ThicknessRange",
    "Thickness", "Thick", "Thick.", "Dia", "Diameter",
)

PERFORMANCE_ENGINE_AVAILABLE = True
PERFORMANCE_ENGINE_IMPORT_ERROR = None


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# NOTE (packaging): this module lives in mmpds_desktop/config/, so __file__'s
# parent is .../config. The original single-file script used its own directory
# as the app home (the folder that holds Data/, selection_history.json and the
# export-counter files). That home is now the package root mmpds_desktop/, so we
# anchor to parent.parent to keep every derived path (PROJECT_ROOT, DATA_DIR,
# HISTORY_FILE, EXPORT_COUNTER_FILE, ...) resolving exactly as before at runtime.
SCRIPT_DIR = Path(__file__).resolve().parent.parent


MASTER_FILE = "Metal_Data_ABS-Basis_V3.csv"
CLEAN_MASTER_FILE = "MaterialDB_clean_ALL.csv"


def find_project_root(start: Path) -> Path:
    """Find the project root using only the approved master CSV.

    Manager requirement for this version:
    - Use Data/Metal_Data_ABS-Basis_V3.csv as the only material database.
    - Do not fall back to MaterialDB_clean_ALL.csv, because that can make the
      GUI show materials/thicknesses that are not in the approved master file.
    """
    for folder in [start] + list(start.parents):
        if (folder / "Data" / MASTER_FILE).exists():
            return folder
        if (folder / MASTER_FILE).exists():
            return folder
    return start.parent


def resolve_data_dir(project_root: Path) -> Path:
    """Resolve Data folder using only Metal_Data_ABS-Basis_V3.csv."""
    data_folder = project_root / "Data"
    if (data_folder / MASTER_FILE).exists():
        return data_folder
    if (project_root / MASTER_FILE).exists():
        return project_root
    return data_folder


PROJECT_ROOT = find_project_root(SCRIPT_DIR)
DATA_DIR = resolve_data_dir(PROJECT_ROOT)
DROPDOWN_DIR = DATA_DIR / "Dropdown"
IMAGE_DIR = DATA_DIR / "Images"
SOURCE_IMAGES_DIR = Path(r"J:\AVETDigital\01_MaterialDB\01_Metals\01_Data\03_Generated_Files\03_Extracted_Images")
HISTORY_FILE = SCRIPT_DIR / "selection_history.json"
EXPORT_AUDIT_FILE = SCRIPT_DIR / "export_log_audit.json"


EXPORT_COUNTER_FILE = SCRIPT_DIR / "export_counter.json"
EXPORT_COUNTER_LOCK_DIR = SCRIPT_DIR / "export_counter.lock"
EXPORT_COUNTER_START = 1000
EXPORT_COUNTER_MAX = 999_999_999

PARQUET_FILE = DATA_DIR / "Metal_Data_ABS-Basis_V3.parquet"
DUCKDB_FILE = DATA_DIR / "mmpds_material_image_index.duckdb"
IMAGE_INDEX_FILE = DATA_DIR / "source_image_index.json"
THUMBNAIL_CACHE_DIR = DATA_DIR / "ImageThumbCache"
LOG_DIR = PROJECT_ROOT / "Logs"
LOG_TRACKING_AUTOSAVE_MS = 3000
LOG_TRACKING_VISIBLE_LIMIT = 500

NO_SPEC_DISPLAY = "(No Specification)"
PLACEHOLDER_SEARCH = "Search..."


MAX_LISTBOX_ITEMS = 250
MAX_SOURCE_IMAGES = 4
SEARCH_DEBOUNCE_MS = 300
CACHE_SIZE_LIMIT = 5000
CSV_CHUNK_SIZE = 10000
REFRESH_DEBOUNCE_MS = 150
WINDOW_RESIZE_DEBOUNCE_MS = 260
SCREEN2_HYDRATE_START_MS = 40
SCREEN2_HYDRATE_STEP_MS = 70
OPTION_UPDATE_DEBOUNCE_MS = 120


STAGES = ["Element", "Series", "Material", "Temper", "Specification", "Specification 2", "Form"]

LOOKUP_FILES = {
    "element": ["element"],
    "series": ["series"],
    "material": ["material"],
    "tempers": ["tempers", "temper"],
    "specs": ["specifications", "specification", "specs", "spec"],
    "form": ["form"],
}

BASIS_OPTIONS = [
    ("A Basis", "A"),
    ("B Basis", "B"),
    ("S Basis", "S"),
]

DIRECTION_OPTIONS = [
    ("L", "L"),
    ("LT", "LT"),
]

UNIT_SYSTEMS = [
    ("mm, Tonne, sec", "mm_T_s"),
    ("m, Kg, sec", "m_Kg_s"),
    ("mm, Kg, msec", "mm_Kg_ms"),
]

MAT_MODELS = [
    ("MAT024", "MAT024"),
    ("MAT082", "MAT082"),
    ("MAT224", "MAT224"),
    ("MAT024+GISSMO", "MAT024+GISSMO"),
]

UNIT_SYSTEM_SPEC = {
    "mm_T_s": {
        "label": "mm, Tonne, sec",
        "pressure_label": "MPa",
        "pressure_factor": 6.894757,
        "modulus_factor": 6894.757,
        "density_label": "ton/mm^3",
        "density_factor": 2.76799e-8,
    },
    "m_Kg_s": {
        "label": "m, Kg, sec",
        "pressure_label": "Pa",
        "pressure_factor": 6.894757e6,
        "modulus_factor": 6.894757e9,
        "density_label": "kg/m^3",
        "density_factor": 27679.9,
    },
    "mm_Kg_ms": {
        "label": "mm, Kg, msec",
        "pressure_label": "GPa",
        "pressure_factor": 6.894757e-3,
        "modulus_factor": 6.894757,
        "density_label": "kg/mm^3",
        "density_factor": 2.76799e-5,
    },
}


DEFAULT_UNIT_CONVERSIONS = {
    "mm_T_s_pressure": 6.894757,
    "mm_T_s_density": 2.76799e-8,
    "m_Kg_s_pressure": 6.894757e6,
    "m_Kg_s_density": 27679.9,
    "mm_Kg_ms_pressure": 6.894757e-3,
    "mm_Kg_ms_density": 2.76799e-5,


    "mpa_to_ksi": 0.1450377377,
}

UNIT_CONVERSION_ROWS = [
    ("mm_T_s_pressure", "mm, tonne, sec", "Unit Conversion Factor (Pressure)", "ksi", "MPa"),
    ("mm_T_s_density", "mm, tonne, sec", "Unit Conversion Factor (Density)", "lb/in^3", "ton/mm^3"),
    ("m_Kg_s_pressure", "M, Kg, sec", "Unit Conversion Factor (Pressure)", "ksi", "Pa"),
    ("m_Kg_s_density", "M, Kg, sec", "Unit Conversion Factor (Density)", "lb/in^3", "kg/m^3"),
    ("mm_Kg_ms_pressure", "mm, kg, msec", "Unit Conversion Factor (Pressure)", "ksi", "GPa"),
    ("mm_Kg_ms_density", "mm, kg, msec", "Unit Conversion Factor (Density)", "lb/in^3", "kg/mm^3"),
]

PROPERTY_ROWS = [
    ("Ftu", "Ult. Tensile Strength: Ftu", "pressure", "Tensile_Str_L", "Tensile_Str_LT"),
    ("Fty", "Tensile Yield: Fty", "pressure", "Tensile_Yield_L", "Tensile_Yield_LT"),
    ("Fcy", "Compression Yield: Fcy", "pressure", "Compress_Yield_L", "Compress_Yield_LT"),
    ("Fsu", "Ult. Shear Strength: Fsu", "pressure", "Shear_Str_L", "Shear_Str_LT"),
    ("Elong", "Elong. at Break, Table", "percent", "Elong_L", "Elong_LT"),
    ("E", "Young's Modulus: E", "modulus", "Youngs_Mod_L", "Youngs_Mod_LT"),
    ("Ec", "Young's Modulus Comp.: E", "modulus", "Youngs_Mod_Comp_L", "Youngs_Mod_Comp_LT"),
    ("G", "Shear Modulus: G", "modulus", "Shear_Mod", "Shear_Mod"),
    ("PR", "Poisson's Ratio", "ratio", "Poissons_Ratio", "Poissons_Ratio"),
    ("RO", "Density", "density", "Density", "Density"),
    ("Etan", "Tangent Modulus: Etan", "modulus", None, None),
    ("Compression", "Compression", "percent", None, None),
]

READONLY_VALUE_ROWS = {"Etan", "Compression"}


THEME = {

    "bg": "#F3F6FA",
    "panel": "#FFFFFF",
    "panel_alt": "#F8FAFC",
    "panel_elevated": "#EEF2F7",
    "border": "#D6DEE8",


    "text": "#111827",
    "text_muted": "#64748B",
    "text_subtle": "#94A3B8",


    "accent": "#1F3A5F",
    "accent_hover": "#2A4E7E",
    "accent_text": "#FFFFFF",


    "select_bg": "#DBEAFE",
    "select_fg": "#1E3A8A",
    "focus_ring": "#3B82F6",


    "entry_bg": "#FFFFFF",
    "entry_fg": "#111827",
    "listbox_bg": "#FFFFFF",
    "listbox_fg": "#111827",


    "table_bg": "#FFFFFF",
    "table_alt_bg": "#F8FAFC",
    "table_header_bg": "#1F3A5F",
    "table_header_fg": "#FFFFFF",
    "table_fg": "#111827",
    "table_select_bg": "#DBEAFE",
    "table_select_fg": "#1E3A8A",


    "text_area_bg": "#FFFFFF",
    "text_area_fg": "#111827",


    "tab_inactive_bg": "#E9EEF5",
    "tab_active_bg": "#FFFFFF",
    "tab_inactive_fg": "#64748B",
    "tab_active_fg": "#1F3A5F",


    "edit_bg": "#FFF5CC",
    "edit_fg": "#5F4300",
    "pending_bg": "#FFF0B3",
    "pending_fg": "#7A4A00",
    "custom_history_bg": "#FFF4C2",
    "custom_history_fg": "#5F4300",
    "disabled_fg": "#9AA4B2",


    "btn_primary": "#1F3A5F",
    "btn_primary_hover": "#2A4E7E",
    "btn_secondary_bg": "#E9EEF5",
    "btn_secondary_fg": "#1F3A5F",
    "btn_secondary_hover": "#DDE4EE",
    "btn_danger": "#B42318",
    "btn_danger_hover": "#922218",
    "btn_success": "#137333",
    "btn_success_hover": "#0F5D29",
    "btn_warn": "#9A6700",


    "status_ok_fg": "#137333",
    "status_warn_fg": "#9A6700",
    "status_error_fg": "#B42318",


    "matrix_basis": "#FCE4A8",
    "matrix_orange": "#F6A96B",
    "matrix_dir": "#A8C890",
    "matrix_meta": "#CFD8DC",
    "matrix_label": "#1F3A5F",
    "matrix_label_fg": "#FFFFFF",
    "matrix_black": "#1A1A1A",
    "matrix_value": "#FAFAFA",
}

LIGHT_THEME = THEME.copy()

DARK_THEME = {

    "bg": "#111827",
    "panel": "#1F2937",
    "panel_alt": "#273449",
    "panel_elevated": "#334155",
    "border": "#374151",


    "text": "#F9FAFB",
    "text_muted": "#CBD5E1",
    "text_subtle": "#94A3B8",


    "accent": "#2563EB",
    "accent_hover": "#3B82F6",
    "accent_text": "#FFFFFF",


    "select_bg": "#2563EB",
    "select_fg": "#FFFFFF",
    "focus_ring": "#3B82F6",


    "entry_bg": "#111827",
    "entry_fg": "#F9FAFB",
    "listbox_bg": "#0F172A",
    "listbox_fg": "#F8FAFC",


    "table_bg": "#F8FAFC",
    "table_alt_bg": "#EEF2F7",
    "table_header_bg": "#1E40AF",
    "table_header_fg": "#FFFFFF",
    "table_fg": "#111827",
    "table_select_bg": "#BFDBFE",
    "table_select_fg": "#0F172A",


    "text_area_bg": "#F8FAFC",
    "text_area_fg": "#111827",


    "tab_inactive_bg": "#1F2937",
    "tab_active_bg": "#2563EB",
    "tab_inactive_fg": "#CBD5E1",
    "tab_active_fg": "#FFFFFF",


    "edit_bg": "#3A2F12",
    "edit_fg": "#FACC15",
    "pending_bg": "#4A3510",
    "pending_fg": "#FDE68A",
    "custom_history_bg": "#3A2F12",
    "custom_history_fg": "#FACC15",
    "disabled_fg": "#64748B",


    "btn_primary": "#2563EB",
    "btn_primary_hover": "#3B82F6",
    "btn_secondary_bg": "#334155",
    "btn_secondary_fg": "#F8FAFC",
    "btn_secondary_hover": "#475569",
    "btn_danger": "#DC2626",
    "btn_danger_hover": "#B91C1C",
    "btn_success": "#16A34A",
    "btn_success_hover": "#15803D",
    "btn_warn": "#FACC15",


    "status_ok_fg": "#16A34A",
    "status_warn_fg": "#D97706",
    "status_error_fg": "#DC2626",


    "matrix_basis": "#FCE4A8",
    "matrix_orange": "#F6A96B",
    "matrix_dir": "#A8C890",
    "matrix_meta": "#E2E8F0",
    "matrix_label": "#1E40AF",
    "matrix_label_fg": "#FFFFFF",
    "matrix_black": "#111827",
    "matrix_value": "#F8FAFC",
}

FONTS = {

    "display":   ("Segoe UI Semibold", 20, "bold"),
    "title":     ("Segoe UI Semibold", 16, "bold"),
    "h1":        ("Segoe UI Semibold", 13, "bold"),
    "h2":        ("Segoe UI Semibold", 11, "bold"),
    "subtitle":  ("Segoe UI", 11),
    "body":      ("Segoe UI", 10),
    "body_bold": ("Segoe UI Semibold", 10, "bold"),
    "label":     ("Segoe UI Semibold", 9, "bold"),
    "small":     ("Segoe UI", 9),
    "small_bold": ("Segoe UI Semibold", 9, "bold"),
    "caption":   ("Segoe UI", 8),
    "tiny":      ("Segoe UI", 8),
    "mono_small": ("Cascadia Code", 9),
    "mono_body":  ("Cascadia Code", 10),
}


NAVY_LIGHT = LIGHT_THEME
NAVY_DARK = DARK_THEME

WARM_LIGHT = {
    "bg": "#F7F3EE", "panel": "#FFFDFA", "panel_alt": "#F4EEE6",
    "panel_elevated": "#EDE4D8", "border": "#E0D4C4",
    "text": "#2B2018", "text_muted": "#7A6A58", "text_subtle": "#A8967F",
    "accent": "#9A4F2C", "accent_hover": "#B25E37", "accent_text": "#FFFFFF",
    "select_bg": "#F3E1C7", "select_fg": "#7A3D17", "focus_ring": "#C9772F",
    "entry_bg": "#FFFDFA", "entry_fg": "#2B2018",
    "listbox_bg": "#FFFDFA", "listbox_fg": "#2B2018",
    "table_bg": "#FFFDFA", "table_alt_bg": "#F6F0E8",
    "table_header_bg": "#7A3D17", "table_header_fg": "#FFF6EC",
    "table_fg": "#2B2018", "table_select_bg": "#F3E1C7", "table_select_fg": "#7A3D17",
    "text_area_bg": "#FFFDFA", "text_area_fg": "#2B2018",
    "tab_inactive_bg": "#EDE4D8", "tab_active_bg": "#FFFDFA",
    "tab_inactive_fg": "#7A6A58", "tab_active_fg": "#9A4F2C",
    "edit_bg": "#FBEFD2", "edit_fg": "#6B4A00",
    "pending_bg": "#F8E6B8", "pending_fg": "#7A4A00",
    "custom_history_bg": "#FBEFD2", "custom_history_fg": "#6B4A00",
    "disabled_fg": "#B5A691",
    "btn_primary": "#9A4F2C", "btn_primary_hover": "#B25E37",
    "btn_secondary_bg": "#EDE4D8", "btn_secondary_fg": "#7A3D17",
    "btn_secondary_hover": "#E2D5C4",
    "btn_danger": "#B23A2A", "btn_danger_hover": "#94301F",
    "btn_success": "#5E7B3A", "btn_success_hover": "#4C6630", "btn_warn": "#A8761B",
    "status_ok_fg": "#5E7B3A", "status_warn_fg": "#A8761B", "status_error_fg": "#B23A2A",
    "toast_info_bg": "#3A2A1C", "toast_info_fg": "#FFF6EC",
    "toast_success_bg": "#4C6630", "toast_success_fg": "#FFFFFF",
    "toast_error_bg": "#94301F", "toast_error_fg": "#FFFFFF",
    "matrix_basis": "#F3D9A0", "matrix_orange": "#E8964F", "matrix_dir": "#B7C089",
    "matrix_meta": "#E0D4C4", "matrix_label": "#7A3D17", "matrix_label_fg": "#FFF6EC",
    "matrix_black": "#2B2018", "matrix_value": "#FFFDF6",
}

WARM_DARK = {
    "bg": "#1C1611", "panel": "#2A211A", "panel_alt": "#342A20",
    "panel_elevated": "#43362A", "border": "#4A3B2C",
    "text": "#F6EFE6", "text_muted": "#CDB99F", "text_subtle": "#A8967F",
    "accent": "#D98A4E", "accent_hover": "#E89C5E", "accent_text": "#1C1611",
    "select_bg": "#7A3D17", "select_fg": "#FFF6EC", "focus_ring": "#E89C5E",
    "entry_bg": "#1C1611", "entry_fg": "#F6EFE6",
    "listbox_bg": "#17110C", "listbox_fg": "#F6EFE6",
    "table_bg": "#FBF6EF", "table_alt_bg": "#F1E8DB",
    "table_header_bg": "#8A4A1F", "table_header_fg": "#FFF6EC",
    "table_fg": "#2B2018", "table_select_bg": "#F3D9A0", "table_select_fg": "#3A2410",
    "text_area_bg": "#FBF6EF", "text_area_fg": "#2B2018",
    "tab_inactive_bg": "#2A211A", "tab_active_bg": "#D98A4E",
    "tab_inactive_fg": "#CDB99F", "tab_active_fg": "#1C1611",
    "edit_bg": "#3E2F12", "edit_fg": "#F5C84B",
    "pending_bg": "#4A3510", "pending_fg": "#FBDC8A",
    "custom_history_bg": "#3E2F12", "custom_history_fg": "#F5C84B",
    "disabled_fg": "#7A6A58",
    "btn_primary": "#D98A4E", "btn_primary_hover": "#E89C5E",
    "btn_secondary_bg": "#43362A", "btn_secondary_fg": "#F6EFE6",
    "btn_secondary_hover": "#54442F",
    "btn_danger": "#D9544A", "btn_danger_hover": "#C0433A",
    "btn_success": "#86A85A", "btn_success_hover": "#6F9047", "btn_warn": "#F5C84B",
    "status_ok_fg": "#86A85A", "status_warn_fg": "#E0A93C", "status_error_fg": "#D9544A",
    "toast_info_bg": "#43362A", "toast_info_fg": "#F6EFE6",
    "toast_success_bg": "#6F9047", "toast_success_fg": "#FFFFFF",
    "toast_error_bg": "#C0433A", "toast_error_fg": "#FFFFFF",
    "matrix_basis": "#F3D9A0", "matrix_orange": "#E8964F", "matrix_dir": "#B7C089",
    "matrix_meta": "#54442F", "matrix_label": "#8A4A1F", "matrix_label_fg": "#FFF6EC",
    "matrix_black": "#1C1611", "matrix_value": "#FBF6EF",
}


for _t, _v in {
    "toast_info_bg": "#1F3A5F", "toast_info_fg": "#FFFFFF",
    "toast_success_bg": "#137333", "toast_success_fg": "#FFFFFF",
    "toast_error_bg": "#B42318", "toast_error_fg": "#FFFFFF",
}.items():
    NAVY_LIGHT.setdefault(_t, _v)
for _t, _v in {
    "toast_info_bg": "#334155", "toast_info_fg": "#F9FAFB",
    "toast_success_bg": "#15803D", "toast_success_fg": "#FFFFFF",
    "toast_error_bg": "#B91C1C", "toast_error_fg": "#FFFFFF",
}.items():
    NAVY_DARK.setdefault(_t, _v)

GRAPHITE_LIGHT = {
    "bg": "#F4F5F2", "panel": "#FFFFFF", "panel_alt": "#F8F8F5",
    "panel_elevated": "#ECEFEB", "border": "#D8DDD6",
    "text": "#1D2320", "text_muted": "#607068", "text_subtle": "#8C9992",
    "accent": "#2F6B57", "accent_hover": "#3A7C66", "accent_text": "#FFFFFF",
    "select_bg": "#DDECE5", "select_fg": "#1F4D3E", "focus_ring": "#5B987E",
    "entry_bg": "#FFFFFF", "entry_fg": "#1D2320",
    "listbox_bg": "#FFFFFF", "listbox_fg": "#1D2320",
    "table_bg": "#FFFFFF", "table_alt_bg": "#F2F5F1",
    "table_header_bg": "#315B4F", "table_header_fg": "#FFFFFF",
    "table_fg": "#1D2320", "table_select_bg": "#DDECE5", "table_select_fg": "#1F4D3E",
    "text_area_bg": "#FFFFFF", "text_area_fg": "#1D2320",
    "tab_inactive_bg": "#E7ECE7", "tab_active_bg": "#FFFFFF",
    "tab_inactive_fg": "#607068", "tab_active_fg": "#2F6B57",
    "edit_bg": "#FFF1C7", "edit_fg": "#6C4D00",
    "pending_bg": "#FFE8A8", "pending_fg": "#7A4A00",
    "custom_history_bg": "#FFF1C7", "custom_history_fg": "#6C4D00",
    "disabled_fg": "#9AA7A0",
    "btn_primary": "#2F6B57", "btn_primary_hover": "#3A7C66",
    "btn_secondary_bg": "#E7ECE7", "btn_secondary_fg": "#315B4F",
    "btn_secondary_hover": "#DCE4DC",
    "btn_danger": "#B43B32", "btn_danger_hover": "#943127",
    "btn_success": "#3E7A4D", "btn_success_hover": "#336840", "btn_warn": "#A56F16",
    "status_ok_fg": "#2F7A45", "status_warn_fg": "#A56F16", "status_error_fg": "#B43B32",
    "toast_info_bg": "#315B4F", "toast_info_fg": "#FFFFFF",
    "toast_success_bg": "#2F7A45", "toast_success_fg": "#FFFFFF",
    "toast_error_bg": "#943127", "toast_error_fg": "#FFFFFF",
    "matrix_basis": "#F8D989", "matrix_orange": "#D88C49", "matrix_dir": "#BFD3A9",
    "matrix_meta": "#DCE4DC", "matrix_label": "#315B4F", "matrix_label_fg": "#FFFFFF",
    "matrix_black": "#1D2320", "matrix_value": "#F8F8F5",
}

GRAPHITE_DARK = {
    "bg": "#151917", "panel": "#202722", "panel_alt": "#26302A",
    "panel_elevated": "#303B34", "border": "#3A463F",
    "text": "#F0F4F1", "text_muted": "#C2CEC7", "text_subtle": "#95A49B",
    "accent": "#76A88B", "accent_hover": "#86B89A", "accent_text": "#101512",
    "select_bg": "#315B4F", "select_fg": "#F0F4F1", "focus_ring": "#86B89A",
    "entry_bg": "#151917", "entry_fg": "#F0F4F1",
    "listbox_bg": "#121613", "listbox_fg": "#F0F4F1",
    "table_bg": "#F8F8F5", "table_alt_bg": "#ECEFEB",
    "table_header_bg": "#315B4F", "table_header_fg": "#FFFFFF",
    "table_fg": "#1D2320", "table_select_bg": "#DDECE5", "table_select_fg": "#1F4D3E",
    "text_area_bg": "#F8F8F5", "text_area_fg": "#1D2320",
    "tab_inactive_bg": "#202722", "tab_active_bg": "#76A88B",
    "tab_inactive_fg": "#C2CEC7", "tab_active_fg": "#101512",
    "edit_bg": "#3A3218", "edit_fg": "#F7CC53",
    "pending_bg": "#4A3A14", "pending_fg": "#FBDD86",
    "custom_history_bg": "#3A3218", "custom_history_fg": "#F7CC53",
    "disabled_fg": "#78857E",
    "btn_primary": "#76A88B", "btn_primary_hover": "#86B89A",
    "btn_secondary_bg": "#303B34", "btn_secondary_fg": "#F0F4F1",
    "btn_secondary_hover": "#3A463F",
    "btn_danger": "#D9544A", "btn_danger_hover": "#C0433A",
    "btn_success": "#77A96A", "btn_success_hover": "#649456", "btn_warn": "#F7CC53",
    "status_ok_fg": "#77A96A", "status_warn_fg": "#E3B241", "status_error_fg": "#D9544A",
    "toast_info_bg": "#303B34", "toast_info_fg": "#F0F4F1",
    "toast_success_bg": "#649456", "toast_success_fg": "#FFFFFF",
    "toast_error_bg": "#C0433A", "toast_error_fg": "#FFFFFF",
    "matrix_basis": "#F8D989", "matrix_orange": "#D88C49", "matrix_dir": "#BFD3A9",
    "matrix_meta": "#3A463F", "matrix_label": "#315B4F", "matrix_label_fg": "#FFFFFF",
    "matrix_black": "#151917", "matrix_value": "#F8F8F5",
}

PALETTES = {
    "graphite": {"light": GRAPHITE_LIGHT, "dark": GRAPHITE_DARK},
    "navy": {"light": NAVY_LIGHT, "dark": NAVY_DARK},
    "warm": {"light": WARM_LIGHT, "dark": WARM_DARK},
}

PALETTE_ORDER = ("graphite", "warm", "navy")
PALETTE_LABELS = {
    "graphite": "Graphite",
    "warm": "Warm",
    "navy": "Navy",
}


def resolve_theme(family: str, mode: str) -> Dict[str, Any]:
    fam = PALETTES.get(family, PALETTES["graphite"])
    return fam.get(mode, fam["light"])


def apply_theme(family: str, mode: str) -> None:
    """Swap the live THEME dict in place so existing widget builders keep working."""
    THEME.clear()
    THEME.update(resolve_theme(family, mode))


def is_dark_theme() -> bool:
    bg = str(THEME.get("bg", "#ffffff")).lstrip("#")
    if len(bg) != 6:
        return False
    try:
        r, g, b = (int(bg[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return False
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return luminance < 0.45


DROPDOWN_MARK = ""


THICKNESS_VALUE_COLUMNS = (


    "Thick_Value", "Thick Value", "ThickValue", "Thickness_Value", "Thickness Value",
    "ThicknessOrDia", "Thickness Or Dia", "ThicknessOrDiameter", "Thickness Or Diameter",
    "Thickness/Dia", "Thickness / Dia", "Thickness Dia", "Thickness Diameter",
    "Thickness", "Thickness Range", "Thickness_Range", "Thick_Range", "ThicknessRange",
    "ThicknessDescription", "Thickness Description", "Thickness_Size", "Thickness Size",
    "Nominal_Thickness", "Nominal Thickness", "NominalThickness",
    "Thick", "Thick.", "Thickness_In", "Thickness (in)", "Thickness_inch", "Thickness inch",
    "Dia", "Diameter", "Diameter_Value", "Diameter Value",
    "Gage", "Gauge",
)
WALL_THICKNESS_COLUMNS = (
    "Wall_Thick", "Wall Thick", "WallThickness", "Wall Thickness",
    "Wall_Thickness", "WallThick", "Wall Thick Value", "WallThicknessValue",
)
CROSS_SECTION_VALUE_COLUMNS = (
    "Cross_Section", "Cross Section", "CrossSection", "CrossSectionArea",
    "Cross Section Area", "Cross_Section_Area", "CrossSection_Area",
    "C_S", "C S", "CS", "C/S", "C.S.", "C.S", "Cross Sec", "CrossSec",
)


# Remove only orange/warm theme; keep current Graphite/Green and Navy/Blue light/dark themes.
PALETTES = {
    "graphite": {"light": GRAPHITE_LIGHT, "dark": GRAPHITE_DARK},
    "navy": {"light": NAVY_LIGHT, "dark": NAVY_DARK},
}
PALETTE_ORDER = ("graphite", "navy")
PALETTE_LABELS = {"graphite": "Green", "navy": "Blue"}
