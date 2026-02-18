# extensions/system_apps/apps.py
import os
import json
import subprocess
import ctypes
import threading
from api.types import ResultItem, Action
from .lnk_parser import resolve_lnk

class AppIndexer:
    def __init__(self):
        self.apps = []
        self.alias_registry = {}
        self.lock = threading.Lock()
        
        # Path for the cache file
        self.cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_index_cache.json")
        
        self.load_aliases()
        
        # 1. Load from cache immediately (Instant startup)
        self.load_cache()
        
        # 2. Refresh from disk in background (Updates index)
        threading.Thread(target=self.refresh_index, daemon=True).start()

    def load_aliases(self):
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            json_path = os.path.join(current_dir, "aliases.json")
            if os.path.exists(json_path):
                with open(json_path, 'r') as f:
                    data = json.load(f)
                for category in data.values():
                    if isinstance(category, dict):
                        for alias, target in category.items():
                            self.alias_registry[alias.lower()] = target.lower()
        except Exception as e:
            print(f"[System Apps] Error loading aliases: {e}")

    def load_cache(self):
        """Loads apps from JSON to ensure 0ms startup delay."""
        if not os.path.exists(self.cache_path):
            return

        try:
            with open(self.cache_path, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                with self.lock:
                    self.apps = cached_data
            print(f"[System Apps] Loaded {len(self.apps)} apps from cache.")
        except Exception as e:
            print(f"[System Apps] Cache load failed: {e}")

    def save_cache(self):
        try:
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(self.apps, f)
        except Exception as e:
            print(f"[System Apps] Cache save failed: {e}")

    def refresh_index(self):
        target_map = {}  # exe_path.lower() -> app_data
        
        # 1. Recursive Directories (Start Menu only)
        start_menu_dirs = [
            os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
        ]

        # 2. Flat Directories (PATH) - Only scan top level, do not recurse
        path_dirs = []
        path_env = os.environ.get("PATH", "")
        for p in path_env.split(os.pathsep):
            # Optimization: Skip Windows system folders to avoid junk (dlls, etc)
            # Users usually search for 'calc', not 'svchost'
            p_lower = p.lower()
            if "windows\\system32" in p_lower or "windows\\winsxs" in p_lower:
                continue
            if p and os.path.isdir(p): # FIX: Ensure it is a directory
                path_dirs.append(p)

        valid_extensions = {".exe", ".lnk"}
        ignore_names = {"uninstall", "readme", "help", "website", "update", "installer", "setup", "eula"}

        # Helper to process a file
        def process_file(root, filename):
            try:
                name, ext = os.path.splitext(filename)
                ext = ext.lower()
                if ext not in valid_extensions:
                    return
                
                lower_name = name.lower()
                if any(bad in lower_name for bad in ignore_names):
                    return
                
                full_path = os.path.normpath(os.path.join(root, filename))
                
                # Check if it exists (sometimes dead shortcuts remain)
                if not os.path.exists(full_path):
                    return

                clean_name = name.replace(" - Shortcut", "")
                
                if ext == ".lnk":
                    resolved = resolve_lnk(full_path)
                    target_path = resolved if resolved else full_path
                else:
                    target_path = full_path
                
                target_key = target_path.lower()
                existing = target_map.get(target_key)
                
                # Prefer shortcuts over raw exes (better naming)
                should_add = (
                    existing is None or
                    (ext == ".lnk" and not existing["is_shortcut"])
                )
                
                if should_add:
                    target_map[target_key] = {
                        "name": clean_name,
                        "path": full_path,      
                        "target": target_path,
                        "lower_name": clean_name.lower(),
                        "is_shortcut": ext == ".lnk"
                    }
            except Exception:
                pass

        # Scan Start Menus (Recursive)
        for directory in start_menu_dirs:
            if not os.path.exists(directory): continue
            for root, _, files in os.walk(directory):
                for filename in files:
                    process_file(root, filename)

        # Scan PATH (Flat - faster)
        for directory in path_dirs:
            try:
                # LISTDIR is much faster than walk for flat scanning
                files = os.listdir(directory)
                for filename in files:
                    process_file(directory, filename)
            except (PermissionError, OSError):
                continue

        with self.lock:
            self.apps = list(target_map.values())
        
        print(f"[System Apps] Index refreshed: {len(self.apps)} apps found.")
        self.save_cache()

    def search(self, query):
        if not query:
            return []
        
        results = []
        query_lower = query.lower()
        
        # Alias scoring (Fast enough to keep on main thread)
        alias_targets = {}
        for alias_key, target_name in self.alias_registry.items():
            ratio = len(query) / len(alias_key)
            if alias_key.startswith(query_lower):
                fuzzy_score = 250 + (ratio * 150)
            elif query_lower in alias_key:
                fuzzy_score = 200 + (ratio * 100)
            else:
                continue
            if target_name not in alias_targets or fuzzy_score > alias_targets[target_name]:
                alias_targets[target_name] = fuzzy_score

        # Use local reference for thread safety
        with self.lock:
            current_apps = self.apps

        for app in current_apps:
            score = 0
            
            # Match by name
            if query_lower in app['lower_name']:
                score = 300
                if app['lower_name'].startswith(query_lower):
                    score += 100
                if app['lower_name'] == query_lower:
                    score += 300
                if app['is_shortcut']:
                    score += 50
            
            # Match by alias
            target_lower = app.get('target', '').lower()
            for target_part, alias_score in alias_targets.items():
                if target_part in app['lower_name'] or target_part in target_lower:
                    if alias_score > score:
                        score = alias_score
            
            if score > 0:
                launch_action = Action("Open Application", lambda p=app['path']: self._launch(p))
                
                results.append(ResultItem(
                    id=app.get('target', app['path']),
                    name=app['name'],
                    description=app.get('target', app['path']),
                    icon_path=app.get('target', app['path']),
                    action=launch_action,
                    context_actions=[
                        launch_action,
                        Action("Run as Administrator", lambda p=app['path']: self._launch_as_admin(p)),
                        Action("Open File Location", lambda p=app['path']: self._show_in_explorer(p))
                    ],
                    score=int(score)
                ))
                
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def _launch(self, path):
        try:
            os.startfile(path)
        except Exception as e:
            print(f"[Error] Launch failed: {e}")

    def _launch_as_admin(self, path):
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", path, None, None, 1)
        except Exception as e:
            print(f"[Error] Launch as admin failed: {e}")

    def _show_in_explorer(self, path):
        try:
            subprocess.run(['explorer', '/select,', os.path.normpath(path)])
        except Exception as e:
            print(f"[Error] Show in explorer failed: {e}")