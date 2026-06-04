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
