import os
import re
from datetime import datetime
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

@app.route("/dashboard")
@login_required
def dashboard():
    cfg = load_config()

    # Combine file reports and history reports
    reports_dir = Path("reports")
    file_reports = sorted(reports_dir.glob("*.html"), reverse=True)

    # Build report list from files + history
    report_list = []
    seen_files = set()

    for r in file_reports:
        date_part = r.stem.replace("vacancies_", "")
        seen_files.add(r.name)
        report_list.append({
            "date": date_part,
            "filename": r.name,
            "source": "file"
        })

    # Add history reports that don't exist as files
    for h in cfg.get("reports_history", [])[::-1]:
        if h.get("filename_html") not in seen_files:
            report_list.append({
                "date": h.get("date"),
                "filename": h.get("filename_html"),
                "count": h.get("count"),
                "source": "history"
            })

    telegram_ok = bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    hh_token_ok = bool(cfg.get("hh_access_token", "").strip())
    period_labels = {1: "Сутки", 3: "3 дня", 7: "Неделя", 30: "Месяц"}
    period_label = period_labels.get(int(cfg.get("search_period", 1)), "Сутки")

    return render_template("dashboard.html", cfg=cfg, reports=report_list, telegram_ok=telegram_ok, hh_token_ok=hh_token_ok, period_label=period_label)

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
        cfg["hh_access_token"] = request.form.get("hh_access_token", "").strip()
        cfg["enabled"] = request.form.get("enabled") == "on"
        cfg["only_workdays"] = request.form.get("only_workdays") == "on"

        # CRITICAL FIX: properly parse textarea lines
        queries_raw = request.form.get("search_queries", "")
        # Split by newlines, strip each, filter empty
        cfg["search_queries"] = [q.strip() for q in queries_raw.replace('\r\n', '\n').split('\n') if q.strip()]

        save_config(cfg)
        update_schedule(cfg["schedule_time"])
        flash("Настройки сохранены. Запросы: {}".format(len(cfg["search_queries"])), "success")
        return redirect(url_for("settings"))

    telegram_ok = bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    # Prepare search_queries as newline-separated string for textarea
    search_queries_text = "\n".join(cfg.get("search_queries", []))
    return render_template("settings.html", cfg=cfg, telegram_ok=telegram_ok, search_queries_text=search_queries_text)

@app.route("/run-now", methods=["POST"])
@login_required
def run_now():
    try:
        run_monitor_job()
        flash("Проверка выполнена успешно", "success")
    except Exception as e:
        flash("Ошибка при выполнении: {}".format(e), "danger")
    return redirect(url_for("dashboard"))

@app.route("/reports/<filename>")
@login_required
def view_report(filename):
    # Check if file exists on disk
    file_path = Path("reports") / filename
    if file_path.exists():
        return send_from_directory("reports", filename)

    # Check if in history (for HTML reports)
    cfg = load_config()
    for h in cfg.get("reports_history", []):
        if h.get("filename_html") == filename:
            return h.get("html_content", "<html><body>Отчёт не найден</body></html>")

    # Check TXT in history
    for h in cfg.get("reports_history", []):
        if h.get("filename_txt") == filename:
            return h.get("txt_content", "Отчёт не найден"), 200, {"Content-Type": "text/plain; charset=utf-8"}

    return "Отчёт не найден", 404

@app.route("/api/status")
@login_required
def api_status():
    cfg = load_config()
    telegram_ok = bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    hh_token_ok = bool(cfg.get("hh_access_token", "").strip())
    return jsonify({
        "enabled": cfg.get("enabled", True),
        "schedule_time": cfg.get("schedule_time", "09:00"),
        "only_workdays": cfg.get("only_workdays", True),
        "queries_count": len(cfg.get("search_queries", [])),
        "telegram_ok": telegram_ok,
        "hh_token_ok": hh_token_ok,
        "search_period": cfg.get("search_period", 1),
    })

@app.route("/api/reports")
@login_required
def api_reports():
    cfg = load_config()
    reports_dir = Path("reports")
    file_reports = sorted(reports_dir.glob("*.html"), reverse=True)
    result = []
    for r in file_reports:
        result.append({"date": r.stem.replace("vacancies_", ""), "filename": r.name, "source": "file"})
    for h in cfg.get("reports_history", [])[::-1]:
        result.append({
            "date": h.get("date"),
            "filename": h.get("filename_html"),
            "count": h.get("count"),
            "source": "history"
        })
    return jsonify(result)

@app.route("/api/run", methods=["POST"])
@login_required
def api_run():
    try:
        run_monitor_job()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
