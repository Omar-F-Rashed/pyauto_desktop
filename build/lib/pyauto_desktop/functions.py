import cv2
import numpy as np
from PIL import Image, ImageGrab
from pynput.mouse import Button, Controller
import platform
import ctypes

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


def _get_monitors_safe():
    """
    Returns a list of bounding boxes (x, y, w, h) for all connected monitors
    in virtual screen coordinates.
    """
    monitors = []

    if platform.system() == "Windows":
        try:
            user32 = ctypes.windll.user32

            # Define necessary ctypes for EnumDisplayMonitors
            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT),
                                                 ctypes.c_double)

            def _monitor_enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
                r = lprcMonitor.contents
                # Convert RECT to (x, y, w, h)
                monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
                return True

            user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_monitor_enum_proc), 0)
        except Exception:
            pass

    # Fallback: Treat the whole virtual desktop as one screen
    if not monitors:
        try:
            # Helper to get full virtual size if possible, or just primary
            # ImageGrab.grab() grabs all screens on Windows usually
            img = ImageGrab.grab()
            monitors.append((0, 0, img.width, img.height))
        except Exception:
            monitors.append((0, 0, 1920, 1080))  # Last resort fallback

    # Sort by X coordinate (Left to Right)
    monitors.sort(key=lambda m: m[0])
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
    boxes: List of (x, y, w, h)
    overlap_thresh: Float (0.0 to 1.0)
    """
    if len(boxes) == 0:
        return []

    # Convert to float numpy array for calculations
    boxes = np.array(boxes, dtype=np.float32)

    # Convert to [x1, y1, x2, y2] for NMS logic
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

    # Return as integers (x, y, w, h)
    return boxes[pick].astype("int").tolist()


def _run_template_match(needleImage, haystackImage, grayscale=False):
    """
    Shared logic for preparing images and running cv2.matchTemplate.
    Returns (result_matrix, needle_width, needle_height).
    """
    # 1. Prepare Haystack
    haystack_pil = _load_image(haystackImage)
    haystack_np = np.array(haystack_pil)

    # Handle RGB vs BGR (OpenCV uses BGR)
    if haystack_pil.mode == 'RGB':
        haystack = cv2.cvtColor(haystack_np, cv2.COLOR_RGB2BGR)
    elif haystack_pil.mode == 'RGBA':
        haystack = cv2.cvtColor(haystack_np, cv2.COLOR_RGBA2BGR)
    else:
        # Grayscale or other
        haystack = haystack_np
        if len(haystack.shape) == 2:
            haystack = cv2.cvtColor(haystack, cv2.COLOR_GRAY2BGR)

    # 2. Prepare Needle (Template)
    needle_pil = _load_image(needleImage)
    needle_np = np.array(needle_pil)

    needle = None
    mask = None

    # Handle Alpha Channel in Template
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

    # 3. Grayscale Option
    if grayscale:
        haystack = cv2.cvtColor(haystack, cv2.COLOR_BGR2GRAY)
        needle = cv2.cvtColor(needle, cv2.COLOR_BGR2GRAY)

    # 4. Match
    if mask is not None and not grayscale:
        res = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED, mask=mask)
    else:
        res = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)

    h, w = needle.shape[:2]
    return res, w, h


def locate(needleImage, haystackImage, grayscale=False, confidence=0.9):
    """
    Locate the BEST instance of 'needleImage' inside 'haystackImage'.
    Uses cv2.minMaxLoc for efficiency (avoids processing all matches).
    Returns (x, y, w, h) or None.
    """
    res, w, h = _run_template_match(needleImage, haystackImage, grayscale)

    # Efficiently find the single global maximum (best match)
    minVal, maxVal, minLoc, maxLoc = cv2.minMaxLoc(res)

    if maxVal >= confidence:
        return (maxLoc[0], maxLoc[1], w, h)

    return None


def locateAll(needleImage, haystackImage, grayscale=False, confidence=0.9, overlap_threshold=0.5):
    """
    Locate all instances of 'needleImage' inside 'haystackImage'.
    """
    res, w, h = _run_template_match(needleImage, haystackImage, grayscale)

    # Filter by Confidence
    loc = np.where(res >= confidence)

    rects = []
    # loc is (y_indices, x_indices)
    for pt in zip(*loc[::-1]):
        rects.append([int(pt[0]), int(pt[1]), int(w), int(h)])

    # Non-Max Suppression
    if overlap_threshold < 1.0 and len(rects) > 1:
        rects = _non_max_suppression(rects, overlap_threshold)

    # --- FIX: Sort results to ensure Top-Left -> Bottom-Right ordering ---
    # NMS can scramble order, so we force a sort by Y (row), then X (col).
    rects.sort(key=lambda r: (r[1], r[0]))

    return [tuple(r) for r in rects]


def locateAllOnScreen(image, region=None, screen=0, grayscale=False, confidence=0.9, overlap_threshold=0.5,
                      original_resolution=None):
    """
    Locate all instances of 'image' on the screen with smart resolution scaling and routing.

    Args:
        screen (int): Logical screen index (default 0).
        original_resolution (tuple): (width, height) of the monitor where image was captured.
    """
    # 1. Resolve Screen & Capture
    haystack_pil, offset_x, offset_y, scale_factor = _prepare_screen_capture(region, screen, original_resolution)

    # 2. Resize Needle if needed
    needle_pil = _load_image(image)
    if scale_factor != 1.0:
        needle_pil = _resize_template(needle_pil, scale_factor)

    # 3. Call core logic
    rects = locateAll(needle_pil, haystack_pil, grayscale, confidence, overlap_threshold)

    # 4. Adjust Coordinates (Offset)
    if offset_x or offset_y:
        final_rects = []
        for (x, y, w, h) in rects:
            final_rects.append((x + offset_x, y + offset_y, w, h))
        return final_rects

    return rects


def locateOnScreen(image, region=None, screen=0, grayscale=False, confidence=0.9, overlap_threshold=0.5,
                   original_resolution=None):
    """
    Locate the best instance of 'image' on the screen with smart resolution scaling and routing.

    Args:
        screen (int): Logical screen index (default 0).
        original_resolution (tuple): (width, height) of the monitor where image was captured.
    """
    # 1. Resolve Screen & Capture
    haystack_pil, offset_x, offset_y, scale_factor = _prepare_screen_capture(region, screen, original_resolution)

    # 2. Resize Needle if needed
    needle_pil = _load_image(image)
    if scale_factor != 1.0:
        needle_pil = _resize_template(needle_pil, scale_factor)

    # 3. Call optimized single-result logic
    result = locate(needle_pil, haystack_pil, grayscale, confidence)

    if result:
        x, y, w, h = result
        return (x + offset_x, y + offset_y, w, h)

    return result


def _prepare_screen_capture(region, screen_idx, original_resolution):
    """
    Internal helper to handle:
    1. Virtual Screen Routing (Person A vs Person B)
    2. Monitor Geometries
    3. Scale Factor Calculation

    Returns: (haystack_pil, offset_x, offset_y, scale_factor)
    """
    # 1. Routing
    physical_screen = _resolve_screen(screen_idx)
    monitors = _get_monitors_safe()

    # Safety Fallback
    if physical_screen >= len(monitors):
        print(f"Warning: Screen {physical_screen} not found. Falling back to Primary (0).")
        physical_screen = 0

    target_monitor_rect = monitors[physical_screen]

    # 2. Determine Capture Area
    offset_x, offset_y = 0, 0

    if region:
        # User specified a global region
        x, y, w, h = region
        haystack_pil = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        offset_x, offset_y = x, y
    else:
        # Full Monitor
        x, y, w, h = target_monitor_rect
        haystack_pil = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        offset_x, offset_y = x, y

    # 3. Determine Scale Factor
    scale_factor = 1.0

    if original_resolution:
        # Scale based on HEIGHT ratio of the MONITOR (not the region)
        # This assumes UI scaling is consistent across the monitor
        orig_w, orig_h = original_resolution
        target_monitor_h = target_monitor_rect[3]

        # Calculate ratio
        scale_factor = target_monitor_h / float(orig_h)

        # Ignore negligible differences (floating point noise)
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

    # 1. Calculate Center
    center_x = x + (w / 2)
    center_y = y + (h / 2)

    # 2. Apply Offset
    target_x = center_x + offset[0]
    target_y = center_y + offset[1]

    # 3. Move
    _mouse_controller.position = (target_x, target_y)

    # 4. Determine Button
    pynput_button = Button.left
    if button == 'right':
        pynput_button = Button.right
    elif button == 'middle':
        pynput_button = Button.middle

    # 5. Click
    _mouse_controller.click(pynput_button, clicks)