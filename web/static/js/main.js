/* Read-only UI: provider/import strings always enter the DOM as text. */
document.addEventListener('DOMContentLoaded', () => {
    const zh = document.body.dataset.lang === 'zh',
        t = (en, cn) => zh ? cn : en,
        F = window.Favorites;
    const el = (tag, text, cls) => {
        const e = document.createElement(tag);
        if (text !== undefined) e.textContent = text;
        if (cls) e.className = cls;
        return e;
    };
    const toast = message => {
        const e = document.querySelector('#toast');
        e.textContent = message;
        e.hidden = false;
        setTimeout(() => e.hidden = true, 6500);
    };
    const names = {
        stage2_us: 'Stage 2',
        contraction_us: t('Contraction candidates', '收缩候选'),
        bottom_fisher_us: t('Countertrend', '逆势观察'),
        checklist_us: t('Checklist', '条件清单')
    };
    const states = {
        ok: t('Available', '可用'),
        pending: t('Pending update', '待更新'),
        failed: t('Failed', '失败'),
        stale: t('Stale', '过期'),
        insufficient_data: t('Insufficient data', '数据不足'),
        unavailable: t('Unavailable / not covered', '不可用 / 暂未覆盖')
    };
    const money = v => v == null ? '—' : '$' + v.toFixed(2),
        pct = v => v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(2) + '%',
        canonical = s => s.replaceAll('.', '-');

    function sync() {
        document.querySelectorAll('[data-favorite]').forEach(b => {
            const active = F.get().includes(canonical(b.dataset.favorite));
            b.textContent = active ? t('Remove favorite', '取消收藏') : t('Add favorite', '收藏');
            b.setAttribute('aria-pressed', String(active));
            b.setAttribute('aria-label', b.textContent + ' ' + b.dataset.favorite);
        });
        const message = {
            storage: t('Storage unavailable. Changes work in this tab but cannot be saved permanently.', '浏览器无法保存收藏。当前页面仍可使用，修改不能长期保存。'),
            invalid: t('Saved favorites are damaged or unsupported. Import a valid file or explicitly restore defaults.', '收藏数据已损坏或版本不支持。请导入有效文件，或主动恢复默认。'),
            removed: t('Site storage was cleared. Restore defaults or add stocks.', '网站收藏已被清除。可恢复默认或重新添加股票。')
        } [F.warning()];
        const banner = document.querySelector('#storage-warning');
        banner.textContent = message || '';
        banner.hidden = !message;
    }
    document.addEventListener('click', event => {
        const b = event.target.closest('[data-favorite]');
        if (!b) return;
        try {
            F.toggle(b.dataset.favorite);
        } catch {
            toast(t('Maximum 100 favorites.', '最多可收藏100个代码。'));
        }
    });
    const guest = document.querySelector('#guest');
    let page = 1,
        generation = 0;
    const request = async url => {
        const response = await fetch(url, {
            cache: 'no-store'
        });
        if (!response.ok) throw Error(t('Data unavailable. Retry or refresh this page.', '数据暂不可用，请重试或刷新页面。'));
        return response.json();
    };
    const link = (symbol, batch) => {
        const a = el('a', symbol);
        a.href = '/ticker/' + encodeURIComponent(symbol) + '?' + new URLSearchParams({
            batch: batch || 'none',
            lang: zh ? 'zh' : 'en'
        });
        return a;
    };

    function card(a, batch, sortable) {
        const article = el('article', undefined, 'stock-card');
        article.dataset.symbol = a.symbol;
        const head = el('div', undefined, 'toolbar');
        head.append(a.status === 'unavailable' ? el('strong', a.symbol) : link(a.symbol, batch), el('span', a.name));
        const favorite = el('button');
        favorite.type = 'button';
        favorite.dataset.favorite = a.symbol;
        favorite.disabled = a.status === 'unavailable' && !F.get().includes(canonical(a.symbol));
        head.append(favorite);
        if (sortable && F.get().includes(canonical(a.symbol)))
            for (const [text, delta] of [
                    [t('Move up', '上移'), -1],
                    [t('Move down', '下移'), 1]
                ]) {
                const b = el('button', text);
                b.type = 'button';
                b.setAttribute('aria-label', text + ' ' + a.symbol);
                const i = F.get().indexOf(canonical(a.symbol));
                b.disabled = i + delta < 0 || i + delta >= F.get().length;
                b.addEventListener('click', () => F.move(a.symbol, delta));
                head.append(b);
            }
        article.append(head, el('p', money(a.price) + ' · ' + pct(a.change_1d) + ' · ' + (a.actual_date || '—') + ' · ' + (states[a.status] || a.status)));
        if (a.status === 'unavailable') return article;
        const matrix = el('div', undefined, 'strategy-matrix');
        if (a.role === 'benchmark') matrix.append(el('p', t('Benchmark: prices and technical indicators; stock screens do not apply.', '基准资产：显示行情和技术指标，不套用普通股票筛选。')));
        else
            for (const [key, name] of Object.entries(names)) {
                const r = a.strategies[key] || {},
                    text = r.status === 'ok' ? (r.is_signal ? t('Match', '匹配') : r.near ? t('Near', '接近') : t('No match', '未匹配')) + ' ' + r.passed + '/' + r.total : states[r.status] || states.pending;
                const group = el('div');
                group.append(el('small', name), el('span', text, 'badge ' + (r.is_signal ? 'ok' : r.near ? 'near' : '')));
                matrix.append(group);
            }
        article.append(matrix);
        if (a.sparkline) {
            const valid = a.sparkline.filter(v => v !== null),
                svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('viewBox', '0 0 140 36');
            svg.setAttribute('class', 'sparkline');
            svg.setAttribute('role', 'img');
            svg.setAttribute('aria-label', t('20-session closes; gaps preserved', '20交易日收盘价，保留缺口'));
            if (valid.length) {
                const min = Math.min(...valid),
                    max = Math.max(...valid);
                let connected = false,
                    d = '';
                a.sparkline.forEach((v, i) => {
                    if (v === null) {
                        connected = false;
                        return;
                    }
                    d += (connected ? 'L' : 'M') + (2 + i * 136 / 19) + ',' + (max === min ? 18 : 34 - (v - min) * 32 / (max - min)) + ' ';
                    connected = true;
                });
                const path = document.createElementNS(svg.namespaceURI, 'path');
                path.setAttribute('d', d);
                path.setAttribute('fill', 'none');
                path.setAttribute('stroke', 'currentColor');
                svg.append(path);
            }
            article.append(svg);
        }
        if (guest.dataset.view === 'report' && a.role !== 'benchmark') {
            const details = el('details');
            details.append(el('summary', t('Saved conditions and measurements', '已冻结条件与指标')));
            for (const [key, name] of Object.entries(names)) {
                const r = a.strategies[key] || {};
                details.append(el('h3', name));
                if (r.previous) details.append(el('p', t('Previous session: ', '前一交易日：') + r.previous.passed + '/' + r.total));
                for (const [condition, value] of Object.entries(r.conditions || {})) details.append(el('p', (value === true ? '✓ ' : value === false ? '✕ ' : '— ') + (r.details?.[condition] || condition)));
                for (const [metric, value] of Object.entries(r.metrics || {}))
                    if (typeof value === 'number') details.append(el('p', metric + ': ' + value.toFixed(2)));
            }
            article.append(details);
        }
        return article;
    }
    async function load() {
        if (!guest) return;
        const id = ++generation,
            form = document.querySelector('#guest-filters'),
            list = document.querySelector('#guest-results'),
            params = new URLSearchParams(new FormData(form));
        params.set('batch', guest.dataset.batch);
        params.set('page', page);
        const all = guest.dataset.view === 'discover' || document.querySelector('#report-all')?.checked;
        if (!all) params.set('symbols', F.get().join(','));
        if (guest.dataset.report) params.set('report_id', guest.dataset.report);
        list.replaceChildren();
        list.setAttribute('aria-busy', 'true');
        document.querySelector('#favorite-summary').replaceChildren();
        const status = document.querySelector('#list-status');
        status.textContent = t('Loading…', '正在加载…');
        try {
            const data = await request('/api/assets?' + params);
            if (id !== generation) return;
            if ((data.batch_id || 'none') !== guest.dataset.batch) throw Error(t('Publication changed. Refresh this page.', '发布批次已变化，请刷新页面。'));
            page = data.page;
            status.textContent = data.total ? `${data.start}–${data.end} / ${data.total} · ${t('Data exceptions','行情异常')} ${data.missing_count}` : !all && !F.get().length ? t('No favorites. Discover stocks to add your first one.', '尚无收藏。请前往发现股票添加。') : t('No matching stocks. Change filters; unsupported symbols are not covered yet.', '没有匹配的股票。请调整筛选；不支持的代码暂未覆盖。');
            data.items.forEach(a => list.append(card(a, data.batch_id, !all)));
            if (guest.dataset.view === 'overview' || guest.dataset.view === 'report') {
                const summary = document.querySelector('#favorite-summary');
                for (const [key, name] of Object.entries(names)) {
                    const panel = el('section', undefined, 'panel');
                    panel.append(el('h3', (all ? t('Public', '公开范围') : t('My watchlist', '我的关注')) + ' · ' + name + ' (' + data.counts[key] + ')'));
                    for (const a of data.candidates[key]) panel.append(link(a.symbol, data.batch_id), el('span', ' ' + money(a.price) + ' '));
                    if (!data.counts[key]) panel.append(el('p', t('No candidates in this selection', '当前收藏范围无候选')));
                    const b = el('button', t('View candidates', '查看候选'));
                    b.type = 'button';
                    b.addEventListener('click', () => {
                        form.elements.strategy.value = key;
                        form.elements.match.value = 'matched';
                        page = 1;
                        load();
                    });
                    panel.append(b);
                    summary.append(panel);
                }
                const changes = el('section', undefined, 'panel');
                changes.append(el('h3', t('Confirmed changes in this selection', '当前收藏的确认变化')));
                if (!data.changes.length) changes.append(el('p', t('No confirmed entries or exits. Both sessions must be valid.', '无确认新增或退出；前后交易日均有效才确认变化。')));
                data.changes.forEach(c => changes.append(el('p', c.symbol + ' · ' + names[c.strategy] + ' · ' + (c.change === 'entry' ? t('Entered', '新增') : t('Exited', '退出')))));
                summary.append(changes);
            }
            const nav = document.querySelector('#guest-pagination');
            nav.replaceChildren();
            for (const [label, delta] of [
                    [t('Previous', '上一页'), -1],
                    [t('Next', '下一页'), 1]
                ]) {
                const b = el('button', label);
                b.type = 'button';
                b.disabled = page + delta < 1 || page + delta > data.pages;
                b.addEventListener('click', () => {
                    page += delta;
                    load();
                });
                nav.append(b);
            }
            sync();
        } catch (error) {
            if (id === generation) status.textContent = error.message;
        } finally {
            if (id === generation) list.setAttribute('aria-busy', 'false');
        }
    }
    if (guest) {
        const form = document.querySelector('#guest-filters'),
            query = new URLSearchParams(location.search);
        for (const key of ['search', 'strategy', 'match', 'sort', 'size'])
            if (query.has(key)) form.elements[key].value = query.get(key);
        form.addEventListener('submit', event => {
            event.preventDefault();
            page = 1;
            load();
        });
        document.querySelector('#report-all')?.addEventListener('change', () => {
            page = 1;
            load();
        });
        for (const [id, values] of [
                ['favorites-reset', () => F.defaults()],
                ['favorites-clear', () => []]
            ]) document.getElementById(id).addEventListener('click', () => {
            if (confirm(t('Replace current favorites? Export first to keep a backup.', '将覆盖当前收藏。需要保留时请先导出备份。'))) F.replace(values());
        });
        document.querySelector('#favorites-export').addEventListener('click', () => {
            const a = el('a');
            a.href = URL.createObjectURL(new Blob([JSON.stringify({
                version: 1,
                symbols: F.get()
            }, null, 2)], {
                type: 'application/json'
            }));
            a.download = 'stock-watchlist.json';
            a.click();
            setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        });
        document.querySelector('#favorites-import').addEventListener('change', async event => {
            const file = event.target.files[0];
            if (!file) return;
            try {
                if (file.size > 20000) throw Error('size');
                const parsed = F.validate(JSON.parse(await file.text()));
                const data = await request('/api/assets?' + new URLSearchParams({
                    symbols: parsed.symbols.join(','),
                    size: 100,
                    batch: guest.dataset.batch
                }));
                const unknown = data.items.filter(a => a.status === 'unavailable').map(a => a.symbol);
                if (unknown.length) throw Error(t('Not covered / unavailable: ', '暂未覆盖 / 不可用：') + unknown.join(', '));
                if (!confirm(t('Import replaces current favorites. Continue?', '导入将覆盖当前收藏，是否继续？'))) return;
                F.replace(parsed.symbols);
                document.querySelector('#import-result').textContent = `${t('Imported','已导入')} ${parsed.symbols.length}; ${t('duplicates removed','已去重')} ${parsed.duplicates}.`;
            } catch (error) {
                document.querySelector('#import-result').textContent = t('Import rejected: version 1 favorites JSON, at most 100 covered symbols. ', '导入失败：仅支持 version 1 收藏 JSON，最多100个已覆盖代码。 ') + (error.message.startsWith('Not covered') || error.message.startsWith('暂未覆盖') ? error.message : '');
            } finally {
                event.target.value = '';
            }
        });
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) load();
        });
        window.addEventListener('pageshow', event => {
            if (event.persisted) load();
        });
    }
    F.subscribe(() => {
        sync();
        page = 1;
        load();
    });
    sync();
    load();
    const chart = document.querySelector('#price-chart');
    if (chart && window.Chart) {
        const rows = JSON.parse(document.querySelector('#chart-data').textContent);
        new Chart(chart, {
            type: 'line',
            data: {
                labels: rows.map(r => r.date),
                datasets: [{
                    label: t('Adjusted close', '复权收盘价'),
                    data: rows.map(r => r.quality === 'valid' ? r.close : null),
                    borderColor: '#25627b',
                    backgroundColor: '#25627b12',
                    fill: true,
                    pointRadius: 0,
                    borderWidth: 2,
                    spanGaps: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        backgroundColor: '#fcfbf7',
                        titleColor: '#173c50',
                        bodyColor: '#192327',
                        borderColor: '#d7d8d2',
                        borderWidth: 1
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            maxTicksLimit: 6,
                            color: '#657176'
                        },
                        grid: {
                            display: false
                        }
                    },
                    y: {
                        ticks: {
                            color: '#657176'
                        },
                        grid: {
                            color: '#d7d8d240'
                        }
                    }
                }
            }
        });
    }
});
