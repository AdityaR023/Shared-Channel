from flask import Flask, request, jsonify
from services.generate_metadata_file import generate_metadata
from services.indexing_services import index_data
from services.search_service import hybrid_search, clear_search_cache

app = Flask(__name__)

# ============================================================
#  METADATA API (optional but important)
# ============================================================

import os


@app.route("/generate-metadata", methods=["POST"])
def metadata_api():

    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"status": "error", "message": "Empty filename"}), 400

    # ✅ Detect extension
    ext = os.path.splitext(file.filename)[1].lower()

    if ext == ".csv":
        target_folder = "Data/CSV"
    elif ext == ".json":
        target_folder = "Data/JSON"
    elif ext in [".html", ".mhtml", ".mht"]:
        target_folder = "Data/HTML"
    elif ext == ".pdf":
        target_folder = "Data/PDF"
    else:
        return jsonify({"status": "error", "message": "Unsupported file type"}), 400

    # ✅ Create folder
    os.makedirs(target_folder, exist_ok=True)

    # ✅ Save directly to final location
    target_path = os.path.join(target_folder, file.filename)

    if not os.path.exists(target_path):
        file.save(target_path)

    # ✅ Pass this path to your function
    result = generate_metadata(target_path)
    total_chunks = 0
    # ✅ call indexing automatically
    if result["file_path"] and result["processed"] == 1:
        full_path = os.path.join("Data", result["file_path"])
        total_chunks = index_data(full_path)
        clear_search_cache()
    return jsonify(
        {
            "status": "success",
            "file_path": result["file_path"],
            "metadata_file_path": result["metadata_file_path"],
            "processed": result["processed"],
            "skipped": result["skipped"],
            "total_chunks": total_chunks,
        }
    )


# ============================================================
# TASK-103: INDEXING API
# ============================================================


@app.route("/index", methods=["POST"])
def index_api():
    try:
        result = index_data("file_mapping.json", "Data")

        return jsonify({"status": "indexed", "documents_indexed": result})

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)}), 500


# ============================================================
# TASK-104: SEARCH API
# ============================================================


@app.route("/search", methods=["POST"])
def search_api():
    try:
        data = request.get_json()
        query = data.get("query")

        top_k = int(data.get("top_k", 5))

        domain_filter = data.get("domain_filter")
        brand_filter = data.get("brand_filter")

        if not query:
            return jsonify({"error": "query is required"}), 400

        if top_k <= 0:
            top_k = 5

        results = hybrid_search(query, top_k, domain_filter, brand_filter)

        return jsonify({"status": "success", "results": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# TASK-105: VALIDATION API
# ============================================================


@app.route("/search/validate", methods=["GET"])
def validate_api():
    try:
        query = request.args.get("q")

        if not query:
            return jsonify({"error": "Query parameter 'q' is required"}), 400

        results = hybrid_search(query, top_k=5)

        # validation logic (filter weak results)
        filtered_results = [r for r in results if r["score"] < 0.7]

        return jsonify(
            {
                "query": query,
                "valid_results": filtered_results,
                "total_results": len(results),
                "valid_count": len(filtered_results),
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
