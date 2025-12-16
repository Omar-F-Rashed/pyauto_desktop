import cv2
import numpy as np
from PIL import Image, ImageGrab


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

    return [tuple(r) for r in rects]


def locateAllOnScreen(image, region=None, grayscale=False, confidence=0.9, overlap_threshold=0.5):
    """
    Locate all instances of 'image' on the screen.
    Uses locateAll() internally after grabbing the screenshot.
    """
    # 1. Capture Screenshot
    if region:
        x, y, w, h = region
        haystack_pil = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    else:
        haystack_pil = ImageGrab.grab()

    # 2. Call the core logic
    rects = locateAll(image, haystack_pil, grayscale, confidence, overlap_threshold)

    # Apply region offset if necessary
    if region:
        rx, ry, _, _ = region
        final_rects = []
        for (x, y, w, h) in rects:
            final_rects.append((x + rx, y + ry, w, h))
        return final_rects

    return rects


def locateOnScreen(image, region=None, grayscale=False, confidence=0.9, overlap_threshold=0.5):
    """
    Locate the best instance of 'image' on the screen.
    Uses the optimized locate() function.
    Returns (x, y, w, h) or None.
    """
    # 1. Capture Screenshot
    if region:
        x, y, w, h = region
        haystack_pil = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    else:
        haystack_pil = ImageGrab.grab()

    # 2. Call optimized single-result logic
    # Note: overlap_threshold is ignored as we are only looking for one result
    result = locate(image, haystack_pil, grayscale, confidence)

    if result and region:
        rx, ry, _, _ = region
        x, y, w, h = result
        return (x + rx, y + ry, w, h)

    return result