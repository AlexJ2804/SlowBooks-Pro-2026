/**
 * Budgeting UI — Goals, Sinking Funds, Pay Sources, Per-Paycheck Plan.
 * Phase 1, Task 1B.
 *
 * Two top-level pages share this module:
 *   /#/goals          → GoalsPage
 *   /#/sinking-funds  → SinkingFundsPage
 *
 * Plus a render helper for the dashboard widget:
 *   BudgetingDashboard.renderPerPaycheckPlan() → HTML string
 *
 * Styling follows existing SlowBooks conventions: --qb-navy primary,
 * --qb-gold for accent rules, existing .card / .dashboard-section /
 * .table-container components. No new color system introduced.
 */

// ===========================================================================
// Shared helpers
// ===========================================================================

const _BudgetingHelpers = {
    BILL_PERIODS_OPTIONS: [
        { value: 1,  label: 'Annual (1×/yr)' },
        { value: 2,  label: 'Semiannual (2×/yr)' },
        { value: 4,  label: 'Quarterly (4×/yr)' },
        { value: 12, label: 'Monthly (12×/yr)' },
    ],

    /** Money for display. Falls back to '$0.00' if value is null/undefined. */
    _money(v, currency) {
        const n = (v == null) ? 0 : Number(v);
        return formatCurrency(n, currency || 'USD');
    },

    /** Render a 0..100 progress bar (clamped). */
    _progressBar(pct, color) {
        const clamped = Math.max(0, Math.min(100, pct || 0));
        const colorVar = color || 'var(--qb-blue)';
        return `<div style="position:relative; height:8px; background:var(--rule); border-radius:4px; overflow:hidden;">
            <div style="position:absolute; left:0; top:0; height:100%; width:${clamped}%; background:${colorVar};"></div>
        </div>`;
    },

    /** Render an on-track pill (green/red). */
    _onTrackPill(onTrack) {
        const bg = onTrack ? 'var(--positive)' : 'var(--negative)';
        const label = onTrack ? 'On track' : 'Behind';
        return `<span style="display:inline-block; padding:2px 8px; font-size:10px; font-weight:600; color:#fff; background:${bg}; border-radius:8px;">${label}</span>`;
    },
};


// ===========================================================================
// Pay Sources — small inline form, used as a dependency for Goals/Funds.
// Exposed via the Goals page header so it doesn't need its own sidebar entry.
// ===========================================================================

const PaySourcesEditor = {
    async _load() { return await API.get('/pay-sources'); },

    async render() {
        const sources = await this._load();
        const rows = sources.map(s => `
            <tr>
                <td>${escapeHtml(s.name)}</td>
                <td>${escapeHtml(s.cadence)}</td>
                <td class="amount">${s.periods_per_year}</td>
                <td class="amount">${s.net_per_check != null ? _BudgetingHelpers._money(s.net_per_check) : '—'}</td>
                <td><button class="btn btn-sm btn-secondary" onclick="PaySourcesEditor.editNet(${s.id})">Edit net</button></td>
            </tr>`).join('');
        return `<div class="table-container">
            <table>
                <thead><tr>
                    <th>Earner</th><th>Cadence</th>
                    <th class="amount">Periods/yr</th>
                    <th class="amount">Net per check</th>
                    <th></th>
                </tr></thead>
                <tbody>${rows || `<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">No pay sources yet</td></tr>`}</tbody>
            </table>
        </div>
        <div style="margin-top:8px;">
            <button class="btn btn-secondary" onclick="PaySourcesEditor.addNew()">+ New pay source</button>
        </div>`;
    },

    addNew() {
        openModal('New Pay Source', `
            <form onsubmit="PaySourcesEditor.save(event)">
                <div class="form-grid">
                    <div class="form-group"><label>Name *</label>
                        <input name="name" required></div>
                    <div class="form-group"><label>Cadence *</label>
                        <select name="cadence" required>
                            <option value="weekly">Weekly (52)</option>
                            <option value="biweekly" selected>Biweekly (26)</option>
                            <option value="semimonthly">Semimonthly (24)</option>
                            <option value="monthly">Monthly (12)</option>
                        </select></div>
                    <div class="form-group"><label>Net per check (optional)</label>
                        <input name="net_per_check" type="number" step="0.01" placeholder="e.g. 2150.00"></div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>`);
    },

    async save(e) {
        e.preventDefault();
        const f = e.target;
        const data = { name: f.name.value, cadence: f.cadence.value };
        if (f.net_per_check.value) data.net_per_check = f.net_per_check.value;
        try {
            await API.post('/pay-sources', data);
            toast('Pay source created');
            closeModal();
            App.navigate('#/goals');  // re-render whichever page is current
        } catch (err) { toast(err.message, 'error'); }
    },

    async editNet(id) {
        const all = await this._load();
        const src = all.find(s => s.id === id);
        if (!src) return;
        openModal(`Edit ${src.name}`, `
            <form onsubmit="PaySourcesEditor.savePatch(event, ${id})">
                <div class="form-group"><label>Net per check</label>
                    <input name="net_per_check" type="number" step="0.01" value="${src.net_per_check || ''}"></div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>`);
    },

    async savePatch(e, id) {
        e.preventDefault();
        const v = e.target.net_per_check.value;
        try {
            await API.patch(`/pay-sources/${id}`,
                { net_per_check: v === '' ? null : v });
            toast('Updated');
            closeModal();
            App.navigate(window.location.hash || '#/goals');
        } catch (err) { toast(err.message, 'error'); }
    },
};


// ===========================================================================
// Goals page
// ===========================================================================

const GoalsPage = {
    async render() {
        const [goals, sources, accounts, paySourcesHtml] = await Promise.all([
            API.get('/goals'),
            API.get('/pay-sources'),
            API.get('/accounts'),
            PaySourcesEditor.render(),
        ]);
        this._sources = sources;
        this._accounts = accounts;

        const tiles = goals.length === 0
            ? `<div class="empty-state" style="grid-column:1/-1;"><p>No goals yet. Add a savings target to start tracking.</p></div>`
            : goals.map(g => this._renderTile(g)).join('');

        return `
            <div class="page-header">
                <h2>Savings Goals</h2>
                <div class="btn-group">
                    <button class="btn btn-secondary" onclick="App.navigate('#/sinking-funds')">Sinking Funds</button>
                    <button class="btn btn-primary" onclick="GoalsPage.addNew()">+ New goal</button>
                </div>
            </div>

            <div class="card-grid" style="grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap:12px;">
                ${tiles}
            </div>

            <div class="dashboard-section" style="margin-top:20px;">
                <h3>Pay Sources</h3>
                <div style="color:var(--text-muted); font-size:11px; margin-bottom:8px;">
                    Earners and cadences. The Per-Paycheck Plan widget on the
                    dashboard uses these to convert monthly set-asides into
                    per-check figures.
                </div>
                ${paySourcesHtml}
            </div>
        `;
    },

    _renderTile(g) {
        const pct = Math.max(0, Math.min(100, g.progress_pct || 0));
        const targetStr = _BudgetingHelpers._money(g.target_amount, g.currency);
        const savedStr = _BudgetingHelpers._money(g.current_saved, g.currency);
        const monthlyStr = _BudgetingHelpers._money(g.monthly_required, g.currency);
        const source = (this._sources || []).find(s => s.id === g.funding_source_id);
        const sourceLabel = source ? source.name : '—';
        return `
            <div class="card" style="display:flex; flex-direction:column; gap:8px;">
                <div style="display:flex; justify-content:space-between; align-items:start;">
                    <div>
                        <div style="font-weight:700; font-size:14px;">${escapeHtml(g.name)}</div>
                        <div style="font-size:11px; color:var(--text-muted);">
                            Target ${targetStr} by ${formatDate(g.target_date)} &middot; ${g.months_until} mo left
                        </div>
                    </div>
                    ${_BudgetingHelpers._onTrackPill(g.on_track)}
                </div>
                <div>
                    <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:4px;">
                        <span>${savedStr} saved</span>
                        <span style="color:var(--text-muted);">${pct.toFixed(0)}%</span>
                    </div>
                    ${_BudgetingHelpers._progressBar(pct)}
                </div>
                <div style="font-size:11px; color:var(--text-muted); display:flex; justify-content:space-between;">
                    <span>Required: <strong style="color:var(--ink);">${monthlyStr}/mo</strong></span>
                    <span>Funded by ${escapeHtml(sourceLabel)}</span>
                </div>
                <div style="display:flex; gap:6px; margin-top:4px;">
                    <button class="btn btn-sm btn-secondary" onclick="GoalsPage.edit(${g.id})">Edit</button>
                    <button class="btn btn-sm btn-secondary" onclick="GoalsPage.del(${g.id}, '${escapeJs(g.name)}')">Delete</button>
                </div>
            </div>`;
    },

    _formHtml(g) {
        const sources = this._sources || [];
        const accounts = (this._accounts || []).filter(
            a => a.account_type === 'asset' && a.is_active
        );
        const srcOpts = sources.map(s =>
            `<option value="${s.id}" ${g && g.funding_source_id === s.id ? 'selected' : ''}>${escapeHtml(s.name)} (${s.cadence})</option>`
        ).join('');
        const acctOpts = accounts.map(a =>
            `<option value="${a.id}" ${g && g.linked_account_id === a.id ? 'selected' : ''}>${escapeHtml(a.name)}</option>`
        ).join('');
        return `
            <div class="form-grid">
                <div class="form-group"><label>Name *</label>
                    <input name="name" required value="${g ? escapeHtml(g.name) : ''}"></div>
                <div class="form-group"><label>Target amount *</label>
                    <input name="target_amount" type="number" step="0.01" required value="${g ? g.target_amount : ''}"></div>
                <div class="form-group"><label>Target date *</label>
                    <input name="target_date" type="date" required value="${g ? g.target_date : ''}"></div>
                <div class="form-group"><label>Currently saved</label>
                    <input name="current_saved" type="number" step="0.01" value="${g ? g.current_saved : '0'}"></div>
                <div class="form-group"><label>Funded by</label>
                    <select name="funding_source_id"><option value="">—</option>${srcOpts}</select></div>
                <div class="form-group"><label>Holding account</label>
                    <select name="linked_account_id"><option value="">—</option>${acctOpts}</select></div>
            </div>`;
    },

    addNew() {
        openModal('New Goal', `
            <form onsubmit="GoalsPage.save(event)">
                ${this._formHtml(null)}
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>`);
    },

    async edit(id) {
        const goals = await API.get('/goals');
        const g = goals.find(x => x.id === id);
        if (!g) return;
        openModal('Edit Goal', `
            <form onsubmit="GoalsPage.save(event, ${id})">
                ${this._formHtml(g)}
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>`);
    },

    async save(e, id) {
        e.preventDefault();
        const f = e.target;
        const data = {
            name: f.name.value,
            target_amount: f.target_amount.value,
            target_date: f.target_date.value,
            current_saved: f.current_saved.value || '0',
            funding_source_id: f.funding_source_id.value ? parseInt(f.funding_source_id.value) : null,
            linked_account_id: f.linked_account_id.value ? parseInt(f.linked_account_id.value) : null,
        };
        try {
            if (id) await API.patch(`/goals/${id}`, data);
            else    await API.post('/goals', data);
            toast(id ? 'Goal updated' : 'Goal created');
            closeModal();
            App.navigate('#/goals');
        } catch (err) { toast(err.message, 'error'); }
    },

    async del(id, name) {
        if (!confirm(`Delete goal "${name}"? This cannot be undone.`)) return;
        try {
            await API.del(`/goals/${id}`);
            toast('Goal deleted');
            App.navigate('#/goals');
        } catch (err) { toast(err.message, 'error'); }
    },
};


// ===========================================================================
// Sinking Funds page — envelope list
// ===========================================================================

const SinkingFundsPage = {
    async render() {
        const [funds, sources, accounts] = await Promise.all([
            API.get('/sinking-funds'),
            API.get('/pay-sources'),
            API.get('/accounts'),
        ]);
        this._sources = sources;
        this._accounts = accounts;

        const monthly = funds.filter(f => f.bill_periods_per_year === 12);
        const periodic = funds.filter(f => f.bill_periods_per_year !== 12);

        const renderRow = (f) => {
            const source = sources.find(s => s.id === f.funding_source_id);
            const sourceLabel = source ? source.name : '—';
            const fillPct = f.amount > 0
                ? Math.min(100, (Number(f.current_balance) / Number(f.amount)) * 100)
                : 0;
            return `
                <div class="card" style="display:flex; flex-direction:column; gap:8px;">
                    <div style="display:flex; justify-content:space-between; align-items:start;">
                        <div>
                            <div style="font-weight:700; font-size:14px;">${escapeHtml(f.name)}</div>
                            <div style="font-size:11px; color:var(--text-muted);">
                                ${_BudgetingHelpers._money(f.amount, f.currency)} × ${f.bill_periods_per_year}/yr
                                ${f.next_due ? `&middot; next ${formatDate(f.next_due)}` : ''}
                            </div>
                        </div>
                        <span style="font-size:11px; color:var(--text-muted);">
                            ${_BudgetingHelpers._money(f.monthly_accrual, f.currency)}/mo
                        </span>
                    </div>
                    <div>
                        <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:4px;">
                            <span>${_BudgetingHelpers._money(f.current_balance, f.currency)} saved</span>
                            <span style="color:var(--text-muted);">${fillPct.toFixed(0)}% of next bill</span>
                        </div>
                        ${_BudgetingHelpers._progressBar(fillPct, 'var(--qb-gold)')}
                    </div>
                    <div style="font-size:11px; color:var(--text-muted);">
                        Funded by ${escapeHtml(sourceLabel)}
                    </div>
                    <div style="display:flex; gap:6px; margin-top:4px;">
                        <button class="btn btn-sm btn-secondary" onclick="SinkingFundsPage.edit(${f.id})">Edit</button>
                        <button class="btn btn-sm btn-secondary" onclick="SinkingFundsPage.del(${f.id}, '${escapeJs(f.name)}')">Delete</button>
                    </div>
                </div>`;
        };

        const periodicHtml = periodic.length
            ? `<div class="dashboard-section">
                <h3>Periodic Envelopes <span style="font-size:11px; color:var(--text-muted); font-weight:normal;">(annual / semiannual / quarterly — balance climbs toward next bill)</span></h3>
                <div class="card-grid" style="grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap:12px;">
                    ${periodic.map(renderRow).join('')}
                </div>
            </div>`
            : '';

        const monthlyHtml = monthly.length
            ? `<div class="dashboard-section">
                <h3>Monthly Envelopes <span style="font-size:11px; color:var(--text-muted); font-weight:normal;">(reset each cycle — current_balance shows what's available right now)</span></h3>
                <div class="card-grid" style="grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap:12px;">
                    ${monthly.map(renderRow).join('')}
                </div>
            </div>`
            : '';

        const emptyHtml = (!periodic.length && !monthly.length)
            ? `<div class="empty-state"><p>No sinking funds yet. Add a recurring bill (e.g. car insurance, phone) to pre-fund.</p></div>`
            : '';

        return `
            <div class="page-header">
                <h2>Sinking Funds</h2>
                <div class="btn-group">
                    <button class="btn btn-secondary" onclick="App.navigate('#/goals')">Goals</button>
                    <button class="btn btn-primary" onclick="SinkingFundsPage.addNew()">+ New fund</button>
                </div>
            </div>
            ${periodicHtml}
            ${monthlyHtml}
            ${emptyHtml}
        `;
    },

    _formHtml(f) {
        const sources = this._sources || [];
        const accounts = (this._accounts || []).filter(
            a => a.account_type === 'asset' && a.is_active
        );
        const srcOpts = sources.map(s =>
            `<option value="${s.id}" ${f && f.funding_source_id === s.id ? 'selected' : ''}>${escapeHtml(s.name)} (${s.cadence})</option>`
        ).join('');
        const acctOpts = accounts.map(a =>
            `<option value="${a.id}" ${f && f.linked_account_id === a.id ? 'selected' : ''}>${escapeHtml(a.name)}</option>`
        ).join('');
        const bpyOpts = _BudgetingHelpers.BILL_PERIODS_OPTIONS.map(o =>
            `<option value="${o.value}" ${f && f.bill_periods_per_year === o.value ? 'selected' : ''}>${o.label}</option>`
        ).join('');
        return `
            <div class="form-grid">
                <div class="form-group"><label>Name *</label>
                    <input name="name" required value="${f ? escapeHtml(f.name) : ''}"></div>
                <div class="form-group"><label>Bill amount (per occurrence) *</label>
                    <input name="amount" type="number" step="0.01" required value="${f ? f.amount : ''}"></div>
                <div class="form-group"><label>Frequency *</label>
                    <select name="bill_periods_per_year" required>${bpyOpts}</select></div>
                <div class="form-group"><label>Next due (optional)</label>
                    <input name="next_due" type="date" value="${f && f.next_due ? f.next_due : ''}"></div>
                <div class="form-group"><label>Current envelope balance</label>
                    <input name="current_balance" type="number" step="0.01" value="${f ? f.current_balance : '0'}"></div>
                <div class="form-group"><label>Funded by</label>
                    <select name="funding_source_id"><option value="">—</option>${srcOpts}</select></div>
                <div class="form-group"><label>Holding account</label>
                    <select name="linked_account_id"><option value="">—</option>${acctOpts}</select></div>
            </div>`;
    },

    addNew() {
        openModal('New Sinking Fund', `
            <form onsubmit="SinkingFundsPage.save(event)">
                ${this._formHtml(null)}
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>`);
    },

    async edit(id) {
        const funds = await API.get('/sinking-funds');
        const f = funds.find(x => x.id === id);
        if (!f) return;
        openModal('Edit Sinking Fund', `
            <form onsubmit="SinkingFundsPage.save(event, ${id})">
                ${this._formHtml(f)}
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>`);
    },

    async save(e, id) {
        e.preventDefault();
        const f = e.target;
        const data = {
            name: f.name.value,
            amount: f.amount.value,
            bill_periods_per_year: parseInt(f.bill_periods_per_year.value),
            next_due: f.next_due.value || null,
            current_balance: f.current_balance.value || '0',
            funding_source_id: f.funding_source_id.value ? parseInt(f.funding_source_id.value) : null,
            linked_account_id: f.linked_account_id.value ? parseInt(f.linked_account_id.value) : null,
        };
        try {
            if (id) await API.patch(`/sinking-funds/${id}`, data);
            else    await API.post('/sinking-funds', data);
            toast(id ? 'Fund updated' : 'Fund created');
            closeModal();
            App.navigate('#/sinking-funds');
        } catch (err) { toast(err.message, 'error'); }
    },

    async del(id, name) {
        if (!confirm(`Delete fund "${name}"? This cannot be undone.`)) return;
        try {
            await API.del(`/sinking-funds/${id}`);
            toast('Fund deleted');
            App.navigate('#/sinking-funds');
        } catch (err) { toast(err.message, 'error'); }
    },
};


// ===========================================================================
// Dashboard widget — "Per-Paycheck Plan"
// ===========================================================================

const BudgetingDashboard = {
    /** Returns the widget HTML (or '' if there's nothing to show). */
    async renderPerPaycheckPlan() {
        let plans;
        try {
            plans = await API.get('/budget/per-paycheck-plan');
        } catch (e) { return ''; }
        if (!plans || plans.length === 0) return '';

        // Hide the widget entirely if every earner has 0 set-aside — that
        // means the household hasn't configured any goals/funds yet, and
        // a row of zeros isn't useful clutter.
        const anyMoney = plans.some(p => Number(p.monthly_total) > 0);
        if (!anyMoney) return '';

        const cards = plans.map(p => {
            const cadenceLabel = `per ${p.cadence === 'biweekly' ? 'biweekly' : p.cadence} check`;
            const items = (p.items || []).map(it => `
                <tr>
                    <td>${escapeHtml(it.name)}</td>
                    <td style="font-size:10px; color:var(--text-muted); text-transform:capitalize;">
                        ${it.kind.replace('_', ' ')}
                    </td>
                    <td class="amount">${_BudgetingHelpers._money(it.monthly)}</td>
                    <td class="amount" style="color:var(--qb-navy); font-weight:600;">${_BudgetingHelpers._money(it.per_check)}</td>
                </tr>`).join('');
            const detailsId = `ppc-details-${p.pay_source_id}`;
            return `
                <div class="card" style="display:flex; flex-direction:column; gap:6px;">
                    <div style="display:flex; justify-content:space-between; align-items:baseline;">
                        <div>
                            <div style="font-size:11px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em;">${escapeHtml(p.pay_source_name)}</div>
                            <div style="font-size:20px; font-weight:700; color:var(--qb-navy);">
                                Set aside ${_BudgetingHelpers._money(p.per_check_total)}
                            </div>
                            <div style="font-size:11px; color:var(--text-muted);">${cadenceLabel}</div>
                        </div>
                        <div style="text-align:right; font-size:10px; color:var(--text-muted);">
                            <div>${_BudgetingHelpers._money(p.monthly_total)} / month</div>
                            <div>${p.periods_per_year} checks/yr</div>
                        </div>
                    </div>
                    ${p.items.length ? `
                        <details id="${detailsId}" style="margin-top:4px;">
                            <summary style="cursor:pointer; font-size:11px; color:var(--qb-navy); user-select:none;">
                                ${p.items.length} item${p.items.length === 1 ? '' : 's'}
                            </summary>
                            <div class="table-container" style="margin-top:6px;">
                                <table style="font-size:11px;">
                                    <thead><tr>
                                        <th>Item</th><th>Kind</th>
                                        <th class="amount">Monthly</th>
                                        <th class="amount">Per check</th>
                                    </tr></thead>
                                    <tbody>${items}</tbody>
                                </table>
                            </div>
                        </details>
                    ` : ''}
                </div>`;
        }).join('');

        return `
            <div class="dashboard-section">
                <h3>Per-Paycheck Plan
                    <span style="font-size:11px; color:var(--text-muted); font-weight:normal;">
                        — what to set aside per paycheck for goals + sinking funds
                    </span>
                </h3>
                <div class="card-grid" style="grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:12px;">
                    ${cards}
                </div>
            </div>`;
    },
};
