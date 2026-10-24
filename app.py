from flask import Flask, render_template, request, jsonify
import os
import requests

app = Flask(__name__)

CACHE_BASE = os.getenv("SCRYFALL_CACHE_URL", "http://scryfall-cache:8080")

@app.get("/")
def index():
    return render_template("booster.html")

@app.get("/api/booster/sets")
def api_booster_sets():
    try:
        r = requests.get(f"{CACHE_BASE}/api/booster/sets", timeout=20)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.post("/api/booster/single")
def api_booster_single():
    try:
        payload = request.get_json(silent=True) or {}
        r = requests.post(
            f"{CACHE_BASE}/api/booster/single",
            json=payload,
            timeout=25,
        )
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
