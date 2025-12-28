import platform
import ctypes

IS_WINDOWS = platform.system() == "Windows"

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

if IS_WINDOWS:
    from ctypes import windll, wintypes


def enable_dpi_awareness():
    if not IS_WINDOWS:
        return

    try:
        result = windll.user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        if result == 0:
            raise Exception("V2 Failed")
    except Exception:
        try:
            windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def get_window_rect(hwnd):
    if not IS_WINDOWS:
        return (0, 0, 0, 0)

    rect = wintypes.RECT()
    try:
        dwmapi = ctypes.windll.dwmapi
        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect)
        )
    except Exception:
        windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))

    return (rect.left, rect.top, rect.right, rect.bottom)