# extensions/web_search/__init__.py
import sys
import os
import webbrowser
import subprocess
import urllib.parse
from typing import List, Optional, Tuple, Dict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QCheckBox, 
    QLineEdit, QPushButton, QFileDialog, 
    QHBoxLayout, QGroupBox, QScrollArea, QFrame, 
    QComboBox, QSizePolicy
)
from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, 
    QPoint, Property, QRect
)
from PySide6.QtGui import QColor, QPainter, QBrush, QPen

from api.extension import Extension
from api.types import ResultItem, Action

# --- Configuration Constants ---
DEFAULT_ENGINES = {
    "google": {"name": "Google", "url": "https://www.google.com/search?q={}", "default_bang": "!g"},
    "googleai" : {"name": "Google AI Mode", "url": "https://www.google.com/search?q={}&udm=50", "default_bang": "!gai"},
    "bing": {"name": "Bing", "url": "https://www.bing.com/search?q={}", "default_bang": "!b"},
    "duckduckgo": {"name": "DuckDuckGo", "url": "https://duckduckgo.com/?q={}", "default_bang": "!ddg"},
    "brave": {"name": "Brave Search", "url": "https://search.brave.com/search?q={}", "default_bang": "!br"},
    "yahoo": {"name": "Yahoo", "url": "https://search.yahoo.com/search?p={}", "default_bang": "!y"},
    "youtube": {"name": "YouTube", "url": "https://www.youtube.com/results?search_query={}", "default_bang": "!yt"},
    "wikipedia": {"name": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Special:Search?search={}", "default_bang": "!w"},
    "t3": {"name": "T3 chat", "url": "https://t3.chat/new?model=kimi-k2&q={}", "default_bang": "!t3"},
    "reddit": {"name": "Reddit", "url": "https://www.reddit.com/search/?q={}", "default_bang": "!r"},
    "github": {"name": "GitHub", "url": "https://github.com/search?q={}", "default_bang": "!gh"},
    "stackoverflow": {"name": "Stack Overflow", "url": "https://stackoverflow.com/search?q={}", "default_bang": "!so"},
    "amazon": {"name": "Amazon", "url": "https://www.amazon.com/s?k={}", "default_bang": "!a"},
    "wolfram": {"name": "WolframAlpha", "url": "https://www.wolframalpha.com/input/?i={}", "default_bang": "!wa"},
    "maps": {"name": "Google Maps", "url": "https://www.google.com/maps/search/{}", "default_bang": "!map"},
    "mdn": {"name": "MDN Web Docs", "url": "https://developer.mozilla.org/en-US/search?q={}", "default_bang": "!mdn"},
    "pypi": {"name": "PyPI", "url": "https://pypi.org/search/?q={}", "default_bang": "!pypi"},
    "npm": {"name": "NPM", "url": "https://www.npmjs.com/search?q={}", "default_bang": "!npm"},
    "imdb": {"name": "IMDb", "url": "https://www.imdb.com/find?q={}", "default_bang": "!imdb"},
    "twitter": {"name": "X (Twitter)", "url": "https://twitter.com/search?q={}", "default_bang": "!tw"},
    "twitch": {"name": "Twitch", "url": "https://www.twitch.tv/search?term={}", "default_bang": "!tv"},
    "perplexity": {"name": "Perplexity AI", "url": "https://www.perplexity.ai/search?q={}", "default_bang": "!pp"},
    "svgrepo": {"name": "SVG Repo", "url": "https://www.svgrepo.com/vectors/{}/" , "default_bang": "!svg"}
}
# --- Custom UI Components ---

class Toggle(QCheckBox):
    """
    A modern iOS/Android style toggle switch.
    Inherits from QCheckBox for easy state management.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(45, 26)
        
        # Colors
        self._bg_color = "#777"      # Off color
        self._circle_color = "#DDD"  # Circle color
        self._active_color = "#3a86ff" # On color (Blue)
        
        # Animation properties
        self._circle_position = 3
        self._anim = QPropertyAnimation(self, b"circle_position", self)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.setDuration(200)  # ms

        self.stateChanged.connect(self.start_transition)

    # Property for animation
    def get_circle_position(self):
        return self._circle_position

    def set_circle_position(self, pos):
        self._circle_position = pos
        self.update()

    circle_position = Property(float, get_circle_position, set_circle_position)

    def start_transition(self, state):
        self._anim.stop()
        if state: # Checked
            self._anim.setEndValue(self.width() - 23)
        else: # Unchecked
            self._anim.setEndValue(3)
        self._anim.start()

    def hitButton(self, pos: QPoint):
        return self.rect().contains(pos)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Draw Background (Track)
        rect = QRect(0, 0, self.width(), self.height())
        if self.isChecked():
            p.setBrush(QColor(self._active_color))
            p.setPen(Qt.NoPen)
        else:
            p.setBrush(QColor(self._bg_color))
            p.setPen(Qt.NoPen)
        
        p.drawRoundedRect(0, 0, rect.width(), rect.height(), 13, 13)

        # Draw Circle (Handle)
        p.setBrush(QColor(self._circle_color))
        p.drawEllipse(int(self._circle_position), 3, 20, 20)
        p.end()

# --- Main Extension Logic ---

class WebSearchExtension(Extension):
    def __init__(self, context):
        super().__init__(context)
        self.name = "Web Search"
        self.description = "Fallback web search for configured engines."
        # Store the path to the assets directory relative to this file
        self.assets_dir = os.path.join(os.path.dirname(__file__), 'assets')

    def on_input(self, text: str) -> List[ResultItem]:
        if not text or len(text.strip()) == 0:
            return []

        # 1. Load Configurations
        active_ids = self.get_setting("active_engines", ["google"])
        saved_bangs = self.get_setting("bangs", {})
        
        # Build Bang Map: "!yt" -> "youtube"
        bang_map = {}
        for eid, data in DEFAULT_ENGINES.items():
            # Prefer saved bang, fallback to default
            bang_str = saved_bangs.get(eid, data["default_bang"])
            if bang_str:
                bang_map[bang_str] = eid

        # 2. Check for Bangs in input
        target_engine_id = None
        clean_text = text
        
        tokens = text.split()
        for token in tokens:
            if token in bang_map:
                target_engine_id = bang_map[token]
                # Remove the bang from the query text
                tokens.remove(token)
                clean_text = " ".join(tokens)
                break
        
        # 3. Determine which engines to use
        engines_to_show = []

        if target_engine_id:
            # Bang found! Override everything and only show this engine
            if target_engine_id in DEFAULT_ENGINES:
                engines_to_show.append(target_engine_id)
        else:
            # No bang, show all active engines
            for eid in active_ids:
                if eid in DEFAULT_ENGINES:
                    engines_to_show.append(eid)

        # 4. Generate Results
        results = []
        for engine_id in engines_to_show:
            engine_data = DEFAULT_ENGINES[engine_id]
            name = engine_data["name"]
            url_template = engine_data["url"]
            
            # If query is empty (user typed just "!yt"), don't search yet
            display_desc = f"Search for '{clean_text}' in {name}"
            if not clean_text.strip():
                display_desc = f"Type to search {name}..."
            
            action = Action(
                name=f"Search {name}",
                handler=lambda u=url_template, t=clean_text: self.open_search(u, t),
                close_on_action=True
            )
            
            # If a bang was used, boost score significantly to ensure it's top
            score = 100 if target_engine_id else 1

            # Resolve Icon Path
            # Looks for extensions/web_search/assets/{engine_id}.svg
            # Example: assets/google.svg, assets/youtube.svg
            icon_path = os.path.join(self.assets_dir, f"{engine_id}.svg")
            
            # Safety check: if the specific icon doesn't exist, pass None 
            # (UI will show default extension icon)
            if not os.path.exists(icon_path):
                icon_path = None

            item = ResultItem(
                id=f"web_search_{engine_id}",
                name=f"Search {name}",
                description=display_desc,
                icon_path=icon_path, 
                action=action,
                score=score 
            )
            results.append(item)
            
        return results

    def open_search(self, url_template: str, query: str):
        """Opens the browser based on user settings."""
        if not query.strip():
            return 

        encoded_query = urllib.parse.quote_plus(query)
        final_url = url_template.format(encoded_query)
        
        browser_mode = self.get_setting("browser_mode", "system") # 'system' or 'custom'
        custom_path = self.get_setting("browser_path", "")

        try:
            if browser_mode == "custom" and custom_path and os.path.exists(custom_path):
                if sys.platform == "win32":
                    subprocess.Popen([custom_path, final_url])
                else:
                    subprocess.Popen([custom_path, final_url])
            else:
                webbrowser.open(final_url)
        except Exception as e:
            print(f"[WebSearch] Error opening browser: {e}")
            webbrowser.open(final_url)

    def get_settings_widget(self) -> Optional[QWidget]:
        return WebSearchSettingsWidget(self)


def detect_installed_browsers() -> List[Tuple[str, str]]:
    """
    Scans Windows Registry for registered browsers.
    Returns list of tuples: (Display Name, Exe Path)
    """
    browsers = []
    if sys.platform != "win32":
        return browsers

    import winreg
    
    # Locations to check
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet"),
        (winreg.HKEY_CURRENT_USER, r"Software\Clients\StartMenuInternet")
    ]

    for root, path in roots:
        try:
            with winreg.OpenKey(root, path) as key:
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            try:
                                name, _ = winreg.QueryValueEx(subkey, None) 
                            except OSError:
                                name = subkey_name

                            cmd_path = fr"{subkey_name}\shell\open\command"
                            with winreg.OpenKey(key, cmd_path) as cmd_key:
                                raw_cmd, _ = winreg.QueryValueEx(cmd_key, None)
                                clean_cmd = raw_cmd.strip('"')
                                browsers.append((name, clean_cmd))
                    except OSError:
                        continue
        except OSError:
            continue

    seen_paths = set()
    unique_browsers = []
    for name, path in browsers:
        if path.lower() not in seen_paths:
            unique_browsers.append((name, path))
            seen_paths.add(path.lower())

    return unique_browsers


class WebSearchSettingsWidget(QWidget):
    def __init__(self, extension):
        super().__init__()
        self.extension = extension
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignTop)
        
        self.detected_browsers = detect_installed_browsers()
        
        self.setup_browser_section()
        self.layout.addSpacing(20)
        self.setup_engines_section()


    def setup_browser_section(self):
        group = QGroupBox("Browser Settings")
        layout = QVBoxLayout(group)

        # 1. Dropdown
        lbl = QLabel("Select Browser:")
        layout.addWidget(lbl)
        
        self.combo = QComboBox()
        self.combo.addItem("System Default", "system")
        for name, path in self.detected_browsers:
            self.combo.addItem(f"{name} (Detected)", path)
        self.combo.addItem("Custom Select...", "custom_manual")
        
        self.combo.currentIndexChanged.connect(self.on_combo_changed)
        layout.addWidget(self.combo)

        # 2. Custom Path Area
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("C:\\Path\\To\\browser.exe")
        self.path_input.textChanged.connect(self.save_custom_path)
        
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self.browse_file)
        
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(btn_browse)
        
        self.path_widget = QWidget()
        self.path_widget.setLayout(path_layout)
        layout.addWidget(self.path_widget)
        
        self.load_browser_state()
        self.layout.addWidget(group)

    def load_browser_state(self):
        current_mode = self.extension.get_setting("browser_mode", "system")
        current_path = self.extension.get_setting("browser_path", "")

        if current_mode == "system":
            self.combo.setCurrentIndex(0)
            self.path_widget.setVisible(False)
        else:
            found = False
            for i, (_, path) in enumerate(self.detected_browsers):
                if path == current_path:
                    self.combo.setCurrentIndex(i + 1)
                    found = True
                    self.path_widget.setVisible(False) 
                    break
            
            if not found:
                self.combo.setCurrentIndex(self.combo.count() - 1)
                self.path_input.setText(current_path)
                self.path_widget.setVisible(True)

    def on_combo_changed(self, index):
        data = self.combo.currentData()
        if data == "system":
            self.extension.set_setting("browser_mode", "system")
            self.path_widget.setVisible(False)
        elif data == "custom_manual":
            self.extension.set_setting("browser_mode", "custom")
            self.path_widget.setVisible(True)
            self.path_input.setFocus()
        else:
            self.extension.set_setting("browser_mode", "custom")
            self.extension.set_setting("browser_path", data)
            self.path_widget.setVisible(False)

    def save_custom_path(self, text):
        if self.combo.currentData() == "custom_manual":
            self.extension.set_setting("browser_path", text)

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Browser Executable", "", "Executables (*.exe);;All Files (*)")
        if file_path:
            self.path_input.setText(file_path)
            if self.combo.currentData() != "custom_manual":
                 self.combo.setCurrentIndex(self.combo.count() - 1)
            self.extension.set_setting("browser_path", file_path)

    def setup_engines_section(self):
        group = QGroupBox("Search Engines & Bangs")
        layout = QVBoxLayout(group)
        
        lbl = QLabel("Toggle active engines and configure bangs (e.g., !yt):")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setFixedHeight(300)
        scroll.setStyleSheet("""
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
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(10)
        
        active_engines = self.extension.get_setting("active_engines", ["google"])
        saved_bangs = self.extension.get_setting("bangs", {})
        
        self.toggles = {}
        self.bang_inputs = {}
        
        for eid, data in DEFAULT_ENGINES.items():
            # Row Container
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 10, 0)
            
            # Label
            name_lbl = QLabel(data["name"])
            name_lbl.setFixedWidth(120)
            name_lbl.setStyleSheet("font-size: 14px;")
            
            # Bang Input
            bang_input = QLineEdit()
            bang_input.setPlaceholderText(data["default_bang"])
            # Load saved bang or default
            current_bang = saved_bangs.get(eid, data["default_bang"])
            bang_input.setText(current_bang)
            bang_input.setFixedWidth(60)
            bang_input.setAlignment(Qt.AlignCenter)
            # Connect editing finished signal to save
            bang_input.editingFinished.connect(self.save_engines)
            
            self.bang_inputs[eid] = bang_input

            # Custom Toggle
            toggle = Toggle()
            toggle.setChecked(eid in active_engines)
            toggle.stateChanged.connect(self.save_engines)
            
            self.toggles[eid] = toggle
            
            row_layout.addWidget(name_lbl)
            row_layout.addWidget(bang_input)
            row_layout.addStretch() 
            row_layout.addWidget(toggle)
            
            content_layout.addWidget(row_widget)
            
        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        self.layout.addWidget(group)

    def save_engines(self):
        # 1. Save Active Toggles
        active = []
        for eid, toggle in self.toggles.items():
            if toggle.isChecked():
                active.append(eid)
        self.extension.set_setting("active_engines", active)
        
        # 2. Save Bangs
        bangs = {}
        for eid, inp in self.bang_inputs.items():
            text = inp.text().strip()
            if text:
                bangs[eid] = text
        self.extension.set_setting("bangs", bangs)

# Export
Extension = WebSearchExtension