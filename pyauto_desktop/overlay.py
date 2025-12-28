import logging
from typing import List, Tuple, Optional

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPaintEvent

from .functions import get_monitors_safe, get_monitor_dpr
from .utils import local_to_global


class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self._setup_ui_flags()
        self._init_attributes()
        self._update_geometry()

    def _setup_ui_flags(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _init_attributes(self):
        self.target_offset_x: int = 0
        self.target_offset_y: int = 0

        self.show_click: bool = False
        self.click_offset_x: int = 0
        self.click_offset_y: int = 0

        self.rects: List[Tuple[int, int, int, int]] = []
        self.anchors: List[Tuple[int, int, int, int]] = []
        self.regions: List[Tuple[int, int, int, int]] = []
        self.scale_factor: float = 1.0

        self.font_idx = QFont("Arial", 10, QFont.Weight.Bold)

    def _update_geometry(self):
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

    def set_target_screen_offset(self, x: int, y: int):
        self.target_offset_x = x
        self.target_offset_y = y

    def set_click_config(self, show: bool, off_x: int, off_y: int):
        self.show_click = show
        self.click_offset_x = off_x
        self.click_offset_y = off_y
        self.update()

    def update_rects(self, rects: list, anchors: list, regions: list, scale_factor: float):
        self.rects = rects
        self.anchors = anchors
        self.regions = regions
        self.scale_factor = scale_factor
        self.update()

    def _get_matching_monitor(self, monitor_list: list, tx: int, ty: int) -> Optional[tuple]:
        for i, monitor in enumerate(monitor_list):
            if monitor[0] == tx and monitor[1] == ty:
                return i, monitor
        return None

    def paintEvent(self, event: QPaintEvent):
        if not (self.rects or self.anchors or self.regions):
            return

        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setFont(self.font_idx)

            styles = {
                'box': {
                    'pen': QPen(QColor(0, 255, 0), 2),
                    'brush': QColor(0, 255, 0, 50)
                },
                'anchor': {
                    'pen': QPen(QColor(0, 100, 255), 2),
                    'brush': QColor(0, 100, 255, 30)
                },
                'region': {
                    'pen': QPen(QColor(255, 200, 0), 2),
                    'brush': QColor(255, 200, 0, 10)
                },
                'click_dot': {
                    'pen': QPen(QColor(255, 0, 0), 2),
                    'brush': QBrush(QColor(255, 0, 0))
                },
                'text': {
                    'bg_brush': QBrush(QColor(0, 0, 0, 180)),
                    'pen': QPen(QColor(255, 255, 255)),
                    'anchor_pen': QPen(QColor(100, 200, 255))
                }
            }

            styles['anchor']['pen'].setStyle(Qt.PenStyle.DashLine)
            styles['region']['pen'].setStyle(Qt.PenStyle.DotLine)

            monitors = get_monitors_safe()

            if self.regions:
                self._draw_element_group(
                    painter, self.regions, monitors, styles['region'], styles['text'],
                    label_prefix="R", is_region=True
                )

            if self.anchors:
                self._draw_element_group(
                    painter, self.anchors, monitors, styles['anchor'], styles['text'],
                    label_prefix="A", is_anchor=True
                )

            if self.rects:
                self._draw_element_group(
                    painter, self.rects, monitors, styles['box'], styles['text'],
                    label_prefix="#", click_style=styles['click_dot']
                )

        except Exception as e:
            print(f"Overlay paint error: {e}")

    def _draw_element_group(self, painter: QPainter, rect_list: list, monitors: list,
                            style: dict, text_style: dict, label_prefix: str,
                            is_anchor: bool = False, is_region: bool = False, click_style: dict = None):
        painter.setPen(style['pen'])
        painter.setBrush(style['brush'])

        _idxscreen, selected_monitor = self._get_matching_monitor(monitors, self.target_offset_x, self.target_offset_y)

        if not selected_monitor:
            return

        dpr = self.devicePixelRatioF()
        for i, (x, y, w, h) in enumerate(rect_list):
            gx, gy, _, _ = local_to_global((x, y, w, h), (self.target_offset_x, self.target_offset_y))
            global_point = QPoint(int(gx), int(gy))

            max_x = (x + w) * dpr
            max_y = (y + h) * dpr

            if x * dpr > selected_monitor[2] or y * dpr > selected_monitor[3]:
                continue
            elif x < 0:
                x = 0
            elif y < 0:
                y = 0
            elif max_x > selected_monitor[2]:
                w = w - (max_x - selected_monitor[2]) / dpr
            elif max_y > selected_monitor[3]:
                h = h - (max_y - selected_monitor[3]) / dpr
            top_left_local = self.mapFromGlobal(QPoint(int(gx), int(gy)))

            scaling = self.scale_factor/get_monitor_dpr(_idxscreen, monitors)


            draw_x = top_left_local.x()
            draw_y = top_left_local.y()
            draw_w = int(round(w)/scaling)
            draw_h = int(round(h)/scaling)

            painter.drawRect(draw_x, draw_y, draw_w, draw_h)

            if is_region:
                continue

            label_text = f"{label_prefix}{i}"
            fm = painter.fontMetrics()
            text_w = fm.horizontalAdvance(label_text) + 8
            text_h = fm.height() + 4

            label_x = draw_x
            label_y = draw_y - text_h
            if label_y < 0:
                label_y = draw_y

            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(text_style['bg_brush'])
            painter.drawRect(label_x, label_y, text_w, text_h)
            painter.restore()

            painter.save()
            painter.setPen(text_style['anchor_pen'] if is_anchor else text_style['pen'])
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(QRect(label_x, label_y, text_w, text_h),
                             Qt.AlignmentFlag.AlignCenter, label_text)
            painter.restore()

            if not is_anchor and not is_region and self.show_click and click_style:
                center_x = draw_x + (draw_w / 2)
                center_y = draw_y + (draw_h / 2)

                target_x = center_x + self.click_offset_x
                target_y = center_y + self.click_offset_y

                local_target_x = x + (draw_w / 2) + self.click_offset_x
                local_target_y = y + (draw_h / 2) + self.click_offset_y
                dpr_target_x = local_target_x * dpr
                dpr_target_y = local_target_y * dpr

                if (dpr_target_x > selected_monitor[2] or
                        dpr_target_y > selected_monitor[3] or
                        dpr_target_x < 0 or
                        dpr_target_y < 0):
                    continue

                target_local = QPoint(int(target_x), int(target_y))

                painter.save()
                painter.setPen(click_style['pen'])
                painter.setBrush(click_style['brush'])
                painter.drawEllipse(target_local, 4, 4)
                painter.restore()