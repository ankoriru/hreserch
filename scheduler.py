import json
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from config import load_config, save_config

OUTPUT_DIR = Path("reports")
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "VacancyMonitor/1.0 (web-app@example.com)",
    "Accept": "application/json",
}

def is_workday():
    today = datetime.now().weekday()
    return today not in (5, 6)

def format_salary(vacancy):
    salary = vacancy.get("salary")
    if not salary:
        return "з/п не указана"
    parts = []
    if salary.get("from"):
        parts.append("от {:,}".format(salary["from"]))
    if salary.get("to"):
        parts.append("до {:,}".format(salary["to"]))
    if salary.get("currency"):
        parts.append(salary["currency"])
    return " ".join(parts) if parts else "з/п не указана"

def fetch_vacancies(query, area_id, date_from, date_to, per_page=100):
    url = "https://api.hh.ru/vacancies"
    params = {
        "text": query,
        "area": area_id,
        "date_from": date_from,
        "date_to": date_to,
        "order_by": "publication_time",
        "per_page": per_page,
    }
    full_url = "{}?{}".format(url, urllib.parse.urlencode(params))
    req = urllib.request.Request(full_url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("items", [])
    except Exception as e:
        print("[API Error] {}: {}".format(query, e))
        return []

def send_telegram(token, chat_id, message):
    if not token or not chat_id:
        return False
    tg_url = "https://api.telegram.org/bot{}/sendMessage".format(token)
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(tg_url, data=data,
                                  headers={"Content-Type": "application/json"},
                                  method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception as e:
        print("[Telegram Error] {}".format(e))
        return False

def run_monitor_job():
    cfg = load_config()
    if not cfg.get("enabled", True):
        print("[Scheduler] Monitor disabled, skipping.")
        return
    if cfg.get("only_workdays", True) and not is_workday():
        print("[Scheduler] Weekend, skipping.")
        return

    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    date_from = "{}T00:00:00+03:00".format(date_str)
    date_to = "{}T23:59:59+03:00".format(date_str)

    sent_ids = set(cfg.get("sent_vacancies", []))
    all_vacancies = []
    seen_ids = set()

    for query in cfg.get("search_queries", []):
        items = fetch_vacancies(query, cfg["area_id"], date_from, date_to, cfg["per_page"])
        print('[Scheduler] Query "{}" -> {} items'.format(query, len(items)))
        for item in items:
            vid = item.get("id")
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                all_vacancies.append(item)

    new_vacancies = [v for v in all_vacancies if v.get("id") not in sent_ids]
    print("[Scheduler] Total: {}, New: {}".format(len(all_vacancies), len(new_vacancies)))

    if not new_vacancies:
        cfg["sent_vacancies"] = sorted(sent_ids | seen_ids)
        save_config(cfg)
        return

    # Build text report
    lines = ["📋 Новые вакансии ИТ-руководителей в Москве — {}".format(date_str),
             "Найдено: {}".format(len(new_vacancies)), ""]
    for v in new_vacancies:
        title = v.get("name", "Без названия")
        employer = v.get("employer", {}).get("name", "Неизвестный")
        url = v.get("alternate_url", "")
        salary = format_salary(v)
        published = v.get("published_at", "")[:10]
        lines.append("• {}".format(title))
        lines.append("  Компания: {}".format(employer))
        lines.append("  Зарплата: {}".format(salary))
        lines.append("  Дата: {}".format(published))
        lines.append("  Ссылка: {}".format(url))
        lines.append("")

    text_report = "
".join(lines)
    txt_path = OUTPUT_DIR / "vacancies_{}.txt".format(date_str)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text_report)

    # Build HTML report
    items_html = []
    for v in new_vacancies:
        title = v.get("name", "Без названия")
        employer = v.get("employer", {}).get("name", "Неизвестный")
        url = v.get("alternate_url", "")
        salary = format_salary(v)
        published = v.get("published_at", "")[:10]
        items_html.append(
            '<div class="vacancy"><h3><a href="{}" target="_blank">{}</a></h3>'
            '<p>Компания: {}</p><p>Зарплата: {}</p><p>Дата: {}</p>'
            '<p><a href="{}" target="_blank">Открыть на hh.ru →</a></p></div>'
            .format(url, title, employer, salary, published, url)
        )

    html = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>Вакансии {}</title>
<style>
body{{font-family:Arial,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;color:#333}}
h1{{color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:10px}}
.vacancy{{background:#f8f9fa;border-left:4px solid #3498db;padding:15px;margin:15px 0;border-radius:4px}}
.vacancy h3{{margin:0 0 8px 0}} .vacancy h3 a{{color:#2980b9;text-decoration:none}}
.vacancy h3 a:hover{{text-decoration:underline}} .vacancy p{{margin:4px 0;color:#555}}
.meta{{color:#7f8c8d;font-size:0.9em;margin-top:20px}}
</style></head><body>
<h1>Новые вакансии ИТ-руководителей в Москве</h1>
<p>Дата: <strong>{}</strong> | Найдено: <strong>{}</strong></p>
{}
<p class="meta">Сформировано автоматически</p>
</body></html>""".format(date_str, date_str, len(new_vacancies), "
".join(items_html))

    html_path = OUTPUT_DIR / "vacancies_{}.html".format(date_str)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Send Telegram
    token = cfg.get("telegram_bot_token", "")
    chat_id = cfg.get("telegram_chat_id", "")
    if token and chat_id:
        MAX_LEN = 4000
        header = "📋 <b>Новые вакансии ИТ-руководителей</b>
<b>Дата:</b> {}
<b>Найдено:</b> {}

".format(date_str, len(new_vacancies))
        messages = []
        current = header
        for v in new_vacancies:
            block = "• {}
  Компания: {}
  Зарплата: {}
  Ссылка: {}

".format(
                v.get("name", ""), v.get("employer", {}).get("name", ""),
                format_salary(v), v.get("alternate_url", "")
            )
            if len(current) + len(block) > MAX_LEN:
                messages.append(current)
                current = block
            else:
                current += block
        if current:
            messages.append(current)
        for i, msg in enumerate(messages, 1):
            ok = send_telegram(token, chat_id, msg)
            print("[Scheduler] Telegram part {}/{}: {}".format(i, len(messages), "OK" if ok else "FAIL"))

    # Save history
    new_ids = {v.get("id") for v in new_vacancies}
    cfg["sent_vacancies"] = sorted(sent_ids | new_ids)
    save_config(cfg)
    print("[Scheduler] Job completed. Saved {} total IDs.".format(len(cfg["sent_vacancies"])))

# Global scheduler instance
scheduler = BackgroundScheduler()

def init_scheduler():
    cfg = load_config()
    time_str = cfg.get("schedule_time", "09:00")
    try:
        hour, minute = map(int, time_str.split(":"))
    except Exception:
        hour, minute = 9, 0
    scheduler.add_job(run_monitor_job, 'cron', hour=hour, minute=minute, id='vacancy_job')
    scheduler.start()
    print("[Scheduler] Started. Daily at {}:{}".format(hour, minute))

def update_schedule(new_time):
    try:
        scheduler.reschedule_job('vacancy_job', trigger='cron', hour=int(new_time.split(":")[0]), minute=int(new_time.split(":")[1]))
    except Exception as e:
        print("[Scheduler] Failed to reschedule: {}".format(e))
