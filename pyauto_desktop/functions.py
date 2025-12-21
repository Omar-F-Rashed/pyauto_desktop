import concurrent.futures
import time
from collections import defaultdict

import cv2
import numpy as np
from PIL import Image, ImageGrab
from pynput.mouse import Button, Controller
import platform
import ctypes
from screeninfo import get_monitors


# Initialize the controller once to save performance
_mouse_controller = Controller()
# --- Screen Routing & Configuration ---
# Maps Logical Screen Index (Script) -> Physical Screen Index (Hardware)
_SCREEN_ROUTER = {}


def route_screen(logical_screen, physical_screen):
    """
    Redirects searches intended for 'logical_screen' to 'physical_screen'.
    Useful when a script written for Screen 1 needs to run on Screen 0.
    Example: route_screen(source=1, target=0)
    """
    _SCREEN_ROUTER[logical_screen] = physical_screen


def _resolve_screen(screen_idx):
    """Resolves logical screen index to physical index."""
    return _SCREEN_ROUTER.get(screen_idx, screen_idx)


def get_monitors_safe():
    """
    Returns a list of bounding boxes (x, y, w, h) for all connected monitors.
    THIS IS THE SINGLE SOURCE OF TRUTH for both the GUI and the Runtime.
    """
    monitors = []

    # Priority 1: Use screeninfo (Recommended)
    if get_monitors:
        try:
            # We trust the order returned by screeninfo implicitly.
            si_monitors = get_monitors()
            for m in si_monitors:
                monitors.append((m.x, m.y, m.width, m.height))
            return monitors
        except Exception as e:
            print(f"screeninfo error: {e}")

    # Priority 2: Windows Fallback (ctypes)
    if not monitors and platform.system() == "Windows":
        try:
            user32 = ctypes.windll.user32

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT),
                                                 ctypes.c_double)

            def _monitor_enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
                r = lprcMonitor.contents
                monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
                return True

            user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_monitor_enum_proc), 0)
        except Exception:
            pass

    # Priority 3: Last Resort (Virtual Desktop)
    if not monitors:
        try:
            img = ImageGrab.grab()
            monitors.append((0, 0, img.width, img.height))
        except Exception:
            monitors.append((0, 0, 1920, 1080))

    return monitors


def _resize_template(needle_pil, scale_factor):
    """Resizes the needle image by the scale factor using Lanczos resampling."""
    if scale_factor == 1.0:
        return needle_pil

    w, h = needle_pil.size
    new_w = int(max(1, w * scale_factor))
    new_h = int(max(1, h * scale_factor))
    return needle_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)


def _load_image(img):
    """Helper to load image from path or PIL Image."""
    if isinstance(img, str):
        return Image.open(img)
    return img


def _non_max_suppression(boxes, overlap_thresh):
    """
    Standard Non-Maximum Suppression (NMS) to remove overlapping bounding boxes.
    """
    if len(boxes) == 0:
        return []

    boxes = np.array(boxes, dtype=np.float32)

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 0] + boxes[:, 2]
    y2 = boxes[:, 1] + boxes[:, 3]

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

        idxs = np.delete(idxs, np.concatenate(([last],
                                               np.where(overlap > overlap_thresh)[0])))

    return boxes[pick].astype("int").tolist()


def _run_template_match(needleImage, haystackImage, grayscale=False):
    """
    Shared logic for preparing images and running cv2.matchTemplate.
    """
    haystack_pil = _load_image(haystackImage)
    haystack_np = np.array(haystack_pil)

    if haystack_pil.mode == 'RGB':
        haystack = cv2.cvtColor(haystack_np, cv2.COLOR_RGB2BGR)
    elif haystack_pil.mode == 'RGBA':
        haystack = cv2.cvtColor(haystack_np, cv2.COLOR_RGBA2BGR)
    else:
        haystack = haystack_np
        if len(haystack.shape) == 2:
            haystack = cv2.cvtColor(haystack, cv2.COLOR_GRAY2BGR)

    needle_pil = _load_image(needleImage)
    needle_np = np.array(needle_pil)
    mask = None

    if needle_pil.mode == 'RGBA':
        needle_bgra = cv2.cvtColor(needle_np, cv2.COLOR_RGBA2BGRA)
        needle = needle_bgra[:, :, :3]
        mask = needle_bgra[:, :, 3]
    else:
        if needle_pil.mode == 'RGB':
            needle = cv2.cvtColor(needle_np, cv2.COLOR_RGB2BGR)
        else:
            needle = needle_np
            if len(needle.shape) == 2:
                needle = cv2.cvtColor(needle, cv2.COLOR_GRAY2BGR)

    if grayscale:
        haystack = cv2.cvtColor(haystack, cv2.COLOR_BGR2GRAY)
        needle = cv2.cvtColor(needle, cv2.COLOR_BGR2GRAY)

    if mask is not None and not grayscale:
        res = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED, mask=mask)
    else:
        res = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)

    h, w = needle.shape[:2]
    return res, w, h




def locateAll(needleImage, haystackImage, grayscale=False, confidence=0.9, overlap_threshold=0.5):
    """
    Locate all instances of 'needleImage' inside 'haystackImage'.
    """
    res, w, h = _run_template_match(needleImage, haystackImage, grayscale)

    loc = np.where(res >= confidence)
    rects = []
    for pt in zip(*loc[::-1]):
        rects.append([int(pt[0]), int(pt[1]), int(w), int(h)])

    if overlap_threshold < 1.0 and len(rects) > 1:
        rects = _non_max_suppression(rects, overlap_threshold)

    rects.sort(key=lambda r: (r[1], r[0]))

    return [tuple(r) for r in rects]


def locateAllOnScreen(image, region=None, screen=0, grayscale=False, confidence=0.9, overlap_threshold=0.5,
                      original_resolution=None):
    """
    Locate all instances of 'image' on the screen.
    """
    haystack_pil, offset_x, offset_y, scale_factor = _prepare_screen_capture(region, screen, original_resolution)
    needle_pil = _load_image(image)
    if scale_factor != 1.0:
        needle_pil = _resize_template(needle_pil, scale_factor)

    rects = locateAll(needle_pil, haystack_pil, grayscale, confidence, overlap_threshold)

    if offset_x or offset_y:
        final_rects = []
        for (x, y, w, h) in rects:
            final_rects.append((x + offset_x, y + offset_y, w, h))
        return final_rects

    return rects


def locateOnScreen(image, region=None, screen=0, grayscale=False, confidence=0.9,
                   original_resolution=None):
    """
    Locate the first instance of 'image' on the screen.
    """
    # 1. Prepare screen and image (Same as your existing functions)
    haystack_pil, offset_x, offset_y, scale_factor = _prepare_screen_capture(region, screen, original_resolution)
    needle_pil = _load_image(image)
    if scale_factor != 1.0:
        needle_pil = _resize_template(needle_pil, scale_factor)

    # 2. Get raw matches (Generator or List)
    # We use locateAll because it returns results sorted by position (top-left to bottom-right)
    # whereas locate() returns results sorted by confidence.
    rects = locateAll(needle_pil, haystack_pil, grayscale, confidence)

    # 3. OPTIMIZATION: Extract only the first item immediately
    # This works whether 'rects' is a list or a generator
    try:
        first_match = next(iter(rects))
    except StopIteration:
        return None  # No matches found

    # 4. Apply offset ONLY to the first match
    # (Your original function applied this math to every single match found)
    x, y, w, h = first_match
    return (x + offset_x, y + offset_y, w, h)


def _prepare_screen_capture(region, screen_idx, original_resolution):
    # 1. Routing & Monitor Info
    physical_screen = _resolve_screen(screen_idx)
    monitors = get_monitors_safe()

    # Fallback to Primary if screen doesn't exist
    if physical_screen >= len(monitors):
        physical_screen = 0

    # Get the Global X/Y where this specific monitor starts
    monitor_left, monitor_top, monitor_width, monitor_height = monitors[physical_screen]

    # 2. CALCULATE CAPTURE AREA (The Math)
    if region:
        # User provided local region (x, y, w, h)
        local_x, local_y, local_w, local_h = region

        # CALCULATION:
        # Global X = Monitor Global Start + Local Region Start
        # Global Y = Monitor Global Start + Local Region Start
        capture_left = monitor_left + local_x
        capture_top = monitor_top + local_y

        # The Bottom-Right is simply the Start + Width/Height
        capture_right = capture_left + local_w
        capture_bottom = capture_top + local_h

        # Store these for later so we know where to click
        offset_x = capture_left
        offset_y = capture_top
    else:
        # No region? Capture the full monitor.
        capture_left = monitor_left
        capture_top = monitor_top
        capture_right = monitor_left + monitor_width
        capture_bottom = monitor_top + monitor_height

        offset_x, offset_y = monitor_left, monitor_top

    # 3. EFFICIENT CAPTURE
    # We ask the OS for ONLY the specific rectangle we calculated.
    try:
        haystack_pil = ImageGrab.grab(bbox=(capture_left, capture_top, capture_right, capture_bottom), all_screens=True)
    except TypeError:
        # Fallback for older Pillow versions that don't support 'all_screens'
        print("You have an old Pillow version that doesn't support secondary screens, upgrade or"
              " you wont be able to detect except in primary screen.")
        haystack_pil = ImageGrab.grab(bbox=(capture_left, capture_top, capture_right, capture_bottom))

    # haystack_pil.save('test.png')
    # 4. Scaling (Standard)

    scale_factor = 1.0
    if original_resolution:
        orig_w, orig_h = original_resolution
        scale_factor = monitor_height / float(orig_h)
        if abs(scale_factor - 1.0) < 0.02:
            scale_factor = 1.0

    return haystack_pil, offset_x, offset_y, scale_factor

def clickimage(match, offset=(0, 0), button='left', clicks=1):
    """
    Clicks a location with an optional offset using pynput.
    """
    if not match:
        print("Debug: No match found, skipping click.")
        return

    x, y, w, h = match
    center_x = x + (w / 2)
    center_y = y + (h / 2)
    target_x = center_x + offset[0]
    target_y = center_y + offset[1]

    _mouse_controller.position = (target_x, target_y)

    pynput_button = Button.left
    if button == 'right':
        pynput_button = Button.right
    elif button == 'middle':
        pynput_button = Button.middle

    _mouse_controller.click(pynput_button, clicks)


def _parse_task(task, default_screen=0):
    """
    Normalizes task into:
    {'label': str, 'image': str, 'region': tuple/None, 'confidence': float, 'screen': int}
    """
    defaults = {'region': None, 'confidence': 0.9, 'screen': default_screen, 'grayscale': True}

    if isinstance(task, dict):
        base = defaults.copy()
        base.update(task)
        return base


    raise ValueError(f"Invalid task format: {task}")

def locate_any(tasks, timeout=5, default_screen=0):
    parsed_tasks = [_parse_task(t, default_screen) for t in tasks]

    start_time = time.time()

    # --------------------------------------------------
    # FAST PROBE (single-pass, sequential)
    # --------------------------------------------------
    for t in parsed_tasks:
        match = locateOnScreen(
            image=t['image'],
            region=t['region'],
            screen=t['screen'],
            grayscale=t['grayscale'],
            confidence=t['confidence']
        )
        if match:
            return (t['label'], match)

    # No waiting requested
    if timeout <= 0:
        return None

    # --------------------------------------------------
    # WAIT MODE
    # --------------------------------------------------
    while True:
        for t in parsed_tasks:
            match = locateOnScreen(
                image=t['image'],
                region=t['region'],
                screen=t['screen'],
                grayscale=t['grayscale'],
                confidence=t['confidence']
            )
            if match:
                return (t['label'], match)
        if time.time() - start_time > timeout:
            break

        # Small sleep to avoid hammering the compositor
        time.sleep(0.01)

    return None



def locate_all(tasks, timeout=0, default_screen=0):
    parsed_tasks = [_parse_task(t, default_screen) for t in tasks]
    results = {t['label']: None for t in parsed_tasks}

    start_time = time.time()

    # --------------------------------------------------
    # FAST PROBE (single-pass)
    # --------------------------------------------------
    for t in parsed_tasks:
        matches = locateAllOnScreen(
            image=t['image'],
            region=t['region'],
            screen=t['screen'],
            grayscale=t['grayscale'],
            confidence=t['confidence']
        )
        if matches:
            results[t['label']] = matches

    # If no waiting requested or everything found
    if timeout <= 0 or all(results.values()):
        return results

    # --------------------------------------------------
    # WAIT MODE
    # --------------------------------------------------
    while True:
        for t in parsed_tasks:
            if results[t['label']] is not None:
                continue

            matches = locateAllOnScreen(
                image=t['image'],
                region=t['region'],
                screen=t['screen'],
                grayscale=t['grayscale'],
                confidence=t['confidence']
            )
            if matches:
                results[t['label']] = matches

        if all(results.values()):
            break

        if time.time() - start_time > timeout:
            break

        time.sleep(0.01)

    return results
