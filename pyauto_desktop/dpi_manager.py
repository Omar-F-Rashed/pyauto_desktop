import ctypes
from ctypes import windll, wintypes

# --- Constants for Windows API ---
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4


def enable_dpi_awareness():
    """
    Forces the application to be 'Per-Monitor DPI Aware'.
    Tries V2 first (Win10/11), falls back to V1 (Win8.1), then System (Win7).
    This ensures coordinates match physical pixels on mixed-resolution/VSR screens.
    """
    try:
        # Method 1: Per-Monitor V2 (Windows 10 Anniversary Update +)
        # This is the gold standard for mixed DPI environments.
        result = windll.user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        if result == 0:
            raise Exception("V2 Failed")
    except Exception:
        try:
            # Method 2: Per-Monitor V1 (Windows 8.1 +)
            # This worked for your setup and handles the VSR offset correctly.
            windll.shcore.SetProcessDpiAwareness(2)  # 2 = Process_Per_Monitor_DPI_Aware
        except Exception:
            try:
                # Method 3: System Aware (Vista/7)
                windll.user32.SetProcessDPIAware()
            except Exception:
                pass  # If all fail, proceed with default scaling (offsets may occur)


def get_window_rect(hwnd):
    """
    Returns the physical pixel coordinates of the window,
    bypassing Windows DPI virtualization.
    """
    rect = wintypes.RECT()
    try:
        # DWM Extended Frame Bounds excludes the invisible drop shadow borders,
        # giving a tighter, more accurate fit for overlays.
        dwmapi = ctypes.windll.dwmapi
        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect)
        )
    except Exception:
        # Standard fallback if DWM fails
        windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))

    return (rect.left, rect.top, rect.right, rect.bottom)