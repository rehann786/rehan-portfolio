from __future__ import annotations

from tkinter import messagebox
import sys
import tkinter as tk

from mmpds_desktop.ui.main_window import MaterialSelectorApp
from mmpds_desktop.models.app_state import MaterialDatabase
from mmpds_desktop.ui.widgets import enable_windows_dpi_awareness


# End marker for VS Code search:
# REHAN_ADVANCED_SELECTION_EXCEL_NOTES_CUSTOM_FIX_2026_06_22

def main():
    """Start the app after loading required data."""
    enable_windows_dpi_awareness()

    try:
        db = MaterialDatabase()
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Data Error", str(e))
        root.destroy()
        return 1

    if db.errors:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Data Error", "\n".join(db.errors))
        root.destroy()
        return 1

    app = MaterialSelectorApp(db)
    app.mainloop()
    return 0


# End marker for VS Code search:
# SAMUEL_GISSMO_EXPORT_CURVE_ELONGATION_REQUIRED_FIX_ACTIVE_2026_06_25
if __name__ == "__main__":
    sys.exit(main())
