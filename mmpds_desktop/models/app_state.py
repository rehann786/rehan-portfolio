from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import product
from pathlib import Path
import getpass
import hashlib
import json
import pandas as pd
import shutil
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from mmpds_desktop.calculations.conversions import _candidate_columns, _source_row_label_piece, _source_series_from_master_value, build_col_lookup, clean_text, df_first_existing_series, display_spec_value, find_col, first_nonblank_value, is_blank, norm, row_get_first_nonblank_tolerant, row_spec2_value, source_cross_section_value, source_thickness_base_value, source_thickness_display_label, stage_value_for_row, thickness_label_for_row
from mmpds_desktop.config.settings import CACHE_SIZE_LIMIT, CLEAN_MASTER_FILE, CROSS_SECTION_VALUE_COLUMNS, DATA_DIR, DEFAULT_BASIS_CODES, DEFAULT_DIRECTION_CODES, DEFAULT_MAT_MODELS, DEFAULT_STAGES, DROPDOWN_DIR, EXPORT_COUNTER_FILE, EXPORT_COUNTER_LOCK_DIR, EXPORT_COUNTER_MAX, EXPORT_COUNTER_START, HISTORY_FILE, LOOKUP_FILES, MASTER_FILE, MAX_SOURCE_IMAGES, NO_SPEC_DISPLAY, PROPERTY_ALIASES, REQUIRED_MAT_VALUE_GROUPS, STAGES, THICKNESS_VALUE_COLUMNS, WALL_THICKNESS_COLUMNS, logger



@dataclass(frozen=True)
class DefaultCombo:
    basis: str = ""
    direction: str = ""
    matcard: str = ""
    count: int = 0


class FastMaterialEngine:
    """Cached, vectorized exact-match backend for Advanced Selection/Finder."""

    def __init__(
        self,
        master_df: pd.DataFrame,
        stages: Sequence[str] = DEFAULT_STAGES,
        material_to_series: Optional[Dict[str, str]] = None,
        max_cache: int = 768,
    ):
        self.master = master_df.copy() if master_df is not None else pd.DataFrame()
        self.stages = list(stages)
        self.material_to_series = material_to_series or {}
        self.max_cache = max_cache
        self._cache: Dict[Tuple[Any, ...], Any] = {}
        self._col_lookup = build_col_lookup(self.master.columns) if self.master is not None else {}
        self._stage_df = self._build_stage_df()
        self._availability_df = self._build_availability_df()

    def clear_cache(self) -> None:
        self._cache.clear()

    def _put_cache(self, key: Tuple[Any, ...], value: Any) -> Any:
        if len(self._cache) >= self.max_cache:
            self._cache.clear()
        self._cache[key] = value
        return value

    def _build_stage_df(self) -> pd.DataFrame:
        if self.master.empty:
            return pd.DataFrame(columns=self.stages)
        out = pd.DataFrame(index=self.master.index)
        for stage in self.stages:
            out[stage] = [stage_value_for_row(row, stage, self.material_to_series) for _, row in self.master.iterrows()]
            out[f"{stage}__norm"] = out[stage].map(norm)
        if "__adv_thickness_label" in self.master.columns:
            out["Thickness"] = self.master["__adv_thickness_label"].astype(str).fillna("NA")
        else:
            out["Thickness"] = [thickness_label_for_row(row) for _, row in self.master.iterrows()]
        out["Thickness__norm"] = out["Thickness"].map(norm)
        return out

    def _nonnull_any(self, cols: List[str]) -> pd.Series:
        if self.master.empty:
            return pd.Series([], dtype=bool)
        if not cols:
            # If the schema has no recognizable columns, do not block results.
            return pd.Series(True, index=self.master.index)
        out = pd.Series(False, index=self.master.index)
        for col in cols:
            try:
                vals = self.master[col].astype(str).str.strip()
                out |= ~vals.map(is_blank)
            except Exception:
                continue
        return out

    def _build_availability_df(self) -> pd.DataFrame:
        idx = self.master.index
        av = pd.DataFrame(index=idx)
        if self.master.empty:
            return av
        columns = list(self.master.columns)

        # Basic basis/direction availability from any useful material property.
        for b in DEFAULT_BASIS_CODES:
            for d in DEFAULT_DIRECTION_CODES:
                cols = _candidate_columns(columns, PROPERTY_ALIASES, basis=b, direction=d)
                av[f"bd_{b}_{d}"] = self._nonnull_any(cols)

        # Required MAT value availability by basis/direction.
        for b in DEFAULT_BASIS_CODES:
            for d in DEFAULT_DIRECTION_CODES:
                ok = pd.Series(True, index=idx)
                for _required, aliases in REQUIRED_MAT_VALUE_GROUPS.items():
                    cols = _candidate_columns(columns, aliases, basis=b, direction=d)
                    ok &= self._nonnull_any(cols)
                av[f"core_{b}_{d}"] = ok
        return av

    def _selection_cache_key(self, selections: Optional[Dict[str, Any]], exclude_stage: Optional[str] = None) -> Tuple[Any, ...]:
        selections = selections or {}
        return tuple([exclude_stage] + [(stage, norm(selections.get(stage, ""))) for stage in self.stages])

    def base_mask(self, selections: Optional[Dict[str, Any]], exclude_stage: Optional[str] = None) -> pd.Series:
        key = ("base_mask", self._selection_cache_key(selections, exclude_stage))
        cached = self._cache.get(key)
        if cached is not None:
            return cached.copy()
        if self.master.empty or self._stage_df.empty:
            mask = pd.Series([], dtype=bool)
            return self._put_cache(key, mask).copy()
        selections = selections or {}
        mask = pd.Series(True, index=self.master.index)
        for stage in self.stages:
            if stage == exclude_stage:
                continue
            value = selections.get(stage, "")
            if is_blank(value):
                continue
            norm_col = f"{stage}__norm"
            if norm_col in self._stage_df.columns:
                mask &= self._stage_df[norm_col].eq(norm(value))
        return self._put_cache(key, mask).copy()

    def base_rows(self, selections: Optional[Dict[str, Any]], exclude_stage: Optional[str] = None) -> pd.DataFrame:
        key = ("base_rows", self._selection_cache_key(selections, exclude_stage))
        cached = self._cache.get(key)
        if cached is not None:
            return cached.copy()
        mask = self.base_mask(selections, exclude_stage)
        rows = self.master.loc[mask].copy() if len(mask) else pd.DataFrame()
        return self._put_cache(key, rows).copy()

    def available_stage(self, stage: str, selections: Optional[Dict[str, Any]]) -> List[str]:
        key = ("available_stage", stage, self._selection_cache_key(selections, exclude_stage=stage))
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        if stage not in self._stage_df.columns:
            return []
        mask = self.base_mask(selections, exclude_stage=stage)
        values = self._stage_df.loc[mask, stage] if len(mask) else pd.Series([], dtype=str)
        if stage in {"Specification", "Specification 2"}:
            result = sorted({str(v).strip() for v in values if str(v).strip()}, key=lambda x: (x == NO_SPEC_DISPLAY, x.lower()))
        else:
            result = sorted({str(v).strip() for v in values if not is_blank(v)}, key=str.lower)
        return self._put_cache(key, result)

    def _strict_mask(self, selections: Optional[Dict[str, Any]], thickness: str = "", basis: str = "", direction: str = "", matcard: str = "") -> pd.Series:
        key = ("strict_mask", self._selection_cache_key(selections), norm(thickness), clean_text(basis).upper(), clean_text(direction).upper(), norm(matcard))
        cached = self._cache.get(key)
        if cached is not None:
            return cached.copy()
        mask = self.base_mask(selections)
        if len(mask) == 0:
            return self._put_cache(key, mask).copy()
        if not is_blank(thickness) and thickness != "First matching thickness" and thickness != "All matching thickness rows":
            exact_norm = norm(thickness)
            if "__adv_thickness_norm" in self.master.columns and "__adv_thickness_base_norm" in self.master.columns:
                mask &= (
                    self.master["__adv_thickness_norm"].astype(str).eq(exact_norm)
                    | self.master["__adv_thickness_base_norm"].astype(str).eq(exact_norm)
                )
            elif "Thickness__norm" in self._stage_df.columns:
                mask &= self._stage_df["Thickness__norm"].eq(exact_norm)
        b = clean_text(basis).upper()
        d = clean_text(direction).upper()
        if b in {"A", "B", "S"} and d in {"L", "LT"}:
            col = f"bd_{b}_{d}"
            if col in self._availability_df.columns:
                mask &= self._availability_df[col]
        elif b in {"A", "B", "S"}:
            cols = [f"bd_{b}_{dd}" for dd in DEFAULT_DIRECTION_CODES if f"bd_{b}_{dd}" in self._availability_df.columns]
            if cols:
                mask &= self._availability_df[cols].any(axis=1)
        elif d in {"L", "LT"}:
            cols = [f"bd_{bb}_{d}" for bb in DEFAULT_BASIS_CODES if f"bd_{bb}_{d}" in self._availability_df.columns]
            if cols:
                mask &= self._availability_df[cols].any(axis=1)

        if not is_blank(matcard):
            # Current MAT models all require the same core properties. If the user
            # picked only a basis or direction, use any compatible counterpart.
            if b in {"A", "B", "S"} and d in {"L", "LT"}:
                cols = [f"core_{b}_{d}"]
            elif b in {"A", "B", "S"}:
                cols = [f"core_{b}_{dd}" for dd in DEFAULT_DIRECTION_CODES]
            elif d in {"L", "LT"}:
                cols = [f"core_{bb}_{d}" for bb in DEFAULT_BASIS_CODES]
            else:
                cols = [f"core_{bb}_{dd}" for bb in DEFAULT_BASIS_CODES for dd in DEFAULT_DIRECTION_CODES]
            cols = [c for c in cols if c in self._availability_df.columns]
            if cols:
                mask &= self._availability_df[cols].any(axis=1)
        return self._put_cache(key, mask).copy()

    def filter_rows(self, selections: Optional[Dict[str, Any]], *, thickness: str = "", basis: str = "", direction: str = "", matcard: str = "", limit: Optional[int] = None) -> pd.DataFrame:
        key = ("filter_rows", self._selection_cache_key(selections), norm(thickness), clean_text(basis).upper(), clean_text(direction).upper(), norm(matcard), limit)
        cached = self._cache.get(key)
        if cached is not None:
            return cached.copy()
        mask = self._strict_mask(selections, thickness, basis, direction, matcard)
        rows = self.master.loc[mask].copy() if len(mask) else pd.DataFrame()
        if limit is not None and rows is not None and not rows.empty:
            rows = rows.head(int(limit)).copy()
        return self._put_cache(key, rows if rows is not None else pd.DataFrame()).copy()

    def count(self, selections: Optional[Dict[str, Any]], **kwargs: Any) -> int:
        mask = self._strict_mask(selections, kwargs.get("thickness", ""), kwargs.get("basis", ""), kwargs.get("direction", ""), kwargs.get("matcard", ""))
        return int(mask.sum()) if len(mask) else 0

    def available_thicknesses(self, selections: Optional[Dict[str, Any]]) -> List[str]:
        key = ("available_thicknesses", self._selection_cache_key(selections))
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        mask = self.base_mask(selections)
        vals = self._stage_df.loc[mask, "Thickness"] if len(mask) else pd.Series([], dtype=str)
        result: List[str] = []
        seen = set()
        for value in vals.astype(str):
            if not value or norm(value) in seen:
                continue
            seen.add(norm(value))
            result.append(value)
        return self._put_cache(key, result)

    def available_bases(self, selections: Optional[Dict[str, Any]], *, thickness: str = "", direction: str = "", matcard: str = "") -> List[str]:
        return [b for b in DEFAULT_BASIS_CODES if self.count(selections, thickness=thickness, basis=b, direction=direction, matcard=matcard) > 0]

    def available_directions(self, selections: Optional[Dict[str, Any]], *, thickness: str = "", basis: str = "", matcard: str = "") -> List[str]:
        return [d for d in DEFAULT_DIRECTION_CODES if self.count(selections, thickness=thickness, basis=basis, direction=d, matcard=matcard) > 0]

    def available_matcards(self, selections: Optional[Dict[str, Any]], *, thickness: str = "", basis: str = "", direction: str = "") -> List[str]:
        # Keep the displayed model order, but the model availability check is
        # vectorized through count().
        return [m for m in DEFAULT_MAT_MODELS if self.count(selections, thickness=thickness, basis=basis, direction=direction, matcard=m) > 0]

    @staticmethod
    def _preferred(values: Sequence[str], preferred: str, fallback: str = "") -> str:
        values = [v for v in values if not is_blank(v)]
        if preferred in values:
            return preferred
        return values[0] if values else fallback

    def best_defaults(self, selections: Optional[Dict[str, Any]], *, thickness: str = "", preferred_basis: str = "B", preferred_direction: str = "L", preferred_matcard: str = "MAT024+GISSMO") -> DefaultCombo:
        if self.count(selections, thickness=thickness, basis=preferred_basis, direction=preferred_direction, matcard=preferred_matcard) > 0:
            return DefaultCombo(preferred_basis, preferred_direction, preferred_matcard, count=1)
        for model in DEFAULT_MAT_MODELS:
            if self.count(selections, thickness=thickness, basis=preferred_basis, direction=preferred_direction, matcard=model) > 0:
                return DefaultCombo(preferred_basis, preferred_direction, model, count=1)
        for basis, direction, model in list(product([preferred_basis], DEFAULT_DIRECTION_CODES, DEFAULT_MAT_MODELS)) + list(product(DEFAULT_BASIS_CODES, DEFAULT_DIRECTION_CODES, DEFAULT_MAT_MODELS)):
            if self.count(selections, thickness=thickness, basis=basis, direction=direction, matcard=model) > 0:
                return DefaultCombo(basis, direction, model, count=1)
        return DefaultCombo("", "", "", count=0)

    def validate_exact(self, selections: Optional[Dict[str, Any]], *, thickness: str = "", basis: str = "", direction: str = "", matcard: str = "") -> Tuple[bool, str, int]:
        count = self.count(selections, thickness=thickness, basis=basis, direction=direction, matcard=matcard)
        if count <= 0:
            return False, "No exact matching material exists for the selected combination.", 0
        return True, "", count


def _read_export_counter_payload() -> Dict[str, Any]:
    """Read the persistent export-counter JSON safely."""
    default_payload = {
        "next_export_id": EXPORT_COUNTER_START,
        "max_export_id": EXPORT_COUNTER_MAX,
        "last_export_id": None,
        "updated_at": "",
        "updated_by": "",
    }
    try:
        if EXPORT_COUNTER_FILE.exists():
            payload = json.loads(EXPORT_COUNTER_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                default_payload.update(payload)
    except Exception:
        pass

    try:
        next_id = int(default_payload.get("next_export_id", EXPORT_COUNTER_START))
    except Exception:
        next_id = EXPORT_COUNTER_START
    try:
        max_id = int(default_payload.get("max_export_id", EXPORT_COUNTER_MAX))
    except Exception:
        max_id = EXPORT_COUNTER_MAX

    if next_id < EXPORT_COUNTER_START:
        next_id = EXPORT_COUNTER_START
    if max_id > EXPORT_COUNTER_MAX or max_id < EXPORT_COUNTER_START:
        max_id = EXPORT_COUNTER_MAX

    default_payload["next_export_id"] = next_id
    default_payload["max_export_id"] = max_id
    return default_payload


def _write_export_counter_payload(payload: Dict[str, Any]) -> None:
    EXPORT_COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_COUNTER_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _acquire_export_counter_lock(timeout_seconds: float = 10.0) -> None:
    """Acquire a simple directory lock for safe shared-drive counter updates."""
    start = time.time()
    while True:
        try:
            EXPORT_COUNTER_LOCK_DIR.mkdir(parents=True, exist_ok=False)
            try:
                (EXPORT_COUNTER_LOCK_DIR / "owner.txt").write_text(
                    f"user={getpass.getuser()}\nstarted={datetime.now().isoformat(timespec='seconds')}\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
            return
        except FileExistsError:

            if time.time() - start > timeout_seconds:
                try:
                    shutil.rmtree(EXPORT_COUNTER_LOCK_DIR, ignore_errors=True)
                except Exception:
                    pass
                try:
                    EXPORT_COUNTER_LOCK_DIR.mkdir(parents=True, exist_ok=False)
                    return
                except Exception:
                    raise RuntimeError("Could not acquire export counter lock. Please try exporting again.")
            time.sleep(0.08)
        except Exception as exc:
            raise RuntimeError(f"Could not acquire export counter lock: {exc}")


def _release_export_counter_lock() -> None:
    try:
        shutil.rmtree(EXPORT_COUNTER_LOCK_DIR, ignore_errors=True)
    except Exception:
        pass


SESSION_NEXT_EXPORT_ID = EXPORT_COUNTER_START


def normalize_export_id(value: Any, default: Optional[int] = None) -> int:
    """Return a valid integer export ID for this app session."""
    if default is None:
        default = EXPORT_COUNTER_START
    try:
        text = str(value).strip().replace(",", "")
        export_id = int(float(text))
    except Exception:
        export_id = int(default)
    if export_id < EXPORT_COUNTER_START:
        export_id = EXPORT_COUNTER_START
    if export_id > EXPORT_COUNTER_MAX:
        raise RuntimeError(
            f"Export ID {export_id:,} is above the maximum allowed ID ({EXPORT_COUNTER_MAX:,})."
        )
    return export_id


def reserve_next_export_id(preferred_id: Optional[Any] = None) -> int:
    """Reserve and return the next session-based export ID.

    Manager requirement:
    - The ID starts from 1000 every time the application is opened.
    - It does not continue from export_counter.json after closing/reopening.
    - If the user edits the visible ID, that edited value is honored.
    """
    global SESSION_NEXT_EXPORT_ID
    if preferred_id not in (None, ""):
        export_id = normalize_export_id(preferred_id, default=SESSION_NEXT_EXPORT_ID)
    else:
        export_id = normalize_export_id(SESSION_NEXT_EXPORT_ID, default=EXPORT_COUNTER_START)

    SESSION_NEXT_EXPORT_ID = max(int(SESSION_NEXT_EXPORT_ID), int(export_id) + 1)
    return int(export_id)


def peek_next_export_id() -> int:
    """Return the next session ID without incrementing it."""
    return normalize_export_id(SESSION_NEXT_EXPORT_ID, default=EXPORT_COUNTER_START)


def advance_session_export_id_after(value: Any) -> None:
    """Keep the next session ID ahead of a user-entered or range-applied ID."""
    global SESSION_NEXT_EXPORT_ID
    try:
        export_id = normalize_export_id(value, default=SESSION_NEXT_EXPORT_ID)
        SESSION_NEXT_EXPORT_ID = max(int(SESSION_NEXT_EXPORT_ID), int(export_id) + 1)
    except Exception:
        return


def export_counter_status_text() -> str:
    try:
        return f"Next Session Export ID: {peek_next_export_id():,}"
    except Exception:
        return f"Session Export IDs start at {EXPORT_COUNTER_START:,}"



def read_csv_safely(path: Path) -> pd.DataFrame:
    if not Path(path).exists():
        raise FileNotFoundError(f"Missing CSV file: {path}")
    try:
        df = pd.read_csv(path, dtype=str, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(path, dtype=str, encoding="latin-1")
    df.columns = [str(c).strip() for c in df.columns]
    return df.fillna("-")


def read_master_fast(csv_path: Path, parquet_path: Path) -> pd.DataFrame:
    """Fast master loader without manual cache button.

    First run reads CSV and tries to create a Parquet copy.
    Later runs load Parquet if it exists and is newer than the CSV.
    If pyarrow/fastparquet is not installed, it safely falls back to CSV.
    """
    try:
        if parquet_path.exists() and parquet_path.stat().st_mtime >= csv_path.stat().st_mtime:
            df = pd.read_parquet(parquet_path)
            df.columns = [str(c).strip() for c in df.columns]
            return df.astype(str).fillna("-")
    except Exception:
        pass

    df = read_csv_safely(csv_path)

    try:
        df.to_parquet(parquet_path, index=False)
    except Exception:
        pass

    return df


def _clean_text(value: Any) -> str:
    """Normalize a source value while keeping '-' for blanks."""
    if value is None:
        return "-"
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return "-"
    return text


def _norm_basis(value: Any) -> str:
    text = _clean_text(value).upper().replace(" ", "").replace("_", "")
    if text.startswith("A"):
        return "A"
    if text.startswith("B"):
        return "B"
    if text.startswith("S"):
        return "S"
    if text.startswith("T"):
        return "T"
    return ""


def _norm_direction(value: Any) -> str:
    text = _clean_text(value).upper().replace(" ", "").replace("_", "").replace("-", "")
    if text in {"L", "LONG", "LONGITUDINAL"}:
        return "L"
    if text in {"LT", "LONGTRANSVERSAL", "LONGTRANSVERSE", "LONGTRANSV", "TRANSVERSE", "TRANSVERSAL"}:
        return "LT"
    if "TRANS" in text:
        return "LT"
    return "L" if text else ""


def is_materialdb_clean_long_format(df: pd.DataFrame) -> bool:
    """Detect the XML-derived clean long-format CSV files.

    These files have one row per Material + Thickness + Basis + Direction.
    The older GUI expects one wide row with columns such as Tensile_Str_L_A.
    """
    required = {
        "Element", "Series", "Material", "Temper", "Form",
        "Basis", "GrainOrientation", "UltTensileStrength",
        "TensileYield", "YoungsModulus", "Density",
    }
    return required.issubset(set(map(str, df.columns)))


def convert_materialdb_clean_to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Convert XML-derived clean long-format MaterialDB CSV to the legacy GUI-wide schema.

    Input rows:
        Material + Thickness + Basis + GrainOrientation + property values

    Output row:
        Material + Thickness with A/B/S and L/LT values spread into columns:
        Tensile_Str_L_A, Tensile_Str_LT_A, Tensile_Yield_L_B, etc.

    This adapter is intentionally conservative: it does not invent values. Blank
    source cells remain '-'. Failure-sensitive outputs are later calculated only
    when the selected material row has the needed source values.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy().fillna("-")
    df.columns = [str(c).strip() for c in df.columns]


    if "Spec1_1" not in df.columns:
        df["Spec1_1"] = df.get("Specification", "-")
    if "MMPDS_Version" not in df.columns:
        df["MMPDS_Version"] = df.get("MmpdsVersion", "-")
    if "Thick_Value" not in df.columns:
        df["Thick_Value"] = df_first_existing_series(df, THICKNESS_VALUE_COLUMNS, default="-")
    if "Wall_Thick" not in df.columns:
        df["Wall_Thick"] = df_first_existing_series(df, WALL_THICKNESS_COLUMNS, default="-")
    if "Cross_Section" not in df.columns:
        df["Cross_Section"] = df_first_existing_series(df, CROSS_SECTION_VALUE_COLUMNS, default="-")
    if "Material_Card_Name" not in df.columns:
        df["Material_Card_Name"] = df.get("MatCardName", "-")
    if "Spec2_1" not in df.columns:
        df["Spec2_1"] = df.get("Specification2", df.get("Specification 2", df.get("Spec2", "-")))
    if "Spec2_2" not in df.columns:
        df["Spec2_2"] = "-"

    meta_cols = [
        "Element", "Series", "Material", "Temper", "Specification", "Form",
        "Spec1_1", "Spec1_2", "Spec1_3", "Spec1_4", "Spec2_1", "Spec2_2",
        "MatCardName", "Material_Card_Name", "MMPDS_Version", "MmpdsVersion",
        "MmpdsReleaseDate", "MaterialDate", "DataEntry", "ReviewedBy",
        "ThicknessNumber", "ThicknessOrDia", "WallThickness", "Thick_Value",
        "Wall_Thick", "CrossSectionArea", "Cross_Section",
        "LocationInCasting", "StrengthClass",
    ]
    group_cols = [c for c in meta_cols if c in df.columns]


    required_group = [
        "Element", "Series", "Material", "Temper", "Specification", "Form",
        "Spec1_1", "Spec2_1", "Spec2_2", "MatCardName", "Material_Card_Name", "MMPDS_Version",
        "ThicknessNumber", "ThicknessOrDia", "WallThickness", "Thick_Value",
        "Wall_Thick", "CrossSectionArea", "Cross_Section",
        "LocationInCasting", "StrengthClass",
    ]
    group_cols = [c for c in required_group if c in df.columns]

    prop_map = {
        "UltTensileStrength": "Tensile_Str",
        "TensileYield": "Tensile_Yield",
        "CompressionYield": "Compress_Yield",
        "UltShearStrength": "Shear_Str",
        "ElongAtBreak": "Elong",
        "YoungsModulus": "Youngs_Mod",
        "YoungsModulusComp": "Youngs_Mod_Comp",
        "ShearModulus": "Shear_Mod",
        "PoissonsRatio": "Poissons_Ratio",
        "Density": "Density",
    }

    wide_rows: List[Dict[str, Any]] = []


    for keys, group in df.groupby(group_cols, sort=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        out = {col: _clean_text(val) for col, val in zip(group_cols, keys)}


        out["Spec1_1"] = _clean_text(out.get("Spec1_1", out.get("Specification", "-")))
        out["Spec2_1"] = _clean_text(out.get("Spec2_1", "-"))
        out["Spec2_2"] = _clean_text(out.get("Spec2_2", "-"))
        out["MMPDS_Version"] = _clean_text(out.get("MMPDS_Version", out.get("MmpdsVersion", "-")))


        out["Thick_Value"] = _clean_text(first_nonblank_value(
            out.get("Thick_Value", ""),
            out.get("ThicknessOrDia", ""),
            out.get("Thickness", ""),
            out.get("Thickness Range", ""),
            default="-",
        ))
        out["Wall_Thick"] = _clean_text(first_nonblank_value(
            out.get("Wall_Thick", ""),
            out.get("WallThickness", ""),
            out.get("Wall Thickness", ""),
            default="-",
        ))
        out["Cross_Section"] = _clean_text(first_nonblank_value(
            out.get("Cross_Section", ""),
            out.get("CrossSectionArea", ""),
            out.get("C_S", ""),
            out.get("CS", ""),
            default="-",
        ))
        out["Material_Card_Name"] = _clean_text(out.get("Material_Card_Name", out.get("MatCardName", "-")))


        for _idx, row in group.iterrows():
            basis = _norm_basis(row.get("Basis", ""))
            direction = _norm_direction(row.get("GrainOrientation", ""))
            if basis not in {"A", "B", "S"} or direction not in {"L", "LT"}:
                continue

            for source_col, gui_prefix in prop_map.items():
                if source_col not in group.columns:
                    continue
                value = _clean_text(row.get(source_col, "-"))
                if is_blank(value):
                    continue


                out[f"{gui_prefix}_{direction}_{basis}"] = value


                if gui_prefix in {"Shear_Mod", "Poissons_Ratio", "Density"}:
                    out.setdefault(f"{gui_prefix}_{basis}", value)

        wide_rows.append(out)

    wide = pd.DataFrame(wide_rows).fillna("-")

    wide = wide.astype(str)
    return wide


class SourceImageIndex:
    """Fast source-image metadata index.

    This combines an image metadata cache + optional DuckDB mirror:
    - Avoids scanning the J: image folder every time Screen 2 opens.
    - Searches material/temper/spec tokens from a local JSON index.
    - If DuckDB is installed, writes the same index to a DuckDB table.
    """
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

    def __init__(self, folders: List[Path], index_file: Path, duckdb_file: Path | None = None):
        self.folders = [Path(f) for f in folders]
        self.index_file = Path(index_file)
        self.duckdb_file = Path(duckdb_file) if duckdb_file else None
        self.records: List[Dict[str, Any]] = []
        self.loaded = False
        self.refreshing = False
        self.last_error = ""
        self._lock = threading.Lock()
        self._image_signature_cache: Dict[str, Tuple[Any, ...]] = {}

    @staticmethod
    def _safe_token(value: Any) -> str:
        text = str(value).strip()
        if not text or text in ("-", NO_SPEC_DISPLAY):
            return ""
        for ch in [" ", "/", "\\", ":", "*", "?", '"', "<", ">", "|", ",", ".", "(", ")", "[", "]"]:
            text = text.replace(ch, "_")
        while "__" in text:
            text = text.replace("__", "_")
        return text.strip("_").lower()

    def _available_folders(self) -> List[Path]:
        return [f for f in self.folders if f.exists()]

    def _load_cache(self) -> bool:
        if not self.index_file.exists():
            return False
        try:
            payload = json.loads(self.index_file.read_text(encoding="utf-8"))
            records = payload.get("records", [])

            records = [r for r in records if Path(r.get("path", "")).exists()]
            with self._lock:
                self.records = records
                self.loaded = True
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def _save_cache(self, records: List[Dict[str, Any]]) -> None:
        try:
            self.index_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "folders": [str(f) for f in self._available_folders()],
                "count": len(records),
                "records": records,
            }
            self.index_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            self.last_error = str(exc)
        self._write_duckdb(records)

    def _write_duckdb(self, records: List[Dict[str, Any]]) -> None:
        if not self.duckdb_file:
            return
        try:
            import duckdb
            self.duckdb_file.parent.mkdir(parents=True, exist_ok=True)
            con = duckdb.connect(str(self.duckdb_file))
            df = pd.DataFrame(records)
            if df.empty:
                df = pd.DataFrame(columns=["path", "stem", "stem_norm", "suffix", "folder", "mtime", "size"])
            con.register("image_records_df", df)
            con.execute("CREATE OR REPLACE TABLE source_images AS SELECT * FROM image_records_df")
            con.close()
        except Exception as exc:

            self.last_error = str(exc)

    def refresh(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        seen = set()
        for folder in self._available_folders():
            try:
                files = [p for p in folder.rglob("*") if p.suffix.lower() in self.IMAGE_EXTENSIONS]
            except Exception as exc:
                self.last_error = str(exc)
                files = []
            for p in files:
                try:
                    path_text = str(p)
                    if path_text in seen:
                        continue
                    seen.add(path_text)
                    stat = p.stat()
                    records.append({
                        "path": path_text,
                        "stem": p.stem,
                        "stem_norm": self._safe_token(p.stem),
                        "suffix": p.suffix.lower(),
                        "folder": str(folder),
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                    })
                except Exception:
                    continue
        with self._lock:
            self.records = records
            self.loaded = True
        self._save_cache(records)
        return records

    def refresh_async(self) -> None:
        if self.refreshing:
            return
        self.refreshing = True

        def worker():
            try:

                self._load_cache()
                self.refresh()
            finally:
                self.refreshing = False

        threading.Thread(target=worker, daemon=True).start()

    def ensure_loaded(self) -> bool:
        """Load the source-image index without freezing the UI.

        An existing JSON cache is used immediately. If no cache is available,
        a background refresh starts and the method returns False until records
        are ready for searching.
        """
        if self.loaded:
            return True
        if self._load_cache():
            return True
        self.refresh_async()
        return False

    def _image_unique_signature(self, path: Path) -> Tuple[Any, ...]:
        """Return a stable signature so duplicated source pictures count once.

        Some MMPDS materials can match two image records that are actually the
        same picture.  The GUI should show/count/export unique pictures, not
        duplicated records.  We first normalize the path, then use file size +
        content hash when the file is available.  The hash is cached so repeated
        View Image / Card Screen calls stay fast.
        """
        try:
            p = Path(path)
            try:
                cache_key = str(p.resolve()).casefold()
            except Exception:
                cache_key = str(p).casefold()

            cached = self._image_signature_cache.get(cache_key)
            if cached is not None:
                return cached

            try:
                stat = p.stat()
                digest = hashlib.md5()
                with p.open("rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        digest.update(chunk)
                signature = ("content", int(stat.st_size), digest.hexdigest())
            except Exception:
                signature = ("path", cache_key)

            if len(self._image_signature_cache) > 5000:
                self._image_signature_cache.clear()
            self._image_signature_cache[cache_key] = signature
            return signature
        except Exception:
            return ("path", str(path).casefold())

    def _unique_image_paths(self, paths: List[Path]) -> List[Path]:
        """Keep only unique image files while preserving best-match order."""
        unique: List[Path] = []
        seen = set()
        for raw_path in paths or []:
            try:
                path = Path(raw_path)
                signature = self._image_unique_signature(path)
            except Exception:
                path = Path(str(raw_path))
                signature = ("path", str(path).casefold())
            if signature in seen:
                continue
            seen.add(signature)
            unique.append(path)
        return unique

    def search(self, parts: Dict[str, str], max_results: int = MAX_SOURCE_IMAGES) -> Tuple[List[Path], int]:
        self.ensure_loaded()
        with self._lock:
            records = list(self.records)


        if not records:
            return [], 0

        material = self._safe_token(parts.get("material", ""))
        temper = self._safe_token(parts.get("temper", ""))
        spec = self._safe_token(parts.get("spec", ""))
        form = self._safe_token(parts.get("form", ""))
        element = self._safe_token(parts.get("element", ""))

        material_digits = "".join(ch for ch in material if ch.isdigit())
        spec_digits = "".join(ch for ch in spec if ch.isdigit())

        scored = []
        for rec in records:
            stem = rec.get("stem_norm", "")
            if not stem:
                continue

            has_material = bool(material_digits and material_digits in stem) or bool(material and material in stem)
            has_temper = bool(temper and temper in stem)
            has_spec = bool((spec_digits and spec_digits in stem) or (spec and spec in stem))
            has_form = bool(form and form in stem)
            has_element = bool(element and element in stem)

            if material and not has_material:
                continue
            if temper and not has_temper:
                continue
            if spec and not has_spec:
                continue

            score = 0
            if has_material:
                score += 50
            if has_temper:
                score += 30
            if has_spec:
                score += 25
            if has_form:
                score += 5
            if has_element:
                score += 2
            scored.append((score, len(rec.get("path", "")), rec.get("path", ""), rec))

        scored.sort(key=lambda x: (-x[0], x[1], x[2]))
        paths = self._unique_image_paths([Path(item[3]["path"]) for item in scored])
        total = len(paths)
        return paths[:max_results], total

class DebouncedCallback:
    """Debounce rapid callback invocations."""
    def __init__(self, callback, delay_ms: int = 300):
        self.callback = callback
        self.delay_ms = delay_ms
        self.timer = None

    def __call__(self, *args, **kwargs):
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(self.delay_ms / 1000, self._run, args=args, kwargs=kwargs)
        self.timer.daemon = True
        self.timer.start()

    def _run(self, *args, **kwargs):
        self.timer = None
        self.callback(*args, **kwargs)

    def cancel(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None


class MaterialDatabase:
    """Fast in-memory material database without cache file.

    Speed comes from:
    1. Reading the master CSV only once at startup.
    2. Building a lightweight in-memory selection index once.
    3. Using normalized columns for fast filtering.
    4. Caching dropdown results only during the current app session.
    """

    def __init__(self):
        self.errors = []
        self.lookups = {}
        self.master = pd.DataFrame()
        self.master_columns = []
        self.selection_df = pd.DataFrame()
        self._available_cache = {}
        self._filter_cache = {}

        self._load_lookups()
        self._material_to_series = self._build_material_to_series()
        self._load_master()
        self._augment_material_to_series_from_master()
        self._build_runtime_helper_columns()
        self._build_selection_index()

    def _load_lookups(self):
        if not DROPDOWN_DIR.exists():
            return

        files = [p for p in DROPDOWN_DIR.iterdir() if p.suffix.lower() == ".csv"]
        for key, words in LOOKUP_FILES.items():
            found = None
            for p in files:
                stem = p.stem.lower()
                if any(w in stem for w in words):
                    found = p
                    break

            if found:
                try:
                    self.lookups[key] = read_csv_safely(found)
                except Exception:
                    self.lookups[key] = pd.DataFrame()
            else:
                self.lookups[key] = pd.DataFrame()

    def _build_material_to_series(self):
        df = self.lookups.get("material", pd.DataFrame())
        if df.empty:
            return {}

        name_col = find_col(df, "Name", "Material")
        series_col = find_col(df, "SeriesID", "Series")
        if not name_col or not series_col:
            return {}

        out = {}
        for _, r in df.iterrows():
            name = str(r[name_col]).strip()
            series = str(r[series_col]).strip()
            if not is_blank(name) and not is_blank(series):
                out[norm(name)] = series
        return out

    def _augment_material_to_series_from_master(self):
        """Fill missing Series mappings from Metal_Data_ABS-Basis_V3.csv itself."""
        if self.master is None or self.master.empty:
            return
        try:
            mat_col = find_col(self.master, "Material")
            elem_col = find_col(self.master, "Element")
            if not mat_col:
                return
            for _, row in self.master.iterrows():
                material = str(row.get(mat_col, "")).strip()
                if not material or is_blank(material):
                    continue
                key = norm(material)
                if key in self._material_to_series and not is_blank(self._material_to_series.get(key, "")):
                    continue
                element = str(row.get(elem_col, "")).strip() if elem_col else ""
                series = _source_series_from_master_value(element, material)
                if series:
                    self._material_to_series[key] = series
        except Exception as exc:
            logger.warning("Could not infer Series from master CSV: %s", exc)

    def _load_master(self):
        """Load material data from only Data/Metal_Data_ABS-Basis_V3.csv.

        This version intentionally does not fall back to MaterialDB_clean_ALL.csv.
        That keeps every GUI filter, thickness row, material card, and export
        tied to the same approved master CSV the user is reviewing.
        """
        legacy_path = DATA_DIR / MASTER_FILE
        if not legacy_path.exists():
            self.errors.append(
                f"Missing approved material data file:\n"
                f"  {legacy_path}\n\n"
                f"Place {MASTER_FILE} in the Data folder. This version does not use {CLEAN_MASTER_FILE}."
            )
            self.master = pd.DataFrame()
            self.master_columns = []
            return

        try:
            self.master = read_csv_safely(legacy_path).astype(str).fillna("-")
            self.master_columns = list(self.master.columns)
            logger.info("Loaded approved master material CSV only: %s (%s rows)", legacy_path, len(self.master))
        except Exception as e:
            self.errors.append(f"Could not read material data from {legacy_path}: {e}")
            self.master = pd.DataFrame()
            self.master_columns = []

    def _master_cols(self):
        cols = set(self.master_columns or list(self.master.columns))
        lower_map = {norm(c): c for c in cols}

        def pick(*names):
            for name in names:
                if norm(name) in lower_map:
                    return lower_map[norm(name)]
            return None

        return {
            "Element": pick("Element"),
            "Material": pick("Material"),
            "Temper": pick("Temper"),
            "Specification": pick("Spec1_1", "spec1_1", "Specification"),
            "Specification 2": pick("Spec2_1", "Spec2_2", "Spec2", "Specification 2", "Specification2"),
            "Form": pick("Form"),
        }

    @staticmethod
    def _display_spec(v):
        return NO_SPEC_DISPLAY if is_blank(v) else str(v).strip()

    def _combined_spec2_series(self) -> pd.Series:
        """Build the visible Specification 2 column from all secondary spec columns."""
        if self.master.empty:
            return pd.Series([], dtype=str)
        candidates = [
            find_col(self.master, "Specification 2", "Specification2", "Spec2", "Spec2_1"),
            find_col(self.master, "Spec2_2"),
            find_col(self.master, "Spec2_3"),
            find_col(self.master, "Spec2_4"),
        ]
        candidates = [c for c in candidates if c]
        if not candidates:
            return pd.Series([NO_SPEC_DISPLAY] * len(self.master), index=self.master.index)
        values = []
        for _, row in self.master.iterrows():
            values.append(display_spec_value(first_nonblank_value(*(row.get(c, "") for c in candidates))))
        return pd.Series(values, index=self.master.index)

    def _build_runtime_helper_columns(self):
        """Precompute Advanced Selection helper columns from the approved CSV.

        The master file has legitimate cases where the same visible Thick_Value
        repeats for the same material/spec/form but represents a different source
        row because Cross_Section, Wall_Thick, Location, Strength Class, or MatID
        is different. Earlier GUI filtering collapsed those duplicate thickness
        labels. This builds duplicate-aware labels so every source combination can
        appear and map back to the exact row.
        """
        if self.master is None or self.master.empty:
            return
        try:
            self.master["__adv_row_key"] = [f"idx:{idx}" for idx in self.master.index]

            base_values: List[str] = []
            group_keys: List[Tuple[str, ...]] = []
            suffix_parts: List[List[str]] = []
            matids: List[str] = []

            for idx, row in self.master.iterrows():
                try:
                    base_label = source_thickness_display_label(row) or "NA"
                except Exception:
                    base_label = "NA"
                try:
                    base_value = source_thickness_base_value(row, prefer_wall=False) or base_label
                except Exception:
                    base_value = base_label
                base_values.append(str(base_value))

                spec1 = display_spec_value(row_get_first_nonblank_tolerant(row, "Spec1_1", "spec1_1", "Specification", default=""))
                spec2 = display_spec_value(row_spec2_value(row))
                group_keys.append(tuple(norm(v) for v in [
                    row_get_first_nonblank_tolerant(row, "Element", default=""),
                    row_get_first_nonblank_tolerant(row, "Material", default=""),
                    row_get_first_nonblank_tolerant(row, "Temper", default=""),
                    spec1,
                    spec2,
                    row_get_first_nonblank_tolerant(row, "Form", default=""),
                    base_label,
                ]))

                pieces: List[str] = []
                try:
                    cs = source_cross_section_value(row)
                    piece = _source_row_label_piece("CS", cs)
                    if piece:
                        pieces.append(piece)
                except Exception:
                    pass
                try:
                    wall = row_get_first_nonblank_tolerant(row, "Wall_Thick", "Wall Thick", "WallThickness", "Wall Thickness", default="")
                    piece = _source_row_label_piece("Wall", wall)
                    if piece:
                        pieces.append(piece)
                except Exception:
                    pass
                try:
                    loc = row_get_first_nonblank_tolerant(row, "Loc_In_Casting", "LocationInCasting", "Location In Casting", default="")
                    piece = _source_row_label_piece("Loc", loc)
                    if piece:
                        pieces.append(piece)
                except Exception:
                    pass
                try:
                    strength = row_get_first_nonblank_tolerant(row, "Str_Class_Num", "StrengthClass", "Strength Class", default="")
                    piece = _source_row_label_piece("Class", strength)
                    if piece:
                        pieces.append(piece)
                except Exception:
                    pass
                suffix_parts.append(pieces)

                try:
                    mid = row_get_first_nonblank_tolerant(row, "MatID", "Material ID", "Material_ID", "MID", default="")
                except Exception:
                    mid = ""
                matids.append(str(mid).strip())

            from collections import Counter
            group_counts = Counter(group_keys)

            preliminary_labels: List[str] = []
            for i in range(len(base_values)):
                base_label = str(base_values[i] if base_values[i] else "NA")
                if group_counts[group_keys[i]] > 1:
                    pieces = suffix_parts[i]
                    preliminary_labels.append(base_label + (" | " + " | ".join(pieces) if pieces else ""))
                else:
                    preliminary_labels.append(base_label)

            label_counts = Counter((group_keys[i], norm(preliminary_labels[i])) for i in range(len(preliminary_labels)))
            final_labels: List[str] = []
            for i, label in enumerate(preliminary_labels):
                final_label = str(label or "NA")
                if label_counts[(group_keys[i], norm(final_label))] > 1:
                    mid = matids[i] or str(self.master.index[i])
                    final_label = f"{final_label} | MatID {mid}"
                final_labels.append(final_label)

            self.master["__adv_thickness_label"] = final_labels
            self.master["__adv_thickness_norm"] = [norm(v) for v in final_labels]
            self.master["__adv_thickness_base_norm"] = [norm(v) for v in base_values]
        except Exception as exc:
            logger.warning("Could not build Advanced Selection helper columns: %s", exc)

    def _build_selection_index(self):
        """Build a small in-memory index for fast Screen 1 filtering."""
        if self.master.empty:
            self.selection_df = pd.DataFrame(columns=STAGES)
            return

        cols = self._master_cols()
        idx = pd.DataFrame(index=self.master.index)

        for stage in ["Element", "Material", "Temper", "Form"]:
            col = cols.get(stage)
            idx[stage] = self.master[col].astype(str).str.strip() if col else ""

        spec_col = cols.get("Specification")
        idx["Specification"] = self.master[spec_col].map(self._display_spec) if spec_col else NO_SPEC_DISPLAY
        idx["Specification 2"] = self._combined_spec2_series()


        series_col = find_col(self.master, "Series")
        if series_col:
            idx["Series"] = self.master[series_col].astype(str).str.strip()
            missing_series = idx["Series"].map(is_blank)
            if missing_series.any():
                idx.loc[missing_series, "Series"] = [
                    self._material_to_series.get(norm(mat), _source_series_from_master_value(elem, mat))
                    for mat, elem in zip(idx.loc[missing_series, "Material"], self.master.loc[missing_series, "Element"] if "Element" in self.master.columns else [""] * int(missing_series.sum()))
                ]
        else:
            idx["Series"] = [
                self._material_to_series.get(norm(row.get("Material", "")), _source_series_from_master_value(row.get("Element", ""), row.get("Material", "")))
                for _, row in self.master.iterrows()
            ]


        for stage in STAGES:
            idx[f"{stage}__norm"] = idx[stage].map(norm)

        self.selection_df = idx

    def _cache_key(self, selections: dict, exclude_stage: str | None = None):
        return (exclude_stage, tuple((s, selections.get(s, "")) for s in STAGES))

    def _selection_mask(self, selections: dict, exclude_stage: str | None = None):
        if self.selection_df.empty:
            return pd.Series([], dtype=bool)

        mask = pd.Series(True, index=self.selection_df.index)

        for stage, value in selections.items():
            if stage == exclude_stage or not value:
                continue

            norm_col = f"{stage}__norm"
            if norm_col in self.selection_df.columns:
                mask &= self.selection_df[norm_col].eq(norm(value))

        return mask

    def filter_master(self, selections: dict, exclude_stage: str | None = None):
        key = self._cache_key(selections, exclude_stage)
        if key in self._filter_cache:
            return self._filter_cache[key].copy()

        if self.master.empty:
            return pd.DataFrame()

        mask = self._selection_mask(selections, exclude_stage)
        result = self.master.loc[mask].copy()

        if len(self._filter_cache) > 300:
            self._filter_cache.clear()
        self._filter_cache[key] = result

        return result.copy()

    def available(self, stage: str, selections: dict):
        key = ("available", stage, self._cache_key(selections, exclude_stage=stage))
        if key in self._available_cache:
            return self._available_cache[key]

        if self.selection_df.empty or stage not in self.selection_df.columns:
            return []

        mask = self._selection_mask(selections, exclude_stage=stage)
        vals = self.selection_df.loc[mask, stage]

        if stage in {"Specification", "Specification 2"}:
            values = {str(v).strip() for v in vals if str(v).strip()}
            result = sorted(values, key=lambda x: (x == NO_SPEC_DISPLAY, x.lower()))
        else:
            values = {str(v).strip() for v in vals if not is_blank(v)}
            result = sorted(values, key=str.lower)

        if len(self._available_cache) > CACHE_SIZE_LIMIT:
            self._available_cache.clear()
        self._available_cache[key] = result

        return result

    def match_count(self, selections: dict) -> int:
        key = ("count", self._cache_key(selections))
        if key in self._available_cache:
            return self._available_cache[key]

        mask = self._selection_mask(selections)
        count = int(mask.sum())

        if len(self._available_cache) > CACHE_SIZE_LIMIT:
            self._available_cache.clear()
        self._available_cache[key] = count

        return count


class HistoryStore:
    def load(self):
        if not HISTORY_FILE.exists():
            return []
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []

    def save(self, entries):
        try:
            HISTORY_FILE.write_text(json.dumps(entries[:100], indent=2), encoding="utf-8")
        except Exception:
            pass

    def append(self, entry):
        entries = self.load()
        entries.insert(0, entry)
        self.save(entries)
        return entries
