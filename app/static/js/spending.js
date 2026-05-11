/**
 * Spending — monthly trend + per-category breakdown + top merchants.
 * Phase 3 — analytics built on the categorization loop.
 *
 * Charts are hand-rolled SVG (no external chart lib). The colour palette
 * is the Slowbooks token set; categories cycle through a fixed palette so
 * the same category is the same colour across renders.
 */
const SpendingPage = {
    state: {
        bankAccounts: [],
        bankAccountId: '',     // '' = all
        currentMonth: null,    // 'YYYY-MM'
    },

    // 12-step palette borrowed from the dashboard charts. Repeats for >12.
    PALETTE: [
        'var(--qb-blue)', 'var(--success)', 'var(--qb-gold)', '#f97316',
        '#a855f7', '#06b6d4', 'var(--danger)', '#10b981',
        '#f59e0b', '#3b82f6', '#ec4899', '#84cc16',
    ],

    async render() {
        const today = new Date();
        if (!SpendingPage.state.currentMonth) {
            SpendingPage.state.currentMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
        }
        SpendingPage.state.bankAccounts = await API.get('/spending/accounts');
        return SpendingPage._renderHtml();
    },

    async _renderHtml() {
        const month = SpendingPage.state.currentMonth;
        const baFilter = SpendingPage.state.bankAccountId
            ? `&bank_account_id=${SpendingPage.state.bankAccountId}`
            : '';

        const [monthly, byCat, topMerchants, topIncome] = await Promise.all([
            API.get(`/spending/monthly?months=12${baFilter}`),
            API.get(`/spending/by-category?month=${month}&direction=expense${baFilter}`),
            API.get(`/spending/top-merchants?month=${month}&direction=expense&limit=10${baFilter}`),
            API.get(`/spending/by-category?month=${month}&direction=income${baFilter}`),
        ]);

        const html = `
            <div class="page-header">
                <h2>Spending</h2>
                <div class="btn-group">
                    <select id="spending-account" onchange="SpendingPage.changeAccount(this.value)">
                        <option value="">All accounts</option>
                        ${SpendingPage.state.bankAccounts.map(ba =>
                            `<option value="${ba.id}" ${String(ba.id) === SpendingPage.state.bankAccountId ? 'selected' : ''}>${escapeHtml(ba.name)}${ba.is_active ? '' : ' (inactive)'}</option>`
                        ).join('')}
                    </select>
                    <select id="spending-month" onchange="SpendingPage.changeMonth(this.value)">
                        ${SpendingPage._monthOptions(monthly.months, month)}
                    </select>
                </div>
            </div>

            <div class="dashboard-section">
                <h3>Income vs Expense — last 12 months</h3>
                ${SpendingPage._renderMonthlyChart(monthly)}
                <div style="font-size:11px; color:var(--text-muted); margin-top:8px;">
                    Net: ${formatCurrency(monthly.total_income + monthly.total_expense)}
                    over the window
                    (income ${formatCurrency(monthly.total_income)},
                    expense ${formatCurrency(monthly.total_expense)}).
                </div>
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
                <div class="dashboard-section">
                    <h3>${SpendingPage._formatMonthLabel(month)} — spend by category</h3>
                    ${SpendingPage._renderPieChart(byCat, 'expense')}
                </div>
                <div class="dashboard-section">
                    <h3>${SpendingPage._formatMonthLabel(month)} — top 10 merchants</h3>
                    ${SpendingPage._renderTopList(topMerchants)}
                </div>
            </div>

            ${topIncome.items.length ? `
            <div class="dashboard-section">
                <h3>${SpendingPage._formatMonthLabel(month)} — income by category</h3>
                ${SpendingPage._renderPieChart(topIncome, 'income')}
            </div>` : ''}

            <div style="font-size:10px; color:var(--text-muted); margin-top:16px;">
                Multi-currency note: Revolut EUR/CZK/GBP/etc rows are summed at face value
                without FX conversion. Totals are accurate for USD-denominated accounts;
                slightly off for the multi-currency Revolut account. Filter by account to
                isolate currencies.
            </div>
        `;
        return html;
    },

    _monthOptions(months, selectedKey) {
        // Reverse so most-recent is first.
        return months.slice().reverse().map(m =>
            `<option value="${m.month}" ${m.month === selectedKey ? 'selected' : ''}>${SpendingPage._formatMonthLabel(m.month)}</option>`
        ).join('');
    },

    _formatMonthLabel(yyyyMm) {
        if (!yyyyMm) return '';
        const [y, m] = yyyyMm.split('-');
        const d = new Date(parseInt(y, 10), parseInt(m, 10) - 1, 1);
        return d.toLocaleString('en-US', { month: 'short', year: 'numeric' });
    },

    _renderMonthlyChart(data) {
        const months = data.months;
        if (!months.length) return '<div class="empty-state">No data in window.</div>';

        const W = 720, H = 220;
        const padL = 50, padR = 12, padT = 12, padB = 32;
        const innerW = W - padL - padR;
        const innerH = H - padT - padB;

        // Find absolute peak (income or |expense|) for the y-scale.
        const peak = months.reduce((max, m) =>
            Math.max(max, m.income, Math.abs(m.expense)), 1);

        // Bar group per month: income bar above zero, expense bar below.
        const groupW = innerW / months.length;
        const barW = Math.max(2, groupW * 0.35);
        const zeroY = padT + innerH / 2;

        const incomeBars = months.map((m, i) => {
            const x = padL + i * groupW + groupW / 2 - barW;
            const h = (m.income / peak) * (innerH / 2);
            const y = zeroY - h;
            return `<rect x="${x}" y="${y}" width="${barW}" height="${h}"
                          fill="var(--success)" opacity="0.85">
                          <title>${m.month}: income ${formatCurrency(m.income)}</title>
                    </rect>`;
        }).join('');

        const expenseBars = months.map((m, i) => {
            const x = padL + i * groupW + groupW / 2;
            const h = (Math.abs(m.expense) / peak) * (innerH / 2);
            const y = zeroY;
            return `<rect x="${x}" y="${y}" width="${barW}" height="${h}"
                          fill="var(--danger)" opacity="0.85">
                          <title>${m.month}: expense ${formatCurrency(m.expense)}</title>
                    </rect>`;
        }).join('');

        const xLabels = months.map((m, i) => {
            const x = padL + i * groupW + groupW / 2;
            const [y, mo] = m.month.split('-');
            const d = new Date(parseInt(y, 10), parseInt(mo, 10) - 1, 1);
            const txt = d.toLocaleString('en-US', { month: 'short' });
            return `<text x="${x}" y="${H - 8}" font-size="10"
                          fill="var(--text-muted)" text-anchor="middle">${txt}</text>`;
        }).join('');

        // Y-axis: zero, +peak, -peak labels
        const yLabels = `
            <text x="${padL - 6}" y="${zeroY + 3}" font-size="10"
                  fill="var(--text-muted)" text-anchor="end">0</text>
            <text x="${padL - 6}" y="${padT + 8}" font-size="10"
                  fill="var(--text-muted)" text-anchor="end">${SpendingPage._kfmt(peak)}</text>
            <text x="${padL - 6}" y="${H - padB + 4}" font-size="10"
                  fill="var(--text-muted)" text-anchor="end">-${SpendingPage._kfmt(peak)}</text>
        `;

        return `
            <svg viewBox="0 0 ${W} ${H}" style="width:100%; max-width:100%; height:auto;">
                <line x1="${padL}" y1="${zeroY}" x2="${W - padR}" y2="${zeroY}"
                      stroke="var(--border)" stroke-width="1"/>
                ${incomeBars}
                ${expenseBars}
                ${xLabels}
                ${yLabels}
            </svg>
            <div style="display:flex; gap:16px; margin-top:6px; font-size:11px;">
                <span><span style="color:var(--success);">&#9632;</span> Income</span>
                <span><span style="color:var(--danger);">&#9632;</span> Expense</span>
            </div>
        `;
    },

    _renderPieChart(data, direction) {
        const items = data.items.filter(i => Math.abs(i.total) > 0.005);
        if (!items.length) return '<div class="empty-state">No data for this month.</div>';

        const total = items.reduce((s, i) => s + Math.abs(i.total), 0);
        if (total === 0) return '<div class="empty-state">No data for this month.</div>';

        const SIZE = 220, R_OUT = 100, R_IN = 60;
        const cx = SIZE / 2, cy = SIZE / 2;

        let angle = -Math.PI / 2;  // start at 12 o'clock
        const slices = items.map((it, i) => {
            const frac = Math.abs(it.total) / total;
            const sweep = frac * Math.PI * 2;
            const a0 = angle, a1 = angle + sweep;
            angle = a1;
            const fill = it.is_uncategorized ? 'var(--text-muted)' : SpendingPage.PALETTE[i % SpendingPage.PALETTE.length];

            const large = sweep > Math.PI ? 1 : 0;
            const x0o = cx + R_OUT * Math.cos(a0), y0o = cy + R_OUT * Math.sin(a0);
            const x1o = cx + R_OUT * Math.cos(a1), y1o = cy + R_OUT * Math.sin(a1);
            const x0i = cx + R_IN * Math.cos(a1),  y0i = cy + R_IN * Math.sin(a1);
            const x1i = cx + R_IN * Math.cos(a0),  y1i = cy + R_IN * Math.sin(a0);

            const d = [
                `M ${x0o} ${y0o}`,
                `A ${R_OUT} ${R_OUT} 0 ${large} 1 ${x1o} ${y1o}`,
                `L ${x0i} ${y0i}`,
                `A ${R_IN} ${R_IN} 0 ${large} 0 ${x1i} ${y1i}`,
                'Z',
            ].join(' ');

            return `<path d="${d}" fill="${fill}" opacity="0.92">
                        <title>${escapeHtml(it.name)}: ${formatCurrency(it.total)} (${(frac * 100).toFixed(1)}%)</title>
                    </path>`;
        }).join('');

        const legend = items.map((it, i) => {
            const frac = Math.abs(it.total) / total;
            const fill = it.is_uncategorized ? 'var(--text-muted)' : SpendingPage.PALETTE[i % SpendingPage.PALETTE.length];
            return `
                <div style="display:flex; align-items:center; gap:6px; font-size:11px; padding:2px 0;">
                    <span style="display:inline-block; width:10px; height:10px; background:${fill};"></span>
                    <span style="flex:1; ${it.is_uncategorized ? 'font-style:italic; color:var(--text-muted);' : ''}">${escapeHtml(it.name)}</span>
                    <span style="color:var(--text-muted);">${(frac * 100).toFixed(1)}%</span>
                    <span class="amount" style="min-width:80px; text-align:right;">${formatCurrency(it.total)}</span>
                </div>`;
        }).join('');

        const centerLabel = direction === 'expense' ? 'Spent' : 'Earned';
        return `
            <div style="display:grid; grid-template-columns:auto 1fr; gap:16px; align-items:center;">
                <div style="position:relative; width:${SIZE}px; height:${SIZE}px;">
                    <svg viewBox="0 0 ${SIZE} ${SIZE}" width="${SIZE}" height="${SIZE}">${slices}</svg>
                    <div style="position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center;">
                        <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px;">${centerLabel}</div>
                        <div style="font-size:14px; font-weight:600;">${formatCurrency(direction === 'expense' ? -total : total)}</div>
                    </div>
                </div>
                <div style="min-width:0; max-height:240px; overflow-y:auto;">${legend}</div>
            </div>
        `;
    },

    _renderTopList(data) {
        const items = data.items;
        if (!items.length) return '<div class="empty-state">No transactions this month.</div>';

        return `
            <div class="table-container" style="max-height:280px; overflow-y:auto;">
                <table>
                    <thead><tr>
                        <th>Merchant</th>
                        <th class="amount">Count</th>
                        <th class="amount">Total</th>
                    </tr></thead>
                    <tbody>
                        ${items.map(it => `
                            <tr>
                                <td style="font-family:var(--font-mono); font-size:11px;">${escapeHtml(it.payee)}</td>
                                <td class="amount">${it.count}</td>
                                <td class="amount">${formatCurrency(it.total)}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    },

    _kfmt(n) {
        if (Math.abs(n) >= 1000) return (n / 1000).toFixed(0) + 'k';
        return Math.round(n).toString();
    },

    async changeMonth(yyyyMm) {
        SpendingPage.state.currentMonth = yyyyMm;
        $('#page-content').innerHTML = await SpendingPage._renderHtml();
    },

    async changeAccount(value) {
        SpendingPage.state.bankAccountId = value || '';
        $('#page-content').innerHTML = await SpendingPage._renderHtml();
    },
};
