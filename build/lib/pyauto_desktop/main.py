import sys
import os
import time
from PIL import Image
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QSlider,
                             QCheckBox, QTextEdit, QFileDialog, QGroupBox, QMessageBox, QComboBox, QSpinBox,
                             QRadioButton)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QBuffer, QIODevice
from PyQt6.QtGui import QPixmap, QImage

# --- IMPORTS ---
from .style import DARK_THEME
from .capture_tool import SnippingController
from .overlay import Overlay
from .detection import DetectionWorker
from .editor import MagicWandEditor

# --- CRITICAL FIX: ENABLE DPI AWARENESS ---
# This forces Windows to treat the app as "Per-Monitor DPI Aware V2".

# --- Windows-specific setup ---
if sys.platform == "win32":
    import ctypes

    user32 = ctypes.windll.user32
    WDA_EXCLUDEFROMCAPTURE = 0x00000011


    def set_window_display_affinity(hwnd, affinity):
        try:
            user32.SetWindowDisplayAffinity(hwnd, affinity)
        except Exception as e:
            print(f"Failed to set display affinity: {e}")
else:
    def set_window_display_affinity(hwnd, affinity):
        pass


class ClickableDropLabel(QLabel):
    clicked = pyqtSignal()
    file_dropped = pyqtSignal(str)

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border: 2px dashed #555; padding: 10px; background-color: #222; color: #aaa;")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            fpath = urls[0].toLocalFile()
            if fpath and fpath.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                self.file_dropped.emit(fpath)
                event.accept()
                return
        event.ignore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class RegionButton(QPushButton):
    reset_clicked = pyqtSignal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.btn_close = QPushButton("X", self)
        self.btn_close.setCursor(Qt.CursorShape.ArrowCursor)
        self.btn_close.setStyleSheet(
            "QPushButton { background: transparent; color: red; font-weight: bold; font-size: 14px; padding: 0px; text-align: center; }"
            "QPushButton:hover { color: #ffcccc; border-color: #ffcccc; }"
        )
        self.btn_close.setFixedSize(30, 30)
        self.btn_close.clicked.connect(self.reset_clicked.emit)
        self.btn_close.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.btn_close.move(self.width() - self.btn_close.width() - 5, (self.height() - self.btn_close.height()) // 2)

    def set_active(self, active):
        if active:
            self.setStyleSheet(
                "QPushButton { background-color: #198754; text-align: left; padding-left: 15px; } QPushButton:hover { background-color: #157347; }")
            self.btn_close.show()
        else:
            self.setStyleSheet("")  # Revert to default
            self.btn_close.hide()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Desktop Inspector")
        self.resize(550, 800)  # Increased height for new controls
        self.setStyleSheet(DARK_THEME)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

        # State
        self.template_image = None
        self.search_region = None  # (x, y, w, h) in Global Logical Coordinates
        self.current_scale = 1.0
        self.is_image_unsaved = False
        self.current_filename = None

        # Controllers
        self.snip_controller = SnippingController()
        self.snip_controller.finished.connect(self.on_snip_finished)
        self.active_snip_mode = None

        # Initialize Overlay
        self.overlay = Overlay()
        if sys.platform == "win32":
            self.overlay.winId()
            set_window_display_affinity(int(self.overlay.winId()), WDA_EXCLUDEFROMCAPTURE)

        # Timer-based detection
        self.detection_timer = QTimer(self)
        self.detection_timer.timeout.connect(self.detection_step)
        self.is_detecting = False
        self.worker = None
        self.worker_running = False
        self.last_fps_time = 0

        # Metadata passed to worker to help map results back to screen
        self.detection_context = {}

        self.initUI()

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # --- Header ---
        lbl_title = QLabel("AutoMate Studio")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #0d6efd;")
        layout.addWidget(lbl_title, alignment=Qt.AlignmentFlag.AlignCenter)

        # --- 1. Capture Section ---
        grp_cap = QGroupBox("1. Image & Region")
        cap_layout = QVBoxLayout()

        hbox_btns = QHBoxLayout()
        self.btn_snip = QPushButton("Snip Image From Screen")
        self.btn_snip.clicked.connect(self.start_snip_template)

        self.btn_region = RegionButton("Set Search Region")
        self.btn_region.clicked.connect(self.start_snip_region)
        self.btn_region.setObjectName("secondary_btn")
        self.btn_region.reset_clicked.connect(self.reset_region)

        hbox_btns.addWidget(self.btn_snip)
        hbox_btns.addWidget(self.btn_region)

        self.btn_reedit = QPushButton("Edit Image")
        self.btn_reedit.clicked.connect(self.reedit_template)
        self.btn_reedit.setEnabled(False)
        self.btn_reedit.setObjectName("secondary_btn")

        self.lbl_preview = ClickableDropLabel("Click or Drop Image Here\n(PNG, JPG, BMP)")
        self.lbl_preview.clicked.connect(self.request_upload_image)
        self.lbl_preview.file_dropped.connect(self.handle_dropped_image)
        self.lbl_preview.setFixedHeight(120)

        self.lbl_region_status = QLabel("Region: Full Screen")
        self.lbl_region_status.setStyleSheet("color: #888; font-size: 12px;")

        cap_layout.addLayout(hbox_btns)
        cap_layout.addWidget(self.btn_reedit)
        cap_layout.addWidget(self.lbl_preview)
        cap_layout.addWidget(self.lbl_region_status)
        grp_cap.setLayout(cap_layout)
        layout.addWidget(grp_cap)

        # --- 2. Parameters ---
        grp_test = QGroupBox("2. Live Test & Action")
        test_layout = QVBoxLayout()

        # Confidence
        hbox_conf = QHBoxLayout()
        hbox_conf.addWidget(QLabel("Confidence:"))
        self.slider_conf = QSlider(Qt.Orientation.Horizontal)
        self.slider_conf.setRange(50, 99)
        self.slider_conf.setValue(90)
        self.slider_conf.valueChanged.connect(self.update_conf_label)
        self.lbl_conf_val = QLabel("0.90")
        hbox_conf.addWidget(self.slider_conf)
        hbox_conf.addWidget(self.lbl_conf_val)

        # Overlap
        hbox_overlap = QHBoxLayout()
        hbox_overlap.addWidget(QLabel("Overlap Threshold:"))
        self.slider_overlap = QSlider(Qt.Orientation.Horizontal)
        self.slider_overlap.setRange(0, 100)
        self.slider_overlap.setValue(50)
        self.slider_overlap.valueChanged.connect(self.update_overlap_label)
        self.lbl_overlap_val = QLabel("0.50")
        hbox_overlap.addWidget(self.slider_overlap)
        hbox_overlap.addWidget(self.lbl_overlap_val)

        self.chk_gray = QCheckBox("Grayscale (Faster)")
        self.chk_gray.setChecked(True)

        # --- Click / Action Settings ---
        hbox_click = QHBoxLayout()
        self.chk_click = QCheckBox("Simulate Click / Show Target")
        self.chk_click.stateChanged.connect(self.update_overlay_click_settings)

        self.spin_off_x = QSpinBox()
        self.spin_off_x.setRange(-9999, 9999)
        self.spin_off_x.setValue(0)
        self.spin_off_x.setSuffix(" px")
        self.spin_off_x.setToolTip("X Offset from Center")
        self.spin_off_x.valueChanged.connect(self.update_overlay_click_settings)

        self.spin_off_y = QSpinBox()
        self.spin_off_y.setRange(-9999, 9999)
        self.spin_off_y.setValue(0)
        self.spin_off_y.setSuffix(" px")
        self.spin_off_y.setToolTip("Y Offset from Center")
        self.spin_off_y.valueChanged.connect(self.update_overlay_click_settings)

        hbox_click.addWidget(self.chk_click)
        hbox_click.addWidget(QLabel("X:"))
        hbox_click.addWidget(self.spin_off_x)
        hbox_click.addWidget(QLabel("Y:"))
        hbox_click.addWidget(self.spin_off_y)

        # --- Screen Selection ---
        hbox_screen = QHBoxLayout()
        self.cbo_screens = QComboBox()

        screens = QApplication.screens()
        for i, screen in enumerate(screens):
            name = screen.name()
            geo = screen.geometry()
            self.cbo_screens.addItem(f"Screen {i + 1} ({geo.width()}x{geo.height()})", screen)

        if len(screens) > 0:
            self.cbo_screens.setCurrentIndex(0)  # Default to first screen

        hbox_screen.addWidget(QLabel("Detect On:"))
        hbox_screen.addWidget(self.cbo_screens)

        hbox_ctrl = QHBoxLayout()
        self.btn_start = QPushButton("Start Detection")
        self.btn_start.clicked.connect(self.toggle_detection)
        self.btn_start.setEnabled(False)
        self.btn_start.setStyleSheet("background-color: #198754;")

        self.lbl_status = QLabel("Matches: 0")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #00ff00;")

        test_layout.addLayout(hbox_conf)
        test_layout.addLayout(hbox_overlap)
        test_layout.addWidget(self.chk_gray)
        test_layout.addLayout(hbox_click)  # Add click row
        test_layout.addLayout(hbox_screen)
        test_layout.addLayout(hbox_ctrl)
        test_layout.addWidget(self.btn_start)
        test_layout.addWidget(self.lbl_status)
        grp_test.setLayout(test_layout)
        layout.addWidget(grp_test)

        # --- 3. Output ---
        grp_out = QGroupBox("3. Generate Code")
        out_layout = QVBoxLayout()

        # Generation Mode (Single vs All)
        hbox_mode = QHBoxLayout()
        self.rdo_single = QRadioButton("Best Match (Single)")
        self.rdo_single.setChecked(True)
        self.rdo_all = QRadioButton("All Matches (Loop)")
        hbox_mode.addWidget(self.rdo_single)
        hbox_mode.addWidget(self.rdo_all)
        out_layout.addLayout(hbox_mode)

        hbox_gen = QHBoxLayout()
        self.btn_save = QPushButton("Save Image")
        self.btn_save.clicked.connect(self.save_image)
        self.btn_save.setEnabled(False)

        self.btn_gen = QPushButton("Generate Code")
        self.btn_gen.clicked.connect(self.generate_code)
        self.btn_gen.setEnabled(False)  # Disabled by default until saved/loaded

        hbox_gen.addWidget(self.btn_save)
        hbox_gen.addWidget(self.btn_gen)

        out_layout.addLayout(hbox_gen)

        self.txt_output = QTextEdit()
        self.txt_output.setPlaceholderText("Generated code will appear here...")
        self.txt_output.setFixedHeight(120)
        out_layout.addWidget(self.txt_output)

        grp_out.setLayout(out_layout)
        layout.addWidget(grp_out)

    def update_conf_label(self):
        val = self.slider_conf.value() / 100.0
        self.lbl_conf_val.setText(f"{val:.2f}")

    def update_overlap_label(self):
        val = self.slider_overlap.value() / 100.0
        self.lbl_overlap_val.setText(f"{val:.2f}")

    def update_overlay_click_settings(self):
        """Push click settings to overlay immediately."""
        self.overlay.set_click_config(
            self.chk_click.isChecked(),
            self.spin_off_x.value(),
            self.spin_off_y.value()
        )

    # --- Snipping Handlers ---
    def start_snip_template(self):
        self.hide()
        self.active_snip_mode = 'template'
        self.snip_controller.start()

    def start_snip_region(self):
        self.hide()
        self.active_snip_mode = 'region'
        self.snip_controller.start()

    def on_snip_finished(self, pixmap, global_rect):
        self.show()
        x, y, w, h = global_rect

        # Check for valid snip
        if w < 5 or h < 5:
            return

        if self.active_snip_mode == 'template':
            # Convert QPixmap to PIL for editor
            pil_image = self.qpixmap_to_pil(pixmap)

            # Reset state for new unsaved image
            self.is_image_unsaved = True
            self.current_filename = None
            self.btn_gen.setEnabled(False)  # Disable code gen for unsaved snip

            self.open_editor(pil_image)

        elif self.active_snip_mode == 'region':
            self.search_region = (x, y, w, h)
            self.lbl_region_status.setText(f"Region: {self.search_region}")
            self.btn_region.set_active(True)

        self.active_snip_mode = None

    def reset_region(self):
        self.search_region = None
        self.lbl_region_status.setText("Region: Full Screen")
        self.btn_region.set_active(False)

    # --- Image Loading & Editor ---
    def request_upload_image(self):
        if self.template_image:
            if QMessageBox.question(self, "Replace?", "Replace current image?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.No:
                return
        fname, _ = QFileDialog.getOpenFileName(self, "Open Image", "", "Images (*.png *.jpg *.bmp)")
        if fname: self.process_loaded_image(fname)

    def handle_dropped_image(self, path):
        if self.template_image:
            if QMessageBox.question(self, "Replace?", "Replace current image?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.No:
                return
        self.process_loaded_image(path)

    def process_loaded_image(self, path):
        try:
            img = Image.open(path)
            self.current_scale = QApplication.primaryScreen().devicePixelRatio()

            # Loaded image is considered "saved" or at least exists on disk
            self.is_image_unsaved = False
            self.current_filename = os.path.basename(path)

            self.open_editor(img)
            self.btn_gen.setEnabled(True)  # Enable code gen for loaded image

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load image:\n{e}")

    def reedit_template(self):
        if self.template_image:
            self.open_editor(self.template_image)

    def open_editor(self, pil_img):
        editor = MagicWandEditor(pil_img, self)
        if editor.exec():
            self.template_image = editor.get_result()
            self.update_preview()
            self.btn_start.setEnabled(True)
            self.btn_start.setText("Start Detection")
            self.btn_reedit.setEnabled(True)
            self.btn_save.setEnabled(True)

            # Note: We do NOT enable btn_gen here for snipped images.
            # It remains disabled until saved.
            # For loaded images, it was already enabled in process_loaded_image.

    def update_preview(self):
        if not self.template_image: return
        qim = self.pil2pixmap(self.template_image)
        self.lbl_preview.setPixmap(
            qim.scaled(self.lbl_preview.width(), self.lbl_preview.height(), Qt.AspectRatioMode.KeepAspectRatio))

    # --- Detection Logic ---
    def toggle_detection(self):
        if self.is_detecting:
            self.is_detecting = False
            self.detection_timer.stop()
            self.overlay.hide()
            self.btn_start.setText("Start Detection")
            self.btn_start.setStyleSheet("background-color: #198754;")
            self.btn_snip.setEnabled(True)
            self.btn_reedit.setEnabled(True)
            self.lbl_preview.setEnabled(True)
            self.cbo_screens.setEnabled(True)
            self.btn_save.setEnabled(True)
            # Restore state of generate button
            self.btn_gen.setEnabled(not self.is_image_unsaved and self.template_image is not None)
        else:
            if not self.template_image: return

            if self.chk_gray.isChecked() and self.template_image.mode in ('RGBA', 'LA'):
                if self.template_image.getextrema()[-1][0] < 255:
                    if QMessageBox.question(self, "Warning", "Grayscale with transparency enabled. Disable grayscale?",
                                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                        self.chk_gray.setChecked(False)

            self.is_detecting = True
            # Sync click settings before showing
            self.update_overlay_click_settings()

            self.last_fps_time = time.time()
            self.overlay.show()
            self.detection_timer.start(50)  # Increased interval slightly for screen grab perf
            self.btn_start.setText("Stop Detection")
            self.btn_start.setStyleSheet("background-color: #dc3545;")
            self.btn_snip.setEnabled(False)
            self.btn_reedit.setEnabled(False)
            self.lbl_preview.setEnabled(False)
            self.cbo_screens.setEnabled(False)
            self.btn_save.setEnabled(False)
            self.btn_gen.setEnabled(False)

    def detection_step(self):
        if self.worker_running or not self.is_detecting: return
        if not self.template_image: self.toggle_detection(); return

        # 1. Determine Search Target (Haystack)
        target_screen = None

        if self.search_region:
            # If manual region, find the screen containing the center of that region
            center_x = self.search_region[0] + self.search_region[2] // 2
            center_y = self.search_region[1] + self.search_region[3] // 2
            target_screen = QApplication.screenAt(QPoint(center_x, center_y))
            if not target_screen: target_screen = QApplication.primaryScreen()
        else:
            # Dropdown selection - must have a valid screen selected
            target_screen = self.cbo_screens.currentData()
            if not target_screen:
                # Fallback to primary screen if somehow no screen is selected
                target_screen = QApplication.primaryScreen()

        if not target_screen: return

        # 2. Grab Screen Image (Physical Pixels)
        # We perform the grab here in Main Thread to ensure thread safety with Qt
        try:
            # Validate screen is accessible
            screen_geo = target_screen.geometry()
            if screen_geo.width() <= 0 or screen_geo.height() <= 0:
                print(f"Invalid screen geometry for {target_screen.name()}")
                return

            screen_pixmap = target_screen.grabWindow(0)
            if screen_pixmap.isNull() or screen_pixmap.width() == 0 or screen_pixmap.height() == 0:
                print(f"Failed to grab screen {target_screen.name()} - null or empty pixmap")
                return

            haystack_img = self.qpixmap_to_pil(screen_pixmap)
            if haystack_img is None:
                print(f"Failed to convert pixmap to PIL for screen {target_screen.name()}")
                return

            if haystack_img.size[0] == 0 or haystack_img.size[1] == 0:
                print(f"Invalid haystack image dimensions from screen {target_screen.name()}")
                return
        except Exception as e:
            print(f"Error grabbing screen {target_screen.name()}: {e}")
            import traceback
            traceback.print_exc()
            return

        # 3. Handle Manual Region Cropping (Optimization)
        # Map Global Logical Region -> Local Physical Crop
        offset_x_phys = 0
        offset_y_phys = 0

        if self.search_region:
            geo = target_screen.geometry()
            dpr = target_screen.devicePixelRatio()

            # Local Logical
            local_x = self.search_region[0] - geo.x()
            local_y = self.search_region[1] - geo.y()

            # To Physical
            phys_x = int(local_x * dpr)
            phys_y = int(local_y * dpr)
            phys_w = int(self.search_region[2] * dpr)
            phys_h = int(self.search_region[3] * dpr)

            # Ensure crop is valid
            img_w, img_h = haystack_img.size
            phys_x = max(0, phys_x)
            phys_y = max(0, phys_y)
            phys_w = min(phys_w, img_w - phys_x)
            phys_h = min(phys_h, img_h - phys_y)

            if phys_w > 0 and phys_h > 0:
                haystack_img = haystack_img.crop((phys_x, phys_y, phys_x + phys_w, phys_y + phys_h))
                offset_x_phys = phys_x
                offset_y_phys = phys_y

        # 4. Context for Result Mapping
        self.detection_context = {
            'screen_geo': target_screen.geometry(),  # Logical (x, y, w, h)
            'dpr': target_screen.devicePixelRatio(),
            'offset_phys': (offset_x_phys, offset_y_phys)
        }

        # 5. Start Worker
        self.worker_running = True
        conf = self.slider_conf.value() / 100.0
        gray = self.chk_gray.isChecked()
        overlap = self.slider_overlap.value() / 100.0

        # Note: We pass the Haystack Image, NOT the region.
        self.worker = DetectionWorker(self.template_image, haystack_img, conf, gray, overlap)
        self.worker.result_signal.connect(self.on_detection_result)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_worker_finished(self):
        self.worker_running = False
        self.worker = None

    def on_detection_result(self, rects, count):
        if not self.is_detecting: return

        curr_time = time.time()
        dt = curr_time - self.last_fps_time
        self.last_fps_time = curr_time
        fps = int(1.0 / dt) if dt > 0 else 0

        # Map Results (Physical Local) -> Logical Local
        # We do NOT convert to global coordinates here anymore.
        ctx = self.detection_context
        screen_geo = ctx['screen_geo']
        off_x_phys, off_y_phys = ctx['offset_phys']
        dpr = ctx['dpr']

        # 1. Inform the overlay which screen we are on (Global Start Point)
        self.overlay.set_target_screen_offset(screen_geo.x(), screen_geo.y())

        mapped_rects = []
        for (rx, ry, rw, rh) in rects:
            # Detection results (rx, ry, rw, rh) are in physical pixels
            # relative to the haystack image (which is the full screen or cropped region)

            # 2. Add Crop Offset (Physical) - put it back in context of the full monitor
            total_x_phys = rx + off_x_phys
            total_y_phys = ry + off_y_phys

            # 3. Convert Physical to Logical (Divide by DPR)
            # This gives us coordinates relative to the TOP-LEFT of the SCREEN.
            # NOTE: This conversion is accurate because dpi_manager ensures
            # that we are getting true physical pixels, and Qt provides the correct DPR.
            log_x = total_x_phys / dpr
            log_y = total_y_phys / dpr
            log_w = rw / dpr
            log_h = rh / dpr

            # We send these LOCAL coordinates to the overlay.
            mapped_rects.append((log_x, log_y, log_w, log_h))

        self.overlay.update_rects(mapped_rects, 1.0)
        self.lbl_status.setText(f"Matches: {count} (FPS: {fps})")

    # --- Generation ---
    def save_image(self):
        if not self.template_image: return

        fname, _ = QFileDialog.getSaveFileName(self, "Save Image", "template.png", "Images (*.png)")
        if fname:
            if not fname.endswith('.png'): fname += '.png'
            try:
                self.template_image.save(fname)
                self.current_filename = os.path.basename(fname)
                self.is_image_unsaved = False

                self.btn_gen.setEnabled(True)
                self.lbl_status.setText(f"Saved: {self.current_filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save image: {e}")

    def generate_code(self):
        if not self.template_image: return

        # --- 1. Gather Basic Info ---
        # Use current filename if available, else default
        filename = self.current_filename if self.current_filename else "template.png"
        name = filename.replace('.png', '')

        # --- 2. Gather Widget Values ---
        screen_idx = self.cbo_screens.currentIndex()
        if screen_idx < 0: screen_idx = 0

        # Get Physical Resolution
        screen_obj = self.cbo_screens.currentData()
        geo = screen_obj.geometry()
        dpr = screen_obj.devicePixelRatio()
        phys_w = int(geo.width() * dpr)
        phys_h = int(geo.height() * dpr)

        # Get User Settings
        current_conf = float(self.lbl_conf_val.text())
        is_grayscale = self.chk_gray.isChecked()
        current_overlap = float(self.lbl_overlap_val.text())

        # --- 3. Build Parameters List (Only add if NOT default) ---
        # Default assumptions based on your functions:
        # confidence=0.9, grayscale=False, overlap_threshold=0.5, screen=0

        params = [f"'{filename}'"]  # First arg is always the image

        if self.search_region:
            params.append(f"region={self.search_region}")

        if screen_idx != 0:
            params.append(f"screen={screen_idx}")

        if is_grayscale:  # Default is False, so only add if True
            params.append(f"grayscale=True")

        if current_conf != 0.9:
            params.append(f"confidence={current_conf}")

        if current_overlap != 0.5:
            params.append(f"overlap_threshold={current_overlap}")

        # original_resolution defaults to None, but we always have a value here.
        # We include it to ensure resolution independence works.
        params.append(f"original_resolution=({phys_w}, {phys_h})")

        # --- 4. Build Code Block ---
        code_lines = []

        # Helper to generate click code cleanly
        def get_click_line(target_name):
            off_x = self.spin_off_x.value()
            off_y = self.spin_off_y.value()

            # Only add offset parameter if it is not (0,0)
            if off_x == 0 and off_y == 0:
                return f"    pyauto_desktop.clickimage({target_name})"
            else:
                return f"    pyauto_desktop.clickimage({target_name}, offset=({off_x}, {off_y}))"

        # Decide between Single (Best) vs Loop (All)
        if self.rdo_single.isChecked():
            # MODE: Best Match
            code_lines.append(f"{name} = pyauto_desktop.locateOnScreen({', '.join(params)})")
            code_lines.append(f"if {name}:")
            code_lines.append(f"    print(f'Found {name} at: {{{name}}}')")

            if self.chk_click.isChecked():
                code_lines.append(get_click_line(name))

        else:
            # MODE: All Matches (Loop)
            code_lines.append(f"{name}_matches = pyauto_desktop.locateAllOnScreen({', '.join(params)})")
            code_lines.append(f"for {name} in {name}_matches:")
            code_lines.append(f"    print(f'Found {name} at: {{{name}}}')")

            if self.chk_click.isChecked():
                code_lines.append(get_click_line(name))
                code_lines.append(f"    time.sleep(0.5)")

        code_block = "\n".join(code_lines)

        # --- 5. Output & Copy to Clipboard ---
        self.txt_output.setText(code_block)

        # This line ensures automatic copying
        QApplication.clipboard().setText(code_block)
        self.lbl_status.setText("Code copied to clipboard!")

    # --- Utils ---
    def pil2pixmap(self, image):
        if image.mode == "RGBA":
            data = image.tobytes("raw", "RGBA")
            qim = QImage(data, image.size[0], image.size[1], QImage.Format.Format_RGBA8888)
        else:
            data = image.convert("RGB").tobytes("raw", "RGB")
            qim = QImage(data, image.size[0], image.size[1], QImage.Format.Format_RGB888)
        return QPixmap.fromImage(qim)

    def qpixmap_to_pil(self, pixmap):
        """Convert QPixmap to PIL Image with error handling."""
        try:
            if pixmap.isNull():
                raise ValueError("Pixmap is null")

            qimg = pixmap.toImage()
            if qimg.isNull():
                raise ValueError("QImage conversion failed")

            qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
            width = qimg.width()
            height = qimg.height()

            if width <= 0 or height <= 0:
                raise ValueError(f"Invalid image dimensions: {width}x{height}")

            # Use constBits() for read-only access (safer)
            ptr = qimg.constBits()
            if ptr is None:
                raise ValueError("Failed to get image bits")

            # Calculate expected size
            expected_size = height * width * 4

            # Safely get the bytes - PyQt6 compatible approach
            try:
                # Set the size first
                ptr.setsize(expected_size)
                # Get bytes using asstring() (works in both PyQt5 and PyQt6)
                data_bytes = ptr.asstring()
            except (AttributeError, TypeError) as e:
                # Fallback: try alternative methods
                try:
                    # Try using memoryview
                    mv = memoryview(ptr)
                    data_bytes = mv.tobytes()
                except Exception:
                    # Last resort: save to buffer and read back
                    buffer = QBuffer()
                    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                    if qimg.save(buffer, "PNG"):
                        data_bytes = buffer.data().data()
                        # Parse PNG to get raw RGBA (simpler: just use the direct method)
                        # Actually, let's stick with the direct method
                        raise ValueError("Need direct pixel access")
                    else:
                        raise ValueError("Failed to save image to buffer")

            return Image.frombytes("RGBA", (width, height), data_bytes, "raw", "RGBA", 0, 1)
        except Exception as e:
            print(f"Error converting QPixmap to PIL: {e}")
            import traceback
            traceback.print_exc()
            # Return a dummy image to prevent crash
            return Image.new("RGBA", (1, 1), (0, 0, 0, 0))

    def closeEvent(self, event):
        self.is_detecting = False
        self.detection_timer.stop()
        if self.worker: self.worker.wait()
        self.overlay.close()
        event.accept()


def run_inspector():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_inspector()