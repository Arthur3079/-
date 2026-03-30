from __future__ import annotations

import tkinter as tk
from collections import defaultdict
from tkinter import messagebox, ttk
from typing import Callable, Dict, Iterable, List

from core.cleaner import Cleaner
from core.junk_finder import JunkFinding


def human_size(num: int) -> str:
    size = float(num)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


class JunkTab(ttk.Frame):
    def __init__(self, master: tk.Misc, cleaner: Cleaner | None = None) -> None:
        super().__init__(master)
        self.cleaner = cleaner or Cleaner()
        self._items: List[JunkFinding] = []
        self._selected: Dict[str, tk.BooleanVar] = {}
        self._total_label = ttk.Label(self, text="Выбрано: 0 B")
        self._build_ui()

    def _build_ui(self) -> None:
        self.pack(fill="both", expand=True)
        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True, padx=8, pady=8)

        self._total_label.pack(anchor="w", padx=8, pady=(0, 8))

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Button(buttons, text="Удалить", command=lambda: self._run_cleanup("delete")).pack(side="left", padx=4)
        ttk.Button(buttons, text="В карантин", command=lambda: self._run_cleanup("quarantine")).pack(side="left", padx=4)

    def set_findings(self, findings: Iterable[JunkFinding]) -> None:
        self._items = list(findings)
        self._selected.clear()

        for child in self.container.winfo_children():
            child.destroy()

        grouped: Dict[str, List[JunkFinding]] = defaultdict(list)
        for f in self._items:
            grouped[f.category].append(f)

        for category, items in grouped.items():
            panel = ttk.LabelFrame(self.container, text=category)
            panel.pack(fill="x", expand=True, pady=4)

            toolbar = ttk.Frame(panel)
            toolbar.pack(fill="x")
            ttk.Button(toolbar, text="Выбрать всё", command=lambda c=category: self._set_category(c, True)).pack(side="left", padx=2)
            ttk.Button(toolbar, text="Снять всё", command=lambda c=category: self._set_category(c, False)).pack(side="left", padx=2)

            for item in items:
                key = item.path
                var = tk.BooleanVar(value=False)
                var.trace_add("write", lambda *_: self._update_total())
                self._selected[key] = var
                text = f"{item.path} ({human_size(item.size)}) [{item.risk_level}]"
                ttk.Checkbutton(panel, text=text, variable=var).pack(anchor="w", padx=8)

        self._update_total()

    def _set_category(self, category: str, value: bool) -> None:
        for item in self._items:
            if item.category == category:
                self._selected[item.path].set(value)
        self._update_total()

    def _selected_items(self) -> List[JunkFinding]:
        return [item for item in self._items if self._selected.get(item.path) and self._selected[item.path].get()]

    def _update_total(self) -> None:
        total = sum(item.size for item in self._selected_items())
        self._total_label.config(text=f"Выбрано: {human_size(total)}")

    def _run_cleanup(self, mode: str) -> None:
        targets = self._selected_items()
        if not targets:
            messagebox.showinfo("Очистка", "Нет выбранных элементов.")
            return

        message = f"Подтвердите действие: {mode}. Будет обработано {len(targets)} элементов."
        if not messagebox.askyesno("Подтверждение", message):
            return

        results = self.cleaner.cleanup(targets, mode=mode, confirmed=True)
        success = sum(1 for r in results if r.success)
        failed = len(results) - success
        messagebox.showinfo("Результат", f"Успешно: {success}, пропущено/ошибок: {failed}")
