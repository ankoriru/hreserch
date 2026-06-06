import html as html_module
import json
import os
import re
import socket
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
from bs4 import BeautifulSoup
from config import load_config, save_config

OUTPUT_DIR = Path("reports")
OUTPUT_DIR.mkdir(exist_ok=True)

TZ = timezone("Europe/Moscow")

# Hour-based cutoffs per period
PERIOD_HOURS = {1: 24, 3: 72, 7: 168, 30: 720}

def is_workday():
    today = datetime.now(TZ).weekday()
    return today not in (5, 6)

def format_salary(vacancy):
    salary = vacancy.get("salary")
    if not salary:
        return "\u0437/\u043f \u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d\u0430"
    parts = []
    if salary.get("from"):
        parts.append("\u043e\u0442 {:,}".format(salary["from"]))
    if salary.get("to"):
        parts.append("\u0434\u043e {:,}".format(salary["to"]))
    currency = salary.get("currency", "RUR")
    currency_map = {"RUR": "\u20bd", "USD": "$", "EUR": "\u20ac"}
    parts.append(currency_map.get(currency, currency))
    return " ".join(parts) if parts else "\u0437/\u043f \u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d\u0430"

def format_datetime(published_at):
    if not published_at:
        return ""
    try:
        dt = datetime.fromisoformat(published_at.replace("+0300", "+03:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return published_at[:16].replace("T", " ")

def parse_salary_text(text):
    if not text:
        return None
    text = text.replace('\xa0', ' ').replace('\u202f', ' ').replace('\u2011', ' ')
    currency = "RUR"
    if 'USD' in text or '$' in text:
        currency = "USD"
    elif 'EUR' in text or '\u20ac' in text:
        currency = "EUR"
    match = re.search(r'\u043e\u0442\s+(\d[\d\s]*)\s+\u0434\u043e\s+(\d[\d\s]*)', text, re.IGNORECASE)
    if match:
        return {"from": int(match.group(1).replace(' ', '')), "to": int(match.group(2).replace(' ', '')), "currency": currency}
    match = re.search(r'\u0434\u043e\s+(\d[\d\s]*)', text, re.IGNORECASE)
    if match:
        return {"to": int(match.group(1).replace(' ', '')), "currency": currency}
    match = re.search(r'\u043e\u0442\s+(\d[\d\s]*)', text, re.IGNORECASE)
    if match:
        return {"from": int(match.group(1).replace(' ', '')), "currency": currency}
    if any(c in text for c in ['\u20bd', '\u0440\u0443\u0431', 'USD', 'EUR', '$', '\u20ac']):
        nums = re.findall(r'\d[\d\s]*', text)
        nums_clean = [int(n.replace(' ', '')) for n in nums if n.strip().replace(' ', '').isdigit()]
        if nums_clean:
            if len(nums_clean) >= 2:
                return {"from": nums_clean[0], "to": nums_clean[1], "currency": currency}
            else:
                return {"from": nums_clean[0], "currency": currency}
    return None

def find_salary_in_card(card):
    sal_tag = card.find("span", attrs={"data-qa": "vacancy-serp__vacancy-compensation"})
    if sal_tag:
        txt = sal_tag.get_text(strip=True, separator=' ')
        if txt:
            sal = parse_salary_text(txt)
            if sal:
                return sal
    for cls in ["compensation", "vacancy-serp-item__sidebar", "bloko-header-section-3"]:
        for tag in card.find_all(class_=re.compile(r"{}".format(cls))):
            txt = tag.get_text(strip=True, separator=' ')
            if txt and len(txt) < 100:
                sal = parse_salary_text(txt)
                if sal:
                    return sal
    return None

def parse_date_text(date_text):
    today = datetime.now(TZ)
    if not date_text:
        return today.strftime("%Y-%m-%dT23:59:59+03:00")
    dt = date_text.lower().strip()
    # Hours/minutes/months/"just now" = today
    if "\u0441\u0435\u0433\u043e\u0434\u043d\u044f" in dt or "\u0447\u0430\u0441" in dt or "\u043c\u0438\u043d\u0443\u0442" in dt or "\u043c\u0435\u0441" in dt or "\u0442\u043e\u043b\u044c\u043a\u043e \u0447\u0442\u043e" in dt:
        return today.strftime("%Y-%m-%dT23:59:59+03:00")
    elif "\u0432\u0447\u0435\u0440\u0430" in dt:
        return (today - timedelta(days=1)).strftime("%Y-%m-%dT23:59:59+03:00")
    elif "\u043d\u0435\u0434\u0435\u043b" in dt:
        return (today - timedelta(days=7)).strftime("%Y-%m-%dT23:59:59+03:00")
    else:
        nums = re.findall(r'\d+', dt)
        if nums:
            return (today - timedelta(days=int(nums[0]))).strftime("%Y-%m-%dT23:59:59+03:00")
    return today.strftime("%Y-%m-%dT23:59:59+03:00")

def matches_query(vacancy_name, query):
    if not vacancy_name or not query:
        return False
    name_lower = vacancy_name.lower()
    query_lower = query.lower()
    # Direct substring match first (e.g. "cio" matches "Chief Information Officer (CIO)")
    if query_lower in name_lower:
        return True
    words = [w.strip() for w in query_lower.split() if w.strip()]
    if not words:
        return False
    return all(word in name_lower for word in words)

def fetch_vacancies_html(query, area_id, search_period=1):
    url = "https://hh.ru/search/vacancy"
    params = {
        "text": query,
        "area": area_id,
        "order_by": "publication_time",
        "search_period": search_period,
        "items_on_page": 20,
    }
    full_url = "{}?{}".format(url, urllib.parse.urlencode(params))
    print("[HTML URL] {}".format(full_url))
    req = urllib.request.Request(full_url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Referer": "https://hh.ru/",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8")
            items = parse_html_vacancies(html)
            filtered = [item for item in items if matches_query(item.get("name", ""), query)]
            print("[HTML] Получено {}, после фильтра: {}".format(len(items), len(filtered)))
            return filtered
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        print("[HTML Connection Error] {}: {}".format(query, e))
        return []
    except Exception as e:
        print("[HTML Error] {}: {}".format(query, e))
        return []

def parse_html_vacancies(html):
    soup = BeautifulSoup(html, "html.parser")
    vacancies = []
    cards = soup.find_all("div", attrs={"data-qa": "vacancy-serp__vacancy"})
    if not cards:
        cards = soup.find_all("div", class_=re.compile(r"vacancy-serp-item"))
    if not cards:
        cards = soup.find_all("div", class_=re.compile(r"serp-item"))
    print("[HTML Parser] Найдено {} карточек".format(len(cards)))
    for card in cards:
        try:
            link_tag = card.find("a", attrs={"data-qa": "vacancy-serp__vacancy-title"})
            if not link_tag:
                link_tag = card.find("a", href=re.compile(r"/vacancy/\d+"))
            if not link_tag:
                continue
            href = link_tag.get("href", "")
            id_match = re.search(r'/vacancy/(\d+)', href)
            if not id_match:
                continue
            vid = id_match.group(1)
            title = link_tag.get_text(strip=True, separator=' ')
            # Short clean URL
            url = "https://hh.ru/vacancy/{}".format(vid)

            emp_tag = card.find("a", attrs={"data-qa": "vacancy-serp__vacancy-employer"})
            if not emp_tag:
                emp_tag = card.find("div", class_=re.compile(r"employer"))
            employer = emp_tag.get_text(strip=True, separator=' ') if emp_tag else "\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u044b\u0439"

            salary = find_salary_in_card(card)

            # Try <time datetime> first
            published = None
            time_tag = card.find("time")
            if time_tag and time_tag.get("datetime"):
                try:
                    dt_val = time_tag["datetime"]
                    datetime.fromisoformat(dt_val.replace("+0300", "+03:00"))
                    published = dt_val
                except (ValueError, TypeError):
                    pass
            # Fallback: relative text date
            if not published:
                date_tag = card.find("span", attrs={"data-qa": "vacancy-serp__vacancy-date"})
                if not date_tag:
                    date_tag = card.find("span", class_=re.compile(r"date"))
                date_text = date_tag.get_text(strip=True, separator=' ') if date_tag else None
                published = parse_date_text(date_text)

            vacancies.append({
                "id": vid, "name": title, "employer": {"name": employer},
                "salary": salary, "published_at": published, "alternate_url": url,
            })
        except Exception as e:
            print("[HTML Parser] Ошибка карточки: {}".format(e))
            continue
    return vacancies

def _escape_tg(text):
    if not text:
        return ""
    return html_module.escape(str(text))

def send_telegram(token, chat_id, message, retries=3):
    if not token or not chat_id:
        return False
    tg_url = "https://api.telegram.org/bot{}/sendMessage".format(token)
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(tg_url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                return False
        except Exception:
            if attempt < retries:
                time.sleep(5)
    return False

def cleanup_old_reports(days=7):
    cutoff = datetime.now(TZ).replace(tzinfo=None) - timedelta(days=days)
    count = 0
    for f in OUTPUT_DIR.glob("vacancies_*"):
        try:
            parts = f.stem.split('_')
            if len(parts) >= 3:
                file_dt = datetime.strptime(parts[1], "%Y-%m-%d")
                if file_dt < cutoff:
                    f.unlink()
                    count += 1
        except Exception:
            pass
    if count > 0:
        print("[Cleanup] Удалено {} старых отч\u0451тов".format(count))

def _write_last_run(start_ts, new_count, has_new, queries, finished=True, error=None):
    try:
        last_run = {"start_ts": start_ts, "new_count": new_count, "has_new": has_new, "queries": queries}
        if finished:
            last_run["finished_at"] = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S")
        if error:
            last_run["error"] = str(error)
        with open(OUTPUT_DIR / "last_run.json", "w", encoding="utf-8") as f:
            json.dump(last_run, f, ensure_ascii=True)
    except Exception as e:
        print("[Scheduler] Ошибка записи last_run: {}".format(e))

def _build_reports(vacancies, date_str, time_str, search_period, cutoff_dt, queries_ran, cfg, send_tg=False):
    """Build HTML and txt reports. Returns (count, html_filename, txt_filename)."""
    count = len(vacancies)
    if count == 0:
        return 0, None, None

    today = datetime.now(TZ)
    # Text report
    lines = []
    lines.append("\ud83d\udccb Вакансии \u2014 {}".format(date_str))
    lines.append("\u041f\u0435\u0440\u0438\u043e\u0434: {} \u0434\u043d. | \u041d\u0430\u0439\u0434\u0435\u043d\u043e: {}".format(search_period, count))
    lines.append("")
    for v in vacancies:
        lines.append("\u2022 {}".format(v.get("name", "")))
        lines.append("  \u041a\u043e\u043c\u043f\u0430\u043d\u0438\u044f: {}".format(v.get("employer", {}).get("name", "")))
        lines.append("  \u0417\u0430\u0440\u043f\u043b\u0430\u0442\u0430: {}".format(format_salary(v)))
        lines.append("  \u0414\u0430\u0442\u0430: {}".format(format_datetime(v.get("published_at", ""))))
        lines.append("  \u0421\u0441\u044b\u043b\u043a\u0430: {}".format(v.get("alternate_url", "")))
        lines.append("")
    text_report = "\n".join(lines)
    txt_filename = "vacancies_{}_{}.txt".format(date_str, time_str)
    with open(OUTPUT_DIR / txt_filename, "w", encoding="utf-8") as f:
        f.write(text_report)

    # HTML report
    items_html = []
    for v in vacancies:
        title = v.get("name", "\u0411\u0435\u0437 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u044f")
        employer = v.get("employer", {}).get("name", "\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u044b\u0439")
        url = v.get("alternate_url", "")
        salary = format_salary(v)
        published = format_datetime(v.get("published_at", ""))
        items_html.append(
            '<div class="vacancy">\n'
            '  <h3><a href="{}" target="_blank">{}</a></h3>\n'
            '  <p><strong>\u041a\u043e\u043c\u043f\u0430\u043d\u0438\u044f:</strong> {}</p>\n'
            '  <p><strong>\u0417\u0430\u0440\u043f\u043b\u0430\u0442\u0430:</strong> {}</p>\n'
            '  <p><strong>\u0414\u0430\u0442\u0430 \u043f\u0443\u0431\u043b\u0438\u043a\u0430\u0446\u0438\u0438:</strong> {}</p>\n'
            '  <p><a href="{}" target="_blank">\u041e\u0442\u043a\u0440\u044b\u0442\u044c на hh.ru \u2192</a></p>\n'
            '</div>'.format(url, title, employer, salary, published, url)
        )

    html = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>\u0412\u0430\u043a\u0430\u043d\u0441\u0438\u0438 \u2014 {}</title>
<style>body{{font-family:Arial,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;color:#333}}
h1{{color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:10px}}
.vacancy{{background:#f8f9fa;border-left:4px solid #3498db;padding:15px;margin:15px 0;border-radius:4px}}
.vacancy h3{{margin:0 0 8px 0}} .vacancy h3 a{{color:#2980b9;text-decoration:none}}
.vacancy p{{margin:4px 0;color:#555}} .meta{{color:#7f8c8d;font-size:0.9em;margin-top:20px}}
.back{{margin-bottom:20px}} .back a{{color:#2980b9;text-decoration:none}}</style>
</head>
<body>
<div class="back"><a href="/dashboard">\u2190 \u041d\u0430\u0437\u0430\u0434</a></div>
<h1>\ud83d\udccb \u041d\u043e\u0432\u044b\u0435 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0438</h1>
<p>\u041f\u0435\u0440\u0438\u043e\u0434: <strong>{} \u0434\u043d.</strong> | \u041d\u0430\u0439\u0434\u0435\u043d\u043e: <strong>{}</strong></p>
{}
<p class="meta">\u0421\u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u043d\u043e {}</p>
</body></html>""".format(date_str, search_period, count, "\n".join(items_html), today.strftime("%d.%m.%Y %H:%M"))

    html_filename = "vacancies_{}_{}.html".format(date_str, time_str)
    with open(OUTPUT_DIR / html_filename, "w", encoding="utf-8") as f:
        f.write(html)

    # Meta
    meta = {"date": date_str, "time": time_str, "period": search_period,
            "cutoff": cutoff_dt.strftime("%Y-%m-%dT%H:%M"), "count": count,
            "queries": queries_ran}
    with open(OUTPUT_DIR / "vacancies_{}_{}.meta.json".format(date_str, time_str), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=True, indent=2)

    # History (WITHOUT full content to avoid surrogate/bloat issues)
    report_meta = {"date": date_str, "time": time_str, "period": search_period,
                   "count": count, "filename_html": html_filename,
                   "filename_txt": txt_filename}
    history = cfg.get("reports_history", [])
    history.append(report_meta)
    if len(history) > 30:
        history = history[-30:]
    cfg["reports_history"] = history

    cleanup_old_reports(days=7)

    # Telegram
    if send_tg:
        token_tg = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if token_tg and chat_id:
            header = "\ud83d\udccb \u041d\u043e\u0432\u044b\u0435 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0438\n\u041f\u0435\u0440\u0438\u043e\u0434: {} \u0434\u043d. | \u041d\u0430\u0439\u0434\u0435\u043d\u043e: {}\n\n".format(search_period, count)
            messages = []
            current = header
            for v in vacancies:
                block = "\u2022 {}\n  \u041a\u043e\u043c\u043f\u0430\u043d\u0438\u044f: {}\n  \u0417\u0430\u0440\u043f\u043b\u0430\u0442\u0430: {}\n  \u0414\u0430\u0442\u0430: {}\n  \u0421\u0441\u044b\u043b\u043a\u0430: {}\n\n".format(
                    _escape_tg(v.get("name", "")), _escape_tg(v.get("employer", {}).get("name", "")),
                    _escape_tg(format_salary(v)), _escape_tg(format_datetime(v.get("published_at", ""))),
                    _escape_tg(v.get("alternate_url", "")))
                if len(current) + len(block) > 4000:
                    messages.append(current)
                    current = block
                else:
                    current += block
            if current:
                messages.append(current)
            for i, msg in enumerate(messages, 1):
                ok = send_telegram(token_tg, chat_id, msg)
                print("[Scheduler] Telegram {}/{}: {}".format(i, len(messages), "OK" if ok else "FAIL"))

    return count, html_filename, txt_filename


def run_monitor_job(force=False):
    start_ts = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S")
    queries_ran = []
    try:
        mode = "\u0420\u0423\u0427\u041d\u041e\u0419" if force else "\u0430\u0432\u0442\u043e"
        print("[Scheduler] === {} \u0437\u0430\u043f\u0443\u0441\u043a {} ===".format(mode, start_ts))
        cfg = load_config()
        queries_ran = cfg.get("search_queries", [])

        if not cfg.get("enabled", True) and not force:
            print("[Scheduler] \u041c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433 \u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d, \u043f\u0440\u043e\u043f\u0443\u0441\u043a\u0430\u0435\u043c.")
            _write_last_run(start_ts, 0, False, queries_ran, finished=True)
            return
        if cfg.get("only_workdays", True) and not is_workday() and not force:
            print("[Scheduler] \u0412\u044b\u0445\u043e\u0434\u043d\u043e\u0439, \u043f\u0440\u043e\u043f\u0443\u0441\u043a\u0430\u0435\u043c.")
            _write_last_run(start_ts, 0, False, queries_ran, finished=True)
            return

        today = datetime.now(TZ)
        date_str = today.strftime("%Y-%m-%d")
        time_str = today.strftime("%H-%M")
        search_period_days = int(cfg.get("search_period", 1))
        hours = PERIOD_HOURS.get(search_period_days, search_period_days * 24)
        cutoff_dt = today - timedelta(hours=hours)
        print("[Scheduler] \u041f\u0435\u0440\u0438\u043e\u0434: {} \u0434\u043d. ({} \u0447.), \u043e\u0442\u0441\u0435\u0447\u043a\u0430: {}".format(
            search_period_days, hours, cutoff_dt.strftime("%Y-%m-%dT%H:%M")))

        sent_ids = set(cfg.get("sent_vacancies", []))
        all_vacancies = []
        seen_ids = set()

        for query in cfg.get("search_queries", []):
            try:
                items = fetch_vacancies_html(query, cfg["area_id"], search_period=search_period_days)
                print('[Scheduler] \u0417\u0430\u043f\u0440\u043e\u0441 "{}" -> {} \u0448\u0442.'.format(query, len(items)))
                for item in items:
                    try:
                        vid = item.get("id")
                        if not vid or vid in seen_ids:
                            continue
                        pub_str = item.get("published_at", "")
                        try:
                            dt_str = pub_str.replace("+0300", "+03:00").replace("+0200", "+02:00")
                            pub_dt = datetime.fromisoformat(dt_str)
                            if pub_dt.tzinfo is None:
                                pub_dt = TZ.localize(pub_dt)
                            if pub_dt < cutoff_dt:
                                continue
                        except Exception:
                            pub_date = pub_str[:10] if pub_str else ""
                            if pub_date and pub_date < cutoff_dt.strftime("%Y-%m-%d"):
                                continue
                        seen_ids.add(vid)
                        all_vacancies.append(item)
                    except Exception as inner_e:
                        print("[Scheduler] \u041e\u0448\u0438\u0431\u043a\u0430 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0438: {}".format(inner_e))
                        continue
            except Exception as query_e:
                print("[Scheduler] \u041e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u043f\u0440\u043e\u0441\u0430 '{}': {}".format(query, query_e))
                continue

        print("[Scheduler] \u0412\u0441\u0435\u0433\u043e \u0443\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0445: {}".format(len(all_vacancies)))

        if force:
            report_vacancies = all_vacancies
        else:
            report_vacancies = [v for v in all_vacancies if v.get("id") not in sent_ids]

        count = len(report_vacancies)
        print("[Scheduler] \u0412 \u043e\u0442\u0447\u0451\u0442: {}".format(count))

        if count > 0:
            _build_reports(report_vacancies, date_str, time_str, search_period_days, cutoff_dt, queries_ran, cfg, send_tg=(not force))
            if not force:
                new_ids = {v.get("id") for v in report_vacancies}
                cfg["sent_vacancies"] = sorted(sent_ids | new_ids)
            save_config(cfg)
            _write_last_run(start_ts, count, True, queries_ran, finished=True)
            print("[Scheduler] \u0417\u0430\u0434\u0430\u0447\u0430 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430. \u041e\u0442\u0447\u0451\u0442: {} \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439".format(count))
        else:
            if not force:
                cfg["sent_vacancies"] = sorted(sent_ids | seen_ids)
                save_config(cfg)
            _write_last_run(start_ts, 0, False, queries_ran, finished=True)
            print("[Scheduler] \u041d\u0435\u0442 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439 \u0434\u043b\u044f \u043e\u0442\u0447\u0451\u0442\u0430.")

    except Exception as e:
        print("[Scheduler] \u041a\u0420\u0418\u0422\u0418\u0427\u0415\u0421\u041a\u0410\u042f \u041e\u0428\u0418\u0411\u041a\u0410: {}".format(e))
        import traceback
        traceback.print_exc()
        _write_last_run(start_ts, 0, False, queries_ran, finished=True, error=str(e))

scheduler = BackgroundScheduler(timezone=TZ)

def init_scheduler():
    if scheduler.running:
        return
    cfg = load_config()
    time_str = cfg.get("schedule_time", "09:00")
    try:
        hour, minute = map(int, time_str.split(":"))
    except Exception:
        hour, minute = 9, 0
    scheduler.add_job(lambda: run_monitor_job(force=False), 'cron', hour=hour, minute=minute, id='vacancy_job')
    scheduler.start()
    print("[Scheduler] \u0417\u0430\u043f\u0443\u0449\u0435\u043d. \u0415\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u043e \u0432 {}:{}".format(hour, minute))

def update_schedule(new_time):
    try:
        h, m = map(int, new_time.split(":"))
        job = scheduler.get_job('vacancy_job')
        if job:
            scheduler.reschedule_job('vacancy_job', trigger='cron', hour=h, minute=m)
        else:
            scheduler.add_job(lambda: run_monitor_job(force=False), 'cron', hour=h, minute=m, id='vacancy_job')
    except Exception as e:
        print("[Scheduler] \u041e\u0448\u0438\u0431\u043a\u0430: {}".format(e))
