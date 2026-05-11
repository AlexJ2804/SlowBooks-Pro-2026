/**
 * Balance entry — net worth phase 1, task 4.
 *
 * A simple form for entering point-in-time balance snapshots. Account
 * dropdown is populated from /api/accounts. Date defaults to today.
 * Currency is filled from the selected account's native currency
 * (the user can override but rarely needs to).
 *
 * POST is upsert: re-entering for the same (account, date) overwrites
 * the previous value rather than throwing a unique-constraint error.
 *
 * Recent entries table below the form acts as a visual sanity check —
 * 50 most recent snapshots, most recent first.
 */
const BalancesPage = {
    _accounts: [],

    async render() {
        // Fetch all accounts; the dropdown shows account_kind in the
        // option label so the user can tell "Heartland Joint Checking
        // (bank)" apart from a same-named brokerage account.
        BalancesPage._accounts = await API.get('/accounts');
        const recent = await API.get('/balances?limit=50');

        const today = new Date().toISOString().slice(0, 10);

        // Filter the dropdown to only personal accounts (those with a
        // kind set). System COA rows like "Service Income" don't get
        // balance snapshots — they're aggregations of transactions.
        const personalAccounts = BalancesPage._accounts.filter(a => a.account_kind);
        personalAccounts.sort((a, b) => a.name.localeCompare(b.name));

        const accountOptions = personalAccounts.map(a =>
            `<option value="${a.id}" data-currency="${escapeHtml((a.currency || 'USD').toUpperCase())}">`
            + `${escapeHtml(a.name)} — ${a.account_kind || 'unknown'} (${escapeHtml((a.currency || 'USD').toUpperCase())})`
            + `</option>`
        ).join('');

        let html = `
            <div class="page-header">
                <h2>Balance Entry</h2>
            </div>
            <div style="display:flex; gap:24px; align-items:flex-start;">
                <form id="balance-form" onsubmit="BalancesPage.save(event)" style="flex: 0 0 360px;">
                    <div class="form-group">
                        <label>Account *</label>
                        <select name="account_id" required onchange="BalancesPage._syncCurrency()">
                            <option value="">— Select an account —</option>
                            ${accountOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Balance *</label>
                        <input name="balance" type="number" step="0.01" required>
                    </div>
                    <div class="form-group">
                        <label>Currency</label>
                        <select name="currency">
                            <option value="">— Account default —</option>
                            ${currencyOptions()}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>As-of Date *</label>
                        <input name="as_of_date" type="date" required value="${today}">
                    </div>
                    <div class="form-actions">
                        <button type="submit" class="btn btn-primary">Save Snapshot</button>
                    </div>
                    <div style="font-size:10px; color:var(--text-muted); margin-top:6px;">
                        Re-entering the same account + date overwrites the previous value.
                        For credit cards and loans, enter the current outstanding balance as a positive number — the dashboard treats those account kinds as liabilities and signs them automatically.
                    </div>
                </form>
                <div style="flex: 1 1 auto; min-width: 0;">
                    <h3 style="font-size:13px; margin:0 0 6px 0;">Recent entries</h3>
                    <div class="table-container" id="balance-recent">
                        ${BalancesPage._renderRecent(recent)}
                    </div>
                </div>
            </div>
        `;
        return html;
    },

    _renderRecent(rows) {
        if (!rows || rows.length === 0) {
            return '<div class="empty-state"><p>No balance snapshots yet</p></div>';
        }
        // Account header gets width:100% so it absorbs any slack;
        // every other column gets white-space:nowrap so they collapse
        // to their natural width and sit flush against Account.
        let html = `<table>
            <thead><tr>
                <th style="white-space:nowrap;">Date</th>
                <th style="width:100%;">Account</th>
                <th class="amount" style="white-space:nowrap;">Balance</th>
                <th style="white-space:nowrap;">Currency</th>
                <th style="white-space:nowrap; width:60px;">Actions</th>
            </tr></thead><tbody>`;
        for (const r of rows) {
            html += `<tr>
                <td>${formatDate(r.as_of_date)}</td>
                <td>${escapeHtml(r.account_name || '')}
                    ${r.account_kind ? '<span style="font-size:10px; color:var(--text-muted); margin-left:4px;">' + escapeHtml(r.account_kind.replace('_', ' ')) + '</span>' : ''}
                </td>
                <td class="amount">${formatCurrency(r.balance, r.currency)}</td>
                <td style="font-family:var(--font-mono); font-size:11px;">${escapeHtml(r.currency)}</td>
                <td class="actions">
                    <button class="btn btn-sm btn-danger" onclick="BalancesPage.deleteSnapshot(${r.id})">Delete</button>
                </td>
            </tr>`;
        }
        html += '</tbody></table>';
        return html;
    },

    _syncCurrency() {
        // Pre-pick the currency dropdown to match the selected account's
        // native currency so the user doesn't have to confirm it for the
        // common case. If the account's currency isn't one of the three
        // listed (USD/CAD/EUR), fall back to the "Account default"
        // option so the select doesn't end up in a broken
        // selectedIndex=-1 state.
        const form = document.getElementById('balance-form');
        if (!form) return;
        const accountSel = form.elements['account_id'];
        const opt = accountSel.options[accountSel.selectedIndex];
        const currencySel = form.elements['currency'];
        const wanted = (opt && opt.dataset && opt.dataset.currency) || '';
        const hasOption = [...currencySel.options].some(o => o.value === wanted);
        currencySel.value = hasOption ? wanted : '';
    },

    async save(e) {
        e.preventDefault();
        const form = e.target;
        const data = Object.fromEntries(new FormData(form).entries());
        const payload = {
            account_id: parseInt(data.account_id, 10),
            balance: data.balance,
            as_of_date: data.as_of_date,
        };
        if (data.currency) payload.currency = data.currency.toUpperCase();
        try {
            await API.post('/balances', payload);
            toast('Snapshot saved');
            // Refresh the recent-entries table inline rather than a full
            // page navigation so the form stays primed for the next
            // entry (the user often enters several in a row).
            const recent = await API.get('/balances?limit=50');
            const wrap = document.getElementById('balance-recent');
            if (wrap) wrap.innerHTML = BalancesPage._renderRecent(recent);
            // Clear the balance field; keep account + date for likely
            // next entry on a different account.
            form.elements['balance'].value = '';
        } catch (err) {
            toast(err.message || 'Save failed', 'error');
        }
    },

    async deleteSnapshot(id) {
        if (!confirm('Delete this balance snapshot?')) return;
        try {
            await API.del(`/balances/${id}`);
            toast('Snapshot deleted');
            const recent = await API.get('/balances?limit=50');
            const wrap = document.getElementById('balance-recent');
            if (wrap) wrap.innerHTML = BalancesPage._renderRecent(recent);
        } catch (err) {
            toast(err.message || 'Delete failed', 'error');
        }
    },
};
