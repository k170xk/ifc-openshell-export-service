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


def create_ifc_file(project_name=DEFAULT_PROJECT_NAME, project_coords=None):
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

    # Storey placement at world origin for absolute coordinate mode
    # Chambers will be placed with absolute coordinates (PlacementRelTo=None)
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

    apply_georeferencing(ifc_file, project_coords)

    return ifc_file, storey, body_context


def create_chamber_representation(ifc_file, context, width, length, height):
    axis_placement = ifc_file.createIfcAxis2Placement2D(
        ifc_file.createIfcCartesianPoint((0.0, 0.0)),
        ifc_file.createIfcDirection((1.0, 0.0)),
    )
    profile = ifc_file.createIfcRectangleProfileDef("AREA", None, axis_placement, width, length)
    depth = max(height, 0.1)
    return ifc_run(
        "geometry.add_profile_representation",
        file=ifc_file,
        context=context,
        profile=profile,
        depth=depth,
    )


def add_chamber_to_ifc(ifc_file, storey, context, chamber_data, project_coords=None):
    """Add a chamber (manhole) to the IFC file with basic geometry and placement.
    
    ABSOLUTE WORLD COORDINATE MODE:
    Chambers are placed at their absolute real-world coordinates directly.
    This provides maximum compatibility with all IFC import software.
    IfcMapConversion is included as reference information only.
    """

    position = chamber_data.get("position", {})
    width = max(chamber_data.get("width", 1.0), 0.01)
    length = max(chamber_data.get("length", 1.0), 0.01)
    cover_level = chamber_data.get("coverLevel", 0.0)
    invert_level = chamber_data.get("invertLevel", 0.0)
    chamber_height = max(cover_level - invert_level, 0.1)
    
    # ===== CODE VERSION: 2025-11-17 ABSOLUTE COORDINATES =====
    print("[CHAMBER] 🔧 Using ABSOLUTE world coordinate placement")
    
    # Chamber position in world coordinates (from app) - use directly
    world_x = position.get("x", 0.0)
    world_y = position.get("y", 0.0)
    world_z = position.get("z", 0.0)
    
    print(f"[CHAMBER] Adding chamber: {chamber_data.get('name', chamber_data.get('id'))}")
    print(f"[CHAMBER]   Absolute world position: x={world_x}, y={world_y}, z={world_z}")
    print(f"[CHAMBER]   Dimensions: width={width}m, length={length}m, height={chamber_height}m")
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
    # App: {x: easting, y: elevation at COVER level, z: northing}
    # IFC: {X: easting, Y: northing, Z: elevation at INVERT level}
    # CRITICAL: Chamber geometry origin is at bottom (invert), so place at invert level
    invert_elevation = world_y - chamber_height
    
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
    chamber_matrix[0, 3] = world_x           # X = absolute easting
    chamber_matrix[1, 3] = world_z           # Y = absolute northing (from z)
    chamber_matrix[2, 3] = invert_elevation  # Z = absolute elevation at INVERT (bottom)
    
    print(f"[CHAMBER]   Input WORLD (Y-up): x={world_x}, y={world_y} (cover), z={world_z}")
    print(f"[CHAMBER]   Cover elevation: {world_y}, Invert elevation: {invert_elevation}, Height: {chamber_height}")
    print(f"[CHAMBER]   Output WORLD (Z-up): X={chamber_matrix[0, 3]}, Y={chamber_matrix[1, 3]}, Z={chamber_matrix[2, 3]} (at invert)")
    print(f"[CHAMBER]   ✅ Placement is ABSOLUTE world coordinates")

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

    representation = create_chamber_representation(ifc_file, context, width, length, chamber_height)
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

    return chamber


def add_pipe_to_ifc(ifc_file, storey, context, pipe_data, project_coords=None):
    """Add a pipe segment to the IFC file with proper geometry and placement.
    
    Uses REAL-WORLD coordinates (same approach as chambers).
    Pipes use IfcPipeSegment with extruded circular profile.
    Based on working export from Nov 17, 2025 (commit 51d2d81)
    """
    
    # Get pipe data
    start_point = pipe_data.get("startPoint", [0, 0, 0])
    end_point = pipe_data.get("endPoint", [0, 0, 0])
    diameter = pipe_data.get("diameter", 100) / 1000  # mm to meters
    radius = diameter / 2
    
    pipe_id = pipe_data.get("pipeId", "Pipe")
    utility_type = pipe_data.get("utilityType", "")
    is_bend = pipe_data.get("isBend", False)
    points = pipe_data.get("points", None)  # For swept solids (bends)
    color_hex = pipe_data.get("color", None)  # Hex color (e.g., "#FF0000")
    
    print(f"\n[PIPE] Adding pipe: {pipe_id}")
    print(f"[PIPE]   Type: {'BEND (swept solid)' if is_bend else 'STRAIGHT (extrusion)'}")
    print(f"[PIPE]   Start (Y-up THREE.js format [x,y,z]): {start_point}")
    print(f"[PIPE]   End (Y-up THREE.js format [x,y,z]): {end_point}")
    print(f"[PIPE]   Diameter: {diameter}m")
    if is_bend and points:
        print(f"[PIPE]   Points for swept solid: {len(points)}")
    
    # Convert Y-up (Three.js) to Z-up (IFC) - SAME AS CHAMBERS
    # Input: [x=easting, y=elevation, z=northing]
    # Output: [X=easting, Y=northing, Z=elevation]
    start_ifc = [start_point[0], start_point[2], start_point[1]]
    end_ifc = [end_point[0], end_point[2], end_point[1]]
    
    print(f"[PIPE]   Start (Z-up): {start_ifc}")
    print(f"[PIPE]   End (Z-up): {end_ifc}")
    
    # Calculate direction vector and length
    direction = [
        end_ifc[0] - start_ifc[0],
        end_ifc[1] - start_ifc[1],
        end_ifc[2] - start_ifc[2]
    ]
    length = math.sqrt(sum(d * d for d in direction))
    
    if length < 0.001:
        print(f"[PIPE]   ⚠️ Skipping pipe with zero length")
        return None
    
    # Normalize direction
    direction_normalized = [d / length for d in direction]
    
    print(f"[PIPE]   Length: {length}m")
    print(f"[PIPE]   Direction: {direction_normalized}")
    
    # Determine predefined type based on utility
    utility_lower = utility_type.lower()
    if "sewer" in utility_lower or "drainage" in utility_lower or "waste" in utility_lower:
        predefined_type = "CULVERT"
    else:
        predefined_type = "RIGIDSEGMENT"
    
    # Create pipe segment
    pipe = ifc_run(
        "root.create_entity",
        file=ifc_file,
        ifc_class="IfcPipeSegment",
        name=pipe_id,
        predefined_type=predefined_type,
    )
    
    # Use IfcSweptDiskSolid for ALL segments (bends and straights)
    # This eliminates matrix transformation issues
    if points and len(points) >= 2:
        print(f"[PIPE]   Creating SWEPT SOLID with {len(points)} points ({'BEND' if is_bend else 'STRAIGHT'})")
        
        # Convert all points from Y-up to Z-up - use ABSOLUTE coordinates
        points_ifc = []
        for pt in points:
            pt_ifc = [pt[0], pt[2], pt[1]]  # [x, z, y] -> [X, Y, Z]
            points_ifc.append(pt_ifc)
        
        # Create polyline curve from ABSOLUTE points
        # IMPORTANT: IfcCartesianPoint requires tuples, not lists
        ifc_points = [ifc_file.createIfcCartesianPoint(tuple(pt)) for pt in points_ifc]
        polyline = ifc_file.createIfcPolyline(ifc_points)
        
        # Create swept disk solid (circular cross-section swept along polyline)
        swept_solid = ifc_file.createIfcSweptDiskSolid(
            polyline,  # Directrix (the path in ABSOLUTE world coordinates)
            radius,    # Radius
            None,      # InnerRadius (None for solid pipe)
            None,      # StartParam (None = start of curve)
            None       # EndParam (None = end of curve)
        )
        
        # Use identity matrix - geometry is already in world coordinates
        matrix = np.eye(4)
        
        print(f"[PIPE]   Swept solid using ABSOLUTE coordinates")
        print(f"[PIPE]   First point IFC [X,Y,Z]: {points_ifc[0]}")
        print(f"[PIPE]   Last point IFC [X,Y,Z]: {points_ifc[-1]}")
        print(f"[PIPE]   First point THREE.js [x,y,z]: {points[0]}")
        print(f"[PIPE]   Last point THREE.js [x,y,z]: {points[-1]}")
        print(f"[PIPE]   Transformation: THREE.js [x,y,z] -> IFC [x,z,y] = [X,Y,Z]")
        print(f"[PIPE]   Path length: {len(points_ifc)} points")
        
    else:
        # STRAIGHT SEGMENT: Use extruded area solid
        print(f"[PIPE]   Creating EXTRUDED SOLID for straight segment")
        
        # Create placement matrix
        # Matrix is 4x4 transformation: [rotation | translation]
        # We need to orient the local Z-axis along the pipe direction
        matrix = np.eye(4)
        
        # Z-axis = pipe direction (normalized)
        z_axis = np.array(direction_normalized)
        
        # Calculate perpendicular X-axis
        if abs(z_axis[2]) < 0.9:
            # Not primarily vertical, use world Z-up as reference
            x_axis = np.array([z_axis[1], -z_axis[0], 0])
            x_axis_len = np.linalg.norm(x_axis)
            if x_axis_len > 1e-6:
                x_axis = x_axis / x_axis_len
            else:
                x_axis = np.array([1, 0, 0])
        else:
            # Primarily vertical, use world X-axis
            x_axis = np.array([1, 0, 0])
        
        # Y-axis = Z cross X
        y_axis = np.cross(z_axis, x_axis)
        y_axis = y_axis / np.linalg.norm(y_axis)
        
        # Recalculate X to ensure orthogonality
        x_axis = np.cross(y_axis, z_axis)
        
        # Build rotation matrix
        matrix[0, 0:3] = x_axis
        matrix[1, 0:3] = y_axis
        matrix[2, 0:3] = z_axis
        
        # Translation = start point (ABSOLUTE WORLD COORDINATES)
        matrix[0, 3] = start_ifc[0]
        matrix[1, 3] = start_ifc[1]
        matrix[2, 3] = start_ifc[2]
    
    # Verification only needed if not using swept solids
    # (swept solids use absolute coordinates directly, no calculation needed)
    
    # Set placement with absolute coordinates
    if points and len(points) >= 2:
        # For swept solids with absolute coordinates, place at origin
        # The geometry itself is already in world coordinates
        origin = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
        z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
        x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
        placement = ifc_file.createIfcLocalPlacement(
            None,  # PlacementRelTo = None for absolute
            ifc_file.createIfcAxis2Placement3D(origin, z_dir, x_dir)
        )
        pipe.ObjectPlacement = placement
        print(f"[PIPE]   ✅ Placement set to ORIGIN (geometry in absolute coords)")
    else:
        # Fallback for segments without points array (shouldn't happen)
        # For extruded solids, use standard placement with transformation
        placement = ifc_run(
            "geometry.edit_object_placement",
            file=ifc_file,
            product=pipe,
            matrix=matrix,
            is_si=True,
        )
        
        # Set PlacementRelTo=None for absolute world coordinates
        if placement and hasattr(placement, 'PlacementRelTo'):
            placement.PlacementRelTo = None
            print(f"[PIPE]   ✅ Placement set to ABSOLUTE")
    
    # Create geometry based on type
    if points and len(points) >= 2:
        # ALL segments: swept_solid already created above
        solid = swept_solid
        print(f"[PIPE]   ✅ Swept disk solid created")
    else:
        # Fallback (shouldn't happen)
        # STRAIGHT: Create extruded area solid
        # Create circular profile for pipe cross-section
        # Profile is in 2D (XY plane), will be extruded along Z-axis
        profile_placement_2d = ifc_file.createIfcAxis2Placement2D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0)),
            ifc_file.createIfcDirection((1.0, 0.0))
        )
        profile = ifc_file.createIfcCircleProfileDef(
            "AREA",  # ProfileType
            None,  # ProfileName
            profile_placement_2d,
            radius
        )
        
        # Create extruded solid
        # Position is at origin (0,0,0) in local coordinates
        extrusion_placement = ifc_file.createIfcAxis2Placement3D(
            ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0)),
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),  # Extrusion direction (local Z)
            ifc_file.createIfcDirection((1.0, 0.0, 0.0))   # Reference direction (local X)
        )
        
        # Extrude along local Z-axis (which is aligned with pipe direction due to placement matrix)
        solid = ifc_file.createIfcExtrudedAreaSolid(
            profile,  # SweptArea
            extrusion_placement,  # Position
            ifc_file.createIfcDirection((0.0, 0.0, 1.0)),  # ExtrudedDirection
            length  # Depth
        )
        print(f"[PIPE]   ✅ Extruded area solid created for straight")
    
    # Create shape representation
    shape_rep = ifc_file.createIfcShapeRepresentation(
        context,  # ContextOfItems
        "Body",  # RepresentationIdentifier
        "SweptSolid",  # RepresentationType
        [solid]  # Items
    )
    
    # Create product definition shape
    product_shape = ifc_file.createIfcProductDefinitionShape(
        None,  # Name
        None,  # Description
        [shape_rep]  # Representations
    )
    
    # Assign representation to pipe
    pipe.Representation = product_shape
    
    print(f"[PIPE]   ✅ Geometry created")
    
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


def add_cable_tray_to_ifc(ifc_file, storey, context, tray_data, project_coords=None):
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
    
    # Convert Y-up to Z-up
    start_ifc = [start_point[0], start_point[2], start_point[1]]
    end_ifc = [end_point[0], end_point[2], end_point[1]]
    
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
        points_ifc = [[pt[0], pt[2], pt[1]] for pt in points]
        
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
    
    # Set placement at origin (geometry is in absolute coordinates)
    origin = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
    z_dir = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
    x_dir = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    placement = ifc_file.createIfcLocalPlacement(
        None,
        ifc_file.createIfcAxis2Placement3D(origin, z_dir, x_dir)
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


def add_hanger_to_ifc(ifc_file, storey, context, hanger_data, project_coords=None):
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
    
    # Convert Y-up to Z-up
    pos_ifc = [position[0], position[2], position[1]]
    dir_ifc = [direction[0], direction[2], direction[1]]  # Convert direction too
    
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
    print(f"[HANGER]   Position (IFC Z-up): X={pos_ifc[0]:.2f}, Y={pos_ifc[1]:.2f}, Z={pos_ifc[2]:.2f}")
    
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


def export_chambers_to_ifc(chambers_data, output_path, project_coords=None, pipes_data=None, cable_trays_data=None, hangers_data=None):
    """
    Export chambers and pipes to IFC file
    
    Args:
        chambers_data: List of chamber dictionaries
        output_path: Output IFC file path
        project_coords: Optional project coordinate system info
        pipes_data: Optional list of pipe dictionaries
    """
    try:
        chamber_count = len(chambers_data)
        pipe_count = len(pipes_data) if pipes_data else 0
        tray_count = len(cable_trays_data) if cable_trays_data else 0
        hanger_count = len(hangers_data) if hangers_data else 0
        print(f"[EXPORT] Starting export with {chamber_count} chambers, {pipe_count} pipes, {tray_count} cable trays, and {hanger_count} hangers")

        project_name = (project_coords or {}).get("name", DEFAULT_PROJECT_NAME)
        ifc_file, storey, context = create_ifc_file(project_name, project_coords)

        # Export chambers
        for index, chamber in enumerate(chambers_data, start=1):
            print(f"[EXPORT] Adding chamber {index}/{chamber_count}: {chamber.get('name', chamber.get('id'))}")
            add_chamber_to_ifc(ifc_file, storey, context, chamber, project_coords)

        # Export pipes
        if pipes_data:
            for index, pipe in enumerate(pipes_data, start=1):
                print(f"[EXPORT] Adding pipe {index}/{pipe_count}: {pipe.get('pipeId', 'Pipe')}")
                add_pipe_to_ifc(ifc_file, storey, context, pipe, project_coords)

        # Export cable trays
        if cable_trays_data:
            for index, tray in enumerate(cable_trays_data, start=1):
                print(f"[EXPORT] Adding cable tray {index}/{tray_count}: {tray.get('trayId', 'CableTray')}")
                add_cable_tray_to_ifc(ifc_file, storey, context, tray, project_coords)

        # Export hangers
        if hangers_data:
            for index, hanger in enumerate(hangers_data, start=1):
                print(f"[EXPORT] Adding hanger {index}/{hanger_count}: {hanger.get('hangerId', 'Hanger')}")
                add_hanger_to_ifc(ifc_file, storey, context, hanger, project_coords)

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
