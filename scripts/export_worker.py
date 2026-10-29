"""Run one IFC export in a child process.

The web process only receives the upload and streams the result. IfcOpenShell
is CPU-bound and holds the GIL for the whole build, so running it on a server
thread stalled every other request (uploads, CORS preflights, progress
streams) for the length of the export. A child process also returns all of its
memory to the OS when it exits, and an out-of-memory kill or native crash ends
only this export instead of the whole service.
"""
import gzip
import importlib.util
import json
import os
import shutil
import traceback

GZIP_MAGIC = b"\x1f\x8b"
RESULT_GZIP_LEVEL = 3


def _load_export_module():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "export-ifc.py")
    spec = importlib.util.spec_from_file_location("export_ifc", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_payload(input_path):
    with open(input_path, "rb") as fh:
        head = fh.read(2)
    if head == GZIP_MAGIC:
        with gzip.open(input_path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    with open(input_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def run_export(input_path, output_path, conn):
    """Child-process entry point. Sends ("progress", ...) tuples then one ("result", dict)."""

    def send(message):
        try:
            conn.send(message)
        except Exception:
            pass

    try:
        export_module = _load_export_module()
        data = _read_payload(input_path)
        try:
            os.unlink(input_path)
        except OSError:
            pass

        def progress_callback(step, current, total, message):
            send(("progress", step, current, total, message))

        result = export_module.export_chambers_to_ifc(
            data.get("chambers", []),
            output_path,
            data.get("project", {}),
            data.get("pipes", []),
            data.get("cableTrays", []),
            data.get("hangers", []),
            public_lights_data=data.get("publicLights", []),
            light_connections_data=data.get("lightConnections", []),
            roads_data=data.get("roads", []),
            hardstandings_data=data.get("hardstandings", []),
            drainage_elements_data=data.get("drainageElements", []),
            retaining_walls_data=data.get("retainingWalls", []),
            site_mesh_elements_data=data.get("siteMeshElements", []),
            coordinate_mode=data.get("coordinateMode", "absolute"),
            progress_callback=progress_callback,
            watermain_fittings_data=data.get("watermainFittings", []),
        )
        del data

        if result.get("success") and os.path.exists(output_path):
            send(("progress", "compressing", 1, 1, "Compressing IFC file..."))
            gz_path = output_path + ".gz"
            with open(output_path, "rb") as src, gzip.open(gz_path, "wb", compresslevel=RESULT_GZIP_LEVEL) as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            result["gzipPath"] = gz_path

        send(("result", result))
    except MemoryError:
        send(("result", {
            "success": False,
            "error": "The server ran out of memory building this IFC. Export the model in smaller parts.",
        }))
    except Exception as error:
        traceback.print_exc()
        send(("result", {"success": False, "error": str(error)}))
    finally:
        try:
            conn.close()
        except Exception:
            pass
