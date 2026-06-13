/**
 * Net worth dashboard — net worth phase 1, task 5.
 *
 * Renders household + Alex/Alexa/Kids slices from /api/net-worth.
 * Server does all the math; this page is purely presentational.
 *
 * The "as of" timestamp on each account row is how we surface staleness:
 * if the user sees that Vanguard (Alexa) was last updated 6 weeks ago
 * they know to go enter a fresh balance via /#/balances.
 */
const NetWorthPage = {
    async render() {
        const data = await API.get('/net-worth');
        const home = data.home_currency || 'USD';

        const totals = data.totals || {};
        const household = totals.household || {};
        const slices = [
            ['Alex',  totals.alex],
            ['Alexa', totals.alexa],
            ['Kids',  totals.kids],
        ];

        // Banner shown when FX fell back to hardcoded or identity rates.
        let fxBanner = '';
        if (data.fx_status === 'fallback' || data.fx_status === 'mixed') {
            const warnings = (data.fx_warnings || []).map(w => `<li>${escapeHtml(w)}</li>`).join('');
            const head = data.fx_status === 'mixed'
                ? 'Some FX rates fell back to hardcoded constants (BoC live rates partial).'
                : 'Live FX rates unavailable — using hardcoded fallback constants.';
            fxBanner = `<div style="background:#fff7d6; border:1px solid #d4b03a; padding:8px 12px; margin:8px 0; font-size:11px;">
                <strong>FX warning:</strong> ${escapeHtml(head)}
                ${warnings ? `<ul style="margin:4px 0 0 16px;">${warnings}</ul>` : ''}
            </div>`;
        }

        let html = `
            <div class="page-header">
                <h2>Net Worth</h2>
                <span style="font-size:11px; color:var(--text-muted);">
                    All values in ${escapeHtml(home)} · as of ${formatDate(data.as_of?.slice(0, 10))}
                </span>
            </div>
            ${fxBanner}
            <div style="display:flex; gap:12px; margin-bottom:16px;">
                ${NetWorthPage._headlineCard('Household', household, home, true)}
                ${slices.map(([label, t]) => NetWorthPage._headlineCard(label, t || {}, home, false)).join('')}
            </div>
            <h3 style="font-size:13px; margin:8px 0;">Account breakdown</h3>
            ${NetWorthPage._breakdownTable(data.accounts || [], home)}
        `;
        return html;
    },

    _headlineCard(label, slice, home, primary) {
        const net = slice.net !== undefined ? slice.net : '0';
        const assets = slice.assets !== undefined ? slice.assets : '0';
        const liabilities = slice.liabilities !== undefined ? slice.liabilities : '0';
        const bg = primary ? '#1f5fa8' : '#f5f7fa';
        const fg = primary ? '#fff' : 'var(--text-primary)';
        const labelColor = primary ? 'rgba(255,255,255,0.85)' : 'var(--text-muted)';
        return `<div style="flex: 1 1 0; min-width: 0; background:${bg}; color:${fg}; padding:12px 14px; border-radius:6px; border:1px solid ${primary ? '#1a4f8a' : 'var(--border)'};">
            <div style="font-size:11px; color:${labelColor}; text-transform:uppercase; letter-spacing:0.5px; font-weight:600;">${escapeHtml(label)}</div>
            <div style="font-size:${primary ? '24px' : '18px'}; font-weight:700; margin:4px 0;">${formatCurrency(net, home)}</div>
            <div style="font-size:10px; color:${labelColor};">
                <span title="Assets">A ${formatCurrency(assets, home)}</span>
                &nbsp;·&nbsp;
                <span title="Liabilities">L ${formatCurrency(liabilities, home)}</span>
            </div>
        </div>`;
    },

    _breakdownTable(accounts, home) {
        if (!accounts.length) {
            return '<div class="empty-state"><p>No personal accounts yet — set them up via /#/accounts</p></div>';
        }
        let html = `<div class="table-container"><table>
            <thead><tr>
                <th>Account</th>
                <th>Kind</th>
                <th class="amount">Latest Balance</th>
                <th>Currency</th>
                <th class="amount">In ${escapeHtml(home)}</th>
                <th class="amount">Alex</th>
                <th class="amount">Alexa</th>
                <th class="amount">Kids</th>
                <th>As of</th>
            </tr></thead><tbody>`;

        // Group rows by kind so the table is scannable.
        const byKind = {};
        for (const a of accounts) {
            const k = a.kind || '_other';
            (byKind[k] = byKind[k] || []).push(a);
        }
        const kindOrder = ['bank', 'brokerage', 'retirement', 'property', 'credit_card', 'loan', '_other'];
        const kindLabels = {
            bank: 'Banks', brokerage: 'Brokerage', retirement: 'Retirement',
            property: 'Property', credit_card: 'Credit Cards', loan: 'Loans',
            _other: 'Other',
        };

        for (const kind of kindOrder) {
            const rows = byKind[kind] || [];
            if (rows.length === 0) continue;
            html += `<tr style="background:linear-gradient(180deg, #e8ecf2 0%, #dde2ea 100%);">
                <td colspan="9" style="font-weight:700; color:var(--qb-navy); font-size:11px; padding:4px 10px;">${escapeHtml(kindLabels[kind] || kind)}</td>
            </tr>`;
            for (const a of rows) {
                const stale = NetWorthPage._stalenessClass(a.latest_balance_as_of);
                const isLiability = !!a.is_liability;
                html += `<tr>
                    <td><strong>${escapeHtml(a.name)}</strong></td>
                    <td>${App._kindChip(a.kind)}</td>
                    <td class="amount">${a.latest_balance_native !== null ? formatCurrency(a.latest_balance_native, a.currency) : '<span style="color:var(--text-muted);">—</span>'}</td>
                    <td style="font-family:var(--font-mono); font-size:11px;">${escapeHtml((a.currency || 'USD').toUpperCase())}</td>
                    <td class="amount" style="${isLiability ? 'color:var(--qb-red, #c00);' : ''}">
                        ${a.signed_balance_home !== null ? formatCurrency(a.signed_balance_home, home) : '<span style="color:var(--text-muted);">—</span>'}
                    </td>
                    <td class="amount">${a.contributions?.alex !== null && a.contributions?.alex !== undefined ? formatCurrency(a.contributions.alex, home) : '—'}</td>
                    <td class="amount">${a.contributions?.alexa !== null && a.contributions?.alexa !== undefined ? formatCurrency(a.contributions.alexa, home) : '—'}</td>
                    <td class="amount">${a.contributions?.kids !== null && a.contributions?.kids !== undefined ? formatCurrency(a.contributions.kids, home) : '—'}</td>
                    <td style="${stale}; font-size:11px;">${a.latest_balance_as_of ? formatDate(a.latest_balance_as_of) : '<span style="color:var(--text-muted);">never</span>'}</td>
                </tr>`;
            }
        }
        html += '</tbody></table></div>';
        return html;
    },

    _stalenessClass(asOfStr) {
        // Color the as-of date red if older than 30 days — a heuristic
        // for "go update this" without being noisy on weekly cadence.
        if (!asOfStr) return '';
        const asOf = new Date(asOfStr);
        const daysAgo = (Date.now() - asOf.getTime()) / (1000 * 60 * 60 * 24);
        if (daysAgo > 30) return 'color:var(--qb-red, #c00); font-weight:600';
        if (daysAgo > 14) return 'color:#b45309'; // amber
        return '';
    },
};
