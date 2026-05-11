/**
 * Categorize — LLM-assisted bulk categorization of unmatched bank txns.
 * Phase 3: spending analytics.
 *
 * Flow:
 *  1. Load top-N most-frequent uncategorized merchants
 *  2. User clicks "Suggest categories with AI" -> batch sent to /suggest
 *     -> per-row suggestion dropdown pre-fills with the LLM's pick
 *  3. User accepts (or overrides) per row -> POST /accept creates a
 *     BankRule and applies it to every matching unmatched txn in one shot
 *  4. Accepted rows are removed from the table; remaining merchants stay
 *     visible so the user can keep going
 */
const CategorizePage = {
    state: {
        items: [],          // [{normalized, payee, tx_count, spend_total, ...}]
        categories: [],     // [{id, name, type, account_number}]
        suggestions: {},    // {normalized -> {account_id, confidence, reason}}
        total: 0,
        limit: 100,
        offset: 0,
    },

    async render() {
        const [merchantsResp, categories] = await Promise.all([
            API.get('/categorize/unmatched-merchants?limit=100'),
            API.get('/categorize/categories'),
        ]);
        CategorizePage.state.items = merchantsResp.items;
        CategorizePage.state.total = merchantsResp.total;
        CategorizePage.state.limit = merchantsResp.limit;
        CategorizePage.state.offset = merchantsResp.offset;
        CategorizePage.state.categories = categories;
        CategorizePage.state.suggestions = {};

        return CategorizePage._renderHtml();
    },

    _renderHtml() {
        const s = CategorizePage.state;
        const intro = `
            <div class="page-header">
                <h2>Categorize Transactions</h2>
                <div class="btn-group">
                    <button class="btn btn-secondary" onclick="App.navigate('#/bank-rules')">View Rules</button>
                    <button class="btn btn-primary" id="cat-suggest-btn"
                            onclick="CategorizePage.runSuggest()">
                        Suggest categories with AI
                    </button>
                </div>
            </div>
            <p style="color:var(--text-muted); font-size:12px; margin-bottom:12px;">
                ${s.total.toLocaleString()} distinct merchant${s.total === 1 ? '' : 's'} across unmatched
                transactions; showing top ${s.items.length} by frequency. Accepting a suggestion
                creates a Bank Rule and immediately applies it to every matching transaction.
            </p>`;

        if (s.items.length === 0) {
            return intro + `<div class="empty-state">
                <p>Nothing to categorize — every transaction with a payee already has a category.</p>
            </div>`;
        }

        const optsByType = CategorizePage._categoryOptions();
        const rowsHtml = s.items.map(it => CategorizePage._renderRow(it, optsByType)).join('');

        return intro + `
            <div class="table-container">
                <table>
                    <thead><tr>
                        <th style="width:32%;">Merchant</th>
                        <th class="amount" style="width:8%;">Count</th>
                        <th class="amount" style="width:12%;">Spend</th>
                        <th style="width:12%;">Date range</th>
                        <th style="width:28%;">Category</th>
                        <th style="width:8%;"></th>
                    </tr></thead>
                    <tbody id="cat-tbody">${rowsHtml}</tbody>
                </table>
            </div>`;
    },

    _categoryOptions() {
        // Group by type for a slightly-readable optgroup list.
        const groups = { expense: [], income: [], cogs: [] };
        for (const c of CategorizePage.state.categories) {
            if (groups[c.type]) groups[c.type].push(c);
        }
        const opt = c => `<option value="${c.id}">${escapeHtml(c.name)}${c.account_number ? ' (' + escapeHtml(c.account_number) + ')' : ''}</option>`;
        return `
            <option value="">— pick a category —</option>
            ${groups.expense.length ? `<optgroup label="Expense">${groups.expense.map(opt).join('')}</optgroup>` : ''}
            ${groups.cogs.length ? `<optgroup label="COGS">${groups.cogs.map(opt).join('')}</optgroup>` : ''}
            ${groups.income.length ? `<optgroup label="Income">${groups.income.map(opt).join('')}</optgroup>` : ''}
        `;
    },

    _renderRow(item, optsHtml) {
        const sug = CategorizePage.state.suggestions[item.normalized];
        const selected = sug && sug.account_id ? sug.account_id : '';
        const confBadge = sug
            ? `<span class="badge badge-${CategorizePage._confClass(sug.confidence)}" title="${escapeHtml(sug.reason || '')}">${sug.confidence}</span>`
            : '';
        const datesText = (item.first_date === item.last_date)
            ? formatDate(item.first_date)
            : `${formatDate(item.first_date)} → ${formatDate(item.last_date)}`;
        // Default rule pattern: lowercased payee, but UI lets user tweak.
        const defaultPattern = CategorizePage._defaultPattern(item.payee);
        const rowId = `cat-row-${escapeHtml(item.normalized).replace(/[^a-z0-9]/gi, '_')}`;
        return `
            <tr id="${rowId}" data-normalized="${escapeHtml(item.normalized)}">
                <td>
                    <div style="font-family:var(--font-mono); font-size:11px;">${escapeHtml(item.payee)}</div>
                    <div style="margin-top:4px;">
                        <input type="text" class="cat-pattern" value="${escapeHtml(defaultPattern)}"
                               placeholder="match pattern (lowercased substring)"
                               style="width:100%; font-family:var(--font-mono); font-size:10px; padding:2px 4px;">
                    </div>
                </td>
                <td class="amount">${item.tx_count.toLocaleString()}</td>
                <td class="amount">${formatCurrency(Math.abs(item.spend_total))}</td>
                <td style="font-size:11px;">${datesText}</td>
                <td>
                    <select class="cat-select" style="width:100%;">${optsHtml}</select>
                    <div style="margin-top:4px;">${confBadge}${sug && sug.reason ? `<span style="font-size:10px; color:var(--text-muted); margin-left:6px;">${escapeHtml(sug.reason)}</span>` : ''}</div>
                </td>
                <td>
                    <button class="btn btn-primary btn-sm"
                            onclick="CategorizePage.acceptRow('${escapeHtml(item.normalized).replace(/'/g, "\\'")}')">
                        Accept
                    </button>
                </td>
            </tr>`.replace('value="' + selected + '"', selected ? `value="${selected}" selected` : '');
    },

    _defaultPattern(payee) {
        if (!payee) return '';
        // Strip common Amex/Apple-Pay prefixes; take first 1-2 alpha-rich
        // tokens; lowercase. Good enough as a starting suggestion the
        // user can tweak in the input.
        let s = payee.toLowerCase().trim();
        s = s.replace(/^(aplpay|nt_\w+|sq \*|sq\*|tst-|tst \*)\s*/i, '');
        const tokens = s.split(/\s+/).filter(t => /[a-z]/.test(t));
        if (tokens.length === 0) return s.slice(0, 30);
        // First two tokens, capped at 30 chars.
        return tokens.slice(0, 2).join(' ').slice(0, 30);
    },

    _confClass(confidence) {
        switch (confidence) {
            case 'high':   return 'paid';
            case 'medium': return 'sent';
            case 'low':    return 'overdue';
            default:       return 'draft';
        }
    },

    async runSuggest() {
        const btn = $('#cat-suggest-btn');
        const items = CategorizePage.state.items;
        if (!items.length) return;
        // Only re-suggest items that don't already have a suggestion.
        const todo = items
            .filter(it => !CategorizePage.state.suggestions[it.normalized])
            .slice(0, 50);
        if (!todo.length) {
            toast('All visible merchants already have a suggestion.');
            return;
        }
        const merchants = todo.map((it, i) => ({ idx: i, payee: it.payee }));
        btn.disabled = true;
        btn.textContent = `Asking Claude (${todo.length})…`;
        try {
            const resp = await API.post('/categorize/suggest', { merchants });
            if (!resp.ok) {
                toast(resp.error || 'Suggestion failed', 'error');
                return;
            }
            for (const s of (resp.suggestions || [])) {
                const it = todo[s.idx];
                if (!it) continue;
                CategorizePage.state.suggestions[it.normalized] = s;
            }
            const cents = resp.cost_cents || 0;
            toast(`${resp.suggestions.length} suggestions (${(cents / 100).toFixed(3)} USD).`);
            $('#page-content').innerHTML = CategorizePage._renderHtml();
        } catch (err) {
            toast(err.message, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Suggest categories with AI';
        }
    },

    async acceptRow(normalized) {
        const item = CategorizePage.state.items.find(i => i.normalized === normalized);
        if (!item) return;
        const rowEl = document.querySelector(`tr[data-normalized="${CSS.escape(normalized)}"]`);
        if (!rowEl) return;
        const select = rowEl.querySelector('.cat-select');
        const patternInput = rowEl.querySelector('.cat-pattern');
        const accountId = select.value ? parseInt(select.value, 10) : null;
        const pattern = (patternInput.value || '').trim();
        if (!accountId) {
            toast('Pick a category first', 'error');
            return;
        }
        if (!pattern) {
            toast('Pattern is empty', 'error');
            return;
        }
        const accountName = select.options[select.selectedIndex].text;
        try {
            const resp = await API.post('/categorize/accept', {
                name: `${pattern} → ${accountName}`.slice(0, 200),
                pattern,
                account_id: accountId,
                rule_type: 'contains',
                priority: 0,
            });
            toast(`Rule created — categorized ${resp.matched} txn${resp.matched === 1 ? '' : 's'}.`);
            // Remove this row from the table; refresh totals from server lazily.
            CategorizePage.state.items = CategorizePage.state.items.filter(i => i.normalized !== normalized);
            CategorizePage.state.total = Math.max(0, CategorizePage.state.total - 1);
            $('#page-content').innerHTML = CategorizePage._renderHtml();
        } catch (err) {
            toast(err.message, 'error');
        }
    },
};
