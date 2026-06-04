// Dashboard auto-refresh for reports list
let _pollInterval = null;
let _pollCount = 0;
const MAX_POLLS = 60; // 60 * 3sec = 3 minutes max

function refreshReports() {
    fetch('/api/reports')
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById('reports-tbody');
            const emptyAlert = document.getElementById('reports-empty');
            if (!tbody) return;

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
                    // Extract time from filename: vacancies_2026-06-04_11-00.html
                    if (r.filename) {
                        const parts = r.filename.replace('.html', '').split('_');
                        if (parts.length >= 3) {
                            const t = parts[2]; // 11-00
                            timeStr = t.substring(0, 2) + ':' + t.substring(3);
                        }
                    }
                    const dateTime = dateStr + (timeStr ? ' ' + timeStr : '');
                    const period = r.period || '—';
                    const count = r.count !== null && r.count !== undefined ? r.count : '—';
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
        })
        .catch(() => {});
}

function startPolling() {
    if (_pollInterval) clearInterval(_pollInterval);
    _pollCount = 0;
    _pollInterval = setInterval(() => {
        _pollCount++;
        refreshReports();
        if (_pollCount >= MAX_POLLS) {
            clearInterval(_pollInterval);
            _pollInterval = null;
            // Hide status
            const statusEl = document.getElementById('run-status');
            const btnEl = document.getElementById('run-now-btn');
            if (statusEl) statusEl.style.display = 'none';
            if (btnEl) {
                btnEl.disabled = false;
                btnEl.textContent = '▶ Запустить сейчас';
            }
        }
    }, 3000);
}

function runNow() {
    if (!confirm('Запустить проверку вакансий прямо сейчас?')) return;

    const btnEl = document.getElementById('run-now-btn');
    const statusEl = document.getElementById('run-status');

    if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = '⏳ Запуск...';
    }
    if (statusEl) statusEl.style.display = 'inline';

    fetch('/api/run', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (btnEl) btnEl.textContent = '⏳ Выполняется...';
            // Start polling for new reports
            startPolling();
        })
        .catch(e => {
            alert('Ошибка запуска: ' + e);
            if (btnEl) {
                btnEl.disabled = false;
                btnEl.textContent = '▶ Запустить сейчас';
            }
            if (statusEl) statusEl.style.display = 'none';
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
}

// Confirm dangerous actions
document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', e => {
        if (!confirm(el.dataset.confirm)) {
            e.preventDefault();
        }
    });
});
