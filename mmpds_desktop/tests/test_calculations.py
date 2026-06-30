"""Tests for the pure calculations layer (no Tkinter, no data files).

These exercise mmpds_desktop.calculations.conversions in isolation and also
pin down the *live* (last-wins) behavior of the helpers that were defined more
than once in the original monolith.
"""
from __future__ import annotations

import pandas as pd
import pytest

from mmpds_desktop.calculations import conversions as c


def test_norm():
    assert c.norm(None) == ""
    assert c.norm("  AbC ") == "abc"
    assert c.norm(123) == "123"


def test_is_blank_live_semantics():
    # The live (last definition) of is_blank treats only these as blank.
    for v in ["", "-", "nan", "none", None, "  ", "NONE"]:
        assert c.is_blank(v) is True, v
    # ...and these are NOT blank in the live version (the early, dead definition
    # would have treated "na"/"n/a"/"null" as blank — behavior we preserved).
    for v in ["na", "n/a", "null", "x", "0", "AMS"]:
        assert c.is_blank(v) is False, v


def test_clean_text():
    assert c.clean_text(None, "d") == "d"
    assert c.clean_text("-", "d") == "d"
    assert c.clean_text("  hi ") == "hi"


def test_normalized_col_key_and_row_get():
    row = pd.Series({"Tensile_Yield": "50", "Material": "7075"})
    # spaces / underscores / case are normalized away when matching columns
    assert c.row_get(row, "Tensile Yield") == "50"
    assert c.row_get(row, "material") == "7075"
    assert c.row_get(row, "missing", default="NA") == "NA"


def test_display_spec():
    assert c.display_spec("-") == c.NO_SPEC_DISPLAY
    assert c.display_spec("") == c.NO_SPEC_DISPLAY
    assert c.display_spec("AMS4045") == "AMS4045"


def test_try_float():
    assert c.try_float("2.5") == 2.5
    assert c.try_float("abc") is None
    assert c.try_float(None) is None


def test_fmt_number():
    assert c.fmt_number("2.5000") == "2.500"
    assert c.fmt_number("3") == "3.000"
    assert c.fmt_number("abc") == "-"


def test_safe_divide():
    assert c.safe_divide(10, 2) == 5
    assert c.safe_divide(10, 0) == 0          # default on divide-by-zero
    assert c.safe_divide(10, 0, default=-1) == -1
    assert c.safe_divide(None, 2) == 0


def test_clamp():
    assert c.clamp(5, 0, 3) == 3
    assert c.clamp(-1, 0, 3) == 0
    assert c.clamp(2, 0, 3) == 2


def test_dropdown_and_edit_marks_roundtrip():
    assert c.strip_dropdown_mark(c.with_dropdown_mark("x")) == "x"
    assert c.strip_edit_box(c.with_edit_box("y")) == "y"


def test_duplicate_detection():
    items = [
        {"Material": "7075", "Element": "Al", "Temper": "T6"},
        {"Material": "7075", "Element": "Al", "Temper": "T6"},
        {"Material": "2024", "Element": "Al", "Temper": "T3"},
    ]
    marked = c.mark_duplicate_items([dict(i) for i in items])
    assert marked[0]["_duplicate"] and marked[1]["_duplicate"]
    assert marked[2]["_duplicate"] is False

    dedup = c.remove_duplicate_items(items)
    assert len(dedup) == 2
    assert all(it["_duplicate"] is False for it in dedup)


def test_convert_value_returns_value_and_label():
    out = c.convert_value("100", "stress", "mm_T_s")
    assert isinstance(out, tuple) and len(out) == 2
    assert out[0] == "100"
    assert isinstance(out[1], str)


def test_unit_label_helpers_return_strings():
    assert isinstance(c.source_unit_label("stress"), str)
    assert isinstance(c.converted_unit_label("stress", "mm_T_s"), str)
