from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS
import ifcopenshell
import json
import os
import tempfile
import sys
import threading
import uuid
import time

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
add_light_connection_to_ifc = export_ifc_module.add_light_connection_to_ifc

app = Flask(__name__)
CORS(app)

# In-memory progress store (keyed by export_id)
export_progress = {}
export_lock = threading.Lock()

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

def update_progress(export_id, progress_data):
    """Update progress for an export"""
    with export_lock:
        export_progress[export_id] = {
            **progress_data,
            "timestamp": time.time()
        }

@app.route("/api/export-progress/<export_id>", methods=["GET"])
def get_export_progress(export_id):
    """Server-Sent Events endpoint for export progress"""
    def generate():
        last_timestamp = 0
        start_time = time.time()
        timeout = 300  # 5 minute timeout
        try:
            while True:
                # Check timeout
                if time.time() - start_time > timeout:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Progress timeout - export may have failed'})}\n\n"
                    break
                
                with export_lock:
                    progress = export_progress.get(export_id)
                
                if progress:
                    # Only send if updated
                    if progress.get("timestamp", 0) > last_timestamp:
                        last_timestamp = progress.get("timestamp", 0)
                        yield f"data: {json.dumps(progress)}\n\n"
                        
                        # Stop if complete or error
                        if progress.get("type") in ("complete", "error"):
                            break
                else:
                    # Send initial message if no progress yet
                    if last_timestamp == 0:
                        yield f"data: {json.dumps({'type': 'start', 'message': 'Waiting for export to start...', 'progress': 0})}\n\n"
                
                time.sleep(0.5)  # Poll every 500ms
        except GeneratorExit:
            # Client disconnected, clean up
            pass
        except Exception as e:
            print(f"[API] Error in SSE generator: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    response = Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Cache-Control'
        }
    )
    return response

@app.route("/api/export-chambers", methods=["POST"])
def export_chambers():
    """Export chambers, pipes, cable trays, hangers, public lights, light connections, and roads to IFC file.
    
    Expected JSON payload:
    {
        "exportId": "optional-export-id",  // If provided, progress will be tracked
        "chambers": [...],
        "pipes": [...],
        "cableTrays": [...],
        "hangers": [...],
        "publicLights": [...],
        "lightConnections": [...],
        "roads": [...],
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
    export_id = None
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400
        
        # Get or generate export ID for progress tracking
        export_id = data.get("exportId") or str(uuid.uuid4())
        
        chambers = data.get("chambers", [])
        pipes = data.get("pipes", [])
        cable_trays = data.get("cableTrays", [])
        hangers = data.get("hangers", [])
        public_lights = data.get("publicLights", [])
        light_connections = data.get("lightConnections", [])
        roads = data.get("roads", [])
        project = data.get("project", {})
        coordinate_mode = data.get("coordinateMode", "absolute")
        
        total_items = len(chambers) + len(pipes) + len(cable_trays) + len(hangers) + len(public_lights) + len(light_connections) + len(roads)
        
        # Initialize progress
        update_progress(export_id, {
            "type": "start",
            "message": "Starting export...",
            "total": total_items,
            "current": 0,
            "progress": 0
        })
        
        print("=" * 70)
        print(f"[API] Export request received (ID: {export_id})")
        print(f"[API] Exporting {len(chambers)} chambers, {len(pipes)} pipes, {len(cable_trays)} cable trays, {len(hangers)} hangers, {len(public_lights)} public lights, {len(light_connections)} light connections, {len(roads)} roads")
        print("=" * 70)
        sys.stdout.flush()
        
        # Create temporary file for IFC output
        temp_fd, temp_path = tempfile.mkstemp(suffix=".ifc")
        os.close(temp_fd)
        
        update_progress(export_id, {
            "type": "progress",
            "message": "Creating IFC file...",
            "progress": 5
        })
        
        # Create progress callback
        current_step = 0
        def progress_callback(step, current, total, message):
            nonlocal current_step
            current_step = current
            progress_pct = int(5 + (current / total) * 90) if total > 0 else 5
            update_progress(export_id, {
                "type": "progress",
                "step": step,
                "message": message,
                "current": current,
                "total": total,
                "progress": progress_pct
            })
        
        # Export to IFC
        result = export_chambers_to_ifc(
            chambers,
            temp_path,
            project,
            pipes,
            cable_trays,
            hangers,
            public_lights_data=public_lights,
            light_connections_data=light_connections,
            roads_data=roads,
            coordinate_mode=coordinate_mode,
            progress_callback=progress_callback,
        )
        
        if not result.get("success"):
            # Clean up on error
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            update_progress(export_id, {
                "type": "error",
                "message": result.get("error", "Export failed"),
                "progress": 0
            })
            return jsonify(result), 500
        
        update_progress(export_id, {
            "type": "progress",
            "message": "Finalizing IFC file...",
            "progress": 95
        })
        
        # Return IFC file
        response = send_file(
            temp_path,
            mimetype="application/x-step",
            as_attachment=True,
            download_name="export.ifc",
            headers={"X-Export-Id": export_id}  # Include export ID in response
        )
        
        # Mark as complete
        update_progress(export_id, {
            "type": "complete",
            "message": "Export complete!",
            "progress": 100,
            "current": total_items,
            "total": total_items
        })
        
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
        
        if export_id:
            update_progress(export_id, {
                "type": "error",
                "message": str(e),
                "progress": 0
            })
        
        print(f"[API] Error in export-chambers endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5001))
    app.run(host="0.0.0.0", port=port, debug=False)




