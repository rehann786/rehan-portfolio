from __future__ import annotations

import pandas as pd
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from mmpds_desktop.config.settings import CROSS_SECTION_VALUE_COLUMNS, DEFAULT_UNIT_CONVERSIONS, NO_SPEC_DISPLAY, THICKNESS_COLUMNS, THICKNESS_VALUE_COLUMNS, UNIT_SYSTEM_SPEC, WALL_THICKNESS_COLUMNS



def norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def is_blank(value: Any) -> bool:
    return norm(value) in {"", "-", "nan", "none", "null", "n/a", "na"}


def clean_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if is_blank(text):
        return default
    return text


def normalized_col_key(value: Any) -> str:
    return norm(value).replace(" ", "").replace("_", "").replace("/", "").replace(".", "").replace("-", "")


def build_col_lookup(columns: Iterable[Any]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for col in columns:
        lookup.setdefault(normalized_col_key(col), str(col))
    return lookup


def row_get(row: pd.Series, *candidates: str, default: str = "") -> str:
    lookup = build_col_lookup(row.index)
    for cand in candidates:
        actual = lookup.get(normalized_col_key(cand))
        if actual is None:
            continue
        value = row.get(actual, default)
        if not is_blank(value):
            return str(value).strip()
    return default


def display_spec(value: Any) -> str:
    return NO_SPEC_DISPLAY if is_blank(value) else str(value).strip()


def row_spec2_value(row: pd.Series) -> str:
    return display_spec(row_get(row, "Specification 2", "Specification2", "Spec2", "Spec2_1", "Spec2_2", "Spec2_3", "Spec2_4"))


def thickness_label_for_row(row: pd.Series) -> str:
    value = row_get(row, *THICKNESS_COLUMNS, default="")
    if not value:
        return "NA"
    try:
        if str(value).strip().isdigit() and len(str(value).strip()) <= 3:
            return "NA"
    except Exception:
        pass
    return str(value).strip()


def stage_value_for_row(row: pd.Series, stage: str, material_to_series: Optional[Dict[str, str]] = None) -> str:
    if stage == "Series":
        value = row_get(row, "Series", default="")
        if value:
            return value
        if material_to_series:
            return material_to_series.get(norm(row_get(row, "Material", default="")), "")
        return ""
    if stage == "Specification":
        return display_spec(row_get(row, "Spec1_1", "spec1_1", "Specification", default=""))
    if stage == "Specification 2":
        return row_spec2_value(row)
    if stage == "Thickness":
        return thickness_label_for_row(row)
    return row_get(row, stage, default="")


def _candidate_columns(columns: Sequence[str], aliases: Sequence[str], basis: str = "", direction: str = "") -> List[str]:
    lookup = build_col_lookup(columns)
    basis = str(basis or "").strip().upper()
    direction = str(direction or "").strip().upper()
    bases = [basis] if basis in {"A", "B", "S"} else ["A", "B", "S"]
    dirs = [direction] if direction in {"L", "LT"} else ["L", "LT"]
    requested: List[str] = []
    for alias in aliases:
        for d in dirs:
            for b in bases:
                requested.append(f"{alias}_{d}_{b}")
        for b in bases:
            requested.append(f"{alias}_{b}")
        for d in dirs:
            requested.append(f"{alias}_{d}")
        requested.append(alias)
    out: List[str] = []
    seen = set()
    for name in requested:
        actual = lookup.get(normalized_col_key(name))
        if actual and actual not in seen:
            seen.add(actual)
            out.append(actual)
    return out


def duplicate_key(item: Dict[str, Any]) -> Tuple[str, ...]:
    unit = clean_text(item.get("Unit", "")) or clean_text(item.get("Unit_System", ""))
    matcard = clean_text(item.get("Matcard", "")) or clean_text(item.get("Material_Model", "")) or clean_text(item.get("Model", ""))
    values = [
        item.get("Element", ""), item.get("Series", ""), item.get("Material", ""),
        item.get("Temper", ""), item.get("Specification", ""), item.get("Specification 2", ""),
        item.get("Form", ""), item.get("Thickness", ""), item.get("Basis", ""),
        item.get("Direction", ""), unit, matcard,
    ]
    return tuple(norm(v) for v in values)


def mark_duplicate_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[Tuple[str, ...], int] = {}
    for item in items:
        item["_duplicate"] = False
    for idx, item in enumerate(items):
        key = duplicate_key(item)
        if key in seen:
            item["_duplicate"] = True
            first = seen[key]
            if 0 <= first < len(items):
                items[first]["_duplicate"] = True
        else:
            seen[key] = idx
    return items


def remove_duplicate_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        key = duplicate_key(item)
        if key in seen:
            continue
        seen.add(key)
        new_item = dict(item)
        new_item["_duplicate"] = False
        out.append(new_item)
    return out


def norm(v) -> str:
    if v is None:
        return ""
    return str(v).strip().lower()


def is_blank(v) -> bool:
    return norm(v) in ("", "-", "nan", "none")


def first_nonblank_value(*values, default: str = "") -> str:
    """Return the first non-blank value from a list of candidates."""
    for value in values:
        if not is_blank(value):
            return str(value).strip()
    return default


def row_first_nonblank(row, *names: str, default: str = "") -> str:
    """Read the first non-blank value from a Series using tolerant column names."""
    if row is None:
        return default
    try:
        columns = list(row.index)
    except Exception:
        return default
    lower_map = {norm(c): c for c in columns}
    for name in names:
        col = lower_map.get(norm(name))
        if col is not None:
            val = row.get(col, default)
            if not is_blank(val):
                return str(val).strip()
    return default


def row_spec2_value(row, default: str = "") -> str:
    """Return Specification 2 from secondary specification columns."""
    return row_first_nonblank(
        row,
        "Specification 2", "Specification2", "Spec2", "Spec2_1", "Spec2_2", "Spec2_3", "Spec2_4",
        default=default,
    )


def display_spec_value(value) -> str:
    return NO_SPEC_DISPLAY if is_blank(value) else str(value).strip()


def try_float(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "-", "nan", "None"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def fmt_number(v) -> str:
    if v is None:
        return "-"
    try:
        v = float(v)
    except Exception:
        return "-"
    a = abs(v)
    if a == 0:
        return "0"
    if a >= 1e6:
        return f"{v:.6g}"
    if a < 1e-3:
        return f"{v:.6g}"
    if a >= 100:
        return f"{v:.2f}"
    if a >= 1:
        return f"{v:.3f}"
    return f"{v:.6g}"

def with_dropdown_mark(value) -> str:
    """Return clean display text. The real dropdown arrow comes from the Combobox overlay on click."""
    return "" if value is None else str(value).strip()

def strip_dropdown_mark(value) -> str:
    """Clean any legacy dropdown markers before saving/calculating values."""
    text = "" if value is None else str(value).strip()
    return text.replace("\u25bc", "").replace("\u25be", "").strip()


def with_edit_box(value) -> str:
    """Return clean Property Card value text.

    The Value column looks editable through row/cell styling and a real Entry
    editor overlay on click. We do not add fake bracket characters to the data.
    """
    return "" if value is None else str(value).strip()


def strip_edit_box(value) -> str:
    """Clean legacy fake edit-box symbols before saving/calculating."""
    text = strip_dropdown_mark(value)
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    return text


def find_col(df: pd.DataFrame, *candidates: str) -> str | None:
    if df is None or df.empty:
        return None
    lookup = {norm(c): c for c in df.columns}
    for cand in candidates:
        if norm(cand) in lookup:
            return lookup[norm(cand)]
    return None


def source_row_identity_key(row) -> str:
    """Stable internal key for a source row.

    This is intentionally NOT shown in the GUI. It lets Thickness dropdowns keep
    every real source row even when two rows have the same clean visible text
    such as "3.000-4.499" or "<=20 | 3.000-4.499".
    """
    if row is None:
        return ""
    try:
        row_name = getattr(row, "name", None)
        if row_name is not None:
            return f"idx:{row_name}"
    except Exception:
        pass

    parts = []
    for col in (
        "MatID", "Material ID", "Material_ID", "MaterialID", "MID",
        "Element", "Series", "Material", "Temper", "Spec1_1", "Specification",
        "Spec2_1", "Spec2_2", "Specification 2", "Specification2",
        "Form", "Cross_Section", "CrossSectionArea", "Thick_Value",
        "ThicknessOrDia", "Wall_Thick", "WallThickness", "ThicknessNumber",
        "Material_Card_Name", "MatCardName", "MMPDS_Version",
    ):
        try:
            parts.append(str(row.get(col, "")).strip())
        except Exception:
            parts.append("")
    return "|".join(parts)


def _normalized_col_key(value: Any) -> str:
    """Normalize a column name for tolerant alias matching."""
    return norm(value).replace(" ", "").replace("_", "").replace("/", "").replace(".", "").replace("-", "")


def row_get_first_nonblank_tolerant(row, *names: str, default: str = "") -> str:
    """Return first nonblank row value using tolerant column-name matching."""
    values = row_get_all_nonblank_tolerant(row, *names)
    return values[0] if values else default


def row_get_all_nonblank_tolerant(row, *names: str) -> List[str]:
    """Return all nonblank row values whose column names match the aliases."""
    if row is None:
        return []
    try:
        columns = list(row.index)
    except Exception:
        return []

    normalized_to_actual: Dict[str, str] = {}
    for c in columns:
        normalized_to_actual.setdefault(_normalized_col_key(c), c)

    out: List[str] = []
    seen = set()
    for name in names:
        col = normalized_to_actual.get(_normalized_col_key(name))
        if col is None or col in seen:
            continue
        seen.add(col)
        try:
            value = str(row.get(col, "")).strip()
        except Exception:
            value = ""
        if not is_blank(value):
            out.append(value)
    return out


def _row_values_from_named_columns(row, include_tokens: Tuple[str, ...]) -> List[str]:
    """Read values from source columns whose names contain useful dimension tokens.

    This is a defensive fallback for source files that use slightly different
    column names than the legacy GUI expected. It is restricted to dimension-like
    column names so tensile/yield/modulus numbers are not accidentally used as
    thickness values.

    ThicknessNumber / Thickness No columns are deliberately skipped because they
    are row sequence/index values like 1, 2, 3, 4, not physical thickness values.
    """
    if row is None:
        return []
    try:
        columns = list(row.index)
    except Exception:
        return []
    values: List[str] = []
    for col in columns:
        col_key = _normalized_col_key(col)
        if not any(token in col_key for token in include_tokens):
            continue

        if (
            "thick" in col_key
            and any(bad in col_key for bad in ("number", "num", "no", "index", "idx", "seq", "sequence", "row"))
        ):
            continue
        try:
            value = str(row.get(col, "")).strip()
        except Exception:
            value = ""
        if not is_blank(value):
            values.append(value)
    return values


def df_first_existing_series(df: pd.DataFrame, names: Tuple[str, ...], default: str = "-") -> pd.Series:
    """Return the first existing nonblank column from a DataFrame alias list."""
    if df is None or df.empty:
        return pd.Series([], dtype=str)
    normalized_to_actual = {_normalized_col_key(c): c for c in df.columns}
    result = pd.Series([default] * len(df), index=df.index, dtype=object)
    missing = pd.Series([True] * len(df), index=df.index)
    for name in names:
        col = normalized_to_actual.get(_normalized_col_key(name))
        if col is None:
            continue
        values = df[col].astype(str).str.strip()
        usable = ~values.map(is_blank)
        result.loc[missing & usable] = values.loc[missing & usable]
        missing = missing & ~usable
    return result.fillna(default).astype(str)


def _clean_dimension_piece(value: Any) -> str:
    """Clean a CS/thickness text value without adding internal labels to the GUI."""
    if value is None:
        return ""
    text = str(value).strip()
    if is_blank(text):
        return ""
    text = (
        text.replace("\u2264", "<=")
            .replace("\u2265", ">=")
            .replace("\u2013", "-")
            .replace("\u2014", "-")
            .replace("\u00a0", " ")
    )
    text = " ".join(text.split())


    label_patterns = [
        r"^(?:cross[_\s/.-]*section(?:[_\s/.-]*area)?|c[_\s/.-]*s|cs)\s*[:=]?\s*",
        r"^(?:thick(?:ness)?(?:[_\s/.-]*(?:value|or[_\s/.-]*dia|or[_\s/.-]*diameter|range))?|wall[_\s/.-]*thick(?:ness)?|dia(?:meter)?|gauge|gage)\s*[:=]?\s*",
        r"^(?:t)\s*[:=]\s*",
    ]
    import re
    changed = True
    while changed:
        changed = False
        for pat in label_patterns:
            new_text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()
            if new_text != text:
                text = new_text
                changed = True
    return text.strip(" |,;:")


def _split_embedded_cross_section(value: Any) -> Tuple[str, str]:
    """Split strings like '3.000-4.499 C_S >20-<=32'.

    Returns (text_before_cs_marker, cross_section_after_marker). If there is no
    embedded C_S/Cross Section marker, the second item is empty.
    """
    import re
    text = _clean_dimension_piece(value)
    if not text:
        return "", ""


    patterns = [
        r"(?i)(.*?)\s*(?:\bC\s*[_./-]?\s*S\b|\bCS\b|\bCross\s*[-_ ]*Section(?:\s*[-_ ]*Area)?\b)\s*[:=]?\s*(.+)$",
    ]
    for pat in patterns:
        m = re.match(pat, text)
        if m:
            before = _clean_dimension_piece(m.group(1))
            after = _clean_dimension_piece(m.group(2))
            return before, after
    return text, ""


def _looks_like_thickness_text(value: str) -> bool:
    """Heuristic used only as a fallback for unusual source column names."""
    import re
    text = _clean_dimension_piece(value)
    if not text:
        return False

    if re.search(r"\d+\.\d+", text):
        return True
    if re.search(r"\b\d+\s*/\s*\d+\b", text):
        return True
    if re.search(r"\b(?:dia|diameter|thick|thickness)\b", text, flags=re.IGNORECASE):
        return True
    return False


def _looks_like_cross_section_text(value: str) -> bool:
    """Heuristic for CS values like '<=20', '>20-<=32', '<=32'."""
    import re
    text = _clean_dimension_piece(value)
    if not text:
        return False
    if re.search(r"(<=|>=|<|>)\s*\d", text):
        return True
    if re.search(r"\bC\s*[_./-]?\s*S\b|\bCS\b|Cross\s*[-_ ]*Section", text, flags=re.IGNORECASE):
        return True
    return False


def _first_unique(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        clean = _clean_dimension_piece(value)
        if not clean:
            continue
        key = norm(clean)
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def source_actual_thick_value(row) -> str:
    """Return the user-facing actual Thick_Value only.

    Manager requirement: the Thickness dropdown should show the real source
    Thick_Value column values, like:
        0.250-0.499
        0.500-0.749
        0.750-1.499
        <=0.249

    It must NOT show Cross_Section and must NOT show ThicknessNumber values
    such as 1, 2, 3, 4, 5, 6.
    """
    import re

    if row is None:
        return ""


    actual_columns = (
        "Thick_Value", "Thick Value", "ThickValue", "Thickness_Value", "Thickness Value",
        "ThicknessOrDia", "Thickness Or Dia", "ThicknessOrDiameter", "Thickness Or Diameter",
        "Thickness/Dia", "Thickness / Dia", "Thickness Dia", "Thickness Diameter",
        "Thickness Range", "Thickness_Range", "Thick_Range", "ThicknessRange",
        "Thickness", "Thick", "Thick.",
        "Dia", "Diameter", "Diameter_Value", "Diameter Value",
    )

    candidates = []
    candidates.extend(row_get_all_nonblank_tolerant(row, *actual_columns))


    for card_col in ("MatCard_Name", "MatCardName", "Material_Card_Name", "Material Card Name"):
        card_name = row_get_first_nonblank_tolerant(row, card_col, default="")
        if card_name:
            m = re.search(r"(?:^|[_\s])t\s*=\s*([^_\s,;]+)", card_name, flags=re.IGNORECASE)
            if m:
                candidates.append(m.group(1).strip())
                break


    candidates.extend(row_get_all_nonblank_tolerant(row, *WALL_THICKNESS_COLUMNS))

    for raw in candidates:
        before, _embedded_cs = _split_embedded_cross_section(raw)
        value = _clean_dimension_piece(before or raw)
        if not value:
            continue


        if re.fullmatch(r"\d{1,3}", value):
            continue


        if _looks_like_cross_section_text(value) and not _looks_like_thickness_text(value):
            continue

        return value

    return ""

def source_thickness_components(row) -> Tuple[str, str, str]:
    """Return (cross_section, thick_value, wall_thick) for clean UI display.

    The dropdown label is created from these components as:
        Cross_Section | Thick_Value

    The function is defensive because some source exports have shifted or
    embedded text such as '3.000-4.499 C_S >20-<=32'. It removes the embedded
    C_S text from the thickness value and uses it as the CS value.
    """
    thick_candidates = _first_unique(
        row_get_all_nonblank_tolerant(row, *THICKNESS_VALUE_COLUMNS)
        + _row_values_from_named_columns(row, ("thick", "thickness", "dia", "diameter", "gage", "gauge"))
    )
    wall_candidates = _first_unique(
        row_get_all_nonblank_tolerant(row, *WALL_THICKNESS_COLUMNS)
        + _row_values_from_named_columns(row, ("wallthick", "wallthickness"))
    )
    cs_candidates = _first_unique(
        row_get_all_nonblank_tolerant(row, *CROSS_SECTION_VALUE_COLUMNS)
        + _row_values_from_named_columns(row, ("crosssection", "crosssectionarea", "crosssec", "cs"))
    )

    cs = ""
    thick = ""
    wall = wall_candidates[0] if wall_candidates else ""


    for raw in thick_candidates:
        before, embedded_cs = _split_embedded_cross_section(raw)
        if embedded_cs and not cs:
            cs = embedded_cs
        if before:
            if _looks_like_cross_section_text(before) and not _looks_like_thickness_text(before):
                if not cs:
                    cs = before
            elif not thick:


                import re
                if not re.fullmatch(r"\d{1,3}", _clean_dimension_piece(before)):
                    thick = before
        if thick and cs:
            break


    for raw in cs_candidates:
        before, embedded_cs = _split_embedded_cross_section(raw)
        if embedded_cs:
            if before and not thick:
                thick = before
            if not cs:
                cs = embedded_cs
        else:
            if _looks_like_cross_section_text(before) and not cs:
                cs = before
            elif _looks_like_thickness_text(before) and not thick:

                thick = before
        if thick and cs:
            break


    if not thick and wall:
        thick = wall


    thick_before, thick_embedded_cs = _split_embedded_cross_section(thick)
    if thick_before:
        thick = thick_before
    if thick_embedded_cs and not cs:
        cs = thick_embedded_cs

    cs_before, cs_embedded_cs = _split_embedded_cross_section(cs)
    if cs_embedded_cs:
        if cs_before and not thick:
            thick = cs_before
        cs = cs_embedded_cs
    else:
        cs = cs_before

    cs = _clean_dimension_piece(cs)
    thick = _clean_dimension_piece(thick)
    wall = _clean_dimension_piece(wall)


    if cs and thick and norm(cs) == norm(thick):
        thick = ""

    return cs, thick, wall


def source_thickness_display_label(row) -> str:
    """Visible Thickness dropdown label: actual Thick_Value only.

    Manager/current requirement:
        Show only the real source Thick_Value values, for example:
            0.250-0.499
            0.500-0.749
            0.750-1.499
            1.500-2.999
            3.000-4.499
            3.000-4.499
            4.500-5.000
            <=0.249

    Important:
    - Do NOT show Cross_Section values such as <=20, >20-<=32, or <=32.
    - Do NOT show ThicknessNumber values like 1, 2, 3, 4, 5, 6.
    - Duplicate Thick_Value labels are allowed and preserved internally by
      dropdown index/source-row key, so selecting either duplicate still maps
      to the correct source row.
    """
    thick = source_actual_thick_value(row)
    return thick if thick else "NA"

def source_cross_section_value(row) -> str:
    cs, _thick, _wall = source_thickness_components(row)
    return cs


def source_thickness_base_value(row, prefer_wall: bool = False) -> str:
    """Return actual Thick_Value for matching/file names; never ThicknessNumber."""
    thick = source_actual_thick_value(row)
    return thick if thick else "-"


def _source_series_from_master_value(element: Any, material: Any) -> str:
    """Infer a Series label directly from the approved master CSV row.

    The approved Metal_Data_ABS-Basis_V3.csv does not always contain a Series
    column. This helper prevents the GUI from needing another material database
    just to show a Series filter. Existing Dropdown/material mappings still win
    when present; this is only a master-CSV fallback.
    """
    import re
    element_text = str(element or "").strip().upper()
    material_text = str(material or "").strip().upper()
    if not material_text or is_blank(material_text):
        return ""
    if element_text == "ALUMINUM":
        digits = "".join(re.findall(r"\d", material_text))
        if len(digits) >= 4 and digits[0] in "123456789":
            return f"{digits[0]}000_Wrought"
        if len(digits) == 3:
            return "Aluminum_Casting"
        return "Aluminum"
    if element_text == "STEEL":
        return "Steel"
    if element_text == "TITANIUM":
        return "Titanium"
    if element_text == "MAGNESIUM":
        return "Magnesium"
    return element_text.title() if element_text else ""


def _source_row_label_piece(label: str, value: Any) -> str:
    """Return one clean suffix piece for duplicate thickness display labels."""
    text = _clean_dimension_piece(value)
    if not text or is_blank(text):
        return ""
    return f"{label} {text}"


def source_gui_thickness_label(row) -> str:
    """Return the GUI-visible thickness label for a source row.

    Runtime helper column __adv_thickness_label is duplicate-aware. It keeps rows
    with the same Thick_Value but different Cross_Section, Wall_Thick, Location,
    Strength Class, or MatID visible in the GUI instead of collapsing them into
    one option.
    """
    try:
        value = row.get("__adv_thickness_label", "")
        if not is_blank(value):
            return str(value).strip()
    except Exception:
        pass
    return source_thickness_display_label(row)


def source_unit_label(kind: str) -> str:
    if kind == "pressure":
        return "ksi"
    if kind == "modulus":
        return "10^3 ksi"
    if kind == "density":
        return "lb/in^3"
    if kind == "percent":
        return "%"
    return "[-]"


def converted_unit_label(kind: str, unit_sys: str) -> str:
    """Return the Eng./converted unit label for the selected unit system.

    The source Unit column stays tied to the original MMPDS/source value
    (ksi, 10^3 ksi, lb/in^3, %, [-]). This helper drives the new
    Converted Unit column, so users can see which unit the Eng. value uses.
    """
    spec = UNIT_SYSTEM_SPEC.get(unit_sys, UNIT_SYSTEM_SPEC["mm_T_s"])
    if kind in ("pressure", "modulus"):
        return spec["pressure_label"]
    if kind == "density":
        return spec["density_label"]
    if kind == "percent":
        return "%"
    return "[-]"


def convert_value(raw, kind: str, unit_sys: str, conversions: Optional[Dict[str, float]] = None):
    """Convert source values using the active editable conversion table.

    The source Value column is not changed by this function. It is used only for
    calculated/display columns such as Eng., MAT_24 values, True, and Eff.P.S.
    """
    spec = UNIT_SYSTEM_SPEC[unit_sys]
    factors = conversions or DEFAULT_UNIT_CONVERSIONS

    if raw is None:
        if kind in ("pressure", "modulus"):
            return None, spec["pressure_label"]
        if kind == "density":
            return None, spec["density_label"]
        if kind == "percent":
            return None, "%"
        return None, "[-]"

    pressure_factor = factors.get(f"{unit_sys}_pressure", spec["pressure_factor"])

    if kind == "pressure":
        return raw * pressure_factor, spec["pressure_label"]
    if kind == "modulus":


        return raw * 1000 * pressure_factor, spec["pressure_label"]
    if kind == "density":
        return raw * factors.get(f"{unit_sys}_density", spec["density_factor"]), spec["density_label"]
    if kind == "percent":
        return raw, "%"
    return raw, "[-]"


def safe_divide(numerator: Optional[float], denominator: Optional[float], default: float = 0) -> float:
    """Safely divide two numbers, returning default if denominator is zero."""
    if denominator is None or denominator == 0:
        return default
    if numerator is None:
        return default
    try:
        return numerator / denominator
    except (TypeError, ZeroDivisionError):
        return default


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min and max."""
    return max(min_val, min(max_val, value))
