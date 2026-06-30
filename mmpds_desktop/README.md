# MMPDS Material Selector — modular package

A behavior-preserving modular refactor of the original 23,281-line single-file
Tkinter app (`legacy/MMPDS_Version6_2_original.py`).

## Structure

```
mmpds_desktop/
├── main.py                  # entry point: DPI → MaterialDatabase → MaterialSelectorApp → mainloop
├── config/
│   └── settings.py          # constants, file paths, palette/theme values, defaults, logging
├── models/
│   └── app_state.py         # data classes + shared state (DefaultCombo, MaterialDatabase,
│                            #   FastMaterialEngine, HistoryStore, SourceImageIndex,
│                            #   DebouncedCallback, export-counter) — no Tkinter
├── calculations/
│   └── conversions.py       # pure compute: unit conversions, formatting, row/spec parsing — no UI
├── ui/
│   ├── main_window.py       # the 3 screen classes + all revision/monkey-patch logic
│   ├── widgets.py           # reusable widgets: TkDebouncer, LazyImageCache, bind_mousewheel, DPI
│   └── dialogs.py           # dialog/toast home (see file docstring)
├── tests/
│   ├── test_calculations.py
│   └── test_models.py
└── legacy/
    └── MMPDS_Version6_2_original.py   # pristine original, kept as the equivalence reference
```

## Dependency direction

Everything points inward; the inner layers never import UI or Tkinter:

```
main ──► config
 │   ──► models ──► calculations ──► config
 └─► ui ──► (config, calculations, models, ui.widgets)
```

`config`, `calculations` and `models` import cleanly with Tkinter absent
(enforced by the build tooling and exercised by the tests).

## Running

From the repository root:

```bash
python -m mmpds_desktop.main
```

The app expects its data files (`Data/Metal_Data_ABS-Basis_V3.csv`, etc.) and
the `selection_history.json` / `export_counter.json` files relative to the
package root — the same layout the original script used from its own directory.

## Tests

```bash
python -m pytest mmpds_desktop/tests/
```

## How the split was verified

The refactor moves code **verbatim**: `_build_package.py` partitions every line
of the original into exactly one destination module (verified to reconstruct the
original byte-for-byte) and auto-generates the cross-module imports. A
namespace-equivalence check then confirmed that, against the original monolith,
every class has an identical attribute set, every method (including all
order-dependent "last-wins" monkey-patches) resolves to a source-identical
function, and all constants match — so runtime behavior is unchanged.
