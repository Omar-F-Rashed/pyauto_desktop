from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QObject
from PyQt6.QtGui import QPainter, QColor, QPen, QPixmap


class Snipper(QWidget):
    """
    An individual overlay for a single screen.
    Responsible for capturing mouse events and drawing the selection
    ONLY on its assigned monitor.
    """
    # Emits (Captured Pixmap, Global Rect (x,y,w,h))
    snipped = pyqtSignal(QPixmap, tuple)
    closed = pyqtSignal()

    def __init__(self, screen):
        super().__init__()
        self.target_screen = screen

        # Window Flags: Frameless, On Top, Tool (no taskbar icon)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # 1. Geometry Setup
        # We set the geometry to match the logical geometry of the assigned screen exactly.
        geo = self.target_screen.geometry()
        self.setGeometry(geo)

        # 2. Background Capture
        # We capture the screen content immediately to use as the background.
        # grabWindow(0) captures the specific screen this widget is on.
        self.original_pixmap = self.target_screen.grabWindow(0)

        # State
        self.start_point = None
        self.end_point = None
        self.is_snipping = False

    def paintEvent(self, event):
        painter = QPainter(self)

        # 1. Draw the frozen screenshot (Background)
        # We draw the pixmap into the full rect of the widget.
        # Qt handles the High-DPI scaling here automatically if the widget size matches the screen logical size.
        painter.drawPixmap(self.rect(), self.original_pixmap)

        # 2. Draw Dim Overlay
        painter.setBrush(QColor(0, 0, 0, 100))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(self.rect())

        # 3. Draw Selection (Clear/Highlight)
        if self.start_point and self.end_point:
            rect = QRect(self.start_point, self.end_point).normalized()

            # "Cut out" the dim overlay to reveal the bright screenshot
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.drawRect(rect)

            # Draw Blue Border
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(0, 120, 255), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        # Start snipping logic local to this screen
        self.start_point = event.pos()
        self.end_point = event.pos()
        self.is_snipping = True
        self.update()

    def mouseMoveEvent(self, event):
        if self.is_snipping:
            self.end_point = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if not self.is_snipping:
            return

        self.is_snipping = False

        # 1. Calculate Logical Rect (Local to this screen/widget)
        start = self.start_point
        end = self.end_point
        local_rect = QRect(start, end).normalized()

        # 2. Calculate Physical Crop
        # We must crop the original high-res pixmap.
        # Map logical coordinates to physical pixels using the device pixel ratio.
        dpr = self.target_screen.devicePixelRatio()
        phys_x = int(local_rect.x() * dpr)
        phys_y = int(local_rect.y() * dpr)
        phys_w = int(local_rect.width() * dpr)
        phys_h = int(local_rect.height() * dpr)

        # Safe crop (copy rect from original pixmap)
        cropped_pixmap = self.original_pixmap.copy(phys_x, phys_y, phys_w, phys_h)

        # 3. Calculate Global Coordinates
        # Global = Screen Origin + Local Offset
        screen_geo = self.target_screen.geometry()
        global_x = screen_geo.x() + local_rect.x()
        global_y = screen_geo.y() + local_rect.y()

        global_rect = (global_x, global_y, local_rect.width(), local_rect.height())

        self.snipped.emit(cropped_pixmap, global_rect)
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.closed.emit()
            self.close()


class SnippingController(QObject):
    """
    Manages multiple Snipper windows (one per screen).
    Ensures they all open together and close together.
    """
    finished = pyqtSignal(QPixmap, tuple)

    def __init__(self):
        super().__init__()
        self.snippers = []

    def start(self):
        screens = QApplication.screens()
        self.snippers = []

        for screen in screens:
            snipper = Snipper(screen)
            snipper.snipped.connect(self.on_snip_completed)
            snipper.closed.connect(self.on_snip_cancelled)
            snipper.show()
            self.snippers.append(snipper)

    def on_snip_completed(self, pixmap, rect):
        # Forward the result
        self.finished.emit(pixmap, rect)
        self.close_all()

    def on_snip_cancelled(self):
        """
        Handle cancellation (e.g., ESC key) by notifying listeners with
        an empty result so they can restore their UI state.
        """
        self.finished.emit(QPixmap(), (0, 0, 0, 0))
        self.close_all()

    def close_all(self):
        for snipper in self.snippers:
            snipper.close()
        self.snippers = []