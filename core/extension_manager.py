# core/extension_manager.py
import os
import importlib.util
import sys
import traceback
import concurrent.futures
import time
import threading
from api.extension import Extension
from api.context import ExtensionContext
from .crash_logger import log_exception

class ExtensionManager:
    def __init__(self, core_app):
        self.extensions = []
        self.core = core_app
        self.settings = core_app.settings
        
        # Determine Base AppData Path
        if sys.platform == "win32":
            base_path = os.getenv("APPDATA")
        else:
            base_path = os.path.expanduser("~/.local/share")
            
        self.app_data_root = os.path.join(base_path, "NeverLiie", "extensions")
        
        # Thread pool
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10, thread_name_prefix="ExtWorker")
        
        # Async state management
        self._query_id = 0
        self._search_lock = threading.Lock()
        self._active_futures = []
        
        # Store path for reloading
        self.extensions_dir = None

    def load_extensions(self, extensions_dir):
        self.extensions_dir = extensions_dir
        if not os.path.exists(extensions_dir):
            os.makedirs(extensions_dir)
            
        for folder in os.listdir(extensions_dir):
            path = os.path.join(extensions_dir, folder)
            if os.path.isdir(path):
                init_file = os.path.join(path, "__init__.py")
                if os.path.exists(init_file):
                    self._load_module(folder, init_file)

    def _load_module(self, folder_name, path):
        try:
            # Create module name key
            module_name = f"ext_{folder_name}"
            
            spec = importlib.util.spec_from_file_location(module_name, path)
            if not spec:
                raise ImportError(f"Could not create spec for {path}")
                
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            return self._instantiate_extension(module, folder_name)
                        
        except Exception as e:
            print(f"[Error] Failed to load {folder_name}: {e}\n{traceback.format_exc()}")
            # Clean up partial load
            module_name = f"ext_{folder_name}"
            if module_name in sys.modules:
                del sys.modules[module_name]
            return False

    def _instantiate_extension(self, module, folder_name):
        """Helper to find and instantiate the Extension subclass in a module."""
        found = False
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            
            if isinstance(attr, type) and issubclass(attr, Extension) and attr is not Extension:
                print(f"[Core] Loading Extension: {folder_name}")
                found = True
                
                context = ExtensionContext(self.core, ext_id=folder_name)
                
                # Define centralized storage path
                ext_data_path = os.path.join(self.app_data_root, folder_name)
                if not os.path.exists(ext_data_path):
                    os.makedirs(ext_data_path)
                    
                context.data_path = ext_data_path

                try:
                    # Check for existing instance to clean up
                    old_instance = next((e for e in self.extensions if e.id == folder_name), None)
                    if old_instance and hasattr(old_instance, 'cleanup'):
                        try:
                            old_instance.cleanup()
                        except Exception as ex:
                            print(f"[Error] Cleanup failed for {folder_name}: {ex}")

                    instance = attr(context)
                    # Remove existing instance from list
                    with self._search_lock:
                        self.extensions = [e for e in self.extensions if e.id != instance.id]
                        self.extensions.append(instance)
                    return True
                except Exception as e:
                    print(f"[Error] Failed to instantiate {folder_name}: {e}")
                    return False
        
        if not found:
            print(f"[Error] No Extension subclass found in {folder_name}")
        return False

    def reload_extension(self, ext_id):
        """Reloads the python module and re-instantiates the extension class."""
        if not self.extensions_dir:
            print("[Error] Extensions directory not set.")
            return False

        path = os.path.join(self.extensions_dir, ext_id, "__init__.py")
        if not os.path.exists(path):
            print(f"[Error] Extension path not found: {path}")
            return False

        print(f"[Core] Reloading extension module: {ext_id}...")
        
        # 1. Aggressively unload module and submodules from cache
        # This ensures imports inside __init__.py (like `from . import config`) are re-executed
        prefix = f"ext_{ext_id}"
        to_delete = [k for k in sys.modules.keys() if k == prefix or k.startswith(prefix + ".")]
        
        for k in to_delete:
            del sys.modules[k]

        # 2. Force re-load
        if self._load_module(ext_id, path):
            print(f"[Core] Successfully reloaded {ext_id}")
            return True
        else:
            return False

    def _safe_query(self, ext, text):
        start_time = time.perf_counter()
        results = []
        try:
            results = ext.on_input(text) or []
        except Exception:
            import sys
            log_exception(f"extension_query:{ext.id}", sys.exc_info())
            print(f"[Error] Extension '{ext.id}' crashed - see crash log")
            results = []
        finally:
            end_time = time.perf_counter()
            elapsed_ms = (end_time - start_time) * 1000
            if elapsed_ms > 200:
                print(f"[{ext.id}] Slow: {elapsed_ms:.2f} ms")

        return results

    def cancel_previous_queries(self):
        with self._search_lock:
            self._query_id += 1
            
    def search_async(self, text, callback_fn):
        # 1. Invalidate previous searches
        self.cancel_previous_queries()
        
        current_qid = self._query_id
        
        # 2. Prepare result bucket
        current_results = []
        
        # 3. Define the completion handler (runs on worker thread)
        def on_task_done(future):
            if self._query_id != current_qid:
                return

            try:
                new_items = future.result()
                if not new_items: 
                    return
                
                with self._search_lock:
                    if self._query_id != current_qid:
                        return
                        
                    current_results.extend(new_items)
                    current_results.sort(key=lambda x: x.score, reverse=True)
                    results_snapshot = list(current_results)
                
                try:
                    callback_fn(results_snapshot, current_qid)
                except Exception:
                    import sys
                    log_exception("qt_callback_from_thread", sys.exc_info())
                    print(f"[Error] Qt callback crashed - see crash log")
                
            except Exception:
                import sys
                log_exception("task_callback", sys.exc_info())
                print(f"[Error] Task callback crashed - see crash log")

        # 4. Submit tasks
        for ext in self.extensions:
            if self.settings.is_extension_enabled(ext.id):
                future = self.executor.submit(self._safe_query, ext, text)
                future.add_done_callback(on_task_done)

    def shutdown(self):
        # Notify extensions of shutdown if they support it
        for ext in self.extensions:
            if hasattr(ext, 'cleanup'):
                try:
                    ext.cleanup()
                except Exception:
                    pass        
        self.executor.shutdown(wait=False)