#!/usr/bin/env python3
"""
cam_module.py
Self-contained CAM Engine and UI Plugin.
Includes advanced 2.5D Two-Tool V-Carving logic for preserving fragile topological features.
"""

import math
import os
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, 
                             QGroupBox, QLineEdit, QPushButton, QFileDialog, 
                             QDoubleSpinBox, QCheckBox, QLabel, QStackedWidget)
from PyQt6.QtCore import pyqtSignal, Qt

try:
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
except ImportError:
    Polygon = None
    unary_union = None

# --- GLOBAL DEFAULT CAM PARAMETERS ---
DEF_CUTTER_DIA = 3.175
DEF_FEED_RAPID = 1000.0
DEF_FEED_CUT = 500.0
DEF_FEED_PLUNGE = 150.0
DEF_STEP_DEPTH = 1.0
DEF_OVERSTEP = 0.5
DEF_DEPTH_CUT = 5.0
DEF_DEPTH_ENGRAVE = 1.0
DEF_PROLOGUE = "M3"
DEF_EPILOGUE = "M5"
SAFE_Z_HEIGHT = 5.000

# V-Carve Specific Defaults
DEF_V_CUTTER_EN = False
DEF_V_ANGLE = 60.0
DEF_V_TIP = 0.1

# --- GLOBAL UI STRINGS & COLORS ---
UI_TITLE_CAM = "CAM Parameters (G-Code)"
UI_BTN_OUTSIDE = "G-Code: Outside Cut"
UI_BTN_ENGRAVE = "G-Code: Pocket Letters"
UI_BTN_POCKET = "G-Code: Pocket Background"
UI_CHK_VCUTTER = "Enable V-Cutter Profiling (Two-Tool Setup)"
UI_BTN_V_ROUGH = "G-Code: V-Rough (Flat Bit)"
UI_BTN_V_FINISH = "G-Code: V-Finish (V-Bit)"

COLOR_BTN_ENGRAVE = "#35538b"
COLOR_BTN_POCKET = "#1e7a5c"
COLOR_BTN_OUTSIDE = "#8b3535"
COLOR_BTN_V = "#8b6508"
FILE_FILTER_GCODE = "G-Code (*.gcode *.nc)"


def create_cam_spinbox(default, min_val=0.0, max_val=10000.0, step=0.5):
    """Instantiates a strictly typed QDoubleSpinBox with standard constraints."""
    spin = QDoubleSpinBox()
    spin.setRange(min_val, max_val)
    spin.setValue(default)
    spin.setSingleStep(step)
    return spin


class CAMGenerator:
    """Headless numerical control engine for generating G-Code paths via Shapely."""
    
    def __init__(self, params):
        """Initializes the CAM generator with a dictionary of machining parameters."""
        self.cutter_diameter = float(params.get("cam_cutter_dia", DEF_CUTTER_DIA))
        self.feed_rapid = float(params.get("cam_feed_rapid", DEF_FEED_RAPID))
        self.feed_cut = float(params.get("cam_feed_cut", DEF_FEED_CUT))
        self.feed_plunge = float(params.get("cam_feed_plunge", DEF_FEED_PLUNGE))
        self.step_depth = float(params.get("cam_step_depth", DEF_STEP_DEPTH))
        self.overstep = float(params.get("cam_overstep", DEF_OVERSTEP))
        self.depth_total_cut = float(params.get("cam_depth_cut", DEF_DEPTH_CUT))
        self.depth_total_engrave = float(params.get("cam_depth_engrave", DEF_DEPTH_ENGRAVE))
        self.prologue = str(params.get("cam_prologue", DEF_PROLOGUE))
        self.epilogue = str(params.get("cam_epilogue", DEF_EPILOGUE))
        
        self.use_v_bit = bool(params.get("cam_use_v_bit", DEF_V_CUTTER_EN))
        self.v_angle = float(params.get("cam_v_angle", DEF_V_ANGLE))
        self.v_tip = float(params.get("cam_v_tip_dia", DEF_V_TIP))

    def _header(self, title):
        """Generates the standardized G-Code header."""
        return [
            f"; --- CRITICAL BUSINESS CAM: {title} ---",
            "G21 ; Set units to mm",
            "G90 ; Absolute positioning",
            self.prologue,
            f"G0 Z{SAFE_Z_HEIGHT:.3f} F{self.feed_rapid:.1f} ; Safe Z"
        ]

    def _footer(self):
        """Generates the standardized G-Code footer."""
        return [
            f"G0 Z{SAFE_Z_HEIGHT:.3f} F{self.feed_rapid:.1f} ; Safe Z",
            self.epilogue,
            "M2 ; End program"
        ]

    def _discretize_wire(self, wire):
        """Converts continuous CAD wireframe geometry into discrete coordinate lists."""
        min_samples = 2
        max_samples = 50
        sample_resolution = 0.1
        
        wire_pts = []
        for edge in wire.edges():
            samples = max(min_samples, min(max_samples, int(edge.length / sample_resolution)))
            e_pts = [edge.position_at(i/samples) for i in range(samples+1)]
            if wire_pts:
                d_start = (wire_pts[-1] - e_pts[0]).length
                d_end = (wire_pts[-1] - e_pts[-1]).length
                if d_end < d_start: e_pts.reverse()
                wire_pts.extend(e_pts[1:])
            else:
                wire_pts.extend(e_pts)
        return [(p.X, p.Y) for p in wire_pts]

    def _get_shapely_polys(self, shape):
        """Extracts outer bounds and internal topological faces into Shapely polygons."""
        simplify_tolerance = 0.01
        
        faces = list(shape.faces())
        if not faces: return None, None
        
        main_face = sorted(faces, key=lambda f: f.bounding_box().size.X * f.bounding_box().size.Y, reverse=True)[0]
        base_rect = Polygon(self._discretize_wire(main_face.outer_wire()))
        
        polys = []
        for face in faces:
            outer = self._discretize_wire(face.outer_wire())
            inners = [self._discretize_wire(w) for w in face.inner_wires()]
            try:
                polys.append(Polygon(outer, inners))
            except Exception:
                pass
                
        stamp_poly = unary_union(polys).simplify(simplify_tolerance, preserve_topology=True)
        return stamp_poly, base_rect

    def _generate_pocket_paths(self, target_poly):
        """Calculates concentric inward toolpaths for a given topological area."""
        max_pocket_loops = 200
        simplify_tolerance = 0.01
        mitre_join_style = 2
        
        rings_to_cut = []
        inset = self.cutter_diameter / 2.0
        step_mm = self.cutter_diameter * self.overstep
        
        current_poly = target_poly.buffer(-inset, join_style=mitre_join_style)
        
        for _ in range(max_pocket_loops):
            if current_poly.is_empty: break
            
            current_poly = current_poly.simplify(simplify_tolerance, preserve_topology=True)
            
            if current_poly.geom_type == 'Polygon':
                polys = [current_poly]
            elif current_poly.geom_type in ['MultiPolygon', 'GeometryCollection']:
                polys = list(current_poly.geoms)
            else:
                polys = []
                
            added = False
            for p in polys:
                if p.is_empty or p.geom_type != 'Polygon': continue
                rings_to_cut.append(list(p.exterior.coords))
                for interior in p.interiors:
                    rings_to_cut.append(list(interior.coords))
                added = True
                
            if not added: break
            current_poly = current_poly.buffer(-step_mm, join_style=mitre_join_style)
            
        return rings_to_cut

    def _generate_depth_passes(self, rings, target_depth):
        """Translates 2D path rings into layered Z-depth G-Code operations."""
        min_point_dist = 0.01
        
        if not rings: return []
        gcode = []
        depths = []
        z = 0.0
        
        while round(z, 5) > round(-target_depth, 5):
            z -= self.step_depth
            if z <= -target_depth:
                depths.append(-target_depth)
                break
            depths.append(z)
            
        for current_z in depths:
            gcode.append(f"; Depth pass: Z{current_z:.3f}")
            for ring in rings:
                if not ring: continue
                
                clean_ring = [ring[0]]
                for p in ring[1:]:
                    if math.hypot(p[0] - clean_ring[-1][0], p[1] - clean_ring[-1][1]) > min_point_dist:
                        clean_ring.append(p)
                
                if len(clean_ring) < 2: continue
                
                gcode.append(f"G0 X{clean_ring[0][0]:.3f} Y{clean_ring[0][1]:.3f} F{self.feed_rapid:.1f}")
                gcode.append(f"G1 Z{current_z:.3f} F{self.feed_plunge:.1f}")
                for p in clean_ring[1:]:
                    gcode.append(f"G1 X{p[0]:.3f} Y{p[1]:.3f} F{self.feed_cut:.1f}")
                gcode.append(f"G0 Z{SAFE_Z_HEIGHT:.3f} F{self.feed_rapid:.1f}")
        return gcode

    def _verify_shapely(self):
        """Ensures the Shapely library is loaded prior to execution."""
        if Polygon is None:
            raise RuntimeError("CRITICAL: You must run 'pip install shapely' to calculate CAM paths.")

    def export_engrave(self, shape, filepath):
        """Calculates and exports the G-Code to pocket the interior of text elements."""
        self._verify_shapely()
        stamp_poly, base_rect = self._get_shapely_polys(shape)
        if not stamp_poly: return
        
        text_poly = base_rect.difference(stamp_poly)
        rings = self._generate_pocket_paths(text_poly)
        if not rings: 
            raise RuntimeError(f"Cutter ({self.cutter_diameter}mm) is too wide to fit inside the letter strokes.")
            
        gcode = self._header("TEXT POCKET (ENGRAVE)")
        gcode.extend(self._generate_depth_passes(rings, self.depth_total_engrave))
        gcode.extend(self._footer())
        with open(filepath, 'w', encoding='utf-8') as f: f.write("\n".join(gcode) + "\n")

    def export_pocket_raised(self, shape, filepath):
        """Calculates and exports the G-Code to pocket the background, raising text."""
        self._verify_shapely()
        stamp_poly, _ = self._get_shapely_polys(shape)
        if not stamp_poly: return
        
        rings = self._generate_pocket_paths(stamp_poly)
        if not rings: 
            raise RuntimeError(f"Cutter ({self.cutter_diameter}mm) is too wide to fit between the letters.")
            
        gcode = self._header("RAISED TEXT POCKET")
        gcode.extend(self._generate_depth_passes(rings, self.depth_total_engrave))
        gcode.extend(self._footer())
        with open(filepath, 'w', encoding='utf-8') as f: f.write("\n".join(gcode) + "\n")
        
    def export_v_rough(self, shape, filepath):
        """Calculates the flat-endmill roughing clearance pass for a V-Bit profile."""
        self._verify_shapely()
        stamp_poly, _ = self._get_shapely_polys(shape)
        if not stamp_poly: return
        
        r_surface = (self.v_tip / 2.0) + (self.depth_total_engrave * math.tan(math.radians(self.v_angle / 2.0)))
        rough_area = stamp_poly.buffer(-r_surface, join_style=2).simplify(0.01)
        
        rings = self._generate_pocket_paths(rough_area)
        if not rings:
            raise RuntimeError(f"Clearance error: Flat Cutter ({self.cutter_diameter}mm) cannot fit into the V-Carve roughing area.")
            
        gcode = self._header("V-CARVE ROUGHING POCKET")
        gcode.extend(self._generate_depth_passes(rings, self.depth_total_engrave))
        gcode.extend(self._footer())
        with open(filepath, 'w', encoding='utf-8') as f: f.write("\n".join(gcode) + "\n")
        
    def export_v_finish(self, shape, filepath):
        """Calculates the precise vector profile boundaries for the V-Bit finish pass."""
        self._verify_shapely()
        stamp_poly, _ = self._get_shapely_polys(shape)
        if not stamp_poly: return
        
        r_surface = (self.v_tip / 2.0) + (self.depth_total_engrave * math.tan(math.radians(self.v_angle / 2.0)))
        profile_area = stamp_poly.buffer(-r_surface, join_style=2).simplify(0.01)
        
        if profile_area.is_empty:
            raise RuntimeError("V-Bit configuration consumes entire stamp geometry. Tool is too large/deep.")
            
        rings = []
        if profile_area.geom_type == 'Polygon':
            polys = [profile_area]
        elif profile_area.geom_type in ['MultiPolygon', 'GeometryCollection']:
            polys = list(profile_area.geoms)
        else:
            polys = []
            
        for p in polys:
            if p.is_empty or p.geom_type != 'Polygon': continue
            rings.append(list(p.exterior.coords))
            for interior in p.interiors:
                rings.append(list(interior.coords))
                
        if not rings:
            raise RuntimeError("Failed to generate V-Bit profile rings.")
            
        gcode = self._header("V-CARVE FINISH PROFILE")
        gcode.extend(self._generate_depth_passes(rings, self.depth_total_engrave))
        gcode.extend(self._footer())
        with open(filepath, 'w', encoding='utf-8') as f: f.write("\n".join(gcode) + "\n")

    def export_outside(self, shape, filepath):
        """Calculates and exports the boundary cut outlining the primary bounding box."""
        simplify_tolerance = 0.01
        mitre_join_style = 2
        
        self._verify_shapely()
        _, base_rect = self._get_shapely_polys(shape)
        if not base_rect: return
        
        toolpath = base_rect.buffer(self.cutter_diameter / 2.0, join_style=mitre_join_style).simplify(simplify_tolerance)
        rings = [list(toolpath.exterior.coords)]

        gcode = self._header("OUTSIDE CUT")
        gcode.extend(self._generate_depth_passes(rings, self.depth_total_cut))
        gcode.extend(self._footer())
        with open(filepath, 'w', encoding='utf-8') as f: f.write("\n".join(gcode) + "\n")


class CAMUIWidget(QGroupBox):
    """Encapsulated UI component managing CAM parameters and export execution."""
    state_changed = pyqtSignal()

    def __init__(self, geometry_cb, filename_cb, status_cb, parent=None):
        """Initializes the CAM widget layout, inputs, and functional linkages."""
        super().__init__(UI_TITLE_CAM, parent)
        self.geometry_cb = geometry_cb
        self.filename_cb = filename_cb
        self.status_cb = status_cb
        
        layout = QFormLayout(self)
        
        self.cam_cutter_dia = create_cam_spinbox(DEF_CUTTER_DIA, 0.1, 50.0, 0.1)
        self.cam_feed_rapid = create_cam_spinbox(DEF_FEED_RAPID, 10.0, 10000.0, 100.0)
        self.cam_feed_cut = create_cam_spinbox(DEF_FEED_CUT, 10.0, 10000.0, 50.0)
        self.cam_feed_plunge = create_cam_spinbox(DEF_FEED_PLUNGE, 10.0, 10000.0, 10.0)
        self.cam_step_depth = create_cam_spinbox(DEF_STEP_DEPTH, 0.1, 50.0, 0.5)
        self.cam_overstep = create_cam_spinbox(DEF_OVERSTEP, 0.1, 1.0, 0.1)
        self.cam_depth_cut = create_cam_spinbox(DEF_DEPTH_CUT, 0.1, 100.0, 0.5)
        self.cam_depth_engrave = create_cam_spinbox(DEF_DEPTH_ENGRAVE, 0.1, 100.0, 0.5)
        self.cam_prologue = QLineEdit(DEF_PROLOGUE)
        self.cam_epilogue = QLineEdit(DEF_EPILOGUE)
        
        self.cam_use_v_bit = QCheckBox(UI_CHK_VCUTTER)
        self.cam_v_angle = create_cam_spinbox(DEF_V_ANGLE, 10.0, 180.0, 5.0)
        self.cam_v_tip = create_cam_spinbox(DEF_V_TIP, 0.0, 10.0, 0.1)

        def hbox(w1, w2):
            h = QHBoxLayout()
            h.addWidget(w1)
            h.addWidget(w2)
            h.setContentsMargins(0, 0, 0, 0)
            c = QWidget()
            c.setLayout(h)
            return c

        layout.addRow("Flat Cutter Dia (mm):", self.cam_cutter_dia)
        layout.addRow("Feed Rapid/Cut:", hbox(self.cam_feed_rapid, self.cam_feed_cut))
        layout.addRow("Feed Plunge:", self.cam_feed_plunge)
        layout.addRow("Depth Step/Over:", hbox(self.cam_step_depth, self.cam_overstep))
        layout.addRow("Total Cut/Engrave:", hbox(self.cam_depth_cut, self.cam_depth_engrave))
        layout.addRow("Prologue/Epilogue:", hbox(self.cam_prologue, self.cam_epilogue))
        
        layout.addRow("", self.cam_use_v_bit)
        
        self.v_params_widget = QWidget()
        v_layout = QHBoxLayout(self.v_params_widget)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.addWidget(QLabel("V-Angle (°):"))
        v_layout.addWidget(self.cam_v_angle)
        v_layout.addWidget(QLabel("Tip Dia (mm):"))
        v_layout.addWidget(self.cam_v_tip)
        layout.addRow(self.v_params_widget)
        
        self.btn_export_eng = QPushButton(UI_BTN_ENGRAVE)
        self.btn_export_pock = QPushButton(UI_BTN_POCKET)
        self.btn_export_eng.setStyleSheet(f"background-color: {COLOR_BTN_ENGRAVE}; color: white;")
        self.btn_export_pock.setStyleSheet(f"background-color: {COLOR_BTN_POCKET}; color: white;")
        
        self.btn_export_v_rough = QPushButton(UI_BTN_V_ROUGH)
        self.btn_export_v_finish = QPushButton(UI_BTN_V_FINISH)
        self.btn_export_v_rough.setStyleSheet(f"background-color: {COLOR_BTN_POCKET}; color: white;")
        self.btn_export_v_finish.setStyleSheet(f"background-color: {COLOR_BTN_V}; color: white;")
        
        self.standard_btn_widget = hbox(self.btn_export_eng, self.btn_export_pock)
        self.v_btn_widget = hbox(self.btn_export_v_rough, self.btn_export_v_finish)
        
        layout.addRow(self.standard_btn_widget)
        layout.addRow(self.v_btn_widget)
        
        self.btn_export_out = QPushButton(UI_BTN_OUTSIDE)
        self.btn_export_out.setStyleSheet(f"background-color: {COLOR_BTN_OUTSIDE}; color: white;")
        layout.addRow(self.btn_export_out)

        # Wire Signals
        self.cam_use_v_bit.toggled.connect(self._toggle_v_mode)
        self.cam_use_v_bit.toggled.connect(self.state_changed.emit)
        
        for widget in [self.cam_prologue, self.cam_epilogue]: 
            widget.textChanged.connect(self.state_changed.emit)
            
        for spin in [self.cam_cutter_dia, self.cam_feed_rapid, self.cam_feed_cut, self.cam_feed_plunge,
                     self.cam_step_depth, self.cam_overstep, self.cam_depth_cut, self.cam_depth_engrave,
                     self.cam_v_angle, self.cam_v_tip]:
            spin.valueChanged.connect(self.state_changed.emit)

        self.btn_export_out.clicked.connect(self.export_outside)
        self.btn_export_eng.clicked.connect(self.export_engrave)
        self.btn_export_pock.clicked.connect(self.export_pocket_raised)
        self.btn_export_v_rough.clicked.connect(self.export_v_rough)
        self.btn_export_v_finish.clicked.connect(self.export_v_finish)
        
        self._toggle_v_mode(DEF_V_CUTTER_EN)

    def _toggle_v_mode(self, enabled):
        """Dynamically adjusts the visibility of V-Carve parameters and export buttons."""
        self.v_params_widget.setVisible(enabled)
        self.v_btn_widget.setVisible(enabled)
        self.standard_btn_widget.setVisible(not enabled)

    def get_state(self):
        """Serializes the current CAM widget configurations to a dictionary."""
        return {
            "cam_cutter_dia": self.cam_cutter_dia.value(), "cam_feed_rapid": self.cam_feed_rapid.value(),
            "cam_feed_cut": self.cam_feed_cut.value(), "cam_feed_plunge": self.cam_feed_plunge.value(),
            "cam_step_depth": self.cam_step_depth.value(), "cam_overstep": self.cam_overstep.value(),
            "cam_depth_cut": self.cam_depth_cut.value(), "cam_depth_engrave": self.cam_depth_engrave.value(),
            "cam_prologue": self.cam_prologue.text(), "cam_epilogue": self.cam_epilogue.text(),
            "cam_use_v_bit": self.cam_use_v_bit.isChecked(), "cam_v_angle": self.cam_v_angle.value(),
            "cam_v_tip_dia": self.cam_v_tip.value()
        }

    def load_state(self, cfg):
        """Restores the CAM widget configuration state from a provided dictionary."""
        self.cam_cutter_dia.setValue(cfg.get("cam_cutter_dia", DEF_CUTTER_DIA))
        self.cam_feed_rapid.setValue(cfg.get("cam_feed_rapid", DEF_FEED_RAPID))
        self.cam_feed_cut.setValue(cfg.get("cam_feed_cut", DEF_FEED_CUT))
        self.cam_feed_plunge.setValue(cfg.get("cam_feed_plunge", DEF_FEED_PLUNGE))
        self.cam_step_depth.setValue(cfg.get("cam_step_depth", DEF_STEP_DEPTH))
        self.cam_overstep.setValue(cfg.get("cam_overstep", DEF_OVERSTEP))
        self.cam_depth_cut.setValue(cfg.get("cam_depth_cut", DEF_DEPTH_CUT))
        self.cam_depth_engrave.setValue(cfg.get("cam_depth_engrave", DEF_DEPTH_ENGRAVE))
        self.cam_prologue.setText(cfg.get("cam_prologue", DEF_PROLOGUE))
        self.cam_epilogue.setText(cfg.get("cam_epilogue", DEF_EPILOGUE))
        
        use_v = cfg.get("cam_use_v_bit", DEF_V_CUTTER_EN)
        self.cam_use_v_bit.setChecked(use_v)
        self.cam_v_angle.setValue(cfg.get("cam_v_angle", DEF_V_ANGLE))
        self.cam_v_tip.setValue(cfg.get("cam_v_tip_dia", DEF_V_TIP))
        self._toggle_v_mode(use_v)

    def export_outside(self):
        """Handles user interaction to export the outside bounding G-Code."""
        shape = self.geometry_cb()
        if not shape: return
        path, _ = QFileDialog.getSaveFileName(self, "Export Outside", self.filename_cb("_outside.gcode"), FILE_FILTER_GCODE)
        if path:
            try:
                CAMGenerator(self.get_state()).export_outside(shape, path)
                self.status_cb(f"Exported Outside G-Code to {os.path.basename(path)}", 4000)
            except Exception as e:
                err_msg = str(e).split('\n')[0]
                self.status_cb(f"Export failed: {err_msg}", 6000)

    def export_engrave(self):
        """Handles user interaction to export internal text pocketing G-Code."""
        shape = self.geometry_cb()
        if not shape: return
        path, _ = QFileDialog.getSaveFileName(self, "Export Pocket Letters", self.filename_cb("_engrave.gcode"), FILE_FILTER_GCODE)
        if path:
            try:
                CAMGenerator(self.get_state()).export_engrave(shape, path)
                self.status_cb(f"Exported Pocket Letters G-Code to {os.path.basename(path)}", 4000)
            except Exception as e:
                err_msg = str(e).split('\n')[0]
                self.status_cb(f"Export failed: {err_msg}", 6000)

    def export_pocket_raised(self):
        """Handles user interaction to export negative space pocketing G-Code."""
        shape = self.geometry_cb()
        if not shape: return
        path, _ = QFileDialog.getSaveFileName(self, "Export Pocket Background", self.filename_cb("_pocket.gcode"), FILE_FILTER_GCODE)
        if path:
            try:
                CAMGenerator(self.get_state()).export_pocket_raised(shape, path)
                self.status_cb(f"Exported Pocket Background to {os.path.basename(path)}", 4000)
            except Exception as e:
                err_msg = str(e).split('\n')[0]
                self.status_cb(f"Pocket failed: {err_msg}", 6000)
                
    def export_v_rough(self):
        """Handles user interaction to export the V-Carve clearance operation."""
        shape = self.geometry_cb()
        if not shape: return
        path, _ = QFileDialog.getSaveFileName(self, "Export V-Rough (Flat Bit)", self.filename_cb("_v_rough.gcode"), FILE_FILTER_GCODE)
        if path:
            try:
                CAMGenerator(self.get_state()).export_v_rough(shape, path)
                self.status_cb(f"Exported V-Rough G-Code to {os.path.basename(path)}", 4000)
            except Exception as e:
                err_msg = str(e).split('\n')[0]
                self.status_cb(f"V-Rough failed: {err_msg}", 6000)
                
    def export_v_finish(self):
        """Handles user interaction to export the V-Carve profile finish operation."""
        shape = self.geometry_cb()
        if not shape: return
        path, _ = QFileDialog.getSaveFileName(self, "Export V-Finish (V-Bit)", self.filename_cb("_v_finish.gcode"), FILE_FILTER_GCODE)
        if path:
            try:
                CAMGenerator(self.get_state()).export_v_finish(shape, path)
                self.status_cb(f"Exported V-Finish G-Code to {os.path.basename(path)}", 4000)
            except Exception as e:
                err_msg = str(e).split('\n')[0]
                self.status_cb(f"V-Finish failed: {err_msg}", 6000)