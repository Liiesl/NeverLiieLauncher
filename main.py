import sys
import traceback
from core.crash_logger import log_exception, enable_segfault_handler

def crash_logger(exc_type, exc_value, exc_tb):
    log_exception("unhandled_exception", (exc_type, exc_value, exc_tb))
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = crash_logger
enable_segfault_handler()

from core.app import App

if __name__ == "__main__":
    app = App()
    app.run()
