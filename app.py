import os
import re
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from config import load_config, save_config
from scheduler import init_scheduler, run_monitor_job, update_schedule

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-12345")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS_HASH = os.environ.get("ADMIN_PASS_HASH", generate_password_hash("admin"))

init_scheduler()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "").strip()
        pwd = request.form.get("password", "")
        if user == ADMIN_USER and check_password_hash(ADMIN_PASS_HASH, pwd):
            session["logged_in"] = True
            session["user"] = user
            return redirect(url_for("dashboard"))
        flash("Неверный логин или пароль", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def _get_reports_list(cfg=None):
    """Get deduplicated reports list from both files and history."""
    if cfg is None:
        cfg = load_config()
    reports_dir = Path("reports")
    cutoff = datetime.now() - timedelta(days=7)

    # Use dict for deduplication by filename
    reports_by_file = {}

    # 1. Reports from disk files
    for f in reports_dir.glob("*.html"):
        try:
            parts = f.stem.split('_')
            if len(parts) >= 3:
                date_str = parts[1]
                file_dt = datetime.strptime(date_str, "%Y-%m-%d")
                if file_dt >= cutoff:
                    count = None
                    period = None
                    meta_path = f.with_suffix(".meta.json")
                    if meta_path.exists():
                        try:
                            with open(meta_path, "r", encoding="utf-8") as fp:
                                meta = json.load(fp)
                                count = meta.get("count")
                                period = meta.get("period")
                        except:
                            pass
                    reports_by_file[f.name] = {
                        "date": date_str,
                        "time": parts[2] if len(parts) > 2 else "",
                        "filename": f.name,
                        "count": count,
                        "period": period,
                        "source": "file"
                    }
        except Exception as e:
            print("[Reports] Ошибка парсинга файла {}: {}".format(f, e))

    # 2. Reports from history (only those NOT already on disk)
    for h in cfg.get("reports_history", []):
        fname = h.get("filename_html", "")
        if fname and fname not in reports_by_file:
            try:
                h_date = datetime.strptime(h.get("date", ""), "%Y-%m-%d")
                if h_date >= cutoff:
                    reports_by_file[fname] = {
                        "date": h.get("date"),
                        "time": h.get("time", ""),
                        "filename": fname,
                        "count": h.get("count"),
                        "period": h.get("period"),
                        "source": "history"
                    }
            except:
                pass

    # Sort by date+time descending
    reports = list(reports_by_file.values())
    reports.sort(key=lambda x: "{}_{}".format(x["date"], x["time"]), reverse=True)
    return reports

@app.route("/dashboard")
@login_required
def dashboard():
    cfg = load_config()
    reports = _get_reports_list(cfg)

    telegram_ok = bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    period_labels = {1: "Сутки", 3: "3 дня", 7: "Неделя", 30: "Месяц"}
    period_label = period_labels.get(int(cfg.get("search_period", 1)), "Сутки")

    return render_template("dashboard.html", cfg=cfg, reports=reports, telegram_ok=telegram_ok, period_label=period_label)

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    cfg = load_config()
    if request.method == "POST":
        time_str = request.form.get("schedule_time", "09:00").strip()
        if not re.match(r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$", time_str):
            flash("Неверный формат времени. Используйте ЧЧ:ММ (00:00 - 23:59)", "danger")
            return redirect(url_for("settings"))

        cfg["area_id"] = request.form.get("area_id", "1").strip()
        cfg["per_page"] = int(request.form.get("per_page", 100))
        cfg["schedule_time"] = time_str
        cfg["search_period"] = int(request.form.get("search_period", 1))
        cfg["enabled"] = request.form.get("enabled") == "on"
        cfg["only_workdays"] = request.form.get("only_workdays") == "on"

        queries_raw = request.form.get("search_queries", "")
        cfg["search_queries"] = [q.strip() for q in queries_raw.replace('\r\n', '\n').split('\n') if q.strip()]

        save_config(cfg)
        update_schedule(cfg["schedule_time"])
        flash("Настройки сохранены. Запросов: {} | Время: {} | Период: {} дн.".format(
            len(cfg["search_queries"]), cfg["schedule_time"], cfg["search_period"]), "success")
        return redirect(url_for("settings"))

    telegram_ok = bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    search_queries_text = "\n".join(cfg.get("search_queries", []))
    return render_template("settings.html", cfg=cfg, telegram_ok=telegram_ok, search_queries_text=search_queries_text)

@app.route("/run-now", methods=["POST"])
@login_required
def run_now():
    def _job():
        try:
            run_monitor_job(force=True)
        except Exception as e:
            print("[Run-Now] Ошибка в фоне: {}".format(e))

    threading.Thread(target=_job, daemon=True).start()
    flash("Проверка запущена в фоновом режиме. Результат появится через 1\u20132 минуты.", "info")
    return redirect(url_for("dashboard"))

@app.route("/reports/<filename>")
@login_required
def view_report(filename):
    file_path = Path("reports") / filename
    if file_path.exists():
        return send_from_directory("reports", filename)

    cfg = load_config()
    for h in cfg.get("reports_history", []):
        if h.get("filename_html") == filename:
            return h.get("html_content", "<html><body>Отч\u0451т не найден</body></html>")
    for h in cfg.get("reports_history", []):
        if h.get("filename_txt") == filename:
            return h.get("txt_content", "Отч\u0451т не найден"), 200, {"Content-Type": "text/plain; charset=utf-8"}
    return "Отч\u0451т не найден", 404

@app.route("/api/status")
@login_required
def api_status():
    cfg = load_config()
    telegram_ok = bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    return jsonify({
        "enabled": cfg.get("enabled", True),
        "schedule_time": cfg.get("schedule_time", "09:00"),
        "only_workdays": cfg.get("only_workdays", True),
        "queries_count": len(cfg.get("search_queries", [])),
        "telegram_ok": telegram_ok,
        "search_period": cfg.get("search_period", 1),
    })

@app.route("/api/reports")
@login_required
def api_reports():
    reports = _get_reports_list()
    # Return simplified format for JS
    result = []
    for r in reports:
        result.append({
            "date": r["date"],
            "filename": r["filename"],
            "count": r["count"],
            "period": r["period"],
        })
    return jsonify(result)

@app.route("/api/last_run")
@login_required
def api_last_run():
    last_run_path = Path("reports") / "last_run.json"
    if last_run_path.exists():
        try:
            with open(last_run_path, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception:
            pass
    return jsonify({"start_ts": None, "finished_at": None, "new_count": 0, "has_new": False})

@app.route("/api/run", methods=["POST"])
@login_required
def api_run():
    try:
        threading.Thread(target=lambda: run_monitor_job(force=True), daemon=True).start()
        return jsonify({"status": "ok", "message": "Задача запущена в фоне"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
