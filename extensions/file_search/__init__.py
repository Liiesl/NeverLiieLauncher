# extensions/file_search/__init__.py
import os
import sys
import ctypes
import re
import subprocess
from PySide6.QtGui import QGuiApplication
from api.extension import Extension
from api.types import ResultItem, Action

# --- Ctypes Definitions for Properties Dialog ---
SEE_MASK_INVOKEIDLIST = 0x0000000C
SW_SHOW = 5

class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_int),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_int),
        ("hIcon", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]

# --- Helper Functions ---
def parse_gitignore_patterns(gitignore_path):
    patterns = []
    if not os.path.exists(gitignore_path):
        return patterns
    try:
        with open(gitignore_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    patterns.append(line)
    except:
        pass
    return patterns

def path_matches_pattern(path, patterns, base_path):
    for pattern in patterns:
        if pattern.startswith('!'):
            continue
        pattern = pattern.rstrip('/')
        regex_pattern = pattern
        if pattern.startswith('/'):
            regex_pattern = '^' + pattern[1:]
        elif pattern.endswith('/'):
            regex_pattern = '.*/' + pattern.rstrip('/') + '$'
        else:
            regex_pattern = '.*/' + pattern + '$'
        regex_pattern = regex_pattern.replace('.', '\\.').replace('*', '.*').replace('?', '.')
        if re.match(regex_pattern, path):
            return True
    return False

class EverythingExtension(Extension):
    def __init__(self, api):
        super().__init__(api)
        self.client = None
        self.setup_dll()

    def setup_dll(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        dll_name = "Everything3_x64.dll" if sys.maxsize > 2**32 else "Everything32.dll"
        dll_path = os.path.join(script_dir, dll_name)
        
        self.available = False
        if os.path.exists(dll_path):
            try:
                self.dll = ctypes.WinDLL(dll_path)
                
                # --- Define Everything 1.5 SDK (v3) Signatures ---
                
                # Client Connection
                self.dll.Everything3_ConnectW.argtypes = [ctypes.c_wchar_p]
                self.dll.Everything3_ConnectW.restype = ctypes.c_void_p # Returns Client*
                
                self.dll.Everything3_DestroyClient.argtypes = [ctypes.c_void_p]
                self.dll.Everything3_DestroyClient.restype = ctypes.c_bool

                # Search State
                self.dll.Everything3_CreateSearchState.argtypes = []
                self.dll.Everything3_CreateSearchState.restype = ctypes.c_void_p # Returns SearchState*

                self.dll.Everything3_DestroySearchState.argtypes = [ctypes.c_void_p]
                self.dll.Everything3_DestroySearchState.restype = ctypes.c_bool

                self.dll.Everything3_SetSearchTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
                self.dll.Everything3_SetSearchTextW.restype = ctypes.c_bool

                # Execution
                self.dll.Everything3_Search.argtypes = [ctypes.c_void_p, ctypes.c_void_p] # Client*, SearchState*
                self.dll.Everything3_Search.restype = ctypes.c_void_p # Returns ResultList*

                # Results
                self.dll.Everything3_DestroyResultList.argtypes = [ctypes.c_void_p]
                self.dll.Everything3_DestroyResultList.restype = ctypes.c_bool

                self.dll.Everything3_GetResultListViewportCount.argtypes = [ctypes.c_void_p]
                self.dll.Everything3_GetResultListViewportCount.restype = ctypes.c_size_t

                self.dll.Everything3_GetResultFullPathNameW.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_wchar_p, ctypes.c_size_t]
                self.dll.Everything3_GetResultFullPathNameW.restype = ctypes.c_size_t

                # Check for Folder Result
                self.dll.Everything3_IsFolderResult.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
                self.dll.Everything3_IsFolderResult.restype = ctypes.c_bool

                self.available = True
                
                # Initialize Connection (Try default, then 1.5a)
                self.connect_client()
                
            except Exception as e:
                print(f"Everything SDK Error: {e}")
                self.available = False

    def connect_client(self):
        """Attempts to connect to Everything 1.5 IPC"""
        if self.client:
            return

        # Try default unnamed instance
        self.client = self.dll.Everything3_ConnectW(None)
        
        # If failed, try "1.5a" instance (standard for 1.5 alpha)
        if not self.client:
            self.client = self.dll.Everything3_ConnectW("1.5a")
        
        if not self.client:
            print("Could not connect to Everything 1.5 instance.")

    def __del__(self):
        # Cleanup client on exit
        if self.available and self.client:
            self.dll.Everything3_DestroyClient(self.client)

    # --- Actions ---

    def copy_to_clipboard(self, text):
        QGuiApplication.clipboard().setText(text)

    def show_in_folder(self, path):
        try:
            path = os.path.normpath(path)
            subprocess.Popen(f'explorer /select,"{path}"')
        except Exception as e:
            print(f"Explorer Error: {e}")

    def open_with(self, path):
        try:
            path = os.path.normpath(path)
            subprocess.Popen(['rundll32', 'shell32.dll,OpenAs_RunDLL', path])
        except Exception as e:
            print(f"Open With Error: {e}")

    def run_as_admin(self, path):
        """Runs executable with UAC prompt"""
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", path, None, None, 1)
        except Exception as e:
            print(f"Admin Run Error: {e}")

    def open_terminal(self, path):
        """Opens CMD at the file's directory"""
        try:
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            subprocess.Popen(f'start cmd /K "cd /d {folder}"', shell=True)
        except Exception as e:
            print(f"Terminal Error: {e}")

    def show_properties(self, path):
        """Shows the Windows Properties dialog"""
        try:
            sei = SHELLEXECUTEINFOW()
            sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
            sei.fMask = SEE_MASK_INVOKEIDLIST
            sei.lpVerb = "properties"
            sei.lpFile = path
            sei.nShow = SW_SHOW
            ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
        except Exception as e:
            print(f"Properties Error: {e}")

    def copy_file_content(self, path):
        """Reads text file content to clipboard (Max 1MB)"""
        try:
            if os.path.getsize(path) > 1024 * 1024: # 1MB limit
                print("File too large to copy content")
                return
            
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                QGuiApplication.clipboard().setText(content)
        except Exception as e:
            print(f"Read Error: {e}")

    def on_input(self, text):
        if not self.available or not text: return []
        
        # Ensure we have a client connection
        if not self.client:
            self.connect_client()
            if not self.client:
                return []

        # Normalize search text for Everything (it prefers backslashes for paths)
        # We pass the slash to Everything so it knows to look for directories if provided
        search_text = text.replace('/', '\\')
        results = []

        # 1. Create Search State
        search_state = self.dll.Everything3_CreateSearchState()
        if not search_state:
            return []

        try:
            # 2. Set Search Text
            self.dll.Everything3_SetSearchTextW(search_state, search_text)

            # 3. Execute Search (Blocks until results are ready)
            result_list = self.dll.Everything3_Search(self.client, search_state)
            
            if result_list:
                try:
                    # 4. Process Results
                    num_results = self.dll.Everything3_GetResultListViewportCount(result_list)
                    
                    filter_dirs = ['.git', 'node_modules', 'venv', '__pycache__', '.venv', 'dist', 'build', '.next', 'out']
                    
                    # Only bypass the GLOBAL junk filter if the user is specifically typing the junk name.
                    # This does NOT bypass gitignore.
                    is_explicit_junk_search = any(d in search_text.lower() for d in filter_dirs)

                    buffer_size = 260 # MAX_PATH
                    filename_buffer = ctypes.create_unicode_buffer(buffer_size)

                    for i in range(min(num_results, 20)):
                        # Retrieve Full Path
                        # Try standard size first
                        req_len = self.dll.Everything3_GetResultFullPathNameW(result_list, i, filename_buffer, buffer_size)
                        
                        # Handle Long Paths if necessary
                        if req_len > buffer_size:
                            large_buffer = ctypes.create_unicode_buffer(req_len + 1)
                            self.dll.Everything3_GetResultFullPathNameW(result_list, i, large_buffer, req_len + 1)
                            full_path = large_buffer.value
                        else:
                            full_path = filename_buffer.value

                        name = os.path.basename(full_path)
                        folder = os.path.dirname(full_path)
                        
                        # Check if result is a folder using SDK
                        is_folder = self.dll.Everything3_IsFolderResult(result_list, i)

                        # --- Filtering Logic ---
                        normalized_full = full_path.replace('\\', '/').lower()
                        
                        # 1. Global junk folders filter
                        # Skipped only if user is explicitly searching for "node_modules" etc.
                        if not is_explicit_junk_search:
                            if any(f'/{d}/' in normalized_full or normalized_full.endswith(f'/{d}') for d in filter_dirs):
                                continue

                        # 2. .gitignore filter
                        # This runs ALWAYS unless the file itself IS the gitignore file, 
                        # or if you are specifically looking for a file that happens to be ignored 
                        # (but we default to hiding ignored files to keep results clean).
                        normalized_path = full_path.replace('\\', '/')
                        gitignore_path = os.path.join(folder, '.gitignore')
                        if os.path.exists(gitignore_path):
                            rel_path = os.path.relpath(normalized_path, folder).replace('\\', '/')
                            if path_matches_pattern(rel_path, parse_gitignore_patterns(gitignore_path), folder):
                                continue

                        # --- Determine File Type ---
                        ext = os.path.splitext(name)[1].lower()
                        is_exec = not is_folder and ext in ['.exe', '.bat', '.cmd', '.lnk', '.msi']
                        is_text = not is_folder and ext in ['.txt', '.py', '.js', '.json', '.md', '.log', '.ini', '.css', '.html']

                        # --- Build Actions ---
                        action_open = Action("Open", lambda p=full_path: os.startfile(p))

                        context_actions = []
                        context_actions.append(Action("Open", lambda p=full_path: os.startfile(p)))
                        
                        if not is_folder:
                            context_actions.append(Action("Open With...", lambda p=full_path: self.open_with(p)))
                        
                        if is_exec:
                            context_actions.append(Action("Run as Administrator", lambda p=full_path: self.run_as_admin(p)))
                        
                        context_actions.append(Action("Show in Folder", lambda p=full_path: self.show_in_folder(p)))
                        context_actions.append(Action("Open Location in Terminal", lambda p=full_path: self.open_terminal(p)))
                        context_actions.append(Action("Copy Path", lambda p=full_path: self.copy_to_clipboard(p)))
                        
                        if is_text:
                            context_actions.append(Action("Copy File Content", lambda p=full_path: self.copy_file_content(p)))
                        
                        context_actions.append(Action("Properties", lambda p=full_path: self.show_properties(p)))

                        results.append(ResultItem(
                            id=full_path,
                            name=name,
                            description=folder,
                            icon_path=full_path,
                            action=action_open,
                            context_actions=context_actions,
                            score=100
                        ))
                finally:
                    # 5. Clean up Result List
                    self.dll.Everything3_DestroyResultList(result_list)
        finally:
            # 6. Clean up Search State
            self.dll.Everything3_DestroySearchState(search_state)

        return results

Extension = EverythingExtension