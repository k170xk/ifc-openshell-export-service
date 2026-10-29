from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS
import ifcopenshell
import gzip
import io
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
import multiprocessing
import shutil
spec = importlib.util.spec_from_file_location("export_ifc", os.path.join(os.path.dirname(__file__), 'scripts', 'export-ifc.py'))
export_ifc_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_ifc_module)
export_dwg_lines_to_ifc = export_ifc_module.export_dwg_lines_to_ifc
create_blank_ifc_at_origin = export_ifc_module.create_blank_ifc_at_origin
export_chambers_to_ifc = export_ifc_module.export_chambers_to_ifc
add_light_connection_to_ifc = export_ifc_module.add_light_connection_to_ifc
import export_worker

app = Flask(__name__)
CORS(app, expose_headers=["X-Export-Id", "X-Export-Skipped-Count", "X-Export-Skipped", "X-Export-Timing"])
# Large sites (tens of km of roads) post hundreds of MB of JSON, gzip'd to a fraction. No Flask cap.
app.config["MAX_CONTENT_LENGTH"] = None

# In-memory progress store (keyed by export_id)
export_progress = {}
export_lock = threading.Lock()

GZIP_MAGIC = b"\x1f\x8b"

# One IFC build peaks near 1 GB on a large site; two at once on the 2 GB box is
# an OOM kill for both. Later requests wait their turn instead.
EXPORT_CONCURRENCY = max(1, int(os.environ.get("EXPORT_CONCURRENCY", "1")))
export_slots = threading.BoundedSemaphore(EXPORT_CONCURRENCY)
export_queue_lock = threading.Lock()
export_queue_waiting = 0
# Spawn, not fork: the server is multi-threaded and a forked child can inherit held locks.
export_mp = multiprocessing.get_context("spawn")
SKIPPED_HEADER_LIMIT = 3500


def remove_files_after_response(response, *paths):
    def cleanup():
        for path in paths:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError as e:
                    print(f"[API] Warning: could not remove {path}: {e}")
    response.call_on_close(cleanup)
    return response


def read_json_body():
    """Read the request body as JSON, transparently decompressing gzip.

    The app sends `Content-Encoding: gzip`; the magic-byte sniff also covers a
    proxy that strips the header, and plain JSON from older clients.
    """
    raw = request.get_data(cache=False)
    if not raw:
        return None
    encoding = (request.headers.get("Content-Encoding") or "").lower()
    if raw[:2] == GZIP_MAGIC or "gzip" in encoding:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            data = json.load(gz)
    else:
        data = json.loads(raw)
    del raw
    return data


@app.route("/health")
def health():
    # Capability flags let the app pick an upload path the deployed build understands.
    return jsonify({"status": "healthy", "gzipUpload": True}), 200

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
        
        response = send_file(
            temp_path,
            mimetype="application/x-step",
            as_attachment=True,
            download_name="scheme_lines.ifc"
        )
        return remove_files_after_response(response, temp_path)
    
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
        return remove_files_after_response(response, temp_path)
    
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
    now = time.time()
    with export_lock:
        export_progress[export_id] = {
            **progress_data,
            "timestamp": now
        }
        if len(export_progress) > 200:
            stale = [key for key, value in export_progress.items() if now - value.get("timestamp", 0) > 3 * 3600]
            for key in stale:
                del export_progress[key]

@app.route("/api/export-progress/<export_id>", methods=["GET"])
def get_export_progress(export_id):
    """Server-Sent Events endpoint for export progress"""
    def generate():
        last_timestamp = 0
        start_time = time.time()
        last_sent = start_time
        # Large exports run for many minutes; Render's edge allows 100 min per request.
        timeout = 100 * 60
        keepalive_every = 15
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
                        last_sent = time.time()
                        yield f"data: {json.dumps(progress)}\n\n"
                        
                        # Stop if complete or error
                        if progress.get("type") in ("complete", "error"):
                            break
                    elif time.time() - last_sent > keepalive_every:
                        # Proxies drop idle streams; re-send the current step as a heartbeat.
                        last_sent = time.time()
                        yield f"data: {json.dumps({**progress, 'keepalive': True})}\n\n"
                else:
                    # Send initial message if no progress yet
                    if last_timestamp == 0:
                        yield f"data: {json.dumps({'type': 'start', 'message': 'Waiting for export payload...', 'progress': 0})}\n\n"
                
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
    """Export chambers, pipes, roads, drainage, site meshes and the rest to one IFC file.

    The body is the app's export payload (JSON, usually gzip'd). The build runs
    in a child process (scripts/export_worker.py); this thread only stores the
    upload, waits for a free slot, relays progress and streams the result.

    Response headers:
        X-Export-Skipped-Count / X-Export-Skipped: elements left out because
        they could not be built (the rest of the model is still exported).
        X-Export-Timing: seconds spent receiving, queued, building.
    """
    global export_queue_waiting
    input_path = None
    output_path = None
    gz_path = None
    export_id = request.headers.get("X-Export-Id") or str(uuid.uuid4())
    started = time.time()
    try:
        update_progress(export_id, {
            "type": "progress",
            "message": "Reading export payload...",
            "progress": 2,
        })

        input_fd, input_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(input_fd, "wb") as fh:
            shutil.copyfileobj(request.stream, fh, 1024 * 1024)
        received_bytes = os.path.getsize(input_path)
        if received_bytes == 0:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400
        received_at = time.time()
        print(f"[API] Export {export_id}: received {received_bytes / 1e6:.1f} MB in {received_at - started:.1f}s")
        sys.stdout.flush()

        with export_queue_lock:
            export_queue_waiting += 1
            ahead = export_queue_waiting - 1
        try:
            while not export_slots.acquire(timeout=2):
                with export_queue_lock:
                    ahead = max(export_queue_waiting - 1, 1)
                update_progress(export_id, {
                    "type": "progress",
                    "step": "queued",
                    "message": f"Waiting for {ahead} other export(s) to finish...",
                    "progress": 3,
                })
        finally:
            with export_queue_lock:
                export_queue_waiting -= 1

        try:
            slot_at = time.time()
            output_fd, output_path = tempfile.mkstemp(suffix=".ifc")
            os.close(output_fd)

            update_progress(export_id, {
                "type": "progress",
                "message": "Creating IFC file...",
                "progress": 5,
            })

            parent_conn, child_conn = export_mp.Pipe(duplex=False)
            proc = export_mp.Process(
                target=export_worker.run_export,
                args=(input_path, output_path, child_conn),
                daemon=True,
            )
            proc.start()
            child_conn.close()

            result = None
            while result is None:
                if parent_conn.poll(1.0):
                    try:
                        message = parent_conn.recv()
                    except EOFError:
                        break
                    if message[0] == "progress":
                        _, step, current, total, text = message
                        update_progress(export_id, {
                            "type": "progress",
                            "step": step,
                            "message": text,
                            "current": current,
                            "total": total,
                            "progress": int(5 + (current / total) * 90) if total else 5,
                        })
                    elif message[0] == "result":
                        result = message[1]
                elif not proc.is_alive():
                    break
            proc.join(timeout=30)
            if proc.is_alive():
                proc.kill()
            parent_conn.close()
        finally:
            export_slots.release()

        built_at = time.time()
        timing = f"receive={received_at - started:.1f};queue={slot_at - received_at:.1f};build={built_at - slot_at:.1f}"
        print(f"[API] Export {export_id}: {timing} exit={proc.exitcode}")
        sys.stdout.flush()

        if result is None:
            if proc.exitcode is not None and proc.exitcode < 0:
                error = (
                    f"The IFC build process was stopped by the server (signal {-proc.exitcode}), "
                    "usually because it ran out of memory. Export the model in smaller parts."
                )
            else:
                error = f"The IFC build process ended without a result (exit code {proc.exitcode})."
            result = {"success": False, "error": error}

        if not result.get("success"):
            update_progress(export_id, {
                "type": "error",
                "message": result.get("error", "Export failed"),
                "progress": 0,
            })
            return jsonify(result), 500

        gz_path = result.get("gzipPath")
        accepts_gzip = "gzip" in (request.headers.get("Accept-Encoding") or "").lower()
        if gz_path and accepts_gzip and os.path.exists(gz_path):
            response = send_file(gz_path, mimetype="application/x-step", as_attachment=True, download_name="export.ifc")
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Vary"] = "Accept-Encoding"
        else:
            response = send_file(output_path, mimetype="application/x-step", as_attachment=True, download_name="export.ifc")

        skipped = result.get("skipped") or []
        response.headers["X-Export-Id"] = export_id
        response.headers["X-Export-Timing"] = timing
        response.headers["X-Export-Skipped-Count"] = str(len(skipped))
        if skipped:
            listed = []
            for item in skipped:
                listed.append({"kind": item.get("kind"), "name": item.get("name")})
                if len(json.dumps(listed, ensure_ascii=True)) > SKIPPED_HEADER_LIMIT:
                    listed.pop()
                    break
            response.headers["X-Export-Skipped"] = json.dumps(listed, ensure_ascii=True)

        update_progress(export_id, {
            "type": "complete",
            "message": "Download starting...",
            "progress": 100,
        })
        return remove_files_after_response(response, output_path, gz_path)

    except Exception as e:
        for path in (input_path, output_path, gz_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
        update_progress(export_id, {
            "type": "error",
            "message": str(e),
            "progress": 0,
        })
        print(f"[API] Error in export-chambers endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if input_path and os.path.exists(input_path):
            try:
                os.unlink(input_path)
            except OSError:
                pass

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5001))
    app.run(host="0.0.0.0", port=port, debug=False)




