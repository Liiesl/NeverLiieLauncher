import os
import traceback
import faulthandler
from datetime import datetime

CRASH_DIR = os.path.join(os.getenv("APPDATA"), "NeverLiie", "crashes")
os.makedirs(CRASH_DIR, exist_ok=True)

_segfault_file = None

def get_crash_path(suffix=""):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}-crash{suffix}.log"
    return os.path.join(CRASH_DIR, filename)

def log_exception(source, exc_info):
    try:
        log_path = get_crash_path()
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"=== Crash Log: {datetime.now().isoformat()} ===\n")
            f.write(f"Source: {source}\n\n")
            traceback.print_exception(*exc_info, file=f)
        return log_path
    except Exception:
        pass
    return None

def log_message(source, message):
    try:
        log_path = get_crash_path()
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"=== Error Log: {datetime.now().isoformat()} ===\n")
            f.write(f"Source: {source}\n\n")
            f.write(str(message))
        return log_path
    except Exception:
        pass
    return None

def enable_segfault_handler():
    global _segfault_file
    try:
        _segfault_file = open(get_crash_path("_segfault"), "wb")
        faulthandler.enable(_segfault_file)
    except Exception:
        pass
