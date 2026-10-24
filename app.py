from flask import Flask, render_template, request, jsonify
import os
import random
from datetime import date
import requests

app = Flask(__name__)

SCRYFALL_API = "https://api.scryfall.com"
CACHE_BASE = os.getenv("SCRYFALL_CACHE_URL")

EXCLUDED_SET_CODES = {"pred", "h17", "phtr", "punk", "klr", "h2r"}
EXCLUDED_SET_KEYWORDS = {
    "commander",
    "jumpstart",
    "eternal",
    "timeshifts",
    "big score",
    "planechase",
    "clue",
    "jurassic",
    "heroes of the realm",
}

BONUS_SHEET_MAP = {
    "tsp": "tsb",
    "tsr": "tsr",
    "stx": "sta",
    "dmu": "dmc",
    "bro": "brr",
    "mom": "mul",
    "woe": "wot",
    "mkm": "mkc",
    "otj": "otp",
    "mh3": "m3c",
    "blb": "blb",
    "dsk": "spg",
    "inr": "inr",
}


def _is_cache_enabled() -> bool:
    return bool(CACHE_BASE and CACHE_BASE.strip())


def _call_cache_or_scryfall(path: str, method: str = "GET", payload: dict | None = None):
    if _is_cache_enabled():
        url = f"{CACHE_BASE.rstrip('/')}{path}"
    else:
        url = f"{SCRYFALL_API}{path}"

    headers = {"User-Agent": "booster-sim/0.1", "Accept": "application/json"}
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=25)
        else:
            response = requests.post(url, headers=headers, json=payload, timeout=25)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


@app.get("/")
def index():
    return render_template("booster.html")


@app.get("/api/booster/sets")
def api_booster_sets():
    try:
        if _is_cache_enabled():
            return _call_cache_or_scryfall("/api/booster/sets")

        today = date.today()
        data = _call_cache_or_scryfall("/sets")
        eligible = []

        for set_data in data.get("data", []):
            set_type = set_data.get("set_type", "")
            set_code = (set_data.get("code") or "").lower()
            set_name = (set_data.get("name") or "").lower()
            released_at = set_data.get("released_at", "")

            if released_at:
                try:
                    if date.fromisoformat(released_at) > today:
                        continue
                except ValueError:
                    pass

            if set_code in EXCLUDED_SET_CODES:
                continue

            if any(kw in set_name or kw in set_code for kw in EXCLUDED_SET_KEYWORDS):
                continue

            if set_name.endswith("commander") or (
                set_name.startswith("commander") and any(char.isdigit() for char in set_name)
            ):
                continue

            if set_type in [
                "expansion",
                "core",
                "masters",
                "draft_innovation",
                "commander",
                "funny",
                "starter",
                "eternal",
            ]:
                eligible.append({
                    "code": set_data.get("code"),
                    "name": set_data.get("name"),
                    "released_at": set_data.get("released_at"),
                    "card_count": set_data.get("card_count", 0),
                    "set_type": set_type,
                    "icon_svg_uri": set_data.get("icon_svg_uri", ""),
                })

        return jsonify({
            "sets": eligible,
            "cache_size_gb": 0.0,
            "bonus_sheet_map": BONUS_SHEET_MAP,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/booster/single")
def api_booster_single():
    try:
        if _is_cache_enabled():
            return _call_cache_or_scryfall("/api/booster/single", method="POST", payload=request.get_json(silent=True) or {})

        payload = request.get_json(silent=True) or {}
        set_code = (payload.get("set_code") or "").strip().lower()
        rarity = (payload.get("rarity") or "").strip().lower()
        exclude_ids = set(payload.get("exclude_ids", []))
        color = (payload.get("color") or "").strip()
        cn_min = payload.get("cn_min")
        cn_max = payload.get("cn_max")
        subtype = (payload.get("subtype") or "").strip().lower()
        bonus = bool(payload.get("bonus", False))

        if not set_code:
            return jsonify({"error": "Missing set_code"}), 400
        if not rarity:
            return jsonify({"error": "Missing rarity"}), 400

        effective_set_code = set_code
        is_bonus = False
        if bonus and not subtype:
            bonus_code = BONUS_SHEET_MAP.get(set_code)
            if bonus_code:
                effective_set_code = bonus_code
                is_bonus = True

        pool = _direct_fetch_set_cards(effective_set_code)
        if not pool:
            return jsonify({"error": f"No cards found for set {effective_set_code}"}), 404

        if color:
            pool = [c for c in pool if c.get("color_bucket") == _normalise_bucket(color)]
            if not pool:
                return jsonify({"error": f"No {color} cards in pool"}), 404

        if rarity == "rare":
            card = _get_rare_or_mythic(pool, exclude_ids)
            if not card:
                return jsonify({"error": "No rare/mythic cards available"}), 404
        elif rarity == "land":
            card = _get_common_land(pool, exclude_ids)
            if not card:
                return jsonify({"error": "No land cards available"}), 404
        elif rarity == "cu":
            candidates = [c for c in pool if c.get("rarity") in ("common", "uncommon") and c["id"] not in exclude_ids]
            if not candidates:
                return jsonify({"error": "No C/U cards available"}), 404
            card = random.choice(candidates)
        elif rarity == "any":
            candidates = [c for c in pool if c["id"] not in exclude_ids]
            if not candidates:
                return jsonify({"error": "No available cards"}), 404
            card = random.choice(candidates)
        else:
            candidates = [c for c in pool if c.get("rarity") == rarity and c["id"] not in exclude_ids]
            if not candidates:
                return jsonify({"error": f"No {rarity} cards available"}), 404
            if rarity == "common" and not color and not subtype and not is_bonus:
                candidates = [c for c in candidates if not c.get("is_common_land")]
                if not candidates:
                    return jsonify({"error": "No non-land common cards available"}), 404
            card = random.choice(candidates)

        return jsonify({
            "card": card,
            "from_cache": False,
            "fetch_time": 0,
            "is_bonus": is_bonus,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _normalise_bucket(color_value: str) -> str:
    color_value = (color_value or "").upper()
    if len(color_value) == 1:
        return color_value
    return color_value.lower()


def _direct_fetch_set_cards(set_code: str):
    cards = []
    page = 1
    while True:
        data = _call_cache_or_scryfall(f"/cards/search?q=set:{set_code}&page={page}")
        for raw in data.get("data", []):
            card = _normalise_card(raw, set_code)
            if card:
                cards.append(card)

        if not data.get("has_more"):
            break
        page += 1
    return cards


def _normalise_card(card: dict, set_code: str) -> dict | None:
    rarity = card.get("rarity", "")
    if rarity not in ["common", "uncommon", "rare", "mythic", "special"]:
        return None

    type_line = card.get("type_line", "")
    colors = card.get("colors") or []

    if card.get("image_uris"):
        front_url = _pick_image(card["image_uris"])
        back_url = None
    elif card.get("card_faces") and len(card["card_faces"]) >= 2:
        f0 = card["card_faces"][0]
        f1 = card["card_faces"][1]
        front_url = _pick_image(f0.get("image_uris") or {})
        back_url = _pick_image(f1.get("image_uris") or {})
        if not colors:
            colors = f0.get("colors") or []
    else:
        return None

    if not front_url:
        return None

    collector_number = card.get("collector_number", "")
    try:
        cn_int = int("".join(ch for ch in collector_number if ch.isdigit()) or "0")
    except ValueError:
        cn_int = 0

    card_obj = {
        "id": card.get("id"),
        "name": card.get("name", "Unknown"),
        "image_url": front_url,
        "back_image_url": back_url,
        "rarity": rarity,
        "set": set_code,
        "mana_cost": card.get("mana_cost", ""),
        "type_line": type_line,
        "is_common_land": (rarity == "common" and "Land" in type_line),
        "color_bucket": _classify_color(colors, type_line),
        "frame": card.get("frame", ""),
        "border_color": card.get("border_color", ""),
        "collector_number": cn_int,
    }
    return card_obj


def _pick_image(image_uris: dict) -> str:
    if not isinstance(image_uris, dict):
        return ""
    for key in ("border_crop", "normal", "large", "png", "art_crop"):
        if image_uris.get(key):
            return image_uris[key]
    return ""


def _classify_color(colors: list[str], type_line: str) -> str:
    if "Land" in type_line:
        return "land"
    if len(colors) > 1:
        return "multi"
    if len(colors) == 1:
        return colors[0].upper()
    return "colorless"


def _get_rare_or_mythic(pool, exclude_ids):
    mythic = [c for c in pool if c.get("rarity") == "mythic" and c["id"] not in exclude_ids]
    if mythic and random.randint(1, 8) == 1:
        return random.choice(mystic)

    rares = [c for c in pool if c.get("rarity") == "rare" and c["id"] not in exclude_ids]
    if rares:
        return random.choice(rares)
    return None


def _get_common_land(pool, exclude_ids):
    lands = [c for c in pool if c.get("rarity") == "common" and "Land" in c.get("type_line", "") and c["id"] not in exclude_ids]
    return random.choice(lands) if lands else None


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
