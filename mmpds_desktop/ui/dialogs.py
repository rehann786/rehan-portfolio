"""Dialogs, popups and toast notifications.

In the original single-file application these were not standalone functions:

* the toast/notification system is ``MaterialSelectorApp.show_toast`` (and the
  related ``_reapply_theme`` status messaging) — see :mod:`ui.main_window`;
* the export-log popup is ``SelectionScreen._export_log_dialog``;
* every other user-facing alert is an inline ``tkinter.messagebox`` /
  ``tkinter.filedialog`` call inside the screen methods.

To honour the "pure restructuring, no behaviour change" constraint, those
instance methods were deliberately left attached to their classes instead of
being carved out into this module: lifting a method out of a class body changes
how it is defined and bound, which is exactly the kind of behavioural risk this
refactor avoids.

This module is the designated home for that dialog code once it is extracted as
a follow-up, and it re-exports the Tk dialog entry points so new dialog code has
a single, stable import site.
"""
from __future__ import annotations

from tkinter import filedialog, messagebox

__all__ = ["messagebox", "filedialog"]
