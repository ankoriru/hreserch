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
    btn.disabled = !enabled;
    btn.textContent = enabled ? '\u25b6 \u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u0441\u0435\u0439\u0447\u0430\u0441' : '\u23f3 \u0412\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f...';
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
    setButton(true);
    showStatus(statusHtml, autoHideMs);
}

function doPoll() {
    _pollCount++;

    // Always refresh table
    fetch('/api/reports')
        .then(r => r.json())
        .then(data => updateTable(data))
        .catch(() => {});

    // Check if job finished
    fetch('/api/last_run')
        .then(r => r.json())
        .then(lr => {
            if (lr.finished_at && lr.start_ts >= _runStartTime) {
                if (lr.has_new) {
                    stopAll('<span class="text-success fw-bold">\u2705 \u041e\u0442\u0447\u0451\u0442 \u0441\u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u043d</span>', 5000);
                } else {
                    stopAll('<span class="text-info fw-bold">\u2139\ufe0f \u041d\u043e\u0432\u044b\u0445 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e</span>', 5000);
                }
                return;
            }
            if (_pollCount >= MAX_POLLS) {
                stopAll('<span class="text-muted">\u23f0 \u0417\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e</span>', 3000);
            }
        })
        .catch(() => {
            if (_pollCount >= MAX_POLLS) {
                stopAll('<span class="text-muted">\u23f0 \u0417\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e</span>', 3000);
            }
        });
}

function startPolling() {
    if (_pollInterval) clearInterval(_pollInterval);
    _pollCount = 0;
    _runStartTime = new Date().toISOString().slice(0, 19);
    doPoll();
    _pollInterval = setInterval(doPoll, 3000);
}

function runNow() {
    if (!confirm('\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443?')) return;
    setButton(false);
    showStatus('<span class="spinner-border spinner-border-sm"></span> \u0412\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f...', 0);
    fetch('/api/run', { method: 'POST' })
        .then(r => r.json())
        .then(() => startPolling())
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
