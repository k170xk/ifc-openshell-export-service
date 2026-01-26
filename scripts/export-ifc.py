#!/usr/bin/env python3
"""
IFC Export Service using IfcOpenShell
Receives chamber data via JSON and exports to IFC file
"""

import sys
import json
import math

import numpy as np
import ifcopenshell
from ifcopenshell.api import run as ifc_run

DEFAULT_PROJECT_NAME = "InfraGrid3D Project"


UNIT_MAPPING = {
    "meters": {"is_metric": True, "raw": "METERS"},
    "meter": {"is_metric": True, "raw": "METERS"},
    "m": {"is_metric": True, "raw": "METERS"},
    "millimeters": {"is_metric": True, "raw": "MILLIMETERS"},
    "millimetres": {"is_metric": True, "raw": "MILLIMETERS"},
    "mm": {"is_metric": True, "raw": "MILLIMETERS"},
    "feet": {"is_metric": False, "raw": "FEET"},
    "foot": {"is_metric": False, "raw": "FEET"},
    "ft": {"is_metric": False, "raw": "FEET"},
    "inches": {"is_metric": False, "raw": "INCHES"},
    "inch": {"is_metric": False, "raw": "INCHES"},
    "in": {"is_metric": False, "raw": "INCHES"},
}


def hex_to_rgb(hex_color):
    """
    Convert hex color to RGB values (0-1 range for IFC).
    Input: "#FF0000" or "FF0000"
    Output: (1.0, 0.0, 0.0)
    """
    if not hex_color:
        return None
    
    # Remove '#' if present
    hex_color = hex_color.lstrip('#')
    
    # Parse hex values
    try:
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
        return (r, g, b)
    except (ValueError, IndexError):
        print(f"[COLOR] Warning: Invalid hex color '{hex_color}', using default")
        return None


def apply_color_to_element(ifc_file, element, color_hex):
    """
    Apply a color to an IFC element using surface style.
    """
    if not color_hex:
        return
    
    rgb = hex_to_rgb(color_hex)
    if not rgb:
        return
    
    print(f"[COLOR] Applying color {color_hex} (RGB: {rgb}) to {element.Name}")
    
    # Create surface color
    surface_color = ifc_file.createIfcColourRgb(None, rgb[0], rgb[1], rgb[2])
    
    # Create rendering style
    rendering_style = ifc_file.createIfcSurfaceStyleRendering(
        surface_color,  # SurfaceColour
        None,  # Transparency
        None,  # DiffuseColour
        None,  # TransmissionColour
        None,  # DiffuseTransmissionColour
        None,  # ReflectionColour
        None,  # SpecularColour
        None,  # SpecularHighlight
        "FLAT"  # ReflectanceMethod
    )
    
    # Create surface style
    surface_style = ifc_file.createIfcSurfaceStyle(
        None,  # Name
        "BOTH",  # Side (POSITIVE, NEGATIVE, BOTH)
        [rendering_style]  # Styles
    )
    
    # Create styled item for the element's representation
    if hasattr(element, 'Representation') and element.Representation:
        for representation in element.Representation.Representations:
            for item in representation.Items:
                ifc_file.createIfcStyledItem(
                    item,  # Item
                    [ifc_file.createIfcPresentationStyleAssignment([surface_style])],  # Styles
                    None  # Name
                )


def determine_length_unit_settings(project_coords):
    unit_label = (project_coords or {}).get("unit", "meters")
    return UNIT_MAPPING.get(str(unit_label).lower(), UNIT_MAPPING["meters"])


def assign_project_units(ifc_file, project_coords):
    length_settings = determine_length_unit_settings(project_coords)
    ifc_run(
        "unit.assign_unit",
        file=ifc_file,
        length=length_settings,
        area={"is_metric": True, "raw": "METERS"},
        volume={"is_metric": True, "raw": "METERS"},
    )


def apply_georeferencing(ifc_file, project_coords):
    """Apply georeferencing to IFC file using standard IfcMapConversion.
    
    IFC Standard (ISO 16739):
    - Eastings: X coordinate (horizontal east)
    - Northings: Y coordinate (horizontal north)
    - OrthogonalHeight: Z coordinate (vertical elevation)
    
    This is the standard civil engineering / surveying convention.
    """
    if not project_coords:
        print("[GEOREFERENCE] No project coordinates provided, skipping georeferencing")
        return

    origin = project_coords.get("origin") or {}
    if not origin:
        print("[GEOREFERENCE] No origin in project coordinates, skipping georeferencing")
        return

    print(f"[GEOREFERENCE] Applying IfcMapConversion:")
    print(f"[GEOREFERENCE]   Input from app: x={origin.get('x', 0.0)}, y={origin.get('y', 0.0)}, z={origin.get('z', 0.0)}")
    
    ifc_run("georeference.add_georeferencing", file=ifc_file)

    # Convert Y-up (Three.js) to Z-up (IFC/Revit)
    # App: {x: easting, y: elevation, z: northing}
    # IFC: {Eastings, Northings, OrthogonalHeight}
    coordinate_operation = {
        "Eastings": origin.get("x", 0.0),
        "Northings": origin.get("z", 0.0),  # z → northing
        "OrthogonalHeight": origin.get("y", 0.0),  # y → height
    }
    
    print(f"[GEOREFERENCE]   Converting Y-up to Z-up:")
    print(f"[GEOREFERENCE]     Eastings = {coordinate_operation['Eastings']} (from x)")
    print(f"[GEOREFERENCE]     Northings = {coordinate_operation['Northings']} (from z)")
    print(f"[GEOREFERENCE]     OrthogonalHeight = {coordinate_operation['OrthogonalHeight']} (from y)")

    north_angle = project_coords.get("northAngle")
    if north_angle is not None:
        angle_rad = math.radians(north_angle)
        coordinate_operation["XAxisAbscissa"] = math.cos(angle_rad)
        coordinate_operation["XAxisOrdinate"] = math.sin(angle_rad)
        print(f"[GEOREFERENCE]     Rotation: {north_angle}° (XAxisAbscissa={coordinate_operation['XAxisAbscissa']:.6f}, XAxisOrdinate={coordinate_operation['XAxisOrdinate']:.6f})")

    projected_crs = {}
    epsg_code = project_coords.get("epsgCode")
    if epsg_code:
        projected_crs["Name"] = epsg_code
        print(f"[GEOREFERENCE]     EPSG: {epsg_code}")
    elif project_coords.get("name"):
        projected_crs["Name"] = project_coords["name"]
        print(f"[GEOREFERENCE]     CRS Name: {project_coords['name']}")

    ifc_run(
        "georeference.edit_georeferencing",
        file=ifc_file,
        coordinate_operation=coordinate_operation,
        projected_crs=projected_crs if projected_crs else None,
    )
    
    print("[GEOREFERENCE] ✅ Georeferencing applied successfully")


def get_project_origin_tuple(project_coords):
    origin = (project_coords or {}).get("origin") or {}
    return (
        float(origin.get("x", 0.0)),
        float(origin.get("y", 0.0)),
        float(origin.get("z", 0.0)),
    )


def convert_world_to_mode(x, y, z, origin_tuple, coordinate_mode):
    if coordinate_mode == "project":
        return (
            x - origin_tuple[0],
            y - origin_tuple[1],
            z - origin_tuple[2],
        )
    return (x, y, z)


def convert_point_yup_to_ifc(point, origin_tuple, coordinate_mode):
    world_x = float(point[0]) if len(point) > 0 else 0.0
    world_y = float(point[1]) if len(point) > 1 else 0.0
    world_z = float(point[2]) if len(point) > 2 else 0.0

    local_x, local_y, local_z = convert_world_to_mode(
        world_x,
        world_y,
        world_z,
        origin_tuple,
        coordinate_mode,
    )

    # Return IFC Z-up ordering [X (easting), Y (northing), Z (elevation)]
    return [local_x, local_z, local_y]


def convert_points_yup_to_ifc(points, origin_tuple, coordinate_mode):
    return [convert_point_yup_to_ifc(pt, origin_tuple, coordinate_mode) for pt in points]


def convert_direction_yup_to_ifc(direction):
    dx = float(direction[0]) if len(direction) > 0 else 0.0
    dy = float(direction[1]) if len(direction) > 1 else 0.0
    dz = float(direction[2]) if len(direction) > 2 else 0.0
    return [dx, dz, dy]


def create_ifc_file(project_name=DEFAULT_PROJECT_NAME, project_coords=None, coordinate_mode="absolute"):
    """Create a new IFC4 file with proper project hierarchy, units, and contexts."""

    ifc_file = ifc_run("project.create_file", version="IFC4")

    project = ifc_run(
        "root.create_entity",
        file=ifc_file,
        ifc_class="IfcProject",
        name=project_name or DEFAULT_PROJECT_NAME,
    )

    assign_project_units(ifc_file, project_coords)

    model_context = ifc_run("context.add_context", file=ifc_file, context_type="Model")
    body_context = ifc_run(
        "context.add_context",
        file=ifc_file,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_context,
    )

    site = ifc_run("root.create_entity", file=ifc_file, ifc_class="IfcSite", name="Site")
    building = ifc_run("root.create_entity", file=ifc_file, ifc_class="IfcBuilding", name="Building")
    storey = ifc_run("root.create_entity", file=ifc_file, ifc_class="IfcBuildingStorey", name="Ground")

    storey_elevation = (project_coords or {}).get("elevation")
    if storey_elevation is not None:
        storey.Elevation = storey_elevation

    ifc_run("aggregate.assign_object", file=ifc_file, products=[site], relating_object=project)
    ifc_run("aggregate.assign_object", file=ifc_file, products=[building], relating_object=site)
    ifc_run("aggregate.assign_object", file=ifc_file, products=[storey], relating_object=building)

    # Storey placement at world origin for both coordinate modes
    # Chambers will be placed with coordinates derived per mode (PlacementRelTo=None)
    storey_matrix = np.eye(4)  # Identity matrix = world origin
    storey_placement = ifc_run(
        "geometry.edit_object_placement",
        file=ifc_file,
        product=storey,
        matrix=storey_matrix,
        is_si=True,
    )
    print(f"[STOREY] Created storey placement at world origin")
    print(f"[STOREY] storey.ObjectPlacement = {storey.ObjectPlacement}")

    if coordinate_mode == "project":
        apply_georeferencing(ifc_file, project_coords)
    else:
        print("[GEOREFERENCE] ⚠️  IfcMapConversion skipped (absolute coordinate mode)")
        print("[GEOREFERENCE]    Geometry already uses real-world coordinates")

    return ifc_file, storey, body_context


def create_chamber_geometry_solids(
    ifc_file,
    width,
    length,
    height,
    base_thickness=0.0,
    top_thickness=0.0,
    shape="rectangle",
    diameter=None,
    wall_thickness=0.0,
    lid_config=None,
):
    """Create chamber geometry as separate solids: walls, base slab, and top slab.
    
    Returns a list of IFC solid geometry items.
    Uses 48-segment polygon profiles for circular chambers.
    
    Structure:
    - Base slab: solid at bottom (Z=0 to Z=base_thickness)
    - Walls: hollow extrusion (Z=base_thickness to Z=base_thickness+height-top_thickness)
    - Top slab: solid at top with opening for access (Z=base_thickness+height-top_thickness to Z=base_thickness+height)
    """
    NUM_SEGMENTS = 48
    solids = []
    
    axis_placement = ifc_file.createIfcAxis2Placement2D(
        ifc_file.createIfcCartesianPoint((0.0, 0.0)),
        ifc_file.createIfcDirection((1.0, 0.0)),
    )
    
    wall_thickness = max(float(wall_thickness or 0.0), 0.0)
    base_thickness = max(float(base_thickness or 0.0), 0.0)
    top_thickness = max(float(top_thickness or 0.0), 0.0)
    
    # Calculate dimensions
    if shape == "circle" and diameter and diameter > 0:
        radius = max(diameter / 2.0, 0.01)
        inner_radius = radius - wall_thickness if wall_thickness > 0 else 0
    else:
        radius = None
        inner_radius = None
    
    # Wall height (between slabs)
    wall_height = max(height - top_thickness, 0.1)
    
    print(f"[CHAMBER]   Creating geometry with base={base_thickness}m, walls={wall_height}m, top={top_thickness}m")
    
    # ===== 1. BASE SLAB (solid) =====
    if base_thickness > 0:
        if shape == "circle" and radius:
            # Circular base slab (high detail)
            base_points = []
            for i in range(NUM_SEGMENTS):
                angle = 2 * math.pi * i / NUM_SEGMENTS
                x = radius * math.cos(angle)
                y = radius * math.sin(angle)
                base_points.append(ifc_file.createIfcCartesianPoint((x, y)))
            base_points.append(base_points[0])
            base_polyline = ifc_file.createIfcPolyline(base_points)
            base_profile = ifc_file.createIfcArbitraryClosedProfileDef("AREA", None, base_polyline)
        else:
            # Rectangular base slab
            base_profile = ifc_file.createIfcRectangleProfileDef(
                "AREA", None, axis_placement, width, length
            )
        
        base_extrusion = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0)),
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            ifc_file.createIfcDirection((1.0, 0.0, 0.0))
        )
        base_solid = ifc_file.createIfcExtrudedAreaSolid(
            base_profile,
            base_extrusion,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            base_thickness
        )
        solids.append(base_solid)
        print(f"[CHAMBER]   ✓ Base slab: {base_thickness}m thick")
    
    # ===== 2. WALLS (hollow) =====
    if wall_height > 0:
        if shape == "circle" and radius:
            if wall_thickness > 0 and inner_radius > 0:
                # Hollow circular walls
                outer_points = []
                for i in range(NUM_SEGMENTS):
                    angle = 2 * math.pi * i / NUM_SEGMENTS
                    x = radius * math.cos(angle)
                    y = radius * math.sin(angle)
                    outer_points.append(ifc_file.createIfcCartesianPoint((x, y)))
                outer_points.append(outer_points[0])
                outer_polyline = ifc_file.createIfcPolyline(outer_points)
                
                inner_points = []
                for i in range(NUM_SEGMENTS):
                    angle = 2 * math.pi * (NUM_SEGMENTS - i) / NUM_SEGMENTS
                    x = inner_radius * math.cos(angle)
                    y = inner_radius * math.sin(angle)
                    inner_points.append(ifc_file.createIfcCartesianPoint((x, y)))
                inner_points.append(inner_points[0])
                inner_polyline = ifc_file.createIfcPolyline(inner_points)
                
                wall_profile = ifc_file.createIfcArbitraryProfileDefWithVoids(
                    "AREA", None, outer_polyline, [inner_polyline]
                )
            else:
                # Solid circular (no wall thickness specified)
                wall_points = []
                for i in range(NUM_SEGMENTS):
                    angle = 2 * math.pi * i / NUM_SEGMENTS
                    x = radius * math.cos(angle)
                    y = radius * math.sin(angle)
                    wall_points.append(ifc_file.createIfcCartesianPoint((x, y)))
                wall_points.append(wall_points[0])
                wall_polyline = ifc_file.createIfcPolyline(wall_points)
                wall_profile = ifc_file.createIfcArbitraryClosedProfileDef("AREA", None, wall_polyline)
        else:
            # Rectangular walls
            if wall_thickness > 0 and wall_thickness * 2 < width and wall_thickness * 2 < length:
                wall_profile = ifc_file.createIfcRectangleHollowProfileDef(
                    "AREA", None, axis_placement, width, length, wall_thickness
                )
            else:
                wall_profile = ifc_file.createIfcRectangleProfileDef(
                    "AREA", None, axis_placement, width, length
                )
        
        wall_extrusion = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0, base_thickness)),
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            ifc_file.createIfcDirection((1.0, 0.0, 0.0))
        )
        wall_solid = ifc_file.createIfcExtrudedAreaSolid(
            wall_profile,
            wall_extrusion,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            wall_height
        )
        solids.append(wall_solid)
        print(f"[CHAMBER]   ✓ Walls: {wall_height}m tall, {wall_thickness}m thick ({NUM_SEGMENTS} segments)")
    
    # ===== 3. TOP SLAB (solid with opening for lid) =====
    if top_thickness > 0:
        top_z = base_thickness + wall_height
        
        # Determine opening size from lid config or use defaults
        # The opening should match the lid frame OUTER dimensions exactly
        # Lid frame outer radius = lid_radius + frame_thickness (for circular)
        # Lid frame outer size = lid_size + frame_thickness (for rectangular)
        if lid_config:
            lid_shape = lid_config.get("shape", shape)
            lid_frame_thickness = lid_config.get("frameThickness", 75) / 1000  # mm to m
            
            if lid_shape == "circle":
                # Match lid frame outer radius exactly
                # Lid frame: outer_radius = lid_radius + frame_thickness
                lid_diameter = lid_config.get("diameter")
                if lid_diameter:
                    lid_radius_m = (lid_diameter / 1000) / 2
                    # Frame outer radius = lid_radius + frame_thickness
                    opening_radius = lid_radius_m + lid_frame_thickness
                else:
                    opening_radius = radius * 0.5 if radius else min(width, length) * 0.25
                print(f"[CHAMBER]   Lid frame outer radius: {opening_radius}m (lid_r={lid_radius_m if lid_diameter else 'N/A'}m, frame={lid_frame_thickness}m)")
            else:
                # Rectangular lid opening
                # Lid frame: outer_size = lid_size + frame_thickness
                lid_width_cfg = lid_config.get("width")
                lid_length_cfg = lid_config.get("length")
                if lid_width_cfg:
                    opening_width = lid_width_cfg / 1000 + lid_frame_thickness
                else:
                    opening_width = width * 0.5
                if lid_length_cfg:
                    opening_length = lid_length_cfg / 1000 + lid_frame_thickness
                else:
                    opening_length = length * 0.5
                print(f"[CHAMBER]   Lid frame outer size: {opening_width}m x {opening_length}m")
        else:
            # No lid config - use inner wall dimensions or 50% of outer
            if shape == "circle" and radius:
                opening_radius = inner_radius if inner_radius and inner_radius > 0 else radius * 0.5
            else:
                opening_width = width - wall_thickness * 2 if wall_thickness > 0 else width * 0.5
                opening_length = length - wall_thickness * 2 if wall_thickness > 0 else length * 0.5
        
        # Determine if opening should be circular or rectangular
        use_circular_opening = (lid_config and lid_config.get("shape") == "circle") or (shape == "circle" and not lid_config)
        
        if shape == "circle" and radius:
            # Circular top slab
            # Outer boundary
            outer_points = []
            for i in range(NUM_SEGMENTS):
                angle = 2 * math.pi * i / NUM_SEGMENTS
                x = radius * math.cos(angle)
                y = radius * math.sin(angle)
                outer_points.append(ifc_file.createIfcCartesianPoint((x, y)))
            outer_points.append(outer_points[0])
            outer_polyline = ifc_file.createIfcPolyline(outer_points)
            
            # Inner opening (clockwise) - use lid-based opening_radius
            if not lid_config or lid_config.get("shape") == "circle":
                inner_points = []
                for i in range(NUM_SEGMENTS):
                    angle = 2 * math.pi * (NUM_SEGMENTS - i) / NUM_SEGMENTS
                    x = opening_radius * math.cos(angle)
                    y = opening_radius * math.sin(angle)
                    inner_points.append(ifc_file.createIfcCartesianPoint((x, y)))
                inner_points.append(inner_points[0])
                inner_polyline = ifc_file.createIfcPolyline(inner_points)
            else:
                # Rectangular opening in circular slab
                half_ow = opening_width / 2
                half_ol = opening_length / 2
                inner_points = [
                    ifc_file.createIfcCartesianPoint((-half_ow, -half_ol)),
                    ifc_file.createIfcCartesianPoint((-half_ow, half_ol)),
                    ifc_file.createIfcCartesianPoint((half_ow, half_ol)),
                    ifc_file.createIfcCartesianPoint((half_ow, -half_ol)),
                    ifc_file.createIfcCartesianPoint((-half_ow, -half_ol)),
                ]
                inner_polyline = ifc_file.createIfcPolyline(inner_points)
            
            top_profile = ifc_file.createIfcArbitraryProfileDefWithVoids(
                "AREA", None, outer_polyline, [inner_polyline]
            )
            print(f"[CHAMBER]   Top slab opening: circular radius={opening_radius}m")
        else:
            # Rectangular top slab
            # Outer boundary
            half_w = width / 2
            half_l = length / 2
            outer_points = [
                ifc_file.createIfcCartesianPoint((-half_w, -half_l)),
                ifc_file.createIfcCartesianPoint((half_w, -half_l)),
                ifc_file.createIfcCartesianPoint((half_w, half_l)),
                ifc_file.createIfcCartesianPoint((-half_w, half_l)),
                ifc_file.createIfcCartesianPoint((-half_w, -half_l)),
            ]
            outer_polyline = ifc_file.createIfcPolyline(outer_points)
            
            # Inner opening (clockwise)
            if lid_config and lid_config.get("shape") == "circle":
                # Circular opening in rectangular slab
                inner_points = []
                for i in range(NUM_SEGMENTS):
                    angle = 2 * math.pi * (NUM_SEGMENTS - i) / NUM_SEGMENTS
                    x = opening_radius * math.cos(angle)
                    y = opening_radius * math.sin(angle)
                    inner_points.append(ifc_file.createIfcCartesianPoint((x, y)))
                inner_points.append(inner_points[0])
                inner_polyline = ifc_file.createIfcPolyline(inner_points)
                print(f"[CHAMBER]   Top slab opening: circular radius={opening_radius}m")
            else:
                # Rectangular opening
                half_iw = opening_width / 2
                half_il = opening_length / 2
                inner_points = [
                    ifc_file.createIfcCartesianPoint((-half_iw, -half_il)),
                    ifc_file.createIfcCartesianPoint((-half_iw, half_il)),
                    ifc_file.createIfcCartesianPoint((half_iw, half_il)),
                    ifc_file.createIfcCartesianPoint((half_iw, -half_il)),
                    ifc_file.createIfcCartesianPoint((-half_iw, -half_il)),
                ]
                inner_polyline = ifc_file.createIfcPolyline(inner_points)
                print(f"[CHAMBER]   Top slab opening: rectangular {opening_width}m x {opening_length}m")
            
            top_profile = ifc_file.createIfcArbitraryProfileDefWithVoids(
                "AREA", None, outer_polyline, [inner_polyline]
            )
        
        top_extrusion = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0, top_z)),
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            ifc_file.createIfcDirection((1.0, 0.0, 0.0))
        )
        top_solid = ifc_file.createIfcExtrudedAreaSolid(
            top_profile,
            top_extrusion,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            top_thickness
        )
        solids.append(top_solid)
        print(f"[CHAMBER]   ✓ Top slab: {top_thickness}m thick at Z={top_z}m")
    
    print(f"[CHAMBER]   ✅ Created {len(solids)} geometry components")
    return solids


def create_chamber_representation(
    ifc_file,
    context,
    width,
    length,
    height,
    base_thickness=0.0,
    top_thickness=0.0,
    shape="rectangle",
    diameter=None,
    wall_thickness=0.0,
    lid_config=None,
):
    """Create chamber representation with walls, base slab, and top slab.
    
    Uses create_chamber_geometry_solids to generate the geometry.
    """
    solids = create_chamber_geometry_solids(
        ifc_file,
        width,
        length,
        height,
        base_thickness,
        top_thickness,
        shape,
        diameter,
        wall_thickness,
        lid_config,
    )
    
    if not solids:
        # Fallback to simple extrusion if no solids created
        NUM_SEGMENTS = 48
        axis_placement = ifc_file.createIfcAxis2Placement2D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0)),
            ifc_file.createIfcDirection((1.0, 0.0)),
        )
        
        if shape == "circle" and diameter and diameter > 0:
            radius = max(diameter / 2.0, 0.01)
            points = []
            for i in range(NUM_SEGMENTS):
                angle = 2 * math.pi * i / NUM_SEGMENTS
                x = radius * math.cos(angle)
                y = radius * math.sin(angle)
                points.append(ifc_file.createIfcCartesianPoint((x, y)))
            points.append(points[0])
            polyline = ifc_file.createIfcPolyline(points)
            profile = ifc_file.createIfcArbitraryClosedProfileDef("AREA", None, polyline)
        else:
            profile = ifc_file.createIfcRectangleProfileDef(
                "AREA", None, axis_placement, width, length
            )
        
        depth = max(height + base_thickness, 0.1)
        return ifc_run(
            "geometry.add_profile_representation",
            file=ifc_file,
            context=context,
            profile=profile,
            depth=depth,
        )
    
    # Create shape representation with all solids
    shape_rep = ifc_file.createIfcShapeRepresentation(
        context,
        "Body",
        "SweptSolid",
        solids
    )
    
    return shape_rep


def create_circular_polygon_profile(ifc_file, radius, num_segments=32):
    """Create a high-detail circular profile using polygon approximation.
    
    This provides more visual detail than IfcCircleProfileDef which may render
    with low segment count in some viewers.
    
    Args:
        ifc_file: IFC file object
        radius: Radius of the circle in meters
        num_segments: Number of segments for the polygon (default 32 for smooth appearance)
    
    Returns:
        IfcArbitraryClosedProfileDef with polygon approximating a circle
    """
    points = []
    for i in range(num_segments):
        angle = 2 * math.pi * i / num_segments
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        points.append(ifc_file.createIfcCartesianPoint((x, y)))
    
    # Close the polygon by adding the first point again
    points.append(points[0])
    
    polyline = ifc_file.createIfcPolyline(points)
    profile = ifc_file.createIfcArbitraryClosedProfileDef("AREA", None, polyline)
    return profile


def create_circular_hollow_polygon_profile(ifc_file, outer_radius, inner_radius, num_segments=32):
    """Create a high-detail hollow circular profile (ring) using polygon approximation.
    
    Args:
        ifc_file: IFC file object
        outer_radius: Outer radius in meters
        inner_radius: Inner radius in meters
        num_segments: Number of segments for each circle
    
    Returns:
        IfcArbitraryProfileDefWithVoids for a ring shape
    """
    # Outer boundary (counter-clockwise)
    outer_points = []
    for i in range(num_segments):
        angle = 2 * math.pi * i / num_segments
        x = outer_radius * math.cos(angle)
        y = outer_radius * math.sin(angle)
        outer_points.append(ifc_file.createIfcCartesianPoint((x, y)))
    outer_points.append(outer_points[0])  # Close
    outer_polyline = ifc_file.createIfcPolyline(outer_points)
    
    # Inner boundary (clockwise for void)
    inner_points = []
    for i in range(num_segments):
        angle = 2 * math.pi * (num_segments - i) / num_segments  # Clockwise
        x = inner_radius * math.cos(angle)
        y = inner_radius * math.sin(angle)
        inner_points.append(ifc_file.createIfcCartesianPoint((x, y)))
    inner_points.append(inner_points[0])  # Close
    inner_polyline = ifc_file.createIfcPolyline(inner_points)
    
    profile = ifc_file.createIfcArbitraryProfileDefWithVoids(
        "AREA", None, outer_polyline, [inner_polyline]
    )
    return profile


def create_lid_representation(
    ifc_file,
    context,
    lid_config,
    chamber_shape,
    chamber_width,
    chamber_length,
    chamber_diameter,
):
    """Create lid geometry for a chamber - MATCHING Three.js model exactly.
    
    Three.js Model Structure:
    - Circular Frame: Torus with frameRadius = lidRadius + frameThickness/2, tube radius = frameThickness/2
    - Circular Lid: Cylinder with lidRadius, centered at frameThickness/2 height (sits inside frame)
    - Rectangular Frame: Solid box (lidWidth + frameThickness) x frameThickness x (lidLength + frameThickness)
    - Rectangular Lid: Solid box lidWidth x lidThickness x lidLength, on top of frame
    
    Args:
        ifc_file: IFC file object
        context: IFC geometric representation context
        lid_config: Dictionary with lid configuration
        chamber_shape: Chamber shape ('circle' or 'rectangle')
        chamber_width: Chamber width in meters (fallback for lid)
        chamber_length: Chamber length in meters (fallback for lid)
        chamber_diameter: Chamber diameter in meters (fallback for circular lid)
    
    Returns:
        List of IFC solid geometry items for the lid (frame + cover + vent holes)
    """
    if not lid_config:
        return []
    
    # Get lid dimensions (convert mm to meters)
    lid_shape = lid_config.get("shape", chamber_shape)
    lid_thickness = lid_config.get("thickness", 50) / 1000  # Default 50mm
    frame_thickness = lid_config.get("frameThickness", 75) / 1000  # Default 75mm
    
    # Vent hole configuration
    has_vent_holes = lid_config.get("hasVentHoles", False)
    vent_hole_count = lid_config.get("ventHoleCount", 0) if has_vent_holes else 0
    
    # Number of segments for circular geometry (high detail)
    NUM_SEGMENTS = 48  # High detail for smooth circles
    
    # Lid dimensions - use lid-specific or fall back to chamber dimensions
    if lid_shape == "circle":
        lid_diameter = lid_config.get("diameter")
        if lid_diameter:
            lid_diameter = lid_diameter / 1000  # mm to m
        else:
            # Fall back to chamber diameter or min of width/length
            lid_diameter = chamber_diameter if chamber_diameter else min(chamber_width, chamber_length)
        lid_radius = lid_diameter / 2
        print(f"[LID]   Creating circular lid (matching Three.js model):")
        print(f"[LID]     Lid: diameter={lid_diameter}m, thickness={lid_thickness}m")
        print(f"[LID]     Frame: thickness={frame_thickness}m (torus tube radius={frame_thickness/2}m)")
        if has_vent_holes and vent_hole_count > 0:
            print(f"[LID]     Vent holes: {vent_hole_count}")
    else:
        lid_width = lid_config.get("width")
        lid_length = lid_config.get("length")
        if lid_width:
            lid_width = lid_width / 1000  # mm to m
        else:
            lid_width = chamber_width
        if lid_length:
            lid_length = lid_length / 1000  # mm to m
        else:
            lid_length = chamber_length
        print(f"[LID]   Creating rectangular lid (matching Three.js model):")
        print(f"[LID]     Lid: {lid_width}m x {lid_length}m, thickness={lid_thickness}m")
        print(f"[LID]     Frame: {lid_width + frame_thickness}m x {lid_length + frame_thickness}m, height={frame_thickness}m")
        if has_vent_holes and vent_hole_count > 0:
            print(f"[LID]     Vent holes: {vent_hole_count}")
    
    solids = []
    
    # Create axis placement for profiles (centered at origin)
    axis_placement = ifc_file.createIfcAxis2Placement2D(
        ifc_file.createIfcCartesianPoint((0.0, 0.0)),
        ifc_file.createIfcDirection((1.0, 0.0)),
    )
    
    if lid_shape == "circle":
        # ===== CIRCULAR LID - Match Three.js Torus Frame =====
        # Three.js: frameRadius = lidRadius + frameThickness/2, tube radius = frameThickness/2
        # This creates a torus (ring) that sits around the lid edge
        
        frame_tube_radius = frame_thickness / 2
        frame_center_radius = lid_radius + frame_tube_radius  # Center of torus tube
        
        # For IFC, approximate torus as a hollow ring extrusion
        # Outer radius = frame_center_radius + frame_tube_radius
        # Inner radius = frame_center_radius - frame_tube_radius = lid_radius
        frame_outer_radius = frame_center_radius + frame_tube_radius
        frame_inner_radius = lid_radius  # Inner edge touches the lid
        
        # Frame profile (hollow circle with high detail)
        frame_profile = create_circular_hollow_polygon_profile(
            ifc_file, frame_outer_radius, frame_inner_radius, NUM_SEGMENTS
        )
        
        # Frame extrusion - height matches the tube diameter (frame_thickness)
        # Centered vertically at Z=0 to Z=frame_thickness
        frame_extrusion = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0)),
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            ifc_file.createIfcDirection((1.0, 0.0, 0.0))
        )
        
        frame_solid = ifc_file.createIfcExtrudedAreaSolid(
            frame_profile,
            frame_extrusion,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            frame_thickness  # Height = tube diameter
        )
        solids.append(frame_solid)
        
        # ===== CIRCULAR LID - Sits inside frame =====
        # Three.js: lid.position.y = height + lidThickness/2
        # The lid sits centered vertically within the frame height
        
        # Lid with optional vent holes
        if has_vent_holes and vent_hole_count > 0:
            # Create lid profile with vent holes as voids
            vent_hole_radius = 0.02  # 20mm radius vent holes (matching Three.js)
            vent_ring_radius = lid_radius * 0.6  # Vents at 60% of lid radius
            
            # Outer boundary (counter-clockwise)
            outer_points = []
            for i in range(NUM_SEGMENTS):
                angle = 2 * math.pi * i / NUM_SEGMENTS
                x = lid_radius * math.cos(angle)
                y = lid_radius * math.sin(angle)
                outer_points.append(ifc_file.createIfcCartesianPoint((x, y)))
            outer_points.append(outer_points[0])
            outer_polyline = ifc_file.createIfcPolyline(outer_points)
            
            # Create vent hole voids (clockwise for voids)
            vent_voids = []
            vent_segments = 16  # Segments per vent hole
            for v in range(vent_hole_count):
                vent_angle = 2 * math.pi * v / vent_hole_count
                vent_center_x = vent_ring_radius * math.cos(vent_angle)
                vent_center_y = vent_ring_radius * math.sin(vent_angle)
                
                vent_points = []
                for i in range(vent_segments):
                    a = 2 * math.pi * (vent_segments - i) / vent_segments  # Clockwise
                    x = vent_center_x + vent_hole_radius * math.cos(a)
                    y = vent_center_y + vent_hole_radius * math.sin(a)
                    vent_points.append(ifc_file.createIfcCartesianPoint((x, y)))
                vent_points.append(vent_points[0])
                vent_polyline = ifc_file.createIfcPolyline(vent_points)
                vent_voids.append(vent_polyline)
            
            lid_profile = ifc_file.createIfcArbitraryProfileDefWithVoids(
                "AREA", None, outer_polyline, vent_voids
            )
            print(f"[LID]     Created lid profile with {vent_hole_count} vent holes (radius={vent_hole_radius*1000}mm)")
        else:
            # Solid lid (high detail circle)
            lid_profile = create_circular_polygon_profile(ifc_file, lid_radius, NUM_SEGMENTS)
        
        # Lid position: sits on top of frame center (matching Three.js)
        # Three.js: frame (torus) center at height, lid at height + lidThickness/2
        # The torus extends from height - frameThickness/2 to height + frameThickness/2
        # Lid bottom is at height (frame center), lid top at height + lidThickness
        # For IFC: frame extrusion is from 0 to frameThickness, so frame center is at frameThickness/2
        # Lid should start at frameThickness/2 (frame center level)
        lid_z_offset = frame_thickness / 2
        
        lid_extrusion = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0, lid_z_offset)),
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            ifc_file.createIfcDirection((1.0, 0.0, 0.0))
        )
        
        lid_solid = ifc_file.createIfcExtrudedAreaSolid(
            lid_profile,
            lid_extrusion,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            lid_thickness
        )
        solids.append(lid_solid)
        
    else:
        # ===== RECTANGULAR LID - Match Three.js Box Frame =====
        # Three.js: frame is BoxGeometry(frameWidth, frameThickness, frameLength)
        # where frameWidth = lidWidth + frameThickness, frameLength = lidLength + frameThickness
        
        frame_width = lid_width + frame_thickness
        frame_length = lid_length + frame_thickness
        
        # Frame profile (solid rectangle - the frame is a solid box in Three.js)
        frame_profile = ifc_file.createIfcRectangleProfileDef(
            "AREA", None, axis_placement, frame_width, frame_length
        )
        
        # Frame extrusion
        frame_extrusion = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0)),
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            ifc_file.createIfcDirection((1.0, 0.0, 0.0))
        )
        
        frame_solid = ifc_file.createIfcExtrudedAreaSolid(
            frame_profile,
            frame_extrusion,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            frame_thickness
        )
        solids.append(frame_solid)
        
        # ===== RECTANGULAR LID - On top of frame =====
        # Three.js: lid.position.y = height + frameThickness/2 + lidThickness/2
        # So lid sits ON TOP of the frame
        
        # Lid with optional vent holes
        if has_vent_holes and vent_hole_count > 0:
            # Create rectangular lid with circular vent holes
            vent_hole_radius = 0.02  # 20mm radius vent holes (matching Three.js)
            
            # Outer boundary (rectangle)
            half_w = lid_width / 2
            half_l = lid_length / 2
            outer_points = [
                ifc_file.createIfcCartesianPoint((-half_w, -half_l)),
                ifc_file.createIfcCartesianPoint((half_w, -half_l)),
                ifc_file.createIfcCartesianPoint((half_w, half_l)),
                ifc_file.createIfcCartesianPoint((-half_w, half_l)),
                ifc_file.createIfcCartesianPoint((-half_w, -half_l)),  # Close
            ]
            outer_polyline = ifc_file.createIfcPolyline(outer_points)
            
            # Create vent hole voids (arranged in a row along the center)
            vent_voids = []
            vent_segments = 16
            spacing = min(lid_width, lid_length) / (vent_hole_count + 1)
            
            for v in range(vent_hole_count):
                vent_center_x = (v - (vent_hole_count - 1) / 2) * spacing
                vent_center_y = 0.0  # Center row
                
                vent_points = []
                for i in range(vent_segments):
                    a = 2 * math.pi * (vent_segments - i) / vent_segments  # Clockwise
                    x = vent_center_x + vent_hole_radius * math.cos(a)
                    y = vent_center_y + vent_hole_radius * math.sin(a)
                    vent_points.append(ifc_file.createIfcCartesianPoint((x, y)))
                vent_points.append(vent_points[0])
                vent_polyline = ifc_file.createIfcPolyline(vent_points)
                vent_voids.append(vent_polyline)
            
            lid_profile = ifc_file.createIfcArbitraryProfileDefWithVoids(
                "AREA", None, outer_polyline, vent_voids
            )
            print(f"[LID]   Created rectangular lid profile with {vent_hole_count} vent holes")
        else:
            # Solid rectangular lid
            lid_profile = ifc_file.createIfcRectangleProfileDef(
                "AREA", None, axis_placement, lid_width, lid_length
            )
        
        # Lid extrusion placement (on top of frame)
        lid_extrusion = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0, frame_thickness)),
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            ifc_file.createIfcDirection((1.0, 0.0, 0.0))
        )
        
        lid_solid = ifc_file.createIfcExtrudedAreaSolid(
            lid_profile,
            lid_extrusion,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            lid_thickness
        )
        solids.append(lid_solid)
    
    print(f"[LID]   ✅ Created {len(solids)} geometry items (frame + lid) with {NUM_SEGMENTS} segments")
    return solids


def add_chamber_to_ifc(
    ifc_file,
    storey,
    context,
    chamber_data,
    project_coords=None,
    coordinate_mode="absolute",
    origin_tuple=None,
):
    """Add a chamber (manhole) to the IFC file with basic geometry and placement.
    
    ABSOLUTE WORLD COORDINATE MODE:
    Chambers are placed at their absolute real-world coordinates directly.
    This provides maximum compatibility with all IFC import software.
    IfcMapConversion is included as reference information only.
    """

    position = chamber_data.get("position", {})
    width = max(chamber_data.get("width", 1.0), 0.01)
    length = max(chamber_data.get("length", 1.0), 0.01)
    shape = chamber_data.get("shape", "rectangle")
    diameter = chamber_data.get("diameter")
    if diameter is None and shape == "circle":
        diameter = min(width, length)
    if shape == "circle" and diameter:
        width = length = diameter
    cover_level = chamber_data.get("coverLevel", 0.0)
    invert_level = chamber_data.get("invertLevel", 0.0)
    chamber_height = max(cover_level - invert_level, 0.1)
    wall_thickness = chamber_data.get("wallThickness")
    base_thickness = chamber_data.get("baseThickness")
    top_thickness = chamber_data.get("topThickness")
    if base_thickness is None:
        base_thickness = wall_thickness if wall_thickness is not None else 0.0
    if top_thickness is None:
        top_thickness = wall_thickness if wall_thickness is not None else 0.0
    base_thickness = max(float(base_thickness or 0.0), 0.0)
    top_thickness = max(float(top_thickness or 0.0), 0.0)
    wall_thickness = max(float(wall_thickness or 0.0), 0.0)
    
    # ===== CODE VERSION: 2025-11-17 ABSOLUTE COORDINATES =====
    print("[CHAMBER] 🔧 Using ABSOLUTE world coordinate placement")
    
    # Chamber position in world coordinates (from app)
    world_x = position.get("x", 0.0)
    world_z = position.get("z", 0.0)

    # Use the explicit invert elevation supplied by the frontend for placement
    world_invert_y = invert_level

    origin_tuple = origin_tuple or get_project_origin_tuple(project_coords)
    local_x, local_y, local_z = convert_world_to_mode(
        world_x,
        world_invert_y,
        world_z,
        origin_tuple,
        coordinate_mode,
    )
    
    print(f"[CHAMBER] Adding chamber: {chamber_data.get('name', chamber_data.get('id'))}")
    print(f"[CHAMBER]   Absolute world position: x={world_x}, invert_y={world_invert_y}, z={world_z}")
    if shape == "circle":
        print(f"[CHAMBER]   Dimensions: diameter={diameter if diameter else width}m, height={chamber_height}m")
    else:
        print(f"[CHAMBER]   Dimensions: width={width}m, length={length}m, height={chamber_height}m")
    print(f"[CHAMBER]   Wall thickness: {wall_thickness}m, Base thickness: {base_thickness}m, Top thickness: {top_thickness}m")
    print(f"[CHAMBER]   Levels: cover={cover_level}m, invert={invert_level}m")

    chamber = ifc_run(
        "root.create_entity",
        file=ifc_file,
        ifc_class="IfcBuildingElementProxy",
        name=chamber_data.get("name") or chamber_data.get("id"),
        predefined_type="USERDEFINED",
    )

    # Rotation is sent in RADIANS from frontend (stored as radians in Chamber interface)
    rotation_radians = chamber_data.get("rotation", 0.0) or 0.0
    print(f"[CHAMBER]   Rotation: {rotation_radians} radians ({math.degrees(rotation_radians):.2f}°)")

    # Convert Y-up (Three.js) to Z-up (IFC/Revit)
    # Use ABSOLUTE world coordinates directly
    # App: {x: easting, y: elevation at INVERT level, z: northing}
    # IFC: {X: easting, Y: northing, Z: elevation at bottom of geometry}
    # CRITICAL: Chamber geometry origin is at bottom (including base slab)
    invert_elevation = local_y
    bottom_elevation = invert_elevation - base_thickness
    
    # Build matrix with rotation around Z-axis (vertical in IFC Z-up system)
    # Rotation is in the XY plane (horizontal) in IFC coordinates
    chamber_matrix = np.eye(4)
    cos_a = math.cos(rotation_radians)
    sin_a = math.sin(rotation_radians)
    
    # Rotation around Z-axis in IFC coordinates (X-Y plane)
    chamber_matrix[0, 0] = cos_a
    chamber_matrix[0, 1] = -sin_a
    chamber_matrix[1, 0] = sin_a
    chamber_matrix[1, 1] = cos_a
    
    # Translation in IFC Z-up coordinates
    chamber_matrix[0, 3] = local_x           # X coordinate based on selected mode
    chamber_matrix[1, 3] = local_z           # Y coordinate (northing)
    chamber_matrix[2, 3] = bottom_elevation  # Z = absolute elevation at bottom (invert - base)

    
    cover_elevation = invert_elevation + chamber_height

    print(f"[CHAMBER]   Input WORLD (Y-up): x={world_x}, invert_y={world_invert_y}, z={world_z}")
    print(f"[CHAMBER]   Converted ({coordinate_mode}) position: x={local_x}, y={local_y}, z={local_z}")
    print(f"[CHAMBER]   Cover elevation (mode): {cover_elevation}, Invert elevation: {invert_elevation}, Base thickness: {base_thickness}")
    print(f"[CHAMBER]   Output WORLD (Z-up): X={chamber_matrix[0, 3]}, Y={chamber_matrix[1, 3]}, Z={chamber_matrix[2, 3]} (at invert)")
    print(f"[CHAMBER]   ✅ Placement uses {coordinate_mode.upper()} coordinates")

    # CRITICAL: Place chamber with ABSOLUTE coordinates (PlacementRelTo=None)
    # This bypasses any relative coordinate systems and places geometry at exact world position
    # Maximum compatibility with all IFC software
    placement = ifc_run(
        "geometry.edit_object_placement",
        file=ifc_file,
        product=chamber,
        matrix=chamber_matrix,
        is_si=True,
    )
    
    # Set PlacementRelTo=None for absolute world coordinate placement
    # This tells IFC readers to use coordinates as-is without any transformations
    if placement and hasattr(placement, 'PlacementRelTo'):
        placement.PlacementRelTo = None
        print(f"[CHAMBER]   ✅ Placement set to ABSOLUTE (PlacementRelTo=None)")

    # Get lid config for sizing top slab opening
    lid_config = chamber_data.get("lidConfig")
    
    representation = create_chamber_representation(
        ifc_file,
        context,
        width,
        length,
        chamber_height,
        base_thickness,
        top_thickness,
        shape,
        diameter,
        wall_thickness,
        lid_config,
    )
    
    # Assign representation - handle both old-style (from ifc_run) and new-style (shape_rep)
    if hasattr(representation, 'is_a') and representation.is_a('IfcShapeRepresentation'):
        # New style - create product definition shape and assign directly
        product_shape = ifc_file.createIfcProductDefinitionShape(None, None, [representation])
        chamber.Representation = product_shape
    else:
        # Old style - use ifc_run
        ifc_run(
            "geometry.assign_representation",
            file=ifc_file,
            product=chamber,
            representation=representation,
        )

    # Assign to spatial container for IFC hierarchy compliance
    # This maintains the project→site→building→storey→chamber hierarchy
    # but placement remains absolute (not relative to storey)
    ifc_run(
        "spatial.assign_container",
        file=ifc_file,
        products=[chamber],
        relating_structure=storey,
    )
    
    # ===== ADD MATERIAL =====
    chamber_material = chamber_data.get("material", "concrete")
    wall_color_hex = chamber_data.get("wallColor")  # Custom color override
    
    # Default colors matching Three.js hex values:
    # concrete: #888888, brick: #B34D26, plastic: #FFD700 (yellow), composite: #666666, steel: #7A7A80
    material_colors = {
        "concrete": (0.533, 0.533, 0.533),  # #888888 Grey
        "brick": (0.702, 0.302, 0.149),      # #B34D26 Red-brown
        "plastic": (1.0, 0.843, 0.0),        # #FFD700 Yellow (HDPE)
        "composite": (0.4, 0.4, 0.4),        # #666666 Medium grey
        "steel": (0.478, 0.478, 0.502),      # #7A7A80 Steel grey
    }
    
    # Use custom wallColor if provided, otherwise use material default
    if wall_color_hex and wall_color_hex.startswith('#'):
        # Convert hex to RGB (0-1 range)
        hex_color = wall_color_hex.lstrip('#')
        material_color = tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        print(f"[CHAMBER]   Using custom wall color: {wall_color_hex} -> RGB{material_color}")
    else:
        material_color = material_colors.get(chamber_material, (0.533, 0.533, 0.533))
    
    # Create material
    material = ifc_file.createIfcMaterial(chamber_material.title())
    
    # Create surface style with color
    color_rgb = ifc_file.createIfcColourRgb(None, material_color[0], material_color[1], material_color[2])
    surface_style_rendering = ifc_file.createIfcSurfaceStyleRendering(
        color_rgb, 0.0, None, None, None, None, None, None, "FLAT"
    )
    surface_style = ifc_file.createIfcSurfaceStyle(
        chamber_material.title(), "BOTH", [surface_style_rendering]
    )
    styled_item = ifc_file.createIfcStyledItem(None, [surface_style], None)
    style_rep = ifc_file.createIfcStyledRepresentation(
        context, None, None, [styled_item]
    )
    material_def_rep = ifc_file.createIfcMaterialDefinitionRepresentation(
        None, None, [style_rep], material
    )
    
    # Associate material with chamber
    ifc_file.createIfcRelAssociatesMaterial(
        ifcopenshell.guid.new(),
        None,
        f"{chamber_data.get('name', 'Chamber')}_Material",
        None,
        [chamber],
        material
    )
    print(f"[CHAMBER]   ✓ Material: {chamber_material}")
    
    # ===== ADD PROPERTY SETS =====
    # Pset_ManholeChamberCommon - Standard IFC property set
    pset_properties = []
    
    # Reference/Name
    if chamber_data.get("name"):
        pset_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "Reference", None,
                ifc_file.createIfcLabel(chamber_data.get("name")), None
            )
        )
    
    # Invert Level
    pset_properties.append(
        ifc_file.createIfcPropertySingleValue(
            "InvertLevel", None,
            ifc_file.createIfcLengthMeasure(invert_level), None
        )
    )
    
    # Cover Level
    pset_properties.append(
        ifc_file.createIfcPropertySingleValue(
            "CoverLevel", None,
            ifc_file.createIfcLengthMeasure(cover_level), None
        )
    )
    
    # Depth
    pset_properties.append(
        ifc_file.createIfcPropertySingleValue(
            "Depth", None,
            ifc_file.createIfcLengthMeasure(chamber_height), None
        )
    )
    
    # Wall Thickness
    if wall_thickness > 0:
        pset_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "WallThickness", None,
                ifc_file.createIfcLengthMeasure(wall_thickness), None
            )
        )
    
    # Base Thickness
    if base_thickness > 0:
        pset_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "BaseThickness", None,
                ifc_file.createIfcLengthMeasure(base_thickness), None
            )
        )
    
    # Top Thickness
    if top_thickness > 0:
        pset_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "TopThickness", None,
                ifc_file.createIfcLengthMeasure(top_thickness), None
            )
        )
    
    # Shape
    pset_properties.append(
        ifc_file.createIfcPropertySingleValue(
            "Shape", None,
            ifc_file.createIfcLabel(shape.title()), None
        )
    )
    
    # Diameter (for circular)
    if shape == "circle" and diameter:
        pset_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "Diameter", None,
                ifc_file.createIfcLengthMeasure(diameter), None
            )
        )
    else:
        # Width and Length (for rectangular)
        pset_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "Width", None,
                ifc_file.createIfcLengthMeasure(width), None
            )
        )
        pset_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "Length", None,
                ifc_file.createIfcLengthMeasure(length), None
            )
        )
    
    # Create property set
    pset = ifc_file.createIfcPropertySet(
        ifcopenshell.guid.new(),
        None,
        "Pset_ManholeChamberCommon",
        None,
        pset_properties
    )
    
    # Relate property set to chamber
    ifc_file.createIfcRelDefinesByProperties(
        ifcopenshell.guid.new(),
        None,
        None,
        None,
        [chamber],
        pset
    )
    
    # ===== CUSTOM PROPERTY SET - InfraGrid Chamber Properties =====
    custom_properties = []
    
    # Chamber Type
    chamber_type = chamber_data.get("chamberType")
    if chamber_type:
        custom_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "ChamberType", None,
                ifc_file.createIfcLabel(chamber_type), None
            )
        )
    
    # Construction Method
    construction_method = chamber_data.get("constructionMethod")
    if construction_method:
        custom_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "ConstructionMethod", None,
                ifc_file.createIfcLabel(construction_method), None
            )
        )
    
    # Depth Category
    depth_category = chamber_data.get("depthCategory")
    if depth_category:
        custom_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "DepthCategory", None,
                ifc_file.createIfcLabel(depth_category), None
            )
        )
    
    # Load Rating
    load_rating = chamber_data.get("loadRating")
    if load_rating:
        custom_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "LoadRating", None,
                ifc_file.createIfcLabel(load_rating), None
            )
        )
    
    # Load Class (BS EN 124)
    load_class = chamber_data.get("loadClass")
    if load_class:
        custom_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "LoadClass_BS_EN_124", None,
                ifc_file.createIfcLabel(load_class), None
            )
        )
    
    # Entry Type
    entry_type = chamber_data.get("entryType")
    if entry_type:
        custom_properties.append(
            ifc_file.createIfcPropertySingleValue(
                "EntryType", None,
                ifc_file.createIfcLabel(entry_type), None
            )
        )
    
    # Material
    custom_properties.append(
        ifc_file.createIfcPropertySingleValue(
            "Material", None,
            ifc_file.createIfcLabel(chamber_material), None
        )
    )
    
    if custom_properties:
        custom_pset = ifc_file.createIfcPropertySet(
            ifcopenshell.guid.new(),
            None,
            "Pset_InfraGridChamber",
            None,
            custom_properties
        )
        
        ifc_file.createIfcRelDefinesByProperties(
            ifcopenshell.guid.new(),
            None,
            None,
            None,
            [chamber],
            custom_pset
        )
    
    print(f"[CHAMBER]   ✓ Property sets added")

    # Create lid if lid configuration is provided
    lid_config = chamber_data.get("lidConfig")
    lid_element = None
    if lid_config:
        print(f"[CHAMBER] Creating lid for chamber {chamber_data.get('name', chamber_data.get('id'))}")
        
        # Create lid element
        lid_element = ifc_run(
            "root.create_entity",
            file=ifc_file,
            ifc_class="IfcCovering",  # Use IfcCovering for lids/covers
            name=f"{chamber_data.get('name') or chamber_data.get('id')}_Lid",
            predefined_type="USERDEFINED",
        )
        
        # Create lid geometry
        lid_solids = create_lid_representation(
            ifc_file,
            context,
            lid_config,
            shape,
            width,
            length,
            diameter,
        )
        
        if lid_solids:
            # Position lid to match Three.js model
            # Three.js: frame (torus) CENTER is at cover level (height)
            # Frame extends from cover - frameThickness/2 to cover + frameThickness/2
            # Lid bottom is at cover level
            # 
            # IFC geometry (local coords):
            # - Frame: Z=0 to Z=frameThickness
            # - Lid: Z=frameThickness/2 to Z=frameThickness/2 + lidThickness
            #
            # So lid element should be placed at cover - frameThickness/2
            # This way frame center (Z=frameThickness/2) aligns with cover level
            
            lid_frame_thickness = lid_config.get("frameThickness", 75) / 1000  # mm to m
            lid_placement_z = cover_elevation - lid_frame_thickness / 2
            
            lid_matrix = np.eye(4)
            cos_a = math.cos(rotation_radians)
            sin_a = math.sin(rotation_radians)
            
            # Rotation around Z-axis (same as chamber)
            lid_matrix[0, 0] = cos_a
            lid_matrix[0, 1] = -sin_a
            lid_matrix[1, 0] = sin_a
            lid_matrix[1, 1] = cos_a
            
            # Translation - lid element placed so frame center aligns with cover level
            lid_matrix[0, 3] = local_x
            lid_matrix[1, 3] = local_z
            lid_matrix[2, 3] = lid_placement_z
            
            print(f"[LID]   Frame thickness: {lid_frame_thickness}m")
            print(f"[LID]   Position: X={local_x}, Y={local_z}, Z={lid_placement_z} (cover={cover_elevation}, offset={-lid_frame_thickness/2})")
            
            # Set lid placement
            lid_placement = ifc_run(
                "geometry.edit_object_placement",
                file=ifc_file,
                product=lid_element,
                matrix=lid_matrix,
                is_si=True,
            )
            
            if lid_placement and hasattr(lid_placement, 'PlacementRelTo'):
                lid_placement.PlacementRelTo = None
            
            # Create shape representation for lid
            lid_shape_rep = ifc_file.createIfcShapeRepresentation(
                context,
                "Body",
                "SweptSolid",
                lid_solids
            )
            
            lid_product_shape = ifc_file.createIfcProductDefinitionShape(
                None,
                None,
                [lid_shape_rep]
            )
            lid_element.Representation = lid_product_shape
            
            # Assign lid to spatial container
            ifc_run(
                "spatial.assign_container",
                file=ifc_file,
                products=[lid_element],
                relating_structure=storey,
            )
            
            # ===== ADD LID MATERIAL =====
            lid_material_name = lid_config.get("material", "cast-iron")
            lid_material_colors = {
                "cast-iron": (0.2, 0.2, 0.2),    # Dark grey
                "concrete": (0.5, 0.5, 0.5),     # Medium grey
                "composite": (0.3, 0.3, 0.3),   # Dark grey
            }
            lid_color = lid_material_colors.get(lid_material_name, (0.2, 0.2, 0.2))
            
            # Create lid material
            lid_material = ifc_file.createIfcMaterial(f"Lid_{lid_material_name.title()}")
            
            lid_color_rgb = ifc_file.createIfcColourRgb(None, lid_color[0], lid_color[1], lid_color[2])
            lid_surface_rendering = ifc_file.createIfcSurfaceStyleRendering(
                lid_color_rgb, 0.0, None, None, None, None, None, None, "FLAT"
            )
            lid_surface_style = ifc_file.createIfcSurfaceStyle(
                f"Lid_{lid_material_name.title()}", "BOTH", [lid_surface_rendering]
            )
            lid_styled_item = ifc_file.createIfcStyledItem(None, [lid_surface_style], None)
            lid_style_rep = ifc_file.createIfcStyledRepresentation(
                context, None, None, [lid_styled_item]
            )
            lid_material_def_rep = ifc_file.createIfcMaterialDefinitionRepresentation(
                None, None, [lid_style_rep], lid_material
            )
            
            # Associate material with lid
            ifc_file.createIfcRelAssociatesMaterial(
                ifcopenshell.guid.new(),
                None,
                f"{chamber_data.get('name', 'Chamber')}_Lid_Material",
                None,
                [lid_element],
                lid_material
            )
            
            # ===== ADD LID PROPERTY SET =====
            lid_properties = []
            
            # Lid Shape
            lid_shape_val = lid_config.get("shape", "circle")
            lid_properties.append(
                ifc_file.createIfcPropertySingleValue(
                    "Shape", None,
                    ifc_file.createIfcLabel(lid_shape_val.title()), None
                )
            )
            
            # Lid Dimensions
            if lid_shape_val == "circle":
                lid_diameter = lid_config.get("diameter", 600) / 1000  # mm to m
                lid_properties.append(
                    ifc_file.createIfcPropertySingleValue(
                        "Diameter", None,
                        ifc_file.createIfcLengthMeasure(lid_diameter), None
                    )
                )
            else:
                lid_width_val = lid_config.get("width", 600) / 1000
                lid_length_val = lid_config.get("length", 600) / 1000
                lid_properties.append(
                    ifc_file.createIfcPropertySingleValue(
                        "Width", None,
                        ifc_file.createIfcLengthMeasure(lid_width_val), None
                    )
                )
                lid_properties.append(
                    ifc_file.createIfcPropertySingleValue(
                        "Length", None,
                        ifc_file.createIfcLengthMeasure(lid_length_val), None
                    )
                )
            
            # Lid Thickness
            lid_thickness_val = lid_config.get("thickness", 50) / 1000
            lid_properties.append(
                ifc_file.createIfcPropertySingleValue(
                    "Thickness", None,
                    ifc_file.createIfcLengthMeasure(lid_thickness_val), None
                )
            )
            
            # Frame Thickness
            frame_thickness_val = lid_config.get("frameThickness", 75) / 1000
            lid_properties.append(
                ifc_file.createIfcPropertySingleValue(
                    "FrameThickness", None,
                    ifc_file.createIfcLengthMeasure(frame_thickness_val), None
                )
            )
            
            # Material
            lid_properties.append(
                ifc_file.createIfcPropertySingleValue(
                    "Material", None,
                    ifc_file.createIfcLabel(lid_material_name), None
                )
            )
            
            # Vent Holes
            has_vents = lid_config.get("hasVentHoles", False)
            lid_properties.append(
                ifc_file.createIfcPropertySingleValue(
                    "HasVentHoles", None,
                    ifc_file.createIfcBoolean(has_vents), None
                )
            )
            if has_vents:
                vent_count = lid_config.get("ventHoleCount", 0)
                lid_properties.append(
                    ifc_file.createIfcPropertySingleValue(
                        "VentHoleCount", None,
                        ifc_file.createIfcInteger(vent_count), None
                    )
                )
            
            # Create lid property set
            lid_pset = ifc_file.createIfcPropertySet(
                ifcopenshell.guid.new(),
                None,
                "Pset_CoveringCommon",
                None,
                lid_properties
            )
            
            ifc_file.createIfcRelDefinesByProperties(
                ifcopenshell.guid.new(),
                None,
                None,
                None,
                [lid_element],
                lid_pset
            )
            
            print(f"[LID]   ✓ Material: {lid_material_name}")
            print(f"[LID]   ✓ Property set added")
            print(f"[LID]   ✅ Lid created successfully")

    return chamber


def add_pipe_to_ifc(
    ifc_file,
    storey,
    context,
    pipe_data,
    project_coords=None,
    coordinate_mode="absolute",
    origin_tuple=None,
):
    """Add a pipe segment to the IFC file with proper geometry and placement.
    
    Uses multiple IfcExtrudedAreaSolid segments for maximum viewer compatibility.
    Each segment is a cylinder extruded between consecutive path points.
    This approach works reliably in web-ifc and all major IFC viewers.
    """
    
    # Get pipe data
    start_point = pipe_data.get("startPoint", [0, 0, 0])
    end_point = pipe_data.get("endPoint", [0, 0, 0])
    diameter = pipe_data.get("diameter", 100) / 1000  # mm to meters
    radius = diameter / 2
    
    pipe_id = pipe_data.get("pipeId", "Pipe")
    utility_type = pipe_data.get("utilityType", "")
    is_bend = pipe_data.get("isBend", False)
    points = pipe_data.get("points", None)  # Path points for multi-segment pipes
    color_hex = pipe_data.get("color", None)  # Hex color (e.g., "#FF0000")
    
    print(f"\n[PIPE] Adding pipe: {pipe_id}")
    print(f"[PIPE]   Type: {'BEND' if is_bend else 'STRAIGHT'}")
    print(f"[PIPE]   Start (Y-up): {start_point}")
    print(f"[PIPE]   End (Y-up): {end_point}")
    print(f"[PIPE]   Diameter: {diameter}m")
    
    origin_tuple = origin_tuple or get_project_origin_tuple(project_coords)

    # If no points array provided, create one from start/end
    if not points or len(points) < 2:
        points = [start_point, end_point]
    
    # Convert all points using selected coordinate mode
    points_ifc = convert_points_yup_to_ifc(points, origin_tuple, coordinate_mode)
    
    if len(points_ifc) < 2:
        print(f"[PIPE]   ⚠️ Skipping pipe - insufficient points")
        return None
    
    print(f"[PIPE]   Converting {len(points_ifc)} points to extruded segments")
    print(f"[PIPE]   Start (Z-up): {points_ifc[0]}")
    print(f"[PIPE]   End (Z-up): {points_ifc[-1]}")
    
    # Determine predefined type based on utility
    utility_lower = utility_type.lower()
    if "sewer" in utility_lower or "drainage" in utility_lower or "waste" in utility_lower:
        predefined_type = "CULVERT"
    else:
        predefined_type = "RIGIDSEGMENT"
    
    # Create circular profile for extrusion
    circle_profile = ifc_file.createIfcCircleProfileDef(
        "AREA",  # ProfileType
        None,    # ProfileName
        ifc_file.createIfcAxis2Placement2D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0)),
            None
        ),
        radius   # Radius
    )
    
    # Create extruded segments between consecutive points
    extruded_solids = []
    segments_created = 0
    total_length = 0.0
    
    # Calculate overlap to eliminate gaps at bends
    # Overlap by half the radius at each end to ensure segments connect
    overlap = radius * 0.5
    
    for i in range(len(points_ifc) - 1):
        pt1 = points_ifc[i]
        pt2 = points_ifc[i + 1]
        
        # Calculate direction vector
        dx = pt2[0] - pt1[0]
        dy = pt2[1] - pt1[1]
        dz = pt2[2] - pt1[2]
        
        # Calculate segment length
        length = math.sqrt(dx*dx + dy*dy + dz*dz)
        
        if length < 0.001:
            continue  # Skip zero-length segments silently
        
        total_length += length
        
        # Normalize direction
        dir_x = dx / length
        dir_y = dy / length
        dir_z = dz / length
        
        # Extend segment to overlap at joints (except at very start and very end)
        start_extension = overlap if i > 0 else 0
        end_extension = overlap if i < len(points_ifc) - 2 else 0
        extended_length = length + start_extension + end_extension
        
        # Offset start point backwards along direction for overlap
        start_pt = [
            pt1[0] - dir_x * start_extension,
            pt1[1] - dir_y * start_extension,
            pt1[2] - dir_z * start_extension
        ]
        
        # Create axis placement at extended start point
        position = ifc_file.createIfcCartesianPoint(tuple(start_pt))
        
        # Calculate reference direction (perpendicular to extrusion)
        # Use cross product with world Z or Y to get a perpendicular vector
        if abs(dir_z) < 0.9:
            # Use Z-axis for cross product
            ref_x = -dir_y
            ref_y = dir_x
            ref_z = 0.0
        else:
            # Use Y-axis for cross product (when direction is mostly vertical)
            ref_x = dir_z
            ref_y = 0.0
            ref_z = -dir_x
        
        # Normalize reference direction
        ref_len = math.sqrt(ref_x*ref_x + ref_y*ref_y + ref_z*ref_z)
        if ref_len > 0.001:
            ref_x /= ref_len
            ref_y /= ref_len
            ref_z /= ref_len
        else:
            ref_x, ref_y, ref_z = 1.0, 0.0, 0.0
        
        # Create axis placement with extrusion direction as Z-axis
        axis_direction = ifc_file.createIfcDirection((dir_x, dir_y, dir_z))
        ref_direction = ifc_file.createIfcDirection((ref_x, ref_y, ref_z))
        
        axis_placement = ifc_file.createIfcAxis2Placement3D(
            position,
            axis_direction,  # Z-axis (extrusion direction)
            ref_direction    # X-axis (reference direction)
        )
        
        # Create extruded area solid with extended length to close gaps at bends
        extruded_solid = ifc_file.createIfcExtrudedAreaSolid(
            circle_profile,
            axis_placement,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),  # Extrude along local Z
            extended_length
        )
        
        extruded_solids.append(extruded_solid)
        segments_created += 1
    
    if not extruded_solids:
        print(f"[PIPE]   ⚠️ No valid segments created")
        return None
    
    print(f"[PIPE]   ✅ Created {segments_created} extruded segments, total length: {total_length:.3f}m")
    
    # Create pipe segment entity
    pipe = ifc_run(
        "root.create_entity",
        file=ifc_file,
        ifc_class="IfcPipeSegment",
        name=pipe_id,
        predefined_type=predefined_type,
    )
    
    # Set placement at origin (geometry is in absolute coordinates)
    placement_point = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
    z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
    x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    placement = ifc_file.createIfcLocalPlacement(
        None,
        ifc_file.createIfcAxis2Placement3D(placement_point, z_dir, x_dir)
    )
    pipe.ObjectPlacement = placement
    
    # Create shape representation with all extruded solids
    shape_rep = ifc_file.createIfcShapeRepresentation(
        context,
        "Body",
        "SweptSolid",
        extruded_solids  # All segments as separate solids
    )
    
    # Create product definition shape
    product_shape = ifc_file.createIfcProductDefinitionShape(
        None,
        None,
        [shape_rep]
    )
    
    # Assign representation to pipe
    pipe.Representation = product_shape
    
    # Assign to spatial container
    ifc_run(
        "spatial.assign_container",
        file=ifc_file,
        products=[pipe],
        relating_structure=storey,
    )
    
    # Apply color if provided
    if color_hex:
        apply_color_to_element(ifc_file, pipe, color_hex)
    
    print(f"[PIPE]   ✅ Pipe created successfully")
    
    return pipe


def add_road_to_ifc(
    ifc_file,
    storey,
    context,
    road_data,
    project_coords=None,
    coordinate_mode="absolute",
    origin_tuple=None,
):
    """Add a road to the IFC file with all its components (carriageway, kerbs, footpaths, etc.).
    
    Roads are exported as triangulated meshes (IfcTriangulatedFaceSet) for the carriageway surface,
    and swept solids for kerbs, bedding, haunch, and footpaths.
    
    Expected road_data structure:
    {
        "roadId": "road_1",
        "name": "Main Street",
        "components": [
            {
                "type": "carriageway",  # or "kerb", "footway", "bedding", "haunch"
                "side": "left" | "right" | null,
                "vertices": [[x, y, z], ...],  # Triangle mesh vertices (Y-up)
                "indices": [0, 1, 2, ...],     # Triangle indices
                "color": "#333333"
            },
            {
                "type": "kerb",
                "side": "left",
                "centerline": [[x, y, z], ...],  # Path along kerb
                "profile": {...},  # Cross-section profile
                "color": "#888888"
            },
            ...
        ],
        "centerline": [[x, y, z], ...],  # Road centerline points (Y-up)
        "crossSection": {...}  # Cross-section configuration
    }
    """
    road_id = road_data.get("roadId", "Road")
    road_name = road_data.get("name", road_id)
    components = road_data.get("components", [])
    
    print(f"\n[ROAD] Adding road: {road_name}")
    print(f"[ROAD]   Components: {len(components)}")
    
    # Log all component types for debugging
    component_types = [comp.get("type", "unknown") for comp in components]
    type_counts = {}
    for ct in component_types:
        type_counts[ct] = type_counts.get(ct, 0) + 1
    print(f"[ROAD]   Component type breakdown: {type_counts}")
    
    origin_tuple = origin_tuple or get_project_origin_tuple(project_coords)
    
    created_elements = []
    
    for comp_idx, component in enumerate(components):
        comp_type = component.get("type", "unknown")
        comp_side = component.get("side")
        color_hex = component.get("color")
        vertices = component.get("vertices", [])
        indices = component.get("indices", [])
        
        element_name = f"{road_name}_{comp_type}"
        if comp_side:
            element_name += f"_{comp_side}"
        
        print(f"[ROAD]   Component {comp_idx + 1}: {comp_type} ({comp_side or 'center'}) - {len(vertices)} vertices, {len(indices)} indices")
        
        if comp_type == "carriageway":
            # Carriageway is a triangulated mesh
            element = create_road_mesh_element(
                ifc_file, storey, context,
                element_name, component,
                origin_tuple, coordinate_mode, color_hex
            )
            if element:
                created_elements.append(element)
                
        elif comp_type in ("kerb", "footway", "bedding", "haunch"):
            # These are swept solids along a path
            element = create_road_swept_element(
                ifc_file, storey, context,
                element_name, component, comp_type,
                origin_tuple, coordinate_mode, color_hex
            )
            if element:
                created_elements.append(element)
                
        elif comp_type in ("footpath", "verge", "swale", "ditch", "wall", "fence", "hedge", "custom"):
            # Offset features are exported as triangulated meshes (like carriageway)
            # They preserve exact geometry including crossfalls, profiles, and layers
            vertices = component.get("vertices", [])
            indices = component.get("indices", [])
            print(f"[ROAD]   Processing {comp_type}: {len(vertices)} vertices, {len(indices) // 3 if indices else 0} triangles")
            
            if len(vertices) < 3 or len(indices) < 3:
                print(f"[ROAD]   ⚠️ {comp_type} has insufficient geometry: {len(vertices)} vertices, {len(indices)} indices")
            else:
                element = create_road_mesh_element(
                    ifc_file, storey, context,
                    element_name, component,
                    origin_tuple, coordinate_mode, color_hex,
                    comp_type  # Pass component type for appropriate IFC class
                )
                if element:
                    created_elements.append(element)
                    print(f"[ROAD]   ✅ Created {comp_type} element: {element_name}")
                else:
                    print(f"[ROAD]   ⚠️ Failed to create {comp_type} element: {element_name}")
        else:
            print(f"[ROAD]   ⚠️ Unknown component type: {comp_type}")
    
    print(f"[ROAD]   ✅ Road created with {len(created_elements)} elements")
    
    return created_elements


def create_road_mesh_element(
    ifc_file, storey, context,
    element_name, component,
    origin_tuple, coordinate_mode, color_hex,
    comp_type="carriageway"
):
    """Create a triangulated mesh element for road components.
    
    Uses IfcTriangulatedFaceSet for accurate mesh representation.
    
    Args:
        comp_type: Component type ('carriageway', 'footpath', 'verge', 'swale', 'ditch', 'wall', 'fence', 'hedge', 'custom')
    """
    vertices = component.get("vertices", [])
    indices = component.get("indices", [])
    
    print(f"[ROAD]     create_road_mesh_element called for {comp_type}: {len(vertices)} vertices, {len(indices)} indices")
    
    if len(vertices) < 3 or len(indices) < 3:
        print(f"[ROAD]     ⚠️ Insufficient geometry for {element_name}: {len(vertices)} vertices, {len(indices)} indices")
        return None
    
    print(f"[ROAD]     Creating mesh: {len(vertices)} vertices, {len(indices) // 3} triangles, type={comp_type}")
    
    # Convert vertices from Y-up to Z-up (IFC coordinate system)
    ifc_vertices = []
    coord_bounds = {"x": [], "y": [], "z": []}
    for v in vertices:
        # Convert using coordinate mode
        local_x, local_y, local_z = convert_world_to_mode(
            float(v[0]), float(v[1]), float(v[2]),
            origin_tuple, coordinate_mode
        )
        coord_bounds["x"].append(local_x)
        coord_bounds["y"].append(local_y)
        coord_bounds["z"].append(local_z)
        # Y-up to Z-up: [x, z, y] in IFC
        ifc_vertices.append((local_x, local_z, local_y))
    
    # Log coordinate bounds for debugging
    if len(coord_bounds["x"]) > 0:
        print(f"[ROAD]     {comp_type} coordinate bounds (after conversion):")
        print(f"[ROAD]       X: [{min(coord_bounds['x']):.2f}, {max(coord_bounds['x']):.2f}]")
        print(f"[ROAD]       Y: [{min(coord_bounds['y']):.2f}, {max(coord_bounds['y']):.2f}]")
        print(f"[ROAD]       Z: [{min(coord_bounds['z']):.2f}, {max(coord_bounds['z']):.2f}]")
        print(f"[ROAD]       First vertex (IFC): [{ifc_vertices[0][0]:.2f}, {ifc_vertices[0][1]:.2f}, {ifc_vertices[0][2]:.2f}]")
    
    # Create IFC cartesian point list
    coord_list = ifc_file.createIfcCartesianPointList3D(ifc_vertices)
    
    # Create triangle indices (IFC uses 1-based indexing)
    # Group indices into triangles
    triangles = []
    for i in range(0, len(indices), 3):
        if i + 2 < len(indices):
            # IFC uses 1-based indexing
            triangles.append((indices[i] + 1, indices[i + 1] + 1, indices[i + 2] + 1))
    
    # Create triangulated face set
    face_set = ifc_file.createIfcTriangulatedFaceSet(
        coord_list,  # Coordinates
        None,        # Normals (optional)
        None,        # Closed (optional)
        triangles,   # CoordIndex
        None         # PnIndex (optional)
    )
    
    # Create shape representation
    shape_rep = ifc_file.createIfcShapeRepresentation(
        context,
        "Body",
        "Tessellation",
        [face_set]
    )
    
    # Create product definition shape
    product_shape = ifc_file.createIfcProductDefinitionShape(None, None, [shape_rep])
    
    # Determine appropriate IFC class based on component type
    # Use IfcSlab with PAVING for all surface features to ensure visibility in IFC viewers
    # This matches footpath which is working correctly
    if comp_type == "carriageway":
        ifc_class = "IfcSlab"
        predefined_type = "PAVING"
    elif comp_type in ("footpath", "verge", "swale", "ditch"):
        # All surface features use IfcSlab with PAVING for consistent visibility
        ifc_class = "IfcSlab"
        predefined_type = "PAVING"
    elif comp_type == "wall":
        ifc_class = "IfcWall"
        predefined_type = "USERDEFINED"
    elif comp_type in ("fence", "hedge", "custom"):
        # Use IfcSlab for fence/hedge too to ensure visibility (they're surface features)
        # IfcBuildingElementProxy might not render in some viewers
        ifc_class = "IfcSlab"
        predefined_type = "PAVING"
    else:
        # Default fallback
        ifc_class = "IfcSlab"
        predefined_type = "PAVING"
    
    # Create the element
    try:
        print(f"[ROAD]     Creating IFC element: class={ifc_class}, predefined_type={predefined_type}, name={element_name}")
        road_element = ifc_run(
            "root.create_entity",
            file=ifc_file,
            ifc_class=ifc_class,
            name=element_name,
            predefined_type=predefined_type,
        )
        print(f"[ROAD]     ✅ Created IFC element: {road_element}")
    except Exception as e:
        print(f"[ROAD]     ❌ ERROR creating IFC element: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # Set placement at origin (geometry is in absolute coordinates)
    try:
        placement_point = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
        z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
        x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
        placement = ifc_file.createIfcLocalPlacement(
            None,
            ifc_file.createIfcAxis2Placement3D(placement_point, z_dir, x_dir)
        )
        road_element.ObjectPlacement = placement
        road_element.Representation = product_shape
        print(f"[ROAD]     ✅ Set placement and representation")
    except Exception as e:
        print(f"[ROAD]     ❌ ERROR setting placement: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # Assign to spatial container
    try:
        ifc_run(
            "spatial.assign_container",
            file=ifc_file,
            products=[road_element],
            relating_structure=storey,
        )
        print(f"[ROAD]     ✅ Assigned to storey")
    except Exception as e:
        print(f"[ROAD]     ❌ ERROR assigning to storey: {e}")
        import traceback
        traceback.print_exc()
        # Don't return None here - element is still valid even if container assignment fails
    
    # Apply color if provided
    if color_hex:
        try:
            apply_color_to_element(ifc_file, road_element, color_hex)
            print(f"[ROAD]     ✅ Applied color: {color_hex}")
        except Exception as e:
            print(f"[ROAD]     ⚠️ WARNING: Could not apply color: {e}")
    
    print(f"[ROAD]     ✅ Successfully created {comp_type} element: {element_name}")
    return road_element


def create_road_swept_element(
    ifc_file, storey, context,
    element_name, component, comp_type,
    origin_tuple, coordinate_mode, color_hex
):
    """Create a swept solid element for kerbs, footways, bedding, haunch.
    
    Uses extruded segments similar to pipe export for maximum compatibility.
    """
    centerline = component.get("centerline", [])
    profile = component.get("profile", {})
    
    if len(centerline) < 2:
        print(f"[ROAD]     ⚠️ Insufficient centerline points for {element_name}")
        return None
    
    # Convert centerline points to IFC coordinates
    points_ifc = convert_points_yup_to_ifc(centerline, origin_tuple, coordinate_mode)
    
    print(f"[ROAD]     Creating swept solid: {len(points_ifc)} path points")
    
    # Determine profile based on component type
    if comp_type == "kerb":
        # Kerb profile - trapezoidal shape
        kerb_height = profile.get("height", 125) / 1000  # mm to m
        kerb_width = profile.get("width", 125) / 1000
        batter_width = profile.get("batterWidth", 20) / 1000
        
        # Create kerb profile (simplified trapezoid)
        # Profile points in local 2D (perpendicular to path)
        half_width = kerb_width / 2
        profile_points = [
            (-half_width, 0.0),
            (-half_width + batter_width, kerb_height),
            (half_width - batter_width, kerb_height),
            (half_width, 0.0),
            (-half_width, 0.0),  # Close
        ]
        
        ifc_profile_points = [ifc_file.createIfcCartesianPoint(pt) for pt in profile_points]
        polyline = ifc_file.createIfcPolyline(ifc_profile_points)
        profile_def = ifc_file.createIfcArbitraryClosedProfileDef("AREA", None, polyline)
        
    elif comp_type == "footway":
        # Footway - rectangular slab
        footway_width = profile.get("width", 2000) / 1000  # mm to m
        footway_thickness = profile.get("thickness", 50) / 1000
        
        axis_placement = ifc_file.createIfcAxis2Placement2D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0)),
            ifc_file.createIfcDirection((1.0, 0.0)),
        )
        profile_def = ifc_file.createIfcRectangleProfileDef(
            "AREA", None, axis_placement, footway_width, footway_thickness
        )
        
    elif comp_type == "bedding":
        # Bedding - rectangular below kerb
        bedding_width = profile.get("width", 275) / 1000  # kerb + haunch width
        bedding_thickness = profile.get("thickness", 100) / 1000
        
        axis_placement = ifc_file.createIfcAxis2Placement2D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0)),
            ifc_file.createIfcDirection((1.0, 0.0)),
        )
        profile_def = ifc_file.createIfcRectangleProfileDef(
            "AREA", None, axis_placement, bedding_width, bedding_thickness
        )
        
    elif comp_type == "haunch":
        # Haunch - trapezoid behind kerb
        haunch_bottom_width = profile.get("bottomWidth", 150) / 1000
        haunch_top_width = profile.get("topWidth", 100) / 1000
        haunch_height = profile.get("height", 125) / 1000
        
        # Trapezoid profile
        profile_points = [
            (-haunch_bottom_width / 2, 0.0),
            (-haunch_top_width / 2, haunch_height),
            (haunch_top_width / 2, haunch_height),
            (haunch_bottom_width / 2, 0.0),
            (-haunch_bottom_width / 2, 0.0),  # Close
        ]
        
        ifc_profile_points = [ifc_file.createIfcCartesianPoint(pt) for pt in profile_points]
        polyline = ifc_file.createIfcPolyline(ifc_profile_points)
        profile_def = ifc_file.createIfcArbitraryClosedProfileDef("AREA", None, polyline)
    else:
        print(f"[ROAD]     ⚠️ Unknown swept component type: {comp_type}")
        return None
    
    # Create extruded segments between consecutive points (same approach as pipes)
    extruded_solids = []
    
    for i in range(len(points_ifc) - 1):
        pt1 = points_ifc[i]
        pt2 = points_ifc[i + 1]
        
        # Calculate direction vector
        dx = pt2[0] - pt1[0]
        dy = pt2[1] - pt1[1]
        dz = pt2[2] - pt1[2]
        
        # Calculate segment length
        length = math.sqrt(dx*dx + dy*dy + dz*dz)
        
        if length < 0.001:
            continue
        
        # Normalize direction
        dir_x = dx / length
        dir_y = dy / length
        dir_z = dz / length
        
        # Create axis placement at start point
        position = ifc_file.createIfcCartesianPoint(tuple(pt1))
        
        # Calculate reference direction (perpendicular to extrusion)
        if abs(dir_z) < 0.9:
            ref_x = -dir_y
            ref_y = dir_x
            ref_z = 0.0
        else:
            ref_x = dir_z
            ref_y = 0.0
            ref_z = -dir_x
        
        ref_len = math.sqrt(ref_x*ref_x + ref_y*ref_y + ref_z*ref_z)
        if ref_len > 0.001:
            ref_x /= ref_len
            ref_y /= ref_len
            ref_z /= ref_len
        else:
            ref_x, ref_y, ref_z = 1.0, 0.0, 0.0
        
        axis_direction = ifc_file.createIfcDirection((dir_x, dir_y, dir_z))
        ref_direction = ifc_file.createIfcDirection((ref_x, ref_y, ref_z))
        
        axis_placement = ifc_file.createIfcAxis2Placement3D(
            position,
            axis_direction,
            ref_direction
        )
        
        extruded_solid = ifc_file.createIfcExtrudedAreaSolid(
            profile_def,
            axis_placement,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            length
        )
        
        extruded_solids.append(extruded_solid)
    
    if not extruded_solids:
        print(f"[ROAD]     ⚠️ No valid segments created for {element_name}")
        return None
    
    # Create shape representation
    shape_rep = ifc_file.createIfcShapeRepresentation(
        context,
        "Body",
        "SweptSolid",
        extruded_solids
    )
    
    product_shape = ifc_file.createIfcProductDefinitionShape(None, None, [shape_rep])
    
    # Determine IFC class based on component type
    if comp_type == "kerb":
        ifc_class = "IfcCurbType" if hasattr(ifcopenshell, 'IfcCurbType') else "IfcBuildingElementProxy"
        predefined_type = "USERDEFINED"
    elif comp_type == "footway":
        ifc_class = "IfcSlab"
        predefined_type = "PAVING"
    elif comp_type in ("bedding", "haunch"):
        ifc_class = "IfcBuildingElementProxy"
        predefined_type = "USERDEFINED"
    else:
        ifc_class = "IfcBuildingElementProxy"
        predefined_type = "USERDEFINED"
    
    # Create element
    element = ifc_run(
        "root.create_entity",
        file=ifc_file,
        ifc_class=ifc_class,
        name=element_name,
        predefined_type=predefined_type,
    )
    
    # Set placement at origin
    placement_point = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
    z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
    x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    placement = ifc_file.createIfcLocalPlacement(
        None,
        ifc_file.createIfcAxis2Placement3D(placement_point, z_dir, x_dir)
    )
    element.ObjectPlacement = placement
    element.Representation = product_shape
    
    # Assign to spatial container
    ifc_run(
        "spatial.assign_container",
        file=ifc_file,
        products=[element],
        relating_structure=storey,
    )
    
    # Apply color
    if color_hex:
        apply_color_to_element(ifc_file, element, color_hex)
    
    print(f"[ROAD]     ✅ Created {comp_type} with {len(extruded_solids)} segments")
    
    return element


def add_cable_tray_to_ifc(
    ifc_file,
    storey,
    context,
    tray_data,
    project_coords=None,
    coordinate_mode="absolute",
    origin_tuple=None,
):
    """
    Add cable tray to IFC using swept solid (similar to pipes but with rectangular U-channel profile).
    """
    # Get tray data
    start_point = tray_data.get("startPoint", [0, 0, 0])
    end_point = tray_data.get("endPoint", [0, 0, 0])
    width = tray_data.get("width", 300) / 1000  # mm to meters
    height = tray_data.get("height", 50) / 1000  # mm to meters
    wall_thickness = tray_data.get("wallThickness", 1.5) / 1000  # mm to meters
    bottom_thickness = tray_data.get("bottomThickness", 1.5) / 1000  # mm to meters
    
    tray_id = tray_data.get("trayId", "CableTray")
    utility_type = tray_data.get("utilityType", "")
    is_bend = tray_data.get("isBend", False)
    points = tray_data.get("points", None)
    color_hex = tray_data.get("color", None)
    
    print(f"\n[CABLE TRAY] Adding: {tray_id}")
    print(f"[CABLE TRAY]   Type: {'BEND' if is_bend else 'STRAIGHT'}")
    print(f"[CABLE TRAY]   Width: {width}m, Height: {height}m")
    
    origin_tuple = origin_tuple or get_project_origin_tuple(project_coords)

    # Convert positions using selected mode
    start_ifc = convert_point_yup_to_ifc(start_point, origin_tuple, coordinate_mode)
    end_ifc = convert_point_yup_to_ifc(end_point, origin_tuple, coordinate_mode)
    
    # Create cable tray element
    tray = ifc_run(
        "root.create_entity",
        file=ifc_file,
        ifc_class="IfcCableCarrierSegment",  # Proper IFC class for cable trays
        name=tray_id,
        predefined_type="CABLETRAY",
    )
    
    # Use composite curve approach for U-shaped cable tray (similar to pipe but with 3 parallel "pipes")
    # Create three swept disk solids: bottom + two sides
    if points and len(points) >= 2:
        print(f"[CABLE TRAY]   Creating U-SHAPED SWEPT SOLID with {len(points)} points")
        
        # Convert points to IFC coordinates
        points_ifc = convert_points_yup_to_ifc(points, origin_tuple, coordinate_mode)
        
        # Create polyline curve (centerline of tray)
        # IMPORTANT: IfcCartesianPoint requires tuples, not lists
        ifc_points = [ifc_file.createIfcCartesianPoint(tuple(pt)) for pt in points_ifc]
        polyline = ifc_file.createIfcPolyline(ifc_points)
        
        # For U-channel, create 3 swept disk solids and combine them
        # Bottom: full width
        # Left wall: vertical
        # Right wall: vertical
        
        solids = []
        half_width = width / 2
        
        # 1. Bottom plate (horizontal)
        bottom_points = []
        for pt in points_ifc:
            # Bottom stays at same elevation
            bottom_points.append([pt[0], pt[1], pt[2]])
        
        bottom_ifc_points = [ifc_file.createIfcCartesianPoint(tuple(pt)) for pt in bottom_points]
        bottom_polyline = ifc_file.createIfcPolyline(bottom_ifc_points)
        bottom_solid = ifc_file.createIfcSweptDiskSolid(
            bottom_polyline,
            width,  # Radius (actually width for flat bottom)
            None,
            None,
            None
        )
        solids.append(bottom_solid)
        
        # 2. Left side wall (offset -half_width in X direction)
        left_points = []
        for pt in points_ifc:
            left_points.append([pt[0] - half_width, pt[1], pt[2]])
        
        left_ifc_points = [ifc_file.createIfcCartesianPoint(tuple(pt)) for pt in left_points]
        left_polyline = ifc_file.createIfcPolyline(left_ifc_points)
        left_solid = ifc_file.createIfcSweptDiskSolid(
            left_polyline,
            wall_thickness / 2,  # Radius
            None,
            None,
            None
        )
        solids.append(left_solid)
        
        # 3. Right side wall (offset +half_width in X direction)
        right_points = []
        for pt in points_ifc:
            right_points.append([pt[0] + half_width, pt[1], pt[2]])
        
        right_ifc_points = [ifc_file.createIfcCartesianPoint(tuple(pt)) for pt in right_points]
        right_polyline = ifc_file.createIfcPolyline(right_ifc_points)
        right_solid = ifc_file.createIfcSweptDiskSolid(
            right_polyline,
            wall_thickness / 2,  # Radius
            None,
            None,
            None
        )
        solids.append(right_solid)
        
        # Combine all three solids using Boolean union
        # Start with bottom
        solid = solids[0]
        
        # Note: For simplicity, just use the first solid (bottom plate) for now
        # Full U-channel would require Boolean operations which are complex
        # This will at least show SOMETHING in the viewer
        
        print(f"[CABLE TRAY]   ✅ Creating simplified swept disk solid")
        # Use a thick swept disk to represent the cable tray
        # Use larger of width or height for visibility
        tray_radius = max(width, height) / 3  # Make it substantial but not too large
        solid = ifc_file.createIfcSweptDiskSolid(
            polyline,
            tray_radius,  # Radius for visibility
            None,
            None,
            None
        )
        print(f"[CABLE TRAY]   Tray dimensions: width={width}m, height={height}m")
        print(f"[CABLE TRAY]   Using radius: {tray_radius}m for swept disk")
        print(f"[CABLE TRAY]   Path has {len(points_ifc)} points")
    
    # Set placement at origin (geometry already in target coordinate space)
    origin_point = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
    z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
    x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    placement = ifc_file.createIfcLocalPlacement(
        None,
        ifc_file.createIfcAxis2Placement3D(origin_point, z_dir, x_dir)
    )
    tray.ObjectPlacement = placement
    
    # Create shape representation
    shape_representation = ifc_file.createIfcShapeRepresentation(
        context,
        "Body",
        "SweptSolid",
        [solid]
    )
    
    product_shape = ifc_file.createIfcProductDefinitionShape(
        None,
        None,
        [shape_representation]
    )
    tray.Representation = product_shape
    
    print(f"[CABLE TRAY]   ✅ Geometry created")
    
    # Assign to spatial container
    ifc_run(
        "spatial.assign_container",
        file=ifc_file,
        products=[tray],
        relating_structure=storey,
    )
    
    # Apply color
    if color_hex:
        apply_color_to_element(ifc_file, tray, color_hex)
    
    print(f"[CABLE TRAY]   ✅ Created successfully")
    return tray


def add_hanger_to_ifc(
    ifc_file,
    storey,
    context,
    hanger_data,
    project_coords=None,
    coordinate_mode="absolute",
    origin_tuple=None,
):
    """
    Add cable tray hanger to IFC - using rotation matrix like chambers.
    Creates crossbar perpendicular to path direction with vertical support rods.
    """
    position = hanger_data.get("position", [0, 0, 0])
    height = hanger_data.get("height", 500) / 1000  # mm to meters
    rod_diameter = hanger_data.get("rodDiameter", 12) / 1000  # mm to meters
    tray_width = hanger_data.get("trayWidth", 300) / 1000  # mm to meters
    crossbar_width = hanger_data.get("crossbarWidth", 41) / 1000  # mm to meters
    crossbar_depth = hanger_data.get("crossbarDepth", 41) / 1000  # mm to meters
    hanger_id = hanger_data.get("hangerId", "Hanger")
    color_hex = hanger_data.get("color", "#888888")
    
    # Rotation in radians (around vertical axis)
    rotation_radians = hanger_data.get("rotation", 0.0) or 0.0
    direction = hanger_data.get("direction", [1, 0, 0])  # Tangent direction
    
    print(f"\n[HANGER] Adding: {hanger_id}")
    print(f"[HANGER]   Position (Y-up): {position}")
    print(f"[HANGER]   Height: {height}m ({height*1000}mm)")
    print(f"[HANGER]   Rod diameter: {rod_diameter}m ({rod_diameter*1000}mm)")
    print(f"[HANGER]   Tray width: {tray_width}m ({tray_width*1000}mm)")
    print(f"[HANGER]   Crossbar width: {crossbar_width}m ({crossbar_width*1000}mm)")
    print(f"[HANGER]   Crossbar depth: {crossbar_depth}m ({crossbar_depth*1000}mm)")
    print(f"[HANGER]   Rotation: {rotation_radians} radians ({math.degrees(rotation_radians):.2f}°)")
    print(f"[HANGER]   Direction: {direction}")
    
    origin_tuple = origin_tuple or get_project_origin_tuple(project_coords)
    pos_ifc = convert_point_yup_to_ifc(position, origin_tuple, coordinate_mode)
    dir_ifc = convert_direction_yup_to_ifc(direction)
    
    # Create hanger element
    hanger = ifc_run(
        "root.create_entity",
        file=ifc_file,
        ifc_class="IfcMechanicalFastener",
        name=hanger_id,
        predefined_type="USERDEFINED",
    )
    
    # Build transformation matrix with rotation (like chambers)
    # Crossbar is perpendicular to path direction, so rotate by 90 degrees + path rotation
    hanger_matrix = np.eye(4)
    
    # Apply rotation around Z-axis (vertical in IFC)
    # Crossbar should be perpendicular to path, so add 90 degrees
    crossbar_rotation = rotation_radians + math.pi / 2
    cos_a = math.cos(crossbar_rotation)
    sin_a = math.sin(crossbar_rotation)
    
    # Rotation around Z-axis in IFC coordinates (X-Y plane)
    hanger_matrix[0, 0] = cos_a
    hanger_matrix[0, 1] = -sin_a
    hanger_matrix[1, 0] = sin_a
    hanger_matrix[1, 1] = cos_a
    
    # Translation at tray position + height (crossbar at top)
    hanger_matrix[0, 3] = pos_ifc[0]  # X
    hanger_matrix[1, 3] = pos_ifc[1]  # Y
    hanger_matrix[2, 3] = pos_ifc[2] + height  # Z (at ceiling)
    
    print(f"[HANGER]   Crossbar rotation: {math.degrees(crossbar_rotation):.2f}° (perpendicular to path)")
    print(f"[HANGER]   Position (IFC Z-up, {coordinate_mode}): X={pos_ifc[0]:.2f}, Y={pos_ifc[1]:.2f}, Z={pos_ifc[2]:.2f}")
    
    # Set placement using matrix
    placement = ifc_run(
        "geometry.edit_object_placement",
        file=ifc_file,
        product=hanger,
        matrix=hanger_matrix,
        is_si=True,
    )
    
    # Set PlacementRelTo=None for absolute coordinates
    if placement and hasattr(placement, 'PlacementRelTo'):
        placement.PlacementRelTo = None
    
    # Create hanger geometry: crossbar + two vertical rods + bottom support
    # All in LOCAL coordinates (will be transformed by matrix)
    # Matrix origin is at CEILING level (pos_ifc[2] + height)
    solids = []
    half_width = tray_width / 2
    rod_radius = rod_diameter / 2
    half_crossbar = crossbar_width / 2  # For centering bars
    
    print(f"[HANGER]   Creating geometry with:")
    print(f"[HANGER]     Tray width: {tray_width*1000:.1f}mm, Half: {half_width*1000:.1f}mm")
    print(f"[HANGER]     Crossbar: {crossbar_width*1000:.1f}mm x {crossbar_depth*1000:.1f}mm")
    print(f"[HANGER]     Rod diameter: {rod_diameter*1000:.1f}mm, Radius: {rod_radius*1000:.1f}mm")
    
    # 1. Top crossbar (horizontal at ceiling, centered vertically)
    # Position so it's centered at Z=0 (ceiling level in local coords)
    crossbar_profile_placement = ifc_file.createIfcAxis2Placement2D(
        ifc_file.createIfcCartesianPoint((0.0, 0.0)),
        ifc_file.createIfcDirection((1.0, 0.0))
    )
    crossbar_profile = ifc_file.createIfcRectangleProfileDef(
        "AREA",
        None,
        crossbar_profile_placement,
        tray_width,  # XDim - exact tray width (not extended)
        crossbar_depth  # YDim
    )
    # Center the crossbar vertically at ceiling
    crossbar_extrusion = ifc_file.createIfcAxis2Placement3D(
        ifc_file.createIfcCartesianPoint((0.0, 0.0, -half_crossbar)),  # Start half below ceiling
        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
        ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    )
    crossbar_solid = ifc_file.createIfcExtrudedAreaSolid(
        crossbar_profile,
        crossbar_extrusion,
        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
        crossbar_width  # Extrude upward by full width (centered at 0)
    )
    solids.append(crossbar_solid)
    
    # 2. Left vertical rod (from bottom of top crossbar to top of bottom bar)
    left_rod_points = [
        ifc_file.createIfcCartesianPoint((-half_width, 0.0, -half_crossbar)),  # Bottom of top crossbar
        ifc_file.createIfcCartesianPoint((-half_width, 0.0, -height + half_crossbar))  # Top of bottom bar
    ]
    left_rod_polyline = ifc_file.createIfcPolyline(left_rod_points)
    left_rod_solid = ifc_file.createIfcSweptDiskSolid(left_rod_polyline, rod_radius, None, None, None)
    solids.append(left_rod_solid)
    
    # 3. Right vertical rod
    right_rod_points = [
        ifc_file.createIfcCartesianPoint((half_width, 0.0, -half_crossbar)),  # Bottom of top crossbar
        ifc_file.createIfcCartesianPoint((half_width, 0.0, -height + half_crossbar))  # Top of bottom bar
    ]
    right_rod_polyline = ifc_file.createIfcPolyline(right_rod_points)
    right_rod_solid = ifc_file.createIfcSweptDiskSolid(right_rod_polyline, rod_radius, None, None, None)
    solids.append(right_rod_solid)
    
    # 4. Bottom support bar (at tray level, centered vertically)
    bottom_bar_profile_placement = ifc_file.createIfcAxis2Placement2D(
        ifc_file.createIfcCartesianPoint((0.0, 0.0)),
        ifc_file.createIfcDirection((1.0, 0.0))
    )
    bottom_bar_profile = ifc_file.createIfcRectangleProfileDef(
        "AREA",
        None,
        bottom_bar_profile_placement,
        tray_width,  # XDim - exact tray width (matches top crossbar)
        crossbar_depth  # YDim - same depth as top crossbar
    )
    # Center the bottom bar vertically at tray level
    bottom_bar_extrusion = ifc_file.createIfcAxis2Placement3D(
        ifc_file.createIfcCartesianPoint((0.0, 0.0, -height - half_crossbar)),  # Start half below tray level
        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
        ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    )
    bottom_bar_solid = ifc_file.createIfcExtrudedAreaSolid(
        bottom_bar_profile,
        bottom_bar_extrusion,
        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
        crossbar_width  # SAME height as top crossbar
    )
    solids.append(bottom_bar_solid)
    
    # Verify heights in IFC absolute coordinates
    ceiling_z = pos_ifc[2] + height
    tray_z = pos_ifc[2]
    top_bar_top = ceiling_z + half_crossbar
    top_bar_bottom = ceiling_z - half_crossbar
    bottom_bar_top = tray_z + half_crossbar
    bottom_bar_bottom = tray_z - half_crossbar
    rod_length = (top_bar_bottom - bottom_bar_top)
    
    print(f"[HANGER]   Top crossbar: {top_bar_bottom:.3f}m to {top_bar_top:.3f}m (centered at {ceiling_z:.3f}m)")
    print(f"[HANGER]   Bottom bar: {bottom_bar_bottom:.3f}m to {bottom_bar_top:.3f}m (centered at {tray_z:.3f}m)")
    print(f"[HANGER]   Vertical rods: {rod_length:.3f}m ({rod_length*1000:.1f}mm) connecting the bars")
    print(f"[HANGER]   Total height (bar center to bar center): {height:.3f}m ({height*1000:.1f}mm)")
    
    # Create shape representation with all components
    shape_representation = ifc_file.createIfcShapeRepresentation(
        context,
        "Body",
        "SweptSolid",
        solids  # All 4 components
    )
    
    product_shape = ifc_file.createIfcProductDefinitionShape(
        None,
        None,
        [shape_representation]
    )
    hanger.Representation = product_shape
    
    print(f"[HANGER]   ✅ Geometry complete: top bar + 2 rods + bottom bar (all same thickness)")
    
    # Assign to spatial container
    ifc_run(
        "spatial.assign_container",
        file=ifc_file,
        products=[hanger],
        relating_structure=storey,
    )
    
    # Apply color
    if color_hex:
        apply_color_to_element(ifc_file, hanger, color_hex)
    
    print(f"[HANGER]   ✅ Created successfully")
    return hanger


def add_dwg_line_to_ifc(ifc_file, storey, context, line_data, project_coords=None):
    """Add a DWG line as a simple IFC element (IfcBuildingElementProxy with line geometry).
    
    Args:
        ifc_file: IFC file object
        storey: IFC storey element
        context: IFC geometric representation context
        line_data: Dictionary with 'start', 'end', 'layer', 'color' (optional)
        project_coords: Optional project coordinate system info
    
    Returns:
        IFC element representing the line
    """
    start_point = line_data.get("start", [0, 0, 0])
    end_point = line_data.get("end", [0, 0, 0])
    layer_name = line_data.get("layer", "Default")
    color_hex = line_data.get("color", None)
    line_id = line_data.get("id", f"Line_{layer_name}")
    
    print(f"[DWG LINE] Adding line: {line_id}")
    print(f"[DWG LINE]   Start (Y-up): {start_point}")
    print(f"[DWG LINE]   End (Y-up): {end_point}")
    print(f"[DWG LINE]   Layer: {layer_name}")
    
    # Convert Y-up (Three.js) to Z-up (IFC)
    # Input: [x=easting, y=elevation, z=northing]
    # Output: [X=easting, Y=northing, Z=elevation]
    # IMPORTANT: Convert to float explicitly for IfcCartesianPoint
    start_ifc = [float(start_point[0]), float(start_point[2]), float(start_point[1])]
    end_ifc = [float(end_point[0]), float(end_point[2]), float(end_point[1])]
    
    # Create element
    line_element = ifc_run(
        "root.create_entity",
        file=ifc_file,
        ifc_class="IfcBuildingElementProxy",
        name=line_id,
        predefined_type="USERDEFINED",
    )
    
    # Create polyline geometry (simple line)
    ifc_points = [
        ifc_file.createIfcCartesianPoint(tuple(start_ifc)),
        ifc_file.createIfcCartesianPoint(tuple(end_ifc))
    ]
    polyline = ifc_file.createIfcPolyline(ifc_points)
    
    # Create swept disk solid with minimal radius for visibility
    line_radius = 0.01  # 10mm radius for visibility
    swept_solid = ifc_file.createIfcSweptDiskSolid(
        polyline,
        line_radius,
        None,
        None,
        None
    )
    
    # Set placement at origin (geometry is in absolute coordinates)
    origin = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
    z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
    x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    placement = ifc_file.createIfcLocalPlacement(
        None,
        ifc_file.createIfcAxis2Placement3D(origin, z_dir, x_dir)
    )
    line_element.ObjectPlacement = placement
    
    # Create shape representation
    shape_rep = ifc_file.createIfcShapeRepresentation(
        context,
        "Body",
        "SweptSolid",
        [swept_solid]
    )
    
    product_shape = ifc_file.createIfcProductDefinitionShape(
        None,
        None,
        [shape_rep]
    )
    line_element.Representation = product_shape
    
    # Assign to spatial container
    ifc_run(
        "spatial.assign_container",
        file=ifc_file,
        products=[line_element],
        relating_structure=storey,
    )
    
    # Apply color if provided
    if color_hex:
        apply_color_to_element(ifc_file, line_element, color_hex)
    
    print(f"[DWG LINE]   ✅ Line created successfully")
    return line_element


def add_dwg_polyline_to_ifc(ifc_file, storey, context, polyline_data, project_coords=None):
    """Add a DWG polyline as a simple IFC element (IfcBuildingElementProxy with polyline geometry).
    
    Args:
        ifc_file: IFC file object
        storey: IFC storey element
        context: IFC geometric representation context
        polyline_data: Dictionary with 'vertices', 'layer', 'color' (optional)
        project_coords: Optional project coordinate system info
    
    Returns:
        IFC element representing the polyline
    """
    vertices = polyline_data.get("vertices", [])
    layer_name = polyline_data.get("layer", "Default")
    color_hex = polyline_data.get("color", None)
    polyline_id = polyline_data.get("id", f"Polyline_{layer_name}")
    
    if len(vertices) < 2:
        print(f"[DWG POLYLINE] ⚠️ Skipping polyline with < 2 vertices")
        return None
    
    print(f"[DWG POLYLINE] Adding polyline: {polyline_id}")
    print(f"[DWG POLYLINE]   Vertices: {len(vertices)}")
    print(f"[DWG POLYLINE]   Layer: {layer_name}")
    
    # Convert Y-up (Three.js) to Z-up (IFC)
    # IMPORTANT: Convert to float explicitly for IfcCartesianPoint
    vertices_ifc = []
    for vertex in vertices:
        vertex_ifc = [float(vertex[0]), float(vertex[2]), float(vertex[1])]
        vertices_ifc.append(vertex_ifc)
    
    # Create element
    polyline_element = ifc_run(
        "root.create_entity",
        file=ifc_file,
        ifc_class="IfcBuildingElementProxy",
        name=polyline_id,
        predefined_type="USERDEFINED",
    )
    
    # Create polyline geometry
    ifc_points = [ifc_file.createIfcCartesianPoint(tuple(v)) for v in vertices_ifc]
    polyline = ifc_file.createIfcPolyline(ifc_points)
    
    # Create swept disk solid with minimal radius for visibility
    line_radius = 0.01  # 10mm radius for visibility
    swept_solid = ifc_file.createIfcSweptDiskSolid(
        polyline,
        line_radius,
        None,
        None,
        None
    )
    
    # Set placement at origin (geometry is in absolute coordinates)
    origin = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
    z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
    x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    placement = ifc_file.createIfcLocalPlacement(
        None,
        ifc_file.createIfcAxis2Placement3D(origin, z_dir, x_dir)
    )
    polyline_element.ObjectPlacement = placement
    
    # Create shape representation
    shape_rep = ifc_file.createIfcShapeRepresentation(
        context,
        "Body",
        "SweptSolid",
        [swept_solid]
    )
    
    product_shape = ifc_file.createIfcProductDefinitionShape(
        None,
        None,
        [shape_rep]
    )
    polyline_element.Representation = product_shape
    
    # Assign to spatial container
    ifc_run(
        "spatial.assign_container",
        file=ifc_file,
        products=[polyline_element],
        relating_structure=storey,
    )
    
    # Apply color if provided
    if color_hex:
        apply_color_to_element(ifc_file, polyline_element, color_hex)
    
    print(f"[DWG POLYLINE]   ✅ Polyline created successfully")
    return polyline_element


def add_connected_path_to_ifc(ifc_file, storey, context, path_data, project_coords=None):
    """Add a connected path (polyline) as an IFC pipe segment with swept solid geometry.
    
    Uses the same approach as pipes - IfcSweptDiskSolid for proper extrusion.
    
    Args:
        ifc_file: IFC file object
        storey: IFC storey element
        context: IFC geometric representation context
        path_data: Dictionary with 'vertices', 'layer', 'color', 'id'
        project_coords: Optional project coordinate system info
    
    Returns:
        IFC element representing the connected path
    """
    vertices = path_data.get("vertices", [])
    layer_name = path_data.get("layer", "Default")
    color_hex = path_data.get("color", None)
    path_id = path_data.get("id", f"Path_{layer_name}")
    
    if len(vertices) < 2:
        print(f"[CONNECTED PATH] ⚠️ Skipping path with < 2 vertices")
        return None
    
    print(f"[CONNECTED PATH] Adding path: {path_id}")
    print(f"[CONNECTED PATH]   Vertices: {len(vertices)}")
    print(f"[CONNECTED PATH]   Layer: {layer_name}")
    
    # Convert Y-up (Three.js) to Z-up (IFC)
    # Input: [x=easting, y=elevation, z=northing]
    # Output: [X=easting, Y=northing, Z=elevation]
    vertices_ifc = []
    for vertex in vertices:
        vertex_ifc = [float(vertex[0]), float(vertex[2]), float(vertex[1])]
        vertices_ifc.append(vertex_ifc)
    
    # Create pipe segment (using same class as regular pipes for consistency)
    path_element = ifc_run(
        "root.create_entity",
        file=ifc_file,
        ifc_class="IfcPipeSegment",
        name=path_id,
        predefined_type="RIGIDSEGMENT",
    )
    
    # Create polyline geometry from ABSOLUTE coordinates
    ifc_points = [ifc_file.createIfcCartesianPoint(tuple(v)) for v in vertices_ifc]
    polyline = ifc_file.createIfcPolyline(ifc_points)
    
    # Create swept disk solid with small radius for visibility (10mm = 0.01m)
    # This creates a pipe-like extrusion along the path
    path_radius = 0.01  # 10mm radius for visibility
    swept_solid = ifc_file.createIfcSweptDiskSolid(
        polyline,      # Directrix (the path in ABSOLUTE world coordinates)
        path_radius,   # Radius
        None,          # InnerRadius (None for solid)
        None,          # StartParam (None = start of curve)
        None           # EndParam (None = end of curve)
    )
    
    # Set placement at origin (geometry is in absolute coordinates)
    origin = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
    z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
    x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    placement = ifc_file.createIfcLocalPlacement(
        None,  # PlacementRelTo = None for absolute
        ifc_file.createIfcAxis2Placement3D(origin, z_dir, x_dir)
    )
    path_element.ObjectPlacement = placement
    
    # Create shape representation with swept solid
    shape_rep = ifc_file.createIfcShapeRepresentation(
        context,
        "Body",
        "SweptSolid",
        [swept_solid]
    )
    
    product_shape = ifc_file.createIfcProductDefinitionShape(
        None,
        None,
        [shape_rep]
    )
    path_element.Representation = product_shape
    
    # Assign to spatial container
    ifc_run(
        "spatial.assign_container",
        file=ifc_file,
        products=[path_element],
        relating_structure=storey,
    )
    
    # Apply color if provided
    if color_hex:
        apply_color_to_element(ifc_file, path_element, color_hex)
    
    print(f"[CONNECTED PATH]   ✅ Path created successfully with swept solid extrusion")
    return path_element


def export_dwg_lines_to_ifc(connected_paths_data, output_path, project_coords=None):
    """Export connected DWG paths to IFC file using swept solid extrusion.
    
    Args:
        connected_paths_data: List of connected path dictionaries with 'vertices', 'layer', 'color', 'id'
        output_path: Output IFC file path
        project_coords: Optional project coordinate system info
    
    Returns:
        Dictionary with success status and counts
    """
    try:
        path_count = len(connected_paths_data) if connected_paths_data else 0
        print(f"[DWG EXPORT] Starting export with {path_count} connected paths")
        
        project_name = (project_coords or {}).get("name", "DWG Scheme Lines")
        ifc_file, storey, context = create_ifc_file(project_name, project_coords)
        
        # Export connected paths as swept solids
        if connected_paths_data:
            for index, path in enumerate(connected_paths_data, start=1):
                print(f"[DWG EXPORT] Adding connected path {index}/{path_count}")
                add_connected_path_to_ifc(ifc_file, storey, context, path, project_coords)
        
        print(f"[DWG EXPORT] Writing IFC to {output_path}")
        ifc_file.write(output_path)
        print("[DWG EXPORT] ✅ Export complete!")
        
        return {
            "success": True,
            "file": output_path,
            "paths_count": path_count,
        }
    
    except Exception as error:
        print(f"[DWG EXPORT] ❌ ERROR: {error}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(error),
        }


def add_light_connection_to_ifc(
    ifc_file,
    storey,
    context,
    connection_data,
    project_coords=None,
    coordinate_mode="absolute",
    origin_tuple=None,
):
    """Add a public lighting connection conduit to the IFC file.
    
    Uses multiple IfcExtrudedAreaSolid segments for maximum viewer compatibility.
    Each segment is a cylinder extruded between consecutive path points.
    """
    
    connection_id = connection_data.get("connectionId", "LightConnection")
    light_id = connection_data.get("lightId", "")
    points = connection_data.get("points", [])
    diameter = connection_data.get("diameter", 50) / 1000  # mm to meters
    radius = diameter / 2
    conduit_type = connection_data.get("conduitType", "single")
    color_hex = connection_data.get("color", "#FFA500")  # Default orange
    
    if not points or len(points) < 2:
        print(f"[LIGHT CONNECTION] ⚠️ Skipping {connection_id} - insufficient points")
        return None
    
    print(f"\n[LIGHT CONNECTION] Adding: {connection_id}")
    print(f"[LIGHT CONNECTION]   Light ID: {light_id}")
    print(f"[LIGHT CONNECTION]   Points: {len(points)}")
    print(f"[LIGHT CONNECTION]   Diameter: {diameter}m")
    print(f"[LIGHT CONNECTION]   Type: {conduit_type}")
    
    origin_tuple = origin_tuple or get_project_origin_tuple(project_coords)
    
    # Convert all points from Y-up (THREE.js) to Z-up (IFC)
    points_ifc = convert_points_yup_to_ifc(points, origin_tuple, coordinate_mode)
    
    if len(points_ifc) < 2:
        print(f"[LIGHT CONNECTION] ⚠️ Skipping {connection_id} - insufficient converted points")
        return None
    
    print(f"[LIGHT CONNECTION]   Start (absolute): {points_ifc[0]}")
    print(f"[LIGHT CONNECTION]   End (absolute): {points_ifc[-1]}")
    
    # Create circular profile for extrusion
    circle_profile = ifc_file.createIfcCircleProfileDef(
        "AREA",  # ProfileType
        None,    # ProfileName
        ifc_file.createIfcAxis2Placement2D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0)),
            None
        ),
        radius   # Radius
    )
    
    # Create extruded segments between consecutive points
    extruded_solids = []
    segments_created = 0
    
    # Calculate overlap to eliminate gaps at bends
    overlap = radius * 0.5
    
    for i in range(len(points_ifc) - 1):
        pt1 = points_ifc[i]
        pt2 = points_ifc[i + 1]
        
        # Calculate direction vector
        dx = pt2[0] - pt1[0]
        dy = pt2[1] - pt1[1]
        dz = pt2[2] - pt1[2]
        
        # Calculate segment length
        length = math.sqrt(dx*dx + dy*dy + dz*dz)
        
        if length < 0.001:
            print(f"[LIGHT CONNECTION]   Skipping zero-length segment {i}")
            continue
        
        # Normalize direction
        dir_x = dx / length
        dir_y = dy / length
        dir_z = dz / length
        
        # Extend segment to overlap at joints (except at very start and very end)
        start_extension = overlap if i > 0 else 0
        end_extension = overlap if i < len(points_ifc) - 2 else 0
        extended_length = length + start_extension + end_extension
        
        # Offset start point backwards along direction for overlap
        start_pt = [
            pt1[0] - dir_x * start_extension,
            pt1[1] - dir_y * start_extension,
            pt1[2] - dir_z * start_extension
        ]
        
        # Create axis placement at extended start point
        position = ifc_file.createIfcCartesianPoint(tuple(start_pt))
        
        # Calculate reference direction (perpendicular to extrusion)
        # Use cross product with world Z or Y to get a perpendicular vector
        if abs(dir_z) < 0.9:
            # Use Z-axis for cross product
            ref_x = -dir_y
            ref_y = dir_x
            ref_z = 0.0
        else:
            # Use Y-axis for cross product (when direction is mostly vertical)
            ref_x = dir_z
            ref_y = 0.0
            ref_z = -dir_x
        
        # Normalize reference direction
        ref_len = math.sqrt(ref_x*ref_x + ref_y*ref_y + ref_z*ref_z)
        if ref_len > 0.001:
            ref_x /= ref_len
            ref_y /= ref_len
            ref_z /= ref_len
        else:
            ref_x, ref_y, ref_z = 1.0, 0.0, 0.0
        
        # Create axis placement with extrusion direction as Z-axis
        axis_direction = ifc_file.createIfcDirection((dir_x, dir_y, dir_z))
        ref_direction = ifc_file.createIfcDirection((ref_x, ref_y, ref_z))
        
        axis_placement = ifc_file.createIfcAxis2Placement3D(
            position,
            axis_direction,  # Z-axis (extrusion direction)
            ref_direction    # X-axis (reference direction)
        )
        
        # Create extruded area solid with extended length to close gaps at bends
        extruded_solid = ifc_file.createIfcExtrudedAreaSolid(
            circle_profile,
            axis_placement,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),  # Extrude along local Z
            extended_length
        )
        
        extruded_solids.append(extruded_solid)
        segments_created += 1
    
    if not extruded_solids:
        print(f"[LIGHT CONNECTION] ⚠️ No valid segments created for {connection_id}")
        return None
    
    print(f"[LIGHT CONNECTION]   Created {segments_created} extruded segments")
    
    # Create the IFC element - use IfcPipeSegment for compatibility
    conduit = ifc_run(
        "root.create_entity",
        file=ifc_file,
        ifc_class="IfcPipeSegment",
        name=f"Light Connection {connection_id}",
        predefined_type="RIGIDSEGMENT",
    )
    
    # Set placement at origin (geometry is in absolute coordinates)
    placement_point = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
    z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
    x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    placement = ifc_file.createIfcLocalPlacement(
        None,
        ifc_file.createIfcAxis2Placement3D(placement_point, z_dir, x_dir)
    )
    conduit.ObjectPlacement = placement
    
    # Create shape representation with all extruded solids
    shape_rep = ifc_file.createIfcShapeRepresentation(
        context,
        "Body",
        "SweptSolid",
        extruded_solids  # All segments as separate solids
    )
    
    # Create product definition shape
    product_shape = ifc_file.createIfcProductDefinitionShape(
        None,
        None,
        [shape_rep]
    )
    
    # Assign representation to conduit
    conduit.Representation = product_shape
    
    # Assign to spatial container
    ifc_run(
        "spatial.assign_container",
        file=ifc_file,
        products=[conduit],
        relating_structure=storey,
    )
    
    # Apply color if provided
    if color_hex:
        apply_color_to_element(ifc_file, conduit, color_hex)
    
    print(f"[LIGHT CONNECTION]   ✅ Created successfully with {segments_created} segments")
    
    return conduit


def create_sign_geometry(
    ifc_file,
    sign_config,
    pos_x, pos_y, pos_z,
    pole_height,
    pole_diameter,
    rotation
):
    """
    Create sign geometry (plate, border, straps, mounting hardware).
    
    Args:
        ifc_file: The IFC file object
        sign_config: Sign configuration dictionary
        pos_x, pos_y, pos_z: Pole base position in IFC coordinates
        pole_height: Height of the pole in meters
        pole_diameter: Diameter of the pole in meters
        rotation: Rotation around vertical axis in radians
    
    Returns:
        List of IFC solid geometry objects
    """
    solids = []
    
    # Extract sign configuration
    shape = sign_config.get('shape', 'rectangular')
    width_mm = sign_config.get('width', 600)
    height_mm = sign_config.get('height', 400)
    diameter_mm = sign_config.get('diameter', 600)
    thickness_mm = sign_config.get('thickness', 3)
    mount_height_mm = sign_config.get('mountHeight', 0)
    
    # Border configuration
    border_width_mm = sign_config.get('borderWidth', 20)
    
    # Convert to meters
    thickness = thickness_mm / 1000
    mount_height = mount_height_mm / 1000
    border_width = border_width_mm / 1000
    pole_radius = pole_diameter / 2
    
    # Calculate sign dimensions based on shape
    if shape == 'circular':
        sign_width = diameter_mm / 1000
        sign_height = diameter_mm / 1000
    elif shape == 'square':
        sign_width = width_mm / 1000
        sign_height = width_mm / 1000
    else:  # rectangular or custom
        sign_width = width_mm / 1000
        sign_height = height_mm / 1000
    
    print(f"[SIGN] Creating sign: shape={shape}, size={sign_width*1000:.0f}x{sign_height*1000:.0f}mm, thickness={thickness*1000:.0f}mm")
    
    # Calculate sign center position
    # Sign is mounted at top of pole, offset by mount_height
    # Sign top edge is at pole_height - mount_height, center is half sign height below that
    sign_center_z = pos_z + pole_height - mount_height - sign_height / 2
    
    # Sign is positioned in front of pole
    # The sign plate back surface touches the pole front surface
    # sign_offset_from_pole is the distance from pole center to plate center
    sign_offset_from_pole = pole_radius + thickness / 2
    
    # NOTE: We don't pre-calculate sign_center_x/y here because the offset
    # is applied in the plate_placement below using extrude_dir
    
    print(f"[SIGN] Pole position: ({pos_x:.3f}, {pos_y:.3f}, {pos_z:.3f})")
    
    # === SIGN PLATE (skip for custom shapes - they only have SVG geometry) ===
    if shape == 'custom':
        plate_profile = None
        print(f"[SIGN] Custom shape - skipping sign plate (SVG geometry only)")
    elif shape == 'circular':
        # Circular sign plate
        plate_profile = ifc_file.createIfcCircleProfileDef(
            "AREA", None,
            ifc_file.createIfcAxis2Placement2D(
                ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
            ),
            sign_width / 2
        )
    else:
        # Rectangular/square sign plate
        plate_profile = ifc_file.createIfcRectangleProfileDef(
            "AREA", None,
            ifc_file.createIfcAxis2Placement2D(
                ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
            ),
            sign_width, sign_height
        )
    
    # Sign plate is oriented facing outward from pole
    # In Three.js (Y-up): sign faces +Z direction, then rotated around Y axis
    # rotation = 0 means facing +Z (Three.js) = -Y (IFC after Y-up to Z-up conversion)
    # rotation = π/2 means facing +X (Three.js) = +X (IFC)
    # 
    # Three.js to IFC coordinate conversion:
    #   Three.js +X = IFC +X
    #   Three.js +Y = IFC +Z  
    #   Three.js +Z = IFC -Y
    #
    # In Three.js, rotating around Y by 'rotation' radians:
    #   forward direction = (sin(rotation), 0, cos(rotation))
    # Converting to IFC:
    #   forward direction = (sin(rotation), -cos(rotation), 0)
    #
    # But wait - the sign faces +Z in Three.js local coords, then the whole group rotates.
    # So the world-space forward direction in Three.js is (sin(rotation), 0, cos(rotation))
    # In IFC this becomes (sin(rotation), -cos(rotation), 0)
    
    # Direction the sign faces (outward from sign face)
    # Use same formula as baseplate which works correctly: (cos, sin)
    # The sign plate is positioned at pole_radius distance from pole center
    # and faces outward in the direction of rotation
    extrude_dir_x = math.cos(rotation)
    extrude_dir_y = math.sin(rotation)
    
    # Perpendicular direction (left/right on sign face)
    # 90 degrees rotated from extrude direction
    perp_dir_x = -math.sin(rotation)
    perp_dir_y = math.cos(rotation)
    
    print(f"[SIGN] Rotation: {rotation:.4f} rad ({math.degrees(rotation):.1f} deg)")
    print(f"[SIGN] Extrude direction (sign faces): ({extrude_dir_x:.3f}, {extrude_dir_y:.3f})")
    print(f"[SIGN] Perpendicular direction (left/right): ({perp_dir_x:.3f}, {perp_dir_y:.3f})")
    
    # Plate placement - back of plate touches pole surface
    # Position is at the back of the plate (pole surface), then extrude outward by thickness
    # 
    # For IfcAxis2Placement3D:
    #   - Axis (Z) = extrude direction (outward from sign face)
    #   - RefDirection (X) = perpendicular direction in horizontal plane
    #   - Y = derived from Z cross X = should point upward
    #
    # For a vertical sign profile (width x height):
    #   - Profile X = left/right on sign = perpendicular direction (horizontal)
    #   - Profile Y = up/down on sign = should be vertical (0, 0, 1)
    #
    # To get profile Y pointing up, we need RefDirection to be horizontal
    plate_placement = ifc_file.createIfcAxis2Placement3D(
        ifc_file.createIfcCartesianPoint((
            pos_x + extrude_dir_x * pole_radius,
            pos_y + extrude_dir_y * pole_radius,
            sign_center_z
        )),
        ifc_file.createIfcDirection((extrude_dir_x, extrude_dir_y, 0.0)),  # Z-axis = extrude direction (outward)
        ifc_file.createIfcDirection((perp_dir_x, perp_dir_y, 0.0))  # X-axis = perpendicular (left/right, horizontal)
    )
    
    print(f"[SIGN] Plate placement: ({pos_x + extrude_dir_x * pole_radius:.3f}, {pos_y + extrude_dir_y * pole_radius:.3f}, {sign_center_z:.3f})")
    
    # Only create plate solid for non-custom shapes
    if plate_profile is not None:
        plate_solid = ifc_file.createIfcExtrudedAreaSolid(
            plate_profile, plate_placement,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),  # Extrude along local Z
            thickness
        )
        solids.append(plate_solid)
        print(f"[SIGN] Added sign plate")
    
    # === SVG GEOMETRY (extracted shapes from SVG) ===
    # These are returned separately with colors for individual element creation
    svg_shapes_with_colors = []  # List of (solid, color) tuples
    
    export_geometry = sign_config.get('exportGeometry', [])
    if export_geometry:
        print(f"[SIGN] Processing {len(export_geometry)} SVG shapes for export")
        
        svg_solids_created = 0
        for geom_idx, geom in enumerate(export_geometry):
            vertices = geom.get('vertices', [])
            holes = geom.get('holes', [])
            color = geom.get('color', '#000000')
            z_offset = geom.get('zOffset', 0)
            depth = geom.get('depth', 0.001)
            
            if len(vertices) < 3:
                continue
            
            try:
                # Create IFC polygon profile from vertices
                # Vertices are in meters, relative to sign center (X = horizontal, Y = vertical on sign face)
                
                # Calculate the sign face position (front of sign plate)
                sign_face_offset = pole_radius + thickness + z_offset + 0.0001  # Slightly in front of plate
                
                # Transform 2D sign-local coordinates to 3D IFC coordinates
                # Sign local: X = left/right on sign, Y = up/down on sign
                # IFC: X = east, Y = north, Z = up
                # The sign faces outward from pole in the direction of rotation
                
                # Use the perpendicular direction calculated earlier (left/right on sign face)
                perp_x = perp_dir_x
                perp_y = perp_dir_y
                
                # Create 2D points for the profile
                # We need to transform sign-local (vx, vy) to a 2D profile plane
                # The profile plane has:
                #   - X axis = perpendicular direction (left/right on sign)
                #   - Y axis = Z direction (up/down on sign)
                # 
                # Note: SVG coordinates have Y pointing down, but the profile Y should point up
                # The exportGeometry from Three.js should already have correct orientation
                ifc_points = []
                for vx, vy in vertices:
                    # vx = horizontal position on sign (left/right)
                    # vy = vertical position on sign (up/down)
                    # In the profile's 2D coordinate system:
                    ifc_points.append(ifc_file.createIfcCartesianPoint((float(vx), float(vy))))
                
                # Close the polyline
                if ifc_points:
                    ifc_points.append(ifc_points[0])
                
                # Create polyline for outer boundary
                outer_polyline = ifc_file.createIfcPolyline(ifc_points)
                
                # Create profile (with or without holes)
                if holes and len(holes) > 0:
                    # Create hole curves
                    hole_curves = []
                    for hole in holes:
                        if len(hole) >= 3:
                            hole_points = [ifc_file.createIfcCartesianPoint((float(hx), float(hy))) for hx, hy in hole]
                            hole_points.append(hole_points[0])  # Close
                            hole_polyline = ifc_file.createIfcPolyline(hole_points)
                            hole_curves.append(hole_polyline)
                    
                    if hole_curves:
                        # Use IfcArbitraryProfileDefWithVoids for shapes with holes
                        svg_profile = ifc_file.createIfcArbitraryProfileDefWithVoids(
                            "AREA", None, outer_polyline, hole_curves
                        )
                    else:
                        svg_profile = ifc_file.createIfcArbitraryClosedProfileDef(
                            "AREA", None, outer_polyline
                        )
                else:
                    # Simple closed profile without holes
                    svg_profile = ifc_file.createIfcArbitraryClosedProfileDef(
                        "AREA", None, outer_polyline
                    )
                
                # Placement for the SVG shape - on the sign face
                # The profile is defined in a plane where:
                #   - Local X = perpendicular to extrude (left/right on sign)
                #   - Local Y = up (Z in IFC)
                # Position is at sign center, on the front face
                svg_placement = ifc_file.createIfcAxis2Placement3D(
                    ifc_file.createIfcCartesianPoint((
                        pos_x + extrude_dir_x * sign_face_offset,
                        pos_y + extrude_dir_y * sign_face_offset,
                        sign_center_z
                    )),
                    # Z-axis of placement = extrude direction (outward from sign)
                    ifc_file.createIfcDirection((extrude_dir_x, extrude_dir_y, 0.0)),
                    # X-axis of placement = perpendicular (left/right on sign)
                    ifc_file.createIfcDirection((perp_x, perp_y, 0.0))
                )
                
                # Create extruded solid - extrude along the placement's Z axis (which is outward)
                svg_solid = ifc_file.createIfcExtrudedAreaSolid(
                    svg_profile, svg_placement,
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),  # Extrude along local Z
                    depth
                )
                # Store with color for separate element creation
                svg_shapes_with_colors.append((svg_solid, color))
                svg_solids_created += 1
                
            except Exception as e:
                print(f"[SIGN] Warning: Failed to create SVG shape {geom_idx}: {e}")
                continue
        
        print(f"[SIGN] Created {svg_solids_created} SVG geometry solids with colors")
    else:
        print(f"[SIGN] No exportGeometry found - sign will have plate only")
    
    # === SIGN BORDER (if configured) ===
    if border_width > 0.001 and shape != 'custom':
        if shape == 'circular':
            # Ring border for circular sign
            outer_radius = sign_width / 2
            inner_radius = outer_radius - border_width
            
            # Create ring using two circles (outer - inner)
            # For simplicity, create as a thin cylinder at the edge
            border_profile = ifc_file.createIfcCircleProfileDef(
                "AREA", None,
                ifc_file.createIfcAxis2Placement2D(
                    ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                ),
                outer_radius
            )
            
            border_placement = ifc_file.createIfcAxis2Placement3D(
                ifc_file.createIfcCartesianPoint((
                    pos_x + extrude_dir_x * (pole_radius + thickness),
                    pos_y + extrude_dir_y * (pole_radius + thickness),
                    sign_center_z
                )),
                ifc_file.createIfcDirection((extrude_dir_x, extrude_dir_y, 0.0)),
                ifc_file.createIfcDirection((perp_dir_x, perp_dir_y, 0.0))
            )
            
            border_solid = ifc_file.createIfcExtrudedAreaSolid(
                border_profile, border_placement,
                ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                thickness * 0.2  # Thin border layer
            )
            solids.append(border_solid)
        else:
            # Frame border for rectangular/square sign
            # Create as 4 thin boxes around the edge
            frame_thickness = thickness * 1.2
            
            # Top border
            top_profile = ifc_file.createIfcRectangleProfileDef(
                "AREA", None,
                ifc_file.createIfcAxis2Placement2D(
                    ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                ),
                sign_width, border_width
            )
            top_placement = ifc_file.createIfcAxis2Placement3D(
                ifc_file.createIfcCartesianPoint((
                    pos_x + extrude_dir_x * (pole_radius + thickness * 0.6),
                    pos_y + extrude_dir_y * (pole_radius + thickness * 0.6),
                    sign_center_z + (sign_height - border_width) / 2
                )),
                ifc_file.createIfcDirection((extrude_dir_x, extrude_dir_y, 0.0)),
                ifc_file.createIfcDirection((perp_dir_x, perp_dir_y, 0.0))
            )
            top_solid = ifc_file.createIfcExtrudedAreaSolid(
                top_profile, top_placement,
                ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                frame_thickness
            )
            solids.append(top_solid)
            
            # Bottom border
            bottom_placement = ifc_file.createIfcAxis2Placement3D(
                ifc_file.createIfcCartesianPoint((
                    pos_x + extrude_dir_x * (pole_radius + thickness * 0.6),
                    pos_y + extrude_dir_y * (pole_radius + thickness * 0.6),
                    sign_center_z - (sign_height - border_width) / 2
                )),
                ifc_file.createIfcDirection((extrude_dir_x, extrude_dir_y, 0.0)),
                ifc_file.createIfcDirection((perp_dir_x, perp_dir_y, 0.0))
            )
            bottom_solid = ifc_file.createIfcExtrudedAreaSolid(
                top_profile, bottom_placement,
                ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                frame_thickness
            )
            solids.append(bottom_solid)
            
            # Left border
            side_profile = ifc_file.createIfcRectangleProfileDef(
                "AREA", None,
                ifc_file.createIfcAxis2Placement2D(
                    ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                ),
                border_width, sign_height - 2 * border_width
            )
            
            # Calculate left position (negative perpendicular direction)
            side_offset = (sign_width - border_width) / 2
            left_offset_x = -perp_dir_x * side_offset
            left_offset_y = -perp_dir_y * side_offset
            
            left_placement = ifc_file.createIfcAxis2Placement3D(
                ifc_file.createIfcCartesianPoint((
                    pos_x + extrude_dir_x * (pole_radius + thickness * 0.6) + left_offset_x,
                    pos_y + extrude_dir_y * (pole_radius + thickness * 0.6) + left_offset_y,
                    sign_center_z
                )),
                ifc_file.createIfcDirection((extrude_dir_x, extrude_dir_y, 0.0)),
                ifc_file.createIfcDirection((perp_dir_x, perp_dir_y, 0.0))
            )
            left_solid = ifc_file.createIfcExtrudedAreaSolid(
                side_profile, left_placement,
                ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                frame_thickness
            )
            solids.append(left_solid)
            
            # Right border (positive perpendicular direction)
            right_offset_x = perp_dir_x * side_offset
            right_offset_y = perp_dir_y * side_offset
            
            right_placement = ifc_file.createIfcAxis2Placement3D(
                ifc_file.createIfcCartesianPoint((
                    pos_x + extrude_dir_x * (pole_radius + thickness * 0.6) + right_offset_x,
                    pos_y + extrude_dir_y * (pole_radius + thickness * 0.6) + right_offset_y,
                    sign_center_z
                )),
                ifc_file.createIfcDirection((extrude_dir_x, extrude_dir_y, 0.0)),
                ifc_file.createIfcDirection((perp_dir_x, perp_dir_y, 0.0))
            )
            right_solid = ifc_file.createIfcExtrudedAreaSolid(
                side_profile, right_placement,
                ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                frame_thickness
            )
            solids.append(right_solid)
        
        print(f"[SIGN] Added sign border")
    
    # Return both the main solids (plate, border, straps) and the colored SVG shapes
    return solids, svg_shapes_with_colors


def add_public_light_to_ifc(
    ifc_file,
    storey,
    context,
    light_data,
    project_coords=None,
    coordinate_mode="absolute",
    origin_tuple=None,
):
    """
    Add a public light (pole, baseplate/foundation, fixture) to IFC file.
    
    Args:
        ifc_file: The IFC file object
        storey: The building storey to add the light to
        context: The geometric representation context
        light_data: Dictionary with light configuration
        project_coords: Project coordinate system info
        coordinate_mode: 'absolute' or 'project'
        origin_tuple: Project origin as tuple
    
    Returns:
        The created IFC element or None if failed
    """
    try:
        light_id = light_data.get('id', 'unknown')
        reference_id = light_data.get('referenceId') or light_id
        position = light_data.get('position', {})
        rotation = light_data.get('rotation', 0)  # Y-axis rotation in radians
        
        pole_config = light_data.get('poleConfig', {})
        fixture_config = light_data.get('fixtureConfig', {})
        
        origin_tuple = origin_tuple or get_project_origin_tuple(project_coords)
        
        # Convert position from Three.js Y-up to IFC Z-up using the same method as light connections
        threejs_pos = [position.get('x', 0), position.get('y', 0), position.get('z', 0)]
        ifc_pos = convert_point_yup_to_ifc(threejs_pos, origin_tuple, coordinate_mode)
        pos_x, pos_y, pos_z = ifc_pos[0], ifc_pos[1], ifc_pos[2]
        
        print(f"[PUBLIC LIGHT] Creating light {reference_id}")
        print(f"[PUBLIC LIGHT]   Three.js position: ({threejs_pos[0]:.3f}, {threejs_pos[1]:.3f}, {threejs_pos[2]:.3f})")
        print(f"[PUBLIC LIGHT]   IFC position: ({pos_x:.3f}, {pos_y:.3f}, {pos_z:.3f})")
        print(f"[PUBLIC LIGHT]   Rotation: {rotation:.3f} rad ({math.degrees(rotation):.1f} deg)")
        
        # Pole configuration
        pole_height = pole_config.get('height', 10)  # meters
        pole_diameter = pole_config.get('diameter', 200) / 1000  # mm to m
        taper_ratio = pole_config.get('taperRatio', 0.3)
        pole_color = pole_config.get('color', '#707070')
        base_type = pole_config.get('baseType', 'embedded')
        
        # Get housing color for the fixture (use this as the main color for the light element)
        housing_color = fixture_config.get('housingColor', '#404040')
        
        print(f"[PUBLIC LIGHT]   Pole: height={pole_height}m, diameter={pole_diameter*1000:.0f}mm, taper={taper_ratio}, base={base_type}")
        print(f"[PUBLIC LIGHT]   Pole color: {pole_color}, Housing color: {housing_color}")
        
        # Calculate top and bottom radii for tapered pole
        bottom_radius = pole_diameter / 2
        top_radius = bottom_radius * (1 - taper_ratio)
        
        # Create all geometry solids - track by component for coloring
        solids = []
        pole_solids = []  # For pole color
        baseplate_solids = []  # For baseplate/metal color
        foundation_solids = []  # For concrete color
        fixture_solids = []  # For housing color
        
        # === POLE ===
        # Create tapered cylinder for pole using IfcExtrudedAreaSolid with circle profile
        # For simplicity, use average radius (proper taper would need IfcSweptDiskSolid)
        avg_radius = (bottom_radius + top_radius) / 2
        pole_profile = ifc_file.createIfcCircleProfileDef(
            "AREA",
            None,
            ifc_file.createIfcAxis2Placement2D(
                ifc_file.createIfcCartesianPoint((0.0, 0.0)),
                None
            ),
            avg_radius
        )
        
        # Pole placement (at base position, extruding upward)
        pole_placement = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint((pos_x, pos_y, pos_z)),
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),  # Extrude up (Z)
            ifc_file.createIfcDirection((1.0, 0.0, 0.0))
        )
        
        pole_solid = ifc_file.createIfcExtrudedAreaSolid(
            pole_profile,
            pole_placement,
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
            pole_height
        )
        solids.append(pole_solid)
        pole_solids.append(pole_solid)  # Track for pole color
        
        # === BASEPLATE ===
        if base_type == 'baseplate':
            baseplate_shape = pole_config.get('baseplateShape', 'rectangular')
            baseplate_thickness = pole_config.get('baseplateThickness', 20) / 1000  # mm to m
            
            print(f"[PUBLIC LIGHT]   Baseplate: shape={baseplate_shape}, thickness={baseplate_thickness*1000:.0f}mm")
            
            if baseplate_shape == 'circular':
                plate_diameter = pole_config.get('baseplateDiameter', 500) / 1000  # mm to m
                plate_profile = ifc_file.createIfcCircleProfileDef(
                    "AREA", None,
                    ifc_file.createIfcAxis2Placement2D(
                        ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                    ),
                    plate_diameter / 2
                )
                plate_size = plate_diameter
            else:
                # Rectangular
                plate_width = pole_config.get('baseplateWidth', 500) / 1000  # mm to m
                plate_depth = pole_config.get('baseplateDepth', 500) / 1000  # mm to m
                plate_profile = ifc_file.createIfcRectangleProfileDef(
                    "AREA", None,
                    ifc_file.createIfcAxis2Placement2D(
                        ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                    ),
                    plate_width, plate_depth
                )
                plate_size = min(plate_width, plate_depth)
            
            # Baseplate placement (at ground level, rotated with light)
            baseplate_placement = ifc_file.createIfcAxis2Placement3D(
                ifc_file.createIfcCartesianPoint((pos_x, pos_y, pos_z)),
                ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                ifc_file.createIfcDirection((math.cos(rotation), math.sin(rotation), 0.0))
            )
            
            baseplate_solid = ifc_file.createIfcExtrudedAreaSolid(
                plate_profile, baseplate_placement,
                ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                baseplate_thickness
            )
            solids.append(baseplate_solid)
            baseplate_solids.append(baseplate_solid)  # Track for baseplate color
            
            # Add stiffener gussets if enabled
            if pole_config.get('enableGussets', False):
                gusset_count = pole_config.get('gussetCount', 4)
                gusset_height = pole_config.get('gussetHeight', 100) / 1000  # mm to m
                gusset_thickness = pole_config.get('gussetThickness', 10) / 1000  # mm to m
                gusset_length = pole_config.get('gussetLength', 150) / 1000  # mm to m
                
                print(f"[PUBLIC LIGHT]   Adding {gusset_count} stiffener gussets (h={gusset_height*1000:.0f}mm, t={gusset_thickness*1000:.0f}mm, l={gusset_length*1000:.0f}mm)")
                
                for g in range(gusset_count):
                    gusset_angle = (g / gusset_count) * 2 * math.pi + rotation
                    
                    # Gusset is a thin rectangular plate oriented radially
                    gusset_profile = ifc_file.createIfcRectangleProfileDef(
                        "AREA", None,
                        ifc_file.createIfcAxis2Placement2D(
                            ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                        ),
                        gusset_length, gusset_thickness
                    )
                    
                    # Position gusset at edge of pole, oriented radially
                    gusset_x = pos_x + math.cos(gusset_angle) * (pole_diameter / 2 + gusset_length / 2)
                    gusset_y = pos_y + math.sin(gusset_angle) * (pole_diameter / 2 + gusset_length / 2)
                    
                    gusset_placement = ifc_file.createIfcAxis2Placement3D(
                        ifc_file.createIfcCartesianPoint((gusset_x, gusset_y, pos_z + baseplate_thickness)),
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        ifc_file.createIfcDirection((math.cos(gusset_angle), math.sin(gusset_angle), 0.0))
                    )
                    
                    gusset_solid = ifc_file.createIfcExtrudedAreaSolid(
                        gusset_profile, gusset_placement,
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        gusset_height
                    )
                    solids.append(gusset_solid)
                    baseplate_solids.append(gusset_solid)  # Track for baseplate color
            
            # Add anchor bolts with proper LOD
            bolt_count = pole_config.get('boltCount', 4)
            bolt_diameter = pole_config.get('boltDiameter', 20) / 1000  # mm to m
            bolt_head_diameter = pole_config.get('boltHeadDiameter', 32) / 1000  # mm to m
            bolt_head_height = pole_config.get('boltHeadHeight', 12) / 1000  # mm to m
            
            # Washer dimensions
            washer_outer_diameter = bolt_head_diameter * 1.3
            washer_inner_diameter = bolt_diameter * 1.1
            washer_thickness = bolt_diameter * 0.15
            
            # Thread protrusion above nut
            thread_protrusion = bolt_diameter * 0.5
            
            # Calculate bolt positions - must match Three.js positioning
            print(f"[PUBLIC LIGHT]   Adding {bolt_count} anchor bolts with washers and hex nuts")
            
            for i in range(bolt_count):
                # Calculate local bolt position (relative to pole center)
                local_bolt_x = 0.0
                local_bolt_y = 0.0  # This is IFC Y (Three.js Z)
                
                if baseplate_shape == 'circular':
                    # Circular pattern
                    bolt_radius = (pole_config.get('baseplateDiameter', 500) / 1000) * 0.375  # 75% of radius
                    angle = (i / bolt_count) * 2 * math.pi
                    local_bolt_x = math.cos(angle) * bolt_radius
                    local_bolt_y = math.sin(angle) * bolt_radius
                else:
                    # Rectangular pattern - place bolts near corners (matching Three.js)
                    plate_w = pole_config.get('baseplateWidth', 500) / 1000
                    plate_d = pole_config.get('baseplateDepth', 500) / 1000
                    corner_offset_x = plate_w * 0.4
                    corner_offset_y = plate_d * 0.4  # IFC Y = Three.js Z
                    
                    if bolt_count == 4:
                        # 4 bolts at corners
                        corners = [
                            (-corner_offset_x, -corner_offset_y),
                            (corner_offset_x, -corner_offset_y),
                            (corner_offset_x, corner_offset_y),
                            (-corner_offset_x, corner_offset_y),
                        ]
                        local_bolt_x, local_bolt_y = corners[i]
                    elif bolt_count == 6:
                        # 6 bolts - 2 rows of 3
                        positions = [
                            (-corner_offset_x, -corner_offset_y),
                            (0, -corner_offset_y),
                            (corner_offset_x, -corner_offset_y),
                            (-corner_offset_x, corner_offset_y),
                            (0, corner_offset_y),
                            (corner_offset_x, corner_offset_y),
                        ]
                        local_bolt_x, local_bolt_y = positions[i]
                    elif bolt_count == 8:
                        # 8 bolts - corners plus midpoints
                        positions = [
                            (-corner_offset_x, -corner_offset_y),
                            (0, -corner_offset_y),
                            (corner_offset_x, -corner_offset_y),
                            (corner_offset_x, 0),
                            (corner_offset_x, corner_offset_y),
                            (0, corner_offset_y),
                            (-corner_offset_x, corner_offset_y),
                            (-corner_offset_x, 0),
                        ]
                        local_bolt_x, local_bolt_y = positions[i]
                    else:
                        # Fallback to circular pattern
                        bolt_radius = min(plate_w, plate_d) * 0.4
                        angle = (i / bolt_count) * 2 * math.pi
                        local_bolt_x = math.cos(angle) * bolt_radius
                        local_bolt_y = math.sin(angle) * bolt_radius
                
                # Apply rotation and translate to world position
                # rotation is around vertical axis (IFC Z, Three.js Y)
                cos_rot = math.cos(rotation)
                sin_rot = math.sin(rotation)
                rotated_x = local_bolt_x * cos_rot - local_bolt_y * sin_rot
                rotated_y = local_bolt_x * sin_rot + local_bolt_y * cos_rot
                
                bolt_x = pos_x + rotated_x
                bolt_y = pos_y + rotated_y
                
                # 1. Anchor bolt shaft (extends from below baseplate through to above)
                bolt_shaft_length = baseplate_thickness + washer_thickness + bolt_head_height + thread_protrusion
                bolt_profile = ifc_file.createIfcCircleProfileDef(
                    "AREA", None,
                    ifc_file.createIfcAxis2Placement2D(
                        ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                    ),
                    bolt_diameter / 2
                )
                
                bolt_placement = ifc_file.createIfcAxis2Placement3D(
                    ifc_file.createIfcCartesianPoint((bolt_x, bolt_y, pos_z - 0.01)),  # Slightly below baseplate
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                )
                
                bolt_solid = ifc_file.createIfcExtrudedAreaSolid(
                    bolt_profile, bolt_placement,
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    bolt_shaft_length + 0.01
                )
                solids.append(bolt_solid)
                
                # 2. Washer (flat ring on top of baseplate)
                # Create washer as a circle (simplified - proper would be hollow)
                washer_profile = ifc_file.createIfcCircleProfileDef(
                    "AREA", None,
                    ifc_file.createIfcAxis2Placement2D(
                        ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                    ),
                    washer_outer_diameter / 2
                )
                
                washer_placement = ifc_file.createIfcAxis2Placement3D(
                    ifc_file.createIfcCartesianPoint((bolt_x, bolt_y, pos_z + baseplate_thickness)),
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                )
                
                washer_solid = ifc_file.createIfcExtrudedAreaSolid(
                    washer_profile, washer_placement,
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    washer_thickness
                )
                solids.append(washer_solid)
                
                # 3. Hexagonal nut (6-sided polygon)
                # Create hexagon profile using IfcArbitraryClosedProfileDef
                hex_radius = bolt_head_diameter / 2
                hex_points = []
                for h in range(6):
                    hex_angle = (h / 6) * 2 * math.pi
                    hx = hex_radius * math.cos(hex_angle)
                    hy = hex_radius * math.sin(hex_angle)
                    hex_points.append(ifc_file.createIfcCartesianPoint((hx, hy)))
                hex_points.append(hex_points[0])  # Close the polygon
                
                hex_polyline = ifc_file.createIfcPolyline(hex_points)
                hex_profile = ifc_file.createIfcArbitraryClosedProfileDef(
                    "AREA", None, hex_polyline
                )
                
                nut_placement = ifc_file.createIfcAxis2Placement3D(
                    ifc_file.createIfcCartesianPoint((bolt_x, bolt_y, pos_z + baseplate_thickness + washer_thickness)),
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                )
                
                nut_solid = ifc_file.createIfcExtrudedAreaSolid(
                    hex_profile, nut_placement,
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    bolt_head_height
                )
                solids.append(nut_solid)
            
            print(f"[PUBLIC LIGHT]   Added {bolt_count} complete bolt assemblies (shaft + washer + hex nut)")
        
        # === CONCRETE FOUNDATION ===
        elif base_type == 'concrete-foundation':
            foundation_shape = pole_config.get('foundationShape', 'rectangular')
            foundation_height = pole_config.get('foundationHeight', 200) / 1000  # mm to m
            
            if foundation_shape == 'circular':
                foundation_diameter = pole_config.get('foundationDiameter', 600) / 1000  # mm to m
                foundation_profile = ifc_file.createIfcCircleProfileDef(
                    "AREA",
                    None,
                    ifc_file.createIfcAxis2Placement2D(
                        ifc_file.createIfcCartesianPoint((0.0, 0.0)),
                        None
                    ),
                    foundation_diameter / 2
                )
            else:
                foundation_width = pole_config.get('foundationWidth', 600) / 1000  # mm to m
                foundation_depth = pole_config.get('foundationDepth', 600) / 1000  # mm to m
                foundation_profile = ifc_file.createIfcRectangleProfileDef(
                    "AREA",
                    None,
                    ifc_file.createIfcAxis2Placement2D(
                        ifc_file.createIfcCartesianPoint((0.0, 0.0)),
                        None
                    ),
                    foundation_width,
                    foundation_depth
                )
            
            foundation_placement = ifc_file.createIfcAxis2Placement3D(
                ifc_file.createIfcCartesianPoint((pos_x, pos_y, pos_z)),
                ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                ifc_file.createIfcDirection((math.cos(rotation), math.sin(rotation), 0.0))
            )
            
            foundation_solid = ifc_file.createIfcExtrudedAreaSolid(
                foundation_profile,
                foundation_placement,
                ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                foundation_height
            )
            solids.append(foundation_solid)
            foundation_solids.append(foundation_solid)  # Track for concrete color
            
            # Add baseplate on top of foundation if enabled
            if pole_config.get('foundationHasBaseplate', False):
                baseplate_z = pos_z + foundation_height  # On top of foundation
                baseplate_shape = pole_config.get('baseplateShape', 'rectangular')
                baseplate_thickness = pole_config.get('baseplateThickness', 20) / 1000  # mm to m
                
                print(f"[PUBLIC LIGHT]   Foundation baseplate: shape={baseplate_shape}, thickness={baseplate_thickness*1000:.0f}mm")
                
                if baseplate_shape == 'circular':
                    plate_diameter = pole_config.get('baseplateDiameter', 500) / 1000
                    plate_profile = ifc_file.createIfcCircleProfileDef(
                        "AREA", None,
                        ifc_file.createIfcAxis2Placement2D(
                            ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                        ),
                        plate_diameter / 2
                    )
                else:
                    plate_width = pole_config.get('baseplateWidth', 500) / 1000
                    plate_depth = pole_config.get('baseplateDepth', 500) / 1000
                    plate_profile = ifc_file.createIfcRectangleProfileDef(
                        "AREA", None,
                        ifc_file.createIfcAxis2Placement2D(
                            ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                        ),
                        plate_width, plate_depth
                    )
                
                baseplate_placement = ifc_file.createIfcAxis2Placement3D(
                    ifc_file.createIfcCartesianPoint((pos_x, pos_y, baseplate_z)),
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    ifc_file.createIfcDirection((math.cos(rotation), math.sin(rotation), 0.0))
                )
                
                baseplate_solid = ifc_file.createIfcExtrudedAreaSolid(
                    plate_profile, baseplate_placement,
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    baseplate_thickness
                )
                solids.append(baseplate_solid)
                baseplate_solids.append(baseplate_solid)  # Track for baseplate color
                
                # Add gussets if enabled
                if pole_config.get('enableGussets', False):
                    gusset_count = pole_config.get('gussetCount', 4)
                    gusset_height = pole_config.get('gussetHeight', 100) / 1000
                    gusset_thickness = pole_config.get('gussetThickness', 10) / 1000
                    gusset_length = pole_config.get('gussetLength', 150) / 1000
                    
                    print(f"[PUBLIC LIGHT]   Adding {gusset_count} foundation baseplate gussets")
                    
                    for g in range(gusset_count):
                        gusset_angle = (g / gusset_count) * 2 * math.pi + rotation
                        
                        gusset_profile = ifc_file.createIfcRectangleProfileDef(
                            "AREA", None,
                            ifc_file.createIfcAxis2Placement2D(
                                ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                            ),
                            gusset_length, gusset_thickness
                        )
                        
                        gusset_x = pos_x + math.cos(gusset_angle) * (pole_diameter / 2 + gusset_length / 2)
                        gusset_y = pos_y + math.sin(gusset_angle) * (pole_diameter / 2 + gusset_length / 2)
                        
                        gusset_placement = ifc_file.createIfcAxis2Placement3D(
                            ifc_file.createIfcCartesianPoint((gusset_x, gusset_y, baseplate_z + baseplate_thickness)),
                            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                            ifc_file.createIfcDirection((math.cos(gusset_angle), math.sin(gusset_angle), 0.0))
                        )
                        
                        gusset_solid = ifc_file.createIfcExtrudedAreaSolid(
                            gusset_profile, gusset_placement,
                            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                            gusset_height
                        )
                        solids.append(gusset_solid)
                        baseplate_solids.append(gusset_solid)  # Track for baseplate color
                
                # Add bolts for foundation baseplate
                bolt_count = pole_config.get('boltCount', 4)
                bolt_diameter = pole_config.get('boltDiameter', 20) / 1000
                bolt_head_diameter = pole_config.get('boltHeadDiameter', 32) / 1000
                bolt_head_height = pole_config.get('boltHeadHeight', 12) / 1000
                washer_outer_diameter = bolt_head_diameter * 1.3
                washer_thickness = bolt_diameter * 0.15
                
                print(f"[PUBLIC LIGHT]   Adding {bolt_count} foundation baseplate bolts")
                
                for i in range(bolt_count):
                    local_bolt_x = 0.0
                    local_bolt_y = 0.0
                    
                    if baseplate_shape == 'circular':
                        bolt_radius = (pole_config.get('baseplateDiameter', 500) / 1000) * 0.375
                        angle = (i / bolt_count) * 2 * math.pi
                        local_bolt_x = math.cos(angle) * bolt_radius
                        local_bolt_y = math.sin(angle) * bolt_radius
                    else:
                        plate_w = pole_config.get('baseplateWidth', 500) / 1000
                        plate_d = pole_config.get('baseplateDepth', 500) / 1000
                        corner_offset_x = plate_w * 0.4
                        corner_offset_y = plate_d * 0.4
                        
                        if bolt_count == 4:
                            corners = [
                                (-corner_offset_x, -corner_offset_y),
                                (corner_offset_x, -corner_offset_y),
                                (corner_offset_x, corner_offset_y),
                                (-corner_offset_x, corner_offset_y),
                            ]
                            local_bolt_x, local_bolt_y = corners[i]
                        else:
                            bolt_radius = min(plate_w, plate_d) * 0.4
                            angle = (i / bolt_count) * 2 * math.pi
                            local_bolt_x = math.cos(angle) * bolt_radius
                            local_bolt_y = math.sin(angle) * bolt_radius
                    
                    cos_rot = math.cos(rotation)
                    sin_rot = math.sin(rotation)
                    rotated_x = local_bolt_x * cos_rot - local_bolt_y * sin_rot
                    rotated_y = local_bolt_x * sin_rot + local_bolt_y * cos_rot
                    
                    bolt_x = pos_x + rotated_x
                    bolt_y = pos_y + rotated_y
                    
                    # Bolt shaft
                    bolt_profile = ifc_file.createIfcCircleProfileDef(
                        "AREA", None,
                        ifc_file.createIfcAxis2Placement2D(
                            ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                        ),
                        bolt_diameter / 2
                    )
                    bolt_placement = ifc_file.createIfcAxis2Placement3D(
                        ifc_file.createIfcCartesianPoint((bolt_x, bolt_y, baseplate_z - 0.01)),
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                    )
                    bolt_solid = ifc_file.createIfcExtrudedAreaSolid(
                        bolt_profile, bolt_placement,
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        baseplate_thickness + washer_thickness + bolt_head_height + 0.02
                    )
                    solids.append(bolt_solid)
                    
                    # Washer
                    washer_profile = ifc_file.createIfcCircleProfileDef(
                        "AREA", None,
                        ifc_file.createIfcAxis2Placement2D(
                            ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                        ),
                        washer_outer_diameter / 2
                    )
                    washer_placement = ifc_file.createIfcAxis2Placement3D(
                        ifc_file.createIfcCartesianPoint((bolt_x, bolt_y, baseplate_z + baseplate_thickness)),
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                    )
                    washer_solid = ifc_file.createIfcExtrudedAreaSolid(
                        washer_profile, washer_placement,
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        washer_thickness
                    )
                    solids.append(washer_solid)
                    
                    # Hex nut
                    hex_radius = bolt_head_diameter / 2
                    hex_points = []
                    for h in range(6):
                        hex_angle = (h / 6) * 2 * math.pi
                        hx = hex_radius * math.cos(hex_angle)
                        hy = hex_radius * math.sin(hex_angle)
                        hex_points.append(ifc_file.createIfcCartesianPoint((hx, hy)))
                    hex_points.append(hex_points[0])
                    
                    hex_polyline = ifc_file.createIfcPolyline(hex_points)
                    hex_profile = ifc_file.createIfcArbitraryClosedProfileDef("AREA", None, hex_polyline)
                    
                    nut_placement = ifc_file.createIfcAxis2Placement3D(
                        ifc_file.createIfcCartesianPoint((bolt_x, bolt_y, baseplate_z + baseplate_thickness + washer_thickness)),
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                    )
                    nut_solid = ifc_file.createIfcExtrudedAreaSolid(
                        hex_profile, nut_placement,
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        bolt_head_height
                    )
                    solids.append(nut_solid)
        
        # === CHECK IF THIS IS A SIGN ===
        element_type = light_data.get('type', 'light')
        sign_config = light_data.get('signConfig')
        
        print(f"[PUBLIC LIGHT]   Element type: '{element_type}', has signConfig: {sign_config is not None}")
        if sign_config:
            print(f"[PUBLIC LIGHT]   Sign config shape: {sign_config.get('shape')}, width: {sign_config.get('width')}, height: {sign_config.get('height')}")
        
        if element_type == 'sign' and sign_config:
            # This is a sign - create sign geometry instead of fixture
            print(f"[SIGN] Creating sign with rotation: {rotation:.4f} rad ({math.degrees(rotation):.1f} deg)")
            # Returns (main_solids, svg_shapes_with_colors)
            sign_solids, svg_shapes_with_colors = create_sign_geometry(
                ifc_file,
                sign_config,
                pos_x, pos_y, pos_z,
                pole_height,
                pole_diameter,
                rotation
            )
            solids.extend(sign_solids)
            
            # Create the main sign element (plate, border, straps) with background color
            sign_element = ifc_run(
                "root.create_entity",
                file=ifc_file,
                ifc_class="IfcBuildingElementProxy",
                name=f"Sign {reference_id}",
                predefined_type="USERDEFINED",
            )
            
            # Set placement at origin (geometry is in absolute coordinates)
            placement_point = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
            z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
            x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
            placement = ifc_file.createIfcLocalPlacement(
                None,
                ifc_file.createIfcAxis2Placement3D(placement_point, z_dir, x_dir)
            )
            sign_element.ObjectPlacement = placement
            
            # Create shape representation with main solids (plate, border, straps)
            shape_rep = ifc_file.createIfcShapeRepresentation(
                context,
                "Body",
                "SweptSolid",
                solids
            )
            
            # Create product definition shape
            product_shape = ifc_file.createIfcProductDefinitionShape(
                None,
                None,
                [shape_rep]
            )
            
            # Assign representation
            sign_element.Representation = product_shape
            
            # Assign to spatial container
            ifc_run(
                "spatial.assign_container",
                file=ifc_file,
                products=[sign_element],
                relating_structure=storey,
            )
            
            # Apply colors to individual components using styled items
            def apply_color_to_solids(solids_list, color_hex, component_name):
                """Apply color to a list of solids using styled items"""
                if not solids_list or not color_hex:
                    return
                rgb = hex_to_rgb(color_hex)
                if not rgb:
                    return
                
                # Create surface style for this color
                colour_rgb = ifc_file.createIfcColourRgb(None, rgb[0], rgb[1], rgb[2])
                surface_style_rendering = ifc_file.createIfcSurfaceStyleRendering(
                    colour_rgb, 0.0, None, None, None, None, None, None, "FLAT"
                )
                surface_style = ifc_file.createIfcSurfaceStyle(
                    f"{component_name}_{color_hex}", "BOTH", [surface_style_rendering]
                )
                
                # Apply style to each solid
                for solid in solids_list:
                    ifc_file.createIfcStyledItem(
                        solid,
                        [ifc_file.createIfcPresentationStyleAssignment([surface_style])],
                        None
                    )
                print(f"[COLOR] Applied {color_hex} to {len(solids_list)} {component_name} parts")
            
            # Apply pole color
            if pole_solids and pole_color:
                apply_color_to_solids(pole_solids, pole_color, "pole")
            
            # Apply baseplate color (same as pole color for metal parts)
            if baseplate_solids and pole_color:
                apply_color_to_solids(baseplate_solids, pole_color, "baseplate")
            
            # Apply concrete color to foundation
            concrete_color = '#888888'  # Standard concrete grey
            if foundation_solids:
                apply_color_to_solids(foundation_solids, concrete_color, "foundation")
            
            # Apply sign background color to sign plate solids
            sign_bg_color = sign_config.get('backgroundColor', '#FFFFFF')
            if sign_bg_color and sign_solids:
                apply_color_to_solids(sign_solids, sign_bg_color, "sign_plate")
            
            # Add SVG shapes to the same element but with individual styled items for colors
            if svg_shapes_with_colors:
                # Group SVG shapes by color for efficiency
                color_groups = {}
                for svg_solid, svg_color in svg_shapes_with_colors:
                    if svg_color not in color_groups:
                        color_groups[svg_color] = []
                    color_groups[svg_color].append(svg_solid)
                
                print(f"[SIGN] Processing {len(svg_shapes_with_colors)} SVG shapes in {len(color_groups)} color groups")
                
                # Create styled representations for each color group
                for svg_color, svg_solids in color_groups.items():
                    try:
                        # Parse color
                        hex_color = svg_color.lstrip('#')
                        r = int(hex_color[0:2], 16) / 255.0
                        g = int(hex_color[2:4], 16) / 255.0
                        b = int(hex_color[4:6], 16) / 255.0
                        
                        # Create surface style for this color
                        colour_rgb = ifc_file.createIfcColourRgb(None, r, g, b)
                        surface_style_rendering = ifc_file.createIfcSurfaceStyleRendering(
                            colour_rgb, 0.0, None, None, None, None, None, None, "FLAT"
                        )
                        surface_style = ifc_file.createIfcSurfaceStyle(
                            svg_color, "BOTH", [surface_style_rendering]
                        )
                        
                        # Apply style to each solid in this color group
                        for svg_solid in svg_solids:
                            styled_item = ifc_file.createIfcStyledItem(
                                svg_solid,
                                [ifc_file.createIfcPresentationStyleAssignment([surface_style])],
                                None
                            )
                        
                        print(f"[COLOR] Applied color {svg_color} to {len(svg_solids)} SVG shapes")
                        
                    except Exception as e:
                        print(f"[SIGN] Warning: Failed to apply color {svg_color}: {e}")
                        continue
                
                # Add all SVG solids to the main element's representation
                all_svg_solids = [solid for solid, _ in svg_shapes_with_colors]
                
                # Create a new shape representation that includes both main solids and SVG solids
                combined_solids = solids + all_svg_solids
                combined_shape_rep = ifc_file.createIfcShapeRepresentation(
                    context,
                    "Body",
                    "SweptSolid",
                    combined_solids
                )
                
                combined_product_shape = ifc_file.createIfcProductDefinitionShape(
                    None,
                    None,
                    [combined_shape_rep]
                )
                
                sign_element.Representation = combined_product_shape
            
            print(f"[PUBLIC LIGHT]   ✅ Sign created successfully with {len(solids)} base parts + {len(svg_shapes_with_colors)} colored graphics")
            
            return sign_element
        
        # === FIXTURE ARM (only for lights, not signs) ===
        arm_length = fixture_config.get('armLength', 0) / 1000  # mm to m
        arm_angle = fixture_config.get('armAngle', 0)  # degrees (downward angle from horizontal)
        arm_diameter = fixture_config.get('armDiameter', 60) / 1000  # mm to m
        
        print(f"[PUBLIC LIGHT]   Fixture arm: length={arm_length*1000:.0f}mm, angle={arm_angle}deg, diameter={arm_diameter*1000:.0f}mm")
        
        # Variables to track arm end position for fixture placement
        arm_end_x = pos_x
        arm_end_y = pos_y
        arm_end_z = pos_z + pole_height
        
        if arm_length > 0.001:
            arm_angle_rad = math.radians(arm_angle)
            
            # Arm starts at top of pole (in IFC Z-up coordinates)
            arm_start_z = pos_z + pole_height
            
            # Calculate horizontal and vertical components
            # arm_angle is the downward angle from horizontal
            horizontal_component = arm_length * math.cos(arm_angle_rad)
            vertical_component = arm_length * math.sin(arm_angle_rad)  # Positive = downward
            
            # Arm direction in IFC coordinates (X=east, Y=north, Z=up)
            # rotation is around the vertical axis (Three.js Y, IFC Z)
            arm_dir_x = math.cos(rotation) * math.cos(arm_angle_rad)
            arm_dir_y = math.sin(rotation) * math.cos(arm_angle_rad)
            arm_dir_z = -math.sin(arm_angle_rad)  # Negative because angle is downward
            
            # Normalize direction
            arm_dir_len = math.sqrt(arm_dir_x**2 + arm_dir_y**2 + arm_dir_z**2)
            if arm_dir_len > 0.001:
                arm_dir_x /= arm_dir_len
                arm_dir_y /= arm_dir_len
                arm_dir_z /= arm_dir_len
            
            # Calculate arm end position
            arm_end_x = pos_x + arm_dir_x * arm_length
            arm_end_y = pos_y + arm_dir_y * arm_length
            arm_end_z = arm_start_z + arm_dir_z * arm_length
            
            print(f"[PUBLIC LIGHT]   Arm direction: ({arm_dir_x:.3f}, {arm_dir_y:.3f}, {arm_dir_z:.3f})")
            print(f"[PUBLIC LIGHT]   Arm end position: ({arm_end_x:.3f}, {arm_end_y:.3f}, {arm_end_z:.3f})")
            
            arm_profile = ifc_file.createIfcCircleProfileDef(
                "AREA",
                None,
                ifc_file.createIfcAxis2Placement2D(
                    ifc_file.createIfcCartesianPoint((0.0, 0.0)),
                    None
                ),
                arm_diameter / 2
            )
            
            # Calculate reference direction perpendicular to arm (for profile orientation)
            if abs(arm_dir_z) < 0.9:
                ref_x = -arm_dir_y
                ref_y = arm_dir_x
                ref_z = 0.0
            else:
                ref_x = 1.0
                ref_y = 0.0
                ref_z = 0.0
            
            ref_len = math.sqrt(ref_x**2 + ref_y**2 + ref_z**2)
            if ref_len > 0.001:
                ref_x /= ref_len
                ref_y /= ref_len
                ref_z /= ref_len
            
            arm_placement = ifc_file.createIfcAxis2Placement3D(
                ifc_file.createIfcCartesianPoint((pos_x, pos_y, arm_start_z)),
                ifc_file.createIfcDirection((arm_dir_x, arm_dir_y, arm_dir_z)),
                ifc_file.createIfcDirection((ref_x, ref_y, ref_z))
            )
            
            arm_solid = ifc_file.createIfcExtrudedAreaSolid(
                arm_profile,
                arm_placement,
                ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                arm_length
            )
            solids.append(arm_solid)
            print(f"[PUBLIC LIGHT]   Added arm geometry")
        
        # === FIXTURE HOUSING ===
        fixture_style = fixture_config.get('style', 'shoebox')
        fixture_count = fixture_config.get('fixtureCount', 1)
        fixture_spacing = fixture_config.get('fixtureSpacing', 0) / 1000  # mm to m
        dimensions = fixture_config.get('dimensions', {'width': 600, 'height': 300, 'depth': 400})
        housing_color = fixture_config.get('housingColor', '#404040')
        
        fixture_width = dimensions.get('width', 600) / 1000  # mm to m
        fixture_height = dimensions.get('height', 300) / 1000  # mm to m
        fixture_depth = dimensions.get('depth', 400) / 1000  # mm to m
        
        print(f"[PUBLIC LIGHT]   Fixture: style={fixture_style}, count={fixture_count}, dims=({fixture_width*1000:.0f}x{fixture_height*1000:.0f}x{fixture_depth*1000:.0f})mm")
        
        for i in range(fixture_count):
            # Calculate fixture position - at end of arm, or on top of pole
            fixture_x = arm_end_x + math.cos(rotation) * fixture_spacing * i
            fixture_y = arm_end_y + math.sin(rotation) * fixture_spacing * i
            
            print(f"[PUBLIC LIGHT]   Fixture {i+1} at ({fixture_x:.3f}, {fixture_y:.3f}), style={fixture_style}")
            
            if fixture_style == 'post-top':
                # Post-top: Globe/sphere on top of pole with base cap
                # Matches Three.js: SphereGeometry for globe, CylinderGeometry for cap
                
                globe_radius = fixture_width / 2
                cap_height = globe_radius * 0.3
                
                print(f"[PUBLIC LIGHT]   Post-top globe: radius={globe_radius*1000:.0f}mm")
                
                # 1. Base cap (tapered cylinder below globe)
                cap_bottom_radius = globe_radius * 1.1
                cap_top_radius = globe_radius * 0.8
                cap_avg_radius = (cap_bottom_radius + cap_top_radius) / 2
                
                cap_profile = ifc_file.createIfcCircleProfileDef(
                    "AREA", None,
                    ifc_file.createIfcAxis2Placement2D(
                        ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                    ),
                    cap_avg_radius
                )
                cap_placement = ifc_file.createIfcAxis2Placement3D(
                    ifc_file.createIfcCartesianPoint((fixture_x, fixture_y, arm_end_z)),
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                )
                cap_solid = ifc_file.createIfcExtrudedAreaSolid(
                    cap_profile, cap_placement,
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    cap_height
                )
                solids.append(cap_solid)
                
                # 2. Globe (sphere approximated as stacked discs)
                globe_base_z = arm_end_z + cap_height
                sphere_segments = 8
                segment_height = (globe_radius * 2) / sphere_segments
                
                for seg in range(sphere_segments):
                    # Sphere profile - radius varies as circle cross-section
                    t = (seg + 0.5) / sphere_segments  # 0 to 1
                    # Sphere radius at height h: r = sqrt(R^2 - (h-R)^2)
                    h = t * globe_radius * 2  # Height from bottom of sphere
                    dist_from_center = abs(h - globe_radius)
                    if dist_from_center < globe_radius:
                        seg_radius = math.sqrt(globe_radius**2 - dist_from_center**2)
                    else:
                        seg_radius = globe_radius * 0.1
                    
                    seg_profile = ifc_file.createIfcCircleProfileDef(
                        "AREA", None,
                        ifc_file.createIfcAxis2Placement2D(
                            ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                        ),
                        max(seg_radius, 0.01)
                    )
                    seg_placement = ifc_file.createIfcAxis2Placement3D(
                        ifc_file.createIfcCartesianPoint((fixture_x, fixture_y, globe_base_z + seg * segment_height)),
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                    )
                    seg_solid = ifc_file.createIfcExtrudedAreaSolid(
                        seg_profile, seg_placement,
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        segment_height * 1.05
                    )
                    solids.append(seg_solid)
                
                print(f"[PUBLIC LIGHT]   Added post-top geometry (cap + globe sphere)")
                
            elif fixture_style == 'decorative-lantern':
                # Decorative lantern: hexagonal body, cone roof, finial, bottom cap
                # Matches Three.js geometry
                
                lantern_base_z = arm_end_z
                body_height = fixture_height * 0.7
                roof_height = fixture_height * 0.25
                finial_radius = fixture_width * 0.08
                bottom_cap_height = fixture_height * 0.1
                
                body_radius = fixture_width / 2
                body_top_radius = body_radius * 0.9
                roof_radius = body_radius * 1.2
                
                print(f"[PUBLIC LIGHT]   Lantern body: height={body_height*1000:.0f}mm, radius={body_radius*1000:.0f}mm")
                
                # 1. Bottom cap (tapered cylinder)
                bottom_cap_profile = ifc_file.createIfcCircleProfileDef(
                    "AREA", None,
                    ifc_file.createIfcAxis2Placement2D(
                        ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                    ),
                    body_radius * 0.6
                )
                bottom_cap_placement = ifc_file.createIfcAxis2Placement3D(
                    ifc_file.createIfcCartesianPoint((fixture_x, fixture_y, lantern_base_z)),
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                )
                bottom_cap_solid = ifc_file.createIfcExtrudedAreaSolid(
                    bottom_cap_profile, bottom_cap_placement,
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    bottom_cap_height
                )
                solids.append(bottom_cap_solid)
                
                # 2. Lantern body (hexagonal - use 6-sided polygon)
                hex_radius = body_radius
                hex_points = []
                for h in range(6):
                    hex_angle = (h / 6) * 2 * math.pi
                    hx = hex_radius * math.cos(hex_angle)
                    hy = hex_radius * math.sin(hex_angle)
                    hex_points.append(ifc_file.createIfcCartesianPoint((hx, hy)))
                hex_points.append(hex_points[0])  # Close polygon
                
                hex_polyline = ifc_file.createIfcPolyline(hex_points)
                body_profile = ifc_file.createIfcArbitraryClosedProfileDef(
                    "AREA", None, hex_polyline
                )
                body_placement = ifc_file.createIfcAxis2Placement3D(
                    ifc_file.createIfcCartesianPoint((fixture_x, fixture_y, lantern_base_z + bottom_cap_height)),
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                )
                body_solid = ifc_file.createIfcExtrudedAreaSolid(
                    body_profile, body_placement,
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    body_height
                )
                solids.append(body_solid)
                
                # 3. Conical roof (tapers from wide base to narrow top)
                cone_base_z = lantern_base_z + bottom_cap_height + body_height
                cone_segments = 5
                segment_height = roof_height / cone_segments
                
                for seg in range(cone_segments):
                    t = seg / cone_segments
                    seg_radius = roof_radius * (1 - t * 0.85)  # Taper to 15% at top
                    
                    seg_profile = ifc_file.createIfcCircleProfileDef(
                        "AREA", None,
                        ifc_file.createIfcAxis2Placement2D(
                            ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                        ),
                        seg_radius
                    )
                    seg_placement = ifc_file.createIfcAxis2Placement3D(
                        ifc_file.createIfcCartesianPoint((fixture_x, fixture_y, cone_base_z + seg * segment_height)),
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                    )
                    seg_solid = ifc_file.createIfcExtrudedAreaSolid(
                        seg_profile, seg_placement,
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        segment_height * 1.1
                    )
                    solids.append(seg_solid)
                
                # 4. Finial ball on top
                finial_base_z = cone_base_z + roof_height
                ball_segments = 4
                ball_segment_height = (finial_radius * 2) / ball_segments
                
                for seg in range(ball_segments):
                    t = (seg + 0.5) / ball_segments
                    sphere_factor = math.sin(t * math.pi)
                    seg_radius = finial_radius * max(0.3, sphere_factor)
                    
                    seg_profile = ifc_file.createIfcCircleProfileDef(
                        "AREA", None,
                        ifc_file.createIfcAxis2Placement2D(
                            ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                        ),
                        seg_radius
                    )
                    seg_placement = ifc_file.createIfcAxis2Placement3D(
                        ifc_file.createIfcCartesianPoint((fixture_x, fixture_y, finial_base_z + seg * ball_segment_height)),
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        ifc_file.createIfcDirection((1.0, 0.0, 0.0))
                    )
                    seg_solid = ifc_file.createIfcExtrudedAreaSolid(
                        seg_profile, seg_placement,
                        ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                        ball_segment_height * 1.1
                    )
                    solids.append(seg_solid)
                
                print(f"[PUBLIC LIGHT]   Added decorative lantern geometry (bottom cap + hex body + cone roof + finial)")
                
            elif fixture_style == 'flood':
                # Flood light - rectangular box angled downward (simplified as box for now)
                fixture_z = arm_end_z - fixture_height
                
                fixture_profile = ifc_file.createIfcRectangleProfileDef(
                    "AREA", None,
                    ifc_file.createIfcAxis2Placement2D(
                        ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                    ),
                    fixture_width,
                    fixture_depth
                )
                fixture_placement = ifc_file.createIfcAxis2Placement3D(
                    ifc_file.createIfcCartesianPoint((fixture_x, fixture_y, fixture_z)),
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    ifc_file.createIfcDirection((math.cos(rotation), math.sin(rotation), 0.0))
                )
                fixture_solid = ifc_file.createIfcExtrudedAreaSolid(
                    fixture_profile, fixture_placement,
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    fixture_height
                )
                solids.append(fixture_solid)
                print(f"[PUBLIC LIGHT]   Added flood light geometry")
                
            else:
                # Default shoebox style - rectangular box hanging below arm
                fixture_z = arm_end_z - fixture_height
                
                fixture_profile = ifc_file.createIfcRectangleProfileDef(
                    "AREA", None,
                    ifc_file.createIfcAxis2Placement2D(
                        ifc_file.createIfcCartesianPoint((0.0, 0.0)), None
                    ),
                    fixture_width,
                    fixture_depth
                )
                fixture_placement = ifc_file.createIfcAxis2Placement3D(
                    ifc_file.createIfcCartesianPoint((fixture_x, fixture_y, fixture_z)),
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    ifc_file.createIfcDirection((math.cos(rotation), math.sin(rotation), 0.0))
                )
                fixture_solid = ifc_file.createIfcExtrudedAreaSolid(
                    fixture_profile, fixture_placement,
                    ifc_file.createIfcDirection((0.0, 0.0, 1.0)),
                    fixture_height
                )
                solids.append(fixture_solid)
                print(f"[PUBLIC LIGHT]   Added shoebox geometry")
        
        # Create the IFC element - use IfcLightFixture
        light_element = ifc_run(
            "root.create_entity",
            file=ifc_file,
            ifc_class="IfcLightFixture",
            name=f"Public Light {reference_id}",
            predefined_type="POINTSOURCE",
        )
        
        # Set placement at origin (geometry is in absolute coordinates)
        placement_point = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
        z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
        x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
        placement = ifc_file.createIfcLocalPlacement(
            None,
            ifc_file.createIfcAxis2Placement3D(placement_point, z_dir, x_dir)
        )
        light_element.ObjectPlacement = placement
        
        # Create shape representation with all solids
        shape_rep = ifc_file.createIfcShapeRepresentation(
            context,
            "Body",
            "SweptSolid",
            solids
        )
        
        # Create product definition shape
        product_shape = ifc_file.createIfcProductDefinitionShape(
            None,
            None,
            [shape_rep]
        )
        
        # Assign representation
        light_element.Representation = product_shape
        
        # Assign to spatial container
        ifc_run(
            "spatial.assign_container",
            file=ifc_file,
            products=[light_element],
            relating_structure=storey,
        )
        
        # Apply colors to individual components using styled items
        # This allows different colors for pole, baseplate, foundation, and fixture
        
        def apply_color_to_solids(solids_list, color_hex, component_name):
            """Apply color to a list of solids using styled items"""
            if not solids_list or not color_hex:
                return
            rgb = hex_to_rgb(color_hex)
            if not rgb:
                return
            
            # Create surface style for this color
            colour_rgb = ifc_file.createIfcColourRgb(None, rgb[0], rgb[1], rgb[2])
            surface_style_rendering = ifc_file.createIfcSurfaceStyleRendering(
                colour_rgb, 0.0, None, None, None, None, None, None, "FLAT"
            )
            surface_style = ifc_file.createIfcSurfaceStyle(
                f"{component_name}_{color_hex}", "BOTH", [surface_style_rendering]
            )
            
            # Apply style to each solid
            for solid in solids_list:
                ifc_file.createIfcStyledItem(
                    solid,
                    [ifc_file.createIfcPresentationStyleAssignment([surface_style])],
                    None
                )
            print(f"[COLOR] Applied {color_hex} to {len(solids_list)} {component_name} parts")
        
        # Apply pole color
        if pole_solids and pole_color:
            apply_color_to_solids(pole_solids, pole_color, "pole")
        
        # Apply baseplate color (same as pole color for metal parts)
        if baseplate_solids and pole_color:
            apply_color_to_solids(baseplate_solids, pole_color, "baseplate")
        
        # Apply concrete color to foundation (default grey concrete)
        concrete_color = '#888888'  # Standard concrete grey
        if foundation_solids:
            apply_color_to_solids(foundation_solids, concrete_color, "foundation")
        
        # Apply housing color to fixture parts (remaining solids not in other lists)
        fixture_solids = [s for s in solids if s not in pole_solids and s not in baseplate_solids and s not in foundation_solids]
        if fixture_solids and housing_color:
            apply_color_to_solids(fixture_solids, housing_color, "fixture")
        
        print(f"[PUBLIC LIGHT]   ✅ Created successfully with {len(solids)} geometry parts")
        
        return light_element
        
    except Exception as error:
        print(f"[PUBLIC LIGHT] ❌ Error creating light {light_data.get('id', 'unknown')}: {error}")
        import traceback
        traceback.print_exc()
        return None


def export_chambers_to_ifc(
    chambers_data,
    output_path,
    project_coords=None,
    pipes_data=None,
    cable_trays_data=None,
    hangers_data=None,
    public_lights_data=None,
    light_connections_data=None,
    roads_data=None,
    coordinate_mode="absolute",
):
    """
    Export chambers, pipes, roads, public lights, and light connections to IFC file
    
    Args:
        chambers_data: List of chamber dictionaries
        output_path: Output IFC file path
        project_coords: Optional project coordinate system info
        pipes_data: Optional list of pipe dictionaries
        public_lights_data: Optional list of public light dictionaries
        light_connections_data: Optional list of light connection dictionaries
        roads_data: Optional list of road dictionaries with components
    """
    try:
        chamber_count = len(chambers_data)
        pipe_count = len(pipes_data) if pipes_data else 0
        tray_count = len(cable_trays_data) if cable_trays_data else 0
        hanger_count = len(hangers_data) if hangers_data else 0
        public_light_count = len(public_lights_data) if public_lights_data else 0
        light_connection_count = len(light_connections_data) if light_connections_data else 0
        road_count = len(roads_data) if roads_data else 0
        print(
            f"[EXPORT] Starting export with {chamber_count} chambers, {pipe_count} pipes, {tray_count} cable trays, {hanger_count} hangers, {public_light_count} public lights, {light_connection_count} light connections, and {road_count} roads"
        )

        coordinate_mode = (coordinate_mode or "absolute").lower()
        if coordinate_mode not in ("absolute", "project"):
            print(f"[EXPORT] ⚠️ Unknown coordinate_mode '{coordinate_mode}', defaulting to 'absolute'")
            coordinate_mode = "absolute"
        print(f"[EXPORT] Coordinate mode: {coordinate_mode.upper()}")

        origin_tuple = get_project_origin_tuple(project_coords)

        project_name = (project_coords or {}).get("name", DEFAULT_PROJECT_NAME)
        ifc_file, storey, context = create_ifc_file(
            project_name,
            project_coords,
            coordinate_mode=coordinate_mode,
        )

        # Export chambers
        for index, chamber in enumerate(chambers_data, start=1):
            print(
                f"[EXPORT] Adding chamber {index}/{chamber_count}: {chamber.get('name', chamber.get('id'))}"
            )
            add_chamber_to_ifc(
                ifc_file,
                storey,
                context,
                chamber,
                project_coords,
                coordinate_mode=coordinate_mode,
                origin_tuple=origin_tuple,
            )

        # Export pipes
        pipes_created = 0
        pipes_skipped = 0
        straight_count = 0
        bend_count = 0
        
        if pipes_data:
            for index, pipe in enumerate(pipes_data, start=1):
                print(f"[EXPORT] Adding pipe {index}/{pipe_count}: {pipe.get('pipeId', 'Pipe')}")
                result = add_pipe_to_ifc(
                    ifc_file,
                    storey,
                    context,
                    pipe,
                    project_coords,
                    coordinate_mode=coordinate_mode,
                    origin_tuple=origin_tuple,
                )
                if result:
                    pipes_created += 1
                    if pipe.get('isBend', False):
                        bend_count += 1
                    else:
                        straight_count += 1
                else:
                    pipes_skipped += 1
            
            print(f"\n[EXPORT] ═══ PIPE SUMMARY ═══")
            print(f"[EXPORT] Total pipes requested: {pipe_count}")
            print(f"[EXPORT] Pipes created: {pipes_created}")
            print(f"[EXPORT] Pipes skipped: {pipes_skipped}")
            print(f"[EXPORT] Breakdown: {straight_count} straights, {bend_count} bends")
            print(f"[EXPORT] ═══════════════════\n")

        # Export cable trays
        if cable_trays_data:
            for index, tray in enumerate(cable_trays_data, start=1):
                print(
                    f"[EXPORT] Adding cable tray {index}/{tray_count}: {tray.get('trayId', 'CableTray')}"
                )
                add_cable_tray_to_ifc(
                    ifc_file,
                    storey,
                    context,
                    tray,
                    project_coords,
                    coordinate_mode=coordinate_mode,
                    origin_tuple=origin_tuple,
                )

        # Export hangers
        if hangers_data:
            for index, hanger in enumerate(hangers_data, start=1):
                print(
                    f"[EXPORT] Adding hanger {index}/{hanger_count}: {hanger.get('hangerId', 'Hanger')}"
                )
                add_hanger_to_ifc(
                    ifc_file,
                    storey,
                    context,
                    hanger,
                    project_coords,
                    coordinate_mode=coordinate_mode,
                    origin_tuple=origin_tuple,
                )

        # Export public lights and signs (poles, fixtures, baseplates, foundations, sign plates)
        public_lights_created = 0
        signs_created = 0
        if public_lights_data:
            for index, light in enumerate(public_lights_data, start=1):
                light_ref = light.get('referenceId') or light.get('id', 'Light')
                element_type = light.get('type', 'light')
                type_label = 'sign' if element_type == 'sign' else 'light'
                print(
                    f"[EXPORT] Adding public {type_label} {index}/{public_light_count}: {light_ref}"
                )
                result = add_public_light_to_ifc(
                    ifc_file,
                    storey,
                    context,
                    light,
                    project_coords,
                    coordinate_mode=coordinate_mode,
                    origin_tuple=origin_tuple,
                )
                if result:
                    if element_type == 'sign':
                        signs_created += 1
                    else:
                        public_lights_created += 1
            
            print(f"\n[EXPORT] ═══ PUBLIC LIGHT/SIGN SUMMARY ═══")
            print(f"[EXPORT] Total elements requested: {public_light_count}")
            print(f"[EXPORT] Lights created: {public_lights_created}")
            print(f"[EXPORT] Signs created: {signs_created}")
            print(f"[EXPORT] ═════════════════════════════════\n")

        # Export light connections (public lighting conduits)
        light_connections_created = 0
        if light_connections_data:
            for index, connection in enumerate(light_connections_data, start=1):
                print(
                    f"[EXPORT] Adding light connection {index}/{light_connection_count}: {connection.get('connectionId', 'LightConnection')}"
                )
                result = add_light_connection_to_ifc(
                    ifc_file,
                    storey,
                    context,
                    connection,
                    project_coords,
                    coordinate_mode=coordinate_mode,
                    origin_tuple=origin_tuple,
                )
                if result:
                    light_connections_created += 1
            
            print(f"\n[EXPORT] ═══ LIGHT CONNECTION SUMMARY ═══")
            print(f"[EXPORT] Total light connections requested: {light_connection_count}")
            print(f"[EXPORT] Light connections created: {light_connections_created}")
            print(f"[EXPORT] ═══════════════════════════════\n")

        # Export roads (carriageway, kerbs, footways, bedding, haunch)
        roads_created = 0
        road_components_created = 0
        if roads_data:
            for index, road in enumerate(roads_data, start=1):
                print(
                    f"[EXPORT] Adding road {index}/{road_count}: {road.get('name', road.get('roadId', 'Road'))}"
                )
                result = add_road_to_ifc(
                    ifc_file,
                    storey,
                    context,
                    road,
                    project_coords,
                    coordinate_mode=coordinate_mode,
                    origin_tuple=origin_tuple,
                )
                if result:
                    roads_created += 1
                    road_components_created += len(result)
            
            print(f"\n[EXPORT] ═══ ROAD SUMMARY ═══")
            print(f"[EXPORT] Total roads requested: {road_count}")
            print(f"[EXPORT] Roads created: {roads_created}")
            print(f"[EXPORT] Road components created: {road_components_created}")
            print(f"[EXPORT] ═════════════════════\n")

        print(f"[EXPORT] Writing IFC to {output_path}")
        ifc_file.write(output_path)
        print("[EXPORT] ✅ Export complete!")

        return {
            "success": True,
            "file": output_path,
            "chambers_count": chamber_count,
            "pipes_count": pipe_count,
            "cable_trays_count": tray_count,
            "hangers_count": hanger_count,
            "public_lights_count": public_light_count,
            "light_connections_count": light_connection_count,
            "roads_count": road_count,
            "road_components_count": road_components_created,
        }

    except Exception as error:
        print(f"[EXPORT] ❌ ERROR: {error}")
        import traceback

        traceback.print_exc()
        return {
            "success": False,
            "error": str(error),
        }

def create_blank_ifc_at_origin(output_path, project_name="InfraGrid3D Project"):
    """
    Create a blank IFC file at origin (0, 0, 0) with proper georeferencing.
    This is used to establish the coordinate system for the project.
    
    Args:
        output_path: Path where the IFC file should be saved
        project_name: Name of the project
    
    Returns:
        dict: Result with success status and message
    """
    try:
        print(f"[BLANK IFC] Creating blank IFC file at origin (0, 0, 0)")
        print(f"[BLANK IFC] Project name: {project_name}")
        print(f"[BLANK IFC] Output path: {output_path}")
        
        # Create project coordinates at origin
        project_coords = {
            "name": project_name,
            "origin": {"x": 0.0, "y": 0.0, "z": 0.0},
            "unit": "meters"
        }
        
        # Create IFC file with proper hierarchy
        # Note: create_ifc_file returns (ifc_file, storey, body_context) and already:
        # - Creates Project, Site, Building, Storey hierarchy
        # - Applies units
        # - Applies georeferencing
        # - Sets up contexts
        ifc_file, storey, body_context = create_ifc_file(project_name, project_coords)
        
        # Write the IFC file
        ifc_file.write(output_path)
        
        print(f"[BLANK IFC] ✅ Successfully created blank IFC file at origin")
        print(f"[BLANK IFC]    Georeferencing: (0.0, 0.0, 0.0)")
        print(f"[BLANK IFC]    File saved to: {output_path}")
        
        return {
            "success": True,
            "message": "Blank IFC file created successfully at origin (0, 0, 0)",
            "origin": {"x": 0.0, "y": 0.0, "z": 0.0}
        }
        
    except Exception as error:
        print(f"[BLANK IFC] ❌ Error creating blank IFC: {error}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(error)
        }

def main():
    """Main entry point for CLI usage"""
    if len(sys.argv) < 2:
        print("Usage: python export-ifc.py <input_json> [output_ifc]", file=sys.stderr)
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "export.ifc"
    
    # Read input JSON
    with open(input_file, 'r') as f:
        data = json.load(f)
    
    chambers = data.get("chambers", [])
    project_coords = data.get("project", {})
    
    # Export
    result = export_chambers_to_ifc(chambers, output_file, project_coords)
    
    # Output result as JSON
    print(json.dumps(result))
    
    sys.exit(0 if result["success"] else 1)

if __name__ == "__main__":
    main()
