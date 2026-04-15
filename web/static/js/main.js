/**
 * Stock Tracker Dashboard — 前端交互逻辑
 * 表格排序 / 筛选 / 工具函数
 */

// ============================================================
// 表格排序
// ============================================================
function initTableSort(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;

    const headers = table.querySelectorAll('th[data-sort]');
    let currentSort = { col: null, asc: true };

    headers.forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            const asc = currentSort.col === col ? !currentSort.asc : false; // 默认降序

            // 更新排序指示器
            headers.forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
            th.classList.add(asc ? 'sort-asc' : 'sort-desc');
            currentSort = { col, asc };

            // 排序行
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));

            rows.sort((a, b) => {
                let va = a.dataset[col] || '';
                let vb = b.dataset[col] || '';

                // 尝试数字排序
                const na = parseFloat(va);
                const nb = parseFloat(vb);
                if (!isNaN(na) && !isNaN(nb)) {
                    return asc ? na - nb : nb - na;
                }

                // 字符串排序
                return asc ? va.localeCompare(vb) : vb.localeCompare(va);
            });

            rows.forEach(row => tbody.appendChild(row));
        });
    });
}

// ============================================================
// 工具函数
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
// Modal 弹窗控制
// ============================================================
function openAddTickerModal() {
    const modal = document.getElementById('addTickerModal');
    const overlay = document.getElementById('modalOverlay');
    if (!modal || !overlay) return;

    // 重置状态
    const input = document.getElementById('tickerInput');
    const validation = document.getElementById('tickerValidation');
    const btnConfirm = document.getElementById('btnAddConfirm');
    if (input) input.value = '';
    if (validation) { validation.style.display = 'none'; validation.innerHTML = ''; }
    if (btnConfirm) btnConfirm.disabled = true;

    // 清除缓存的验证数据
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

// ESC 关闭 modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});

// ============================================================
// Ticker 验证
// ============================================================
async function checkTicker() {
    const input = document.getElementById('tickerInput');
    const validation = document.getElementById('tickerValidation');
    const btnCheck = document.getElementById('btnCheck');
    const btnConfirm = document.getElementById('btnAddConfirm');

    const symbol = (input ? input.value.trim().toUpperCase() : '');
    if (!symbol) {
        showValidation('error', '请输入 ticker 代码');
        return;
    }

    // loading 状态
    btnCheck.disabled = true;
    btnCheck.textContent = '验证中…';
    btnConfirm.disabled = true;
    window._tickerValidationData = null;
    showValidation('loading', `正在验证 "${symbol}"…`);

    try {
        const resp = await fetch(`/api/tickers/check/${encodeURIComponent(symbol)}`);
        const data = await resp.json();

        if (!resp.ok) {
            showValidation('error', data.detail || '验证请求失败');
            return;
        }

        if (data.exists && data.enabled) {
            // 已存在且启用
            showValidation('warn', data.message || `"${symbol}" 已在观察列表中`);
            return;
        }

        if (data.exists && !data.enabled) {
            // 曾被移除，可恢复
            const info = `<strong>${data.symbol}</strong> — ${data.name || ''}`;
            const extra = data.has_price_data ? '<br><span class="text-secondary">已有历史数据，添加后将快速恢复</span>' : '';
            showValidation('restore', `${info}<br>${data.message || ''}${extra}`);
            window._tickerValidationData = data;
            btnConfirm.disabled = false;
            return;
        }

        if (data.valid) {
            // 全新 ticker 验证通过
            let html = `<strong>${data.symbol}</strong>`;
            if (data.name) html += ` — ${data.name}`;
            if (data.sector) html += `<br><span class="text-secondary">板块: ${data.sector}</span>`;
            if (data.exchange) html += ` · <span class="text-secondary">交易所: ${data.exchange}</span>`;
            if (data.market_price) html += `<br><span class="text-secondary">当前价格: $${Number(data.market_price).toFixed(2)}</span>`;
            showValidation('success', html);
            window._tickerValidationData = data;
            btnConfirm.disabled = false;
        } else {
            showValidation('error', data.error || '验证失败');
        }

    } catch (err) {
        showValidation('error', `网络错误: ${err.message}`);
    } finally {
        btnCheck.disabled = false;
        btnCheck.textContent = '验证';
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
// 确认添加 Ticker
// ============================================================
async function confirmAddTicker() {
    const btnConfirm = document.getElementById('btnAddConfirm');
    const data = window._tickerValidationData;
    if (!data) return;

    btnConfirm.disabled = true;
    btnConfirm.textContent = '添加中…正在拉取数据并计算策略';
    showValidation('loading', `正在为 "${data.symbol}" 拉取价格数据并运行策略分析，请稍候（约 5-10 秒）…`);

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
            showValidation('error', result.detail || '添加失败');
            btnConfirm.disabled = false;
            btnConfirm.textContent = '添加到观察列表';
            return;
        }

        // 成功
        showValidation('success',
            `✅ ${result.message || `"${data.symbol}" 已成功添加`}<br>` +
            '<span class="text-secondary">页面即将刷新…</span>'
        );

        // 延迟刷新页面
        setTimeout(() => {
            window.location.reload();
        }, 1200);

    } catch (err) {
        showValidation('error', `添加失败: ${err.message}`);
        btnConfirm.disabled = false;
        btnConfirm.textContent = '添加到观察列表';
    }
}

// ============================================================
// 移除 Ticker
// ============================================================
async function removeTicker(symbol, name) {
    const displayName = name ? `${symbol} (${name})` : symbol;
    if (!confirm(`确定要从观察列表中移除 ${displayName} 吗？\n\n注: 仅隐藏显示，不会删除历史数据。`)) {
        return;
    }

    try {
        const resp = await fetch(`/api/tickers/${encodeURIComponent(symbol)}`, {
            method: 'DELETE',
        });
        const result = await resp.json();

        if (!resp.ok) {
            alert(result.detail || '移除失败');
            return;
        }

        // 从表格中移除行（带动画）
        const row = document.querySelector(`tr[data-symbol="${symbol}"]`);
        if (row) {
            row.style.transition = 'opacity 0.3s, transform 0.3s';
            row.style.opacity = '0';
            row.style.transform = 'translateX(20px)';
            setTimeout(() => row.remove(), 300);
        }
    } catch (err) {
        alert(`移除失败: ${err.message}`);
    }
}

// ============================================================
// 页面加载完成后的初始化
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    // 为所有带 data-sort 的表格自动初始化排序
    document.querySelectorAll('table.data-table').forEach(table => {
        if (table.id) {
            initTableSort(table.id);
        }
    });

    // Enter 键快捷触发验证
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
