#!/usr/bin/env python3
"""
The "Highly Critical Business" CNC Text Carver - Adult Edition.
Version: 1.2.6
The Decoupling Update: Removing leaky UI string abstractions between the main app and the CAM plugin.
"""

import sys
import json
import os
import re
import subprocess
import fnmatch
import traceback
import tempfile
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QFormLayout, QLineEdit, 
                             QComboBox, QPushButton, QFileDialog,
                             QGraphicsView, QGraphicsScene, QGroupBox, QLabel,
                             QDoubleSpinBox, QCheckBox)
from PyQt6.QtGui import QPainter, QPen, QColor, QTransform, QPainterPath, QBrush, QFont
from PyQt6.QtCore import Qt, QRectF, QTimer, QPointF
from build123d import *

# --- GLOBAL APP CONFIGURATION ---
VERSION = "1.2.6"
APP_TITLE_BASE = "Critical Business CNC Carver v"
FILE_LAST_USE = os.path.expanduser("~/.sf_last_use.stmp")
FILE_FILTER_STMP = "Stamp Configs (*.stmp);;All Files (*)"
FILE_FILTER_SVG = "SVG Files (*.svg)"

# --- GLOBAL DEFAULTS ---
DEF_TEXT = "STARTUP PIVOT"
DEF_WIDTH = 38.0
DEF_HEIGHT = 13.0
DEF_MARGIN = 1.0
DEF_OFFSET_X = 10.0
DEF_OFFSET_Y = 10.0
DEF_FONT_FAMILY = "sans-serif"
DEF_FONT_STYLE = "Regular"
DEF_ALIGN = "Center"
DEF_MIRROR = False

# --- GLOBAL UI STRINGS ---
UI_LBL_TEXT = "Text:"
UI_LBL_WIDTH = "Width (mm):"
UI_LBL_HEIGHT = "Height (mm):"
UI_LBL_MARGIN_LR = "Margin L/R (mm):"
UI_LBL_MARGIN_TB = "Margin T/B (mm):"
UI_LBL_OFFSET = "Origin Offset:"
UI_LBL_FONT = "Font:"
UI_LBL_ALIGN = "Alignment:"
UI_CHK_MIRROR = "Mirror Output (For physical stamps)"
UI_GRP_GEO = "Geometry Parameters"
UI_GRP_ACT = "Legacy Export & State"
UI_GRP_CAM_ERR = "CAM Plugin (ERROR)"
UI_BTN_SAVE = "Save As"
UI_BTN_SAVE_UNSAVED = "Save As *"
UI_BTN_LOAD = "Open"
UI_BTN_SVG = "SVG"
UI_BTN_ZOOM_IN = "Zoom In"
UI_BTN_ZOOM_OUT = "Zoom Out"
UI_BTN_FIT = "Auto Fit"
UI_BTN_11 = "1:1 Scale"

# --- GLOBAL STYLE CONSTANTS ---
FONT_BLACKLIST = [
    "Noto *", "MathJax*", "Standard Symbols*", "Dingbats", 
    "Webdings", "Sawasdee", "Kinnari", "Loma"
]

DARK_THEME = """
QMainWindow, QWidget { background-color: #2b2d30; color: #a9b7c6; font-family: 'Segoe UI', Ubuntu, sans-serif; font-size: 11pt; }
QGraphicsView { background-color: #1e1e22; border: 1px solid #141415; border-radius: 6px; }
QLineEdit, QComboBox { background-color: #1e1e22; border: 1px solid #4c5052; border-radius: 4px; padding: 6px; color: #dfdfe0; selection-background-color: #35538b; }
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #548af7; }
QDoubleSpinBox { background-color: #1e1e22; border: 1px solid #4c5052; border-radius: 4px; padding: 4px 20px 4px 6px; color: #dfdfe0; selection-background-color: #35538b; }
QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 16px; border-left: 1px solid #4c5052; border-bottom: 1px solid #4c5052; border-top-right-radius: 4px; background-color: #2b2d30; }
QDoubleSpinBox::up-button:hover { background-color: #3c3f41; }
QDoubleSpinBox::up-arrow { image: url("{DARK_UP_ARROW}"); width: 8px; height: 5px; }
QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 16px; border-left: 1px solid #4c5052; border-bottom-right-radius: 4px; background-color: #2b2d30; }
QDoubleSpinBox::down-button:hover { background-color: #3c3f41; }
QDoubleSpinBox::down-arrow { image: url("{DARK_DOWN_ARROW}"); width: 8px; height: 5px; }
QPushButton { background-color: #4c5052; border: none; border-radius: 4px; padding: 6px 12px; color: #dfdfe0; font-weight: bold; }
QPushButton:hover { background-color: #548af7; color: #ffffff; }
QPushButton:pressed { background-color: #35538b; }
QGroupBox { border: 1px solid #4c5052; border-radius: 6px; margin-top: 1.5em; padding-top: 1em; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; color: #8a8a8a; }
QStatusBar { background-color: #212124; color: #8a8a8a; border-top: 1px solid #141415; }
QCheckBox { color: #dfdfe0; }
"""

LIGHT_THEME = """
QMainWindow, QWidget { background-color: #f5f5f5; color: #333333; font-family: 'Segoe UI', Ubuntu, sans-serif; font-size: 11pt; }
QGraphicsView { background-color: #ffffff; border: 1px solid #cccccc; border-radius: 6px; }
QLineEdit, QComboBox { background-color: #ffffff; border: 1px solid #bbbbbb; border-radius: 4px; padding: 6px; color: #333333; selection-background-color: #a0c4ff; }
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #548af7; }
QDoubleSpinBox { background-color: #ffffff; border: 1px solid #bbbbbb; border-radius: 4px; padding: 4px 20px 4px 6px; color: #333333; selection-background-color: #a0c4ff; }
QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 16px; border-left: 1px solid #bbbbbb; border-bottom: 1px solid #bbbbbb; border-top-right-radius: 4px; background-color: #e0e0e0; }
QDoubleSpinBox::up-button:hover { background-color: #d0d0d0; }
QDoubleSpinBox::up-arrow { image: url("{LIGHT_UP_ARROW}"); width: 8px; height: 5px; }
QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 16px; border-left: 1px solid #bbbbbb; border-bottom-right-radius: 4px; background-color: #e0e0e0; }
QDoubleSpinBox::down-button:hover { background-color: #d0d0d0; }
QDoubleSpinBox::down-arrow { image: url("{LIGHT_DOWN_ARROW}"); width: 8px; height: 5px; }
QPushButton { background-color: #e0e0e0; border: none; border-radius: 4px; padding: 6px 12px; color: #333333; font-weight: bold; }
QPushButton:hover { background-color: #548af7; color: #ffffff; }
QPushButton:pressed { background-color: #35538b; color: #ffffff; }
QGroupBox { border: 1px solid #cccccc; border-radius: 6px; margin-top: 1.5em; padding-top: 1em; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; color: #666666; }
QStatusBar { background-color: #eaeaea; color: #666666; border-top: 1px solid #cccccc; }
QCheckBox { color: #333333; }
"""

def create_svg_file(filename, color, is_up=True):
    """Generates physical SVG files in the temp directory to bypass Qt CSS rendering bugs."""
    path_d = "M0 5l4-5 4 5z" if is_up else "M0 0l4 5 4-5z"
    svg_content = f"<svg xmlns='http://www.w3.org/2000/svg' width='8' height='5' viewBox='0 0 8 5'><path fill='{color}' d='{path_d}'/></svg>"
    filepath = os.path.join(tempfile.gettempdir(), filename)
    with open(filepath, "w", encoding="utf-8") as f: 
        f.write(svg_content)
    return filepath.replace("\\", "/")

# Injecting local file paths into the global theme strings
DARK_THEME_COMPILED = DARK_THEME.replace("{DARK_UP_ARROW}", create_svg_file("sf_dark_up.svg", "#a9b7c6", True)).replace("{DARK_DOWN_ARROW}", create_svg_file("sf_dark_down.svg", "#a9b7c6", False))
LIGHT_THEME_COMPILED = LIGHT_THEME.replace("{LIGHT_UP_ARROW}", create_svg_file("sf_light_up.svg", "#333333", True)).replace("{LIGHT_DOWN_ARROW}", create_svg_file("sf_light_down.svg", "#333333", False))

try:
    from cam_module import CAMUIWidget
    cam_error_msg = None
except Exception as e:
    CAMUIWidget = None
    cam_error_msg = traceback.format_exc()


def apply_os_theme(app):
    """Detects the operating system theme and applies the appropriate Qt stylesheet."""
    app.setStyleSheet(DARK_THEME_COMPILED if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else LIGHT_THEME_COMPILED)

def get_system_ttf_fonts():
    """Queries fontconfig for available TrueType fonts, stripping out known incompatible families."""
    try:
        result = subprocess.run(['fc-list', ':fontformat=TrueType', 'family'], capture_output=True, text=True)
        families = set()
        for line in result.stdout.split('\n'):
            if line.strip():
                primary = line.split(',')[0].strip()
                if not any(fnmatch.fnmatchcase(primary.lower(), p.lower()) for p in FONT_BLACKLIST):
                    families.add(primary)
        return sorted(list(families)) if families else [DEF_FONT_FAMILY]
    except Exception:
        return [DEF_FONT_FAMILY]

class CADViewport(QGraphicsView):
    """Handles the rendering and interaction with 2D CAD geometry."""
    
    def __init__(self):
        """Initializes the QGraphicsView container and configures input handling."""
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        
        dpi = QApplication.primaryScreen().physicalDotsPerInch()
        self.dpi = dpi if dpi > 0 else 96
        self.target_rect = QRectF(0, 0, DEF_WIDTH, DEF_HEIGHT)
        self.set_scale_1_to_1()

    def set_scale_1_to_1(self):
        """Calculates physical screen DPI to display geometry at true-to-life physical dimensions."""
        mm_per_inch = 25.4
        ppmm = self.dpi / mm_per_inch
        self.setTransform(QTransform().scale(ppmm, -ppmm))
        self.centerOn(QPointF(self.viewport().width() / ppmm / 2.0, self.viewport().height() / ppmm / 2.0))

    def zoom_in(self): 
        """Applies a standard positive zoom factor."""
        zoom_factor = 1.25
        self.scale(zoom_factor, zoom_factor)
        
    def zoom_out(self): 
        """Applies a standard negative zoom factor."""
        zoom_factor = 0.8
        self.scale(zoom_factor, zoom_factor)
        
    def fit_auto(self): 
        """Calculates the view bounding box and scales it to fit the current window dimensions."""
        padding = 5
        self.fitInView(self.target_rect.adjusted(-padding, -padding, padding, padding), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        """Overrides mouse wheel input to handle zooming operations based on keyboard modifiers."""
        zoom_in_factor = 1.15
        zoom_out_factor = 0.87
        
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier or event.angleDelta().y() != 0:
            zoom = zoom_in_factor if event.angleDelta().y() > 0 else zoom_out_factor
            self.scale(zoom, zoom)
            event.accept()
        else: 
            super().wheelEvent(event)

    def render_cad_geometry(self, shape, bx, by, bw, bh):
        """Translates CAD wires into QPainterPaths and renders them within the scene."""
        fill_alpha = 190
        axis_dim = 10000
        origin_mark = 2
        
        self.scene.clear()
        self.target_rect = QRectF(bx, by, bw, bh)

        is_dark = QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        axis_color = QColor("#444444") if is_dark else QColor("#cccccc")
        geom_color = QColor("#dfdfe0") if is_dark else QColor("#222222")

        pen_axis, pen_origin = QPen(axis_color, 0), QPen(QColor("#00ff00"), 0)
        self.scene.addLine(-axis_dim, 0, axis_dim, 0, pen_axis)
        self.scene.addLine(0, -axis_dim, 0, axis_dim, pen_axis)
        self.scene.addLine(-origin_mark, 0, origin_mark, 0, pen_origin)
        self.scene.addLine(0, -origin_mark, 0, origin_mark, pen_origin)

        pen_bound = QPen(QColor("#ff4444"), 0)
        pen_bound.setStyle(Qt.PenStyle.DashLine)
        self.scene.addRect(self.target_rect, pen_bound)

        if shape:
            comp_path = QPainterPath()
            comp_path.setFillRule(Qt.FillRule.OddEvenFill)
            wires = shape.wires()
            if wires:
                for wire in wires:
                    wire_pts = []
                    for edge in wire.edges():
                        samples = max(4, int(edge.length * 3))
                        e_pts = [edge.position_at(i/samples) for i in range(samples+1)]
                        if wire_pts:
                            if (wire_pts[-1] - e_pts[-1]).length < (wire_pts[-1] - e_pts[0]).length: e_pts.reverse()
                            wire_pts.extend(e_pts[1:])
                        else: wire_pts.extend(e_pts)
                    
                    if wire_pts:
                        comp_path.moveTo(wire_pts[0].X, wire_pts[0].Y)
                        for p in wire_pts[1:]: comp_path.lineTo(p.X, p.Y)
                        comp_path.closeSubpath()
                
                self.scene.addPath(comp_path, QPen(geom_color, 0), QBrush(QColor(255, 215, 0, fill_alpha)))


class CNCCarverApp(QMainWindow):
    """Main application window for coordinating geometry parameters and CAM operations."""
    
    def __init__(self):
        """Builds the UI layouts, initializes default state, and attempts to attach the CAM plugin."""
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE_BASE}{VERSION}")
        self.resize(1150, 800)
        
        self.statusBar().showMessage("Ready.")
        self._is_loading = False 
        self._first_render = True
        self._pending_view_restore = None
        self.current_geometry = None
        
        self.render_timer = QTimer()
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self.generate_geometry)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # --- Left Panel ---
        left_panel = QWidget()
        left_panel.setMaximumWidth(420)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        group_geo = QGroupBox(UI_GRP_GEO)
        form_layout = QFormLayout(group_geo)
        
        self.text_input = QLineEdit(DEF_TEXT)
        self.width_spin = self.create_spinbox(DEF_WIDTH)
        self.height_spin = self.create_spinbox(DEF_HEIGHT)
        self.margin_left = self.create_spinbox(DEF_MARGIN)
        self.margin_right = self.create_spinbox(DEF_MARGIN)
        self.margin_top = self.create_spinbox(DEF_MARGIN)
        self.margin_bottom = self.create_spinbox(DEF_MARGIN)
        self.abs_x = self.create_spinbox(DEF_OFFSET_X, -1000, 1000)
        self.abs_y = self.create_spinbox(DEF_OFFSET_Y, -1000, 1000)
        
        self.font_combo = QComboBox()
        for i, font_name in enumerate(get_system_ttf_fonts()):
            self.font_combo.addItem(font_name)
            self.font_combo.setItemData(i, QFont(font_name, 12), Qt.ItemDataRole.FontRole)
            
        self.style_combo = QComboBox()
        self.style_combo.addItems(["Regular", "Bold", "Italic"])
        self.align_combo = QComboBox()
        self.align_combo.addItems(["Center", "Left", "Right"])
        
        self.mirror_check = QCheckBox(UI_CHK_MIRROR)

        form_layout.addRow(UI_LBL_TEXT, self.text_input)
        form_layout.addRow(UI_LBL_WIDTH, self.width_spin)
        form_layout.addRow(UI_LBL_HEIGHT, self.height_spin)
        form_layout.addRow(UI_LBL_MARGIN_LR, self.create_hbox(self.margin_left, self.margin_right))
        form_layout.addRow(UI_LBL_MARGIN_TB, self.create_hbox(self.margin_top, self.margin_bottom))
        form_layout.addRow(UI_LBL_OFFSET, self.create_hbox(self.abs_x, self.abs_y))
        form_layout.addRow(UI_LBL_FONT, self.create_hbox(self.font_combo, self.style_combo))
        form_layout.addRow(UI_LBL_ALIGN, self.align_combo)
        form_layout.addRow("", self.mirror_check)
        left_layout.addWidget(group_geo)

        # --- Modular CAM Plugin Integration ---
        self.cam_widget = None
        if CAMUIWidget:
            self.cam_widget = CAMUIWidget(
                geometry_cb=lambda: self.current_geometry,
                filename_cb=self.generate_safe_filename,
                status_cb=self.statusBar().showMessage,
                parent=self
            )
            self.cam_widget.state_changed.connect(self.mark_unsaved)
            left_layout.addWidget(self.cam_widget)
        else:
            err_box = QGroupBox(UI_GRP_CAM_ERR)
            err_layout = QVBoxLayout(err_box)
            err_label = QLabel(f"Failed to load the isolated cam_module.py plugin.\n\nTraceback:\n{cam_error_msg}")
            err_label.setStyleSheet("color: #ff5555; font-weight: bold;")
            err_label.setWordWrap(True)
            err_layout.addWidget(err_label)
            left_layout.addWidget(err_box)

        group_actions = QGroupBox(UI_GRP_ACT)
        action_layout = QHBoxLayout(group_actions)
        self.btn_save_cfg = QPushButton(UI_BTN_SAVE)
        self.btn_load_cfg = QPushButton(UI_BTN_LOAD)
        self.btn_export_svg = QPushButton(UI_BTN_SVG)
        action_layout.addWidget(self.btn_save_cfg)
        action_layout.addWidget(self.btn_load_cfg)
        action_layout.addWidget(self.btn_export_svg)
        left_layout.addWidget(group_actions)
        left_layout.addStretch()

        main_layout.addWidget(left_panel, stretch=0)

        # --- Right Panel ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        toolbar = QHBoxLayout()
        self.btn_zoom_in = QPushButton(UI_BTN_ZOOM_IN)
        self.btn_zoom_out = QPushButton(UI_BTN_ZOOM_OUT)
        self.btn_zoom_11 = QPushButton(UI_BTN_11)
        self.btn_zoom_auto = QPushButton(UI_BTN_FIT)
        toolbar.addWidget(self.btn_zoom_in)
        toolbar.addWidget(self.btn_zoom_out)
        toolbar.addWidget(self.btn_zoom_auto)
        toolbar.addWidget(self.btn_zoom_11)
        toolbar.addStretch()
        right_layout.addLayout(toolbar)

        self.viewport = CADViewport()
        right_layout.addWidget(self.viewport)
        main_layout.addWidget(right_panel, stretch=1)

        # --- Signals ---
        self.btn_zoom_in.clicked.connect(self.viewport.zoom_in)
        self.btn_zoom_out.clicked.connect(self.viewport.zoom_out)
        self.btn_zoom_11.clicked.connect(self.viewport.set_scale_1_to_1)
        self.btn_zoom_auto.clicked.connect(self.viewport.fit_auto)

        for widget in [self.text_input, self.font_combo, self.style_combo, self.align_combo]:
            (widget.textChanged if isinstance(widget, QLineEdit) else widget.currentTextChanged).connect(self.trigger_render)
        
        for spin in [self.width_spin, self.height_spin, self.margin_left, self.margin_right,
                     self.margin_top, self.margin_bottom, self.abs_x, self.abs_y]:
            spin.valueChanged.connect(self.trigger_render)

        self.mirror_check.stateChanged.connect(self.trigger_render)
        self.btn_save_cfg.clicked.connect(self.save_config)
        self.btn_load_cfg.clicked.connect(self.load_config)
        self.btn_export_svg.clicked.connect(self.export_svg_file)
        
        if os.path.exists(FILE_LAST_USE): self.load_from_file(FILE_LAST_USE, quiet=True)
        else: self.mark_saved() 
        
        render_delay_ms = 100
        QTimer.singleShot(render_delay_ms, self.trigger_render)

    def closeEvent(self, event):
        """Intercepts window close events to automatically serialize current application state."""
        try:
            with open(FILE_LAST_USE, 'w') as f: json.dump(self.get_config_dict(), f, indent=4)
        except Exception: pass 
        event.accept()

    def mark_unsaved(self):
        """Visually modifies the Save button to indicate pending state changes."""
        unsaved_color = "#d97706"
        if not getattr(self, '_is_loading', False):
            self.btn_save_cfg.setStyleSheet(f"background-color: {unsaved_color}; color: white; font-weight: bold;")
            self.btn_save_cfg.setText(UI_BTN_SAVE_UNSAVED)

    def mark_saved(self):
        """Resets the visual status of the Save button."""
        self.btn_save_cfg.setStyleSheet("")
        self.btn_save_cfg.setText(UI_BTN_SAVE)

    def create_spinbox(self, default, min_val=0.0, max_val=10000.0, step=0.5):
        """Instantiates a strictly typed QDoubleSpinBox with standard constraints."""
        spin = QDoubleSpinBox()
        spin.setRange(min_val, max_val)
        spin.setValue(default)
        spin.setSingleStep(step)
        return spin

    def create_hbox(self, w1, w2):
        """Packs two widgets into a horizontal container without margins."""
        hbox = QHBoxLayout()
        hbox.addWidget(w1)
        hbox.addWidget(w2)
        hbox.setContentsMargins(0, 0, 0, 0)
        widget = QWidget()
        widget.setLayout(hbox)
        return widget

    def trigger_render(self):
        """Debounces CAD regeneration requests to avoid UI lockups during typing."""
        debounce_ms = 250
        self.mark_unsaved()
        self.render_timer.start(debounce_ms)

    def _apply_view_state(self):
        """Restores viewport transformations from a serialized state upon loading."""
        if self._pending_view_restore:
            td = self._pending_view_restore["transform"]
            cd = self._pending_view_restore["center"]
            self.viewport.setTransform(QTransform(td[0], td[1], td[2], td[3], td[4], td[5], td[6], td[7], td[8]))
            self.viewport.centerOn(QPointF(cd[0], cd[1]))
            self._pending_view_restore = None
        elif self._first_render:
            self.viewport.fit_auto()
        self._first_render = False

    def reset_statusbar_color(self):
        """Clears error/warning background styling from the main window status bar."""
        self.statusBar().setStyleSheet("")

    def get_linux_font_path(self, font_family, font_style):
        """Interfaces directly with fontconfig to resolve concrete file paths for requested typography."""
        try:
            query = f"{font_family}:style={font_style}:fontformat=TrueType"
            res = subprocess.run(['fc-match', '-f', '%{file}', query], capture_output=True, text=True).stdout.strip()
            if res and os.path.exists(res) and res.lower().endswith('.ttf'): return res
        except Exception: pass
        return None

    def generate_geometry(self):
        """Executes the primary build123d math engine to compute text geometry and alignments."""
        error_display_ms = 5000
        success_display_ms = 2000
        default_font_size = 10
        
        txt, w, h = self.text_input.text().strip(), self.width_spin.value(), self.height_spin.value()
        ml, mr, mt, mb = self.margin_left.value(), self.margin_right.value(), self.margin_top.value(), self.margin_bottom.value()
        abs_x, abs_y = self.abs_x.value(), self.abs_y.value()

        if not txt or (w - ml - mr) <= 0 or (h - mt - mb) <= 0:
            self.viewport.render_cad_geometry(None, abs_x, abs_y, w, h)
            self._apply_view_state()
            return 

        try:
            base_rect = Rectangle(w, h)
            style_str = self.style_combo.currentText()
            b_style = FontStyle.BOLD if style_str == "Bold" else FontStyle.ITALIC if style_str == "Italic" else FontStyle.REGULAR
            selected_font = self.font_combo.currentText()
            exact_font_path = self.get_linux_font_path(selected_font, style_str)

            if not exact_font_path: raise RuntimeError(f"Missing TTF file for {selected_font}")
                
            raw_text = Text(txt=txt, font_size=default_font_size, font=selected_font, font_path=exact_font_path, font_style=b_style, align=(Align.CENTER, Align.CENTER))
            bbox = raw_text.bounding_box()
            if bbox.size.X == 0 or bbox.size.Y == 0: return 

            scale_factor = min((w - ml - mr) / bbox.size.X, (h - mt - mb) / bbox.size.Y)
            scaled_text = scale(raw_text, by=scale_factor)
            scaled_bbox = scaled_text.bounding_box()

            align = self.align_combo.currentText()
            shift_y = ((mb - mt) / 2.0) - scaled_bbox.center().Y
            
            if align == "Center": shift_x = ((ml - mr) / 2.0) - scaled_bbox.center().X
            elif align == "Left": shift_x = (-w/2 + ml) - scaled_bbox.min.X
            elif align == "Right": shift_x = (w/2 - mr) - scaled_bbox.max.X

            positioned_text = Pos(shift_x, shift_y) * scaled_text
            carve_path = base_rect - positioned_text
            
            if self.mirror_check.isChecked():
                from build123d import Plane, mirror
                carve_path = mirror(carve_path, about=Plane.YZ)
                
            self.current_geometry = Pos(abs_x + w/2, abs_y + h/2) * carve_path
            
            self.viewport.render_cad_geometry(self.current_geometry, abs_x, abs_y, w, h)
            self._apply_view_state()
            
            if not getattr(self, '_is_loading', False):
                self.reset_statusbar_color()
                self.statusBar().showMessage(f"Rendered with {os.path.basename(exact_font_path)}", success_display_ms)

        except Exception as e:
            self.statusBar().setStyleSheet("background-color: #880000; color: white;")
            self.statusBar().showMessage(f"Geometry Error: {str(e).split(chr(10))[0]}", error_display_ms)
            QTimer.singleShot(error_display_ms, self.reset_statusbar_color)

    def export_svg_file(self):
        """Extracts native topological wires into standardized path descriptions for SVG serialization."""
        status_ms_success = 4000
        status_ms_error = 5000
        pad_multiplier = 0.05
        
        if not self.current_geometry: return
        path, _ = QFileDialog.getSaveFileName(self, "Export SVG", self.generate_safe_filename(".svg"), FILE_FILTER_SVG)
        if path:
            try:
                if not path.lower().endswith('.svg'): path += '.svg'
                wires = self.current_geometry.wires()
                if not wires: return
                bbox = self.current_geometry.bounding_box()
                pad = max(bbox.size.X, bbox.size.Y) * pad_multiplier
                svg = [f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>', 
                       f'<svg width="{bbox.size.X + pad*2:.4f}mm" height="{bbox.size.Y + pad*2:.4f}mm" viewBox="{bbox.min.X - pad:.4f} {-(bbox.max.Y + pad):.4f} {bbox.size.X + pad*2:.4f} {bbox.size.Y + pad*2:.4f}" xmlns="http://www.w3.org/2000/svg">']
                d_strings = []
                for wire in wires:
                    pts = []
                    for e in wire.edges():
                        samples = max(4, int(e.length*3))
                        ep = [e.position_at(i/samples) for i in range(samples+1)]
                        if pts:
                            if (pts[-1] - ep[-1]).length < (pts[-1] - ep[0]).length: ep.reverse()
                            pts.extend(ep[1:])
                        else: pts.extend(ep)
                    if pts: d_strings.append(f"M {pts[0].X:.4f},{-pts[0].Y:.4f} " + " ".join([f"L {p.X:.4f},{-p.Y:.4f}" for p in pts[1:]]) + " Z")
                svg.append(f'<path d="{" ".join(d_strings)}" fill="#000000" fill-rule="evenodd" />')
                svg.append('</svg>')
                with open(path, 'w') as f: f.write("\n".join(svg))
                self.statusBar().showMessage(f"Exported CAM-Ready SVG to {os.path.basename(path)}", status_ms_success)
            except Exception as e: 
                self.statusBar().showMessage(f"Export failed: {e}", status_ms_error)

    def get_config_dict(self):
        """Constructs a comprehensive state dictionary encompassing both core parameters and sub-module states."""
        t = self.viewport.transform()
        center = self.viewport.mapToScene(self.viewport.viewport().rect().center())
        
        cfg = {
            "text": self.text_input.text(), "width": self.width_spin.value(), "height": self.height_spin.value(),
            "margin_left": self.margin_left.value(), "margin_right": self.margin_right.value(),
            "margin_top": self.margin_top.value(), "margin_bottom": self.margin_bottom.value(),
            "abs_x": self.abs_x.value(), "abs_y": self.abs_y.value(),
            "font_family": self.font_combo.currentText(), "font_style": self.style_combo.currentText(),
            "alignment": self.align_combo.currentText(), "mirror": self.mirror_check.isChecked(),
            "viewport_transform": [t.m11(), t.m12(), t.m13(), t.m21(), t.m22(), t.m23(), t.m31(), t.m32(), t.m33()],
            "viewport_center": [center.x(), center.y()]
        }
        
        if self.cam_widget:
            cfg["cam"] = self.cam_widget.get_state()
            
        return cfg

    def generate_safe_filename(self, extension):
        """Strips invalid filesystem characters from the user text input to formulate default save targets."""
        txt = self.text_input.text().strip()
        safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '', txt.replace(' ', '_'))
        return f"{safe_name[:40]}{extension}" if safe_name else f"stamp_carve{extension}"
        
    def load_config(self):
        """Triggers the interactive file selection dialog to ingest a state payload."""
        path, _ = QFileDialog.getOpenFileName(self, "Open Stamp Config", "", FILE_FILTER_STMP)
        if path: self.load_from_file(path)

    def load_from_file(self, path, quiet=False):
        """Hydrates the application UI components with parameters mapped from a serialized JSON structure."""
        status_ms_success = 4000
        status_ms_error = 5000
        
        try:
            with open(path, 'r') as f: cfg = json.load(f)
            self._is_loading = True
            
            self.text_input.setText(cfg.get("text", ""))
            self.width_spin.setValue(cfg.get("width", DEF_WIDTH)); self.height_spin.setValue(cfg.get("height", DEF_HEIGHT))
            self.margin_left.setValue(cfg.get("margin_left", DEF_MARGIN)); self.margin_right.setValue(cfg.get("margin_right", DEF_MARGIN))
            self.margin_top.setValue(cfg.get("margin_top", DEF_MARGIN)); self.margin_bottom.setValue(cfg.get("margin_bottom", DEF_MARGIN))
            self.abs_x.setValue(cfg.get("abs_x", DEF_OFFSET_X)); self.abs_y.setValue(cfg.get("abs_y", DEF_OFFSET_Y))
            
            if (idx := self.font_combo.findText(cfg.get("font_family", DEF_FONT_FAMILY))) >= 0: self.font_combo.setCurrentIndex(idx)
            self.style_combo.setCurrentText(cfg.get("font_style", DEF_FONT_STYLE))
            self.align_combo.setCurrentText(cfg.get("alignment", DEF_ALIGN))
            self.mirror_check.setChecked(cfg.get("mirror", DEF_MIRROR))
            
            if "viewport_transform" in cfg and "viewport_center" in cfg:
                self._pending_view_restore = {"transform": cfg["viewport_transform"], "center": cfg["viewport_center"]}

            if self.cam_widget:
                if "cam" in cfg: 
                    self.cam_widget.load_state(cfg["cam"])
                else: 
                    self.cam_widget.load_state(cfg)
                
            self._is_loading = False
            self.mark_saved()
            if not quiet: self.statusBar().showMessage(f"Loaded {os.path.basename(path)}", status_ms_success)
        except Exception as e:
            self._is_loading = False
            if not quiet: self.statusBar().showMessage(f"Load failed: {e}", status_ms_error)

    def save_config(self):
        """Serializes current state payload into an explicit stmp file via a dialog."""
        status_ms_success = 4000
        status_ms_error = 5000
        
        path, _ = QFileDialog.getSaveFileName(self, "Save Stamp Config", self.generate_safe_filename(".stmp"), FILE_FILTER_STMP)
        if path:
            if not path.lower().endswith('.stmp'): path += '.stmp'
            try:
                with open(path, 'w') as f: json.dump(self.get_config_dict(), f, indent=4)
                self.mark_saved()
                self.statusBar().showMessage(f"Config saved to {os.path.basename(path)}", status_ms_success)
            except Exception as e: 
                self.statusBar().showMessage(f"Save failed: {e}", status_ms_error)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    apply_os_theme(app)
    app.styleHints().colorSchemeChanged.connect(lambda: apply_os_theme(app))
    window = CNCCarverApp()
    window.show()
    sys.exit(app.exec())