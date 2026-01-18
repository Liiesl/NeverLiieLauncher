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
        self.setup_dll()

    def setup_dll(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        dll_name = "Everything64.dll" if sys.maxsize > 2**32 else "Everything32.dll"
        dll_path = os.path.join(script_dir, dll_name)
        
        self.available = False
        if os.path.exists(dll_path):
            try:
                self.dll = ctypes.WinDLL(dll_path)
                self.dll.Everything_SetSearchW.argtypes = [ctypes.c_wchar_p]
                self.dll.Everything_GetResultFileNameW.restype = ctypes.c_wchar_p
                self.dll.Everything_GetResultPathW.restype = ctypes.c_wchar_p
                self.dll.Everything_GetNumResults.restype = ctypes.c_int
                self.dll.Everything_SetRequestFlags(0x00000001 | 0x00000002)
                self.available = True
            except Exception as e:
                print(f"DLL Error: {e}")

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
            # ShellExecuteW with "runas" verb triggers UAC
            ctypes.windll.shell32.ShellExecuteW(None, "runas", path, None, None, 1)
        except Exception as e:
            print(f"Admin Run Error: {e}")

    def open_terminal(self, path):
        """Opens CMD at the file's directory"""
        try:
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            # /K keeps the window open
            subprocess.Popen(f'start cmd /K "cd /d {folder}"', shell=True)
        except Exception as e:
            print(f"Terminal Error: {e}")

    def show_properties(self, path):
        """Shows the Windows Properties dialog (Right-click -> Properties)"""
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

        search_text = text.replace('/', '\\')
        self.dll.Everything_SetSearchW(search_text)
        self.dll.Everything_QueryW(True)
        results = []
        num_results = self.dll.Everything_GetNumResults()

        filter_dirs = ['.git', 'node_modules', 'venv', '__pycache__', '.venv', 'dist', 'build', '.next', 'out']
        is_explicit_filter_search = any(d in search_text.lower() for d in filter_dirs)

        for i in range(min(num_results, 20)):
            name = self.dll.Everything_GetResultFileNameW(i)
            folder = self.dll.Everything_GetResultPathW(i)
            full_path = os.path.join(folder, name)

            # --- Filtering Logic ---
            if not is_explicit_filter_search:
                normalized_full = full_path.replace('\\', '/').lower()
                if any(f'/{d}/' in normalized_full or normalized_full.endswith(f'/{d}') for d in filter_dirs):
                    continue

                normalized_path = full_path.replace('\\', '/')
                gitignore_path = os.path.join(folder, '.gitignore')
                if os.path.exists(gitignore_path):
                    rel_path = os.path.relpath(normalized_path, folder).replace('\\', '/')
                    if path_matches_pattern(rel_path, parse_gitignore_patterns(gitignore_path), folder):
                        continue

            # --- Determine File Type ---
            ext = os.path.splitext(name)[1].lower()
            is_exec = ext in ['.exe', '.bat', '.cmd', '.lnk', '.msi']
            is_text = ext in ['.txt', '.py', '.js', '.json', '.md', '.log', '.ini', '.css', '.html']

            # --- Build Actions ---
            
            # Default Action (Enter)
            action_open = Action("Open", lambda p=full_path: os.startfile(p))

            # Context Menu Actions
            context_actions = []
            
            # 1. Standard Open
            context_actions.append(Action("Open", lambda p=full_path: os.startfile(p)))
            
            # 2. Open With (Picker)
            context_actions.append(Action("Open With...", lambda p=full_path: self.open_with(p)))
            
            # 3. Run as Admin (Executables only)
            if is_exec:
                context_actions.append(Action("Run as Administrator", lambda p=full_path: self.run_as_admin(p)))
            
            # 4. Show in Folder
            context_actions.append(Action("Show in Folder", lambda p=full_path: self.show_in_folder(p)))

            # 5. Open Location in Terminal
            context_actions.append(Action("Open Location in Terminal", lambda p=full_path: self.open_terminal(p)))

            # 6. Copy Path
            context_actions.append(Action("Copy Path", lambda p=full_path: self.copy_to_clipboard(p)))
            
            # 7. Copy Content (Text files only)
            if is_text:
                context_actions.append(Action("Copy File Content", lambda p=full_path: self.copy_file_content(p)))

            # 8. Properties
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

        return results

Extension = EverythingExtension