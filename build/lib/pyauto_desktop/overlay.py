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

    def update_rects(self, rects, scale_factor):
        self.rects = rects
        self.scale_factor = scale_factor
        self.update()

    def paintEvent(self, event):
        if not self.rects:
            return

        try:
            painter = QPainter(self)
            painter.setFont(self.font_idx)

            # 1. Setup Pens/Brushes
            pen_box = QPen(QColor(0, 255, 0), 2)
            brush_box = QColor(0, 255, 0, 50)

            pen_dot = QPen(QColor(255, 0, 0), 2)
            brush_dot = QBrush(QColor(255, 0, 0))

            # For text background
            brush_text_bg = QBrush(QColor(0, 0, 0, 180))
            pen_text = QPen(QColor(255, 255, 255))

            # Loop with index
            for i, (x, y, w, h) in enumerate(self.rects):
                # --- Map Logic ---
                global_x = x + self.target_offset_x
                global_y = y + self.target_offset_y
                top_left_local = self.mapFromGlobal(QPoint(int(global_x), int(global_y)))

                draw_x = top_left_local.x()
                draw_y = top_left_local.y()
                draw_w = int(round(w))
                draw_h = int(round(h))

                # --- Draw Box ---
                painter.setPen(pen_box)
                painter.setBrush(brush_box)
                painter.drawRect(draw_x, draw_y, draw_w, draw_h)

                # --- Draw Index Label ---
                label_text = f"#{i}"
                # Calculate text size for background rect
                fm = painter.fontMetrics()
                text_w = fm.horizontalAdvance(label_text) + 8
                text_h = fm.height() + 4

                # Position label just above the box (or inside if near top edge)
                label_x = draw_x
                label_y = draw_y - text_h
                if label_y < 0: label_y = draw_y  # Push inside if cut off

                # Draw Label Background
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(brush_text_bg)
                painter.drawRect(label_x, label_y, text_w, text_h)

                # Draw Label Text
                painter.setPen(pen_text)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawText(QRect(label_x, label_y, text_w, text_h),
                                 Qt.AlignmentFlag.AlignCenter, label_text)

                # --- Draw Click Target (Red Dot) ---
                if self.show_click:
                    local_center_x = draw_x + (draw_w / 2)
                    local_center_y = draw_y + (draw_h / 2)

                    target_local = QPoint(
                        int(local_center_x + self.click_offset_x),
                        int(local_center_y + self.click_offset_y)
                    )

                    painter.setPen(pen_dot)
                    painter.setBrush(brush_dot)
                    painter.drawEllipse(target_local, 4, 4)

        except Exception as e:
            print(f"Overlay paint error: {e}")