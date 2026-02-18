# extensions/calculator/__init__.py
import math
import re
import os
import json
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QVBoxLayout, QFrame
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication

from api.extension import Extension
from api.types import ResultItem, Action

# --- MATH LOGIC ---
class MathEngine:
    def __init__(self, data_path):
        self.data_path = data_path
        self.file_path = os.path.join(self.data_path, "variables.json")
        
        # Safe math functions
        self.allowed_names = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
        self.allowed_names.update({
            "abs": abs, "round": round, "min": min, "max": max, "sum": sum, "pow": pow
        })
        
        self.variables = {}
        self.load_variables()

    def load_variables(self):
        """Load variables from disk"""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r') as f:
                    self.variables = json.load(f)
            except Exception:
                self.variables = {}

    def save_variables(self):
        """Save variables to disk"""
        if not os.path.exists(self.data_path):
            os.makedirs(self.data_path)
        with open(self.file_path, 'w') as f:
            json.dump(self.variables, f)

    def clear_variables(self):
        self.variables = {}
        if os.path.exists(self.file_path):
            os.remove(self.file_path)

    def _split_statements(self, text):
        """Split by comma, but ignore commas inside parentheses (e.g. max(1,2))"""
        parts = []
        current = []
        balance = 0
        for char in text:
            if char == '(': balance += 1
            elif char == ')': balance -= 1
            elif char == ',' and balance == 0:
                parts.append("".join(current))
                current = []
                continue
            current.append(char)
        parts.append("".join(current))
        return parts

    def _add_implicit_multiplication(self, expr):
        # 1. Digit followed by Letter or Open Paren (lookahead prevents breaking scientific notation 2e10)
        expr = re.sub(r'(\d)(\s*)(?!(e|E)\d)([a-zA-Z(])', r'\1*\4', expr)
        # 2. Close Paren followed by Letter, Digit, or Open Paren
        expr = re.sub(r'(\))(\s*)([a-zA-Z0-9(])', r'\1*\3', expr)
        return expr

    def evaluate_block(self, full_text):
        """Evaluates a chain of statements: x=10, y=20, x+y"""
        statements = self._split_statements(full_text)
        last_result = None
        has_assignment = False

        # Work on a temporary copy so we don't corrupt state if the line is half-typed/invalid
        # However, for live preview of 'x=10, x*2', we need to update effectively.
        # We will update self.variables immediately, but save to disk only on success.
        
        temp_vars = self.variables.copy()

        try:
            for stmt in statements:
                stmt = stmt.strip()
                if not stmt: continue

                # Check assignment
                if "=" in stmt and "==" not in stmt:
                    parts = stmt.split("=")
                    if len(parts) == 2:
                        var_name = parts[0].strip()
                        rhs = parts[1].strip()
                        
                        if var_name.isidentifier() and var_name not in self.allowed_names:
                            val = self._calculate(rhs, temp_vars)
                            if val is not None and isinstance(val, (int, float)):
                                temp_vars[var_name] = val
                                last_result = val
                                has_assignment = True
                                continue
                
                # Standard calc
                val = self._calculate(stmt, temp_vars)
                if val is not None:
                    last_result = val
            
            # If successful, update real variables and save
            if has_assignment:
                self.variables = temp_vars
                self.save_variables()

            return last_result, has_assignment
        except Exception:
            return None, False

    def _calculate(self, expression, context_vars):
        expr = expression.replace("^", "**").replace("×", "*")
        expr = self._add_implicit_multiplication(expr)
        
        try:
            # Merge safe math functions with current variables
            full_context = {**self.allowed_names, **context_vars}
            return eval(expr, {"__builtins__": None}, full_context)
        except Exception:
            return None

# --- CUSTOM WIDGET ---
class CalculatorWidget(QWidget):
    def __init__(self, expression, result_str, mode="standard"):
        super().__init__()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(15)

        self.container = QFrame()
        self.container.setStyleSheet("background-color: transparent;")
        
        inner_layout = QVBoxLayout(self.container)
        inner_layout.setContentsMargins(0, 5, 0, 5)
        inner_layout.setSpacing(2)
        
        # Styles based on mode
        if mode == "assignment":
            top_text = expression
            main_text = result_str
            top_color = "#a6adc8"
            main_color = "#a6e3a1" # Green
        elif mode == "clear":
             top_text = "Command"
             main_text = "Clear Variables"
             top_color = "#a6adc8"
             main_color = "#fab387" # Orange
        else:
            top_text = f"{expression} ="
            main_text = result_str
            top_color = "#a6adc8"
            main_color = "#ffffff"

        lbl_expr = QLabel(top_text)
        lbl_expr.setStyleSheet(f"color: {top_color}; font-weight: 500;")
        lbl_expr.setFont(QFont("Segoe UI", 12))
        lbl_expr.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        lbl_res = QLabel(main_text)
        lbl_res.setStyleSheet(f"color: {main_color}; font-weight: bold;")
        lbl_res.setFont(QFont("Segoe UI", 26))
        lbl_res.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        inner_layout.addWidget(lbl_expr)
        inner_layout.addWidget(lbl_res)
        
        layout.addStretch() 
        layout.addWidget(self.container)

class CalculatorExtension(Extension):
    def __init__(self, core_app):
        super().__init__(core_app)
        # Pass data path to engine for storage
        self.engine = MathEngine(self.context.data_path)

    def on_input(self, text):
        text = text.strip()
        if not text:
            return []
        
        # 1. Handle "Clear" Command
        if text.lower() == "clear":
             def perform_clear():
                 self.engine.clear_variables()
                 # Optional: Trigger a UI refresh if your launcher supports it, 
                 # otherwise the next query will show empty results.
            
             def make_clear_widget():
                 return CalculatorWidget("clear", "Reset Data", mode="clear")
             
             return [ResultItem(
                id="calc_clear",
                name="Clear Variables",
                description="Delete all saved variables from storage",
                score=100,
                action=Action("Clear", perform_clear, close_on_action=False),
                widget_factory=make_clear_widget
             )]

        # 2. Heuristic Checks
        math_chars = set("0123456789+-*/%^.()=, ") # added comma
        has_operator = any(c in "+-*/%^=" for c in text)
        is_function = any(func in text for func in ["sqrt", "sin", "cos", "tan", "log", "pi", "e"])
        is_variable_lookup = text in self.engine.variables
        
        # Ignore simple numbers unless they are part of a list (1,2)
        if text.isdigit() and len(text) < 4 and "," not in text: 
            return []
            
        if not (has_operator or is_function or is_variable_lookup or text[0].isdigit()):
            return []

        # 3. Calculate
        val, is_assignment = self.engine.evaluate_block(text)
        
        if val is not None:
            # Format Result
            if isinstance(val, (int, float)):
                if abs(val) > 1e10 or (abs(val) < 1e-6 and val != 0):
                    res_str = f"{val:.6e}" 
                else:
                    res_str = f"{val:,.6f}".rstrip('0').rstrip('.')
            else:
                res_str = str(val)

            # Actions
            def copy_result():
                QGuiApplication.clipboard().setText(res_str)

            # Factory
            mode = "assignment" if is_assignment else "standard"
            def make_widget():
                return CalculatorWidget(text, res_str, mode=mode)
            
            # Text setup
            if is_assignment:
                name_text = f"Saved: {res_str}"
                desc_text = "Variable assigned. Press Enter to keep typing."
            else:
                name_text = res_str
                desc_text = f"Result of {text}"

            return [ResultItem(
                id="calc_result",
                name=name_text,
                description=desc_text,
                action=Action("Copy/Set", copy_result, close_on_action=not is_assignment),
                score=1000, 
                widget_factory=make_widget,
                height=80
        )]
        
        return []

Extension = CalculatorExtension