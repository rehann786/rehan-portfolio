"""Tests for the pure models/state layer (no Tkinter, no GUI).

Verifies the data classes, the export-counter subsystem and the cached
FastMaterialEngine in isolation, with file-backed state redirected to tmp_path.
"""
from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from mmpds_desktop.models import app_state as m


def test_models_layer_has_no_tkinter():
    import sys
    # Importing the models layer must never pull in Tkinter (dependency rule).
    assert "tkinter" not in sys.modules


def test_defaultcombo_dataclass():
    dc = m.DefaultCombo()
    assert dc.basis == "" and dc.direction == "" and dc.matcard == "" and dc.count == 0
    dc2 = m.DefaultCombo(basis="B", direction="L", matcard="MAT024", count=3)
    assert (dc2.basis, dc2.direction, dc2.matcard, dc2.count) == ("B", "L", "MAT024", 3)
    # frozen dataclass -> immutable
    with pytest.raises(dataclasses.FrozenInstanceError):
        dc2.basis = "A"


def test_normalize_export_id():
    # in-range values pass through (commas are tolerated)
    assert m.normalize_export_id("1234") == 1234
    assert m.normalize_export_id(5000) == 5000
    assert m.normalize_export_id("2,500") == 2500
    # values below the start are clamped up to EXPORT_COUNTER_START
    assert m.normalize_export_id(42) == m.EXPORT_COUNTER_START
    # unparseable -> default, which is then also clamped to the valid range
    assert m.normalize_export_id("not-a-number") == m.EXPORT_COUNTER_START
    assert m.normalize_export_id(None, default=7000) == 7000
    # above the maximum is rejected
    with pytest.raises(RuntimeError):
        m.normalize_export_id(m.EXPORT_COUNTER_MAX + 1)


def test_export_counter_reserve_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "EXPORT_COUNTER_FILE", tmp_path / "counter.json")
    monkeypatch.setattr(m, "EXPORT_COUNTER_LOCK_DIR", tmp_path / "counter.lock")
    monkeypatch.setattr(m, "SESSION_NEXT_EXPORT_ID", m.EXPORT_COUNTER_START)

    first = m.reserve_next_export_id()
    second = m.reserve_next_export_id()
    assert isinstance(first, int) and isinstance(second, int)
    assert second >= first                     # ids advance, never go backwards
    assert isinstance(m.peek_next_export_id(), int)
    assert isinstance(m.export_counter_status_text(), str)


def test_history_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "HISTORY_FILE", tmp_path / "history.json")
    store = m.HistoryStore()
    assert store.load() == []                  # missing file -> empty
    store.save([{"a": 1}])
    assert store.load() == [{"a": 1}]
    store.append({"b": 2})
    loaded = store.load()
    assert loaded[0] == {"b": 2}               # append inserts at the front


def test_history_store_handles_corrupt_file(tmp_path, monkeypatch):
    hist = tmp_path / "history.json"
    hist.write_text("not-json{", encoding="utf-8")
    monkeypatch.setattr(m, "HISTORY_FILE", hist)
    assert m.HistoryStore().load() == []       # corrupt file -> empty, no raise


def test_debounced_callback_collapses_rapid_calls():
    import time
    calls = []
    cb = m.DebouncedCallback(lambda *a: calls.append(a), delay_ms=40)
    cb("x")
    cb("y")          # supersedes the first within the debounce window
    time.sleep(0.25)
    assert calls == [("y",)]


def _synthetic_master():
    return pd.DataFrame({
        "Element": ["Aluminum", "Aluminum", "Steel"],
        "Series": ["7000", "7000", "Carbon"],
        "Material": ["7075", "7075", "1018"],
        "Temper": ["T6", "T73", "Annealed"],
        "Specification": ["AMS1", "AMS1", "AMS9"],
        "Specification 2": ["-", "-", "-"],
        "Form": ["Sheet", "Plate", "Bar"],
    })


def test_fast_material_engine_available_stage_and_filter():
    eng = m.FastMaterialEngine(_synthetic_master())
    elements = eng.available_stage("Element", None)
    assert "Aluminum" in elements and "Steel" in elements

    tempers = eng.available_stage("Temper", {"Material": "7075"})
    assert set(tempers) == {"T6", "T73"}

    rows = eng.base_rows({"Material": "7075"})
    assert len(rows) == 2
    assert len(eng.base_rows({"Element": "Steel"})) == 1


def test_fast_material_engine_empty_frame_is_safe():
    eng = m.FastMaterialEngine(pd.DataFrame())
    assert eng.available_stage("Element", None) == []
    assert len(eng.base_rows({"Material": "7075"})) == 0
