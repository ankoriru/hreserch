import json
import os
from pathlib import Path

CONFIG_FILE = Path("config.json")

DEFAULT_CONFIG = {
    "search_queries": [
        "ИТ директор",
        "Руководитель ИТ",
        "IT директор",
        "IT director",
        "Директор по информационным технологиям",
        "Руководитель информационных технологий",
        "CIO",
        "Chief Information Officer",
    ],
    "area_id": "1",
    "per_page": 100,
    "schedule_time": "09:00",
    "search_period": 1,
    "enabled": True,
    "only_workdays": True,
    "sent_vacancies": [],
    "hh_access_token": "",
    "reports_history": [],
}

def _env_override(cfg):
    """Override config with environment variables (for persistence on Amvera)."""
    if os.environ.get("SCHEDULE_TIME"):
        cfg["schedule_time"] = os.environ.get("SCHEDULE_TIME")
    if os.environ.get("SEARCH_PERIOD"):
        try:
            cfg["search_period"] = int(os.environ.get("SEARCH_PERIOD"))
        except:
            pass
    if os.environ.get("AREA_ID"):
        cfg["area_id"] = os.environ.get("AREA_ID")
    if os.environ.get("SEARCH_QUERIES"):
        cfg["search_queries"] = [q.strip() for q in os.environ.get("SEARCH_QUERIES").split(",") if q.strip()]
    if os.environ.get("ENABLED"):
        cfg["enabled"] = os.environ.get("ENABLED").lower() in ("true", "1", "yes", "on")
    if os.environ.get("ONLY_WORKDAYS"):
        cfg["only_workdays"] = os.environ.get("ONLY_WORKDAYS").lower() in ("true", "1", "yes", "on")
    if os.environ.get("HH_ACCESS_TOKEN"):
        cfg["hh_access_token"] = os.environ.get("HH_ACCESS_TOKEN")
    return cfg

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for key, val in DEFAULT_CONFIG.items():
                    if key in data:
                        cfg[key] = data[key]
                    else:
                        cfg[key] = val
        except Exception as e:
            print("[Config] Ошибка загрузки файла: {}".format(e))
    # Apply env overrides (env vars survive container restarts on Amvera)
    cfg = _env_override(cfg)
    print("[Config] Загружено. Запросы: {} | Время: {} | Период: {}".format(
        cfg.get("search_queries", []), cfg.get("schedule_time"), cfg.get("search_period")))
    return cfg

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print("[Config] Сохранено в {}".format(CONFIG_FILE.absolute()))
    except Exception as e:
        print("[Config] Ошибка сохранения: {}".format(e))
