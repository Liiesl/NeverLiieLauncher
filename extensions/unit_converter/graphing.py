# extensions/unit_converter/graphing.py
import time
import json
import urllib.request
import bisect
from datetime import datetime, timedelta
from array import array

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QButtonGroup, QSizePolicy)
from PySide6.QtCore import Qt, QPointF, QMargins
from PySide6.QtGui import (QPainter, QPainterPath, QLinearGradient, QColor, 
                           QPen, QFont, QFontMetrics)

# --- 1. Query Logic (Forex API Client) ---
class ForexApiEngine:
    def __init__(self, api_url="http://localhost:8080"):
        self.base_url = api_url

    def get_cross_rate_history(self, src_ticker, tgt_ticker, period="1y"):
        """
        Fetches historical data from Forex API and downsamples if necessary.
        """
        end_date = datetime.now()
        start_date = end_date

        # Calculate date range
        if period == "7d":
            start_date = end_date - timedelta(days=7)
        elif period == "1mo":
            start_date = end_date - timedelta(days=30)
        elif period == "6mo":
            start_date = end_date - timedelta(days=180)
        elif period == "ytd":
            start_date = datetime(end_date.year, 1, 1)
        elif period == "1y":
            start_date = end_date - timedelta(days=365)
        elif period == "5y":
            start_date = end_date - timedelta(days=365*5)
        else:
            start_date = end_date - timedelta(days=30)

        fmt = "%Y-%m-%d"
        s_str = start_date.strftime(fmt)
        e_str = end_date.strftime(fmt)

        # URL: /convert/usd/eur/1/range/2024-01-01/2024-02-01
        url = f"{self.base_url}/convert/{src_ticker.lower()}/{tgt_ticker.lower()}/1/range/{s_str}/{e_str}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            conversions = data.get("conversions", [])
            
            ts_array = array('d')
            val_array = array('d')

            for item in conversions:
                date_str = item.get("date")
                rate = item.get("rate")
                
                dt = datetime.strptime(date_str, fmt)
                ts = dt.timestamp()
                
                ts_array.append(ts)
                val_array.append(rate)

            # --- RESTORED: Downsampling Logic (Max Plot) ---
            # If we have too many points (e.g. 5 years = 1800 days),
            # the graph looks jagged and renders slower. We limit to ~200 points.
            limit = 200
            count = len(ts_array)
            if count > limit:
                step = count // limit
                # Slice the arrays to reduce point count
                return ts_array[::step], val_array[::step]
            
            return ts_array, val_array

        except Exception as e:
            print(f"[Graphing] API Error: {e}")
            return [], []

# --- 2. Chart Widget (Unchanged) ---
class GoogleChartWidget(QWidget):
    def __init__(self, timestamps, prices):
        super().__init__()
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.chart_color = QColor("#8ab4f8")
        self.grid_color = QColor("#3c4043")
        self.text_color = QColor("#9aa0a6")
        self.bg_color = QColor("#202124") 
        self.margins = QMargins(0, 10, 50, 20) 
        self.hover_pos = None
        
        self.update_data(timestamps, prices)

    def update_data(self, timestamps, prices):
        self.timestamps = timestamps
        self.prices = prices
        self.hover_pos = None

        if self.prices:
            self.min_price = min(self.prices)
            self.max_price = max(self.prices)
            self.min_ts = min(self.timestamps)
            self.max_ts = max(self.timestamps)
            
            rng = self.max_price - self.min_price
            if rng == 0: rng = self.min_price * 0.1
            self.min_price -= rng * 0.05
            self.max_price += rng * 0.05
        else:
            self.min_price = self.max_price = 0
            self.min_ts = self.max_ts = 0
        
        self.update()

    def map_to_pixel(self, ts, price, w, h):
        uw = w - self.margins.left() - self.margins.right()
        uh = h - self.margins.top() - self.margins.bottom()
        
        if self.max_ts == self.min_ts: x = self.margins.left()
        else: x = self.margins.left() + ((ts - self.min_ts) / (self.max_ts - self.min_ts)) * uw
        
        if self.max_price == self.min_price: y = self.margins.top() + uh / 2
        else: y = self.margins.top() + uh - ((price - self.min_price) / (self.max_price - self.min_price)) * uh
        
        return x, y

    def map_from_pixel_x(self, x, w):
        uw = w - self.margins.left() - self.margins.right()
        if uw <= 0: return 0
        rel_x = x - self.margins.left()
        ratio = max(0.0, min(1.0, rel_x / uw))
        return self.min_ts + ratio * (self.max_ts - self.min_ts)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        if not self.prices or len(self.prices) < 2:
            painter.setPen(self.text_color)
            painter.drawText(self.rect(), Qt.AlignCenter, "No Data (Check API)")
            return

        # Draw Grid
        painter.setFont(QFont("Arial", 8))
        steps = 4
        range_price = self.max_price - self.min_price
        step_val = range_price / (steps - 1)
        pen_grid = QPen(self.grid_color, 1, Qt.SolidLine)
        
        uw = w - self.margins.left() - self.margins.right()
        uh = h - self.margins.top() - self.margins.bottom()

        for i in range(steps):
            price = self.min_price + (i * step_val)
            y_pos = self.margins.top() + uh - ((price - self.min_price) / range_price) * uh
            
            painter.setPen(pen_grid)
            painter.drawLine(self.margins.left(), int(y_pos), w - self.margins.right(), int(y_pos))
            
            painter.setPen(self.text_color)
            label = f"{price:.3f}"
            if price > 100: label = f"{price:.1f}"
            painter.drawText(w - self.margins.right() + 5, int(y_pos) + 4, label)

        # Draw Graph
        path = QPainterPath()
        first_pt = self.map_to_pixel(self.timestamps[0], self.prices[0], w, h)
        path.moveTo(QPointF(*first_pt))
        
        for ts, p in zip(self.timestamps[1:], self.prices[1:]):
            pt = self.map_to_pixel(ts, p, w, h)
            path.lineTo(QPointF(*pt))

        # Gradient
        fill_path = QPainterPath(path)
        last_pt = self.map_to_pixel(self.timestamps[-1], self.prices[-1], w, h)
        fill_path.lineTo(last_pt[0], h - self.margins.bottom())
        fill_path.lineTo(self.margins.left(), h - self.margins.bottom())
        fill_path.closeSubpath()

        gradient = QLinearGradient(0, self.margins.top(), 0, h - self.margins.bottom())
        c_top = QColor(self.chart_color)
        c_top.setAlpha(60) 
        c_btm = QColor(self.chart_color)
        c_btm.setAlpha(5)
        gradient.setColorAt(0, c_top)
        gradient.setColorAt(1, c_btm)
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(fill_path)

        # Line
        pen_line = QPen(self.chart_color, 2)
        painter.setPen(pen_line)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        
        # Tooltip
        if self.hover_pos:
            mx = self.hover_pos.x()
            if self.margins.left() <= mx <= w - self.margins.right():
                ts_cursor = self.map_from_pixel_x(mx, w)
                idx = bisect.bisect_left(self.timestamps, ts_cursor)
                if idx >= len(self.timestamps): idx = len(self.timestamps) - 1
                
                real_ts = self.timestamps[idx]
                real_price = self.prices[idx]
                
                px, py = self.map_to_pixel(real_ts, real_price, w, h)
                
                painter.setPen(QPen(Qt.gray, 1, Qt.DashLine))
                painter.drawLine(int(px), self.margins.top(), int(px), h - self.margins.bottom())
                
                painter.setPen(QPen(self.chart_color, 2))
                painter.setBrush(self.bg_color)
                painter.drawEllipse(QPointF(px, py), 4, 4)
                
                date_str = datetime.fromtimestamp(real_ts).strftime("%d %b")
                price_str = f"{real_price:.4f}"
                
                tooltip_text = f"{price_str} {date_str}"
                fm = QFontMetrics(painter.font())
                tw = fm.horizontalAdvance(tooltip_text) + 20
                
                tx = px - tw/2
                if tx < 5: tx = 5
                if tx + tw > w - 5: tx = w - tw - 5
                ty = py - 25
                if ty < 0: ty = py + 15
                
                painter.setBrush(QColor("#3c4043"))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(int(tx), int(ty), int(tw), 20, 4, 4)
                
                painter.setPen(Qt.white)
                painter.drawText(int(tx), int(ty), int(tw), 20, Qt.AlignCenter, tooltip_text)

    def mouseMoveEvent(self, event):
        self.hover_pos = event.pos()
        self.update()
        
    def leaveEvent(self, event):
        self.hover_pos = None
        self.update()

# --- 3. Interactive Container ---
class InteractiveGraphWidget(QWidget):
    def __init__(self, engine, src, tgt):
        super().__init__()
        self.engine = engine
        self.src = src
        self.tgt = tgt
        
        # Layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(15, 10, 15, 10)
        self.layout.setSpacing(5)
        
        # Style
        self.setStyleSheet("""
            QWidget { background-color: #202124; border-radius: 8px; }
            QPushButton {
                background-color: transparent;
                color: #9aa0a6;
                border: 1px solid #5f6368;
                border-radius: 12px;
                padding: 2px 0px;
                font-size: 11px;
                font-weight: bold;
                min-width: 40px;
            }
            QPushButton:hover {
                background-color: #303134;
                color: #e8eaed;
            }
            QPushButton:checked {
                background-color: #303134;
                border: 1px solid #8ab4f8;
                color: #8ab4f8;
            }
        """)
        
        # Header (Buttons)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        btn_layout.addStretch()
        
        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)
        
        periods = ["7d", "1mo", "6mo", "ytd", "1y", "5y"]
        
        for p in periods:
            btn = QPushButton(p.upper())
            btn.setCheckable(True)
            if p == "1mo": btn.setChecked(True)
            
            # Connect
            btn.clicked.connect(lambda checked, x=p: self.change_period(x))
            
            self.btn_group.addButton(btn)
            btn_layout.addWidget(btn)
            
        self.layout.addLayout(btn_layout)
        
        # Initial Data
        ts, prices = self.engine.get_cross_rate_history(src, tgt, "1mo")
        
        # Chart
        self.chart = GoogleChartWidget(ts, prices)
        self.layout.addWidget(self.chart)
        
    def change_period(self, period):
        # Fetch new data
        if self.engine:
            ts, prices = self.engine.get_cross_rate_history(self.src, self.tgt, period)
            self.chart.update_data(ts, prices)