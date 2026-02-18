# extensions/unit_converter/categories/currency.py
import os
import json
import time
import threading
import urllib.request
from datetime import datetime

from PySide6.QtGui import QGuiApplication
from api.types import ResultItem, Action
from .base import BaseCategory
from .. import utils
from .. import graphing

# Local Forex API
API_URL = "http://localhost:8080"

class CurrencyCategory(BaseCategory):
    def __init__(self):
        super().__init__()
        self.cache_file = None
        self.graph_engine = None
        
        self.last_updated_ts = 0
        self.last_updated_str = "Offline Estimate"
        self.is_updating = False
        self.default_targets = ["USD", "EUR", "GBP", "JPY", "BTC"]
        
        # Initialize graphing engine with local API
        self.graph_engine = graphing.ForexApiEngine(API_URL)

        # 1. Definitions (factors are defaults/fallbacks)
        self.definitions = {
            # --- Majors & ECB ---
            "USD": {"factor": 1.0, "api_key": "usd", "display_name": "US Dollar", "aliases": ["dollar", "$"]},
            "EUR": {"factor": 1.08, "api_key": "eur", "display_name": "Euro", "aliases": ["euro", "€"]},
            "JPY": {"factor": 0.0067, "api_key": "jpy", "display_name": "Japanese Yen", "aliases": ["yen", "¥"]},
            "GBP": {"factor": 1.26, "api_key": "gbp", "display_name": "British Pound", "aliases": ["pound", "£"]},
            "CHF": {"factor": 1.12, "api_key": "chf", "display_name": "Swiss Franc", "aliases": ["franc", "chf"]},
            "AUD": {"factor": 0.65, "api_key": "aud", "display_name": "Australian Dollar", "aliases": ["aud"]},
            "CAD": {"factor": 0.74, "api_key": "cad", "display_name": "Canadian Dollar", "aliases": ["cad"]},
            "NZD": {"factor": 0.61, "api_key": "nzd", "display_name": "NZ Dollar", "aliases": ["nzd"]},
            
            # --- Americas ---
            "BRL": {"factor": 0.20, "api_key": "brl", "display_name": "Brazilian Real", "aliases": ["brl", "real"]},
            "MXN": {"factor": 0.059, "api_key": "mxn", "display_name": "Mexican Peso", "aliases": ["mxn", "peso"]},
            "ARS": {"factor": 0.0011, "api_key": "ars", "display_name": "Argentine Peso", "aliases": ["ars"]},
            "CLP": {"factor": 0.0011, "api_key": "clp", "display_name": "Chilean Peso", "aliases": ["clp"]},
            "COP": {"factor": 0.00025, "api_key": "cop", "display_name": "Colombian Peso", "aliases": ["cop"]},
            "PEN": {"factor": 0.27, "api_key": "pen", "display_name": "Peruvian Sol", "aliases": ["pen"]},
            
            # --- Asia/Pacific ---
            "CNY": {"factor": 0.14, "api_key": "cny", "display_name": "Chinese Yuan", "aliases": ["cny", "yuan"]},
            "HKD": {"factor": 0.13, "api_key": "hkd", "display_name": "HK Dollar", "aliases": ["hkd"]},
            "INR": {"factor": 0.012, "api_key": "inr", "display_name": "Indian Rupee", "aliases": ["inr", "rupee", "₹"]},
            "KRW": {"factor": 0.00075, "api_key": "krw", "display_name": "South Korean Won", "aliases": ["krw", "won"]},
            "SGD": {"factor": 0.74, "api_key": "sgd", "display_name": "Singapore Dollar", "aliases": ["sgd"]},
            "TWD": {"factor": 0.031, "api_key": "twd", "display_name": "Taiwan Dollar", "aliases": ["twd"]},
            "VND": {"factor": 0.00004, "api_key": "vnd", "display_name": "Vietnamese Dong", "aliases": ["vnd"]},
            "THB": {"factor": 0.028, "api_key": "thb", "display_name": "Thai Baht", "aliases": ["thb", "baht"]},
            "MYR": {"factor": 0.21, "api_key": "myr", "display_name": "Malaysian Ringgit", "aliases": ["myr"]},
            "PHP": {"factor": 0.018, "api_key": "php", "display_name": "Philippine Peso", "aliases": ["php"]},
            "IDR": {"factor": 0.000064, "api_key": "idr", "display_name": "Indonesian Rupiah", "aliases": ["idr"]},
            "PKR": {"factor": 0.0036, "api_key": "pkr", "display_name": "Pakistani Rupee", "aliases": ["pkr"]},
            
            # --- Middle East & Africa ---
            "AED": {"factor": 0.27, "api_key": "aed", "display_name": "UAE Dirham", "aliases": ["aed", "dirham"]},
            "SAR": {"factor": 0.27, "api_key": "sar", "display_name": "Saudi Riyal", "aliases": ["sar", "riyal"]},
            "ILS": {"factor": 0.27, "api_key": "ils", "display_name": "Israeli Shekel", "aliases": ["ils", "shekel"]},
            "TRY": {"factor": 0.031, "api_key": "try", "display_name": "Turkish Lira", "aliases": ["try", "lira"]},
            "ZAR": {"factor": 0.053, "api_key": "zar", "display_name": "South African Rand", "aliases": ["zar", "rand"]},
            "EGP": {"factor": 0.021, "api_key": "egp", "display_name": "Egyptian Pound", "aliases": ["egp"]},
            "KWD": {"factor": 3.25, "api_key": "kwd", "display_name": "Kuwaiti Dinar", "aliases": ["kwd"]},
            "QAR": {"factor": 0.27, "api_key": "qar", "display_name": "Qatari Rial", "aliases": ["qar"]},
            "NGN": {"factor": 0.00065, "api_key": "ngn", "display_name": "Nigerian Naira", "aliases": ["ngn"]},
            "KES": {"factor": 0.0075, "api_key": "kes", "display_name": "Kenyan Shilling", "aliases": ["kes"]},
            
            # --- Europe (Non-Euro) ---
            "PLN": {"factor": 0.25, "api_key": "pln", "display_name": "Polish Zloty", "aliases": ["pln"]},
            "SEK": {"factor": 0.096, "api_key": "sek", "display_name": "Swedish Krona", "aliases": ["sek"]},
            "NOK": {"factor": 0.095, "api_key": "nok", "display_name": "Norwegian Krone", "aliases": ["nok"]},
            "DKK": {"factor": 0.14, "api_key": "dkk", "display_name": "Danish Krone", "aliases": ["dkk"]},
            "CZK": {"factor": 0.043, "api_key": "czk", "display_name": "Czech Koruna", "aliases": ["czk"]},
            "HUF": {"factor": 0.0028, "api_key": "huf", "display_name": "Hungarian Forint", "aliases": ["huf"]},
            "RON": {"factor": 0.22, "api_key": "ron", "display_name": "Romanian Leu", "aliases": ["ron"]},
            
            # --- Crypto & Commodities ---
            "BTC": {"factor": 65000.0, "api_key": "btc", "display_name": "Bitcoin", "aliases": ["bitcoin", "btc"]},
            "ETH": {"factor": 3500.0, "api_key": "eth", "display_name": "Ethereum", "aliases": ["ethereum", "eth"]},
            "SOL": {"factor": 150.0, "api_key": "sol", "display_name": "Solana", "aliases": ["sol"]},
            "XAU": {"factor": 2350.0, "api_key": "xau", "display_name": "Gold (oz)", "aliases": ["gold"]},
            "XAG": {"factor": 28.0, "api_key": "xag", "display_name": "Silver (oz)", "aliases": ["silver"]},
        }

        # Inject keys and build lookup
        for code, data in self.definitions.items():
            data['symbol'] = code
            
        self._build_lookup()

    def set_data_path(self, folder_path):
        """Called by main extension to set storage path."""
        # We only keep a small cache file for offline redundancy
        self.cache_file = os.path.join(folder_path, "currency_rates_local.json")
        self._load_cache()

    def _check_background_update(self):
        """Checks if data is stale (> 1h) and triggers update if needed."""
        if self.is_updating:
            return

        now = time.time()
        # 3600 seconds = 1 hour (More frequent updates since local API is fast)
        if (now - self.last_updated_ts) > 3600:
            self.is_updating = True
            threading.Thread(target=self._download_rates_thread, daemon=True).start()

    def get_specific_result(self, val, src_unit_str, target_unit_str):
        self._check_background_update()

        src_data = self.get_details(src_unit_str)
        tgt_data = self.get_details(target_unit_str)

        if not src_data or not tgt_data: return []

        res = self.convert(val, src_unit_str, target_unit_str)
        if res is None: return []

        disp_val = utils.format_currency(res)
        input_val_str = utils.format_currency(val)

        title = f"{input_val_str} {src_data['display_name']} = {disp_val} {tgt_data['display_name']}"

        # --- ITEM 1: Conversion Card ---
        def factory_card():
            return utils.ConverterWidget(
                input_data=(input_val_str, src_data['symbol'], src_data['display_name']),
                output_data_list=[(disp_val, tgt_data['symbol'], tgt_data['display_name'])]
            )

        results = [ResultItem(
            id="unit_specific",
            name=title,
            description=f"Rate Source: {self.last_updated_str}",
            score=1000,
            widget_factory=factory_card,
            height=100,
            action=Action("Copy Result", lambda: QGuiApplication.clipboard().setText(str(round(res, 10)).rstrip('0').rstrip('.')))
        )]

        # --- ITEM 2: Graph ---
        # With local API, we assume history is available
        src_sym = src_data['symbol']
        tgt_sym = tgt_data['symbol']
        
        def factory_graph():
            return graphing.InteractiveGraphWidget(self.graph_engine, src_sym, tgt_sym)
        
        results.append(ResultItem(
            id=f"unit_graph_{src_sym}_{tgt_sym}",
            name=f"History: {src_sym} to {tgt_sym}",
            description="Move mouse to see details",
            score=999,
            widget_factory=factory_graph,
            height=200,
            action=Action("Toggle View", lambda: None)
        ))

        return results

    def get_auto_results(self, val, src_unit_str):
        self._check_background_update()
        return super().get_auto_results(val, src_unit_str)

    def _load_cache(self):
        if not self.cache_file or not os.path.exists(self.cache_file):
            return

        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
            
            timestamp = data.get("timestamp", 0)
            rates = data.get("rates", {})
            date_str = data.get("date_str", "Unknown")

            if rates:
                self._apply_rates(rates, timestamp, date_str)
                print(f"[Currency] Cache loaded. Date: {date_str}")
        except Exception as e:
            print(f"[Currency] Cache load error: {e}")

    def _apply_rates(self, rates_dict, timestamp, date_str):
        """
        rates_dict format: { "eur": 0.92, "gbp": 0.79 } (Relative to USD)
        """
        for symbol, def_data in self.definitions.items():
            # Our keys are "eur", "gbp"
            key = symbol.lower()
            
            if key == "usd":
                def_data["factor"] = 1.0
                continue

            if key in rates_dict:
                rate = rates_dict[key]
                if rate > 0:
                    # Logic: 
                    # API says: 1 USD = 0.92 EUR (rate)
                    # Factor represents value in USD.
                    # 1 EUR = 1 / 0.92 USD = 1.08 USD
                    def_data["factor"] = 1.0 / rate
        
        self.last_updated_ts = timestamp
        self.last_updated_str = f"ForexAPI ({date_str})"
        self._build_lookup()

    def _download_rates_thread(self):
        """Fetches batch rates from localhost:8080."""
        print("[Currency] Connecting to ForexAPI...")
        
        targets = []
        for sym in self.definitions.keys():
            if sym.lower() != "usd":
                targets.append(sym.lower())
        
        target_str = ",".join(targets)
        url = f"{API_URL}/convert/usd/batch/1/{target_str}"
        
        data = None
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as response:
                data = json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"[Currency] API Error: {e}")
            self.is_updating = False
            return

        # Parse response: { "conversions": { "eur": {"rate": 0.84}, ... } }
        if data and "conversions" in data:
            conversions = data["conversions"]
            
            # Simplify structure for cache: { "eur": 0.84 }
            simple_rates = {}
            for code, info in conversions.items():
                simple_rates[code] = info["rate"]
            
            date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
            timestamp = time.time()

            # Save to cache
            cache_data = {
                "timestamp": timestamp,
                "date_str": date_str,
                "rates": simple_rates
            }
            try:
                os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
                with open(self.cache_file, 'w') as f:
                    json.dump(cache_data, f)
            except Exception as e:
                print(f"[Currency] Failed to save cache: {e}")

            # Apply
            self._apply_rates(simple_rates, timestamp, date_str)
            print(f"[Currency] Updated rates via ForexAPI.")

        self.is_updating = False