import sys
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QObject
from PyQt6.QtGui import QPainter, QColor, QPen, QPixmap, QScreen
from .utils import logical_to_physical


class Snipper(QWidget):
    snipped = pyqtSignal(QPixmap, tuple, QScreen)
    closed = pyqtSignal()

    def __init__(self, screen):
        super().__init__()
        self.target_screen = screen

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setCursor(Qt.CursorShape.CrossCursor)

        geo = self.target_screen.geometry()
        self.setGeometry(geo)

        self.original_pixmap = self.target_screen.grabWindow(0)

        self.start_point = None
        self.end_point = None
        self.is_snipping = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.original_pixmap)

        painter.setBrush(QColor(0, 0, 0, 100))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(self.rect())

        if self.start_point and self.end_point:
            rect = QRect(self.start_point, self.end_point).normalized()

            painter.setClipRect(rect)
            painter.drawPixmap(self.rect(), self.original_pixmap)
            painter.setClipping(False)

            painter.setPen(QPen(QColor(0, 120, 255), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

    def mousePressEvent(self, event):
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
        start = self.start_point
        end = self.end_point

        if not start or not end:
            return

        local_rect = QRect(start, end).normalized()

        if local_rect.width() < 5 or local_rect.height() < 5:
            self.start_point = None
            self.end_point = None
            self.update()
            return

        dpr = self.target_screen.devicePixelRatio()
        local_coords = (local_rect.x(), local_rect.y(), local_rect.width(), local_rect.height())

        phys_x, phys_y, phys_w, phys_h = logical_to_physical(local_coords, dpr)
        phys_coords = (phys_x, phys_y, phys_w, phys_h)

        try:
            cropped_pixmap = self.original_pixmap.copy(phys_x, phys_y, phys_w, phys_h)
            self.snipped.emit(cropped_pixmap, phys_coords, self.target_screen)
            self.close()
        except Exception as e:
            print(f"Crop failed: {e}")
            self.closed.emit()
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.closed.emit()
            self.close()


class SnippingController(QObject):
    finished = pyqtSignal(QPixmap, tuple, QScreen)

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

        if self.snippers:
            self.snippers[0].activateWindow()
            self.snippers[0].setFocus()

    def on_snip_completed(self, pixmap, rect, screen):
        self.finished.emit(pixmap, rect, screen)
        self.close_all()

    def on_snip_cancelled(self):
        self.finished.emit(QPixmap(), (0, 0, 0, 0), None)
        self.close_all()

    def close_all(self):
        for snipper in self.snippers:
            snipper.close()
        self.snippers = []