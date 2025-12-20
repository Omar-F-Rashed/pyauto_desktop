from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont


class Overlay(QWidget):
    """Transparent overlay to draw bounding boxes and click targets."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool |
                            Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Track the top-left corner of the specific screen we are detecting on
        self.target_offset_x = 0
        self.target_offset_y = 0

        # Click Visualization Settings
        self.show_click = False
        self.click_offset_x = 0
        self.click_offset_y = 0

        # Calculate bounding box to cover all screens
        self._update_geometry()

        self.rects = []
        self.anchors = []  # Store anchor rects separately
        self.regions = []  # Store search regions
        self.scale_factor = 1.0

        # Font for indices
        self.font_idx = QFont("Arial", 10, QFont.Weight.Bold)

    def _update_geometry(self):
        """Recalculate overlay geometry to cover all screens."""
        screens = QApplication.screens()
        if screens:
            full_rect = screens[0].geometry()
            for screen in screens[1:]:
                full_rect = full_rect.united(screen.geometry())
            self.setGeometry(full_rect)
        else:
            self.setGeometry(QApplication.primaryScreen().geometry())

    def showEvent(self, event):
        super().showEvent(event)
        self._update_geometry()

    def set_target_screen_offset(self, x, y):
        self.target_offset_x = x
        self.target_offset_y = y

    def set_click_config(self, show, off_x, off_y):
        self.show_click = show
        self.click_offset_x = off_x
        self.click_offset_y = off_y
        self.update()

    def update_rects(self, rects, anchors, regions, scale_factor):
        self.rects = rects
        self.anchors = anchors
        self.regions = regions
        self.scale_factor = scale_factor
        self.update()

    def paintEvent(self, event):
        if not self.rects and not self.anchors and not self.regions:
            return

        try:
            painter = QPainter(self)
            painter.setFont(self.font_idx)

            # --- Styles ---
            # Target (Green)
            pen_box = QPen(QColor(0, 255, 0), 2)
            brush_box = QColor(0, 255, 0, 50)

            # Anchor (Blue)
            pen_anchor = QPen(QColor(0, 100, 255), 2)  # Nice Blue
            pen_anchor.setStyle(Qt.PenStyle.DashLine)
            brush_anchor = QColor(0, 100, 255, 30)

            # Search Region (Yellow)
            pen_region = QPen(QColor(255, 200, 0), 2)
            pen_region.setStyle(Qt.PenStyle.DotLine)
            brush_region = QColor(255, 200, 0, 10)

            # Click Dot (Red)
            pen_dot = QPen(QColor(255, 0, 0), 2)
            brush_dot = QBrush(QColor(255, 0, 0))

            # Text
            brush_text_bg = QBrush(QColor(0, 0, 0, 180))
            pen_text = QPen(QColor(255, 255, 255))
            pen_text_anchor = QPen(QColor(100, 200, 255))

            # Helper to draw a set of rects
            def draw_set(rect_list, pen, brush, label_prefix, is_anchor=False, is_region=False):
                painter.setPen(pen)
                painter.setBrush(brush)

                for i, (x, y, w, h) in enumerate(rect_list):
                    # --- Map Logic ---
                    global_x = x + self.target_offset_x
                    global_y = y + self.target_offset_y
                    top_left_local = self.mapFromGlobal(QPoint(int(global_x), int(global_y)))

                    draw_x = top_left_local.x()
                    draw_y = top_left_local.y()
                    draw_w = int(round(w))
                    draw_h = int(round(h))

                    # Draw Box
                    painter.drawRect(draw_x, draw_y, draw_w, draw_h)

                    # Skip labels/dots for regions if desired, or keep them simple
                    if is_region:
                        continue

                    # Draw Label
                    label_text = f"{label_prefix}{i}"
                    fm = painter.fontMetrics()
                    text_w = fm.horizontalAdvance(label_text) + 8
                    text_h = fm.height() + 4

                    # Position label
                    label_x = draw_x
                    label_y = draw_y - text_h
                    if label_y < 0: label_y = draw_y

                    # Label Background
                    painter.save()  # Save state for temp brush change
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(brush_text_bg)
                    painter.drawRect(label_x, label_y, text_w, text_h)
                    painter.restore()

                    # Label Text
                    painter.save()
                    painter.setPen(pen_text_anchor if is_anchor else pen_text)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawText(QRect(label_x, label_y, text_w, text_h),
                                     Qt.AlignmentFlag.AlignCenter, label_text)
                    painter.restore()

                    # Draw Click Target (Only for Targets, not Anchors)
                    if not is_anchor and not is_region and self.show_click:
                        local_center_x = draw_x + (draw_w / 2)
                        local_center_y = draw_y + (draw_h / 2)

                        target_local = QPoint(
                            int(local_center_x + self.click_offset_x),
                            int(local_center_y + self.click_offset_y)
                        )
                        painter.save()
                        painter.setPen(pen_dot)
                        painter.setBrush(brush_dot)
                        painter.drawEllipse(target_local, 4, 4)
                        painter.restore()

            # 1. Draw Search Regions (Bottom Layer)
            if self.regions:
                draw_set(self.regions, pen_region, brush_region, "R", is_region=True)

            # 2. Draw Anchors
            if self.anchors:
                draw_set(self.anchors, pen_anchor, brush_anchor, "A", is_anchor=True)

            # 3. Draw Targets (Top Layer)
            if self.rects:
                draw_set(self.rects, pen_box, brush_box, "#", is_anchor=False)

        except Exception as e:
            print(f"Overlay paint error: {e}")