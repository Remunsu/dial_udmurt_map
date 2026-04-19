from PyQt5.QtWidgets import (  # type: ignore
    QDockWidget,
    QLabel,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qgis.PyQt.QtCore import Qt, pyqtSignal  # type: ignore
from typing import Optional


class AnswersDock(QDockWidget):
    add_requested = pyqtSignal()
    delete_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Ответы", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        container = QWidget()
        vbox = QVBoxLayout(container)

        self.current_question_label = QLabel("Вопрос не выбран")
        vbox.addWidget(self.current_question_label)

        self.current_settlement_label = QLabel("Населённый пункт не выбран")
        vbox.addWidget(self.current_settlement_label)

        self.answer_input = QLineEdit()
        self.answer_input.setPlaceholderText("Введите ответ")
        vbox.addWidget(self.answer_input)

        buttons_row = QHBoxLayout()

        self.add_answer_btn = QPushButton("Добавить")
        self.add_answer_btn.clicked.connect(self.add_requested.emit)
        buttons_row.addWidget(self.add_answer_btn)

        self.delete_answer_btn = QPushButton("Удалить")
        self.delete_answer_btn.clicked.connect(self.delete_requested.emit)
        buttons_row.addWidget(self.delete_answer_btn)

        vbox.addLayout(buttons_row)

        self.answers_list = QListWidget()
        vbox.addWidget(self.answers_list)

        self.setWidget(container)

    def set_current_question(self, text: Optional[str]) -> None:
        if text:
            self.current_question_label.setText(f"Текущий вопрос: {text}")
        else:
            self.current_question_label.setText("Вопрос не выбран")

    def set_current_settlement(self, text: Optional[str]) -> None:
        if text:
            self.current_settlement_label.setText(f"Выбранный пункт: {text}")
        else:
            self.current_settlement_label.setText("Населённый пункт не выбран")

    def get_input_text(self) -> str:
        return self.answer_input.text().strip()

    def clear_input(self) -> None:
        self.answer_input.clear()

    def clear_answers(self) -> None:
        self.answers_list.clear()

    def add_answer_item(self, answer_id: int, answer_text: str, settlement_name: str) -> None:
        item = QListWidgetItem(f"{answer_text} — {settlement_name}")
        item.setData(Qt.UserRole, answer_id)
        self.answers_list.addItem(item)

    def current_answer_id(self):
        item = self.answers_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)