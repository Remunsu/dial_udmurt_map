from PyQt5.QtWidgets import (  # type: ignore
    QDockWidget,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from qgis.PyQt.QtCore import Qt  # type: ignore
from typing import Optional


class SettlementInfoDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Населённый пункт", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        container = QWidget()
        layout = QVBoxLayout(container)

        self.title_label = QLabel("Населённый пункт не выбран")
        layout.addWidget(self.title_label)

        self.items_list = QListWidget()
        layout.addWidget(self.items_list)

        self.setWidget(container)

    def set_settlement_name(self, name: Optional[str]) -> None:
        if name:
            self.title_label.setText(f"Пункт: {name}")
        else:
            self.title_label.setText("Населённый пункт не выбран")

    def clear_items(self) -> None:
        self.items_list.clear()

    def add_item(self, question_text: str, answer_text: str) -> None:
        self.items_list.addItem(f"{question_text} — {answer_text}")