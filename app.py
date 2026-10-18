import os
import json
import uuid
import socket
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, send_file

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data.json"
VIDEOS_DIR = BASE_DIR / "videos"

app = Flask(__name__, static_folder=str(BASE_DIR))
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # Support video uploads up to 500 MB

# ── HELPER FUNCTIONS ──────────────────────────────────────────────────────────

def load_data():
    if not DATA_FILE.exists():
        default_data = {
            "categories": {
                "ash": [
                    {"id": "static", "name": "STATIC"},
                    {"id": "fresh-frozen", "name": "FROZEN"},
                    {"id": "dry-sift", "name": "DRY SIFT"},
                    {"id": "mousse", "name": "MOUSSE"},
                    {"id": "work", "name": "WORKLINE"}
                ],
                "weed": []
            },
            "products": []
        }
        save_data(default_data)
        return default_data
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

ADMIN_PASSWORDS = {"topshelf03", "milano03", "tpmilano03", os.environ.get("ADMIN_PASSWORD", "topshelf03")}

def is_authorized(req):
    pass_header = req.headers.get("X-Admin-Password") or req.args.get("pass")
    if pass_header in ADMIN_PASSWORDS:
        return True
    # If on localhost, allow development
    client_ip = req.remote_addr
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return True
    return False

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# ── FRONTEND ROUTES ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file(BASE_DIR / "index.html")

@app.route("/admin")
def admin():
    return send_file(BASE_DIR / "admin.html")

@app.route("/videos/<path:filepath>")
def serve_video(filepath):
    # Support range requests automatically handled by send_from_directory
    return send_from_directory(str(VIDEOS_DIR), filepath, conditional=True)

@app.route("/<path:filename>")
def serve_root_file(filename):
    file_path = BASE_DIR / filename
    if file_path.exists() and file_path.is_file():
        return send_from_directory(str(BASE_DIR), filename)
    return jsonify({"error": "File not found"}), 404

# ── API ROUTES ────────────────────────────────────────────────────────────────

@app.route("/api/data", methods=["GET"])
def api_get_data():
    return jsonify(load_data())

@app.route("/api/upload", methods=["POST"])
def api_upload_video():
    """Uploads a video file directly from the browser"""
    if "video" not in request.files:
        return jsonify({"error": "Nessun file video fornito"}), 400
    
    file = request.files["video"]
    if file.filename == "":
        return jsonify({"error": "Nome file non valido"}), 400

    category = request.form.get("category", "ash").lower()
    subcategory = request.form.get("subcategory", "").lower()

    # Determine destination folder
    if category == "ash" and subcategory:
        dest_folder = VIDEOS_DIR / "ash" / subcategory
    elif category == "weed":
        dest_folder = VIDEOS_DIR / "weed"
    else:
        dest_folder = VIDEOS_DIR / category

    dest_folder.mkdir(parents=True, exist_ok=True)

    # Clean filename
    clean_name = Path(file.filename).name
    target_path = dest_folder / clean_name
    
    # Save file
    file.save(str(target_path))

    # Return relative path using forward slashes for HTML video src
    rel_path = target_path.relative_to(BASE_DIR).as_posix()
    return jsonify({"success": True, "path": rel_path, "filename": clean_name})

@app.route("/api/products", methods=["POST"])
def api_create_product():
    data = load_data()
    
    # Check if this is multipart form data with a new video upload
    if "video_file" in request.files and request.files["video_file"].filename != "":
        vfile = request.files["video_file"]
        category = request.form.get("category", "ash").lower()
        subcategory = request.form.get("subcategory", "").lower()
        strain = request.form.get("strain", "").strip()
        tag = request.form.get("tag", "").strip()

        if category == "ash" and subcategory:
            dest_folder = VIDEOS_DIR / "ash" / subcategory
        elif category == "weed":
            dest_folder = VIDEOS_DIR / "weed"
        else:
            dest_folder = VIDEOS_DIR / category
            
        dest_folder.mkdir(parents=True, exist_ok=True)
        target_path = dest_folder / Path(vfile.filename).name
        vfile.save(str(target_path))
        video_rel = target_path.relative_to(BASE_DIR).as_posix()
    else:
        # JSON body or form with existing video path
        req_json = request.get_json(silent=True) or request.form.to_dict()
        category = req_json.get("category", "ash").lower()
        subcategory = req_json.get("subcategory", "").lower()
        strain = req_json.get("strain", "").strip()
        tag = req_json.get("tag", "").strip()
        video_rel = req_json.get("video", "").strip()

    if not strain:
        return jsonify({"error": "Il nome dello strain è obbligatorio"}), 400

    new_prod = {
        "id": "prod_" + uuid.uuid4().hex[:8],
        "category": category,
        "subcategory": subcategory,
        "strain": strain,
        "tag": tag if tag else (subcategory.upper() if subcategory else "TOP SHELF"),
        "video": video_rel
    }

    data["products"].insert(0, new_prod)  # Insert on top
    save_data(data)
    return jsonify({"success": True, "product": new_prod})

@app.route("/api/products/<prod_id>", methods=["PUT"])
def api_update_product(prod_id):
    data = load_data()
    req_json = request.get_json(silent=True) or request.form.to_dict()
    
    prod = next((p for p in data["products"] if p["id"] == prod_id), None)
    if not prod:
        return jsonify({"error": "Prodotto non trovato"}), 404

    if "strain" in req_json:
        prod["strain"] = req_json["strain"].strip()
    if "category" in req_json:
        prod["category"] = req_json["category"].lower()
    if "subcategory" in req_json:
        prod["subcategory"] = req_json["subcategory"].lower()
    if "tag" in req_json:
        prod["tag"] = req_json["tag"].strip()
    if "video" in req_json:
        prod["video"] = req_json["video"].strip()

    save_data(data)
    return jsonify({"success": True, "product": prod})

@app.route("/api/products/<prod_id>", methods=["DELETE"])
def api_delete_product(prod_id):
    data = load_data()
    prod = next((p for p in data["products"] if p["id"] == prod_id), None)
    if not prod:
        return jsonify({"error": "Prodotto non trovato"}), 404

    # Optional query param delete_file=1 to remove video from disk
    delete_file = request.args.get("delete_file", "0") == "1"
    if delete_file and prod.get("video"):
        try:
            fpath = BASE_DIR / prod["video"]
            if fpath.exists() and fpath.is_file():
                fpath.unlink()
        except Exception:
            pass

    data["products"] = [p for p in data["products"] if p["id"] != prod_id]
    save_data(data)
    return jsonify({"success": True, "deleted_id": prod_id})

# ── CATEGORIES API ────────────────────────────────────────────────────────────

@app.route("/api/categories", methods=["POST"])
def api_add_subcategory():
    data = load_data()
    req_json = request.get_json(silent=True) or request.form.to_dict()
    
    cat_type = req_json.get("type", "ash").lower()
    name = req_json.get("name", "").strip().upper()
    sub_id = req_json.get("id", "").strip().lower()

    if not name:
        return jsonify({"error": "Nome sottocategoria obbligatorio"}), 400

    if not sub_id:
        sub_id = name.lower().replace(" ", "-")

    if cat_type not in data["categories"]:
        data["categories"][cat_type] = []

    # Check duplicate
    if any(c["id"] == sub_id for c in data["categories"][cat_type]):
        return jsonify({"error": f"Sottocategoria '{sub_id}' già esistente"}), 400

    new_cat = {"id": sub_id, "name": name}
    data["categories"][cat_type].append(new_cat)
    
    # Create directory on disk
    (VIDEOS_DIR / cat_type / sub_id).mkdir(parents=True, exist_ok=True)

    save_data(data)
    return jsonify({"success": True, "category": new_cat})

@app.route("/api/categories/<cat_type>/<sub_id>", methods=["PUT"])
def api_rename_subcategory(cat_type, sub_id):
    data = load_data()
    req_json = request.get_json(silent=True) or request.form.to_dict()
    new_name = req_json.get("name", "").strip().upper()

    if not new_name:
        return jsonify({"error": "Nuovo nome non valido"}), 400

    cats = data["categories"].get(cat_type, [])
    cat = next((c for c in cats if c["id"] == sub_id), None)
    if not cat:
        return jsonify({"error": "Sottocategoria non trovata"}), 404

    cat["name"] = new_name
    save_data(data)
    return jsonify({"success": True, "category": cat})

@app.route("/api/categories/<cat_type>/<sub_id>", methods=["DELETE"])
def api_delete_subcategory(cat_type, sub_id):
    data = load_data()
    cats = data["categories"].get(cat_type, [])
    data["categories"][cat_type] = [c for c in cats if c["id"] != sub_id]
    
    # Do not delete products, but optionally leave them or reassign
    save_data(data)
    return jsonify({"success": True, "deleted_id": sub_id})

# ── AUTO-SCAN VIDEOS ON DISK ──────────────────────────────────────────────────

@app.route("/api/scan", methods=["POST"])
def api_scan_videos():
    """Scans videos folder and automatically registers any uncatalogued video file!"""
    data = load_data()
    existing_videos = {p.get("video", "").lower() for p in data["products"]}
    
    added_count = 0
    valid_extensions = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}

    for root, _, files in os.walk(VIDEOS_DIR):
        for file in files:
            ext = Path(file).suffix.lower()
            if ext in valid_extensions:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(BASE_DIR).as_posix()
                
                if rel_path.lower() not in existing_videos:
                    # Determine category and subcategory from path
                    parts = full_path.relative_to(VIDEOS_DIR).parts
                    category = "ash"
                    subcategory = "static"
                    
                    if len(parts) >= 2:
                        category = parts[0].lower()
                        subcategory = parts[1].lower()
                    elif len(parts) == 1:
                        category = parts[0].lower()
                        subcategory = ""

                    # Auto strain name: e.g. "BLACK MAGIC - YELLOW GMOZ.MP4" -> "BLACK MAGIC - YELLOW GMOZ"
                    strain_name = Path(file).stem
                    tag_name = subcategory.upper() if subcategory else category.upper()

                    new_prod = {
                        "id": "prod_" + uuid.uuid4().hex[:8],
                        "category": category,
                        "subcategory": subcategory,
                        "strain": strain_name,
                        "tag": tag_name,
                        "video": rel_path
                    }
                    data["products"].append(new_prod)
                    existing_videos.add(rel_path.lower())
                    added_count += 1

    if added_count > 0:
        save_data(data)

    return jsonify({"success": True, "added_count": added_count, "total_products": len(data["products"])})

@app.route("/api/available-videos", methods=["GET"])
def api_get_available_videos():
    """Returns all video paths found on disk"""
    valid_extensions = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
    videos = []
    for root, _, files in os.walk(VIDEOS_DIR):
        for file in files:
            if Path(file).suffix.lower() in valid_extensions:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(BASE_DIR).as_posix()
                videos.append(rel_path)
    return jsonify(videos)

if __name__ == "__main__":
    local_ip = get_local_ip()
    port = 5000
    print("=" * 60)
    print(f"🚀 TOPSHELFMI SERVER AVVIATO!")
    print(f"👉 Sito Gallery:  http://localhost:{port}")
    print(f"👉 Pannello Admin: http://localhost:{port}/admin")
    print(f"📱 Accesso Mobile (stessa rete Wi-Fi): http://{local_ip}:{port}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False)
