import concurrent.futures
import time
import threading
from collections import defaultdict
from functools import lru_cache
import cv2
import mss
import numpy as np
from PIL import Image, ImageGrab
from pynput.mouse import Button, Controller
from pynput.keyboard import Key, Controller as KeyboardController
import platform
import ctypes
from .utils import logical_to_physical, local_to_global

if platform.system() == "Windows":
    import ctypes.wintypes

# --- DEBUGGING CONFIGURATION ---
# 0 = Off
# 1 = Basic Logs (Errors/Status)
# 2 = Performance Tracing (Timings for major steps)
DEBUG_LEVEL = 1

# --- INPUT CONTROLLERS ---
_mouse_controller = Controller()
_keyboard_controller = KeyboardController()


# --- EXCEPTION CLASSES ---
class FailSafeException(Exception):
    pass


# --- THREAD LOCAL MSS ---
# Replaces _CaptureServer for safer, faster, lock-free access
_thread_local = threading.local()


def _get_mss_instance():
    """
    Returns a thread-local instance of mss.
    Initializes it if it doesn't exist for the current thread.
    """
    if not hasattr(_thread_local, "sct"):
        try:
            _thread_local.sct = mss.mss()
        except Exception as e:
            if DEBUG_LEVEL >= 1: print(f"Error initializing MSS: {e}")
            _thread_local.sct = None
    return _thread_local.sct


# --- Profiling Helper ---
class PerformanceTimer:
    """
    Context manager to measure execution time of code blocks.
    Only prints if DEBUG_LEVEL >= 2.
    """

    def __init__(self, name):
        self.name = name
        self.start = 0

    def __enter__(self):
        if DEBUG_LEVEL >= 2:
            self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if DEBUG_LEVEL >= 2:
            end = time.perf_counter()
            duration = (end - self.start) * 1000
            print(f"[PERF] {self.name:<30}: {duration:.2f} ms")


# --- Screen Routing & Configuration ---
_SCREEN_ROUTER = {}

if platform.system() == "Windows":
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


    MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT),
                                         ctypes.c_double)

    # Try to set DPI Awareness
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        pass


def get_resource_counts():
    """Returns (GDI Objects, User Objects) count for the current process."""
    if platform.system() != "Windows":
        return 0, 0

    try:
        # Constants for Windows API
        GR_GDIOBJECTS = 0
        GR_USEROBJECTS = 1

        process_handle = ctypes.windll.kernel32.GetCurrentProcess()
        gdi_count = ctypes.windll.user32.GetGuiResources(process_handle, GR_GDIOBJECTS)
        user_count = ctypes.windll.user32.GetGuiResources(process_handle, GR_USEROBJECTS)
        return gdi_count, user_count
    except Exception:
        return -1, -1


def route_screen(logical_screen, physical_screen):
    _SCREEN_ROUTER[logical_screen] = physical_screen


def _resolve_screen(screen_idx):
    return _SCREEN_ROUTER.get(screen_idx, screen_idx)


def get_monitors_safe():
    with PerformanceTimer("Get Monitors Info"):
        # Use existing MSS instance (Zero overhead)
        sct = _get_mss_instance()
        if not sct:
            return []

        monitors = []
        # MSS monitors[0] is 'all combined'. We want individual physical monitors (1+)
        if len(sct.monitors) > 1:
            for m in sct.monitors[1:]:
                monitors.append((m['left'], m['top'], m['width'], m['height']))
        else:
            m = sct.monitors[0]
            monitors.append((m['left'], m['top'], m['width'], m['height']))

        return monitors


def get_monitor_dpr(screen_idx, monitors=None):
    if platform.system() == "Windows":
        try:
            if monitors is None:
                monitors = get_monitors_safe()

            if screen_idx >= len(monitors):
                return 1.0

            mx, my, mw, mh = monitors[screen_idx]
            pt = ctypes.wintypes.POINT(mx + mw // 2, my + mh // 2)
            user32 = ctypes.windll.user32
            shcore = ctypes.windll.shcore

            hmon = user32.MonitorFromPoint(pt, 2)
            dpi_x = ctypes.c_uint()
            dpi_y = ctypes.c_uint()
            res = shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
            if res == 0:
                return dpi_x.value / 96.0
        except Exception as e:
            if DEBUG_LEVEL >= 1: print(f"DPR detection failed: {e}")
            pass

    return 1.0


# --- CORE IMAGE PROCESSING HELPERS (Stateless) ---

def _load_image(img):
    if isinstance(img, str):
        with PerformanceTimer(f"Load Image from Disk ({img})"):
            return Image.open(img)
    return img


def _non_max_suppression(boxes, overlap_thresh):
    with PerformanceTimer("Non-Max Suppression"):
        if len(boxes) == 0:
            return []

        boxes_np = np.array(boxes, dtype=np.float32)
        x1 = boxes_np[:, 0]
        y1 = boxes_np[:, 1]
        x2 = boxes_np[:, 0] + boxes_np[:, 2]
        y2 = boxes_np[:, 1] + boxes_np[:, 3]
        area = (x2 - x1 + 1) * (y2 - y1 + 1)
        idxs = np.argsort(y2)
        pick = []

        while len(idxs) > 0:
            last = len(idxs) - 1
            i = idxs[last]
            pick.append(i)
            xx1 = np.maximum(x1[i], x1[idxs[:last]])
            yy1 = np.maximum(y1[i], y1[idxs[:last]])
            xx2 = np.minimum(x2[i], x2[idxs[:last]])
            yy2 = np.minimum(y2[i], y2[idxs[:last]])
            w = np.maximum(0, xx2 - xx1 + 1)
            h = np.maximum(0, yy2 - yy1 + 1)
            overlap = (w * h) / area[idxs[:last]]
            idxs = np.delete(idxs, np.concatenate(([last], np.where(overlap > overlap_thresh)[0])))

        return [boxes[i] for i in pick]


@lru_cache(maxsize=128)
def _load_cached_needle(image_path, scale_factor, grayscale):
    if DEBUG_LEVEL >= 2: print(f"[CACHE] Loading/Processing Needle: {image_path} (Scale: {scale_factor})")
    with PerformanceTimer("Process Needle (Uncached)"):
        img = Image.open(image_path)
        return _process_needle_to_cv2(img, scale_factor, grayscale)


def _process_needle_to_cv2(img_pil, scale_factor, grayscale):
    """
    Converts PIL image to OpenCV format, resizes it using cv2.resize, and handles alpha masks/grayscale.
    """
    if img_pil.mode not in ('RGB', 'RGBA', 'L'):
        img_pil = img_pil.convert('RGBA')

    needle_np = np.array(img_pil)

    # Convert to OpenCV BGR / BGRA BEFORE resize to ensure correct CV2 format
    if img_pil.mode == 'RGBA':
        needle = cv2.cvtColor(needle_np, cv2.COLOR_RGBA2BGRA)
    elif img_pil.mode == 'RGB':
        needle = cv2.cvtColor(needle_np, cv2.COLOR_RGB2BGR)
    elif img_pil.mode == 'L':
        needle = cv2.cvtColor(needle_np, cv2.COLOR_GRAY2BGR)
    else:
        if len(needle_np.shape) == 3 and needle_np.shape[2] == 4:
            needle = cv2.cvtColor(needle_np, cv2.COLOR_RGBA2BGRA)
        elif len(needle_np.shape) == 3 and needle_np.shape[2] == 3:
            needle = cv2.cvtColor(needle_np, cv2.COLOR_RGB2BGR)
        else:
            if len(needle_np.shape) == 2:
                needle = cv2.cvtColor(needle_np, cv2.COLOR_GRAY2BGR)
            else:
                needle = needle_np

    scale_x, scale_y = 1.0, 1.0
    if isinstance(scale_factor, (tuple, list)):
        scale_x, scale_y = scale_factor
    else:
        scale_x = scale_factor
        scale_y = scale_factor

    if scale_x != 1.0 or scale_y != 1.0:
        h, w = needle.shape[:2]
        new_w = int(max(1, w * scale_x))
        new_h = int(max(1, h * scale_y))

        # Downscaling -> INTER_AREA, Upscaling -> INTER_CUBIC
        if scale_x < 1.0 and scale_y < 1.0:
            interpolation = cv2.INTER_AREA
        else:
            interpolation = cv2.INTER_CUBIC

        with PerformanceTimer("Resize Needle (CV2)"):
            needle = cv2.resize(needle, (new_w, new_h), interpolation=interpolation)

    mask = None
    if len(needle.shape) == 3 and needle.shape[2] == 4:
        alpha = needle[:, :, 3]
        if np.all(alpha == 255):
            mask = None
            needle = cv2.cvtColor(needle, cv2.COLOR_BGRA2BGR)
        else:
            mask = np.ascontiguousarray(alpha)
            needle = cv2.cvtColor(needle, cv2.COLOR_BGRA2BGR)

    if grayscale:
        if len(needle.shape) == 3:
            needle = cv2.cvtColor(needle, cv2.COLOR_BGR2GRAY)
        mask = None

    return needle, mask


def _run_template_match(needleImage, haystackImage, grayscale=False, scale_factor=1.0):
    haystack_obj = _load_image(haystackImage)

    if isinstance(haystack_obj, np.ndarray):
        haystack = haystack_obj
        if len(haystack.shape) == 3 and haystack.shape[2] == 4:
            if grayscale:
                haystack = cv2.cvtColor(haystack, cv2.COLOR_BGRA2GRAY)
            else:
                haystack = cv2.cvtColor(haystack, cv2.COLOR_BGRA2BGR)
        elif grayscale and len(haystack.shape) == 3:
            haystack = cv2.cvtColor(haystack, cv2.COLOR_BGR2GRAY)
    else:
        haystack_pil = haystack_obj
        haystack_np = np.array(haystack_pil)
        if haystack_pil.mode == 'RGB':
            haystack = cv2.cvtColor(haystack_np, cv2.COLOR_RGB2BGR)
        elif haystack_pil.mode == 'RGBA':
            haystack = cv2.cvtColor(haystack_np, cv2.COLOR_RGBA2BGR)
        else:
            haystack = haystack_np
            if len(haystack.shape) == 2:
                haystack = cv2.cvtColor(haystack, cv2.COLOR_GRAY2BGR)
        if grayscale and len(haystack.shape) == 3:
            haystack = cv2.cvtColor(haystack, cv2.COLOR_BGR2GRAY)

    if isinstance(needleImage, str):
        needle, mask = _load_cached_needle(needleImage, scale_factor, grayscale)
    else:
        needle_pil = _load_image(needleImage)
        needle, mask = _process_needle_to_cv2(needle_pil, scale_factor, grayscale)

    method = None
    needle_blur = cv2.GaussianBlur(needle, (5, 5), 0)
    haystack_blur = cv2.GaussianBlur(haystack, (5, 5), 0)
    if mask is not None and not grayscale:
        method = cv2.TM_SQDIFF_NORMED
        res = cv2.matchTemplate(haystack_blur, needle_blur, method, mask=mask)
    else:
        method = cv2.TM_CCOEFF_NORMED
        res = cv2.matchTemplate(haystack_blur, needle_blur, method)

    h, w = needle.shape[:2]
    return res, w, h, method


def _get_image_size(image):
    if isinstance(image, str):
        try:
            with Image.open(image) as img:
                return img.size
        except:
            return (0, 0)
    elif hasattr(image, 'size'):
        return image.size
    return (0, 0)


def _locate_all_pyramid(needleImage, haystackImage, grayscale, confidence, overlap_threshold, scale_factor, downscale,
                        return_conf=False):
    sf_x, sf_y = 1.0, 1.0
    if isinstance(scale_factor, (tuple, list)):
        sf_x, sf_y = scale_factor
    else:
        sf_x = sf_y = scale_factor

    # Convert full haystack to CV2 format once to avoid repeated conversions on crops
    with PerformanceTimer("Pyramid: Prep Haystack"):
        haystack_full_raw = _load_image(haystackImage)
        if not isinstance(haystack_full_raw, np.ndarray):
            haystack_full_raw = np.array(haystack_full_raw)

        haystack_full = haystack_full_raw
        if len(haystack_full.shape) == 3:
            if haystack_full.shape[2] == 4:  # RGBA/BGRA
                if grayscale:
                    haystack_full = cv2.cvtColor(haystack_full, cv2.COLOR_BGRA2GRAY)
                else:
                    haystack_full = cv2.cvtColor(haystack_full, cv2.COLOR_BGRA2BGR)
            elif haystack_full.shape[2] == 3:  # RGB/BGR
                # Assuming RGB if coming from PIL, but OpenCV needs BGR
                if grayscale:
                    haystack_full = cv2.cvtColor(haystack_full, cv2.COLOR_RGB2GRAY)
                else:
                    haystack_full = cv2.cvtColor(haystack_full, cv2.COLOR_RGB2BGR)
        elif len(haystack_full.shape) == 2 and not grayscale:
            haystack_full = cv2.cvtColor(haystack_full, cv2.COLOR_GRAY2BGR)

        if haystack_full is None or haystack_full.size == 0:
            return []

        h_full, w_full = haystack_full.shape[:2]
        small_w = int(w_full / downscale)
        small_h = int(h_full / downscale)

        haystack_small = cv2.resize(haystack_full, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
        coarse_scale = (sf_x / downscale, sf_y / downscale)

    # Prepare needles once to prevent 'Resize Needle' calls inside loops
    with PerformanceTimer("Pyramid: Prep Needles"):
        if isinstance(needleImage, str):
            fine_needle, fine_mask = _load_cached_needle(needleImage, scale_factor, grayscale)
        else:
            fine_needle, fine_mask = _process_needle_to_cv2(_load_image(needleImage), scale_factor, grayscale)

        fine_needle_blur = cv2.GaussianBlur(fine_needle, (3, 3), 0)

        if fine_mask is not None and not grayscale:
            fine_method = cv2.TM_SQDIFF_NORMED
        else:
            fine_method = cv2.TM_CCOEFF_NORMED

    with PerformanceTimer("Pyramid: Coarse Search"):
        # Reuse _run_template_match passing the ALREADY converted haystack_small
        coarse_confidence = max(0.5, confidence - 0.15)
        res, w_s, h_s, method = _run_template_match(
            needleImage,
            haystack_small,
            grayscale,
            scale_factor=coarse_scale
        )

        if method == cv2.TM_SQDIFF_NORMED or method == cv2.TM_SQDIFF:
            match_threshold = 1.0 - coarse_confidence
            loc = np.where(res <= match_threshold)
        else:
            loc = np.where(res >= coarse_confidence)

    candidate_count = len(loc[0])
    if candidate_count > 80:
        if DEBUG_LEVEL >= 2:
            print(f"[PERF] Pyramid Abort: Too many candidates ({candidate_count})")
        return None

    if candidate_count == 0:
        return []

    verified_rects = []

    with PerformanceTimer("Pyramid: Fine Verification"):
        coarse_points = list(zip(*loc[::-1]))
        padding = int(16 * max(sf_x, sf_y))
        w_f, h_f = fine_needle.shape[1], fine_needle.shape[0]

        for pt in coarse_points:
            x_small, y_small = pt
            x_orig_center = int(x_small * downscale)
            y_orig_center = int(y_small * downscale)

            w_orig_approx = int(w_s * downscale)
            h_orig_approx = int(h_s * downscale)

            roi_x1 = max(0, x_orig_center - padding)
            roi_y1 = max(0, y_orig_center - padding)
            roi_x2 = min(w_full, x_orig_center + w_orig_approx + padding)
            roi_y2 = min(h_full, y_orig_center + h_orig_approx + padding)

            if roi_x2 <= roi_x1 or roi_y2 <= roi_y1:
                continue

            # Crop from the ALREADY converted haystack_full
            haystack_crop = haystack_full[roi_y1:roi_y2, roi_x1:roi_x2]
            haystack_crop_blur = cv2.GaussianBlur(haystack_crop, (3, 3), 0)

            if fine_method == cv2.TM_SQDIFF_NORMED:
                res_fine = cv2.matchTemplate(haystack_crop_blur, fine_needle_blur, fine_method, mask=fine_mask)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res_fine)
                match_val = 1.0 - min_val
                match_loc = min_loc
            else:
                res_fine = cv2.matchTemplate(haystack_crop_blur, fine_needle_blur, fine_method)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res_fine)
                match_val = max_val
                match_loc = max_loc

            if match_val >= confidence:
                final_x = roi_x1 + match_loc[0]
                final_y = roi_y1 + match_loc[1]
                verified_rects.append([final_x, final_y, w_f, h_f, match_val])

    if len(verified_rects) > 0:
        if overlap_threshold < 1.0:
            verified_rects = _non_max_suppression(verified_rects, overlap_threshold)

        verified_rects.sort(key=lambda r: (r[1], r[0]))

        if return_conf:
            return [tuple(r) for r in verified_rects]
        else:
            return [tuple(r[:4]) for r in verified_rects]

    return []


def _core_locate_all(needleImage, haystackImage, grayscale=False, confidence=0.9, overlap_threshold=0.5,
                     scale_factor=1.0, downscale=1, use_pyramid=True, return_conf=False):
    """
    Core logic: Locate all instances of 'needleImage' inside 'haystackImage'.
    """

    if use_pyramid and downscale > 1:
        nw, nh = _get_image_size(needleImage)
        MIN_NEEDLE_DIM = 16

        if nw > 0 and nh > 0:
            max_safe_scale = min(nw / MIN_NEEDLE_DIM, nh / MIN_NEEDLE_DIM)
            if downscale > max_safe_scale:
                downscale = max_safe_scale

        if downscale >= 1.3:
            ret = _locate_all_pyramid(needleImage, haystackImage, grayscale, confidence, overlap_threshold,
                                      scale_factor, downscale, return_conf)
            if ret is not None:
                return ret

    limit = 100
    if haystackImage is None or haystackImage.size == 0:
        print(f"No haystack image found {haystackImage}")
        return []

    with PerformanceTimer("OpenCV MatchTemplate (Full Res)"):
        res, w, h, method = _run_template_match(needleImage, haystackImage, grayscale, scale_factor)

    with PerformanceTimer("Filter Results"):
        if method == cv2.TM_SQDIFF_NORMED or method == cv2.TM_SQDIFF:
            match_threshold = 1.0 - confidence
            loc = np.where(res <= match_threshold)
        else:
            loc = np.where(res >= confidence)

        if len(loc[0]) > limit and overlap_threshold < 1.0:
            kernel = np.ones((5, 5), np.uint8)
            if method == cv2.TM_SQDIFF_NORMED or method == cv2.TM_SQDIFF:
                background = cv2.erode(res, kernel)
                peaks = (res == background)
                match_threshold = 1.0 - confidence
                loc = np.where(peaks & (res <= match_threshold))
            else:
                background = cv2.dilate(res, kernel)
                peaks = (res == background)
                loc = np.where(peaks & (res >= confidence))

        scores = res[loc]
        if method == cv2.TM_SQDIFF_NORMED or method == cv2.TM_SQDIFF:
            normalized_scores = 1.0 - scores
        else:
            normalized_scores = scores

        if len(scores) > limit:
            if method == cv2.TM_SQDIFF_NORMED:
                sorted_indices = np.argsort(scores)
            else:
                sorted_indices = np.argsort(scores)[::-1]
            keep_indices = sorted_indices[:limit]
            loc = (loc[0][keep_indices], loc[1][keep_indices])
            normalized_scores = normalized_scores[keep_indices]

        rects = []
        for i in range(len(loc[0])):
            y = int(loc[0][i])
            x = int(loc[1][i])
            score = float(normalized_scores[i])
            rects.append([x, y, int(w), int(h), score])

        if overlap_threshold < 1.0 and len(rects) > 1:
            rects = _non_max_suppression(rects, overlap_threshold)

        rects.sort(key=lambda r: (r[1], r[0]))

    if return_conf:
        return [tuple(r) for r in rects]
    else:
        return [tuple(r[:4]) for r in rects]


# --- SESSION CLASS ---
class Session:
    """
    A strict Object-Oriented Session for Desktop Automation.
    The 'screen' is immutable for the lifetime of the Session.
    """

    def __init__(self, screen=0, source_resolution=None, source_dpr=None, scaling_type=None, direct_input=False):
        self._screen = screen  # Immutable: No public setter
        self.source_resolution = source_resolution
        self.source_dpr = source_dpr
        self.scaling_type = scaling_type
        self.direct_input = direct_input

        if self.direct_input:
            if platform.system() != "Windows":
                raise OSError("direct_input=True is only supported on Windows.")
            global pydirectinput
            import pydirectinput
            pydirectinput.FAILSAFE = False

    def __del__(self):
        pass

    def _fail_safe_check(self):
        # When using pydirectinput, the pynput controller might not reflect true position if pydirectinput moved it
        # However, checking (0,0) is still valid for mouse position generally.
        x, y = _mouse_controller.position
        if x == 0 and y == 0:
            raise FailSafeException("Fail-safe triggered from mouse position (0, 0)")

    def _prepare_capture(self, region, override_resolution=None, monitors=None):
        gdi, user = get_resource_counts()

        with PerformanceTimer("Prepare Screen Capture"):
            physical_screen = _resolve_screen(self._screen)
            if monitors is None:
                monitors = get_monitors_safe()

            if physical_screen >= len(monitors):
                if physical_screen == len(monitors):
                    physical_screen = len(monitors) - 1
                else:
                    physical_screen = 0
            elif physical_screen < 0:
                physical_screen = 0

            monitor_left, monitor_top, monitor_width, monitor_height = monitors[physical_screen]
            scale_factor = 1.0

            capture_width = monitor_width
            capture_height = monitor_height
            capture_left = monitor_left
            capture_top = monitor_top

            if region:
                phys_region_local = region
                capture_left, capture_top, capture_width, capture_height = local_to_global(
                    phys_region_local,
                    (monitor_left, monitor_top)
                )

            monitor_dict = {
                "top": int(capture_top),
                "left": int(capture_left),
                "width": int(capture_width),
                "height": int(capture_height)
            }
            if capture_width <= 0 or capture_height <= 0:
                print(f"CRITICAL ERROR: Invalid Dimensions! {monitor_dict} monitors: {monitors} region: {region}")
                return None, 0, 0, 0

            with PerformanceTimer(f"MSS Grab ({capture_width}x{capture_height})"):
                try:
                    sct = _get_mss_instance()
                    if not sct: raise Exception("MSS Init Failed")

                    shot = sct.grab(monitor_dict)
                    sct_img = np.array(shot)
                except Exception as e:
                    if DEBUG_LEVEL >= 1:
                        print(f"!!! MSS FAIL | GDI: {gdi} | Err: {e}")
                        print(f"MSS Capture failed ({e}). Falling back to ImageGrab.")
                        print(
                            f"{monitor_dict} monitors: {monitors} region: {region} {capture_width}x{capture_height} {scale_factor}")
                    try:
                        bbox = (
                            capture_left,
                            capture_top,
                            capture_left + capture_width,
                            capture_top + capture_height
                        )
                        sct_img = np.array(ImageGrab.grab(bbox=bbox))
                    except Exception as fallback_e:
                        if DEBUG_LEVEL >= 1: print(f"Critical: Both Screen grabs failed: {fallback_e}")
                        return None, 0, 0, 0

            return sct_img, capture_left - monitor_left, capture_top - monitor_top, scale_factor

    def locateAllOnScreen(self, image, region=None, grayscale=False, confidence=0.9, overlap_threshold=0.5,
                          scaling_type=None, source_resolution=None, source_dpr=None, time_out=0, downscale=3,
                          use_pyramid=True,
                          return_conf=False):
        """
        Locate all instances of 'image' on the Session's screen.
        'screen' param is NOT available here; it is enforced by the Session.
        """
        start_time = time.time()
        loops = 0

        effective_scaling = scaling_type if scaling_type is not None else self.scaling_type
        effective_resolution = source_resolution if source_resolution is not None else self.source_resolution
        effective_dpr = source_dpr if source_dpr is not None else self.source_dpr

        target_res = None
        target_dpr = 1.0

        monitors = get_monitors_safe()
        phys_screen_idx = _resolve_screen(self._screen)

        if 0 <= phys_screen_idx < len(monitors):
            mx, my, mw, mh = monitors[phys_screen_idx]
            target_res = (mw, mh)
            target_dpr = get_monitor_dpr(phys_screen_idx, monitors)

        scale_x = 1.0
        scale_y = 1.0

        if effective_scaling == 'dpr':
            if effective_dpr and target_dpr:
                ratio = target_dpr / effective_dpr
                scale_x = ratio
                scale_y = ratio

        elif effective_scaling == 'resolution':
            if effective_resolution and target_res:
                sr_w, sr_h = effective_resolution
                tr_w, tr_h = target_res
                if sr_w > 0 and sr_h > 0:
                    scale_x = tr_w / sr_w
                    scale_y = tr_h / sr_h

        final_region = region
        if region:
            rx, ry, rw, rh = region
            if effective_scaling == 'dpr' or effective_scaling == 'resolution':
                final_region = (rx * scale_x, ry * scale_y, rw * scale_x, rh * scale_y)

        while True:
            loops += 1
            with PerformanceTimer(f"Loop #{loops} Total Time"):

                haystack_img, offset_x, offset_y, _ = self._prepare_capture(final_region, override_resolution=False,
                                                                            monitors=monitors)

                final_scale_factor = (scale_x, scale_y)

                if haystack_img is None:
                    if time.time() - start_time > time_out:
                        return []
                    time.sleep(0.5)
                    continue

                rects = _core_locate_all(image, haystack_img, grayscale, confidence, overlap_threshold,
                                         scale_factor=final_scale_factor, downscale=downscale,
                                         use_pyramid=use_pyramid, return_conf=return_conf)

                if DEBUG_LEVEL >= 2: print(f'======== {rects}')
                if rects:
                    if offset_x or offset_y:
                        final_rects = []
                        for r in rects:
                            rx, ry, rw, rh = r[:4]
                            remainder = r[4:]

                            new_rect = (rx + int(offset_x), ry + int(offset_y), rw, rh) + remainder
                            final_rects.append(new_rect)
                        return final_rects
                    return rects

                if time.time() - start_time > time_out:
                    return []

                time.sleep(0.01)

    def locateOnScreen(self, image, region=None, grayscale=False, confidence=0.9, source_resolution=None,
                       scaling_type=None, source_dpr=None, time_out=0, downscale=3, use_pyramid=True, ):

        effective_scaling = scaling_type if scaling_type is not None else self.scaling_type
        effective_resolution = source_resolution if source_resolution is not None else self.source_resolution
        effective_dpr = source_dpr if source_dpr is not None else self.source_dpr

        matches = self.locateAllOnScreen(
            image=image,
            region=region,
            grayscale=grayscale,
            confidence=confidence,
            overlap_threshold=0.5,
            source_resolution=effective_resolution,
            source_dpr=effective_dpr,
            scaling_type=effective_scaling,
            time_out=time_out,
            downscale=downscale,
            use_pyramid=use_pyramid,
            return_conf=True
        )

        if matches:
            matches.sort(key=lambda x: x[4], reverse=True)
            best_match = matches[0]
            return best_match[:4]

        return None

    def moveTo(self, x, y, duration=0.0):
        physical_screen = _resolve_screen(self._screen)
        monitors = get_monitors_safe()

        if physical_screen >= len(monitors):
            physical_screen = 0

        monitor_left, monitor_top, _, _ = monitors[physical_screen]

        dest_x = monitor_left + x
        dest_y = monitor_top + y

        self._fail_safe_check()

        if duration <= 0:
            if self.direct_input:
                pydirectinput.moveTo(int(dest_x), int(dest_y))
            else:
                _mouse_controller.position = (dest_x, dest_y)
            self._fail_safe_check()
        else:
            start_x, start_y = _mouse_controller.position
            start_time = time.time()

            while True:
                elapsed = time.time() - start_time
                if elapsed >= duration:
                    break

                ratio = elapsed / duration
                cur_x = start_x + (dest_x - start_x) * ratio
                cur_y = start_y + (dest_y - start_y) * ratio

                if self.direct_input:
                    pydirectinput.moveTo(int(cur_x), int(cur_y))
                else:
                    _mouse_controller.position = (int(cur_x), int(cur_y))

                self._fail_safe_check()
                time.sleep(0.005)

            if self.direct_input:
                pydirectinput.moveTo(int(dest_x), int(dest_y))
            else:
                _mouse_controller.position = (dest_x, dest_y)
            self._fail_safe_check()

    def click(self, target=None, y=None, offset=(0, 0), button='left', clicks=1, interval=0.2, hold_time=0):
        self._fail_safe_check()

        if isinstance(target, list):
            if DEBUG_LEVEL >= 1: print(f"Debug: Processing list of {len(target)} matches.")
            for item in target:
                self.click(item, offset=offset, button=button, clicks=clicks, interval=interval, hold_time=hold_time)
                time.sleep(interval)
            return

        pynput_button = Button.left
        if button == 'right':
            pynput_button = Button.right
        elif button == 'middle':
            pynput_button = Button.middle

        if target is None:
            if offset != (0, 0):
                cur_x, cur_y = _mouse_controller.position
                if self.direct_input:
                    pydirectinput.moveTo(int(cur_x + offset[0]), int(cur_y + offset[1]))
                else:
                    _mouse_controller.position = (cur_x + offset[0], cur_y + offset[1])
                time.sleep(0.025)

            self._fail_safe_check()
            if self.direct_input:
                for i in range(clicks):
                    pydirectinput.mouseDown(button=button)
                    if hold_time > 0:
                        time.sleep(hold_time)
                    pydirectinput.mouseUp(button=button)
                    if i < clicks - 1:
                        time.sleep(interval)
            else:
                _mouse_controller.click(pynput_button, clicks)
            return

        if isinstance(target, (int, float)) and isinstance(y, (int, float)):
            local_target_x = target
            local_target_y = y

        elif isinstance(target, (tuple, list)):
            if len(target) == 2:
                local_target_x, local_target_y = target
            elif len(target) == 4:
                mx, my, mw, mh = target
                local_target_x = mx + (mw / 2)
                local_target_y = my + (mh / 2)
            else:
                if DEBUG_LEVEL >= 1: print(f"Debug: Invalid tuple length {len(target)}, skipping.")
                return
        else:
            if DEBUG_LEVEL >= 1: print("Debug: Invalid target format, skipping.")
            return

        local_target_x += offset[0]
        local_target_y += offset[1]

        physical_screen = _resolve_screen(self._screen)
        monitors = get_monitors_safe()

        if physical_screen >= len(monitors):
            physical_screen = 0

        monitor_left, monitor_top, _, _ = monitors[physical_screen]

        global_target_x = monitor_left + local_target_x
        global_target_y = monitor_top + local_target_y

        self._fail_safe_check()

        if self.direct_input:
            pydirectinput.moveTo(int(global_target_x), int(global_target_y))
            for i in range(clicks):
                pydirectinput.mouseDown(button=button)
                if hold_time > 0:
                    time.sleep(hold_time)
                pydirectinput.mouseUp(button=button)
                if i < clicks - 1:
                    time.sleep(interval)
        else:
            _mouse_controller.position = (global_target_x, global_target_y)
            _mouse_controller.click(pynput_button, clicks)

    def write(self, message, interval=0.0):
        self._fail_safe_check()

        if self.direct_input:
            pydirectinput.write(message, interval=interval)
        elif interval == 0:
            _keyboard_controller.type(message)
        else:
            for char in message:
                self._fail_safe_check()
                _keyboard_controller.type(char)
                time.sleep(interval)

    def press(self, key):
        self._fail_safe_check()

        if self.direct_input:
            k = key
            if isinstance(key, Key):
                k = key.name
            pydirectinput.press(k)
        else:
            pynput_key = key
            if isinstance(key, str) and len(key) > 1:
                if hasattr(Key, key):
                    pynput_key = getattr(Key, key)

            _keyboard_controller.tap(pynput_key)

    def locateAny(self, tasks, time_out=0):
        start_time = time.time()

        while True:
            for task in tasks:
                if not isinstance(task, dict):
                    continue

                if 'task' in task and isinstance(task['task'], dict):
                    search_args = task['task']

                elif 'params' in task and isinstance(task['params'], dict):
                    search_args = task['params']

                else:
                    search_args = task.copy()
                    if 'label' in search_args:
                        del search_args['label']

                label = task.get('label', 'match')

                match = self.locateOnScreen(**search_args)

                if match:
                    return (label, match)

            if time.time() - start_time > time_out:
                break
            time.sleep(0.01)
        return None

    def locateAll(self, tasks, time_out=0):
        results = {}
        # Pre-fill results keys
        for task in tasks:
            if isinstance(task, dict):
                label = task.get('label', 'unknown')
                results[label] = None

        start_time = time.time()

        while True:
            all_found = True

            for task in tasks:
                if not isinstance(task, dict):
                    continue

                label = task.get('label', 'unknown')
                if results[label] is not None:
                    continue

                all_found = False
                if 'task' in task and isinstance(task['task'], dict):
                    search_args = task['task']
                elif 'params' in task and isinstance(task['params'], dict):
                    search_args = task['params']
                else:
                    search_args = task.copy()
                    if 'label' in search_args:
                        del search_args['label']
                matches = self.locateAllOnScreen(**search_args)

                if matches:
                    results[label] = matches

            if all_found:
                break

            if time.time() - start_time > time_out:
                break
            time.sleep(0.01)

        return results