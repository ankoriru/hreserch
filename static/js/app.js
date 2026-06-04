// Dashboard: report polling and auto-refresh
let _pollInterval = null;
let _pollCount = 0;
const MAX_POLLS = 60; // 60 * 3sec = 3 minutes max
let _knownFilenames = new Set(); // filenames known before run

function renderReportRow(r) {
    const dateStr = r.date || '';
    let timeStr = '';
    if (r.filename) {
        const parts = r.filename.replace('.html', '').split('_');
        if (parts.length >= 3) {
            const t = parts[2]; // e.g. "11-00"
            timeStr = t.substring(0, 2) + ':' + t.substring(3);
        }
    }
    const dateTime = dateStr + (timeStr ? ' ' + timeStr : '');
    const period = (r.period !== null && r.period !== undefined) ? r.period : '\u2014';
    const count = (r.count !== null && r.count !== undefined) ? r.count : '\u2014';
    return '<tr onclick="window.open(\'/reports/' + encodeURIComponent(r.filename) + '\', \'_blank\')" style="cursor:pointer">' +
        '<td>' + dateTime + '</td>' +
        '<td>' + period + ' \u0434\u043d.</td>' +
        '<td>' + count + '</td>' +
        '</tr>';
}

function updateTable(data) {
    const tbody = document.getElementById('reports-tbody');
    const emptyAlert = document.getElementById('reports-empty');
    if (!tbody) return;

    if (data && data.length > 0) {
        data.sort((a, b) => {
            const da = (a.date || '') + '_' + (a.filename || '');
            const db = (b.date || '') + '_' + (b.filename || '');
            return db.localeCompare(da);
        });
        tbody.innerHTML = data.map(renderReportRow).join('');
        if (emptyAlert) emptyAlert.style.display = 'none';
    } else {
        tbody.innerHTML = '';
        if (emptyAlert) emptyAlert.style.display = '';
    }
}

function findNewReport(data) {
    // Check if any report filename is NOT in our known set
    if (!data) return null;
    for (const r of data) {
        if (r.filename && !_knownFilenames.has(r.filename)) {
            return r;
        }
    }
    return null;
}

function checkReports() {
    fetch('/api/reports')
        .then(r => r.json())
        .then(data => {
            // Always update table with latest data
            updateTable(data);

            // Check if a new report appeared (by filename, not count)
            const newReport = findNewReport(data);
            if (newReport) {
                stopPolling('\u2705 \u041e\u0442\u0447\u0451\u0442 \u0441\u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u043d', 5000);
                return;
            }

            _pollCount++;
            if (_pollCount >= MAX_POLLS) {
                stopPolling('\u2139\ufe0f \u041d\u043e\u0432\u044b\u0445 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e', 5000);
            }
        })
        .catch(() => {
            _pollCount++;
            if (_pollCount >= MAX_POLLS) {
                stopPolling('\u2139\ufe0f \u041d\u043e\u0432\u044b\u0445 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e', 5000);
            }
        });
}

function stopPolling(messageText, autoHideMs) {
    if (_pollInterval) {
        clearInterval(_pollInterval);
        _pollInterval = null;
    }
    const statusEl = document.getElementById('run-status');
    const btnEl = document.getElementById('run-now-btn');

    if (statusEl) {
        if (messageText) {
            statusEl.innerHTML = '<span class="text-success fw-bold">' + messageText + '</span>';
            if (autoHideMs) {
                setTimeout(() => {
                    const el = document.getElementById('run-status');
                    if (el) el.style.display = 'none';
                }, autoHideMs);
            }
        } else {
            statusEl.style.display = 'none';
        }
    }
    if (btnEl) {
        btnEl.disabled = false;
        btnEl.textContent = '\u25b6 \u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u0441\u0435\u0439\u0447\u0430\u0441';
    }
}

function startPolling() {
    if (_pollInterval) clearInterval(_pollInterval);
    _pollCount = 0;

    // Capture current filenames before starting
    fetch('/api/reports')
        .then(r => r.json())
        .then(data => {
            _knownFilenames = new Set();
            if (data) {
                data.forEach(r => { if (r.filename) _knownFilenames.add(r.filename); });
            }
            console.log('[Polling] Known reports before run:', _knownFilenames.size);

            // Do first check immediately
            checkReports();

            // Then poll every 3 seconds
            _pollInterval = setInterval(checkReports, 3000);
        })
        .catch(() => {
            _knownFilenames = new Set();
            _pollInterval = setInterval(checkReports, 3000);
        });
}

function runNow() {
    if (!confirm('\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439 \u043f\u0440\u044f\u043c\u043e \u0441\u0435\u0439\u0447\u0430\u0441?')) return;

    const btnEl = document.getElementById('run-now-btn');
    const statusEl = document.getElementById('run-status');

    if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = '\u23f3 \u0417\u0430\u043f\u0443\u0441\u043a...';
    }
    if (statusEl) {
        statusEl.style.display = 'inline';
        statusEl.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> \u0412\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430...';
    }

    fetch('/api/run', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (btnEl) btnEl.textContent = '\u23f3 \u0412\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f...';
            startPolling();
        })
        .catch(e => {
            alert('\u041e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u043f\u0443\u0441\u043a\u0430: ' + e);
            stopPolling(null, 0);
        });
}

// Initial table load on page open
function initTable() {
    fetch('/api/reports')
        .then(r => r.json())
        .then(data => { updateTable(data); })
        .catch(() => {});
}

if (document.getElementById('reports-tbody')) {
    initTable();
}

// Confirm dangerous actions
document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', e => {
        if (!confirm(el.dataset.confirm)) {
            e.preventDefault();
        }
    });
});
