from .functions import locateOnScreen, locateAllOnScreen

# Import the GUI runner from main.py
from .main import run_inspector as inspector
from . import dpi_manager

# Enable DPI awareness automatically on import
# This fixes coordinates for mixed-DPI and VSR screens
dpi_manager.enable_dpi_awareness()

__all__ = ['locateOnScreen', 'locateAllOnScreen', 'inspector']