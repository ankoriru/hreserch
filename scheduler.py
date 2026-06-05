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

def is_workday():
    today = datetime.now(TZ).weekday()
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
        dt = datetime.fromisoformat(published_at.replace("+0300", "+03:00").replace("+02:00", "+02:00"))
        # If time is 00:00:00, show only date (HH HTML doesn't provide exact time)
        if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
            return dt.strftime("%d.%m.%Y")
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return published_at[:16].replace("T", " ") if len(published_at) > 16 else published_at.replace("T", " ")

def parse_date_text(date_text):
    """Parse relative date text. Returns date only (00:00:00) since HH doesn't show exact time in HTML."""
    today = datetime.now(TZ)
    if not date_text:
        return today.strftime("%Y-%m-%dT00:00:00+03:00")
    date_text = date_text.lower().strip()
    if "сегодня" in date_text or "час" in date_text or "минут" in date_text or "только что" in date_text:
        return today.strftime("%Y-%m-%dT00:00:00+03:00")
    elif "вчера" in date_text:
        return (today - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+03:00")
    elif "недел" in date_text:
        return (today - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00+03:00")
    else:
        nums = re.findall(r'\d+', date_text)
        if nums:
            days = int(nums[0])
            return (today - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00+03:00")
    return today.strftime("%Y-%m-%dT00:00:00+03:00")

def parse_salary_text(text):
    """Parse salary text robustly using specific regex patterns."""
    if not text:
        return None
    text = text.replace('\xa0', ' ').replace('\u202f', ' ').replace('\u2011', ' ')

    # Currency detection
    currency = "RUR"
    if 'USD' in text or '$' in text:
        currency = "USD"
    elif 'EUR' in text or '€' in text:
        currency = "EUR"

    # Pattern 1: "от 150 000 до 300 000 ₽"
    match = re.search(r'от\s+(\d[\d\s]*)\s+до\s+(\d[\d\s]*)', text, re.IGNORECASE)
    if match:
        from_val = int(match.group(1).replace(' ', ''))
        to_val = int(match.group(2).replace(' ', ''))
        return {"from": from_val, "to": to_val, "currency": currency}

    # Pattern 2: "до 200 000 ₽" (but NOT "до вычета налогов" — must have number immediately after)
    match = re.search(r'до\s+(\d[\d\s]*)', text, re.IGNORECASE)
    if match:
        val = int(match.group(1).replace(' ', ''))
        return {"to": val, "currency": currency}

    # Pattern 3: "от 150 000 ₽"
    match = re.search(r'от\s+(\d[\d\s]*)', text, re.IGNORECASE)
    if match:
        val = int(match.group(1).replace(' ', ''))
        return {"from": val, "currency": currency}

    # Fallback: extract all numbers, but only if currency symbol present
    if any(c in text for c in ['₽', 'руб', 'USD', 'EUR', '$', '€']):
        nums = re.findall(r'\d[\d\s]*', text)
        nums_clean = [int(n.replace(' ', '')) for n in nums if n.strip().replace(' ', '').isdigit()]
        if nums_clean:
            if len(nums_clean) >= 2:
                return {"from": nums_clean[0], "to": nums_clean[1], "currency": currency}
            else:
                return {"from": nums_clean[0], "currency": currency}

    return None

def find_salary_in_card(card):
    """Find salary in vacancy card — try multiple selectors."""
    # Primary: data-qa attribute (HH standard)
    sal_tag = card.find("span", attrs={"data-qa": "vacancy-serp__vacancy-compensation"})
    if sal_tag:
        txt = sal_tag.get_text(strip=True, separator=' ')
        if txt:
            sal = parse_salary_text(txt)
            if sal:
                return sal

    # Secondary: any span/div containing currency symbols
    currency_keywords = ['\u20bd', '\u0440\u0443\u0431', 'USD', 'EUR', '$', '\u20ac', 'salary', '\u0437\u043f']
    for tag in card.find_all(["span", "div"]):
        txt = tag.get_text(strip=True, separator=' ')
        if txt and any(c in txt for c in currency_keywords):
            if len(txt) < 150:  # reasonable length for salary text
                sal = parse_salary_text(txt)
                if sal:
                    return sal

    # Tertiary: search all text for "от ... до ... ₽" pattern
    full_text = card.get_text(separator=' ', strip=True)
    salary_pattern = re.search(r'\u043e\u0442\s+[\d\s]+[\u20bd\u0440\u0443\u0431]|\u0434\u043e\s+[\d\s]+[\u20bd\u0440\u0443\u0431]|[\d\s]+\s*[\u20bd\u0440\u0443\u0431]', full_text)
    if salary_pattern:
        sal = parse_salary_text(salary_pattern.group())
        if sal:
            return sal

    return None

def matches_query(vacancy_name, query):
    if not vacancy_name or not query:
        return False
    name_lower = vacancy_name.lower()
    query_lower = query.lower()
    # Direct substring match (e.g. "cio" matches "Chief Information Officer (CIO)")
    if query_lower in name_lower:
        return True
    # Word-by-word match: all words from query must be present
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
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
            title = link_tag.get_text(strip=True, separator=' ') if link_tag else "Без названия"
            url = "https://hh.ru/vacancy/{}".format(vid)

            emp_tag = card.find("a", attrs={"data-qa": "vacancy-serp__vacancy-employer"})
            if not emp_tag:
                emp_tag = card.find("div", class_=re.compile(r"employer"))
            employer = emp_tag.get_text(strip=True, separator=' ') if emp_tag else "Неизвестный"

            salary = find_salary_in_card(card)

            # Try to get exact publish date from <time datetime="...">
            published = None
            time_tag = card.find("time")
            if time_tag and time_tag.get("datetime"):
                try:
                    dt_val = time_tag["datetime"]
                    # Validate it's a proper ISO date
                    datetime.fromisoformat(dt_val.replace("+0300", "+03:00"))
                    published = dt_val
                except (ValueError, TypeError):
                    published = None

            # Fallback: text-based relative date
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

def fetch_vacancies(query, area_id, search_period=1):
    return fetch_vacancies_html(query, area_id, search_period)

def _escape_tg(text):
    """Escape special HTML chars for Telegram HTML parse mode."""
    if not text:
        return ""
    return html_module.escape(str(text))


def send_telegram(token, chat_id, message, retries=3):
    if not token or not chat_id:
        print("[Telegram] Пропуск: токен или chat_id не заданы")
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
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    return True
                body = resp.read().decode("utf-8")[:500]
                print("[Telegram HTTP {}] {}".format(resp.status, body))
                return False
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")[:500] if e.read else ""
            print("[Telegram HTTPError] {} — {}".format(e.code, body))
            last_err = e
            # Don't retry on 4xx client errors
            if 400 <= e.code < 500:
                return False
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            print("[Telegram Connection Error] попытка {}/{} — {}".format(attempt, retries, e))
            last_err = e
        except Exception as e:
            print("[Telegram Error] попытка {}/{} — {}".format(attempt, retries, e))
            last_err = e
        if attempt < retries:
            time.sleep(5)
    print("[Telegram] Все {} попытки исчерпаны. Последняя ошибка: {}".format(retries, last_err))
    return False

def cleanup_old_reports(days=7):
    """Remove report files older than N days."""
    cutoff = datetime.now(TZ).replace(tzinfo=None) - timedelta(days=days)
    count = 0
    for f in OUTPUT_DIR.glob("vacancies_*"):
        try:
            # Extract date from filename: vacancies_2026-06-04_11-00.html
            stem = f.stem  # vacancies_2026-06-04_11-00
            parts = stem.split('_')
            if len(parts) >= 3:
                date_str = parts[1]  # 2026-06-04
                file_dt = datetime.strptime(date_str, "%Y-%m-%d")
                if file_dt < cutoff:
                    f.unlink()
                    count += 1
        except Exception as e:
            print("[Cleanup] Ошибка удаления {}: {}".format(f, e))
    if count > 0:
        print("[Cleanup] Удалено {} старых отчётов".format(count))

def _write_last_run(start_ts, new_count, has_new, queries):
    """Write last_run.json so frontend knows the job finished."""
    try:
        last_run = {
            "start_ts": start_ts,
            "finished_at": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S"),
            "new_count": new_count,
            "has_new": has_new,
            "queries": queries,
        }
        path = OUTPUT_DIR / "last_run.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(last_run, f, ensure_ascii=False)
    except Exception as e:
        print("[Scheduler] Ошибка записи last_run: {}".format(e))


def run_monitor_job():
    start_ts = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S")
    print("[Scheduler] === Задача запущена в {} ===".format(datetime.now(TZ).strftime("%H:%M:%S")))
    cfg = load_config()
    if not cfg.get("enabled", True):
        print("[Scheduler] Мониторинг выключен, пропускаем.")
        _write_last_run(start_ts, 0, False, [])
        return
    if cfg.get("only_workdays", True) and not is_workday():
        print("[Scheduler] Выходной, пропускаем.")
        _write_last_run(start_ts, 0, False, [])
        return

    today = datetime.now(TZ)
    date_str = today.strftime("%Y-%m-%d")
    time_str = today.strftime("%H-%M")
    search_period = int(cfg.get("search_period", 1))
    cutoff_date = (today - timedelta(days=search_period - 1)).strftime("%Y-%m-%d")
    print("[Scheduler] Период: {} дн., отсечка: {}".format(search_period, cutoff_date))

    sent_ids = set(cfg.get("sent_vacancies", []))
    all_vacancies = []
    seen_ids = set()

    for query in cfg.get("search_queries", []):
        items = fetch_vacancies(query, cfg["area_id"], search_period=search_period)
        print('[Scheduler] Запрос "{}" -> {} вакансий'.format(query, len(items)))
        for item in items:
            vid = item.get("id")
            published = item.get("published_at", "")[:10]
            if vid and vid not in seen_ids and published >= cutoff_date:
                seen_ids.add(vid)
                all_vacancies.append(item)

    new_vacancies = [v for v in all_vacancies if v.get("id") not in sent_ids]
    print("[Scheduler] Всего за период: {}, Новых: {}".format(len(all_vacancies), len(new_vacancies)))

    if not new_vacancies:
        cfg["sent_vacancies"] = sorted(sent_ids | seen_ids)
        save_config(cfg)
        print("[Scheduler] Нет новых вакансий.")
        _write_last_run(start_ts, 0, False, cfg.get("search_queries", []))
        return

    # Build text report
    lines = []
    lines.append("📋 Новые вакансии ИТ-руководителей в Москве — {}".format(date_str))
    lines.append("Период: {} дн. (с {} по {}) | Найдено: {}".format(search_period, cutoff_date, date_str, len(new_vacancies)))
    lines.append("")
    for v in new_vacancies:
        title = v.get("name", "Без названия")
        employer = v.get("employer", {}).get("name", "Неизвестный")
        url = v.get("alternate_url", "")
        salary = format_salary(v)
        published = format_datetime(v.get("published_at", ""))
        lines.append("• {}".format(title))
        lines.append("  Компания: {}".format(employer))
        lines.append("  Зарплата: {}".format(salary))
        lines.append("  Дата и время публикации: {}".format(published))
        lines.append("  Ссылка: {}".format(url))
        lines.append("")

    text_report = "\n".join(lines)
    txt_filename = "vacancies_{}_{}.txt".format(date_str, time_str)
    txt_path = OUTPUT_DIR / txt_filename
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text_report)

    # Build HTML report with Back button
    items_html = []
    for v in new_vacancies:
        title = v.get("name", "Без названия")
        employer = v.get("employer", {}).get("name", "Неизвестный")
        url = v.get("alternate_url", "")
        salary = format_salary(v)
        published = format_datetime(v.get("published_at", ""))
        items_html.append(
            '<div class="vacancy">\n'
            '  <h3><a href="{}" target="_blank">{}</a></h3>\n'
            '  <p><strong>Компания:</strong> {}</p>\n'
            '  <p><strong>Зарплата:</strong> {}</p>\n'
            '  <p><strong>Дата и время публикации:</strong> {}</p>\n'
            '  <p><a href="{}" target="_blank">Открыть на hh.ru →</a></p>\n'
            '</div>'
            .format(url, title, employer, salary, published, url)
        )

    html = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Вакансии ИТ-руководителей — {}</title>
    <style>
        body{{font-family:Arial,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;color:#333}}
        h1{{color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:10px}}
        .back{{margin-bottom:20px}}
        .back a{{color:#2980b9;text-decoration:none;font-size:1rem}}
        .back a:hover{{text-decoration:underline}}
        .vacancy{{background:#f8f9fa;border-left:4px solid #3498db;padding:15px;margin:15px 0;border-radius:4px}}
        .vacancy h3{{margin:0 0 8px 0}}
        .vacancy h3 a{{color:#2980b9;text-decoration:none}}
        .vacancy h3 a:hover{{text-decoration:underline}}
        .vacancy p{{margin:4px 0;color:#555}}
        .meta{{color:#7f8c8d;font-size:0.9em;margin-top:20px}}
    </style>
</head>
<body>
    <div class="back"><a href="/dashboard">← Назад к отчётам</a></div>
    <h1>📋 Новые вакансии ИТ-руководителей в Москве</h1>
    <p>Период: <strong>{} дн.</strong> (с {} по {}) | Найдено: <strong>{}</strong></p>
    {}
    <p class="meta">Сформировано автоматически {} в {}</p>
</body>
</html>""".format(date_str, search_period, cutoff_date, date_str, len(new_vacancies), "\n".join(items_html), date_str, today.strftime("%H:%M"))

    html_filename = "vacancies_{}_{}.html".format(date_str, time_str)
    html_path = OUTPUT_DIR / html_filename
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Save meta.json
    meta = {
        "date": date_str,
        "time": time_str,
        "period": search_period,
        "cutoff": cutoff_date,
        "count": len(new_vacancies),
        "queries": cfg.get("search_queries", []),
    }
    meta_filename = "vacancies_{}_{}.meta.json".format(date_str, time_str)
    meta_path = OUTPUT_DIR / meta_filename
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Save to config history (survives container restarts)
    report_meta = {
        "date": date_str,
        "time": time_str,
        "period": search_period,
        "count": len(new_vacancies),
        "filename_html": html_filename,
        "filename_txt": txt_filename,
        "html_content": html,
        "txt_content": text_report,
    }
    history = cfg.get("reports_history", [])
    history.append(report_meta)
    if len(history) > 30:
        history = history[-30:]
    cfg["reports_history"] = history

    # Cleanup old reports (keep 7 days)
    cleanup_old_reports(days=7)

    # Send Telegram (read from env)
    token_tg = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    print("[Scheduler] Telegram: token_{} | chat_{}".format(
        "ok" if token_tg else "missing", "ok" if chat_id else "missing"))
    if token_tg and chat_id:
        MAX_LEN = 4000
        header = "📋 Новые вакансии ИТ-руководителей в Москве\nПериод: {} дн. (с {} по {}) | Найдено: {}\n\n".format(search_period, cutoff_date, date_str, len(new_vacancies))
        messages = []
        current = header
        for v in new_vacancies:
            # Escape HTML-sensitive fields for Telegram parse_mode=HTML
            v_name = _escape_tg(v.get("name", "Без названия"))
            v_employer = _escape_tg(v.get("employer", {}).get("name", "Неизвестный"))
            v_salary = _escape_tg(format_salary(v))
            v_date = _escape_tg(format_datetime(v.get("published_at", "")))
            v_url = _escape_tg(v.get("alternate_url", ""))
            block = (
                "• {}\n"
                "  Компания: {}\n"
                "  Зарплата: {}\n"
                "  Дата и время: {}\n"
                "  Ссылка: {}\n\n"
            ).format(v_name, v_employer, v_salary, v_date, v_url)
            if len(current) + len(block) > MAX_LEN:
                messages.append(current)
                current = block
            else:
                current += block
        if current:
            messages.append(current)
        print("[Scheduler] Telegram: {} сообщений, общий размер ~{}".format(
            len(messages), sum(len(m) for m in messages)))
        for i, msg in enumerate(messages, 1):
            ok = send_telegram(token_tg, chat_id, msg)
            print("[Scheduler] Telegram часть {}/{}: {}".format(i, len(messages), "OK" if ok else "ОШИБКА"))
    else:
        print("[Scheduler] Telegram не настроен")

    # Save history
    new_ids = {v.get("id") for v in new_vacancies}
    cfg["sent_vacancies"] = sorted(sent_ids | new_ids)
    save_config(cfg)
    _write_last_run(start_ts, len(new_vacancies), True, cfg.get("search_queries", []))
    print("[Scheduler] Задача завершена. Сохранено {} ID.".format(len(cfg["sent_vacancies"])))

scheduler = BackgroundScheduler(timezone=TZ)

def init_scheduler():
    if scheduler.running:
        print("[Scheduler] Уже запущен.")
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
    print("[Scheduler] Запущен. Ежедневно в {}:{} (MSK)".format(hour, minute))

def update_schedule(new_time):
    try:
        h, m = map(int, new_time.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Hours must be 0-23, minutes 0-59")
        job = scheduler.get_job('vacancy_job')
        if job:
            scheduler.reschedule_job('vacancy_job', trigger='cron', hour=h, minute=m)
            print("[Scheduler] Переназначено на {}:{}".format(h, m))
        else:
            scheduler.add_job(run_monitor_job, 'cron', hour=h, minute=m, id='vacancy_job')
            print("[Scheduler] Добавлена задача на {}:{}".format(h, m))
    except Exception as e:
        print("[Scheduler] Ошибка переназначения: {}".format(e))