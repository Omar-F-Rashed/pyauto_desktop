import sys
import os
import time
from PIL import Image
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QSlider,
                             QCheckBox, QTextEdit, QFileDialog, QGroupBox, QMessageBox, QComboBox, QSpinBox,
                             QRadioButton, QFrame)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QSize
from PyQt6.QtGui import QPixmap, QImage, QIcon

from .style import DARK_THEME
from .capture_tool import SnippingController
from .overlay import Overlay
from .detection import DetectionWorker
from .editor import MagicWandEditor
from .utils import global_to_local, logical_to_physical, physical_to_logical
from .functions import get_monitors_safe

if sys.platform == "win32":
    import ctypes

    user32 = ctypes.windll.user32
    WDA_EXCLUDEFROMCAPTURE = 0x00000011


    def set_window_display_affinity(hwnd, affinity):
        try:
            user32.SetWindowDisplayAffinity(hwnd, affinity)
            pass
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
            self.setStyleSheet("")
            self.btn_close.hide()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Desktop Inspector")
        self.resize(550, 850)
        self.setStyleSheet(DARK_THEME)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

        # -- MONITOR SPECS TRACKING --
        # Used to enforce that all captures happen on compatible monitors
        # Format: {'dpr': float, 'res': (width, height)}
        self.primary_specs = None

        self.template_image = None
        self.search_region = None  # Physical Rect
        self.current_scale = 1.0
        self.is_image_unsaved = False
        self.current_filename = None
        self.last_save_dir = ""

        self.anchor_image = None
        self.anchor_rect = None  # Physical Rect
        self.target_rect = None  # Physical Rect
        self.anchor_filename = None
        self.is_anchor_unsaved = False

        self.snip_controller = SnippingController()
        self.snip_controller.finished.connect(self.on_snip_finished)
        self.active_snip_mode = None

        self.overlay = Overlay()
        if sys.platform == "win32":
            self.overlay.winId()
            set_window_display_affinity(int(self.overlay.winId()), WDA_EXCLUDEFROMCAPTURE)

        self.detection_timer = QTimer(self)
        self.detection_timer.timeout.connect(self.detection_step)
        self.is_detecting = False
        self.worker = None
        self.worker_running = False
        self.last_fps_time = 0

        self.detection_context = {}

        self.initUI()

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        lbl_title = QLabel("Inspector")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #0d6efd;")
        layout.addWidget(lbl_title, alignment=Qt.AlignmentFlag.AlignCenter)

        grp_cap = QGroupBox("1. Image & Region")
        cap_layout = QVBoxLayout()

        self.chk_anchor_mode = QCheckBox("Use Anchor Image (Relative Search)")
        self.chk_anchor_mode.setStyleSheet("font-weight: bold; color: #ffc107;")
        self.chk_anchor_mode.stateChanged.connect(self.toggle_anchor_ui)
        cap_layout.addWidget(self.chk_anchor_mode)

        self.frm_anchor = QFrame()
        self.frm_anchor.setVisible(False)
        anchor_layout = QVBoxLayout(self.frm_anchor)

        hbox_anchor_btn = QHBoxLayout()
        self.btn_snip_anchor = QPushButton("1. Snip Anchor")
        self.btn_snip_anchor.clicked.connect(self.start_snip_anchor)
        hbox_anchor_btn.addWidget(self.btn_snip_anchor)

        self.btn_save_anchor = QPushButton("Save")
        self.btn_save_anchor.clicked.connect(self.save_anchor_image)
        self.btn_save_anchor.setEnabled(False)
        hbox_anchor_btn.addWidget(self.btn_save_anchor)

        anchor_layout.addLayout(hbox_anchor_btn)

        hbox_anchor_margin = QHBoxLayout()
        self.chk_anchor_margin = QCheckBox("Search Margin")
        self.chk_anchor_margin.setChecked(True)
        self.chk_anchor_margin.stateChanged.connect(self.toggle_margin_inputs)

        self.spin_margin_x = QSpinBox()
        self.spin_margin_x.setRange(0, 9999)
        self.spin_margin_x.setValue(20)
        self.spin_margin_x.setSuffix(" px")
        self.spin_margin_x.setToolTip("Horizontal Margin (Left/Right)")

        self.spin_margin_y = QSpinBox()
        self.spin_margin_y.setRange(0, 9999)
        self.spin_margin_y.setValue(20)
        self.spin_margin_y.setSuffix(" px")
        self.spin_margin_y.setToolTip("Vertical Margin (Top/Bottom)")

        hbox_anchor_margin.addWidget(self.chk_anchor_margin)
        hbox_anchor_margin.addWidget(QLabel("X:"))
        hbox_anchor_margin.addWidget(self.spin_margin_x)
        hbox_anchor_margin.addWidget(QLabel("Y:"))
        hbox_anchor_margin.addWidget(self.spin_margin_y)

        anchor_layout.addLayout(hbox_anchor_margin)

        self.lbl_anchor_preview = ClickableDropLabel("Click or Drop Target Image Here\n(PNG, JPG, BMP)")
        self.lbl_anchor_preview.clicked.connect(lambda: self.request_upload_image(mode='anchor'))
        self.lbl_anchor_preview.file_dropped.connect(lambda p: self.handle_dropped_image(p, mode='anchor'))
        self.lbl_anchor_preview.setFixedHeight(120)
        self.lbl_anchor_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        anchor_layout.addWidget(self.lbl_anchor_preview)

        cap_layout.addWidget(self.frm_anchor)

        hbox_btns = QHBoxLayout()
        self.btn_snip = QPushButton("Snip Target Image")
        self.btn_snip.clicked.connect(self.start_snip_template)

        self.btn_region = RegionButton("Set Search Region")
        self.btn_region.clicked.connect(self.start_snip_region)
        self.btn_region.setObjectName("secondary_btn")
        self.btn_region.reset_clicked.connect(self.reset_region)

        hbox_btns.addWidget(self.btn_snip)
        hbox_btns.addWidget(self.btn_region)

        self.btn_reedit = QPushButton("Edit Target Image")
        self.btn_reedit.clicked.connect(self.reedit_template)
        self.btn_reedit.setEnabled(False)
        self.btn_reedit.setObjectName("secondary_btn")

        self.lbl_preview = ClickableDropLabel("Click or Drop Target Image Here\n(PNG, JPG, BMP)")
        self.lbl_preview.clicked.connect(lambda: self.request_upload_image(mode='target'))
        self.lbl_preview.file_dropped.connect(lambda p: self.handle_dropped_image(p, mode='target'))
        self.lbl_preview.setFixedHeight(120)

        self.lbl_region_status = QLabel("Region: Full Screen")
        self.lbl_region_status.setStyleSheet("color: #888; font-size: 12px;")

        cap_layout.addLayout(hbox_btns)
        cap_layout.addWidget(self.btn_reedit)
        cap_layout.addWidget(self.lbl_preview)
        cap_layout.addWidget(self.lbl_region_status)
        grp_cap.setLayout(cap_layout)
        layout.addWidget(grp_cap)

        grp_test = QGroupBox("2. Live Test & Action")
        test_layout = QVBoxLayout()

        hbox_conf = QHBoxLayout()
        hbox_conf.addWidget(QLabel("Confidence:"))
        self.slider_conf = QSlider(Qt.Orientation.Horizontal)
        self.slider_conf.setRange(50, 99)
        self.slider_conf.setValue(90)
        self.slider_conf.valueChanged.connect(self.update_conf_label)
        self.lbl_conf_val = QLabel("0.90")
        hbox_conf.addWidget(self.slider_conf)
        hbox_conf.addWidget(self.lbl_conf_val)

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

        hbox_click = QHBoxLayout()
        self.chk_click = QCheckBox("Simulate Click")
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

        hbox_screen = QHBoxLayout()
        self.cbo_screens = QComboBox()
        hbox_screen.addWidget(QLabel("Detect On:"))
        hbox_screen.addWidget(self.cbo_screens)
        self.populate_screens()

        hbox_scaling = QHBoxLayout()
        hbox_scaling.addWidget(QLabel("Scaling Strategy:"))
        self.cbo_scaling = QComboBox()
        self.cbo_scaling.addItem("DPR Awareness", "dpr")
        self.cbo_scaling.addItem("Resolution Matching", "resolution")
        self.cbo_scaling.setToolTip(
            "DPR: For non-full screen applications (browser, office apps, etc) \nResolution: Full screen applications like games.")
        hbox_scaling.addWidget(self.cbo_scaling)

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
        test_layout.addLayout(hbox_click)
        test_layout.addLayout(hbox_screen)
        test_layout.addLayout(hbox_scaling)
        test_layout.addLayout(hbox_ctrl)
        test_layout.addWidget(self.btn_start)
        test_layout.addWidget(self.lbl_status)
        grp_test.setLayout(test_layout)
        layout.addWidget(grp_test)

        grp_out = QGroupBox("3. Generate Code")
        out_layout = QVBoxLayout()

        hbox_mode = QHBoxLayout()
        self.rdo_single = QRadioButton("Best Match (Single)")
        self.rdo_single.setChecked(True)
        self.rdo_all = QRadioButton("All Matches (Loop)")
        hbox_mode.addWidget(self.rdo_single)
        hbox_mode.addWidget(self.rdo_all)
        out_layout.addLayout(hbox_mode)

        hbox_gen = QHBoxLayout()
        self.btn_save = QPushButton("Save Target")
        self.btn_save.clicked.connect(self.save_image)
        self.btn_save.setEnabled(False)

        self.btn_gen = QPushButton("Generate Code")
        self.btn_gen.clicked.connect(self.generate_code)
        self.btn_gen.setEnabled(False)

        hbox_gen.addWidget(self.btn_save)
        hbox_gen.addWidget(self.btn_gen)

        out_layout.addLayout(hbox_gen)

        self.txt_output = QTextEdit()
        self.txt_output.setPlaceholderText("Generated code will appear here...")
        self.txt_output.setFixedHeight(120)
        out_layout.addWidget(self.txt_output)

        grp_out.setLayout(out_layout)
        layout.addWidget(grp_out)

        primary = QApplication.primaryScreen()
        if primary:
            self.primary_specs = {
                'dpr': primary.devicePixelRatio(),
                'res': (primary.geometry().width(), primary.geometry().height())
            }

    def populate_screens(self):
        monitor_rects = get_monitors_safe()
        q_screens = QApplication.screens()
        self.cbo_screens.clear()

        for i, (mx, my, mw, mh) in enumerate(monitor_rects):
            matched_q_screen = None
            for qs in q_screens:
                geo = qs.geometry()
                if geo.x() == mx and geo.y() == my:
                    matched_q_screen = qs
                    break
            if not matched_q_screen and i < len(q_screens):
                matched_q_screen = q_screens[i]

            label = f"Screen {i} [Pos: {mx},{my}] ({mw}x{mh})"
            self.cbo_screens.addItem(label, matched_q_screen)

    def toggle_anchor_ui(self, state):
        is_anchor_on = (state == Qt.CheckState.Checked.value)
        self.frm_anchor.setVisible(is_anchor_on)

        if is_anchor_on:
            self.btn_snip.setText("2. Snip Target Image")
        else:
            self.btn_snip.setText("Snip Target Image")

    def toggle_margin_inputs(self, state):
        enabled = (state == Qt.CheckState.Checked.value)
        self.spin_margin_x.setEnabled(enabled)
        self.spin_margin_y.setEnabled(enabled)

    def update_conf_label(self):
        val = self.slider_conf.value() / 100.0
        self.lbl_conf_val.setText(f"{val:.2f}")

    def update_overlap_label(self):
        val = self.slider_overlap.value() / 100.0
        self.lbl_overlap_val.setText(f"{val:.2f}")

    def update_overlay_click_settings(self):
        self.overlay.set_click_config(
            self.chk_click.isChecked(),
            self.spin_off_x.value(),
            self.spin_off_y.value()
        )

    def start_snip_template(self):
        self.hide()
        self.active_snip_mode = 'template'
        self.snip_controller.start()

    def start_snip_anchor(self):
        self.hide()
        self.active_snip_mode = 'anchor'
        self.snip_controller.start()

    def start_snip_region(self):
        self.hide()
        self.active_snip_mode = 'region'
        self.snip_controller.start()

    def _optimize_image(self, img):
        if img.mode == 'RGBA':
            extrema = img.getextrema()
            if extrema[3][0] == 255:
                return img.convert('RGB')
        return img

    def on_snip_finished(self, pixmap, physical_rect, target_screen):
        self.show()
        if not target_screen:
            self.active_snip_mode = None
            return

        x, y, w, h = physical_rect
        if w < 5 or h < 5:
            self.active_snip_mode = None
            return

        captured_dpr = target_screen.devicePixelRatio()
        captured_res =(target_screen.geometry().width()*captured_dpr, target_screen.geometry().height()*captured_dpr)

        # print(f"Captured on Screen: {captured_res} @ DPR {captured_dpr}")

        is_anchor_mode = self.chk_anchor_mode.isChecked()
        is_primary = False
        primary_name = "Target Image"

        if is_anchor_mode:
            primary_name = "Anchor Image"
            if self.active_snip_mode == 'anchor':
                is_primary = True
        else:
            if self.active_snip_mode == 'template':
                is_primary = True

        if is_primary:
            # We are updating the Primary Element.
            # Check if we changed monitors.
            specs_changed = False
            if self.primary_specs:
                if (self.primary_specs['dpr'] != captured_dpr) or (self.primary_specs['res'] != captured_res):
                    specs_changed = True
            else:
                specs_changed = True  # First time setting

            self.primary_specs = {'dpr': captured_dpr, 'res': captured_res}

            if specs_changed:
                # print("Primary monitor specs changed. Resetting secondary elements.")
                self.reset_secondary_elements(is_anchor_mode)

        else:
            # We are updating a Secondary Element.
            # It MUST match the Primary Specs.
            if self.primary_specs:
                m_dpr = self.primary_specs['dpr']
                m_res = self.primary_specs['res']

                if (captured_dpr != m_dpr) or (captured_res != m_res):
                    QMessageBox.critical(
                        self,
                        "Monitor Mismatch",
                        f"Capture Rejected!\n\n"
                        f"You are trying to capture a secondary element on a different monitor than your {primary_name}.\n\n"
                        f"Required Monitor: {m_res} @ DPR {m_dpr}\n"
                        f"Current Monitor: {captured_res} @ DPR {captured_dpr}\n\n"
                        f"To switch monitors, please re-capture the {primary_name} on the new monitor first."
                    )
                    self.active_snip_mode = None
                    return
            else:
                # Fallback: If no primary exists yet, set this as primary specs
                self.primary_specs = {'dpr': captured_dpr, 'res': captured_res}

        if self.active_snip_mode == 'template':
            pil_image = self.qpixmap_to_pil(pixmap)
            edited_img = self.open_editor(pil_image)

            if edited_img:
                edited_img = self._optimize_image(edited_img)
                self.template_image = edited_img
                self.is_image_unsaved = True
                self.current_filename = None
                self.btn_gen.setEnabled(False)
                self.target_rect = physical_rect
                self.update_preview()
                self.btn_start.setEnabled(True)
                self.btn_start.setText("Start Detection")
                self.btn_reedit.setEnabled(True)
                self.btn_save.setEnabled(True)

        elif self.active_snip_mode == 'anchor':
            pil_image = self.qpixmap_to_pil(pixmap)
            edited_img = self.open_editor(pil_image)
            if edited_img:
                edited_img = self._optimize_image(edited_img)
                self.anchor_image = edited_img
                self.anchor_rect = physical_rect
                self.is_anchor_unsaved = True
                self.anchor_filename = None
                self.update_anchor_preview()
                self.btn_save_anchor.setEnabled(True)
                self.btn_gen.setEnabled(False)

        elif self.active_snip_mode == 'region':
            self.search_region = physical_rect
            # Using physical rect directly without logical conversion
            self.lbl_region_status.setText(f"Region: {self.search_region}")
            self.btn_region.set_active(True)

        self.active_snip_mode = None

    def reset_secondary_elements(self, is_anchor_mode):
        # Always reset search region as it is secondary in both modes
        self.reset_region()

        if is_anchor_mode:
            # In Anchor Mode, Target Image is also secondary
            self.template_image = None
            self.target_rect = None
            self.current_filename = None
            self.is_image_unsaved = False
            self.lbl_preview.setText("Click or Drop Target Image Here\n(PNG, JPG, BMP)")
            self.lbl_preview.setPixmap(QPixmap())
            self.btn_start.setEnabled(False)
            self.btn_reedit.setEnabled(False)
            self.btn_save.setEnabled(False)
            self.btn_gen.setEnabled(False)

    def reset_region(self):
        self.search_region = None
        self.lbl_region_status.setText("Region: Full Screen")
        self.btn_region.set_active(False)

    def request_upload_image(self, mode='target'):
        current_img = self.template_image if mode == 'target' else self.anchor_image
        label = "Target" if mode == 'target' else "Anchor"

        if current_img:
            if QMessageBox.question(self, "Replace?", f"Replace current {label} image?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.No:
                return

        fname, _ = QFileDialog.getOpenFileName(self, f"Open {label} Image", "", "Images (*.png *.jpg *.bmp)")
        if fname:
            self.process_loaded_image(fname, mode)

    def handle_dropped_image(self, path, mode='target'):
        current_img = self.template_image if mode == 'target' else self.anchor_image
        label = "Target" if mode == 'target' else "Anchor"

        if current_img:
            if QMessageBox.question(self, "Replace?", f"Replace current {label} image?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.No:
                return

        self.process_loaded_image(path, mode)

    def process_loaded_image(self, path, mode='target'):
        try:
            img = Image.open(path)
            edited_img = self.open_editor(img)
            if not edited_img: return

            filename = os.path.basename(path)

            if mode == 'target':
                self.template_image = edited_img
                self.current_filename = filename
                self.target_rect = None
                self.is_image_unsaved = False
                self.current_scale = QApplication.primaryScreen().devicePixelRatio()

                self.update_preview()
                self.btn_start.setEnabled(True)
                self.btn_start.setText("Start Detection")
                self.btn_reedit.setEnabled(True)
                self.btn_save.setEnabled(True)

            elif mode == 'anchor':
                self.anchor_image = edited_img
                self.anchor_filename = filename
                self.anchor_rect = None
                self.is_anchor_unsaved = False

                self.update_anchor_preview()
                self.btn_save_anchor.setEnabled(True)

            self.check_gen_enable()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load image:\n{e}")

    def reedit_template(self):
        if self.template_image:
            edited_img = self.open_editor(self.template_image)
            if edited_img:
                self.template_image = edited_img
                self.update_preview()

    def open_editor(self, pil_img):
        editor = MagicWandEditor(pil_img, self)
        if editor.exec():
            return editor.get_result()
        return None

    def update_preview(self):
        if not self.template_image: return
        qim = self.pil2pixmap(self.template_image)
        self.lbl_preview.setPixmap(
            qim.scaled(self.lbl_preview.width(), self.lbl_preview.height(), Qt.AspectRatioMode.KeepAspectRatio))

    def update_anchor_preview(self):
        if not self.anchor_image: return
        qim = self.pil2pixmap(self.anchor_image)
        self.lbl_anchor_preview.setPixmap(
            qim.scaled(self.lbl_anchor_preview.width(), self.lbl_anchor_preview.height(),
                       Qt.AspectRatioMode.KeepAspectRatio))
        self.lbl_anchor_preview.setText("")

    def toggle_detection(self):
        if self.is_detecting:
            self.is_detecting = False
            self.detection_timer.stop()
            self.overlay.hide()
            self.btn_start.setText("Start Detection")
            self.btn_start.setStyleSheet("background-color: #198754;")
            self.set_controls_enabled(True)
        else:
            if not self.template_image: return

            use_anchor = self.chk_anchor_mode.isChecked()

            if use_anchor:
                if not self.anchor_image:
                    QMessageBox.warning(self, "Anchor Missing", "Please snip an anchor image first.")
                    return

                if not (self.anchor_rect and self.target_rect):
                    if QMessageBox.warning(self, "Spatial Data Missing",
                                           "Images were not snipped in this session (no coordinates).\n"
                                           "Cannot calculate relative offset automatically.\n"
                                           "Continue with zero offset?",
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.No:
                        return
            if self.chk_gray.isChecked() and self.template_image.mode in ('RGBA', 'LA'):
                if self.template_image.getextrema()[-1][0] < 255:
                    if QMessageBox.question(self, "Warning", "Grayscale with transparency enabled. Disable grayscale?",
                                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                        self.chk_gray.setChecked(False)

            self.is_detecting = True
            self.update_overlay_click_settings()
            self.last_fps_time = time.time()
            self.overlay.show()
            self.detection_timer.start(10)
            self.btn_start.setText("Stop Detection")
            self.btn_start.setStyleSheet("background-color: #dc3545;")
            self.set_controls_enabled(False)

    def set_controls_enabled(self, enabled):
        self.btn_snip.setEnabled(enabled)
        self.btn_reedit.setEnabled(enabled)
        self.lbl_preview.setEnabled(enabled)
        self.cbo_screens.setEnabled(enabled)
        self.btn_save.setEnabled(enabled)
        self.chk_anchor_mode.setEnabled(enabled)
        self.btn_snip_anchor.setEnabled(enabled)
        self.btn_gen.setEnabled(enabled and not self.is_image_unsaved)
        self.cbo_scaling.setEnabled(enabled)

    def detection_step(self):
        if self.worker_running or not self.is_detecting: return
        if not self.template_image: self.toggle_detection(); return

        target_screen_idx = self.cbo_screens.currentIndex()
        if target_screen_idx < 0: target_screen_idx = 0

        target_screen_obj = self.cbo_screens.currentData()
        if not target_screen_obj: target_screen_obj = QApplication.primaryScreen()

        # Capture Source Specs (Passed to worker, no local resizing)
        source_dpr = self.primary_specs['dpr'] if self.primary_specs else 1.0
        source_res = self.primary_specs['res'] if self.primary_specs else (1920, 1080)

        selected_scaling = self.cbo_scaling.currentData()

        img_to_pass = self.template_image

        local_region = self.search_region

        self.detection_context = {
            'screen_geo': target_screen_obj.geometry(),
            'dpr': target_screen_obj.devicePixelRatio(),
            'source_dpr': source_dpr
        }

        self.worker_running = True
        conf = self.slider_conf.value() / 100.0
        gray = self.chk_gray.isChecked()
        overlap = self.slider_overlap.value() / 100.0

        use_anchor = self.chk_anchor_mode.isChecked()
        anchor_img = self.anchor_image if use_anchor else None
        anchor_conf = None

        if use_anchor and self.anchor_rect and self.target_rect:
            ax, ay, _, _ = self.anchor_rect
            tx, ty, tw, th = self.target_rect

            offset_x = tx - ax
            offset_y = ty - ay

            use_margin = self.chk_anchor_margin.isChecked()
            mx_log = self.spin_margin_x.value() if use_margin else 0
            my_log = self.spin_margin_y.value() if use_margin else 0

            mx_phys, my_phys, _, _ = logical_to_physical((mx_log, my_log, 0, 0), source_dpr)

            anchor_conf = {
                'offset_x': offset_x,
                'offset_y': offset_y,
                'w': tw,
                'h': th,
                'margin_x': mx_phys,
                'margin_y': my_phys
            }

        self.worker = DetectionWorker(
            template_img=img_to_pass,
            screen_idx=target_screen_idx,
            confidence=conf,
            grayscale=gray,
            overlap_threshold=overlap,
            anchor_img=anchor_img,
            anchor_config=anchor_conf,
            search_region=local_region,
            source_dpr=source_dpr,
            source_resolution=source_res,
            scaling_type=selected_scaling
        )
        self.worker.result_signal.connect(self.on_detection_result)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_worker_finished(self):
        self.worker_running = False
        self.worker = None

    def on_detection_result(self, rects, anchors, regions, count):
        if not self.is_detecting: return

        curr_time = time.time()
        dt = curr_time - self.last_fps_time
        self.last_fps_time = curr_time
        fps = int(1.0 / dt) if dt > 0 else 0

        ctx = self.detection_context
        screen_geo = ctx['screen_geo']
        dpr = ctx['dpr']
        source_dpr = ctx.get('source_dpr', dpr)

        self.overlay.set_target_screen_offset(screen_geo.x(), screen_geo.y())

        def map_rects(raw_rects):
            mapped = []
            for r in raw_rects:
                lx, ly, lw, lh = physical_to_logical(r, dpr)
                mapped.append((lx, ly, lw, lh))
            return mapped

        mapped_rects = map_rects(rects)
        mapped_anchors = map_rects(anchors)
        mapped_regions = map_rects(regions)

        self.overlay.update_rects(mapped_rects, mapped_anchors, mapped_regions, source_dpr)

        status_msg = f"Matches: {count} (FPS: {fps})"
        if anchors:
            status_msg += f" | Anchors: {len(anchors)}"
        self.lbl_status.setText(status_msg)

    def save_image(self):
        if not self.template_image: return
        name = self._save_image_dialog(self.template_image, "target.png")
        if name:
            self.current_filename = name
            self.is_image_unsaved = False
            self.check_gen_enable()

    def save_anchor_image(self):
        if not self.anchor_image: return
        name = self._save_image_dialog(self.anchor_image, "anchor.png")
        if name:
            self.anchor_filename = name
            self.is_anchor_unsaved = False
            self.btn_save_anchor.setEnabled(False)
            self.check_gen_enable()

    def _save_image_dialog(self, img, default_name):
        start_path = os.path.join(self.last_save_dir, default_name) if self.last_save_dir else default_name
        fname, _ = QFileDialog.getSaveFileName(self, "Save Image", start_path, "Images (*.png)")
        if fname:
            self.last_save_dir = os.path.dirname(fname)
            if not fname.endswith('.png'): fname += '.png'
            try:
                img.save(fname)
                self.lbl_status.setText(f"Saved: {os.path.basename(fname)}")
                return os.path.basename(fname)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save: {e}")
        return None

    def check_gen_enable(self):
        if self.is_image_unsaved:
            self.btn_gen.setEnabled(False)
            return

        if self.chk_anchor_mode.isChecked():
            if not self.anchor_image or self.is_anchor_unsaved:
                self.btn_gen.setEnabled(False)
                return

        self.btn_gen.setEnabled(True)

    def generate_code(self):
        if not self.template_image: return

        m_res = self.primary_specs['res'] if self.primary_specs else (1920, 1080)
        phys_w, phys_h = m_res

        conf = float(self.lbl_conf_val.text())
        gray = self.chk_gray.isChecked()
        overlap = float(self.lbl_overlap_val.text())

        screen_idx = self.cbo_screens.currentIndex()
        use_screen_arg = (screen_idx > 0)

        def build_params(img_name, region_var=None):
            p = [f"'images/{img_name}'"]
            if region_var:
                p.append(f"region={region_var}")
            elif self.search_region and not self.chk_anchor_mode.isChecked():
                p.append(f"region={self.search_region}")

            if use_screen_arg: p.append(f"screen={screen_idx}")
            if gray: p.append(f"grayscale=True")
            if conf != 0.9: p.append(f"confidence={conf}")
            if overlap != 0.5: p.append(f"overlap_threshold={overlap}")
            return ", ".join(p)

        code_lines = []

        target_name = self.current_filename.replace('.png', '')
        dpr = self.primary_specs['dpr'] if self.primary_specs else 1.0
        code_lines.append(
            f'screen{screen_idx} = pyauto_desktop.Session(screen={screen_idx}, source_resolution=({int(m_res[0])}, {int(m_res[1])}), source_dpr={dpr}))')

        def get_click_line(var_name, indent="    "):
            off_x = self.spin_off_x.value()
            off_y = self.spin_off_y.value()
            if off_x == 0 and off_y == 0:
                return f"{indent}screen{screen_idx}.clickImage({var_name})"
            return f"{indent}screen{screen_idx}.clickImage({var_name}, offset=({off_x}, {off_y}))"

        if self.chk_anchor_mode.isChecked():
            if not self.anchor_filename: return
            anchor_name = self.anchor_filename.replace('.png', '')

            if not self.anchor_rect or not self.target_rect:
                code_lines.append("# WARNING: Coordinates missing. Using default offset.")
                ax, ay, aw, ah = 0, 0, 100, 100
                tx, ty, tw, th = 0, 0, 100, 100
            else:
                ax, ay, aw, ah = self.anchor_rect
                tx, ty, tw, th = self.target_rect

            rel_x = tx - ax
            rel_y = ty - ay

            mx_log = self.spin_margin_x.value()
            my_log = self.spin_margin_y.value()


            mx, my, _, _ = logical_to_physical((mx_log, my_log, 0, 0), dpr)
            code_lines.append(
                f"{anchor_name}_matches = screen{screen_idx}.locateAllOnScreen({build_params(self.anchor_filename)})")
            code_lines.append(f"for {anchor_name} in {anchor_name}_matches:")
            code_lines.append(f"    ax, ay, aw, ah = {anchor_name}")

            sign_x = "+" if rel_x >= 0 else "-"
            sign_y = "+" if rel_y >= 0 else "-"

            final_w = tw + (mx * 2)
            final_h = th + (my * 2)

            code_lines.append(
                f"    search_region = (ax {sign_x} {abs(rel_x)} - {mx}, ay {sign_y} {abs(rel_y)} - {my}, {final_w}, {final_h})"
            )

            params = build_params(self.current_filename, 'search_region')
            code_lines.append(f"    {target_name}_match = screen{screen_idx}.locateOnScreen({params})")
            code_lines.append(f"    if {target_name}_match:")
            code_lines.append(f"        print(f'Found {target_name} at: {{{target_name}_match}}')")
            if self.chk_click.isChecked():
                code_lines.append(get_click_line(f"{target_name}_match", "        "))

            if self.rdo_single.isChecked():
                code_lines.append(f"        break")
            else:
                if self.chk_click.isChecked():
                    code_lines.append(f"        time.sleep(0.5)")

        else:
            params = build_params(self.current_filename)
            if self.rdo_single.isChecked():
                code_lines.append(f"{target_name} = screen{screen_idx}.locateOnScreen({params})")
                code_lines.append(f"if {target_name}:")
                code_lines.append(f"    print(f'Found {target_name} at: {{{target_name}}}')")
                if self.chk_click.isChecked():
                    code_lines.append(get_click_line(target_name))
            else:
                code_lines.append(f"{target_name}_matches = screen{screen_idx}.locateAllOnScreen({params})")
                code_lines.append(f"for {target_name} in {target_name}_matches:")
                code_lines.append(f"    print(f'Found {target_name} at: {{{target_name}}}')")
                if self.chk_click.isChecked():
                    code_lines.append(get_click_line(target_name))
                    code_lines.append(f"    time.sleep(0.5)")

        code_block = "\n".join(code_lines)
        self.txt_output.setText(code_block)
        QApplication.clipboard().setText(code_block)
        self.lbl_status.setText("Code copied to clipboard!")

    def pil2pixmap(self, image):
        if image.mode == "RGBA":
            data = image.tobytes("raw", "RGBA")
            qim = QImage(data, image.size[0], image.size[1], QImage.Format.Format_RGBA8888)
        else:
            data = image.convert("RGB").tobytes("raw", "RGB")
            stride = image.size[0] * 3
            qim = QImage(data, image.size[0], image.size[1], stride, QImage.Format.Format_RGB888)
        return QPixmap.fromImage(qim.copy())

    def qpixmap_to_pil(self, pixmap):
        try:
            if pixmap.isNull(): raise ValueError("Pixmap is null")
            qimg = pixmap.toImage()
            qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
            width = qimg.width()
            height = qimg.height()
            ptr = qimg.constBits()
            if ptr is None: raise ValueError("Failed to get image bits")
            try:
                ptr.setsize(height * width * 4)
                data_bytes = ptr.asstring()
            except (AttributeError, TypeError):
                data_bytes = qimg.bits().asstring(height * width * 4)

            return Image.frombytes("RGBA", (width, height), data_bytes, "raw", "RGBA", 0, 1)
        except Exception as e:
            print(f"Error converting QPixmap to PIL: {e}")
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
    app.exec()


if __name__ == "__main__":
    run_inspector()