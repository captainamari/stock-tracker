/* Request orchestration and browser-only favorites. Shared cells live in stock-table.js. */
document.addEventListener('DOMContentLoaded', () => {
    const { t, el, names, canonical } = window.StockTable,
        F = window.Favorites;
    const guest = document.querySelector('#guest'),
        form = document.querySelector('#guest-filters');
    let page = 1,
        generation = 0,
        controller,
        cached,
        editing = false,
        restored = false;
    const query = new URLSearchParams(location.search);
    let preset = query.get('columns') || (matchMedia('(max-width:700px)').matches ? 'market' : 'strategy');
    if (!['market', 'strategy'].includes(preset)) preset = 'market';
    const toast = (message) => {
        const node = document.querySelector('#toast');
        node.textContent = message;
        node.hidden = false;
        setTimeout(() => (node.hidden = true), 6500);
    };
    function sync() {
        const favorites = F.get();
        document.querySelectorAll('[data-favorite]').forEach((b) => {
            const active = favorites.includes(canonical(b.dataset.favorite));
            b.textContent = active ? '★' : '☆';
            b.classList.add('star');
            b.setAttribute('aria-pressed', String(active));
            b.setAttribute(
                'aria-label',
                (active ? t('Remove favorite', '取消收藏') : t('Add favorite', '收藏')) +
                    ' ' +
                    b.dataset.favorite,
            );
        });
        const message = {
            storage: t(
                'Storage unavailable. Changes work in this tab but cannot be saved permanently.',
                '浏览器无法保存收藏。当前页面仍可使用，修改不能长期保存。',
            ),
            invalid: t(
                'Saved favorites are damaged or unsupported. Import a valid file or explicitly restore defaults.',
                '收藏数据已损坏或版本不支持。请导入有效文件，或主动恢复默认。',
            ),
            removed: t(
                'Site storage was cleared. Restore defaults or add stocks.',
                '网站收藏已被清除。可恢复默认或重新添加股票。',
            ),
        }[F.warning()];
        const banner = document.querySelector('#storage-warning');
        banner.textContent = message || '';
        banner.hidden = !message;
    }
    const request = async (url, signal) => {
        const response = await fetch(url, { cache: 'no-store', signal });
        if (!response.ok)
            throw Error(
                t(
                    'Data unavailable. Last successful results remain below.',
                    '请求失败，下方保留最近有效结果。',
                ),
            );
        return response.json();
    };
    const all = () => guest?.dataset.view === 'discover' || document.querySelector('#report-all')?.checked;
    const canEdit = () =>
        guest &&
        guest.dataset.view !== 'report' &&
        !all() &&
        !form.elements.search.value &&
        !form.elements.strategy.value &&
        form.elements.match.value === 'all' &&
        form.elements.sort.value === 'order';
    function controlState() {
        const strategy = form.elements.strategy.value,
            option = form.elements.sort.querySelector('[value=score]');
        option.disabled = !strategy;
        option.textContent = strategy
            ? names[strategy] + ' ' + t('score ↓', '评分 ↓')
            : t('Strategy score ↓ (select strategy)', '策略评分 ↓（先选策略）');
        if (!strategy && form.elements.sort.value === 'score') form.elements.sort.value = 'symbol';
        const edit = document.querySelector('#edit-list');
        if (edit) {
            edit.disabled = !canEdit();
            edit.title = t(
                'Use favorite order without filters to edit the complete list.',
                '仅在无筛选且按收藏顺序时编辑完整列表。',
            );
            if (!canEdit()) editing = false;
            edit.setAttribute('aria-pressed', String(editing));
            edit.textContent = editing ? t('Done editing', '完成编辑') : t('Edit list', '编辑列表');
        }
    }
    function saveURL() {
        const params = new URLSearchParams(new FormData(form));
        params.set('lang', document.documentElement.lang);
        params.set('page', page);
        params.set('columns', preset);
        if (guest.dataset.batch !== 'none') params.set('batch', guest.dataset.batch);
        if (document.querySelector('#report-all')?.checked) params.set('all', '1');
        history.replaceState(null, '', location.pathname + '?' + params);
    }
    function paint() {
        if (!cached) return;
        const list = document.querySelector('#guest-results'),
            oldWrap = list.querySelector('.table-wrap'),
            left = oldWrap?.scrollLeft || 0,
            top = oldWrap?.scrollTop || 0;
        const active = document.activeElement,
            focus = active?.dataset.favorite
                ? { favorite: active.dataset.favorite }
                : active?.dataset.move
                  ? { move: active.dataset.move, stock: active.dataset.stock }
                  : null;
        const oldRow = active?.closest('tr[data-symbol]'),
            oldIndex = oldRow ? [...list.querySelectorAll('tr[data-symbol]')].indexOf(oldRow) : -1;
        const y = scrollY;
        list.replaceChildren(
            StockTable.render(cached, {
                preset,
                edit: editing && canEdit(),
                sort: form.elements.sort.value,
                strategy: form.elements.strategy.value,
                report: guest.dataset.view === 'report',
            }),
        );
        list.querySelector('.table-wrap').scrollLeft = left;
        list.querySelector('.table-wrap').scrollTop = top;
        sync();
        if (focus) {
            const candidates = [...list.querySelectorAll(focus.favorite ? '[data-favorite]' : '[data-move]')];
            const target =
                candidates.find((b) =>
                    focus.favorite
                        ? b.dataset.favorite === focus.favorite && b.getClientRects().length
                        : b.dataset.move === focus.move && b.dataset.stock === focus.stock,
                ) ||
                candidates.filter((b) => b.getClientRects().length)[Math.max(0, oldIndex)] ||
                document.querySelector('#edit-list');
            target?.focus({ preventScroll: true });
            window.scrollTo(0, y);
        }
    }
    function summaries(data) {
        const summary = document.querySelector('#favorite-summary');
        summary.replaceChildren(
            el('strong', all() ? t('All stocks', '全部股票') : t('My watchlist', '我的关注')),
        );
        for (const [key, name] of Object.entries(names)) {
            const b = el('button', `${name} ${data.counts[key]}`);
            b.type = 'button';
            b.dataset.countStrategy = key;
            b.setAttribute(
                'aria-pressed',
                String(form.elements.strategy.value === key && form.elements.match.value === 'matched'),
            );
            summary.append(b);
        }
        const changes = document.querySelector('#confirmed-changes');
        changes.replaceChildren();
        const text = data.changes.length
            ? data.changes
                  .map(
                      (c) =>
                          c.symbol +
                          ' ' +
                          names[c.strategy] +
                          ' ' +
                          (c.change === 'entry' ? t('Entered', '新增') : t('Exited', '退出')),
                  )
                  .join(' · ')
            : t('No confirmed entries or exits.', '无已确认新增或退出。');
        changes.append(el('strong', t('Confirmed changes · ', '已确认变化 · ')), el('span', text));
        if (data.comparison_missing)
            changes.append(
                el(
                    'small',
                    t(
                        ` Cannot confirm ${data.comparison_missing} stock/strategy comparisons: adjacent valid sessions unavailable.`,
                        ` ${data.comparison_missing} 项股票/策略缺少前后有效交易日数据，无法确认变化。`,
                    ),
                ),
            );
    }
    function pagination(data) {
        const nav = document.querySelector('#guest-pagination');
        nav.replaceChildren();
        for (const [label, delta] of [
            [t('Previous', '上一页'), -1],
            [t('Next', '下一页'), 1],
        ]) {
            const b = el('button', label);
            b.type = 'button';
            b.dataset.pageDelta = delta;
            b.disabled = page + delta < 1 || page + delta > data.pages;
            nav.append(b);
            if (delta < 0) nav.append(el('span', `${page} / ${data.pages}`));
        }
    }
    async function load() {
        if (!guest) return;
        controlState();
        saveURL();
        controller?.abort();
        controller = new AbortController();
        const id = ++generation;
        const params = new URLSearchParams(new FormData(form));
        params.set('batch', guest.dataset.batch);
        params.set('page', page);
        if (!all()) params.set('symbols', F.get().join(','));
        if (guest.dataset.report) params.set('report_id', guest.dataset.report);
        const list = document.querySelector('#guest-results'),
            status = document.querySelector('#list-status'),
            retry = document.querySelector('#retry-list');
        list.setAttribute('aria-busy', 'true');
        status.textContent = t('Loading…', '正在加载…');
        retry.hidden = true;
        try {
            const data = await request('/api/assets?' + params, controller.signal);
            if (id !== generation) return;
            if ((data.batch_id || 'none') !== guest.dataset.batch)
                throw Error(t('Publication changed. Refresh this page.', '发布批次已变化，请刷新页面。'));
            cached = data;
            page = data.page;
            saveURL();
            paint();
            summaries(data);
            pagination(data);
            status.textContent = data.total
                ? `${data.start}–${data.end} / ${data.total} · ${t('Scope exceptions', '范围内行情异常')} ${data.missing_count}`
                : !all() && !F.get().length
                  ? t('No favorites. Discover stocks to add your first one.', '尚无收藏，请点击添加股票。')
                  : t('No matching stocks. Change or clear filters.', '没有匹配的股票，请调整或清除筛选。');
            const basis = document.querySelector('#table-basis');
            basis.textContent =
                t('As of ', '截至 ') +
                (data.latest_date || '—') +
                t(' · USD · split/dividend-adjusted close · ', ' · USD · 拆股/分红复权收盘价 · ') +
                ([...new Set(data.items.map((a) => a.price_source).filter(Boolean))].join(', ') ||
                    t('Source unavailable', '来源缺失')) +
                (data.items.some((a) => a.price_source === 'synthetic_test')
                    ? ' · ' + t('SYNTHETIC TEST DATA', '合成测试数据')
                    : '') +
                (guest.dataset.view === 'report'
                    ? ' · ' + t('Historical snapshot', '历史快照')
                    : data.latest_date < guest.dataset.expected
                      ? ' · ' +
                        t('Historical data available; awaiting latest batch', '历史数据可用，等待最新批次')
                      : '');
            if (data.total && data.items.every((a) => a.price == null))
                status.textContent +=
                    ' · ' +
                    t(
                        'No valid prices on this page. Await the next published update.',
                        '本页暂无有效行情，等待后续发布更新。',
                    );
            if (!restored) {
                restored = true;
                try {
                    const saved = JSON.parse(
                        sessionStorage.getItem('stock-scroll:' + location.pathname + location.search) ||
                            'null',
                    );
                    if (saved)
                        requestAnimationFrame(() => {
                            scrollTo(0, saved.y);
                            const wrap = list.querySelector('.table-wrap');
                            wrap.scrollTop = saved.top;
                            wrap.scrollLeft = saved.left;
                        });
                } catch {
                    /* Optional navigation state. */
                }
            }
        } catch (error) {
            if (id === generation && error.name !== 'AbortError') {
                status.textContent = error.message;
                retry.hidden = false;
            }
        } finally {
            if (id === generation) list.setAttribute('aria-busy', 'false');
        }
    }
    document.addEventListener('click', (event) => {
        const b = event.target.closest('[data-favorite]');
        if (b) {
            try {
                F.toggle(b.dataset.favorite);
                toast(t('Favorites updated', '收藏已更新'));
            } catch {
                toast(t('Maximum 100 favorites.', '最多可收藏100个代码。'));
            }
            return;
        }
        const move = event.target.closest('[data-move]');
        if (move && canEdit()) F.move(move.dataset.stock, Number(move.dataset.move));
        const link = event.target.closest('.symbol-link');
        if (link) {
            try {
                const wrap = document.querySelector('.table-wrap');
                sessionStorage.setItem(
                    'stock-scroll:' + location.pathname + location.search,
                    JSON.stringify({ y: scrollY, top: wrap?.scrollTop || 0, left: wrap?.scrollLeft || 0 }),
                );
            } catch {
                /* Storage unavailable. */
            }
        }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        document.querySelectorAll('.management[open], .help[open]').forEach((menu) => {
            menu.open = false;
            menu.querySelector('summary').focus();
        });
    });
    if (guest) {
        document.querySelector('.advanced-filters').open = !matchMedia('(max-width:700px)').matches;
        for (const key of ['search', 'strategy', 'match', 'sort', 'size'])
            if (query.has(key)) form.elements[key].value = query.get(key);
        if (!form.elements.sort.value)
            form.elements.sort.value = guest.dataset.view === 'discover' ? 'symbol' : 'order';
        page = Math.max(1, Number(query.get('page')) || 1);
        const reportAll = document.querySelector('#report-all');
        if (reportAll) reportAll.checked = query.get('all') === '1';
        document.querySelector('#column-preset').value = preset;
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            page = 1;
            load();
        });
        form.addEventListener('change', () => {
            page = 1;
            load();
        });
        document.querySelector('[name=size]').addEventListener('change', () => {
            page = 1;
            load();
        });
        reportAll?.addEventListener('change', () => {
            page = 1;
            load();
        });
        document.querySelector('#retry-list').addEventListener('click', load);
        document.querySelector('#edit-list')?.addEventListener('click', () => {
            editing = !editing;
            controlState();
            paint();
        });
        document.querySelector('#column-preset').addEventListener('change', (e) => {
            preset = e.target.value;
            saveURL();
            paint();
        });
        guest.addEventListener('click', (event) => {
            const count = event.target.closest('[data-count-strategy]');
            if (count) {
                form.elements.strategy.value = count.dataset.countStrategy;
                form.elements.match.value = 'matched';
                page = 1;
                load();
            }
            const sort = event.target.closest('[data-sort]');
            if (sort) {
                form.elements.sort.value = sort.dataset.sort;
                if (sort.dataset.strategy) form.elements.strategy.value = sort.dataset.strategy;
                page = 1;
                load();
            }
            const next = event.target.closest('[data-page-delta]');
            if (next) {
                page = (cached?.page || page) + Number(next.dataset.pageDelta);
                load();
            }
        });
        document
            .querySelector('#favorites-import-button')
            .addEventListener('click', () => document.querySelector('#favorites-import').click());
        for (const [id, values] of [
            ['favorites-reset', () => F.defaults()],
            ['favorites-clear', () => []],
        ])
            document.getElementById(id).addEventListener('click', () => {
                if (
                    confirm(
                        t(
                            'Replace current favorites? Export first to keep a backup.',
                            '将覆盖当前收藏。需要保留时请先导出备份。',
                        ),
                    )
                )
                    F.replace(values());
            });
        document.querySelector('#favorites-export').addEventListener('click', () => {
            const a = el('a');
            a.href = URL.createObjectURL(
                new Blob(
                    [
                        JSON.stringify(
                            {
                                version: 1,
                                symbols: F.get(),
                            },
                            null,
                            2,
                        ),
                    ],
                    {
                        type: 'application/json',
                    },
                ),
            );
            a.download = 'stock-watchlist.json';
            a.click();
            setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        });
        document.querySelector('#favorites-import').addEventListener('change', async (event) => {
            const file = event.target.files[0];
            if (!file) return;
            try {
                if (file.size > 20000) throw Error('size');
                const parsed = F.validate(JSON.parse(await file.text()));
                const data = await request(
                    '/api/assets?' +
                        new URLSearchParams({
                            symbols: parsed.symbols.join(','),
                            size: 100,
                            batch: guest.dataset.batch,
                        }),
                );
                const unknown = data.items.filter((a) => a.status === 'unavailable').map((a) => a.symbol);
                if (unknown.length)
                    throw Error(t('Not covered / unavailable: ', '暂未覆盖 / 不可用：') + unknown.join(', '));
                if (
                    !confirm(
                        t('Import replaces current favorites. Continue?', '导入将覆盖当前收藏，是否继续？'),
                    )
                )
                    return;
                F.replace(parsed.symbols);
                document.querySelector('#import-result').textContent =
                    `${t('Imported', '已导入')} ${parsed.symbols.length}; ${t('duplicates removed', '已去重')} ${parsed.duplicates}.`;
            } catch (error) {
                document.querySelector('#import-result').textContent =
                    t(
                        'Import rejected: version 1 favorites JSON, at most 100 covered symbols. ',
                        '导入失败：仅支持 version 1 收藏 JSON，最多100个已覆盖代码。 ',
                    ) +
                    (error.message.startsWith('Not covered') || error.message.startsWith('暂未覆盖')
                        ? error.message
                        : '');
            } finally {
                event.target.value = '';
            }
        });
        window.addEventListener('pageshow', (e) => {
            if (e.persisted) load();
        });
    }
    F.subscribe(() => {
        sync();
        if (!guest) return;
        if (!all()) load();
    });
    sync();
    load();
    const chart = document.querySelector('#price-chart');
    if (chart && window.Chart) {
        const rows = JSON.parse(document.querySelector('#chart-data').textContent);
        const instance = new Chart(chart, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: t('Adjusted close', '复权收盘价'),
                        data: [],
                        borderColor: '#25627b',
                        backgroundColor: '#25627b12',
                        fill: true,
                        pointRadius: 0,
                        borderWidth: 2,
                        spanGaps: false,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                plugins: { legend: { display: false } },
                scales: { x: { ticks: { maxTicksLimit: 6 } }, y: { ticks: { color: '#657176' } } },
            },
        });
        function range(months) {
            const { selected, limited } = StockTable.historyWindow(rows, months);
            instance.data.labels = selected.map((r) => r.date);
            instance.data.datasets[0].data = selected.map((r) => (r.quality === 'valid' ? r.close : null));
            instance.update();
            document.querySelector('#chart-range-status').textContent = selected.length
                ? `${selected[0].date} — ${selected.at(-1).date} · ${selected.length} ${t('saved sessions', '个已保存交易日')}` +
                  (limited ? ' · ' + t('Limited history', '历史不足，仅展示已保存数据') : '')
                : t('No saved data in this range.', '该区间无已保存行情。');
            document
                .querySelectorAll('[data-months]')
                .forEach((b) => b.setAttribute('aria-pressed', String(Number(b.dataset.months) === months)));
        }
        document.querySelector('#chart-ranges').addEventListener('click', (e) => {
            const b = e.target.closest('[data-months]');
            if (b) range(Number(b.dataset.months));
        });
        range(0);
    }
});
