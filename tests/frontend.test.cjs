const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const context = {
    window: {},
    document: { documentElement: { lang: 'en' }, querySelector: () => ({ textContent: '{}' }) },
};
vm.runInNewContext(readFileSync('web/static/js/stock-table.js', 'utf8'), context);
const { historyWindow, pct, state } = context.window.StockTable;
const rows = ['2024-02-28', '2024-02-29', '2024-03-15', '2024-03-31'].map((date) => ({ date, close: 10 }));
assert.equal(historyWindow(rows, 1).selected[0].date, '2024-02-29');
assert.equal(historyWindow(rows, 12).limited, true);
assert.equal(historyWindow([], 1).selected.length, 0);
assert.equal(historyWindow(rows, 0).selected, rows);
assert.equal(pct(0), '0.00%');
assert.equal(pct(null), '—');
assert.equal(pct(-1), '-1.00%');
assert.equal(state({ role: 'benchmark' }, 'stage2_us').text, 'N/A');
assert.equal(
    state({ strategies: { stage2_us: { status: 'failed', is_signal: true, score: 100 } } }, 'stage2_us').text,
    'Failed',
);
assert.match(
    state(
        { strategies: { stage2_us: { status: 'ok', is_signal: false, near: true, score: 50 } } },
        'stage2_us',
    ).text,
    /Near/,
);
console.log(
    'Frontend boundaries passed: month-end/leap-year, empty/limited history, zero/missing prices, unavailable/near strategy states.',
);
