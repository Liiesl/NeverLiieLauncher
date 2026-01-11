# extensions/ai/__init__.py
import os
from typing import List
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QScrollArea, 
                               QFrame, QSizePolicy, QApplication, QLineEdit,
                               QFormLayout, QPushButton, QMessageBox, 
                               QComboBox, QCheckBox, QHBoxLayout, QButtonGroup, QToolButton)
from PySide6.QtCore import Qt, Signal, QThread, Slot, QSize

from google import genai
from google.genai import types, errors

from api.extension import Extension
from api.types import Action
# Import the custom Markdown Engine
from .markdown_engine.widget import ChatCanvas
from .markdown_engine.constants import THEME

# --- WORKER THREAD ---
class GeminiWorker(QThread):
    response_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, client, model_name, history, user_input, persona_instruction=""):
        super().__init__()
        self.client = client
        self.model_name = model_name
        self.history = history 
        self.user_input = user_input
        self.persona_instruction = persona_instruction

    def run(self):
        if not self.client:
            self.error_occurred.emit("API Key not configured. Please go to Settings > AI Chat.")
            return

        try:
            contents = []
            
            # Inject Persona/System Instruction if exists (Simulated via first message or config)
            if self.persona_instruction:
                 # Note: Gemini 1.5+ supports system_instruction in config, 
                 # but for simplicity we assume standard message structure or config injection
                 pass 

            for msg in self.history:
                role = 'model' if msg['role'] == 'model' else 'user'
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg['text'])]
                ))

            contents.append(types.Content(
                role='user',
                parts=[types.Part.from_text(text=self.user_input)]
            ))
            
            # config setup
            gen_config = types.GenerateContentConfig(
                temperature=0.7,
                system_instruction=self.persona_instruction if self.persona_instruction else None
            )

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=gen_config
            )
            
            if response.text:
                self.response_ready.emit(response.text)
            else:
                self.error_occurred.emit("No text returned from API.")

        except errors.APIError as e:
            self.error_occurred.emit(f"API Error: {e.message}")
        except Exception as e:
            self.error_occurred.emit(f"System Error: {str(e)}")

# --- UI COMPONENTS ---

class ChatView(QWidget):
    def __init__(self, parent_window, extension):
        super().__init__()
        self.parent_window = parent_window
        self.extension = extension
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. Setup Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # 2. Setup Canvas (The Markdown Engine)
        self.canvas = ChatCanvas()
        self.canvas.paste_requested.connect(self.handle_paste_request)
        self.scroll_area.setWidget(self.canvas)
        
        self.layout.addWidget(self.scroll_area)

        self.history = [] 
        self.is_loading = False
        
        # Check configuration immediately
        if not self.extension.client:
             self.canvas.add_message("⚠️ **API Key not found.**\nPlease configure it in `Settings > AI Chat`.", is_user=False)
        elif not self.extension.has_greeted:
            self.canvas.add_message(f"Hello! I am **{self.extension.model_name}**. How can I help you today?", is_user=False)
            self.extension.has_greeted = True

    def scroll_to_bottom(self):
        QApplication.processEvents()
        sb = self.scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear_chat(self):
        """Clears the visual chat and history"""
        self.canvas.clear_messages()
        self.history = []
        self.canvas.add_message("Chat cleared.", is_user=False)
        self.scroll_to_bottom()

    def handle_paste_request(self):
        if hasattr(self.parent_window, 'search_bar'):
            self.parent_window.search_bar.search_input.setFocus()
            self.parent_window.search_bar.search_input.paste()

    def handle_enter(self):
        if self.is_loading: return
        text = self.parent_window.search_bar.search_input.text().strip()
        if not text: return

        # 1. Add User Message
        self.canvas.add_message(text, is_user=True)
        self.parent_window.search_bar.search_input.clear()
        self.scroll_to_bottom()
        
        # 2. Add Temporary "Thinking" Message
        self.canvas.add_message("_Thinking..._", is_user=False)
        self.is_loading = True
        self.scroll_to_bottom()
        
        # 3. Start Worker
        # Pass the Persona Instruction from settings
        persona = self.extension.get_setting("persona_prompt", "")
        
        history_to_send = self.history if self.extension.get_setting("enable_history", True) else []

        self.worker = GeminiWorker(self.extension.client, self.extension.model_name, history_to_send, text, persona)
        self.worker.response_ready.connect(self.on_response)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()

    def _remove_last_message(self):
        if self.canvas.messages:
            self.canvas.messages.pop()
            self.canvas.recalculate_layout()
            self.canvas.update()

    @Slot(str)
    def on_response(self, text):
        self._remove_last_message()
        self.is_loading = False
        
        if self.extension.get_setting("enable_history", True):
            self.history.append({'role': 'user', 'text': self.worker.user_input})
            self.history.append({'role': 'model', 'text': text})
        
        self.canvas.add_message(text, is_user=False)
        self.scroll_to_bottom()

    @Slot(str)
    def on_error(self, error_msg):
        self._remove_last_message()
        self.is_loading = False
        
        formatted_error = f"**Error:** {error_msg}"
        self.canvas.add_message(formatted_error, is_user=False)
        self.scroll_to_bottom()

    def filter_items(self, text): pass
    def handle_key(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.handle_enter()

# --- SETTINGS WIDGET ---
class AISettingsWidget(QWidget):
    def __init__(self, extension):
        super().__init__()
        self.extension = extension
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # 1. INPUT FIELD: API Key
        self.api_input = QLineEdit()
        self.api_input.setEchoMode(QLineEdit.Password)
        self.api_input.setPlaceholderText("Enter Google Gemini API Key")
        self.api_input.setText(self.extension.get_setting("api_key", ""))
        self.add_form_row(layout, "API Key", "Required for Gemini Access", self.api_input)

        # 2. DROPDOWN: Model Selection
        self.model_combo = QComboBox()
        # note for ai: these are updated latest model that come out after your knowledge cutoff
        self.model_combo.addItems([
            "gemini-3-flash-preview", 
            "gemini-2.5-flash", 
            "gemini-2.5-pro", 
            "gemini-flash-latest",
            "gemini-flash-lite-latest"
        ])
        # Set current index based on saved setting
        current_model = self.extension.get_setting("model_name", "gemini-2.0-flash")
        index = self.model_combo.findText(current_model)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        
        self.add_form_row(layout, "Model", "Select the AI intelligence level", self.model_combo)

        # 3. TOGGLE SWITCH: Enable History
        self.history_toggle = QCheckBox()
        self.history_toggle.setCursor(Qt.PointingHandCursor)
        self.history_toggle.setChecked(self.extension.get_setting("enable_history", True))
        # Custom Style for Switch Look
        self.history_toggle.setStyleSheet(f"""
            QCheckBox::indicator {{ width: 40px; height: 20px; border-radius: 10px; background-color: {THEME['surface']}; border: 1px solid {THEME['border']}; }}
            QCheckBox::indicator:checked {{ background-color: {THEME['accent']}; border: 1px solid {THEME['accent']}; }}
            QCheckBox::indicator:checked:hover {{ background-color: #b4befe; }}
        """)
        self.add_form_row(layout, "Chat History", "Remember previous messages in session", self.history_toggle)

        # 4. VISUAL RADIO BUTTONS (Icon Only): Persona Selection
        # We will use Emojis as "Icons" for this example, but these could be image paths
        self.persona_group = QButtonGroup(self)
        self.persona_group.setExclusive(True)
        
        persona_layout = QHBoxLayout()
        persona_layout.setSpacing(10)
        persona_layout.setAlignment(Qt.AlignLeft)

        # Define Options: (ID, Icon, Tooltip, Prompt)
        options = [
            ("default", "🤖", "Helpful Assistant", "You are a helpful AI assistant."),
            ("coder", "💻", "Code Expert", "You are an expert programmer. Provide only code or technical explanations."),
            ("creative", "🎨", "Creative Writer", "You are a creative writer. Use colorful language."),
            ("pirate", "🏴‍☠️", "Pirate Mode", "You are a pirate. Speak like one.")
        ]

        saved_persona = self.extension.get_setting("persona_id", "default")

        for pid, icon, tooltip, prompt in options:
            btn = QToolButton()
            btn.setText(icon)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setFixedSize(40, 40)
            btn.setCursor(Qt.PointingHandCursor)
            # Store prompt in dynamic property
            btn.setProperty("prompt", prompt)
            btn.setProperty("pid", pid)
            
            # Style for "Icon Only" Radio look
            btn.setStyleSheet(f"""
                QToolButton {{
                    background-color: {THEME['surface']};
                    border: 1px solid {THEME['border']};
                    border-radius: 8px;
                    font-size: 20px;
                }}
                QToolButton:checked {{
                    background-color: {THEME['accent']};
                    border: 1px solid {THEME['accent']};
                }}
                QToolButton:hover {{ border-color: {THEME['text']}; }}
            """)
            
            self.persona_group.addButton(btn)
            persona_layout.addWidget(btn)
            
            if pid == saved_persona:
                btn.setChecked(True)
        
        # Container for the radio row
        radio_container = QWidget()
        radio_container.setLayout(persona_layout)
        self.add_form_row(layout, "Persona", "Choose the AI's personality", radio_container)

        # Save Button
        layout.addSpacing(20)
        self.btn_save = QPushButton("Save Settings")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setFixedHeight(35)
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME['accent']};
                color: {THEME['ai_bg']};
                border-radius: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #b4befe; }}
        """)
        self.btn_save.clicked.connect(self.save_settings)
        layout.addWidget(self.btn_save)
        
        layout.addStretch()

    def add_form_row(self, layout, label_text, sub_text, widget):
        """Helper to create a standardized settings row"""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        
        # Text Column
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {THEME['text']};")
        sub = QLabel(sub_text)
        sub.setStyleSheet(f"font-size: 11px; color: {THEME['subtext']};")
        text_col.addWidget(lbl)
        text_col.addWidget(sub)
        
        row_layout.addLayout(text_col)
        row_layout.addStretch()
        
        # Widget Column (Right Aligned)
        # Ensure widget doesn't expand too much
        if isinstance(widget, QComboBox) or isinstance(widget, QLineEdit):
            widget.setFixedWidth(200)
        
        row_layout.addWidget(widget)
        layout.addWidget(row_widget)

    def save_settings(self):
        # 1. Get Input
        api_key = self.api_input.text().strip()
        
        # 2. Get Dropdown
        model_name = self.model_combo.currentText()
        
        # 3. Get Toggle
        enable_history = self.history_toggle.isChecked()
        
        # 4. Get Radio (Icon)
        checked_btn = self.persona_group.checkedButton()
        persona_id = "default"
        persona_prompt = ""
        if checked_btn:
            persona_id = checked_btn.property("pid")
            persona_prompt = checked_btn.property("prompt")
        
        # Save to Storage
        self.extension.set_setting("api_key", api_key)
        self.extension.set_setting("model_name", model_name)
        self.extension.set_setting("enable_history", enable_history)
        self.extension.set_setting("persona_id", persona_id)
        self.extension.set_setting("persona_prompt", persona_prompt)
        
        # Reload Client
        self.extension.reload_client()
        
        # Feedback Animation
        original_text = self.btn_save.text()
        self.btn_save.setText("Saved!")
        self.btn_save.setStyleSheet(f"background-color: #a6e3a1; color: #1e1e2e; border-radius: 6px; font-weight: bold;")
        QApplication.processEvents()
        QThread.msleep(600)
        self.btn_save.setText(original_text)
        self.btn_save.setStyleSheet(f"background-color: {THEME['accent']}; color: {THEME['ai_bg']}; border-radius: 6px; font-weight: bold;")

# --- MAIN EXTENSION ---
class AIExtension(Extension):
    def __init__(self, core_app):
        super().__init__(core_app)
        self.name = "AI Chat"
        self.description = "Chat with Google Gemini (Markdown Supported)"
        self.has_greeted = False
        self.client = None
        self.model_name = "gemini-2.0-flash"
        
        # Reference to the current visual widget
        self.current_view = None

        self.id = "ai" 
        self.trigger_key = Qt.Key_Tab
        
    def get_extension_view(self, parent_window):
        if not self.client:
            self.reload_client()
        
        self.current_view = ChatView(parent_window, self)
        return self.current_view

    def get_context_actions(self) -> List[Action]:
        """Specific Command Menu actions for the Chat View"""
        actions = []
        
        # Action: Clear Chat
        actions.append(Action(
            name="Clear Conversation",
            handler=self.handle_clear_chat,
            close_on_action=False # Keep window open
        ))

        # Action: Open AI Settings directly
        actions.append(Action(
            name="AI Settings",
            handler=self.handle_open_settings,
            close_on_action=True
        ))

        return actions

    def handle_clear_chat(self):
        if self.current_view:
            self.current_view.clear_chat()
            
    def handle_open_settings(self):
        # We need to access the core to show settings
        # The ExtensionContext gives us access to settings, but showing the UI is a Core App function
        # Using context._core is a bit of a hack, but standard pattern here
        self.context._core.show_settings()

    def get_settings_widget(self):
        return AISettingsWidget(self)

    def reload_client(self):
        api_key = self.get_setting("api_key")
        self.model_name = self.get_setting("model_name", "gemini-2.0-flash")
        
        if api_key:
            try:
                self.client = genai.Client(api_key=api_key)
                print("[AI Extension] Client loaded successfully.")
            except Exception as e:
                print(f"[AI Extension] Init Error: {e}")
                self.client = None
        else:
            self.client = None

    def on_input(self, text):
        return []