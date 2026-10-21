/* Native browser controls. Updates are durable jobs; polling only reads state. */
document.addEventListener('DOMContentLoaded', async () => {
    const zh = document.body.dataset.lang === 'zh';
    const t = (en, cn) => zh ? cn : en;
    let auth = null;
    const toast = message => {
        const el = document.querySelector('#toast');
        el.textContent = message;
        el.hidden = false;
        setTimeout(() => el.hidden = true, 6500);
    };
    const request = async (url, method = 'GET', data) => {
        const response = await fetch(url, {
            method,
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                ...(method === 'GET' ? {} : {
                    'X-CSRF-Token': auth?.csrf || ''
                })
            },
            body: data === undefined ? undefined : JSON.stringify(data)
        });
        const result = await response.json();
        if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : t('Request rejected. Check the fields.', '请求被拒绝，请检查填写内容。'));
        return result;
    };
    const safe = fn => async event => {
        event?.preventDefault();
        try {
            await fn(event);
        } catch (error) {
            toast(error.message);
        }
    };
    try {
        auth = await request('/api/auth/session');
    } catch (error) {
        toast(error.message);
    }
    const login = document.querySelector('#login');
    if (login) {
        if (!auth?.initialized) document.querySelector('#login-note').textContent = t('Administrator not initialized. Follow the startup instructions.', '管理员尚未初始化，请按启动说明完成初始化。');
        login.addEventListener('submit', safe(async () => {
            auth = await request('/api/auth/login', 'POST', {
                password: login.password.value
            });
            location.reload();
        }));
    }
    document.querySelector('#logout')?.addEventListener('click', safe(async () => {
        await request('/api/auth/logout', 'POST', {});
        location.href = '/';
    }));
    document.querySelector('#add-ticker')?.addEventListener('submit', safe(async event => {
        const f = event.target;
        await request('/api/tickers', 'POST', {
            symbol: f.elements.symbol.value,
            name: f.elements.name.value,
            yf_ticker: f.elements.yf_ticker.value || null,
            is_public: f.elements.is_public.checked
        });
        location.reload();
    }));
    document.querySelectorAll('.disable').forEach(button => button.addEventListener('click', safe(async () => {
        await request(`/api/tickers/${encodeURIComponent(button.dataset.symbol)}`, 'DELETE');
        location.reload();
    })));
    document.querySelectorAll('.visibility').forEach(button => button.addEventListener('click', safe(async () => {
        await request(`/api/tickers/${encodeURIComponent(button.dataset.symbol)}/visibility`, 'PATCH', {
            is_public: button.dataset.public !== '1'
        });
        location.reload();
    })));
    const statusNames = {
        queued: t('Queued', '排队中'),
        running: t('Running', '运行中'),
        published: t('Published', '已发布'),
        failed: t('Failed', '失败'),
        ok: t('Available', '可用'),
        insufficient_data: t('Insufficient data', '数据不足'),
        stale: t('Stale', '过期'),
        pending: t('Pending', '待更新')
    };
    const showRun = async id => {
        const r = await request(`/api/runs/${id}`);
        const target = document.querySelector('#run-status');
        if (target) target.textContent = `${statusNames[r.status]||r.status} · ${r.completed}/${r.total} · ${r.target_date}`;
        if (target && r.provider?.cooldown_active) target.textContent += ' · ' + t('Yahoo requests paused until ', 'Yahoo 请求暂停至 ') + new Date(r.provider.cooldown_until).toLocaleString();
        const progress = document.querySelector('#run-progress');
        if (progress) {
            progress.hidden = false;
            progress.value = r.total ? r.completed / r.total * 100 : 0;
        }
        const details = document.querySelector('#run-details');
        if (details) {
            details.replaceChildren();
            for (const a of r.assets) {
                const p = document.createElement('p');
                p.textContent = `${a.symbol} · ${statusNames[a.status]||a.status} · ${a.actual_date||'—'}${a.reason?' · '+a.reason:''}`;
                details.append(p);
            }
        }
        if (['queued', 'running'].includes(r.status)) setTimeout(() => showRun(id).catch(e => toast(e.message)), 2000);
        else {
            localStorage.removeItem('stock-update-run');
            document.querySelector('#update-data')?.removeAttribute('disabled');
            if (target) toast(t('Update finished. Reload to view the published data.', '更新已结束，刷新页面查看已发布数据。'));
        }
        return r;
    };
    document.querySelector('#update-data')?.addEventListener('click', safe(async event => {
        event.target.disabled = true;
        try {
            const r = await request('/api/prices/refresh', 'POST', {});
            localStorage.setItem('stock-update-run', r.run_id);
            await showRun(r.run_id);
        } catch (e) {
            event.target.disabled = false;
            throw e;
        }
    }));
    if (auth?.authenticated && document.querySelector('#run-status') && localStorage.getItem('stock-update-run')) showRun(localStorage.getItem('stock-update-run')).catch(e => toast(e.message));
    document.querySelectorAll('.inspect-run').forEach(button => button.addEventListener('click', safe(() => showRun(button.dataset.run))));
    document.querySelector('#search')?.addEventListener('input', event => document.querySelectorAll('#watch-table tbody tr').forEach(row => row.hidden = !row.textContent.toLowerCase().includes(event.target.value.toLowerCase())));
    document.querySelector('#sort')?.addEventListener('change', event => {
        const body = document.querySelector('#watch-table tbody');
        const rows = [...body.rows];
        rows.sort(event.target.value === 'price' ? (a, b) => Number(b.dataset.price) - Number(a.dataset.price) : (a, b) => (a.dataset.symbol || '').localeCompare(b.dataset.symbol || ''));
        rows.forEach(row => body.append(row));
    });
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
    const schedule = document.querySelector('#notification-settings');
    const deliveryNames = {
        sent: t('Sent', '已投递'),
        partial: t('Partially delivered — review', '部分投递，待核对'),
        unknown: t('Uncertain — review before any resend', '结果未知，重发前须核对'),
        queued: t('Queued', '待投递'),
        retryable: t('Waiting to retry', '等待重试'),
        blocked: t('Needs configuration', '需配置'),
        resolved: t('Resolved without resend', '已处理，未重发'),
        sending: t('Sending', '发送中')
    };
    const deliveries = async () => {
        const rows = await request('/api/notifications');
        const el = document.querySelector('#deliveries');
        el.replaceChildren();
        for (const r of rows) {
            const row = document.createElement('div');
            row.className = 'delivery-row';
            const text = document.createElement('span');
            text.textContent = `${r.target_date} · ${deliveryNames[r.status]||r.status} · ${r.parts_sent}/${r.parts_total}`;
            row.append(text);
            if (['unknown', 'partial', 'blocked'].includes(r.status)) {
                const b = document.createElement('button');
                b.className = 'quiet';
                b.textContent = t('Acknowledge, no resend', '确认处理，不重发');
                b.addEventListener('click', safe(async () => {
                    await request(`/api/notifications/${r.delivery_id}/resolve`, 'POST', {});
                    await deliveries();
                }));
                row.append(b);
            }
            if (r.status === 'retryable') {
                const b = document.createElement('button');
                b.className = 'quiet';
                b.textContent = t('Retry unsent parts', '重试未发送分段');
                b.addEventListener('click', safe(async () => {
                    await request(`/api/notifications/${r.delivery_id}/retry`, 'POST', {});
                    await deliveries();
                }));
                row.append(b);
            }
            el.append(row);
        }
        if (!rows.length) el.textContent = t('No deliveries yet.', '暂无投递记录。');
    };
    if (schedule && auth?.authenticated) {
        try {
            const s = await request('/api/settings');
            for (const key of ['update_time', 'notify_time', 'channel']) schedule.elements[key].value = s[key];
            schedule.enabled.checked = s.enabled;
            document.querySelector('#hub-config').textContent = s.hub_configured ? t('Hub connection configured.', '已配置 Hub 连接。') : t('Hub credentials are not configured on the server.', '服务器尚未配置 Hub 凭据。');
            await deliveries();
        } catch (e) {
            toast(e.message);
        }
        schedule.addEventListener('submit', safe(async () => {
            await request('/api/settings', 'PUT', {
                update_time: schedule.update_time.value,
                notify_time: schedule.notify_time.value,
                channel: schedule.channel.value,
                enabled: schedule.enabled.checked
            });
            toast(t('Saved. No message sent.', '已保存，未发送消息。'));
        }));
        document.querySelector('#test-notification').addEventListener('click', safe(async () => {
            if (!confirm(t('Send a test message through the configured hub channel?', '通过已配置的 Hub 渠道发送一条测试消息？'))) return;
            await request('/api/notifications/test', 'POST', {});
            toast(t('Test queued for the notification worker.', '测试消息已进入通知队列。'));
            await deliveries();
        }));
    }
});
