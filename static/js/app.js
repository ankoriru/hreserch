// Dashboard: polling with button locked until report appears
let _pollInterval = null;
let _pollCount = 0;
const MAX_POLLS = 60;
let _runStartTime = null;

function renderRow(r) {
    const dateStr = r.date || '';
    let timeStr = '';
    if (r.filename) {
        const parts = r.filename.replace('.html', '').split('_');
        if (parts.length >= 3) {
            const t = parts[2];
            timeStr = t.substring(0, 2) + ':' + t.substring(3);
        }
    }
    const dateTime = dateStr + (timeStr ? ' ' + timeStr : '');
    const period = (r.period !== null && r.period !== undefined) ? r.period : '\u2014';
    const count = (r.count !== null && r.count !== undefined) ? r.count : '\u2014';
    return '<tr onclick="window.open(\'/reports/' + encodeURIComponent(r.filename) + '\', \'_blank\')">' +
        '<td>' + dateTime + '</td><td>' + period + ' \u0434\u043d.</td><td>' + count + '</td></tr>';
}

function updateTable(data) {
    const tbody = document.getElementById('reports-tbody');
    const emptyAlert = document.getElementById('reports-empty');
    if (!tbody) return false;
    if (data && data.length > 0) {
        data.sort((a, b) => {
            const da = (a.date || '') + '_' + (a.filename || '');
            const db = (b.date || '') + '_' + (b.filename || '');
            return db.localeCompare(da);
        });
        tbody.innerHTML = data.map(renderRow).join('');
        if (emptyAlert) emptyAlert.style.display = 'none';
        return true;
    } else {
        tbody.innerHTML = '';
        if (emptyAlert) emptyAlert.style.display = '';
        return false;
    }
}

function setButton(enabled) {
    const btn = document.getElementById('run-now-btn');
    if (!btn) return;
    btn.style.display = enabled ? '' : 'none';
}

function showStatus(html, autoHideMs) {
    const el = document.getElementById('run-status');
    if (!el) return;
    el.style.display = 'inline';
    el.innerHTML = html;
    if (autoHideMs) {
        setTimeout(() => { const e = document.getElementById('run-status'); if (e) e.style.display = 'none'; }, autoHideMs);
    }
}

function stopAll(statusHtml, autoHideMs) {
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
    // Final table refresh before showing status
    fetch('/api/reports')
        .then(r => r.json())
        .then(data => { updateTable(data); })
        .catch(() => {})
        .finally(() => {
            setButton(true);
            showStatus(statusHtml, autoHideMs);
        });
}

function doPoll() {
    _pollCount++;
    
    // Fetch reports AND last_run in parallel, wait for both
    Promise.all([
        fetch('/api/reports').then(r => r.json()).catch(() => []),
        fetch('/api/last_run').then(r => r.json()).catch(() => ({}))
    ]).then(([reports, lr]) => {
        // Update table first
        updateTable(reports);
        
        // Check if our job finished
        if (lr.start_ts && lr.start_ts >= _runStartTime && lr.finished_at) {
            if (lr.error) {
                stopAll('<span class="text-danger fw-bold">\u274c Ошибка: ' + String(lr.error).substring(0, 80) + '</span>', 8000);
            } else if (lr.has_new) {
                stopAll('<span class="text-success fw-bold">\u2705 Отчёт сформирован</span>', 5000);
            } else {
                stopAll('<span class="text-info fw-bold">\u2139\ufe0f Новых вакансий не найдено</span>', 5000);
            }
            return;
        }
        // Max polls reached
        if (_pollCount >= MAX_POLLS) {
            stopAll('<span class="text-muted">\u23f0 Проверка заняла слишком долго, попробуйте позже</span>', 8000);
        }
    }).catch(() => {
        if (_pollCount >= MAX_POLLS) {
            stopAll('<span class="text-muted">\u23f0 Завершено</span>', 3000);
        }
    });
}

function startPolling(serverStartTs) {
    if (_pollInterval) clearInterval(_pollInterval);
    _pollCount = 0;
    _runStartTime = serverStartTs;
    doPoll();
    _pollInterval = setInterval(doPoll, 3000);
}

function runNow() {
    if (!confirm('\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443?')) return;
    setButton(false);
    showStatus('<span class="spinner-border spinner-border-sm"></span> \u0412\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f...', 0);
    fetch('/api/run', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            const serverTs = data.start_ts || new Date().toISOString().slice(0, 19);
            startPolling(serverTs);
        })
        .catch(e => { alert('\u041e\u0448\u0438\u0431\u043a\u0430: ' + e); stopAll(null, 0); });
}

// Initial load
function initTable() {
    fetch('/api/reports').then(r => r.json()).then(d => updateTable(d)).catch(() => {});
}
if (document.getElementById('reports-tbody')) initTable();

// Confirm dangerous actions
document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', e => { if (!confirm(el.dataset.confirm)) e.preventDefault(); });
});
