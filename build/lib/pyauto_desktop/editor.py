import cv2
import numpy as np
from PIL import Image
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QSlider, QMessageBox, QScrollArea, QWidget)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint, QEvent
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen


class EditorCanvas(QWidget):
    """
    Custom widget for displaying image and handling interactions.
    - Edges/Corners: Resize Crop Rect
    - Inside: Click to Magic Wand
    """
    wand_clicked = pyqtSignal(int, int)  # x, y (image coords)
    crop_changed = pyqtSignal(QRect)  # Emitted when drag ends (for syncing state)
    crop_started = pyqtSignal()  # Emitted when drag starts (for Undo)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.pixmap = None
        self.zoom_level = 1.0

        # Crop State
        self.crop_rect = QRect()  # Image coords
        self.dragging_handle = None
        self.handle_margin = 15  # Pixel distance to grab an edge
        self.is_wand_candidate = False

    def set_pixmap(self, pixmap):
        self.pixmap = pixmap
        # If crop_rect is invalid (e.g. startup), default to full image
        if self.pixmap and (self.crop_rect.isNull() or self.crop_rect.width() == 0):
            w = int(self.pixmap.width() / self.zoom_level)
            h = int(self.pixmap.height() / self.zoom_level)
            self.crop_rect = QRect(0, 0, w, h)
        self.update()

    def set_crop_rect(self, rect):
        """Updates the visual crop rectangle (Image Coordinates)."""
        self.crop_rect = rect
        self.update()

    def get_crop_rect_view(self):
        """Returns the crop rect scaled to the current zoom level (View Coordinates)."""
        if self.crop_rect.isNull():
            return QRect()
        x = int(self.crop_rect.x() * self.zoom_level)
        y = int(self.crop_rect.y() * self.zoom_level)
        w = int(self.crop_rect.width() * self.zoom_level)
        h = int(self.crop_rect.height() * self.zoom_level)
        return QRect(x, y, w, h)

    def paintEvent(self, event):
        if not self.pixmap:
            return
        painter = QPainter(self)

        # 1. Draw scaled pixmap
        target_rect = self.rect()
        painter.drawPixmap(target_rect, self.pixmap)

        # 2. Draw Crop Overlay (Always active)
        crop_view = self.get_crop_rect_view()
        if not crop_view.isValid():
            return

        x, y, w, h = crop_view.x(), crop_view.y(), crop_view.width(), crop_view.height()
        view_w, view_h = self.width(), self.height()

        # Dim outside area
        painter.setBrush(QColor(0, 0, 0, 150))  # Darker dimmer
        painter.setPen(Qt.PenStyle.NoPen)

        # Draw 4 rectangles around the crop area (Top, Bottom, Left, Right)
        # Prevents overdraw on the transparent crop area
        painter.drawRect(0, 0, view_w, y)  # Top
        painter.drawRect(0, y + h, view_w, view_h - (y + h))  # Bottom
        painter.drawRect(0, y, x, h)  # Left
        painter.drawRect(x + w, y, view_w - (x + w), h)  # Right

        # Draw Crop Border
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(Qt.GlobalColor.white, 2, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.drawRect(crop_view)

        # Draw Corner Handles
        painter.setBrush(Qt.GlobalColor.white)
        painter.setPen(Qt.GlobalColor.black)
        handle_len = 6
        # Corners
        painter.drawRect(x - handle_len, y - handle_len, handle_len * 2, handle_len * 2)  # TL
        painter.drawRect(x + w - handle_len, y - handle_len, handle_len * 2, handle_len * 2)  # TR
        painter.drawRect(x - handle_len, y + h - handle_len, handle_len * 2, handle_len * 2)  # BL
        painter.drawRect(x + w - handle_len, y + h - handle_len, handle_len * 2, handle_len * 2)  # BR

    def _get_hit_code(self, pos, rect):
        """
        Determines which edge or corner the mouse is hovering over.
        Returns: 'TL', 'T', 'TR', 'R', 'BR', 'B', 'BL', 'L' or None
        """
        x, y = pos.x(), pos.y()
        l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
        m = self.handle_margin

        # Check outside/inside proximity
        on_left = abs(x - l) < m
        on_right = abs(x - r) < m
        on_top = abs(y - t) < m
        on_bottom = abs(y - b) < m

        # Priority: Corners -> Edges
        if on_top and on_left: return 'TL'
        if on_top and on_right: return 'TR'
        if on_bottom and on_left: return 'BL'
        if on_bottom and on_right: return 'BR'

        if on_left and (t - m < y < b + m): return 'L'
        if on_right and (t - m < y < b + m): return 'R'
        if on_top and (l - m < x < r + m): return 'T'
        if on_bottom and (l - m < x < r + m): return 'B'

        return None

    def mousePressEvent(self, event):
        if not self.pixmap: return

        view_rect = self.get_crop_rect_view()
        hit = self._get_hit_code(event.pos(), view_rect)

        if hit:
            # Clicked on Edge/Corner -> Start Crop Drag
            self.dragging_handle = hit
            self.crop_started.emit()  # Signal to push Undo
            self.is_wand_candidate = False
        else:
            # Clicked Inside/Outside -> Potential Magic Wand
            self.is_wand_candidate = True

    def mouseMoveEvent(self, event):
        if not self.pixmap: return

        view_rect = self.get_crop_rect_view()

        # 1. Update Cursor if not dragging
        if not self.dragging_handle:
            hit = self._get_hit_code(event.pos(), view_rect)
            if hit in ['TL', 'BR']:
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif hit in ['TR', 'BL']:
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif hit in ['T', 'B']:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif hit in ['L', 'R']:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        # 2. Handle Dragging
        else:
            mx = int(event.pos().x() / self.zoom_level)
            my = int(event.pos().y() / self.zoom_level)

            # Image bounds
            img_w = int(self.pixmap.width() / self.zoom_level)
            img_h = int(self.pixmap.height() / self.zoom_level)

            # Clamp mouse to image area
            mx = max(0, min(mx, img_w))
            my = max(0, min(my, img_h))

            r = self.crop_rect
            l, t, r_edge, b = r.left(), r.top(), r.right(), r.bottom()

            # Minimum size
            min_size = 5

            # Resize logic
            if 'L' in self.dragging_handle:
                l = min(mx, r_edge - min_size)
            if 'R' in self.dragging_handle:
                r_edge = max(mx, l + min_size)
            if 'T' in self.dragging_handle:
                t = min(my, b - min_size)
            if 'B' in self.dragging_handle:
                b = max(my, t + min_size)

            self.crop_rect = QRect(QPoint(l, t), QPoint(r_edge, b)).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.dragging_handle:
            self.dragging_handle = None
            self.crop_changed.emit(self.crop_rect)

        elif self.is_wand_candidate:
            # Trigger Magic Wand
            img_x = int(event.pos().x() / self.zoom_level)
            img_y = int(event.pos().y() / self.zoom_level)
            self.wand_clicked.emit(img_x, img_y)
            self.is_wand_candidate = False


class MagicWandEditor(QDialog):
    """
    A simple image editor to remove backgrounds using FloodFill (Magic Wand) and Crop.
    """

    def __init__(self, pil_image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Image")
        self.resize(900, 700)
        # Enable Maximize/Minimize buttons
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)

        # State
        # Stack elements: tuple(cv_image_copy, crop_rect_copy)
        self.undo_stack = []
        self.redo_stack = []

        # Load initial image
        self.load_pil_image(pil_image)

        self.tolerance = 40
        self.zoom_level = 1.0

        self.initUI()
        self.update_display()

    def load_pil_image(self, pil_image):
        """Loads a PIL image into the editor, resetting state."""
        self.original_pil = pil_image

        # Convert to CV2 (BGRA)
        img_array = np.array(pil_image)
        if img_array.ndim == 3 and img_array.shape[2] == 4:
            self.cv_image = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGRA)
        else:
            self.cv_image = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGRA)

        self.cv_image = np.ascontiguousarray(self.cv_image, dtype=np.uint8)

        # Reset Crop to Full Image
        h, w = self.cv_image.shape[:2]
        self.current_crop_rect = QRect(0, 0, w, h)

        # Reset Stacks
        self.undo_stack = []
        self.redo_stack = []

    def initUI(self):
        layout = QVBoxLayout(self)

        # Instructions
        lbl_instr = QLabel("Drag edges to Crop. Click inside to Remove Background. Ctrl+Scroll to Zoom.")
        lbl_instr.setStyleSheet("color: #aaa; font-style: italic; margin-bottom: 5px;")
        layout.addWidget(lbl_instr)

        # Scroll Area / Canvas
        self.scroll_area = QScrollArea()
        self.scroll_area.setStyleSheet("background-color: #333; border: 1px solid #555;")
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.canvas = EditorCanvas()
        self.canvas.wand_clicked.connect(self.apply_magic_wand)
        self.canvas.crop_started.connect(self.push_undo)
        self.canvas.crop_changed.connect(self.on_crop_changed)

        self.scroll_area.setWidget(self.canvas)

        # Install event filter on viewport to capture Ctrl+Wheel
        self.scroll_area.viewport().installEventFilter(self)

        layout.addWidget(self.scroll_area)

        self.zoom_level = max(0.1, min(self.zoom_level, 5.0))
        ctrl_layout = QHBoxLayout()

        # Wand Controls
        ctrl_layout.addWidget(QLabel("Wand Tolerance:"))
        self.slider_tol = QSlider(Qt.Orientation.Horizontal)
        self.slider_tol.setRange(0, 150)
        self.slider_tol.setValue(40)
        self.slider_tol.valueChanged.connect(self.on_tol_change)
        self.lbl_tol_val = QLabel("40")
        ctrl_layout.addWidget(self.slider_tol)
        ctrl_layout.addWidget(self.lbl_tol_val)

        ctrl_layout.addStretch()

        # Undo/Redo/Reset
        self.btn_undo = QPushButton("Undo")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_undo.setEnabled(False)
        self.btn_undo.setObjectName("secondary_btn")

        self.btn_redo = QPushButton("Redo")
        self.btn_redo.clicked.connect(self.redo)
        self.btn_redo.setEnabled(False)
        self.btn_redo.setObjectName("secondary_btn")

        btn_reset = QPushButton("Reset")
        btn_reset.clicked.connect(self.reset_image)
        btn_reset.setObjectName("secondary_btn")

        ctrl_layout.addWidget(self.btn_undo)
        ctrl_layout.addWidget(self.btn_redo)
        ctrl_layout.addWidget(btn_reset)

        layout.addLayout(ctrl_layout)

        # Bottom Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Use This Image")
        btn_save.clicked.connect(self.accept)
        btn_save.setStyleSheet("background-color: #198754; color: white; padding: 6px 12px; font-weight: bold;")

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)

        layout.addLayout(btn_layout)

    def eventFilter(self, source, event):
        """Filter events to allow Ctrl+Scroll zoom inside QScrollArea."""
        if source == self.scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.perform_zoom_event(event)
                return True  # Consume event to prevent scrolling
            # Otherwise return False to let QScrollArea handle scrolling
            return False
        return super().eventFilter(source, event)

    def perform_zoom_event(self, event):
        """Helper to handle zoom logic from event."""
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom_level *= 1.1
        else:
            self.zoom_level /= 1.1

        # Clamp zoom
        self.zoom_level = max(0.1, min(self.zoom_level, 5.0))
        self.canvas.zoom_level = self.zoom_level
        self.update_display()

    def on_tol_change(self):
        self.tolerance = self.slider_tol.value()
        self.lbl_tol_val.setText(str(self.tolerance))

    def on_crop_changed(self, new_rect):
        """Called when user finishes dragging a crop handle."""
        self.current_crop_rect = new_rect
        # No need to update display, canvas is already updated visually

    def undo(self):
        if not self.undo_stack: return

        # Save current to redo
        self.redo_stack.append((self.cv_image.copy(), QRect(self.current_crop_rect)))

        # Restore
        img, rect = self.undo_stack.pop()
        self.cv_image = img
        self.current_crop_rect = rect

        self.update_display()
        self.update_buttons()

    def redo(self):
        if not self.redo_stack: return

        self.undo_stack.append((self.cv_image.copy(), QRect(self.current_crop_rect)))

        img, rect = self.redo_stack.pop()
        self.cv_image = img
        self.current_crop_rect = rect

        self.update_display()
        self.update_buttons()

    def push_undo(self):
        """Saves current state (Image + Crop Rect) to undo stack."""
        self.undo_stack.append((self.cv_image.copy(), QRect(self.current_crop_rect)))
        if len(self.undo_stack) > 20:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.update_buttons()

    def update_buttons(self):
        self.btn_undo.setEnabled(len(self.undo_stack) > 0)
        self.btn_redo.setEnabled(len(self.redo_stack) > 0)

    def reset_image(self):
        self.load_pil_image(self.original_pil)
        self.reset_image_state()

    def reset_image_state(self):
        """Helper to reset UI state after loading new image"""
        self.update_buttons()
        self.zoom_level = 1.0
        self.canvas.zoom_level = 1.0
        self.update_display()

    def update_display(self):
        if not self.cv_image.flags['C_CONTIGUOUS']:
            self.cv_image = np.ascontiguousarray(self.cv_image)

        # Convert BGRA to RGBA for Qt
        display_img = cv2.cvtColor(self.cv_image, cv2.COLOR_BGRA2RGBA)
        h, w, ch = display_img.shape
        bytes_per_line = ch * w

        q_img = QImage(display_img.data, w, h, bytes_per_line, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(q_img.copy())

        # Scale
        new_w = int(w * self.zoom_level)
        new_h = int(h * self.zoom_level)
        if new_w > 0 and new_h > 0:
            pixmap = pixmap.scaled(new_w, new_h, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)

        self.canvas.setFixedSize(new_w, new_h)
        self.canvas.set_crop_rect(self.current_crop_rect)  # Push state to canvas
        self.canvas.set_pixmap(pixmap)

    def apply_magic_wand(self, x, y):
        h, w = self.cv_image.shape[:2]
        if x < 0 or x >= w or y < 0 or y >= h: return

        self.push_undo()

        mask = np.zeros((h + 2, w + 2), np.uint8)
        tol = self.tolerance
        diff = (tol, tol, tol)
        bgr = np.ascontiguousarray(self.cv_image[:, :, :3])
        flags = 4 | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (255 << 8)

        try:
            cv2.floodFill(bgr, mask, (x, y), (0, 0, 0), diff, diff, flags)
            region_mask = mask[1:-1, 1:-1]

            # Set Alpha channel (index 3) to 0 where mask is 255
            self.cv_image[:, :, 3][region_mask == 255] = 0

            # CRITICAL FIX: Also set RGB to 0.
            # If we don't, Grayscale conversion (which drops Alpha) will still see the original background pixels.
            self.cv_image[:, :, 0][region_mask == 255] = 0
            self.cv_image[:, :, 1][region_mask == 255] = 0
            self.cv_image[:, :, 2][region_mask == 255] = 0

        except Exception as e:
            print(f"FloodFill Error: {e}")
            if self.undo_stack: self.undo_stack.pop()

        self.update_display()

    def get_result(self):
        """Applies the final crop and returns PIL image."""
        if not self.cv_image.flags['C_CONTIGUOUS']:
            self.cv_image = np.ascontiguousarray(self.cv_image)

        # 1. Apply Crop
        x, y, w, h = self.current_crop_rect.x(), self.current_crop_rect.y(), self.current_crop_rect.width(), self.current_crop_rect.height()

        # Ensure bounds
        img_h, img_w = self.cv_image.shape[:2]
        x = max(0, x);
        y = max(0, y)
        w = min(w, img_w - x);
        h = min(h, img_h - y)

        if w > 0 and h > 0:
            cropped_cv = self.cv_image[y:y + h, x:x + w]
        else:
            cropped_cv = self.cv_image

        # 2. Convert to PIL
        img_rgb = cv2.cvtColor(cropped_cv, cv2.COLOR_BGRA2RGBA)
        return Image.fromarray(img_rgb)