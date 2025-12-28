from . import functions as pyauto_desktop
from .functions import _resolve_screen
from PyQt6.QtCore import QThread, pyqtSignal
import traceback
from PIL import Image
from .utils import global_to_local, local_to_global


class DetectionWorker(QThread):
    result_signal = pyqtSignal(list, list, list, int)

    def __init__(self, template_img, screen_idx, confidence, grayscale, overlap_threshold=0.5,
                 anchor_img=None, anchor_config=None, search_region=None,
                 source_dpr=1.0, source_resolution=None, scaling_type='dpr'):
        super().__init__()
        self.template_img = template_img
        self.screen_idx = screen_idx
        self.confidence = confidence
        self.grayscale = grayscale
        self.overlap_threshold = overlap_threshold
        self.search_region = search_region
        self.anchor_img = anchor_img
        self.anchor_config = anchor_config
        self.source_dpr = source_dpr
        self.source_resolution = source_resolution
        self.scaling_type = scaling_type

    def run(self):
        try:
            final_rects = []
            found_anchors = []
            scanned_regions = []
            monitors = pyauto_desktop.get_monitors_safe()

            session = pyauto_desktop.Session(
                screen=self.screen_idx,
                source_resolution=self.source_resolution,
                source_dpr=self.source_dpr
            )

            if self.screen_idx < len(monitors):
                selected_screen = monitors[self.screen_idx]
            else:
                print(f"Error in detection worker: screen {self.screen_idx}: out of bounds")
                traceback.print_exc()
                self.result_signal.emit([], [], [], 0)
                return

            target_dpr = pyauto_desktop.get_monitor_dpr(self.screen_idx, monitors)
            scale_x = 1.0
            scale_y = 1.0

            if self.scaling_type == 'dpr':
                if self.source_dpr and target_dpr:
                    ratio = target_dpr / self.source_dpr
                    scale_x = ratio
                    scale_y = ratio
            elif self.scaling_type == 'resolution':
                if self.source_resolution:
                    sr_w, sr_h = self.source_resolution
                    tr_w, tr_h = selected_screen[2], selected_screen[3]
                    if sr_w > 0 and sr_h > 0:
                        scale_x = tr_w / sr_w
                        scale_y = tr_h / sr_h

            if self.anchor_img and self.anchor_config:
                anchors_iter = session.locateAllOnScreen(
                    image=self.anchor_img,
                    grayscale=self.grayscale,
                    confidence=self.confidence,
                    overlap_threshold=self.overlap_threshold,
                    region=self.search_region,
                    scaling_type=self.scaling_type
                )

                anchors_list = list(anchors_iter)
                found_anchors = anchors_list
                margin_x = self.anchor_config.get('margin_x', 0)
                margin_y = self.anchor_config.get('margin_y', 0)

                for (ax, ay, aw, ah) in anchors_list:
                    rel_rect_with_margin = global_to_local(
                        (self.anchor_config['offset_x'], self.anchor_config['offset_y'], 0, 0),
                        (margin_x, margin_y)
                    )
                    region_x, region_y, _, _ = local_to_global(
                        rel_rect_with_margin, (ax, ay)
                    )

                    region_w = self.anchor_config['w'] + (margin_x * 2)
                    region_h = self.anchor_config['h'] + (margin_y * 2)
                    if region_w <= 0 or region_h <= 0:
                        continue

                    scanned_regions.append((region_x, region_y, region_w, region_h))
                    mx, my, mw, mh = selected_screen
                    local_search_region = global_to_local(
                        (region_x, region_y, region_w, region_h), (mx, my)
                    )

                    targets = session.locateAllOnScreen(
                        image=self.template_img,
                        region=local_search_region,
                        grayscale=self.grayscale,
                        confidence=self.confidence,
                        overlap_threshold=self.overlap_threshold,
                        scaling_type=self.scaling_type
                    )
                    for rect in targets:
                        final_rects.append(rect)
                    final_rects.extend(list(targets))

            else:
                if self.search_region:
                    rx, ry, rw, rh = self.search_region
                    scaled_region = (
                        int(rx * scale_x),
                        int(ry * scale_y),
                        int(rw * scale_x),
                        int(rh * scale_y)
                    )
                    scanned_regions.append(scaled_region)

                rects = session.locateAllOnScreen(
                    image=self.template_img,
                    region=self.search_region,
                    grayscale=self.grayscale,
                    confidence=self.confidence,
                    overlap_threshold=self.overlap_threshold,
                    scaling_type=self.scaling_type
                )
                final_rects = rects

            self.result_signal.emit(final_rects, found_anchors, scanned_regions, len(final_rects))

        except Exception as e:
            print(f"Error in detection worker: {e}")
            traceback.print_exc()
            self.result_signal.emit([], [], [], 0)