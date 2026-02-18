# markdown_engine/widget.py
import sys
import time
from PySide6.QtWidgets import QWidget, QMenu, QToolTip
from PySide6.QtCore import Qt, QPoint, Signal, QRect, QUrl, QTimer
from PySide6.QtGui import (QColor, QPainter, QGuiApplication, QTextLayout, 
                           QAction, QKeySequence, QPainterPath, 
                           QDesktopServices, QCursor, QFontMetrics)

from .constants import THEME, PADDING_Y, MSG_SPACING, BLOCK_SPACING, LINE_SPACING
from .data_types import Message, BlockType, FormatType
from .parser import MarkdownParser
from .layout import LayoutEngine
from .styles import StyleManager
from .benchmark import get_global_benchmark

# Import Renderers
from .renderers.text import TextRenderer
from .renderers.header import HeaderRenderer
from .renderers.code import CodeRenderer
from .renderers.quote import QuoteRenderer
from .renderers.table import TableRenderer 
from .renderers.divider import DividerRenderer
from .renderers.list_item import ListItemRenderer

class ChatCanvas(QWidget):
    paste_requested = Signal()

    def __init__(self):
        super().__init__()
        self.messages = []
        
        self.styles = StyleManager()

        self._warmup_fonts()

        self.parser = MarkdownParser()
        self.layout_engine = LayoutEngine(self.styles)
        
        # Keep instances to call helper methods
        self.text_renderer = TextRenderer()
        
        self.renderers = {
            BlockType.PARAGRAPH: self.text_renderer,
            BlockType.LIST_ITEM: ListItemRenderer(),
            BlockType.HEADER: HeaderRenderer(),
            BlockType.CODE: CodeRenderer(),
            BlockType.QUOTE: QuoteRenderer(),
            BlockType.TABLE: TableRenderer(),
            BlockType.DIVIDER: DividerRenderer()
        }

        self.min_height = 100
        self.sel_start = None 
        self.sel_end = None
        self.is_selecting = False
        self.hovered_url = None
        self._last_click_time = 0
        self._last_click_pos = None
        self._double_click_time = 0
        self._double_click_start = None
        self._double_click_end = None
        self._is_double_click_selecting = False
        self._drag_cursor_pos = None
        
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)

    def _warmup_fonts(self):
        """Forces Qt to load the font database and emoji glyphs."""
        bench = get_global_benchmark()
        if bench:
            timer = bench.child("Font Warmup")
            start = time.perf_counter()
        
        font = self.styles.get_font(BlockType.PARAGRAPH)
        dummy_text = "Warmup 🛠️ Emoji"
        fm = QFontMetrics(font)
        _ = fm.horizontalAdvance(dummy_text)
        layout = QTextLayout(dummy_text, font)
        layout.beginLayout()
        layout.createLine()
        layout.endLayout()
        
        if bench:
            timer.record_time((time.perf_counter() - start) * 1000)

    def add_message(self, text, is_user=False):
        bench = get_global_benchmark()
        if bench:
            timer = bench.child("add_message")
            timer.set_context(is_user=is_user, chars=len(text), lines=len(text.split('\n')))
            start = time.perf_counter()
        
        msg = Message(text, is_user)
        
        if bench:
            parse_timer = bench.child("Markdown Parsing")
            parse_start = time.perf_counter()
            msg.blocks = self.parser.parse(text)
            parse_end = time.perf_counter()
            parse_timer.total_time = (parse_end - parse_start) * 1000
            parse_timer.count = 1
            if bench:
                bench.children["Markdown Parsing"].append(parse_timer)
        else:
            msg.blocks = self.parser.parse(text)
        
        self.messages.append(msg)
        self.recalculate_layout()
        self.update()
        
        if bench:
            timer.record_time((time.perf_counter() - start) * 1000)

    def recalculate_layout(self):
        width = self.width()
        current_y = PADDING_Y
        for msg in self.messages:
            h = self.layout_engine.calculate_message_layout(msg, width, current_y)
            current_y += h + MSG_SPACING
        self.min_height = current_y
        self.setMinimumHeight(self.min_height)

    def _ensure_cache(self, block, line):
        """Ensures the line's render cache is populated."""
        if line.render_cache is None:
            # We use the text renderer's logic for PARAGRAPH, QUOTE, LIST_ITEM
            # Header and Code usually have simpler logic, but TextRenderer handles formatting
            if block.type in (BlockType.PARAGRAPH, BlockType.QUOTE, BlockType.LIST_ITEM, BlockType.HEADER):
                self.text_renderer.precalculate_line(line, block)
            else:
                line.render_cache = [(line.text, FormatType.NORMAL, None)]

    def _get_text_width(self, block, line, char_limit):
        """
        Calculates the pixel width of the text up to `char_limit` 
        accounting for variable fonts (Bold, Italic, Code).
        """
        self._ensure_cache(block, line)
        
        if not line.render_cache:
            return 0

        total_width = 0
        chars_processed = 0

        for text_seg, format_type, _ in line.render_cache:
            seg_len = len(text_seg)
            # --- FIX: Pass block.level for Headers ---
            font = self.styles.get_font(block.type, level=block.level, format_type=format_type)
            fm = QFontMetrics(font)

            if chars_processed + seg_len <= char_limit:
                # Fully include this segment
                total_width += fm.horizontalAdvance(text_seg)
                chars_processed += seg_len
            else:
                # Partial segment
                needed = char_limit - chars_processed
                total_width += fm.horizontalAdvance(text_seg[:needed])
                return total_width
                
        return total_width

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        clip_rect = event.rect()
        
        # 1. Backgrounds & Text
        for m_i, msg in enumerate(self.messages):
            if msg.y_pos + msg.total_height < clip_rect.top() or msg.y_pos > clip_rect.bottom(): continue
            
            # Draw Bubble
            bubble_w = self.width() * 0.85
            path = QPainterPath()
            path.addRoundedRect(msg.x_pos, msg.y_pos, bubble_w, msg.total_height, 12, 12)
            color = THEME["user_bg"] if msg.is_user else THEME["ai_bg"]
            painter.fillPath(path, QColor(color))

            # Draw Text
            for b_i, block in enumerate(msg.blocks):
                renderer = self.renderers.get(block.type, self.renderers[BlockType.PARAGRAPH])
                renderer.paint(painter, block, msg.x_pos, msg.y_pos, THEME, self.styles)

        # 2. Selection Overlay (Drawn on top)
        if self.sel_start and self.sel_end:
            start, end = sorted([self.sel_start, self.sel_end])
            
            def is_line_selected(m_i, b_i, l_i):
                return (start[0], start[1], start[2]) <= (m_i, b_i, l_i) <= (end[0], end[1], end[2])

            painter.setBrush(QColor(THEME["selection"]))
            painter.setPen(Qt.NoPen)

            # Optimization: Only loop visible messages for selection
            for m_i, msg in enumerate(self.messages):
                if msg.y_pos > clip_rect.bottom(): break
                if msg.y_pos + msg.total_height < clip_rect.top(): continue

                for b_i, block in enumerate(msg.blocks):
                    for l_i, line in enumerate(block.layout_lines):
                        if is_line_selected(m_i, b_i, l_i):
                            draw_y = msg.y_pos + line.rect.y()
                            draw_x = line.rect.x()
                            
                            # Default: Select whole line
                            x_s = 0
                            x_e = line.rect.width()

                            # If start of selection, calculate exact pixel start
                            if (m_i, b_i, l_i) == (start[0], start[1], start[2]):
                                x_s = self._get_text_width(block, line, start[3])

                            # If end of selection, calculate exact pixel end
                            if (m_i, b_i, l_i) == (end[0], end[1], end[2]):
                                x_e = self._get_text_width(block, line, end[3])
                            
                            sel_rect = QRect(draw_x + x_s, draw_y, x_e - x_s, line.rect.height())
                            painter.drawRect(sel_rect)

    def resizeEvent(self, event):
        self.recalculate_layout()
        super().resizeEvent(event)
    
    def get_cursor_at(self, pos: QPoint):
        """
        Hit testing that accounts for variable width fonts (Bold/Italic).
        """
        msg_idx = -1
        # 1. Find Message
        for i, m in enumerate(self.messages):
            if m.y_pos <= pos.y() <= m.y_pos + m.total_height:
                msg_idx = i
                break
        if msg_idx == -1: return None
        msg = self.messages[msg_idx]
        local_y = pos.y() - msg.y_pos

        # 2. Find Block
        block_idx = -1
        for i, b in enumerate(msg.blocks):
            if b.y_pos <= local_y <= b.y_pos + b.height + BLOCK_SPACING:
                block_idx = i
                break
        if block_idx == -1: return (msg_idx, 0, 0, 0)
        block = msg.blocks[block_idx]
        
        if not block.layout_lines:
            return (msg_idx, block_idx, 0, 0)
            
        # 3. Find Line
        line_idx = -1
        closest_dist = 99999
        
        # --- FIXED: Table Support ---
        # Instead of breaking on the first Y match, collect all lines on this Y plane (e.g. table cells)
        row_candidates = []
        
        for i, line in enumerate(block.layout_lines):
            line_rect_y = msg.y_pos + line.rect.y()
            line_h = line.rect.height()
            
            # Check overlap
            if line_rect_y <= pos.y() <= line_rect_y + line_h + LINE_SPACING:
                row_candidates.append(i)
            
            # Track closest (only used if no row_candidates found)
            # This handles clicking in vertical padding between blocks or lines
            if not row_candidates:
                dist = min(abs(pos.y() - line_rect_y), abs(pos.y() - (line_rect_y + line_h)))
                if dist < closest_dist:
                    closest_dist = dist
                    line_idx = i
        
        # If we found lines overlapping Y, find the one matching X
        if row_candidates:
            # Default to the right-most candidate if none match strictly
            line_idx = row_candidates[-1] 
            
            for i in row_candidates:
                line = block.layout_lines[i]
                # line.rect.x() is absolute widget X coordinate
                line_end_x = line.rect.x() + line.rect.width()
                
                # If cursor is to the left of this line's end, we pick it.
                if pos.x() <= line_end_x:
                    line_idx = i
                    break
        
        if line_idx == -1: line_idx = 0
        
        line_obj = block.layout_lines[line_idx]
        
        # 4. Find Character Index (Account for Formatting)
        self._ensure_cache(block, line_obj)
        
        local_x = pos.x() - line_obj.rect.x()
        if local_x <= 0: return (msg_idx, block_idx, line_idx, 0)
        if local_x >= line_obj.rect.width(): return (msg_idx, block_idx, line_idx, len(line_obj.text))

        current_pixel_x = 0
        char_offset = 0
        final_char_idx = len(line_obj.text)
        found = False

        if line_obj.render_cache:
            for text_seg, format_type, _ in line_obj.render_cache:
                # --- FIX: Pass block.level for Headers ---
                font = self.styles.get_font(block.type, level=block.level, format_type=format_type)
                fm = QFontMetrics(font)
                seg_width = fm.horizontalAdvance(text_seg)
                
                if current_pixel_x + seg_width >= local_x:
                    seg_local_x = local_x - current_pixel_x
                    for c in range(1, len(text_seg) + 1):
                        w = fm.horizontalAdvance(text_seg[:c])
                        if w > seg_local_x:
                            prev_w = fm.horizontalAdvance(text_seg[:c-1])
                            if (seg_local_x - prev_w) < (w - seg_local_x):
                                final_char_idx = char_offset + c - 1
                            else:
                                final_char_idx = char_offset + c
                            found = True
                            break
                    if not found:
                        final_char_idx = char_offset + len(text_seg)
                        found = True
                    break
                current_pixel_x += seg_width
                char_offset += len(text_seg)
        else:
             # Fallback (Shouldn't happen due to _ensure_cache)
             final_char_idx = len(line_obj.text)
             

        return (msg_idx, block_idx, line_idx, final_char_idx)

    def get_link_data_at(self, pos: QPoint):
        cursor = self.get_cursor_at(pos)
        if not cursor: return None
        
        m_i, b_i, l_i, _ = cursor
        if m_i >= len(self.messages): return None
        
        msg = self.messages[m_i]
        block = msg.blocks[b_i]
        if not block.layout_lines: return None
        line = block.layout_lines[l_i]
        
        # Ensure cache before checking links
        self._ensure_cache(block, line)
        if not line.render_cache: return None
        
        line_global_x = line.rect.x() 
        rel_x = pos.x() - line_global_x
        
        current_x = 0
        for text_seg, format_type, data in line.render_cache:
            font = self.styles.get_font(block.type, level=block.level, format_type=format_type)
            seg_w = QFontMetrics(font).horizontalAdvance(text_seg)
            
            if current_x <= rel_x <= current_x + seg_w:
                if format_type == FormatType.LINK:
                    return data
                return None
            
            current_x += seg_w
            
        return None

    def find_word_bounds(self, cursor):
        if not cursor: 
            return None, None
        m_i, b_i, l_i, char_idx = cursor
        
        if m_i >= len(self.messages): 
            return None, None
        msg = self.messages[m_i]
        
        if b_i >= len(msg.blocks): 
            return None, None
        block = msg.blocks[b_i]
        
        if not block.layout_lines or l_i >= len(block.layout_lines): 
            return None, None
        line = block.layout_lines[l_i]
        
        text = line.text
        if not text or char_idx >= len(text): 
            return None, None
        
        def is_word_char(c):
            return c.isalnum() or c == '_'
        
        if not is_word_char(text[char_idx]):
            return (m_i, b_i, l_i, char_idx), (m_i, b_i, l_i, char_idx)
        
        start_idx = char_idx
        while start_idx > 0 and is_word_char(text[start_idx - 1]):
            start_idx -= 1
        
        end_idx = char_idx
        while end_idx < len(text) - 1 and is_word_char(text[end_idx + 1]):
            end_idx += 1
        
        result = (m_i, b_i, l_i, start_idx), (m_i, b_i, l_i, end_idx + 1)
        return result

    def _hit_test_copy_button(self, pos: QPoint):
        """Check if global pos touches a copy button."""
        for msg in self.messages:
            if msg.y_pos <= pos.y() <= msg.y_pos + msg.total_height:
                local_pos = pos - QPoint(int(msg.x_pos), int(msg.y_pos))
                for block in msg.blocks:
                    if block.type == BlockType.CODE and block.copy_rect:
                        # block.copy_rect is relative to message
                        if block.copy_rect.contains(local_pos):
                            return block
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # 1. Check Copy Button Click
            copy_block = self._hit_test_copy_button(event.position().toPoint())
            if copy_block:
                QGuiApplication.clipboard().setText(copy_block.text)
                copy_block.show_copied_text = True
                self.update()
                
                # Reset text after 2 seconds
                QTimer.singleShot(2000, lambda b=copy_block: self._reset_copy_text(b))
                return

            link_data = self.get_link_data_at(event.position().toPoint())
            if link_data:
                self.hovered_url = link_data['url']
                return 

            current_time = event.timestamp()
            
            if self._double_click_time and current_time - self._double_click_time < 500:
                self._double_click_time = 0
                return

            self._is_double_click_selecting = False
            self._double_click_start = None
            self._double_click_end = None

            current_pos = event.position().toPoint()
            
            if (self._last_click_time and 
                current_time - self._last_click_time < 500 and
                self._last_click_pos and
                (current_pos - self._last_click_pos).manhattanLength() < 10):
                self._last_click_time = current_time
                self._last_click_pos = current_pos
                return

            cursor = self.get_cursor_at(current_pos)
            if cursor:
                self.sel_start = cursor
                self.sel_end = cursor
                self.is_selecting = True
                self.update()
            else:
                self.sel_start = None; self.sel_end = None; self.update()
            
            self._last_click_time = current_time
            self._last_click_pos = current_pos
        super().mousePressEvent(event)

    def _reset_copy_text(self, block):
        if block:
            block.show_copied_text = False
            self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        
        # 1. Check Copy Button Hover
        found_copy_hover = False
        needs_update = False
        
        # We need to iterate blocks to update their hover state
        # (Optimize: only search visible messages if needed, but this is fast enough)
        for msg in self.messages:
            # Simple optimization: check Y bounds
            if msg.y_pos > pos.y() or msg.y_pos + msg.total_height < pos.y():
                continue
                
            local_pos = pos - QPoint(int(msg.x_pos), int(msg.y_pos))
            for block in msg.blocks:
                if block.type == BlockType.CODE and block.copy_rect:
                    is_hovered = block.copy_rect.contains(local_pos)
                    if block.is_copy_hovered != is_hovered:
                        block.is_copy_hovered = is_hovered
                        needs_update = True
                    if is_hovered:
                        found_copy_hover = True

        if found_copy_hover:
            self.setCursor(Qt.PointingHandCursor)
        elif not self.is_selecting:
            # ... existing URL hover logic ...
            link_data = self.get_link_data_at(pos)
            if link_data:
                self.setCursor(Qt.PointingHandCursor)
                self.hovered_url = link_data['url']
                
                title = link_data.get('title')
                if title:
                    QToolTip.showText(event.globalPosition().toPoint(), title, self)
                else:
                    QToolTip.hideText()
            else:
                self.setCursor(Qt.IBeamCursor)
                self.hovered_url = None
                QToolTip.hideText()

        if needs_update:
            self.update()

        if self.is_selecting:
            cursor = self.get_cursor_at(pos)
            if cursor:
                if self._is_double_click_selecting:
                    start, end = self.find_word_bounds(cursor)
                    if start and end:
                        if cursor[3] < self._double_click_start[3] or (cursor[3] == self._double_click_start[3] and (cursor[2] < self._double_click_start[2] or cursor[1] < self._double_click_start[1] or cursor[0] < self._double_click_start[0])):
                            self.sel_start = start
                            self.sel_end = self._double_click_end
                        else:
                            self.sel_start = self._double_click_start
                            self.sel_end = end
                    else:
                        self.sel_end = cursor
                else:
                    self.sel_end = cursor
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.hovered_url and not self.is_selecting:
                clicked_data = self.get_link_data_at(event.position().toPoint())
                if clicked_data and clicked_data['url'] == self.hovered_url:
                    QDesktopServices.openUrl(QUrl(self.hovered_url))
            
            self.is_selecting = False
            self._is_double_click_selecting = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            cursor = self.get_cursor_at(event.position().toPoint())
            if cursor:
                start, end = self.find_word_bounds(cursor)
                if start and end:
                    self.sel_start = start
                    self.sel_end = end
                    self.is_selecting = True
                    self._last_click_time = 0
                    self._last_click_pos = None
                    self._double_click_time = event.timestamp()
                    self._double_click_start = start
                    self._double_click_end = end
                    self._is_double_click_selecting = True
                    self.update()

        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy): self.copy_selection()
        elif event.matches(QKeySequence.Paste): self.paste_requested.emit()
        else: super().keyPressEvent(event)
    def get_selected_text(self):
        if self.sel_start is None or self.sel_end is None: return ""
        if self.sel_start == self.sel_end: return ""
        start, end = sorted([self.sel_start, self.sel_end])
        result = []
        for m_i in range(start[0], end[0] + 1):
            if m_i >= len(self.messages): break
            msg = self.messages[m_i]
            b_start = start[1] if m_i == start[0] else 0
            b_end = end[1] if m_i == end[0] else len(msg.blocks) - 1
            for b_i in range(b_start, b_end + 1):
                if b_i >= len(msg.blocks): break
                block = msg.blocks[b_i]
                if not block.layout_lines: continue
                l_start = start[2] if (m_i == start[0] and b_i == start[1]) else 0
                l_end = end[2] if (m_i == end[0] and b_i == end[1]) else len(block.layout_lines) - 1
                for l_i in range(l_start, l_end + 1):
                    if l_i >= len(block.layout_lines): break
                    line = block.layout_lines[l_i]
                    text = line.text
                    c_start = start[3] if (m_i == start[0] and b_i == start[1] and l_i == start[2]) else 0
                    c_end = end[3] if (m_i == end[0] and b_i == end[1] and l_i == end[2]) else len(text)
                    result.append(text[c_start:c_end])
                result.append("\n")
            result.append("\n\n")
        return "".join(result).strip()
    def copy_selection(self):
        text = self.get_selected_text()
        if text: QGuiApplication.clipboard().setText(text)
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(f"QMenu {{ background: {THEME['surface']}; color: {THEME['text']}; border: 1px solid {THEME['border']}; }} QMenu::item:selected {{ background: {THEME['user_bg']}; }}")
        copy_action = QAction("Copy", self)
        copy_action.triggered.connect(self.copy_selection)
        if not self.sel_start or self.sel_start == self.sel_end: copy_action.setEnabled(False)
        paste_action = QAction("Paste", self)
        paste_action.triggered.connect(lambda: self.paste_requested.emit())
        menu.addAction(copy_action)
        menu.addAction(paste_action)
        menu.exec(event.globalPos())