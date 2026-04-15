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
// 页面加载完成后的初始化
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    // 为所有带 data-sort 的表格自动初始化排序
    document.querySelectorAll('table.data-table').forEach(table => {
        if (table.id) {
            initTableSort(table.id);
        }
    });
});
