/**
 * Stock Tracker Dashboard — Frontend interaction logic
 * Table sorting / filtering / utility functions
 *
 * i18n: Uses window.__i18n (language pack injected from server)
 *       _t(key, replacements) for translations
 */

// ============================================================
// i18n helper — reads from window.__i18n (set by base.html)
// ============================================================
function _t(key, replacements) {
    const pack = window.I18N || {};
    const parts = key.split('.');
    let value = pack;
    for (const p of parts) {
        if (value && typeof value === 'object' && p in value) {
            value = value[p];
        } else {
            return key; // fallback: return key itself
        }
    }
    if (typeof value !== 'string') return key;
    if (replacements) {
        for (const [k, v] of Object.entries(replacements)) {
            value = value.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
        }
    }
    return value;
}

// ============================================================
// Table sorting
// ============================================================
function initTableSort(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const headers = table.querySelectorAll('th[data-sort]');
    let currentSort = { col: null, asc: true };

    headers.forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            const asc = currentSort.col === col ? !currentSort.asc : false;

            headers.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
            th.classList.add(asc ? 'sort-asc' : 'sort-desc');
            currentSort = { col, asc };

            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));

            rows.sort((a, b) => {
                let va = a.dataset[col] || '';
                let vb = b.dataset[col] || '';

                const na = parseFloat(va);
                const nb = parseFloat(vb);
                if (!isNaN(na) && !isNaN(nb)) {
                    return asc ? na - nb : nb - na;
                }

                return asc ? va.localeCompare(vb) : vb.localeCompare(va);
            });

            rows.forEach(row => tbody.appendChild(row));
        });
    });
}

// ============================================================
// Utility functions
// ============================================================
function formatNumber(val, decimals = 1) {
    if (val === null || val === undefined) return '—';
    return Number(val).toFixed(decimals);
}

function formatPct(val) {
    if (val === null || val === undefined) return '—';
    const sign = val > 0 ? '+' : '';
    return `${sign}${Number(val).toFixed(1)}%`;
}

// ============================================================
// Modal control
// ============================================================
function openAddTickerModal() {
    const modal = document.getElementById('addTickerModal');
    const overlay = document.getElementById('modalOverlay');
    if (!modal || !overlay) return;

    const input = document.getElementById('tickerInput');
    const validation = document.getElementById('tickerValidation');
    const btnConfirm = document.getElementById('btnAddConfirm');
    if (input) input.value = '';
    if (validation) { validation.style.display = 'none'; validation.innerHTML = ''; }
    if (btnConfirm) btnConfirm.disabled = true;

    window._tickerValidationData = null;

    modal.style.display = 'block';
    overlay.style.display = 'block';
    if (input) input.focus();
}

function closeModal() {
    const modal = document.getElementById('addTickerModal');
    const overlay = document.getElementById('modalOverlay');
    if (modal) modal.style.display = 'none';
    if (overlay) overlay.style.display = 'none';
}

// ESC to close modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});

// ============================================================
// Ticker validation
// ============================================================
async function checkTicker() {
    const input = document.getElementById('tickerInput');
    const validation = document.getElementById('tickerValidation');
    const btnCheck = document.getElementById('btnCheck');
    const btnConfirm = document.getElementById('btnAddConfirm');

    const symbol = (input ? input.value.trim().toUpperCase() : '');
    if (!symbol) {
        showValidation('error', _t('js.enter_ticker'));
        return;
    }

    // loading state
    btnCheck.disabled = true;
    btnCheck.textContent = _t('modal.btn_checking');
    btnConfirm.disabled = true;
    window._tickerValidationData = null;
    showValidation('loading', _t('js.checking_ticker', { symbol }));

    try {
        const resp = await fetch(`/api/tickers/check/${encodeURIComponent(symbol)}`);
        const data = await resp.json();

        if (!resp.ok) {
            showValidation('error', data.detail || _t('js.check_failed'));
            return;
        }

        if (data.exists && data.enabled) {
            showValidation('warn', data.message || _t('js.already_in_list', { symbol }));
            return;
        }

        if (data.exists && !data.enabled) {
            const info = `<strong>${data.symbol}</strong> — ${data.name || ''}`;
            const extra = data.has_price_data ? `<br><span class="text-secondary">${_t('js.has_history')}</span>` : '';
            showValidation('restore', `${info}<br>${data.message || ''}${extra}`);
            window._tickerValidationData = data;
            btnConfirm.disabled = false;
            return;
        }

        if (data.valid) {
            let html = `<strong>${data.symbol}</strong>`;
            if (data.name) html += ` — ${data.name}`;
            if (data.sector) html += `<br><span class="text-secondary">${_t('js.sector_label', { sector: data.sector })}</span>`;
            if (data.exchange) html += ` · <span class="text-secondary">${_t('js.exchange_label', { exchange: data.exchange })}</span>`;
            if (data.market_price) html += `<br><span class="text-secondary">${_t('js.current_price', { price: Number(data.market_price).toFixed(2) })}</span>`;
            showValidation('success', html);
            window._tickerValidationData = data;
            btnConfirm.disabled = false;
        } else {
            showValidation('error', data.error || _t('js.check_error'));
        }

    } catch (err) {
        showValidation('error', _t('js.network_error', { msg: err.message }));
    } finally {
        btnCheck.disabled = false;
        btnCheck.textContent = _t('modal.btn_check');
    }
}

function showValidation(type, html) {
    const el = document.getElementById('tickerValidation');
    if (!el) return;
    el.style.display = 'block';
    el.className = `ticker-validation validation-${type}`;
    el.innerHTML = html;
}

// ============================================================
// Confirm add ticker
// ============================================================
async function confirmAddTicker() {
    const btnConfirm = document.getElementById('btnAddConfirm');
    const data = window._tickerValidationData;
    if (!data) return;

    btnConfirm.disabled = true;
    btnConfirm.textContent = _t('modal.btn_adding');
    showValidation('loading', _t('js.adding_msg', { symbol: data.symbol }));

    try {
        const resp = await fetch('/api/tickers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                symbol: data.symbol,
                name: data.name || null,
                sector: data.sector || null,
            }),
        });
        const result = await resp.json();

        if (!resp.ok) {
            showValidation('error', result.detail || _t('js.add_failed'));
            btnConfirm.disabled = false;
            btnConfirm.textContent = _t('modal.btn_add');
            return;
        }

        // success
        showValidation('success',
            `${_t('js.add_success', { msg: result.message || `"${data.symbol}" added` })}<br>` +
            `<span class="text-secondary">${_t('js.page_refreshing')}</span>`
        );

        setTimeout(() => {
            window.location.reload();
        }, 1200);

    } catch (err) {
        showValidation('error', `${_t('js.add_failed')}: ${err.message}`);
        btnConfirm.disabled = false;
        btnConfirm.textContent = _t('modal.btn_add');
    }
}

// ============================================================
// Remove ticker
// ============================================================
async function removeTicker(symbol, name) {
    const displayName = name ? `${symbol} (${name})` : symbol;
    if (!confirm(_t('js.confirm_remove', { name: displayName }))) {
        return;
    }

    try {
        const resp = await fetch(`/api/tickers/${encodeURIComponent(symbol)}`, {
            method: 'DELETE',
        });
        const result = await resp.json();

        if (!resp.ok) {
            alert(result.detail || _t('js.remove_failed'));
            return;
        }

        // Remove row with animation
        const row = document.querySelector(`tr[data-symbol="${symbol}"]`);
        if (row) {
            row.style.transition = 'opacity 0.3s, transform 0.3s';
            row.style.opacity = '0';
            row.style.transform = 'translateX(20px)';
            setTimeout(() => row.remove(), 300);
        }
    } catch (err) {
        alert(`${_t('js.remove_failed')}: ${err.message}`);
    }
}

// ============================================================
// Refresh prices (SSE streaming)
// ============================================================
let _refreshInProgress = false;

async function refreshPrices() {
    if (_refreshInProgress) return;
    _refreshInProgress = true;

    const btn = document.getElementById('btnRefreshPrices');
    const panel = document.getElementById('refreshPanel');
    const title = document.getElementById('refreshTitle');
    const status = document.getElementById('refreshStatus');
    const log = document.getElementById('refreshLog');
    const fill = document.getElementById('refreshProgressFill');
    const closeBtn = document.getElementById('refreshCloseBtn');

    // Reset UI
    btn.disabled = true;
    btn.classList.add('refreshing');
    btn.textContent = _t('watchlist.refreshing');
    panel.style.display = 'block';
    title.textContent = _t('watchlist.refresh_panel_title');
    status.textContent = _t('watchlist.refresh_preparing');
    log.innerHTML = '';
    fill.style.width = '0%';
    fill.className = 'refresh-progress-fill';
    closeBtn.style.display = 'none';

    try {
        const resp = await fetch('/api/prices/refresh', { method: 'POST' });

        if (!resp.ok) {
            throw new Error(_t('js.server_error', { status: resp.status }));
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Parse SSE events
            const lines = buffer.split('\n');
            buffer = '';

            let eventType = 'progress';
            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];

                if (line.startsWith('event: ')) {
                    eventType = line.slice(7).trim();
                } else if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        handleRefreshEvent(eventType, data, { status, log, fill, title });
                    } catch (e) {
                        buffer = lines.slice(i).join('\n');
                        break;
                    }
                    eventType = 'progress';
                } else if (line === '') {
                    // empty line = event separator
                } else {
                    buffer = lines.slice(i).join('\n');
                    break;
                }
            }
        }

    } catch (err) {
        status.textContent = _t('js.refresh_failed', { msg: err.message });
        fill.className = 'refresh-progress-fill has-errors';
    } finally {
        _refreshInProgress = false;
        btn.disabled = false;
        btn.classList.remove('refreshing');
        btn.textContent = _t('watchlist.refresh_prices');
        closeBtn.style.display = 'block';
    }
}

function handleRefreshEvent(eventType, data, ui) {
    if (eventType === 'progress') {
        const pct = Math.round((data.current / data.total) * 100);
        ui.fill.style.width = pct + '%';
        ui.status.textContent = `${data.current} / ${data.total} — ${data.symbol} (${data.name || ''})`;

        // Add log entry
        const icon = data.status === 'updated' ? '✅' :
                     data.status === 'skipped' ? '⏭️' : '❌';
        const cls = data.status === 'updated' ? 'log-updated' :
                    data.status === 'skipped' ? 'log-skipped' : 'log-error';
        let detail = '';
        if (data.status === 'updated') {
            detail = _t('js.updated_rows', { count: data.new_rows });
            if (data.strategies_recalculated) detail += ' · ' + _t('js.strategies_recalculated');
        } else if (data.status === 'error') {
            detail = data.error || _t('js.unknown_error');
        } else {
            detail = _t('js.already_latest');
        }

        const logItem = document.createElement('div');
        logItem.className = `log-item ${cls}`;
        logItem.textContent = `${icon} ${data.symbol} — ${detail}`;
        ui.log.appendChild(logItem);
        ui.log.scrollTop = ui.log.scrollHeight;

    } else if (eventType === 'complete') {
        ui.fill.style.width = '100%';
        ui.fill.className = 'refresh-progress-fill ' + (data.errors > 0 ? 'has-errors' : 'done');
        ui.status.textContent =
            _t('js.refresh_done', { updated: data.updated, skipped: data.skipped }) +
            (data.errors > 0 ? _t('js.refresh_failed_count', { errors: data.errors }) : '') +
            _t('js.refresh_recalc', { count: data.strategies_recalculated });

        const titleEl = document.getElementById('refreshTitle');
        titleEl.textContent = data.errors > 0 ? _t('js.refresh_title_partial') : _t('js.refresh_title_done');

        // If updated, prompt to refresh page
        if (data.updated > 0) {
            const hint = document.createElement('div');
            hint.style.cssText = 'margin-top:8px;font-size:13px;color:var(--blue);cursor:pointer;';
            hint.textContent = _t('js.click_refresh');
            hint.onclick = () => window.location.reload();
            ui.log.appendChild(hint);
        }

    } else if (eventType === 'error') {
        ui.fill.className = 'refresh-progress-fill has-errors';
        ui.status.textContent = _t('js.error_prefix', { msg: data.error });
    }
}

function closeRefreshPanel() {
    const panel = document.getElementById('refreshPanel');
    if (panel) {
        panel.style.transition = 'opacity 0.2s';
        panel.style.opacity = '0';
        setTimeout(() => {
            panel.style.display = 'none';
            panel.style.opacity = '1';
            panel.style.transition = '';
        }, 200);
    }
}

// ============================================================
// Page load initialization
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    // Auto-init sorting for all data-tables
    document.querySelectorAll('table.data-table').forEach(table => {
        if (table.id) {
            initTableSort(table.id);
        }
    });

    // Enter key to trigger ticker check
    const tickerInput = document.getElementById('tickerInput');
    if (tickerInput) {
        tickerInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                checkTicker();
            }
        });
    }
});
