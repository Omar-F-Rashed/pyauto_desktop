from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen


class Overlay(QWidget):
    """Transparent overlay to draw bounding boxes."""

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

        # Calculate bounding box to cover all screens (The Giant Canvas)
        self._update_geometry()

        self.rects = []
        self.scale_factor = 1.0

    def _update_geometry(self):
        """Recalculate overlay geometry to cover all screens."""
        screens = QApplication.screens()
        if screens:
            # Union of all screen geometries is safer than manual min/max
            # to ensure we match Qt's internal understanding of the virtual desktop
            full_rect = screens[0].geometry()
            for screen in screens[1:]:
                full_rect = full_rect.united(screen.geometry())

            self.setGeometry(full_rect)
        else:
            self.setGeometry(QApplication.primaryScreen().geometry())

    def showEvent(self, event):
        """Recalculate geometry when shown in case screens changed."""
        super().showEvent(event)
        self._update_geometry()

    def set_target_screen_offset(self, x, y):
        """
        Update the offset for the screen currently being scanned.
        x, y: The Global Logical coordinates of the target screen's top-left corner.
        """
        self.target_offset_x = x
        self.target_offset_y = y

    def update_rects(self, rects, scale_factor):
        self.rects = rects  # Now receiving Screen-Local Logical coordinates
        self.scale_factor = scale_factor
        self.update()

    def paintEvent(self, event):
        if not self.rects:
            return

        try:
            painter = QPainter(self)
            painter.setPen(QPen(QColor(0, 255, 0), 2))
            painter.setBrush(QColor(0, 255, 0, 50))

            for x, y, w, h in self.rects:
                # Logic:
                # 1. Start with Local Rect (x, y) -> Relative to the Screen being scanned
                # 2. Add Target Screen Offset -> Becomes Global Coordinate
                global_x = x + self.target_offset_x
                global_y = y + self.target_offset_y

                # 3. Use Qt's built-in mapper to find where this global point
                # sits inside this specific Overlay widget.
                # This matches the logic used in debug_corners.py which was confirmed to work.

                # We cast to int() for QPoint, similar to the debug tool.
                # This ensures we snap to the pixel grid exactly as Qt expects.
                top_left_local = self.mapFromGlobal(QPoint(int(global_x), int(global_y)))

                draw_x = top_left_local.x()
                draw_y = top_left_local.y()

                # We also assume width/height don't need projection since they are relative dimensions,
                # but we round them to ensure clean drawing.
                draw_w = int(round(w))
                draw_h = int(round(h))

                painter.drawRect(draw_x, draw_y, draw_w, draw_h)

        except Exception as e:
            print(f"Overlay paint error: {e}")