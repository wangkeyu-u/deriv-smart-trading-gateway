"""Native desktop shell for Deriv Smart Trading Gateway.

Run:
    python desktop_app.py

PySide6 is imported lazily so the rest of the project remains testable without
desktop dependencies.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from budget_guard import BudgetLimits, budget_guard_check
from micro_trading import analyze_micro_trade, micro_trade_config_from_goal
import web_app


def _configure_qt_plugin_path() -> None:
    if os.environ.get("QT_PLUGIN_PATH") and os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"):
        return
    try:
        import PySide6
    except Exception:
        return
    pyside_dir = Path(PySide6.__file__).resolve().parent
    plugins_dir = pyside_dir / "Qt" / "plugins"
    platform_dir = plugins_dir / "platforms"
    if plugins_dir.exists():
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugins_dir))
    if platform_dir.exists():
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(platform_dir))


def _parse_prices(raw: str) -> pd.DataFrame:
    values: list[float] = []
    for item in raw.replace("\n", ",").split(","):
        text = item.strip()
        if not text:
            continue
        values.append(float(text))
    return pd.DataFrame({"close": values})


def _health_text() -> str:
    snapshot = web_app.system_health_snapshot(
        {
            "deriv_token": "",
            "pending_trade": None,
            "last_tick": None,
            "last_advisor_result": None,
            "chart_snapshots": [],
            "api_trace": [],
            "runtime_events": [],
        }
    )
    return json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)


def _desktop_dependency_error(exc: Exception) -> int:
    print("PySide6 is required for the desktop app.")
    print("Install it with:")
    print("  .venv/bin/pip install -r desktop_requirements.txt")
    print(f"Import error: {exc}")
    return 2


def _qt_preflight_ok() -> bool:
    code = """
from PySide6.QtWidgets import QApplication
app = QApplication([])
app.quit()
""".strip()
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def _main_tk(reason: str = "") -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except Exception as exc:
        print("Neither PySide6 nor Tkinter desktop UI could be started.")
        print(f"PySide6 issue: {reason}")
        print(f"Tkinter import error: {exc}")
        return 2

    root = tk.Tk()
    root.title("Deriv Smart Trading Gateway")
    root.geometry("980x720")
    root.minsize(780, 560)

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TNotebook.Tab", padding=(16, 8))
    style.configure("Primary.TButton", padding=(12, 8))

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=14, pady=14)

    monitor = ttk.Frame(notebook, padding=16)
    health_output = tk.Text(monitor, wrap="word", height=26)
    ttk.Label(monitor, text="System Health", font=("Helvetica", 20, "bold")).pack(anchor="w")
    ttk.Label(monitor, text="Local checks only. No network trading call is made here.").pack(anchor="w", pady=(4, 12))
    health_output.pack(fill="both", expand=True)
    notebook.add(monitor, text="Monitor")

    micro = ttk.Frame(notebook, padding=16)
    form = ttk.Frame(micro)
    form.pack(fill="x")
    fields: dict[str, tk.StringVar] = {
        "goal": tk.StringVar(value="高频小额交易，先做纸面策略"),
        "symbol": tk.StringVar(value="R_75"),
        "amount": tk.StringVar(value="1.0"),
        "daily": tk.StringVar(value="5.0"),
        "total": tk.StringVar(value="5.0"),
        "spent_today": tk.StringVar(value="0.0"),
        "spent_total": tk.StringVar(value="0.0"),
        "asset": tk.StringVar(value="deriv"),
    }
    rows = [
        ("Goal", "goal"),
        ("Symbol / Fund", "symbol"),
        ("Max Trade Amount", "amount"),
        ("Daily Budget Cap", "daily"),
        ("Total Budget Cap", "total"),
        ("Spent Today", "spent_today"),
        ("Spent Total", "spent_total"),
    ]
    for row, (label, key) in enumerate(rows):
        ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=fields[key]).grid(row=row, column=1, sticky="ew", pady=4, padx=(12, 0))
    ttk.Label(form, text="Asset Kind").grid(row=len(rows), column=0, sticky="w", pady=4)
    ttk.Combobox(
        form,
        textvariable=fields["asset"],
        values=["deriv", "fund", "equity", "crypto", "forex"],
        state="readonly",
    ).grid(row=len(rows), column=1, sticky="ew", pady=4, padx=(12, 0))
    form.columnconfigure(1, weight=1)

    ttk.Label(micro, text="Recent closes").pack(anchor="w", pady=(14, 4))
    price_input = tk.Text(micro, height=5, wrap="word")
    price_input.insert("1.0", "100,100.03,100.06,100.10,100.15,100.22,100.30,100.39,100.49")
    price_input.pack(fill="x")
    micro_output = tk.Text(micro, wrap="word")
    micro_output.pack(fill="both", expand=True, pady=(12, 0))

    def refresh_health() -> None:
        health_output.delete("1.0", "end")
        health_output.insert("1.0", _health_text())
        root.after(5000, refresh_health)

    def analyze() -> None:
        try:
            frame = _parse_prices(price_input.get("1.0", "end"))
            config = micro_trade_config_from_goal(
                fields["goal"].get(),
                fields["symbol"].get().strip() or "R_75",
                asset_kind=fields["asset"].get(),  # type: ignore[arg-type]
                default_amount=float(fields["amount"].get() or 1.0),
            )
            budget = budget_guard_check(
                action="execute_simulated_trade" if config.asset_kind == "deriv" else "spot_paper_trade",
                amount=config.max_trade_amount,
                limits=BudgetLimits(
                    max_single_trade_amount=float(fields["amount"].get() or 1.0),
                    max_daily_trade_budget=float(fields["daily"].get() or 5.0),
                    max_total_trade_budget=float(fields["total"].get() or 5.0),
                ),
                daily_spent=float(fields["spent_today"].get() or 0.0),
                total_spent=float(fields["spent_total"].get() or 0.0),
            )
            result = analyze_micro_trade(frame, config)
            result["micro_budget_guard"] = budget
            if not budget.get("ok"):
                result["action"] = "WAIT" if config.asset_kind == "deriv" else "HOLD"
                result["blockers"] = list(result.get("blockers") or []) + [str(budget.get("reason"))]
            result["generated_at"] = datetime.utcnow().isoformat() + "Z"
            result["desktop_runtime"] = "tkinter_fallback"
            micro_output.delete("1.0", "end")
            micro_output.insert("1.0", json.dumps(result, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:
            messagebox.showwarning("Analysis failed", str(exc))

    ttk.Button(micro, text="Analyze Micro Strategy", style="Primary.TButton", command=analyze).pack(anchor="w", pady=12)
    notebook.add(micro, text="Micro Strategy")

    background = ttk.Frame(notebook, padding=16)
    ttk.Label(background, text="Background Mode", font=("Helvetica", 20, "bold")).pack(anchor="w")
    ttk.Label(
        background,
        text=(
            "PySide6 tray mode is unavailable on this machine, so this fallback "
            "desktop window keeps the operator tools available without crashing."
        ),
        wraplength=720,
    ).pack(anchor="w", pady=(8, 18))
    ttk.Label(background, text=f"Fallback reason: {reason}", wraplength=720).pack(anchor="w")
    ttk.Button(background, text="Quit Desktop App", command=root.destroy).pack(anchor="w", pady=18)
    notebook.add(background, text="Background")

    refresh_health()
    root.mainloop()
    return 0


def main() -> int:
    _configure_qt_plugin_path()
    if not _qt_preflight_ok():
        return _main_tk("Qt platform plugin preflight failed")
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QAction, QIcon
        from PySide6.QtWidgets import (
            QApplication,
            QComboBox,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QSystemTrayIcon,
            QTabWidget,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except Exception as exc:  # pragma: no cover - depends on optional desktop package
        return _desktop_dependency_error(exc)

    class DesktopWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Deriv Smart Trading Gateway")
            self.resize(980, 720)
            self.setMinimumSize(780, 560)
            self.tray: QSystemTrayIcon | None = None
            self.tabs = QTabWidget()
            self.setCentralWidget(self.tabs)
            self.health_output = QTextEdit()
            self.micro_output = QTextEdit()
            self.price_input = QTextEdit()
            self.goal_input = QLineEdit("高频小额交易，先做纸面策略")
            self.symbol_input = QLineEdit("R_75")
            self.micro_amount_input = QLineEdit("1.0")
            self.micro_daily_budget_input = QLineEdit("5.0")
            self.micro_total_budget_input = QLineEdit("5.0")
            self.micro_spent_today_input = QLineEdit("0.0")
            self.micro_spent_total_input = QLineEdit("0.0")
            self.asset_kind = QComboBox()
            self.asset_kind.addItems(["deriv", "fund", "equity", "crypto", "forex"])
            self._build_dashboard_tab()
            self._build_micro_trade_tab()
            self._build_background_tab()
            self._setup_tray(QIcon())
            self._refresh_health()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._refresh_health)
            self.timer.start(5000)

        def _build_dashboard_tab(self) -> None:
            page = QWidget()
            layout = QVBoxLayout(page)
            title = QLabel("System Health")
            title.setStyleSheet("font-size: 20px; font-weight: 700;")
            self.health_output.setReadOnly(True)
            layout.addWidget(title)
            layout.addWidget(QLabel("Local checks only. No network trading call is made here."))
            layout.addWidget(self.health_output)
            self.tabs.addTab(page, "Monitor")

        def _build_micro_trade_tab(self) -> None:
            page = QWidget()
            layout = QVBoxLayout(page)
            form = QFormLayout()
            form.addRow("Goal", self.goal_input)
            form.addRow("Symbol / Fund", self.symbol_input)
            form.addRow("Asset Kind", self.asset_kind)
            form.addRow("Max Trade Amount", self.micro_amount_input)
            form.addRow("Daily Budget Cap", self.micro_daily_budget_input)
            form.addRow("Total Budget Cap", self.micro_total_budget_input)
            form.addRow("Spent Today", self.micro_spent_today_input)
            form.addRow("Spent Total", self.micro_spent_total_input)
            self.price_input.setPlainText("100,100.03,100.06,100.10,100.15,100.22,100.30,100.39,100.49")
            form.addRow("Recent closes", self.price_input)
            analyze_button = QPushButton("Analyze Micro Strategy")
            analyze_button.clicked.connect(self._analyze_micro_trade)
            self.micro_output.setReadOnly(True)
            layout.addLayout(form)
            layout.addWidget(analyze_button)
            layout.addWidget(self.micro_output)
            self.tabs.addTab(page, "Micro Strategy")

        def _build_background_tab(self) -> None:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.addWidget(QLabel("Background Mode"))
            layout.addWidget(
                QLabel(
                    "Closing the window hides it to the system tray when the tray is available. "
                    "The app keeps health refresh timers alive in the background."
                )
            )
            quit_button = QPushButton("Quit Desktop App")
            quit_button.clicked.connect(QApplication.instance().quit)
            row = QHBoxLayout()
            row.addWidget(quit_button)
            row.addStretch()
            layout.addLayout(row)
            layout.addStretch()
            self.tabs.addTab(page, "Background")

        def _setup_tray(self, icon: QIcon) -> None:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip("Deriv Smart Trading Gateway")
            show_action = QAction("Show", self)
            quit_action = QAction("Quit", self)
            show_action.triggered.connect(self.showNormal)
            quit_action.triggered.connect(QApplication.instance().quit)
            menu = self.tray.contextMenu()
            if menu is None:
                from PySide6.QtWidgets import QMenu

                menu = QMenu()
                self.tray.setContextMenu(menu)
            menu.addAction(show_action)
            menu.addAction(quit_action)
            self.tray.show()

        def _refresh_health(self) -> None:
            self.health_output.setPlainText(_health_text())

        def _analyze_micro_trade(self) -> None:
            try:
                frame = _parse_prices(self.price_input.toPlainText())
                config = micro_trade_config_from_goal(
                    self.goal_input.text(),
                    self.symbol_input.text().strip() or "R_75",
                    asset_kind=str(self.asset_kind.currentText()),  # type: ignore[arg-type]
                    default_amount=float(self.micro_amount_input.text() or 1.0),
                )
                budget = budget_guard_check(
                    action="execute_simulated_trade" if config.asset_kind == "deriv" else "spot_paper_trade",
                    amount=config.max_trade_amount,
                    limits=BudgetLimits(
                        max_single_trade_amount=float(self.micro_amount_input.text() or 1.0),
                        max_daily_trade_budget=float(self.micro_daily_budget_input.text() or 5.0),
                        max_total_trade_budget=float(self.micro_total_budget_input.text() or 5.0),
                    ),
                    daily_spent=float(self.micro_spent_today_input.text() or 0.0),
                    total_spent=float(self.micro_spent_total_input.text() or 0.0),
                )
                result = analyze_micro_trade(frame, config)
                result["micro_budget_guard"] = budget
                if not budget.get("ok"):
                    result["action"] = "WAIT" if config.asset_kind == "deriv" else "HOLD"
                    result["blockers"] = list(result.get("blockers") or []) + [str(budget.get("reason"))]
                result["generated_at"] = datetime.utcnow().isoformat() + "Z"
                self.micro_output.setPlainText(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            except Exception as exc:
                QMessageBox.warning(self, "Analysis failed", str(exc))

        def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API name
            if self.tray and self.tray.isVisible():
                event.ignore()
                self.hide()
                self.tray.showMessage(
                    "Deriv Gateway",
                    "Still running in the background.",
                    QSystemTrayIcon.MessageIcon.Information,
                    1800,
                )
            else:
                event.accept()

    app = QApplication(sys.argv)
    window = DesktopWindow()
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
