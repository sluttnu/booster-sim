from flask import Flask, render_template, request, jsonify
import os
import requests
from urllib.parse import quote_plus

app = Flask(__name__)

CACHE_BASE = os.getenv("SCRYFALL_CACHE_URL", "https://api.scryfall.com").rstrip("/")


def _request_json(path: str, method: str = "GET", payload: dict | None = None, timeout: int = 25):
    url = f"{CACHE_BASE}{path}"
    if method.upper() == "GET":
        r = requests.get(url, timeout=timeout)
    elif method.upper() == "POST":
        r = requests.post(url, json=payload, timeout=timeout)
    else:
        raise ValueError(f"Unsupported method: {method}")

    if r.status_code >= 400:
        try:
            body = r.json()
        except ValueError:
            body = {"error": r.text}
        raise RuntimeError(f"Upstream request failed ({r.status_code}): {body}")

    try:
        return r.json()
    except ValueError:
        return {}


def _canonical_set_list(data):
    if isinstance(data, dict):
        if "data" in data:
            return data["data"]
        if "sets" in data:
            return data["sets"]
    if isinstance(data, list):
        return data
    return []


def _build_search_query(payload):
    set_code = (payload.get("set_code") or "").strip()
    rarity = (payload.get("rarity") or "").strip()
    color = (payload.get("color") or "").strip()
    subtype = (payload.get("subtype") or "").strip()
    cn_min = payload.get("cn_min")
    cn_max = payload.get("cn_max")
    bonus = payload.get("bonus") is True

    parts = []
    if set_code:
        parts.append(f"set:{set_code}")
    if rarity:
        parts.append(f"r:{rarity}")
    if color:
        parts.append(f"c:{color}")
    if subtype and subtype not in {"mb2_main", "mb2_frame", "mb2_border", "mb2_test"}:
        parts.append(f"type:{subtype}")
    if cn_min is not None:
        parts.append(f"cn:>={cn_min}")
    if cn_max is not None:
        parts.append(f"cn:<={cn_max}")
    if bonus:
        parts.append("-is:funny")

    return " ".join(parts) if parts else ""


@app.get("/")
def index():
    return render_template("booster.html")


@app.get("/api/booster/sets")
def api_booster_sets():
    try:
        data = _request_json("/sets", timeout=20)
        sets = _canonical_set_list(data)
        return jsonify({"sets": sets}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.post("/api/booster/single")
def api_booster_single():
    try:
        payload = request.get_json(silent=True) or {}
        q = _build_search_query(payload)

        if not q:
            return jsonify({"error": "Missing set_code or rarity for search"}), 400

        url = f"/cards/search?q={quote_plus(q)}&page=1&unique=prints"
        data = _request_json(url, timeout=25)
        cards = data.get("data", [])

        exclude_ids = set((payload.get("exclude_ids") or []))
        if exclude_ids:
            cards = [card for card in cards if str(card.get("id")) not in exclude_ids]

        if not cards:
            return jsonify({"error": f"No cards found for query: {q}"}), 404

        card = cards[0]
        return jsonify({"card": card}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
