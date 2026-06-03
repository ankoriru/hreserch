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
}

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for key, val in DEFAULT_CONFIG.items():
                if key not in data:
                    data[key] = val
            return data
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
