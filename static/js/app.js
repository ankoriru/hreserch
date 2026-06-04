// Dashboard auto-refresh for reports list
let _pollInterval = null;
let _pollCount = 0;
const MAX_POLLS = 60; // 60 * 3sec = 3 minutes max
let _runStartTime = null;
let _lastReportCount = 0;

function refreshReports() {
    fetch('/api/reports')
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById('reports-tbody');
            const emptyAlert = document.getElementById('reports-empty');
            if (!tbody) return;

            // Check if a NEW report appeared (by comparing count)
            const currentCount = data ? data.length : 0;
            const hasNewReport = currentCount > _lastReportCount;
            if (currentCount > 0) {
                _lastReportCount = currentCount;
            }

            // Build HTML rows
            let html = '';
            if (data && data.length > 0) {
                data.sort((a, b) => {
                    const da = (a.date || '') + '_' + (a.filename || '');
                    const db = (b.date || '') + '_' + (b.filename || '');
                    return db.localeCompare(da);
                });
                data.forEach(r => {
                    const dateStr = r.date || '';
                    let timeStr = '';
                    if (r.filename) {
                        const parts = r.filename.replace('.html', '').split('_');
                        if (parts.length >= 3) {
                            const t = parts[2]; // 11-00
                            timeStr = t.substring(0, 2) + ':' + t.substring(3);
                        }
                    }
                    const dateTime = dateStr + (timeStr ? ' ' + timeStr : '');
                    const period = r.period || '\u2014';
                    const count = r.count !== null && r.count !== undefined ? r.count : '\u2014';
                    html += '<tr onclick="window.open(\'/reports/' + r.filename + '\', \'_blank\')" style="cursor:pointer">' +
                        '<td>' + dateTime + '</td>' +
                        '<td>' + period + ' дн.</td>' +
                        '<td>' + count + '</td>' +
                        '</tr>';
                });
            }

            if (html) {
                tbody.innerHTML = html;
                if (emptyAlert) emptyAlert.style.display = 'none';
            }

            return hasNewReport;
        })
        .then(hasNewReport => {
            // If new report appeared, stop polling and reset button
            if (hasNewReport && _pollInterval) {
                stopPolling('\u2705 \u041e\u0442\u0447\u0451\u0442 \u0441\u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u043d');
            }
        })
        .catch(() => {});
}

function stopPolling(messageText) {
    if (_pollInterval) {
        clearInterval(_pollInterval);
        _pollInterval = null;
    }
    const statusEl = document.getElementById('run-status');
    const btnEl = document.getElementById('run-now-btn');

    if (statusEl) {
        if (messageText) {
            statusEl.innerHTML = '<span class="text-success">' + messageText + '</span>';
            // Clear success message after 5 seconds
            setTimeout(() => {
                if (statusEl) statusEl.style.display = 'none';
            }, 5000);
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
    _runStartTime = Date.now();

    // Fetch current report count before starting
    fetch('/api/reports')
        .then(r => r.json())
        .then(data => {
            _lastReportCount = data ? data.length : 0;
        })
        .catch(() => { _lastReportCount = 0; })
        .finally(() => {
            _pollInterval = setInterval(() => {
                _pollCount++;
                refreshReports();

                // Max polling reached — stop and show "no new vacancies" message
                if (_pollCount >= MAX_POLLS) {
                    stopPolling('\u2139\ufe0f \u041d\u043e\u0432\u044b\u0445 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0439 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e');
                }
            }, 3000);
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
            // Start polling for new reports
            startPolling();
        })
        .catch(e => {
            alert('\u041e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u043f\u0443\u0441\u043a\u0430: ' + e);
            stopPolling(null);
        });
}

// Auto-refresh dashboard status every 30 seconds
function refreshStatus() {
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            // Could update DOM elements here if needed
        })
        .catch(() => {});
}

if (document.querySelector('.dashboard-page') || document.getElementById('reports-tbody')) {
    setInterval(refreshStatus, 30000);
    // Initial load of report count
    fetch('/api/reports')
        .then(r => r.json())
        .then(data => { _lastReportCount = data ? data.length : 0; })
        .catch(() => {});
}

// Confirm dangerous actions
document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', e => {
        if (!confirm(el.dataset.confirm)) {
            e.preventDefault();
        }
    });
});
