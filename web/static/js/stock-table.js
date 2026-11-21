/* Shared presentation only: all signals, scores and comparisons come from saved results. */
(() => {
    const t = (en, zh) => (document.documentElement.lang === 'zh' ? zh : en);
    const el = (tag, text, cls) => {
        const node = document.createElement(tag);
        if (text !== undefined) node.textContent = text;
        if (cls) node.className = cls;
        return node;
    };
    const names = {
        stage2_us: 'Stage 2',
        contraction_us: t('Contraction', '收缩候选'),
        bottom_fisher_us: t('Countertrend', '逆势观察'),
        checklist_us: t('Checklist', '条件清单'),
        buy_us: 'BUY',
    };
    const states = {
        ok: t('Available', '可用'),
        pending: t('Pending update', '待更新'),
        failed: t('Failed', '失败'),
        stale: t('Stale', '过期'),
        insufficient_data: t('Insufficient data', '数据不足'),
        unavailable: t('Unavailable / not covered', '不可用 / 暂未覆盖'),
    };
    const money = (v) =>
        Number.isFinite(v)
            ? '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
            : '—';
    const pct = (v) => (Number.isFinite(v) ? (v > 0 ? '+' : '') + v.toFixed(2) + '%' : '—');
    const tone = (v) => (v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral');
    const canonical = (s) => s.replaceAll('.', '-');
    const metricLabels = JSON.parse(document.querySelector('#metric-labels').textContent);
    const metricLabel = (key) => metricLabels[key] || key.replaceAll('_', ' ');
    function historyWindow(rows, months) {
        const end = rows.at(-1)?.date;
        if (!end || !months) return { selected: rows, limited: false };
        const cutoff = new Date(end + 'T00:00:00Z');
        const day = cutoff.getUTCDate();
        cutoff.setUTCDate(1);
        cutoff.setUTCMonth(cutoff.getUTCMonth() - months);
        const lastDay = new Date(Date.UTC(cutoff.getUTCFullYear(), cutoff.getUTCMonth() + 1, 0)).getUTCDate();
        cutoff.setUTCDate(Math.min(day, lastDay));
        const start = cutoff.toISOString().slice(0, 10);
        return { selected: rows.filter((r) => r.date >= start), limited: rows[0].date > start };
    }
    function sparkline(values) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 200 36');
        svg.setAttribute('class', 'sparkline');
        svg.setAttribute('role', 'img');
        svg.setAttribute(
            'aria-label',
            t('Saved 20-session closes; gaps preserved', '已保存20交易日收盘价，保留缺口'),
        );
        const valid = values.filter((v) => Number.isFinite(v));
        if (!valid.length) return svg;
        const low = Math.min(...valid),
            high = Math.max(...valid);
        let connected = false,
            d = '';
        values.forEach((v, i) => {
            if (!Number.isFinite(v)) {
                connected = false;
                return;
            }
            const x = 2 + (i * 196) / Math.max(1, values.length - 1);
            const y = high === low ? 18 : 34 - ((v - low) * 32) / (high - low);
            d += `${connected ? 'L' : 'M'}${x},${y} `;
            connected = true;
        });
        const path = document.createElementNS(svg.namespaceURI, 'path');
        path.setAttribute('d', d);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', 'currentColor');
        svg.append(path);
        return svg;
    }
    function state(asset, key) {
        if (asset.role === 'benchmark') return { text: t('N/A', '不适用'), cls: 'muted' };
        const r = asset.strategies?.[key] || {};
        if (r.status !== 'ok') return { text: states[r.status] || t('Not calculated', '该批次未计算'), cls: 'warning' };
        return {
            text:
                (r.is_signal ? (key === 'buy_us' ? 'BUY' : t('Match', '匹配')) : key === 'buy_us' && r.metrics?.in_buy_pool ? t('In pool; awaiting trigger', '池内待触发') : r.near ? t('Near', '接近') : t('No match', '未匹配')) +
                (r.score == null ? '' : ' ' + Number(r.score).toFixed(0)) +
                (r.passed == null ? '' : ` · ${r.passed}/${r.total}`),
            cls: r.is_signal ? 'positive' : r.near ? 'warning' : 'muted',
        };
    }
    function volume(asset) {
        const node = el('div', undefined, 'volume-evidence');
        const view = asset.volume_view || {summary: [['Not calculated in this batch', '该批次未计算量价']], details: []};
        view.summary.forEach(line => node.append(el('div', t(...line))));
        if (view.details.length) {
            const details = el('details');
            details.append(el('summary', t('Price/volume evidence', '量价依据')));
            view.details.forEach(line => details.append(el('p', t(...line))));
            node.append(details);
        }
        return node;
    }
    function favorite(symbol) {
        const b = el('button', '☆', 'star');
        b.type = 'button';
        b.dataset.favorite = symbol;
        return b;
    }
    function link(symbol, batch) {
        const a = el('a', symbol, 'symbol-link');
        a.href =
            '/ticker/' +
            encodeURIComponent(symbol) +
            '?' +
            new URLSearchParams({
                batch: batch || 'none',
                lang: document.documentElement.lang,
                return_to: location.pathname + location.search,
            });
        return a;
    }
    const columns = [
        { key: 'favorite', label: t('Favorite', '收藏') },
        { key: 'identity', label: t('Stock', '股票'), sort: 'symbol' },
        { key: 'price', label: t('Adjusted close', '复权收盘价'), sort: 'price' },
        { key: 'change', label: t('Daily change', '日涨跌幅'), sort: 'change' },
        { key: 'volume', label: t('Price / volume', '量价关系') },
        ...Object.entries(names).map(([key, label]) => ({ key, label, strategy: true, sort: 'score' })),
        { key: 'brief', label: t('Strategy summary', '策略摘要') },
        { key: 'exception', label: t('Exceptions', '异常状态') },
    ];
    function render(data, config) {
        const wrap = el('div', undefined, 'table-wrap');
        wrap.tabIndex = 0;
        wrap.setAttribute('role', 'region');
        wrap.setAttribute(
            'aria-label',
            t('Stocks. Scroll horizontally for more columns.', '股票表格，可横向滚动查看其余列。'),
        );
        const table = el('table', undefined, 'stock-table preset-' + config.preset);
        const caption = el(
            'caption',
            t('Prices and saved strategy conditions', '行情与已保存策略条件'),
            'sr-only',
        );
        const head = el('thead'),
            headings = el('tr');
        for (const col of columns) {
            const th = el('th', undefined, 'col-' + col.key);
            th.scope = 'col';
            if (col.strategy) th.classList.add('col-strategy');
            if (col.sort) {
                const selected = config.sort === col.sort && (!col.strategy || config.strategy === col.key);
                th.setAttribute(
                    'aria-sort',
                    selected ? (col.sort === 'symbol' ? 'ascending' : 'descending') : 'none',
                );
                const b = el('button', col.label + (selected ? (col.sort === 'symbol' ? ' ↑' : ' ↓') : ''));
                b.type = 'button';
                b.dataset.sort = col.sort;
                if (col.strategy) b.dataset.strategy = col.key;
                th.append(b);
            } else th.textContent = col.label;
            headings.append(th);
        }
        head.append(headings);
        table.append(caption, head);
        const body = el('tbody');
        data.items.forEach((a) => {
            const row = el('tr');
            row.dataset.symbol = a.symbol;
            for (const col of columns) {
                const cell = el('td', undefined, 'col-' + col.key);
                if (col.strategy) {
                    cell.classList.add('col-strategy');
                    const s = state(a, col.key);
                    cell.append(el('span', s.text, s.cls));
                    if (col.key === 'buy_us' && a.strategies?.buy_us?.status === 'ok' && a.strategies.buy_us.is_signal)
                        cell.append(el('small', t('Reference close ', '参考收盘价 ') + money(a.strategies.buy_us.metrics.reference_price)));
                } else if (col.key === 'favorite') cell.append(favorite(a.symbol));
                else if (col.key === 'identity') {
                    const identity = el('div', undefined, 'identity');
                    identity.append(favorite(a.symbol));
                    const text = el('div', undefined, 'identity-text');
                    text.append(
                        a.status === 'unavailable' ? el('strong', a.symbol) : link(a.symbol, data.batch_id),
                    );
                    const name = el('small', a.name);
                    name.title = a.name || '';
                    text.append(name);
                    identity.append(text);
                    cell.append(identity);
                    const mobileVolume = volume(a);
                    mobileVolume.classList.add('mobile-volume');
                    cell.append(mobileVolume);
                    if (config.edit) {
                        const controls = el('div', undefined, 'order-controls');
                        for (const [label, delta] of [
                            [t('Move up', '上移'), -1],
                            [t('Move down', '下移'), 1],
                        ]) {
                            const b = el('button', delta < 0 ? '↑' : '↓');
                            b.type = 'button';
                            b.dataset.move = delta;
                            b.dataset.stock = a.symbol;
                            b.setAttribute('aria-label', label + ' ' + a.symbol);
                            const i = window.Favorites.get().indexOf(canonical(a.symbol));
                            b.disabled = i + delta < 0 || i + delta >= window.Favorites.get().length;
                            controls.append(b);
                        }
                        cell.append(controls);
                    }
                } else if (col.key === 'price') cell.textContent = money(a.price);
                else if (col.key === 'change') {
                    cell.textContent = pct(a.change_1d);
                    cell.classList.add(tone(a.change_1d));
                } else if (col.key === 'volume') cell.append(volume(a));
                else if (col.key === 'brief') {
                    if (a.role === 'benchmark') cell.textContent = t('N/A · benchmark', '不适用 · 基准');
                    else {
                        const active = Object.keys(names).filter((k) => a.strategies?.[k]?.is_signal);
                        const near = Object.keys(names).filter((k) => a.strategies?.[k]?.near);
                        const uncertain = Object.keys(names).some((k) => a.strategies?.[k]?.status !== 'ok');
                        cell.textContent =
                            (active.map((k) => names[k]).join(' · ') ||
                                near.map((k) => names[k] + ' ' + t('near', '接近')).join(' · ') ||
                                t('No matches', '无匹配')) +
                            (uncertain ? ' · ' + t('Incomplete', '数据不足') : '');
                        cell.title = Object.keys(names)
                            .map((k) => names[k] + ': ' + state(a, k).text)
                            .join('\n');
                    }
                } else if (col.key === 'exception') {
                    const issues = [];
                    if (a.status !== 'ok') issues.push(states[a.status] || a.status);
                    if (!a.actual_date || a.actual_date !== data.latest_date)
                        issues.push(a.actual_date || t('No market date', '无行情日期'));
                    if (a.price_basis === 'legacy_unknown' || a.price_source === 'legacy_unknown')
                        issues.push(t('Unknown price basis', '价格口径未知'));
                    if (a.price == null && a.status === 'ok') issues.push(t('No valid price', '无有效行情'));
                    cell.append(el('span', issues.join(' · ') || '—', issues.length ? 'warning' : 'muted'));
                }
                row.append(cell);
            }
            body.append(row);
            if (config.report && a.role !== 'benchmark') {
                const extra = el('tr', undefined, 'history-row'),
                    td = el('td');
                td.colSpan = columns.length;
                const details = el('details'),
                    summary = el(
                        'summary',
                        t('Saved conditions and history', '已冻结条件与历史') + ' · ' + a.symbol,
                    );
                details.append(summary);
                if (a.sparkline) details.append(sparkline(a.sparkline));
                const content = el('div', undefined, 'history-details');
                for (const [key, name] of Object.entries(names)) {
                    const r = a.strategies?.[key] || {},
                        section = el('section');
                    section.append(el('h3', name), el('p', state(a, key).text));
                    section.append(
                        el(
                            'p',
                            r.previous
                                ? t('Previous session: ', '前一交易日：') + r.previous.passed + '/' + r.total
                                : t(
                                      'Cannot confirm changes: adjacent valid results unavailable.',
                                      '无法确认变化：缺少前后有效交易日结果。',
                                  ),
                        ),
                    );
                    for (const [condition, value] of Object.entries(r.conditions || {}))
                        section.append(
                            el(
                                'p',
                                (value === true ? '✓ ' : value === false ? '✕ ' : '— ') +
                                    (r.details?.[condition] || condition),
                            ),
                        );
                    for (const [key, value] of Object.entries(r.metrics || {}))
                        if (typeof value === 'number')
                            section.append(el('p', metricLabel(key) + ': ' + value.toFixed(2)));
                    content.append(section);
                }
                details.append(content);
                td.append(details);
                extra.append(td);
                body.append(extra);
            }
        });
        table.append(body);
        wrap.append(table);
        return wrap;
    }
    function changeCounts(changes) {
        return { total: changes.length, symbols: new Set(changes.map(c => c.symbol)).size,
            entered: changes.filter(c => c.change === 'entry').length,
            exited: changes.filter(c => c.change === 'exit').length };
    }
    function renderChanges(root, data) {
        root.replaceChildren();
        const changes = data.changes || [], counts = changeCounts(changes);
        if (!changes.length) root.append(el('p', t('No confirmed entries or exits.', '无已确认新增或退出。')));
        else {
            const details = el('details'), summary = el('summary');
            summary.textContent = t(
                `Confirmed changes[${counts.total}] · ${counts.symbols} stocks · Entered ${counts.entered} · Exited ${counts.exited}`,
                `已确认变化[${counts.total}] · 涉及${counts.symbols}只 · 新增${counts.entered} · 退出${counts.exited}`);
            details.append(summary, el('p', t('Complete selected scope; compared with the preceding valid trading-session results.', '完整所选范围；与前一交易日有效结果比较。'), 'muted'));
            const controls = el('div', undefined, 'toolbar change-controls');
            const makeSelect = (label, choices) => {
                const wrap = el('label', label), select = el('select');
                choices.forEach(([value, text]) => { const option = el('option', text); option.value = value; select.append(option); });
                wrap.append(select); controls.append(wrap); return select;
            };
            const type = makeSelect(t('Change', '变化类型'), [['',t('All','全部')],['entry',t('Entered','新增')],['exit',t('Exited','退出')]]);
            const strategy = makeSelect(t('Strategy', '策略'), [['',t('All','全部')],...Object.entries(names)]);
            const table = el('table', undefined, 'changes-table'), thead = el('thead'), header = el('tr'), body = el('tbody');
            [t('Stock','代码'),t('Strategy','策略'),t('Change','变化')].forEach(text=>{const th=el('th',text);th.scope='col';header.append(th);});
            thead.append(header);table.append(thead,body);
            const nav = el('nav', undefined, 'pagination'), previous = el('button', t('Previous','上一页')), next = el('button',t('Next','下一页')), status=el('span');
            nav.setAttribute('aria-label',t('Change pagination','变化明细分页'));
            previous.type=next.type='button'; status.setAttribute('role','status');
            nav.append(previous,status,next);details.append(controls,table,nav);root.append(details);
            let page=1;
            function paintChanges() {
                const selected=changes.filter(c=>(!type.value||c.change===type.value)&&(!strategy.value||c.strategy===strategy.value));
                const pages=Math.max(1,Math.ceil(selected.length/10));page=Math.min(page,pages);
                body.replaceChildren();
                selected.slice((page-1)*10,page*10).forEach(c=>{
                    const row=el('tr'), identity=el('td');identity.append(link(c.symbol,data.batch_id));
                    row.append(identity,el('td',names[c.strategy]||c.strategy),el('td',c.change==='entry'?t('Entered','新增匹配'):t('Exited','退出匹配'),c.change==='entry'?'positive':'warning'));body.append(row);
                });
                if (!selected.length) {const row=el('tr'), cell=el('td',t('No changes for these filters.','该筛选下无变化。'));cell.colSpan=3;row.append(cell);body.append(row);}
                status.textContent=`${page} / ${pages} · ${selected.length} ${t('changes','条')}`;
                previous.disabled=page<=1;next.disabled=page>=pages;
            }
            [type,strategy].forEach(select=>select.addEventListener('change',()=>{page=1;paintChanges();}));
            previous.addEventListener('click',()=>{page--;paintChanges();});next.addEventListener('click',()=>{page++;paintChanges();});paintChanges();
        }
        if (data.comparison_missing) root.append(el('p',t(
            `${data.comparison_missing} stock/strategy comparisons unavailable; missing adjacent valid results.`,
            `${data.comparison_missing} 项股票／策略缺少前后有效数据，无法确认变化。`),'scope-note muted'));
    }
    window.StockTable = {
        renderChanges,
        changeCounts,
        t,
        el,
        names,
        states,
        money,
        pct,
        tone,
        canonical,
        state,
        link,
        render,
        historyWindow,
    };
})();
