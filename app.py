import os
from datetime import datetime
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from config import load_config, save_config
from scheduler import init_scheduler, run_monitor_job, update_schedule

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-12345")

# Admin credentials from env or default (change in production!)
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS_HASH = os.environ.get("ADMIN_PASS_HASH", generate_password_hash("admin"))

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
    reports_dir = Path("reports")
    reports = sorted(reports_dir.glob("*.html"), reverse=True)
    report_list = []
    for r in reports:
        date_part = r.stem.replace("vacancies_", "")
        report_list.append({"date": date_part, "filename": r.name})
    return render_template("dashboard.html", cfg=cfg, reports=report_list)

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    cfg = load_config()
    if request.method == "POST":
        cfg["telegram_bot_token"] = request.form.get("telegram_bot_token", "").strip()
        cfg["telegram_chat_id"] = request.form.get("telegram_chat_id", "").strip()
        cfg["area_id"] = request.form.get("area_id", "1").strip()
        cfg["per_page"] = int(request.form.get("per_page", 100))
        cfg["schedule_time"] = request.form.get("schedule_time", "09:00").strip()
        cfg["enabled"] = request.form.get("enabled") == "on"
        cfg["only_workdays"] = request.form.get("only_workdays") == "on"

        queries_raw = request.form.get("search_queries", "")
        cfg["search_queries"] = [q.strip() for q in queries_raw.splitlines() if q.strip()]

        save_config(cfg)
        update_schedule(cfg["schedule_time"])
        flash("Настройки сохранены", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html", cfg=cfg)

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
    return send_from_directory("reports", filename)

@app.route("/api/status")
@login_required
def api_status():
    cfg = load_config()
    return jsonify({
        "enabled": cfg.get("enabled", True),
        "schedule_time": cfg.get("schedule_time", "09:00"),
        "only_workdays": cfg.get("only_workdays", True),
        "queries_count": len(cfg.get("search_queries", [])),
    })

@app.route("/api/reports")
@login_required
def api_reports():
    reports_dir = Path("reports")
    reports = sorted(reports_dir.glob("*.html"), reverse=True)
    return jsonify([{"date": r.stem.replace("vacancies_", ""), "filename": r.name} for r in reports])

if __name__ == "__main__":
    init_scheduler()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
