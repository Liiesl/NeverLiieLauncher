# core/ui/components/result_list.py
from PySide6.QtWidgets import (QStackedWidget, QListWidget, QListWidgetItem, 
                                QStyledItemDelegate, QStyle, QFileIconProvider, 
                                QAbstractItemView, QSizePolicy)
from PySide6.QtCore import Qt, QSize, QRect, QFileInfo, Signal, QPropertyAnimation, QEasingCurve, Property, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QBrush, QPen, QIcon, QPixmap
import os

from ..theme import THEME

class ResultDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.h_margin = 12
        self.v_margin = 6
        self.row_height = 64
        self.pixmap_cache = {} 

    def sizeHint(self, option, index):
        size_data = index.data(Qt.SizeHintRole)
        if size_data and size_data.isValid():
            return QSize(option.rect.width(), size_data.height())
        return QSize(option.rect.width(), self.row_height)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        
        item_data = index.data(Qt.UserRole)
        if not item_data:
            painter.restore()
            return

        full_rect = option.rect
        card_rect = full_rect.adjusted(self.h_margin, self.v_margin, -self.h_margin, -self.v_margin)
        
        if item_data.widget_factory:
            painter.restore()
            return

        # --- 2. Icon ---
        icon_size = 28
        icon_x = card_rect.left() + 20
        icon_y = card_rect.top() + (card_rect.height() - icon_size) // 2
        
        if item_data.icon_path and item_data.icon_path in self.pixmap_cache:
            pixmap = self.pixmap_cache[item_data.icon_path]
            painter.drawPixmap(icon_x, icon_y, pixmap)
        else:
            painter.setBrush(QColor(THEME["surface"]))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(icon_x, icon_y, icon_size, icon_size)

        # --- 3. Text ---
        # Define where text starts
        text_left = icon_x + icon_size + 15
        
        # Define strict available width:
        # Card Right Edge - Start Position - Right Padding (15px)
        avail_width = card_rect.right() - text_left - 15
        
        if avail_width <= 0:
            painter.restore()
            return

        # -- Title --
        title_rect = QRect(text_left, card_rect.top() + 10, avail_width, 22)
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.setPen(QColor(THEME["text"]))

        # 1. Clean text (remove newlines that break drawing)
        clean_title = item_data.name.replace("\n", " ").strip()
        # 2. Calculate Elision
        fm_title = painter.fontMetrics()
        elided_title = fm_title.elidedText(clean_title, Qt.ElideRight, avail_width)
        # 3. Draw with SingleLine flag to prevent wrapping issues
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, elided_title)
        
        # -- Description --
        desc_rect = QRect(text_left, title_rect.bottom(), avail_width, 18)
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor(THEME["subtext"] if not (option.state & QStyle.State_Selected) else "#bac2de"))

        clean_desc = item_data.description.replace("\n", " ").strip()
        fm_desc = painter.fontMetrics()
        elided_desc = fm_desc.elidedText(clean_desc, Qt.ElideRight, avail_width)
        painter.drawText(desc_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, elided_desc)
        
        painter.restore()


class AnimatedListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._highlight_y = 0
        self._highlight_height = 52
        self._highlight_width = 0
        self._highlight_visible = False
        self._h_margin = 12
        self._v_margin = 6
    
    def hide_highlight(self):
        self._highlight_visible = False
        self.viewport().update()
    
    def highlight_y(self):
        return self._highlight_y
    
    def set_highlight_y(self, value):
        self._highlight_y = value
        self.viewport().update()
    
    highlightY = Property(float, highlight_y, set_highlight_y)
    
    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        
        if self._highlight_visible and self._highlight_width > 0:
            rect = QRect(self._h_margin, int(self._highlight_y), 
                        self._highlight_width, self._highlight_height)
            painter.setBrush(QColor(THEME["surface"]))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 12, 12)
            
            pill_rect = QRect(rect.left() + 4, rect.top() + 12, 4, rect.height() - 24)
            painter.setBrush(QColor(THEME["accent"]))
            painter.drawRoundedRect(pill_rect, 2, 2)
        
        painter.end()
        super().paintEvent(event)


class SelectionHighlight:
    def __init__(self, list_widget):
        self.list_widget = list_widget
        self._h_margin = 12
        self._v_margin = 6
        self._current_y = 0
        self.animation = QPropertyAnimation(list_widget, b"highlightY", list_widget)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)


class ResultListContainer(QStackedWidget):
    item_activated = Signal(object) 
    selection_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_list()
        self.setup_style()
        
    def setup_list(self):
        self.result_list = AnimatedListWidget()
        self.delegate = ResultDelegate(self.result_list)
        self.result_list.setItemDelegate(self.delegate)
        self.result_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.result_list.setUniformItemSizes(False)
        self.result_list.setFocusPolicy(Qt.NoFocus)
        self.result_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.result_list.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        
        self.result_list.itemActivated.connect(self._on_activate)
        self.result_list.currentItemChanged.connect(self._on_change)
        self.result_list.verticalScrollBar().valueChanged.connect(self._on_scroll)
        
        self.addWidget(self.result_list)
        self.icon_provider = QFileIconProvider()
        
        self.selection_highlight = SelectionHighlight(self.result_list)
        self._pending_highlight_row = None
        self._scroll_animation_active = False
        
    def setup_style(self):
        self.setStyleSheet(f"""
            QListWidget {{ background: transparent; border: none; padding: 5px 0; outline: 0; }}
            QListWidget::item {{ border: none; padding: 0px; }}
            QListWidget::item:selected {{ background: transparent; }}
            
            QScrollBar:vertical {{
                border: none; background: transparent; width: 8px; margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {THEME['surface']}; min-height: 30px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {THEME['border']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        """)

    def update_results(self, results):
        self.remove_custom_widget()
        self.result_list.hide_highlight()
        self.result_list._highlight_y = 0
        
        image_extensions = {'.svg', '.png', '.jpg', '.jpeg', '.ico', '.bmp'}

        for item in results:
            if item.icon_path and item.icon_path not in self.delegate.pixmap_cache:
                path = item.icon_path
                _, ext = os.path.splitext(path)
                
                if ext.lower() in image_extensions:
                    qicon = QIcon(path)
                else:
                    qicon = self.icon_provider.icon(QFileInfo(path))
                
                pixmap = qicon.pixmap(28, 28) 
                self.delegate.pixmap_cache[path] = pixmap

        self.result_list.blockSignals(True)
        self.result_list.setUpdatesEnabled(False)
        self.result_list.viewport().setUpdatesEnabled(False)
        
        self.result_list.clear()
        
        if not results:
            self.result_list.blockSignals(False)
            self.result_list.viewport().setUpdatesEnabled(True)
            self.result_list.setUpdatesEnabled(True)
            return 0 

        total_height = 0
        for item_data in results:
            l_item = QListWidgetItem()
            l_item.setData(Qt.UserRole, item_data)
            
            height = item_data.height
            total_height += height
            
            l_item.setSizeHint(QSize(self.result_list.width(), height))
            self.result_list.addItem(l_item)
            
            if item_data.widget_factory:
                widget = item_data.widget_factory()
                self.result_list.setItemWidget(l_item, widget)
        
        self.result_list.setCurrentRow(0)
        self._pending_highlight_row = 0
            
        self.result_list.viewport().setUpdatesEnabled(True)
        self.result_list.setUpdatesEnabled(True)
        self.result_list.blockSignals(False)

        if self.result_list.currentItem():
            self._on_change(self.result_list.currentItem(), None)
           
        return total_height

    def show_custom_widget(self, widget):
        self.addWidget(widget)
        self.setCurrentIndex(1)
        
    def remove_custom_widget(self):
        if self.count() > 1:
            w = self.widget(1)
            self.removeWidget(w)
            w.deleteLater()
        self.setCurrentIndex(0)
        
    def get_custom_widget(self):
        if self.count() > 1:
            return self.widget(1)
        return None

    def navigate(self, direction):
        if self.currentIndex() != 0: return
        count = self.result_list.count()
        if count == 0: return
        
        curr = self.result_list.currentRow()
        new_idx = max(0, min(curr + direction, count - 1))
        self.result_list.setCurrentRow(new_idx)

    def _update_highlight_position(self, row, animate=True):
        if row < 0 or row >= self.result_list.count():
            self.result_list.hide_highlight()
            return
        
        item = self.result_list.item(row)
        if not item:
            return
        
        rect = self.result_list.visualItemRect(item)
        viewport_h = self.result_list.viewport().height()
        
        if not rect.isValid() or rect.top() < -100 or rect.bottom() > viewport_h + 100:
            self.result_list.hide_highlight()
            return
        
        row_height = item.sizeHint().height()
        card_height = row_height - (self.selection_highlight._v_margin * 2)
        card_width = rect.width() - (self.selection_highlight._h_margin * 2)
        target_y = rect.top() + self.selection_highlight._v_margin
        
        old_y = self.result_list._highlight_y
        
        self.result_list._highlight_height = card_height
        self.result_list._highlight_width = card_width
        self.result_list._highlight_visible = True
        
        if animate and old_y > 0 and abs(old_y - target_y) > 1:
            self.selection_highlight.animation.stop()
            self.selection_highlight.animation.setStartValue(old_y)
            self.selection_highlight.animation.setEndValue(target_y)
            self.selection_highlight.animation.start()
        else:
            self.result_list._highlight_y = target_y
            self.result_list.viewport().update()

    def get_current_data(self):
        item = self.result_list.currentItem()
        if item:
            return item.data(Qt.UserRole)
        return None

    def _on_activate(self, item):
        data = item.data(Qt.UserRole)
        self.item_activated.emit(data)

    def _on_change(self, current, previous):
        if current:
            data = current.data(Qt.UserRole)
            self.selection_changed.emit(data)
            row = self.result_list.row(current)
            QTimer.singleShot(0, lambda: self._update_highlight_position(row, animate=(previous is not None)))
    
    def _on_scroll(self):
        if self._scroll_animation_active:
            return
        current = self.result_list.currentItem()
        if current:
            row = self.result_list.row(current)
            self._scroll_animation_active = True
            self._update_highlight_position(row, animate=False)
            self._scroll_animation_active = False