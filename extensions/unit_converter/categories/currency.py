import os
import json
import time
import threading
import ssl
import urllib.request
from datetime import datetime

from PySide6.QtGui import QGuiApplication
from api.types import ResultItem, Action
from .base import BaseCategory
from .. import utils

# PRIMARY URL: jsDelivr CDN (Fast, No Rate Limits)
PRIMARY_API_URL = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"
# FALLBACK URL: Cloudflare Pages (Use if CDN fails)
FALLBACK_API_URL = "https://latest.currency-api.pages.dev/v1/currencies/usd.json"

class CurrencyCategory(BaseCategory):
    def __init__(self):
        super().__init__()
        self.cache_file = None
        self.last_updated_ts = 0
        self.last_updated_str = "Offline Estimate"
        self.is_updating = False
        self.default_targets = ["USD", "EUR", "GBP", "JPY", "BTC"]
        
        # 1. Definitions with API Keys
        # Factor = Value in USD (e.g. 1 EUR = 1.08 USD)
        # API returns Rate (1 USD = X Unit). So Factor = 1 / Rate.
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

        self._build_lookup()

    def set_data_path(self, folder_path):
        """Called by main extension to set storage path."""
        self.cache_file = os.path.join(folder_path, "currency_rates_cdn.json")
        
        # Load existing cache immediately
        self._load_cache()

    def _check_background_update(self):
        """Checks if data is stale (> 24h) and triggers update if needed."""
        if self.is_updating:
            return

        now = time.time()
        # 86400 seconds = 24 hours
        if (now - self.last_updated_ts) > 86400:
            self.is_updating = True
            threading.Thread(target=self._download_rates_thread, daemon=True).start()

    def get_specific_result(self, val, src_unit_str, target_unit_str):
        # Trigger update check
        self._check_background_update()

        src_data = self.get_details(src_unit_str)
        tgt_data = self.get_details(target_unit_str)

        if not src_data or not tgt_data: return []

        res = self.convert(val, src_unit_str, target_unit_str)
        if res is None: return []

        disp_val = utils.format_currency(res)
        input_val_str = utils.format_currency(val)

        title = f"{input_val_str} {src_data['display_name']} = {disp_val} {tgt_data['display_name']}"

        def factory():
            return utils.ConverterWidget(
                input_data=(
                    input_val_str,
                    src_data['symbol'],
                    src_data['display_name']),
                output_data_list=[(
                    disp_val,
                    tgt_data['symbol'],
                    tgt_data['display_name'])]
            )

        return [ResultItem(
            id="unit_specific",
            name=title,
            description=f"Rate Source: {self.last_updated_str}",
            score=1000,
            widget_factory=factory,
            height=100,
            action=Action("Copy Result", lambda: QGuiApplication.clipboard().setText(str(round(res, 10)).rstrip('0').rstrip('.')))
        )]

    def get_auto_results(self, val, src_unit_str):
        # Trigger update check
        self._check_background_update()

        src_data = self.get_details(src_unit_str)
        if not src_data: return []

        src_factor = src_data['factor']
        src_symbol = src_data['symbol']
        src_name = src_data['display_name']

        results_data = []

        for t_symbol in self.default_targets:
            if t_symbol not in self.definitions: continue

            t_data = self.definitions[t_symbol]
            t_factor = t_data['factor']

            if abs(src_factor - t_factor) < 1e-9: continue

            res = (val * src_factor) / t_factor

            results_data.append((
                utils.format_currency(res),
                t_symbol,
                t_data['display_name']
            ))

            if len(results_data) >= 3: break

        if not results_data: return []

        def factory():
            return utils.ConverterWidget(
                input_data=(utils.format_currency(val), src_symbol, src_name),
                output_data_list=results_data
            )

        copy_str = " | ".join([f"{utils.format_currency((val * src_factor) / self.definitions[r[1]]['factor'])} {r[1]}" for r in results_data])

        return [ResultItem(
            id=f"unit_auto_{src_symbol}",
            name=f"Convert {src_name}",
            description=f"Currency conversion for {utils.format_currency(val)} {src_symbol}",
            score=100,
            widget_factory=factory,
            height=100,
            action=Action("Copy All", lambda: QGuiApplication.clipboard().setText(copy_str))
        )]

    def _load_cache(self):
        """Loads cached rates from JSON file if available."""
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
        """Updates internal definitions with new rates."""
        count = 0
        for symbol, def_data in self.definitions.items():
            api_key = def_data.get("api_key")
            
            # The API returns rates relative to USD (1 USD = X Currency)
            # Our logic uses factor relative to USD (1 Currency = X USD)
            # So, Factor = 1.0 / Rate
            
            if api_key in rates_dict:
                rate = rates_dict[api_key]
                if rate > 0:
                    def_data["factor"] = 1.0 / rate
                    count += 1
        
        self.last_updated_ts = timestamp
        # Convert timestamp to readable time if not provided
        if date_str == "Unknown" and timestamp > 0:
            date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        
        self.last_updated_str = f"API ({date_str})"
        self._build_lookup()

    def _download_rates_thread(self):
        """Worker thread to fetch rates from CDN."""
        print("[Currency] Starting background update...")
        
        # SSL Context to avoid certificate errors on some Windows machines
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        data = None
        urls_to_try = [PRIMARY_API_URL, FALLBACK_API_URL]

        for url in urls_to_try:
            try:
                req = urllib.request.Request(
                    url, 
                    headers={'User-Agent': 'NeverLiie-UnitConverter'}
                )
                with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
                    raw_json = json.loads(response.read().decode('utf-8'))
                    
                # Validate response structure
                if "usd" in raw_json:
                    data = raw_json
                    break
            except Exception as e:
                print(f"[Currency] Failed to fetch from {url}: {e}")

        if data:
            rates = data.get("usd", {})
            date_str = data.get("date", "Unknown")
            timestamp = time.time()

            # Save to disk
            cache_data = {
                "timestamp": timestamp,
                "date_str": date_str,
                "rates": rates
            }
            try:
                os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
                with open(self.cache_file, 'w') as f:
                    json.dump(cache_data, f)
            except Exception as e:
                print(f"[Currency] Failed to save cache: {e}")

            # Apply to memory
            self._apply_rates(rates, timestamp, date_str)
            print(f"[Currency] Updated {len(rates)} rates successfully.")
        else:
            print("[Currency] Update failed. Keeping existing rates.")

        self.is_updating = False