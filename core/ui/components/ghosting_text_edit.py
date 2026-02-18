from PySide6.QtWidgets import QTextEdit
from PySide6.QtCore import Qt, QTimer, QRectF, Signal
from PySide6.QtGui import QPainter, QColor, QTextOption, QPen, QFontMetrics
from ..theme import THEME


class GhostingTextEdit(QTextEdit):
    textEdited = Signal(str)
    returnPressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setCursorWidth(0)
        
        self.cursor_color = THEME['accent']
        self.cursor_width = 2
        
        self.fade_speed = 35
        self.smoothness = 0.4
        
        self._current_x = 0.0
        self._ghosts = []
        self._is_moving = False
        self._setting_text = False
        
        self._placeholder_text = ""
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_physics)
        self.timer.start(16)
        
        self.setWordWrapMode(QTextOption.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(35)
        self.setAcceptRichText(False)
        
        super().textChanged.connect(self._on_text_changed)

    def setPlaceholderText(self, text):
        self._placeholder_text = text
        self.viewport().update()

    def placeholderText(self):
        return self._placeholder_text

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self._setting_text = True
        super().setText(text)
        self._setting_text = False

    def _on_text_changed(self):
        if not self._setting_text:
            self.textEdited.emit(self.toPlainText())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.returnPressed.emit()
            event.ignore()
            return
        if event.key() == Qt.Key_Tab:
            event.ignore()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        target = self.cursorRect()
        self._current_x = float(target.x())
        self._ghosts.clear()
        self._is_moving = False
        self.viewport().update()

    def _update_physics(self):
        target_rect = self.cursorRect()
        target_x = float(target_rect.x())
        
        diff = target_x - self._current_x
        
        if abs(diff) > 0.5:
            self._is_moving = True
            
            self._spawn_ghost(self._current_x, target_rect.y(), target_rect.height())
            
            self._current_x += diff * self.smoothness
            self.viewport().update()
        else:
            self._is_moving = False
            self._current_x = target_x
            
            if self._ghosts:
                self.viewport().update()

        if self._ghosts:
            for i in range(len(self._ghosts) - 1, -1, -1):
                ghost = self._ghosts[i]
                ghost['alpha'] -= self.fade_speed
                if ghost['alpha'] <= 0:
                    self._ghosts.pop(i)
            self.viewport().update()

    def _spawn_ghost(self, x, y, height):
        if len(self._ghosts) > 15:
            return
        self._ghosts.append({
            'rect': QRectF(x, y, self.cursor_width, height),
            'alpha': 200
        })

    def paintEvent(self, event):
        super().paintEvent(event)
        
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)

        if self._placeholder_text and not self.toPlainText():
            fm = QFontMetrics(self.font())
            pen = QPen(QColor(120, 120, 120))
            painter.setPen(pen)
            painter.drawText(self.viewport().rect().adjusted(4, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, self._placeholder_text)

        for ghost in self._ghosts:
            color = QColor(self.cursor_color)
            color.setAlpha(int(ghost['alpha']))
            painter.fillRect(ghost['rect'], color)

        if self._is_moving:
            base_rect = self.cursorRect()
            current_rect = QRectF(
                self._current_x, 
                float(base_rect.y()), 
                float(self.cursor_width), 
                float(base_rect.height())
            )
            painter.fillRect(current_rect, self.cursor_color)
