"""Native desktop shell for Deriv Smart Trading Gateway.

Run:
    python desktop_app.py

PySide6 is imported lazily so the rest of the project remains testable without
desktop dependencies.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

import pandas as pd

from budget_guard import BudgetLimits, budget_guard_check
from micro_trading import analyze_micro_trade, micro_trade_config_from_goal
import web_app


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


def main() -> int:
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
