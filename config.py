import json
import shutil
from pathlib import Path

# Amvera provides persistent storage at /data
# We always use /data/config.json if /data directory exists
if Path("/data").exists():
    CONFIG_FILE = Path("/data/config.json")
    # Ensure /data directory is writable
    try:
        Path("/data").mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
else:
    CONFIG_FILE = Path("config.json")

DEFAULT_CONFIG = {
    "search_queries": [
        "\u0418\u0422 \u0434\u0438\u0440\u0435\u043a\u0442\u043e\u0440",
        "\u0420\u0443\u043a\u043e\u0432\u043e\u0434\u0438\u0442\u0435\u043b\u044c \u0418\u0422",
        "IT \u0434\u0438\u0440\u0435\u043a\u0442\u043e\u0440",
        "IT director",
        "\u0414\u0438\u0440\u0435\u043a\u0442\u043e\u0440 \u043f\u043e \u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u043e\u043d\u043d\u044b\u043c \u0442\u0435\u0445\u043d\u043e\u043b\u043e\u0433\u0438\u044f\u043c",
        "\u0420\u0443\u043a\u043e\u0432\u043e\u0434\u0438\u0442\u0435\u043b\u044c \u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u043e\u043d\u043d\u044b\u0445 \u0442\u0435\u0445\u043d\u043e\u043b\u043e\u0433\u0438\u0439",
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
    "reports_history": [],
}

def load_config():
    # If persistent config doesn't exist yet, copy from app directory if available
    if CONFIG_FILE == Path("/data/config.json") and not CONFIG_FILE.exists():
        app_config = Path("/app/config.json")
        if app_config.exists():
            try:
                shutil.copy2(str(app_config), str(CONFIG_FILE))
                print("[Config] Copied existing config to /data/")
            except Exception as e:
                print("[Config] Could not copy to /data: {}".format(e))

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
            print("[Config] \u041e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u0444\u0430\u0439\u043b\u0430: {}".format(e))
    print("[Config] \u0417\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u043e. \u0417\u0430\u043f\u0440\u043e\u0441\u044b: {} | \u0412\u0440\u0435\u043c\u044f: {} | \u041f\u0435\u0440\u0438\u043e\u0434: {}".format(
        cfg.get("search_queries", []), cfg.get("schedule_time"), cfg.get("search_period")))
    return cfg

def save_config(cfg):
    try:
        # Ensure parent directory exists
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print("[Config] \u0421\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043e \u0432 {}".format(CONFIG_FILE.absolute()))
    except Exception as e:
        print("[Config] \u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f: {}".format(e))
