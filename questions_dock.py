from PyQt5.QtWidgets import (  # type: ignore
    QDockWidget,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qgis.PyQt.QtCore import Qt, pyqtSignal  # type: ignore


class QuestionsDock(QDockWidget):
    add_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    selection_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Вопросы", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        container = QWidget()
        vbox = QVBoxLayout(container)

        self.question_input = QLineEdit()
        self.question_input.setPlaceholderText("Введите новый вопрос")
        vbox.addWidget(self.question_input)

        buttons_row = QHBoxLayout()

        self.add_question_btn = QPushButton("Добавить")
        self.add_question_btn.clicked.connect(self.add_requested.emit)
        buttons_row.addWidget(self.add_question_btn)

        self.delete_question_btn = QPushButton("Удалить")
        self.delete_question_btn.clicked.connect(self.delete_requested.emit)
        buttons_row.addWidget(self.delete_question_btn)

        vbox.addLayout(buttons_row)

        self.questions_list = QListWidget()
        self.questions_list.itemSelectionChanged.connect(self.selection_changed.emit)
        vbox.addWidget(self.questions_list)

        self.setWidget(container)

    def get_input_text(self) -> str:
        return self.question_input.text().strip()

    def clear_input(self) -> None:
        self.question_input.clear()

    def clear_questions(self) -> None:
        self.questions_list.clear()

    def add_question_item(self, question_id: int, text: str) -> None:
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, question_id)
        self.questions_list.addItem(item)

    def current_question_text(self):
        item = self.questions_list.currentItem()
        if item is None:
            return None
        return item.text()

    def current_question_id(self):
        item = self.questions_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)