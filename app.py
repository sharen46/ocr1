import os
import json
import time

from flask import Flask, request, render_template_string, jsonify
from werkzeug.utils import secure_filename

from receipt_extractor import extract_receipt_to_object  # object version

app = Flask(__name__)

# -------------------- CONFIG --------------------

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

STATS_FILE = os.path.join(UPLOAD_FOLDER, "stats.json")


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def load_stats():
    if not os.path.isfile(STATS_FILE):
        return {
            "total_files": 0,
            "success": 0,
            "failed": 0,
            "last_updated": None,
        }
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # ensure keys exist
            data.setdefault("total_files", 0)
            data.setdefault("success", 0)
            data.setdefault("failed", 0)
            data.setdefault("last_updated", None)
            return data
    except Exception:
        return {
            "total_files": 0,
            "success": 0,
            "failed": 0,
            "last_updated": None,
        }


def bump_stats(success: bool):
    stats = load_stats()
    stats["total_files"] += 1
    if success:
        stats["success"] += 1
    else:
        stats["failed"] += 1
    stats["last_updated"] = int(time.time())
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)


# -------------------- CORS --------------------

@app.after_request
def add_cors_headers(response):
    # allow your admin site / Yii system / Postman to call this API
    response.headers["Access-Control-Allow-Origin"] = "*"  # or specific domain
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# -------------------- UI TEMPLATE --------------------

HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <title>Receipt → JSON</title>
  <meta charset="utf-8" />
  <style>
    * { box-sizing: border-box; }

    body {
      margin: 0;
      padding: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Inter", sans-serif;
      background: radial-gradient(circle at top, #1f2937 0, #020617 60%);
      color: #e5e7eb;
      min-height: 100vh;
      display: flex;
      align-items: flex-start;
      justify-content: center;
    }

    .shell {
      width: 100%;
      max-width: 1100px;
      margin: 32px auto;
      padding: 0 16px;
    }

    .header {
      text-align: center;
      margin-bottom: 24px;
    }

    .title {
      font-size: 26px;
      font-weight: 700;
      letter-spacing: 0.03em;
    }

    .subtitle {
      font-size: 13px;
      color: #9ca3af;
      margin-top: 4px;
    }

    .layout {
      display: grid;
      grid-template-columns: minmax(0, 340px) minmax(0, 1fr);
      gap: 20px;
    }

    .card {
      background: rgba(15, 23, 42, 0.95);
      border-radius: 18px;
      padding: 18px 20px 20px;
      box-shadow: 0 18px 40px rgba(0,0,0,0.55);
      border: 1px solid rgba(148, 163, 184, 0.15);
    }

    .card h3 {
      margin: 0 0 12px;
      font-size: 16px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .badge {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 999px;
      background: rgba(59,130,246,0.15);
      color: #bfdbfe;
      border: 1px solid rgba(59,130,246,0.4);
    }

    input[type=file] {
      width: 100%;
      margin: 8px 0 10px;
      background: #020617;
      padding: 10px;
      border-radius: 10px;
      border: 1px solid #374151;
      color: #e5e7eb;
      font-size: 13px;
    }

    .hint {
      font-size: 11px;
      color: #9ca3af;
      margin-bottom: 12px;
    }

    .btn {
      width: 100%;
      background: linear-gradient(90deg, #4f46e5, #2563eb);
      border: none;
      padding: 11px 14px;
      border-radius: 999px;
      font-size: 14px;
      font-weight: 600;
      color: #f9fafb;
      cursor: pointer;
      transition: transform 0.08s ease, box-shadow 0.08s ease, opacity 0.1s ease;
      box-shadow: 0 10px 25px rgba(37,99,235,0.6);
      margin-top: 4px;
    }

    .btn:hover {
      opacity: 0.95;
      transform: translateY(-1px);
      box-shadow: 0 14px 35px rgba(37,99,235,0.75);
    }

    .btn:active {
      transform: translateY(0);
      box-shadow: 0 8px 20px rgba(37,99,235,0.5);
    }

    .error {
      color: #fecaca;
      font-size: 13px;
      margin-top: 10px;
    }

    .output-header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }

    .output-header span {
      font-size: 13px;
      color: #9ca3af;
    }

    .stats-line {
      font-size: 11px;
      color: #9ca3af;
      margin-bottom: 6px;
    }

    pre {
      margin: 0;
      background: #020617;
      padding: 14px 16px;
      border-radius: 12px;
      max-height: 480px;
      overflow: auto;
      font-size: 12px;
      line-height: 1.4;
      border: 1px solid #111827;
      font-family: "JetBrains Mono", SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      white-space: pre;
    }

    @media (max-width: 900px) {
      .layout {
        grid-template-columns: minmax(0,1fr);
      }
    }
  </style>
</head>

<body>
  <div class="shell">
    <div class="header">
      <div class="title">Receipt → JSON</div>
      <div class="subtitle">Upload one or more receipts (PDF / image) and get structured JSON output.</div>
    </div>

    <div class="layout">
      <!-- LEFT: Upload -->
      <div class="card">
        <h3>Upload Receipts <span class="badge">Step 1</span></h3>
        <form method="post" enctype="multipart/form-data">
          <input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg" multiple required>
          <div class="hint">You can select more than one file at once.</div>
          <button class="btn" type="submit">Upload & Extract</button>
        </form>

        {% if error %}
          <div class="error">{{ error }}</div>
        {% endif %}
      </div>

      <!-- RIGHT: JSON Output -->
      <div class="card">
        <div class="output-header">
          <h3>JSON Output</h3>
          {% if json_result %}
            <span>Parsed successfully ✔</span>
          {% else %}
            <span>No file processed yet.</span>
          {% endif %}
        </div>

        <div class="stats-line">
          Total: {{ stats.total_files }} | Success: {{ stats.success }} | Failed: {{ stats.failed }}
        </div>

        {% if json_result %}
          <pre>{{ json_result }}</pre>
        {% else %}
          <pre>{}</pre>
        {% endif %}
      </div>
    </div>
  </div>
</body>
</html>
"""


# -------------------- CORE FILE PROCESSOR --------------------

def process_single_file(file_storage):
    """
    Shared logic for:
      - Web UI upload
      - /api/extract (Yii, Postman, etc.)
    Returns: (result_dict, http_status)
    """
    if not file_storage or file_storage.filename == "":
        result = {
            "status": False,
            "message": "No file selected",
            "data": {},
            "status_code": 400,
        }
        # don't bump stats here; it's basically a client error without file
        return result, 400

    filename = secure_filename(file_storage.filename)
    if not allowed_file(filename):
        result = {
            "status": False,
            "message": "File type not allowed. Use pdf/jpg/jpeg/png.",
            "data": {},
            "status_code": 400,
        }
        return result, 400

    ext = filename.rsplit(".", 1)[1].lower()
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file_storage.save(save_path)

    try:
        result = extract_receipt_to_object(save_path, ext)
        # ensure expected keys exist
        result.setdefault("status", False)
        result.setdefault("message", "")
        result.setdefault("data", {})
        result.setdefault("status_code", 200)

        ok = bool(result.get("status"))
        bump_stats(ok)

        return result, 200
    except Exception as e:
        err = {
            "status": False,
            "message": f"Error processing file: {str(e)}",
            "data": {},
            "status_code": 500,
        }
        bump_stats(False)
        return err, 500


# -------------------- WEB UI --------------------

@app.route("/", methods=["GET", "POST"])
def index():
    json_result = None
    error = None
    stats = load_stats()

    if request.method == "POST":
        files = request.files.getlist("file")
        if not files or (len(files) == 1 and files[0].filename == ""):
            error = "No file selected."
        else:
            processed = {}
            total_files = 0
            success_count = 0

            for file in files:
                if not file or file.filename == "":
                    continue

                total_files += 1
                result, _http = process_single_file(file)

                invoice_number = result.get("invoice_number") or file.filename
                processed[invoice_number] = result

                if result.get("status"):
                    success_count += 1

            if total_files == 0:
                error = "No valid files uploaded."
            else:
                top_level = {
                    "status": success_count > 0,
                    "message": f"{success_count} out of {total_files} files processed",
                    "data": processed,
                }
                json_result = json.dumps(top_level, indent=4, ensure_ascii=False)
                stats = load_stats()

    return render_template_string(HTML_TEMPLATE, json_result=json_result, error=error, stats=stats)


# -------------------- API ENDPOINTS --------------------

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": True, "message": "OK"}), 200


@app.route("/api/extract", methods=["POST", "OPTIONS"])
def api_extract():
    # CORS preflight
    if request.method == "OPTIONS":
        resp = jsonify({"status": True, "message": "OK"})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return resp, 200

    # allow single file under "file"
    file = None
    if "file" in request.files:
        file = request.files["file"]
    elif "files" in request.files:
        # some clients use files[]
        files = request.files.getlist("files")
        file = files[0] if files else None
    elif "files[]" in request.files:
        files = request.files.getlist("files[]")
        file = files[0] if files else None

    if not file:
        print("[api_extract] no files received; keys:", list(request.files.keys()))
        return jsonify({
            "status": False,
            "message": "No file provided. Expected form field 'file' or 'files[]'.",
            "data": {},
            "status_code": 400
        }), 400

    result, http_status = process_single_file(file)
    print(f"[api_extract] filename={file.filename} status={result.get('status')} http={http_status}")
    return jsonify(result), http_status


@app.route("/api/stats", methods=["GET"])
def api_stats():
    stats = load_stats()
    return jsonify({
        "status": True,
        "data": stats
    }), 200


@app.route("/stats", methods=["GET"])
def stats_page():
    stats = load_stats()
    total = stats["total_files"] or 0
    success = stats["success"] or 0
    failed = stats["failed"] or 0

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8" />
          <title>OCR Stats</title>
        </head>
        <body style="font-family: system-ui, sans-serif; padding: 24px;">
          <h2>OCR Usage Stats</h2>
          <p><strong>Total files:</strong> {{ total }}</p>
          <p><strong>Success:</strong> {{ success }}</p>
          <p><strong>Failed:</strong> {{ failed }}</p>
        </body>
        </html>
        """,
        total=total,
        success=success,
        failed=failed,
    )


# -------------------- MAIN --------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # Railway uses PORT env
    app.run(host="0.0.0.0", port=port)
