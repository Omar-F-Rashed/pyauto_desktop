# Updated import to point to the new 'functions.py' inside the package
from . import functions as pyauto_desktop
from PyQt6.QtCore import QThread, pyqtSignal
import traceback
from PIL import Image


class DetectionWorker(QThread):
    """
    One-shot thread for image recognition.
    Accepts a 'Haystack' image to search within, ensuring
    consistent coordinate mapping regardless of screen configuration.
    Supports optional 'Anchor' logic: Find Anchor -> Define Region -> Find Target.
    """
    # Updated Signal: (target_rects, anchor_rects, search_regions, count)
    result_signal = pyqtSignal(list, list, list, int)

    def __init__(self, template_img, haystack_img, confidence, grayscale, overlap_threshold=0.5,
                 anchor_img=None, anchor_config=None):
        super().__init__()
        self.template_img = template_img
        self.haystack_img = haystack_img
        self.confidence = confidence
        self.grayscale = grayscale
        self.overlap_threshold = overlap_threshold

        # Anchor support
        self.anchor_img = anchor_img
        self.anchor_config = anchor_config  # {'offset_x', 'offset_y', 'w', 'h'}

    def run(self):
        try:
            final_rects = []
            found_anchors = []
            scanned_regions = []

            # Resolve template dimensions for validation
            # This ensures we don't try to search in regions smaller than the template
            templ_w, templ_h = 0, 0
            if isinstance(self.template_img, str):
                try:
                    with Image.open(self.template_img) as img:
                        templ_w, templ_h = img.size
                except Exception:
                    pass # Let locateAll handle file errors later
            elif hasattr(self.template_img, 'size'):
                templ_w, templ_h = self.template_img.size

            if self.anchor_img and self.anchor_config:
                # --- ANCHOR MODE ---
                # 1. Find all instances of the anchor
                anchors_iter = pyauto_desktop.locateAll(
                    needleImage=self.anchor_img,
                    haystackImage=self.haystack_img,
                    grayscale=self.grayscale,
                    confidence=self.confidence,
                    overlap_threshold=self.overlap_threshold
                )

                # Convert to list to iterate and store
                anchors_list = list(anchors_iter)
                found_anchors = anchors_list  # Pass these back for visualization

                # 2. For each anchor, define a region and search for the target
                haystack_w, haystack_h = self.haystack_img.size

                # Get margins from config, default to 0
                margin_x = self.anchor_config.get('margin_x', 0)
                margin_y = self.anchor_config.get('margin_y', 0)

                for (ax, ay, aw, ah) in anchors_list:
                    # Calculate Search Region relative to this anchor match
                    # The config offsets are relative to the anchor's top-left

                    # Target's expected top-left
                    target_x = ax + self.anchor_config['offset_x']
                    target_y = ay + self.anchor_config['offset_y']

                    # Apply margins to define the search bounds
                    region_x = target_x - margin_x
                    region_y = target_y - margin_y
                    region_w = self.anchor_config['w'] + (margin_x * 2)
                    region_h = self.anchor_config['h'] + (margin_y * 2)

                    # Clip region to haystack bounds to prevent errors
                    rx = max(0, int(region_x))
                    ry = max(0, int(region_y))
                    # If region starts outside, skip
                    if rx >= haystack_w or ry >= haystack_h:
                        continue

                    # Ensure width/height don't go out of bounds
                    # Calculate how much of the requested width is available
                    available_w = haystack_w - rx
                    available_h = haystack_h - ry

                    rw = min(int(region_w), available_w)
                    rh = min(int(region_h), available_h)

                    if rw <= 0 or rh <= 0:
                        continue

                    # --- SAFETY CHECK ---
                    # If the cropped region is smaller than the template, OpenCV will crash.
                    # We must skip these invalid regions.
                    if templ_w > 0 and templ_h > 0:
                        if rw < templ_w or rh < templ_h:
                            # print(f"Debug: Region {rw}x{rh} too small for template {templ_w}x{templ_h}, skipping.")
                            continue
                    # --------------------

                    # Add to scanned regions for visualization
                    scanned_regions.append((rx, ry, rw, rh))

                    # Crop the haystack to this region
                    crop = self.haystack_img.crop((rx, ry, rx + rw, ry + rh))

                    # Search for target in the crop
                    targets = pyauto_desktop.locateAll(
                        needleImage=self.template_img,
                        haystackImage=crop,
                        grayscale=self.grayscale,
                        confidence=self.confidence,
                        overlap_threshold=self.overlap_threshold
                    )

                    targets_list = list(targets)
                    # Map back to main haystack coordinates
                    # tx, ty are relative to the crop (rx, ry)
                    for (tx, ty, tw, th) in targets_list:
                        final_rects.append((rx + tx, ry + ty, tw, th))

            else:
                # --- STANDARD MODE ---
                rects = pyauto_desktop.locateAll(
                    needleImage=self.template_img,
                    haystackImage=self.haystack_img,
                    grayscale=self.grayscale,
                    confidence=self.confidence,
                    overlap_threshold=self.overlap_threshold
                )
                final_rects = list(rects)

            # Result rects are (x, y, w, h) relative to the Haystack Image (Physical Pixels)
            self.result_signal.emit(final_rects, found_anchors, scanned_regions, len(final_rects))

        except Exception as e:
            print(f"Error in detection worker: {e}")
            traceback.print_exc()
            self.result_signal.emit([], [], [], 0)