from flask import Flask, request, jsonify
from generate_metadata_file import generate_metadata
from Chroma import index_data
from Chroma import search_data

app = Flask(__name__)

# ============================================================
#  METADATA API (optional but important)
# ============================================================

@app.route("/generate-metadata", methods=["POST"])
def metadata_api():
    result = generate_metadata("Data")
    return jsonify({
        "status": "success",
        "processed": result["processed"],
        "skipped": result["skipped"]
    })


# ============================================================
# TASK-103: INDEXING API
# ============================================================


@app.route("/index", methods=["POST"])
def index_api():
    try:
        result = index_data("file_mapping.json", "Data")

        return jsonify({
            "status": "indexed",
            "documents_indexed": result
        })

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)}), 500



# ============================================================
# TASK-104: SEARCH API
# ============================================================

@app.route("/search", methods=["GET"])
def search_api():
    try:
        query = request.args.get("q")

        if not query:
            return jsonify({"error": "Query parameter 'q' is required"}), 400

        results = search_data(query)

        return jsonify({
            "query": query,
            "results": results
        })

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

        results = search_data(query)

        # validation logic (filter weak results)
        filtered_results = [
            r for r in results if r["score"] < 0.7
        ]

        return jsonify({
            "query": query,
            "valid_results": filtered_results,
            "total_results": len(results),
            "valid_count": len(filtered_results)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)