# core/ui/components/footer.py
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel
from ..theme import THEME

class Footer(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Footer")
        self.setFixedHeight(40)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        
        self.label = QLabel("Ready")
        self.label.setObjectName("FooterLabel")
        layout.addWidget(self.label)
        
        layout.addStretch()
        
        self.version_label = QLabel("neverliie v0.3.11")
        self.version_label.setObjectName("FooterVersionLabel")
        layout.addWidget(self.version_label)
        
        self.setup_style()

    def set_text(self, text):
        self.label.setText(text)

    def show_border(self, visible):
        color = THEME['surface'] if visible else "transparent"
        self.setStyleSheet(f"""
            QFrame#Footer {{
                background: #30000000;
                border-top: 1px solid {color};
            }}
            QLabel#FooterLabel {{
                color: {THEME['subtext']};
                font-size: 12px;
                font-weight: 600;
            }}
            QLabel#FooterVersionLabel {{
                color: {THEME['subtext']};
                font-size: 12px;
                font-weight: 600;
            }}
        """)

    def setup_style(self):
        self.show_border(False)