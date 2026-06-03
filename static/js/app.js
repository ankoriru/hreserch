// Auto-refresh dashboard status every 30 seconds
function refreshStatus() {
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            // Could update DOM elements here if needed
        })
        .catch(() => {});
}

if (document.querySelector('.dashboard-page')) {
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
