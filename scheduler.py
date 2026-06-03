import json
import os
import re
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from config import load_config, save_config

OUTPUT_DIR = Path("reports")
OUTPUT_DIR.mkdir(exist_ok=True)

# Realistic browser headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://hh.ru/",
    "Connection": "keep-alive",
}

HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://hh.ru/",
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

def format_datetime(published_at):
    if not published_at:
        return ""
    try:
        dt = datetime.fromisoformat(published_at.replace("+0300", "+03:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return published_at[:16].replace("T", " ")

def fetch_vacancies_api(query, area_id, per_page=20):
    """Try API first."""
    url = "https://api.hh.ru/vacancies"
    params = {
        "text": query,
        "area": area_id,
        "per_page": per_page,
    }
    full_url = "{}?{}".format(url, urllib.parse.urlencode(params))
    print("[API URL] {}".format(full_url))
    req = urllib.request.Request(full_url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("items", [])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.read() else ""
        print("[API Error] {}: {} — body: {}".format(query, e, body[:500]))
        return None
    except Exception as e:
        print("[API Error] {}: {}".format(query, e))
        return None

def fetch_vacancies_html(query, area_id):
    """Fallback: parse HTML search page."""
    url = "https://hh.ru/search/vacancy"
    params = {
        "text": query,
        "area": area_id,
        "order_by": "publication_time",
        "search_period": 3,
        "items_on_page": 20,
    }
    full_url = "{}?{}".format(url, urllib.parse.urlencode(params))
    print("[HTML URL] {}".format(full_url))
    req = urllib.request.Request(full_url, headers=HTML_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8")
            return parse_html_vacancies(html)
    except Exception as e:
        print("[HTML Error] {}: {}".format(query, e))
        return []

def parse_html_vacancies(html):
    """Parse vacancies from hh.ru HTML."""
    vacancies = []
    # Find all vacancy cards
    # Pattern: data-qa="vacancy-serp__vacancy" or similar
    cards = re.findall(r'data-qa="vacancy-serp__vacancy"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
    if not cards:
        # Try broader pattern
        cards = re.findall(r'<div[^>]*class="[^"]*vacancy-serp-item[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)

    print("[HTML Parser] Found {} cards".format(len(cards)))

    for card in cards:
        # Extract vacancy ID from URL
        id_match = re.search(r'/vacancy/(\d+)', card)
        if not id_match:
            continue
        vid = id_match.group(1)

        # Title
        title_match = re.search(r'<a[^>]*data-qa="vacancy-serp__vacancy-title"[^>]*>(.*?)</a>', card, re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else "Без названия"

        # URL
        url_match = re.search(r'href="(https://hh\.ru/vacancy/\d+)"', card)
        url = url_match.group(1) if url_match else "https://hh.ru/vacancy/{}".format(vid)

        # Employer
        emp_match = re.search(r'data-qa="vacancy-serp__vacancy-employer"[^>]*>(.*?)</a>', card, re.DOTALL)
        employer = re.sub(r'<[^>]+>', '', emp_match.group(1)).strip() if emp_match else "Неизвестный"

        # Salary
        sal_match = re.search(r'data-qa="vacancy-serp__vacancy-compensation"[^>]*>(.*?)</span>', card, re.DOTALL)
        salary_raw = re.sub(r'<[^>]+>', '', sal_match.group(1)).strip() if sal_match else None
        salary = None
        if salary_raw:
            # Parse "от 400 000 до 600 000 руб." or "400 000 – 600 000 руб."
            parts = {}
            nums = re.findall(r'[\d\s]+', salary_raw)
            nums_clean = [int(n.replace(' ', '')) for n in nums if n.strip().replace(' ', '').isdigit()]
            if nums_clean:
                if len(nums_clean) >= 2:
                    parts = {"from": nums_clean[0], "to": nums_clean[1], "currency": "RUR"}
                else:
                    parts = {"from": nums_clean[0], "currency": "RUR"}
            salary = parts if parts else None

        # Published date (HTML doesn't have exact time, use today)
        published = datetime.now().strftime("%Y-%m-%dT12:00:00+0300")

        vacancies.append({
            "id": vid,
            "name": title,
            "employer": {"name": employer},
            "salary": salary,
            "published_at": published,
            "alternate_url": url,
        })

    return vacancies

def fetch_vacancies(query, area_id, per_page=20):
    """Try API, fallback to HTML."""
    items = fetch_vacancies_api(query, area_id, per_page)
    if items is not None:
        return items
    print("[Fallback] API failed, trying HTML parsing...")
    return fetch_vacancies_html(query, area_id)

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

    search_period = int(cfg.get("search_period", 1))
    cutoff_date = (today - timedelta(days=search_period - 1)).strftime("%Y-%m-%d")
    print("[Scheduler] Period: {} day(s), cutoff: {}".format(search_period, cutoff_date))

    sent_ids = set(cfg.get("sent_vacancies", []))
    all_vacancies = []
    seen_ids = set()

    for query in cfg.get("search_queries", []):
        items = fetch_vacancies(query, cfg["area_id"], per_page=20)
        print('[Scheduler] Query "{}" -> {} items'.format(query, len(items)))
        for item in items:
            vid = item.get("id")
            published = item.get("published_at", "")[:10]
            if vid and vid not in seen_ids and published >= cutoff_date:
                seen_ids.add(vid)
                all_vacancies.append(item)

    new_vacancies = [v for v in all_vacancies if v.get("id") not in sent_ids]
    print("[Scheduler] Total in period: {}, New: {}".format(len(all_vacancies), len(new_vacancies)))

    if not new_vacancies:
        cfg["sent_vacancies"] = sorted(sent_ids | seen_ids)
        save_config(cfg)
        return

    # Build text report
    lines = []
    lines.append("Novye vakansii IT-rukovoditelej v Moskve -- {}".format(date_str))
    lines.append("Period: {} dnja (s {} po {})".format(search_period, cutoff_date, date_str))
    lines.append("Najdeno: {}".format(len(new_vacancies)))
    lines.append("")
    for v in new_vacancies:
        title = v.get("name", "Bez nazvanija")
        employer = v.get("employer", {}).get("name", "Neizvestnyj")
        url = v.get("alternate_url", "")
        salary = format_salary(v)
        published = format_datetime(v.get("published_at", ""))
        lines.append("* {}".format(title))
        lines.append("  Kompanija: {}".format(employer))
        lines.append("  Zarplata: {}".format(salary))
        lines.append("  Data i vremja publikacii: {}".format(published))
        lines.append("  Ssylka: {}".format(url))
        lines.append("")

    text_report = "\n".join(lines)
    txt_path = OUTPUT_DIR / "vacancies_{}.txt".format(date_str)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text_report)

    # Build HTML report
    items_html = []
    for v in new_vacancies:
        title = v.get("name", "Bez nazvanija")
        employer = v.get("employer", {}).get("name", "Neizvestnyj")
        url = v.get("alternate_url", "")
        salary = format_salary(v)
        published = format_datetime(v.get("published_at", ""))
        items_html.append(
            '<div class="vacancy"><h3><a href="{}" target="_blank">{}</a></h3>'
            '<p><strong>Kompanija:</strong> {}</p>'
            '<p><strong>Zarplata:</strong> {}</p>'
            '<p><strong>Data i vremja publikacii:</strong> {}</p>'
            '<p><a href="{}" target="_blank">Otkryt na hh.ru &rarr;</a></p></div>'
            .format(url, title, employer, salary, published, url)
        )

    html_parts = [
        '<!DOCTYPE html>',
        '<html lang="ru">',
        '<head>',
        '<meta charset="UTF-8">',
        '<title>Vakansii {}</title>'.format(date_str),
        '<style>',
        'body{font-family:Arial,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;color:#333}',
        'h1{color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:10px}',
        '.vacancy{background:#f8f9fa;border-left:4px solid #3498db;padding:15px;margin:15px 0;border-radius:4px}',
        '.vacancy h3{margin:0 0 8px 0}',
        '.vacancy h3 a{color:#2980b9;text-decoration:none}',
        '.vacancy h3 a:hover{text-decoration:underline}',
        '.vacancy p{margin:4px 0;color:#555}',
        '.meta{color:#7f8c8d;font-size:0.9em;margin-top:20px}',
        '</style>',
        '</head>',
        '<body>',
        '<h1>Novye vakansii IT-rukovoditelej v Moskve</h1>',
        '<p>Period: <strong>{} dnja</strong> (s {} po {}) | Najdeno: <strong>{}</strong></p>'.format(search_period, cutoff_date, date_str, len(new_vacancies)),
        "\n".join(items_html),
        '<p class="meta">Sformirovano avtomaticheski cherez API hh.ru</p>',
        '</body>',
        '</html>',
    ]
    html = "\n".join(html_parts)

    html_path = OUTPUT_DIR / "vacancies_{}.html".format(date_str)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Send Telegram (read from env)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        MAX_LEN = 4000
        header = "Novye vakansii IT-rukovoditelej v Moskve\nPeriod: {} dnja (s {} po {})\nNajdeno: {}\n\n".format(search_period, cutoff_date, date_str, len(new_vacancies))
        messages = []
        current = header
        for v in new_vacancies:
            block = (
                "* {}\n"
                "  Kompanija: {}\n"
                "  Zarplata: {}\n"
                "  Data i vremja: {}\n"
                "  Ssylka: {}\n\n"
            ).format(
                v.get("name", ""),
                v.get("employer", {}).get("name", ""),
                format_salary(v),
                format_datetime(v.get("published_at", "")),
                v.get("alternate_url", "")
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
    else:
        print("[Scheduler] Telegram not configured (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing)")

    # Save history
    new_ids = {v.get("id") for v in new_vacancies}
    cfg["sent_vacancies"] = sorted(sent_ids | new_ids)
    save_config(cfg)
    print("[Scheduler] Job completed. Saved {} total IDs.".format(len(cfg["sent_vacancies"])))

# Global scheduler instance
scheduler = BackgroundScheduler()

def init_scheduler():
    if scheduler.running:
        print("[Scheduler] Already running.")
        return
    cfg = load_config()
    time_str = cfg.get("schedule_time", "09:00")
    try:
        hour, minute = map(int, time_str.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Invalid time")
    except Exception:
        hour, minute = 9, 0
    scheduler.add_job(run_monitor_job, 'cron', hour=hour, minute=minute, id='vacancy_job')
    scheduler.start()
    print("[Scheduler] Started. Daily at {}:{}".format(hour, minute))

def update_schedule(new_time):
    try:
        h, m = map(int, new_time.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Hours must be 0-23, minutes 0-59")
        job = scheduler.get_job('vacancy_job')
        if job:
            scheduler.reschedule_job('vacancy_job', trigger='cron', hour=h, minute=m)
            print("[Scheduler] Rescheduled to {}:{}".format(h, m))
        else:
            scheduler.add_job(run_monitor_job, 'cron', hour=h, minute=m, id='vacancy_job')
            print("[Scheduler] Added new job at {}:{}".format(h, m))
    except Exception as e:
        print("[Scheduler] Failed to reschedule: {}".format(e))
