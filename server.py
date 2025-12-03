from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import ifcopenshell
import json
import os
import tempfile
import sys

# Add scripts directory to path to import export-ifc module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))
# Import using importlib since the filename has a hyphen
import importlib.util
spec = importlib.util.spec_from_file_location("export_ifc", os.path.join(os.path.dirname(__file__), 'scripts', 'export-ifc.py'))
export_ifc_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_ifc_module)
export_dwg_lines_to_ifc = export_ifc_module.export_dwg_lines_to_ifc
create_blank_ifc_at_origin = export_ifc_module.create_blank_ifc_at_origin
export_chambers_to_ifc = export_ifc_module.export_chambers_to_ifc

app = Flask(__name__)
CORS(app)

@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200

@app.route("/")
def root():
    return jsonify({"service": "ifcopenshell-api", "status": "running"}), 200

@app.route("/api/version")
def version():
    return jsonify({"version": "ifcopenshell_" + ifcopenshell.version}), 200

@app.route("/api/dwg-to-ifc", methods=["POST"])
def dwg_to_ifc():
    """Convert DWG lines and polylines to IFC file.
    
    Expected JSON payload:
    {
        "connectedPaths": [
            {
                "id": "path_1",
                "vertices": [[x, y, z], [x, y, z], ...],
                "layer": "layer_name",
                "color": "#FF0000"
            }
        ],
        "connectThreshold": 0.1,
        "projectCoords": {
            "name": "Project Name",
            "origin": {"x": 0, "y": 0, "z": 0},
            "unit": "meters"
        }
    }
    
    Returns:
        IFC file as binary download
    """
    temp_path = None
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400
        
        connected_paths = data.get("connectedPaths", [])
        connect_threshold = data.get("connectThreshold", 0.1)
        project_coords = data.get("projectCoords", {})
        
        if not connected_paths:
            return jsonify({"success": False, "error": "No connected paths provided"}), 400
        
        print(f"[API] Received request to convert {len(connected_paths)} connected paths to IFC")
        print(f"[API] Connect threshold: {connect_threshold}m")
        
        # Create temporary file for IFC output
        temp_fd, temp_path = tempfile.mkstemp(suffix=".ifc")
        os.close(temp_fd)
        
        # Export to IFC
        result = export_dwg_lines_to_ifc(connected_paths, temp_path, project_coords)
        
        if not result.get("success"):
            # Clean up on error
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            return jsonify(result), 500
        
        # Return IFC file and let Flask handle cleanup
        # Note: send_file will read the file, so we can delete it after
        response = send_file(
            temp_path,
            mimetype="application/x-step",
            as_attachment=True,
            download_name="scheme_lines.ifc"
        )
        
        # Schedule cleanup after response is sent
        # Flask will handle the file deletion after send_file completes
        try:
            if temp_path and os.path.exists(temp_path):
                # Use a deferred cleanup - file will be deleted after response
                import atexit
                atexit.register(lambda: os.path.exists(temp_path) and os.unlink(temp_path))
        except Exception as e:
            print(f"[API] Warning: Failed to schedule cleanup: {e}")
        
        return response
    
    except Exception as e:
        # Clean up on exception
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass
        
        print(f"[API] Error in dwg-to-ifc endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/create-blank-ifc", methods=["POST"])
def create_blank_ifc():
    """Create a blank IFC file at origin (0, 0, 0) for coordinate system establishment.
    
    Expected JSON payload:
    {
        "projectName": "Project Name" (optional, defaults to "InfraGrid3D Project")
    }
    
    Returns:
        IFC file as binary download
    """
    temp_path = None
    try:
        data = request.get_json() or {}
        project_name = data.get("projectName", "InfraGrid3D Project")
        
        print(f"[API] Creating blank IFC at origin for project: {project_name}")
        
        # Create temporary file for IFC output
        temp_fd, temp_path = tempfile.mkstemp(suffix=".ifc")
        os.close(temp_fd)
        
        # Create blank IFC at origin
        result = create_blank_ifc_at_origin(temp_path, project_name)
        
        if not result.get("success"):
            # Clean up on error
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            return jsonify(result), 500
        
        # Return IFC file
        response = send_file(
            temp_path,
            mimetype="application/x-step",
            as_attachment=True,
            download_name="origin_reference.ifc"
        )
        
        # Schedule cleanup after response is sent
        try:
            if temp_path and os.path.exists(temp_path):
                import atexit
                atexit.register(lambda: os.path.exists(temp_path) and os.unlink(temp_path))
        except Exception as e:
            print(f"[API] Warning: Failed to schedule cleanup: {e}")
        
        return response
    
    except Exception as e:
        # Clean up on exception
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass
        
        print(f"[API] Error in create-blank-ifc endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/export-chambers", methods=["POST"])
def export_chambers():
    """Export chambers, pipes, cable trays, and hangers to IFC file.
    
    Expected JSON payload:
    {
        "chambers": [...],
        "pipes": [...],
        "cableTrays": [...],
        "hangers": [...],
        "project": {
            "name": "Project Name",
            "origin": {"x": 0, "y": 0, "z": 0},
            "unit": "meters"
        }
    }
    
    Returns:
        IFC file as binary download
    """
    temp_path = None
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400
        
        chambers = data.get("chambers", [])
        pipes = data.get("pipes", [])
        cable_trays = data.get("cableTrays", [])
        hangers = data.get("hangers", [])
        project = data.get("project", {})
        
        print(f"[API] Exporting {len(chambers)} chambers, {len(pipes)} pipes, {len(cable_trays)} cable trays, {len(hangers)} hangers")
        
        # Create temporary file for IFC output
        temp_fd, temp_path = tempfile.mkstemp(suffix=".ifc")
        os.close(temp_fd)
        
        # Export to IFC
        result = export_chambers_to_ifc(chambers, temp_path, project, pipes, cable_trays, hangers)
        
        if not result.get("success"):
            # Clean up on error
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            return jsonify(result), 500
        
        # Return IFC file
        response = send_file(
            temp_path,
            mimetype="application/x-step",
            as_attachment=True,
            download_name="export.ifc"
        )
        
        # Schedule cleanup after response is sent
        try:
            if temp_path and os.path.exists(temp_path):
                import atexit
                atexit.register(lambda: os.path.exists(temp_path) and os.unlink(temp_path))
        except Exception as e:
            print(f"[API] Warning: Failed to schedule cleanup: {e}")
        
        return response
    
    except Exception as e:
        # Clean up on exception
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass
        
        print(f"[API] Error in export-chambers endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5001))
    app.run(host="0.0.0.0", port=port, debug=False)




