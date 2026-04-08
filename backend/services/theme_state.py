import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

try:
    from pymongo import MongoClient
except Exception:  # pragma: no cover - optional dependency guard
    MongoClient = None

_STORE_LOCK = Lock()
_STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "theme_state.json"
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_MONGO_CLIENT = None
_CONNECTION_STATUS_PRINTED = False


def _read_env_file():
    if not _ENV_PATH.exists():
        return {}

    parsed = {}
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        row = line.strip()
        if not row or row.startswith("#") or "=" not in row:
            continue
        key, value = row.split("=", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    return parsed


def _env_value(name, default=None):
    value = os.getenv(name)
    if value:
        return value

    file_env = _read_env_file()
    return file_env.get(name, default)


def _mongo_collection():
    global _MONGO_CLIENT, _CONNECTION_STATUS_PRINTED

    uri = _env_value("MONGODB_URI")
    if not uri or MongoClient is None:
        if not _CONNECTION_STATUS_PRINTED:
            print("[theme_state] MongoDB not configured; using local JSON store.")
            _CONNECTION_STATUS_PRINTED = True
        return None

    db_name = _env_value("MONGODB_DB", "stylesync")
    collection_name = _env_value("MONGODB_COLLECTION", "theme_state")

    if _MONGO_CLIENT is None:
        try:
            # Use default pool settings because workload/concurrency details are unknown.
            _MONGO_CLIENT = MongoClient(uri, appname="StyleSync")
            _MONGO_CLIENT.admin.command("ping")
            print(f"[theme_state] MongoDB connected: {db_name}.{collection_name}")
            _CONNECTION_STATUS_PRINTED = True
        except Exception:
            if not _CONNECTION_STATUS_PRINTED:
                print("[theme_state] MongoDB connection failed; using local JSON store.")
                _CONNECTION_STATUS_PRINTED = True
            return None

    return _MONGO_CLIENT[db_name][collection_name]


def _ensure_store_file():
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _STORE_PATH.exists():
        _STORE_PATH.write_text("{}", encoding="utf-8")


def _read_all_state():
    _ensure_store_file()
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_all_state(state):
    _ensure_store_file()
    _STORE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_theme_state(site_id):
    with _STORE_LOCK:
        collection = _mongo_collection()
        if collection is not None:
            doc = collection.find_one({"site_id": site_id}, {"_id": 0})
            return doc if isinstance(doc, dict) else None

        state = _read_all_state()
        entry = state.get(site_id)
        return entry if isinstance(entry, dict) else None


def save_theme_state(site_id, url, locked_tokens, overrides):
    now = datetime.now(timezone.utc).isoformat()
    locked_tokens = locked_tokens or []
    overrides = overrides or {}

    with _STORE_LOCK:
        collection = _mongo_collection()

        if collection is not None:
            existing = collection.find_one({"site_id": site_id}, {"_id": 0}) or {}
            if not isinstance(existing, dict):
                existing = {}

            current_version = int(existing.get("version", 0))
            next_version = current_version + 1

            history = existing.get("history", [])
            if not isinstance(history, list):
                history = []

            history_entry = {
                "version": next_version,
                "updated_at": now,
                "locked_tokens": locked_tokens,
                "overrides": overrides,
            }
            history.append(history_entry)

            doc = {
                "site_id": site_id,
                "url": url,
                "version": next_version,
                "updated_at": now,
                "locked_tokens": locked_tokens,
                "overrides": overrides,
                "history": history[-20:],
            }
            collection.replace_one({"site_id": site_id}, doc, upsert=True)
            print(f"[theme_state] MongoDB upsert success: site_id={site_id}, version={next_version}")
            return doc

        state = _read_all_state()
        existing = state.get(site_id, {}) if isinstance(state.get(site_id), dict) else {}

        current_version = int(existing.get("version", 0))
        next_version = current_version + 1

        history = existing.get("history", [])
        if not isinstance(history, list):
            history = []

        history_entry = {
            "version": next_version,
            "updated_at": now,
            "locked_tokens": locked_tokens,
            "overrides": overrides,
        }
        history.append(history_entry)

        state[site_id] = {
            "site_id": site_id,
            "url": url,
            "version": next_version,
            "updated_at": now,
            "locked_tokens": locked_tokens,
            "overrides": overrides,
            "history": history[-20:],
        }

        _write_all_state(state)
        print(f"[theme_state] Local file upsert success: site_id={site_id}, version={next_version}")
        return state[site_id]


def apply_locked_overrides(system, state_entry):
    if not system or not state_entry:
        return system

    locked_tokens = set(state_entry.get("locked_tokens") or [])
    overrides = state_entry.get("overrides") or {}
    color_overrides = overrides.get("colors") or {}
    typography_overrides = overrides.get("typography") or {}
    spacing_overrides = overrides.get("spacing") or {}

    if not isinstance(color_overrides, dict):
        color_overrides = {}

    colors = system.get("colors", {})

    for token_name, token_value in color_overrides.items():
        lock_key = f"color.{token_name}"
        if lock_key not in locked_tokens:
            continue
        if token_name == "neutrals":
            continue

        existing = colors.get(token_name)
        if isinstance(existing, dict) and "value" in existing:
            existing["value"] = token_value
            existing["source"] = "locked"
        elif existing is not None:
            colors[token_name] = {
                "value": token_value,
                "source": "locked",
            }

    system["colors"] = colors

    if isinstance(typography_overrides, dict):
        typography = system.get("typography", {})

        mapping = {
            "fontFamily": "font_family",
            "bodySize": "body_size",
        }

        for override_key, target_key in mapping.items():
            lock_key = f"typography.{override_key}"
            if lock_key not in locked_tokens:
                continue
            value = typography_overrides.get(override_key)
            if value is None:
                continue

            if target_key == "font_family":
                typography[target_key] = [{"value": value, "source": "locked"}]
                if "primary_font" in typography:
                    typography["primary_font"] = {"value": value, "source": "locked"}
            else:
                typography[target_key] = {"value": f"{value}px", "source": "locked"}

        system["typography"] = typography

    if isinstance(spacing_overrides, dict):
        spacing = system.get("spacing", {})
        for key, value in spacing_overrides.items():
            lock_key = f"spacing.{key}"
            if lock_key not in locked_tokens:
                continue
            if key not in spacing:
                continue

            existing = spacing.get(key)
            if isinstance(existing, dict) and "value" in existing:
                existing["value"] = int(value)
                existing["source"] = "locked"
            else:
                spacing[key] = {"value": int(value), "source": "locked"}

        system["spacing"] = spacing

    return system
