# core/ui/launcher.py
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFrame, QGraphicsDropShadowEffect)
from PySide6.QtCore import (Qt, QTimer, QPropertyAnimation, QEasingCurve, 
                            Signal, Slot, QObject, QRect, QEvent)
from PySide6.QtGui import QColor, QAction, QKeySequence, QPalette, QPainter

from .theme import THEME
from .components.search_bar import SearchBar
from .components.result_list import ResultListContainer
from .components.footer import Footer
from .components.command_menu import CommandMenu

import time
import ctypes
from ctypes import wintypes

# Windows API
class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", wintypes.INT), ("cxRightWidth", wintypes.INT),
                ("cyTopHeight", wintypes.INT), ("cyBottomHeight", wintypes.INT)]

user32 = ctypes.WinDLL("user32")
dwmapi = ctypes.WinDLL("dwmapi")

# Constants
GWL_STYLE = -16 
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_POPUP = 0x80000000
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMSBT_MAINWINDOW = 3
DWMWCP_ROUND = 2
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

def safe_cast_to_long(value):
    value = value & 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


class Profiler:
    def __init__(self, name):
        self.name = name
        self.start = None

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (time.perf_counter() - self.start) * 1000  # Convert to ms
        if elapsed > 1.0: # Only print if it takes noticeable time (>1ms)
            print(f"[{self.name}] took {elapsed:.2f}ms")

# --- RESULT RECEIVER (Async Bridge) ---
class ResultReceiver(QObject):
    results_ready = Signal(list, int, str)

class LauncherWindow(QWidget):
    VISUAL_WIDTH = 800
    VISUAL_COMPACT_HEIGHT = 80 
    MAX_VISIBLE_ITEMS = 6
    WINDOW_MARGIN = 0 
    ROW_HEIGHT = 64
    
    def __init__(self, core_app):
        super().__init__()
        self.core = core_app
        
        # State for restoring query when going back
        self._last_root_query = ""

        # Async signals
        self.receiver = ResultReceiver()
        self.receiver.results_ready.connect(self.handle_results)
        
        self.base_y_anchor = None
        self.setup_layout()
        self.setup_connections()
        self.setup_shortcuts()
        
        # Install event filter on the input to catch triggers (like Tab)
        self.search_bar.search_input.installEventFilter(self)

        # Animations
        self.anim_geometry = QPropertyAnimation(self, b"geometry")
        self.anim_geometry.setEasingCurve(QEasingCurve.OutExpo) 
        self.anim_geometry.setDuration(300)
        self.anim_geometry.finished.connect(self.on_animation_finished)

        # Search debouncing
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self.perform_search)

        # Resize debouncing - prevents flicker when typing fast
        self.resize_debounce_timer = QTimer(self)
        self.resize_debounce_timer.setSingleShot(True)
        self.resize_debounce_timer.setInterval(150)
        self.resize_debounce_timer.timeout.connect(self._do_resize)
        self._pending_item_count = 0
        self._pending_content_height = 0

    def setup_layout(self):
        # EXACT setup from prototype - NO FramelessWindowHint
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Start invisible for border-flash workaround
        self.setWindowOpacity(0.0)
        
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        self.setPalette(palette)
        
        self.compact_h_total = self.VISUAL_COMPACT_HEIGHT + (self.WINDOW_MARGIN * 2)
        total_w = self.VISUAL_WIDTH + (self.WINDOW_MARGIN * 2)
        # --- THE FIX ---
        self.setFixedWidth(total_w) # Force the window to stay at 800px + margins
        self.resize(total_w, self.compact_h_total)

        # Main Layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(self.WINDOW_MARGIN, self.WINDOW_MARGIN, self.WINDOW_MARGIN, self.WINDOW_MARGIN)
        
        # Container Frame
        self.container = QFrame()
        self.container.setObjectName("Container")
        self.container.setStyleSheet(f"""
            QFrame#Container {{
                background-color: {THEME['bg']};
                border-radius: 10px;
                border: 1px solid {THEME['border']};
            }}
            QFrame#Separator {{
                color: {THEME['surface']}; background-color: {THEME['surface']};
                border: none; min-height: 1px; max-height: 1px;
            }}
        """)
        
        self.inner_layout = QVBoxLayout(self.container)
        self.inner_layout.setContentsMargins(0, 0, 0, 0)
        self.inner_layout.setSpacing(0)

        # Components
        self.search_bar = SearchBar(self)
        self.separator = QFrame()
        self.separator.setObjectName("Separator")
        self.separator.setFrameShape(QFrame.HLine)
        self.separator.hide()
        
        self.result_container = ResultListContainer(self)
        self.result_container.hide()
        
        self.footer = Footer(self)

        self.inner_layout.addWidget(self.search_bar)
        self.inner_layout.addWidget(self.separator)
        self.inner_layout.addWidget(self.result_container)
        self.inner_layout.addWidget(self.footer)
        
        # Command Menu
        self.command_menu = CommandMenu(self.container)
        self.command_menu.hide()
        self.command_menu.action_triggered.connect(self.execute_action)

        self.main_layout.addWidget(self.container)

    def setup_connections(self):
        # Search Bar
        self.search_bar.text_changed.connect(self.on_text_edited)
        self.search_bar.return_pressed.connect(self.on_enter_pressed)
        self.search_bar.back_clicked.connect(lambda: self.core.exit_extension_mode())
        
        # Navigation
        self.search_bar.nav_requested.connect(self.handle_navigation)
        
        # Ctrl+K Detection
        self.search_bar.command_menu_requested.connect(self.toggle_command_menu)
        
        # Event Handling
        self.search_bar.escape_pressed.connect(self.handle_escape)
        
        # Result List
        self.result_container.item_activated.connect(self.execute_item_data)
        self.result_container.selection_changed.connect(self.update_footer_info)

    def setup_shortcuts(self):
        # Backup shortcut for when SearchBar doesn't have focus
        self.shortcut_actions = QAction(self)
        self.shortcut_actions.setShortcut(QKeySequence("Ctrl+K"))
        self.shortcut_actions.triggered.connect(self.toggle_command_menu)
        self.addAction(self.shortcut_actions)

    def paintEvent(self, event):
        # Clear background for Mica - EXACT from prototype
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)

    def showEvent(self, event):
        # EXACT from prototype - ensure opacity 0 before showing
        self.setWindowOpacity(0.0)
        
        current_y = self.y()
        current_h = self.height()
        expansion_diff = current_h - self.compact_h_total
        self.base_y_anchor = current_y + (expansion_diff * 0.15)
        super().showEvent(event)
        
        # Apply Mica workaround after showing
        QTimer.singleShot(0, self._apply_mica)

    def _apply_mica(self):
        hwnd = self.winId()
        
        # Apply DWM Mica
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 
                                     ctypes.byref(wintypes.DWORD(1)), 4)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, 
                                     ctypes.byref(wintypes.DWORD(DWMSBT_MAINWINDOW)), 4)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                     ctypes.byref(wintypes.DWORD(DWMWCP_ROUND)), 4)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(MARGINS(-1, -1, -1, -1)))
        
        # Border flash workaround - EXACT from prototype
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        style = (style | WS_CAPTION | WS_THICKFRAME) & ~WS_POPUP
        user32.SetWindowLongW(hwnd, GWL_STYLE, safe_cast_to_long(style))
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 
                           SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        
        # Schedule border removal - EXACT timing from prototype
        QTimer.singleShot(10, lambda: self._remove_borders(hwnd))
        
    def _remove_borders(self, hwnd):
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        style = (style & ~(WS_CAPTION | WS_THICKFRAME)) | WS_POPUP
        user32.SetWindowLongW(hwnd, GWL_STYLE, safe_cast_to_long(style))
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                           SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        
        # Reveal window - EXACT from prototype
        self.setWindowOpacity(1.0)

    def resizeEvent(self, event):
        # Position Command Menu at bottom right, just above footer
        if self.command_menu:
            menu_w = self.command_menu.width()
            menu_h = self.command_menu.height()
            cw = self.container.width()
            ch = self.container.height()
            
            # 10px padding from right, 45px from bottom
            x = cw - menu_w - 10
            y = ch - menu_h - 45
            self.command_menu.move(x, y)
        super().resizeEvent(event)

    # --- MODE SWITCHING ---
    def set_mode_root(self):
        self.search_bar.set_mode_root()
        self.result_container.remove_custom_widget()
        self.command_menu.hide()
        
        # Logic to restore previous query if it exists
        if self._last_root_query:
            restored_text = self._last_root_query
            self._last_root_query = ""
            self.search_bar.set_text(restored_text)
            self.search_bar.search_input.selectAll()
            # Manually trigger search for the restored text
            self.on_text_edited(restored_text)
        else:
            self.result_container.update_results([])
            self.animate_resize(0, 0)

    def set_mode_extension(self, ext_name, custom_widget=None):
        # Capture current text before switching
        self._last_root_query = self.search_bar.get_text()

        self.search_bar.set_mode_extension(ext_name)
        self.command_menu.hide()
        
        if custom_widget:
            self.result_container.show_custom_widget(custom_widget)
            self.separator.show()
            self.result_container.show()
            self.footer.show_border(True)
            self.animate_geometry(600)
        else:
            self.result_container.remove_custom_widget()
            self.result_container.update_results([])
            self.perform_search()

    # --- LOGIC ---
    def on_text_edited(self, text):
        self.command_menu.hide() 
        
        if self.result_container.currentIndex() == 1:
            widget = self.result_container.get_custom_widget()
            if hasattr(widget, "filter_items"):
                widget.filter_items(text)
            return

        stripped = text.strip()
        should_search = len(stripped) > 0

        if not should_search:
            status = "Start typing..."
            self.footer.set_text(status)
            self.result_container.update_results([])
            self.schedule_resize(0, 0)
            self.search_timer.stop()
            return

        self.search_timer.start()

    def perform_search(self):
        if self.result_container.currentIndex() != 0: return
        self.resize_debounce_timer.stop()

        text = self.search_bar.get_text()
        
        self.footer.set_text("Searching...")

        def bridge_callback(results, qid):
            self.receiver.results_ready.emit(results, qid, text)
            
        self.core.query(text, bridge_callback)

    @Slot(list, int, str)
    def handle_results(self, results, qid, query_text):
        if self.result_container.currentIndex() != 0: return
        self.resize_debounce_timer.stop()
        if query_text != self.search_bar.get_text(): return
        
        with Profiler("Total Handle Results"):
            count = len(results)
            
            with Profiler("Update List Items"):
                content_height = self.result_container.update_results(results)
            
            if count == 0:
                self.footer.set_text("No results found.")
                self.schedule_resize(0, 0)
            else:
                self.update_footer_info(self.result_container.get_current_data())
                with Profiler("Setup Animation"):
                    self.schedule_resize(count, content_height)

    def update_footer_info(self, item_data):
        if item_data and self.result_container.currentIndex() == 0:
            actions_text = "Actions ⌘K" if item_data.context_actions else ""
            self.footer.set_text(f"{item_data.name}  |  {actions_text}")

    # --- ACTION EXECUTION ---
    def on_enter_pressed(self):
        if self.command_menu.isVisible():
            self.command_menu.execute_current()
            return

        if self.result_container.currentIndex() == 1:
            widget = self.result_container.get_custom_widget()
            if hasattr(widget, "handle_enter"):
                widget.handle_enter()
            return

        data = self.result_container.get_current_data()
        self.execute_item_data(data)

    def execute_item_data(self, item_data):
        if not item_data: return
        if item_data.action:
            self.execute_action(item_data.action)

    def execute_action(self, action):
        if action.close_on_action:
            self.core.hide_window()
        action.handler()
        self.command_menu.hide()
        # Return focus to input if window is still open
        if self.isVisible():
            self.search_bar.focus_input()

    # --- KEY HANDLING & MENU ---
    def toggle_command_menu(self):
        if self.command_menu.isVisible():
            self.command_menu.hide()
            # Return focus to input when closing menu
            self.search_bar.focus_input()
            return

        # Scenario 1: Standard List View (Root or Scoped)
        # This uses the specific actions of the selected ResultItem
        if self.result_container.currentIndex() == 0:
            data = self.result_container.get_current_data()
            if not data or not data.context_actions:
                return
            self.command_menu.set_actions(data.context_actions)
        
        # Scenario 2: Custom Extension View (e.g. AI Chat)
        # This uses global actions defined by the extension itself (OPTIONAL)
        elif self.result_container.currentIndex() == 1:
            ext_instance = self.core.get_active_extension_instance()
            if not ext_instance:
                return
            
            actions = ext_instance.get_context_actions()
            if not actions:
                return
            
            self.command_menu.set_actions(actions)

        self.resizeEvent(None) # Recalculate position
        self.command_menu.show()
        self.command_menu.raise_()

    def handle_navigation(self, direction):
        if self.command_menu.isVisible():
            self.command_menu.navigate(direction)
            return

        # Handle Custom View (Extension Mode)
        if self.result_container.currentIndex() == 1:
            widget = self.result_container.get_custom_widget()
            if hasattr(widget, "navigate"):
                widget.navigate(direction)
        # Handle Standard Result List
        else:
            self.result_container.navigate(direction)

    def handle_escape(self):
        if self.command_menu.isVisible():
            self.command_menu.hide()
            self.search_bar.focus_input()
            return

        if self.core.active_extension:
            self.core.exit_extension_mode()
        else:
            self.core.hide_window()

    def eventFilter(self, obj, event):
        # Handle Triggers in Root Mode (e.g. Tab for AI)
        if obj == self.search_bar.search_input and event.type() == QEvent.KeyPress:
            if self.result_container.currentIndex() == 0: # Only in Root Mode
                key = event.key()
                modifiers = event.modifiers()
                
                # Check all extensions for a matching trigger
                for ext in self.core.pm.extensions:
                    if getattr(ext, 'trigger_key', None) == key:
                        
                        is_char = (Qt.Key_A <= key <= Qt.Key_Z) or (Qt.Key_0 <= key <= Qt.Key_9)
                        has_mod = modifiers != Qt.NoModifier
                        
                        if is_char and not has_mod:
                            continue
                            
                        # Match found! Switch mode and consume event.
                        self.core.enter_extension_mode(ext)
                        return True

        # Existing Extension-Specific Key Handling
        # CHANGED: Added `and not self.command_menu.isVisible()`
        # This ensures that if the command menu is open, we do NOT send keys 
        # to the extension, but let them fall through to SearchBar/handle_navigation.
        if self.result_container.currentIndex() == 1 and event.type() == QEvent.KeyPress:
             if not self.command_menu.isVisible():
                 widget = self.result_container.get_custom_widget()
                 if hasattr(widget, "handle_key"):
                    if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                        widget.handle_key(event)
                        return True
                    
        return super().eventFilter(obj, event)

    # --- ANIMATION ---
    def animate_resize(self, item_count, content_height):
        if self.result_container.currentIndex() == 1: return

        if item_count == 0:
            target_h = self.compact_h_total
            self.separator.hide()
            self.result_container.hide()
            self.footer.show_border(False)
        else:
            max_list_h = self.MAX_VISIBLE_ITEMS * self.ROW_HEIGHT
            list_h = min(content_height, max_list_h) + 10
            target_h = self.compact_h_total + list_h
            
            self.separator.show()
            self.result_container.show()
            self.footer.show_border(True)

        self.animate_geometry(target_h)

    def animate_geometry(self, target_h):
        current = self.geometry()
        target_total_h = target_h if target_h == self.compact_h_total else target_h + (self.WINDOW_MARGIN * 2)
        
        if current.height() == target_total_h:
            if target_h == self.compact_h_total: self.on_animation_finished()
            return

        if self.base_y_anchor is None:
            self.base_y_anchor = current.y()

        expansion = target_total_h - self.compact_h_total
        bias = 0.15 
        
        target_y = int(self.base_y_anchor - (expansion * bias))
        target_rect = QRect(current.x(), target_y, current.width(), target_total_h)
        
        self.anim_geometry.stop()
        self.anim_geometry.setStartValue(current)
        self.anim_geometry.setEndValue(target_rect)
        self.anim_geometry.start()

    def on_animation_finished(self):
        if self.geometry().height() <= self.compact_h_total + 2:
            self.separator.hide()
            self.result_container.hide()
            self.footer.show_border(False)

    def schedule_resize(self, item_count, content_height):
        self._pending_item_count = item_count
        self._pending_content_height = content_height
        self.resize_debounce_timer.start()

    def _do_resize(self):
        self.animate_resize(self._pending_item_count, self._pending_content_height)
