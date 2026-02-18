# core/ui/theme.py
from PySide6.QtGui import QColor, QPainter, QPen, QIcon, QPixmap
from PySide6.QtCore import Qt

# qt color is AARRGGBB
THEME = {
    "bg": "#70000000",
    "mantle": "#402E2E30",
    "surface": "#703E3E40",
    "text": "#cdd6f4",
    "subtext": "#a6adc8",
    "accent": "#89b4fa",
    "highlight": "#45475a",
    "border": "#45475a",
    "red": "#f38ba8",
    "peach": "#fab387"
}

def create_app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(THEME["bg"]))
    painter.setPen(QPen(QColor(THEME["border"]), 2))
    painter.drawEllipse(2, 2, 60, 60)
    painter.setPen(QPen(QColor(THEME["accent"]), 4))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(20, 20, 16, 16)
    painter.drawLine(34, 34, 44, 44)
    painter.end()
    return QIcon(pixmap)