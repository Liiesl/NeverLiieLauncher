# core/ui/components/search_bar.py
import os
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon
from ..theme import THEME

class SearchBar(QFrame):
    text_changed = Signal(str)
    return_pressed = Signal()
    back_clicked = Signal()
    nav_requested = Signal(int)
    escape_pressed = Signal()
    command_menu_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.setup_ui()
        self.setup_style()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 20, 0)
        layout.setSpacing(10)

        # Back Button (Hidden by default)
        self.back_btn = QLabel("←")
        self.back_btn.setObjectName("BackButton")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.hide()
        self.back_btn.mousePressEvent = lambda e: self.back_clicked.emit()

        # Search Icon
        self.search_icon_lbl = QLabel()
        self.search_icon_lbl.setObjectName("SearchIcon")
        self.search_icon_lbl.setFixedSize(24, 24)
        svg_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "search.svg")
        self._load_svg_icon(self.search_icon_lbl, svg_path, THEME['subtext'])

        # Input Field
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search apps, files, commands...")
        self.search_input.installEventFilter(self)
        self.search_input.textEdited.connect(self.text_changed.emit)
        self.search_input.returnPressed.connect(self.return_pressed.emit)

        # Context Label (for Extension Name)
        self.context_lbl = QLabel("")
        self.context_lbl.setObjectName("ContextLabel")
        self.context_lbl.hide()

        layout.addWidget(self.back_btn)
        layout.addWidget(self.search_icon_lbl)
        layout.addWidget(self.search_input)
        layout.addWidget(self.context_lbl)

    def setup_style(self):
        self.setStyleSheet(f"""
            QFrame {{ background: transparent; }}
            
            QLabel#BackButton {{ 
                font-size: 24px; color: {THEME['text']}; font-weight: bold;
                padding: 4px; border-radius: 4px;
            }}
            QLabel#BackButton:hover {{ background: {THEME['surface']}; }}
            
            QLabel#ContextLabel {{ 
                color: {THEME['subtext']}; font-weight: bold; 
                background: {THEME['surface']}; padding: 4px 8px; border-radius: 6px;
            }}

            QLineEdit {{
                background: transparent; color: {THEME['text']};
                border: none; font-size: 20px; font-weight: 500;
                selection-background-color: {THEME['accent']}; selection-color: {THEME['bg']};
            }}
        """)

    def _load_svg_icon(self, label, svg_path, color):
        icon = QIcon(svg_path)
        pixmap = icon.pixmap(24, 24)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color))
        painter.end()
        label.setPixmap(pixmap)

    def set_mode_root(self):
        self.back_btn.hide()
        self.context_lbl.hide()
        self.search_icon_lbl.show()
        self.search_input.setPlaceholderText("Search apps, files, commands...")
        self.search_input.setText("")
        self.search_input.setFocus()

    def set_mode_extension(self, ext_name):
        self.back_btn.show()
        self.search_icon_lbl.hide()
        self.context_lbl.setText(ext_name)
        self.context_lbl.show()
        self.search_input.setText("")
        self.search_input.setPlaceholderText(f"Search in {ext_name}...")
        self.search_input.setFocus()

    def get_text(self):
        return self.search_input.text()

    def set_text(self, text):
        """Programmatically sets text without triggering textEdited signal."""
        self.search_input.setText(text)

    def focus_input(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

    def eventFilter(self, obj, event):
        if obj == self.search_input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Down:
                self.nav_requested.emit(1)
                return True
            elif event.key() == Qt.Key_Up:
                self.nav_requested.emit(-1)
                return True
            elif event.key() == Qt.Key_Escape:
                self.escape_pressed.emit()
                return True
            elif event.key() == Qt.Key_K and event.modifiers() == Qt.ControlModifier:
                self.command_menu_requested.emit()
                return True
        return super().eventFilter(obj, event)