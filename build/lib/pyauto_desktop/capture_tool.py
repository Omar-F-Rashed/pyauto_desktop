from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QObject
from PyQt6.QtGui import QPainter, QColor, QPen, QPixmap, QRegion


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

        # Window Flags: Frameless, On Top, Tool
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)

        # NOTE: We removed WA_TranslucentBackground.
        # Since we are drawing the full screenshot (opaque), we don't need transparency
        # at the window level. This often improves performance and avoids composition artifacts.
        # self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setCursor(Qt.CursorShape.CrossCursor)

        # Ensure we can catch the ESC key immediately
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 1. Geometry Setup
        geo = self.target_screen.geometry()
        self.setGeometry(geo)

        # 2. Background Capture
        # Capture the screen content immediately to use as the frozen background.
        self.original_pixmap = self.target_screen.grabWindow(0)

        # State
        self.start_point = None
        self.end_point = None
        self.is_snipping = False

    def showEvent(self, event):
        super().showEvent(event)
        # Force grab keyboard so ESC works immediately without clicking first
        self.activateWindow()
        self.setFocus()

    def paintEvent(self, event):
        painter = QPainter(self)

        # --- Layer 1: The "Dim" Background ---
        # Draw the frozen screenshot
        painter.drawPixmap(self.rect(), self.original_pixmap)

        # Draw a semi-transparent black layer over the whole image to dim it
        painter.setBrush(QColor(0, 0, 0, 100))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(self.rect())

        # --- Layer 2: The "Bright" Selection ---
        if self.start_point and self.end_point:
            # Calculate the selection rectangle
            rect = QRect(self.start_point, self.end_point).normalized()

            # Set a clip region to ONLY draw inside the selection rectangle
            painter.setClipRect(rect)

            # Draw the bright original screenshot again.
            # Because of the clip, it only appears inside the box.
            painter.drawPixmap(self.rect(), self.original_pixmap)

            # Disable clipping to draw the border
            painter.setClipping(False)

            # Draw the Blue Border around the selection
            painter.setPen(QPen(QColor(0, 120, 255), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        # Start snipping logic
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_point = event.pos()
            self.end_point = event.pos()
            self.is_snipping = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_snipping:
            self.end_point = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if not self.is_snipping or event.button() != Qt.MouseButton.LeftButton:
            return

        self.is_snipping = False

        # 1. Calculate Logical Rect (Local to this screen/widget)
        start = self.start_point
        end = self.end_point
        local_rect = QRect(start, end).normalized()

        # Handle accidental tiny clicks
        if local_rect.width() < 5 or local_rect.height() < 5:
            # If it's too small, just reset the selection instead of closing
            self.start_point = None
            self.end_point = None
            self.update()
            return

        # 2. Calculate Physical Crop
        dpr = self.target_screen.devicePixelRatio()
        phys_x = int(local_rect.x() * dpr)
        phys_y = int(local_rect.y() * dpr)
        phys_w = int(local_rect.width() * dpr)
        phys_h = int(local_rect.height() * dpr)

        # Safe crop
        cropped_pixmap = self.original_pixmap.copy(phys_x, phys_y, phys_w, phys_h)

        # 3. Calculate Global Coordinates
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

        # Ensure the primary screen's snipper gets focus initially
        if self.snippers:
            self.snippers[0].activateWindow()
            self.snippers[0].setFocus()

    def on_snip_completed(self, pixmap, rect):
        self.finished.emit(pixmap, rect)
        self.close_all()

    def on_snip_cancelled(self):
        # Emit empty result to signify cancellation
        self.finished.emit(QPixmap(), (0, 0, 0, 0))
        self.close_all()

    def close_all(self):
        for snipper in self.snippers:
            snipper.close()
        self.snippers = []