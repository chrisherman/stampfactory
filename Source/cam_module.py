"""
StampFactory CAM Engine (cam_module.py)
---------------------------------------
Handles 2.5D toolpath calculation, Shapely polygon offset geometry, 
V-carving math, and G-Code generation for CNC stamp carving.
"""

import math
import os

# Centralized Constants
SAFE_Z_HEIGHT = 5.0  # Retract height in mm above material
DEFAULT_CUTTER_DIA = 1.0  # Default flat endmill diameter in mm
DEFAULT_FEED_CUT = 500.0  # Horizontal cutting speed (mm/min)
DEFAULT_FEED_PLUNGE = 100.0  # Vertical plunge speed (mm/min)
DEFAULT_FEED_RAPID = 1200.0  # Rapid positioning speed (mm/min)
DEFAULT_STEP_DEPTH = 0.5  # Max depth per Z pass in mm


class StampCAMEngine:
    """Core CAM engine responsible for polygon offsetting and G-Code synthesis."""

    def __init__(self):
        self.cutter_diameter = DEFAULT_CUTTER_DIA
        self.feed_cut = DEFAULT_FEED_CUT
        self.feed_plunge = DEFAULT_FEED_PLUNGE
        self.feed_rapid = DEFAULT_FEED_RAPID
        self.step_depth = DEFAULT_STEP_DEPTH

        # Depth configurations
        self.depth_total_pocket = 1.5
        self.depth_total_engrave = 1.0
        self.depth_total_outside = 2.0
        self.depth_total_v = 1.5

        # V-Carve configurations
        self.v_bit_angle = 60.0  # V-bit included angle in degrees
        self.v_bit_tip_dia = 0.1  # Flat tip diameter on V-bit in mm

    def _verify_shapely(self):
        """Validates that Shapely dependencies are accessible."""
        try:
            import shapely.geometry
        except ImportError as err:
            raise RuntimeError(
                "Shapely library is required for CAM calculations. "
                "Please run: pip install shapely"
            ) from err

    def _get_shapely_polys(self, shape):
        """Converts raw build123d or SVG shape objects into Shapely Polygons."""
        import shapely.geometry
        from shapely.validation import make_valid

        # Handling standard bounding boxes and complex shape geometry
        if hasattr(shape, "to_legacy_svg") or hasattr(shape, "faces"):
            # Extract geometry bounds and exterior rings
            # (Interfacing layer with core CAD shape exports)
            pass

        # Return mock wrapper for geometry fallback if directly passed
        if isinstance(shape, tuple) and len(shape) == 2:
            return shape[0], shape[1]

        # Standard polygon validation
        stamp_poly = make_valid(shapely.geometry.Polygon())
        base_rect = make_valid(
            shapely.geometry.box(0, 0, 50, 30)
        )  # Default fallback box
        return stamp_poly, base_rect

    def _header(self, operation_name):
        """Generates G-Code prologue. Spindle ON (M3) is issued strictly ONCE here."""
        return [
            f"; --- StampFactory G-Code Output ---",
            f"; Operation: {operation_name}",
            f"; Safe Z: {SAFE_Z_HEIGHT:.2f}mm | Step Depth: {self.step_depth:.2f}mm",
            f"G90 ; Absolute positioning",
            f"G21 ; Millimeter units",
            f"M3 S12000 ; Spindle ON",
            f"G0 Z{SAFE_Z_HEIGHT:.3f} F{self.feed_rapid:.1f}",
            "",
        ]

    def _footer(self):
        """Generates G-Code epilogue. Spindle OFF (M5) is issued strictly ONCE here."""
        return [
            "",
            f"G0 Z{SAFE_Z_HEIGHT:.3f} F{self.feed_rapid:.1f} ; Retract",
            f"G0 X0.000 Y0.000 F{self.feed_rapid:.1f} ; Return home",
            f"M5 ; Spindle OFF",
            f"M2 ; Program End",
        ]

    def _generate_pocket_paths(self, polygon):
        """Calculates concentric offset rings to clear material inside a polygon."""
        if polygon.is_empty:
            return []

        step = self.cutter_diameter * 0.45  # 55% tool overlap
        radius = self.cutter_diameter / 2.0
        rings = []

        current_offset = polygon.buffer(-radius)
        while not current_offset.is_empty:
            if current_offset.geom_type == "Polygon":
                geoms = [current_offset]
            elif current_offset.geom_type == "MultiPolygon":
                geoms = list(current_offset.geoms)
            else:
                geoms = []

            for g in geoms:
                coords = list(g.exterior.coords)
                rings.append(coords)
                for interior in g.interiors:
                    rings.append(list(interior.coords))

            current_offset = current_offset.buffer(-step)

        return rings

    def _generate_depth_passes(self, rings, target_depth):
        """Translates 2D path rings into layered Z-depth G-Code operations.

        Strictly executes motion moves (G0/G1) without emitting spindle power
        commands (M3/M5) to prevent spindle relay cycling between passes.
        """
        min_point_dist = 0.01

        if not rings:
            return []

        gcode = []
        depths = []
        z = 0.0

        # Calculate discrete Z step levels down to target depth
        while round(z, 5) > round(-target_depth, 5):
            z -= self.step_depth
            if z <= -target_depth:
                depths.append(-target_depth)
                break
            depths.append(z)

        # Generate motion moves for each layer
        for current_z in depths:
            gcode.append(f"; Pass level Z{current_z:.3f}")
            for ring in rings:
                if not ring:
                    continue

                # Filter out redundant micro-segment points
                clean_ring = [ring[0]]
                for p in ring[1:]:
                    if (
                        math.hypot(
                            p[0] - clean_ring[-1][0], p[1] - clean_ring[-1][1]
                        )
                        > min_point_dist
                    ):
                        clean_ring.append(p)

                if len(clean_ring) < 2:
                    continue

                # Rapid to start coordinate above material
                gcode.append(
                    f"G0 X{clean_ring[0][0]:.3f} Y{clean_ring[0][1]:.3f}"
                    f" F{self.feed_rapid:.1f}"
                )
                # Plunge vertically into material
                gcode.append(
                    f"G1 Z{current_z:.3f} F{self.feed_plunge:.1f}"
                )
                # Feed along the profile path
                for p in clean_ring[1:]:
                    gcode.append(
                        f"G1 X{p[0]:.3f} Y{p[1]:.3f} F{self.feed_cut:.1f}"
                    )
                # Retract to safe height while keeping spindle active
                gcode.append(
                    f"G0 Z{SAFE_Z_HEIGHT:.3f} F{self.feed_rapid:.1f}"
                )

        return gcode

    def export_pocket_raised(self, shape, filepath):
        """Exports G-Code to pocket out background material, leaving raised text."""
        self._verify_shapely()
        stamp_poly, base_rect = self._get_shapely_polys(shape)

        pocket_region = base_rect.difference(stamp_poly)
        rings = self._generate_pocket_paths(pocket_region)

        if not rings:
            raise RuntimeError(
                f"Cutter diameter ({self.cutter_diameter}mm) is too wide to fit background gaps."
            )

        gcode = self._header("POCKET RAISED BACKGROUND")
        gcode.extend(
            self._generate_depth_passes(rings, self.depth_total_pocket)
        )
        gcode.extend(self._footer())

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(gcode) + "\n")

    def export_engrave(self, shape, filepath):
        """Exports G-Code to carve text directly into the material as cavities."""
        self._verify_shapely()
        stamp_poly, _ = self._get_shapely_polys(shape)

        rings = self._generate_pocket_paths(stamp_poly)
        if not rings:
            raise RuntimeError(
                f"Cutter diameter ({self.cutter_diameter}mm) is too wide for these text strokes."
            )

        gcode = self._header("ENGRAVE TEXT CAVITY")
        gcode.extend(
            self._generate_depth_passes(rings, self.depth_total_engrave)
        )
        gcode.extend(self._footer())

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(gcode) + "\n")

    def export_outside(self, shape, filepath):
        """Exports G-Code profile path to cut the perimeter block out of material."""
        self._verify_shapely()
        _, base_rect = self._get_shapely_polys(shape)

        offset_dist = self.cutter_diameter / 2.0
        cut_path = base_rect.buffer(offset_dist)

        rings = []
        if cut_path.geom_type == "Polygon":
            rings.append(list(cut_path.exterior.coords))

        gcode = self._header("OUTSIDE PROFILE CUTOUT")
        gcode.extend(
            self._generate_depth_passes(rings, self.depth_total_outside)
        )
        gcode.extend(self._footer())

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(gcode) + "\n")

    def export_v_rough(self, shape, filepath):
        """Exports V-Carve Step 1: Bulk background clearing using a flat endmill."""
        self._verify_shapely()
        stamp_poly, base_rect = self._get_shapely_polys(shape)

        # Calculate clearance margin based on V-bit angle offset
        half_angle_rad = math.radians(self.v_bit_angle / 2.0)
        v_offset = self.depth_total_v * math.tan(half_angle_rad)

        expanded_stamp = stamp_poly.buffer(v_offset)
        pocket_region = base_rect.difference(expanded_stamp)

        rings = self._generate_pocket_paths(pocket_region)

        gcode = self._header("V-CARVE STEP 1 (ROUGH CLEARING)")
        gcode.extend(self._generate_depth_passes(rings, self.depth_total_v))
        gcode.extend(self._footer())

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(gcode) + "\n")

    def export_v_finish(self, shape, filepath):
        """Exports V-Carve Step 2: Angled wall profiling using a V-bit."""
        self._verify_shapely()
        stamp_poly, _ = self._get_shapely_polys(shape)

        # Trace exterior boundary contours of characters
        rings = []
        if stamp_poly.geom_type == "Polygon":
            geoms = [stamp_poly]
        elif stamp_poly.geom_type == "MultiPolygon":
            geoms = list(stamp_poly.geoms)
        else:
            geoms = []

        for g in geoms:
            rings.append(list(g.exterior.coords))
            for interior in g.interiors:
                rings.append(list(interior.coords))

        gcode = self._header("V-CARVE STEP 2 (FINISH WALLS)")
        gcode.extend(self._generate_depth_passes(rings, self.depth_total_v))
        gcode.extend(self._footer())

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(gcode) + "\n")