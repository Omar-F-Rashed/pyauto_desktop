from .functions import Session
from . import dpi_manager
dpi_manager.enable_dpi_awareness()

def inspector():
    from .main import run_inspector
    run_inspector()

__all__ = ['Session', 'inspector']