/**
 * Categorize — LLM-assisted bulk categorization of unmatched bank txns.
 * Phase 3: spending analytics.
 *
 * Flow:
 *  1. Load top-N most-frequent uncategorized merchants
 *  2. User clicks "Suggest categories with AI" -> batch sent to /suggest
 *     -> per-row suggestion dropdown pre-fills with the LLM's pick
 *  3. User picks a Class (business) if applicable — blank = no business
 *     attribution (implicit personal/household)
 *  4. User accepts (or overrides) per row -> POST /accept creates a
 *     BankRule (with optional class_id) and applies it to every matching
 *     unmatched txn in one shot
 *  5. Accepted rows are removed from the table; remaining merchants stay
 *     visible so the user can keep going
 */
const CategorizePage = {
    state: {
        items: [],          // [{normalized, payee, tx_count, spend_total, ...}]
        categories: [],     // [{id, name, type, account_number, account_kind}]
        classes: [],        // [{id, name, is_system_default}]
        suggestions: {},    // {normalized -> {account_id, confidence, reason}}
        total: 0,
        limit: 100,
        offset: 0,
    },

    // Label map for account_kind -> optgroup heading. Personal /
    // Business / Transfer reads better than "expense / expense / expense"
    // which is what grouping by account_type would give us.
    KIND_LABELS: {
        personal_expense: 'Personal Expense',
        business_expense: 'Business Expense',
        personal_income:  'Personal Income',
        business_income:  'Business Income',
        transfer:         'Transfer / Non-Expense',
    },
    KIND_ORDER: [
        'personal_expense', 'business_expense',
        'personal_income',  'business_income',
        'transfer',
    ],

    async render() {
        const [merchantsResp, categories, classes] = await Promise.all([
            API.get('/categorize/unmatched-merchants?limit=100'),
            API.get('/categorize/categories'),
            API.get('/categorize/classes'),
        ]);
        CategorizePage.state.items = merchantsResp.items;
        CategorizePage.state.total = merchantsResp.total;
        CategorizePage.state.limit = merchantsResp.limit;
        CategorizePage.state.offset = merchantsResp.offset;
        CategorizePage.state.categories = categories;
        CategorizePage.state.classes = classes;
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
                Optional <strong>Class</strong> tags the row with a business — leave blank for
                personal / household.
            </p>`;

        if (s.items.length === 0) {
            return intro + `<div class="empty-state">
                <p>Nothing to categorize — every transaction with a payee already has a category.</p>
            </div>`;
        }

        const catOpts = CategorizePage._categoryOptions();
        const classOpts = CategorizePage._classOptions();
        const rowsHtml = s.items.map(it => CategorizePage._renderRow(it, catOpts, classOpts)).join('');

        return intro + `
            <div class="table-container">
                <table>
                    <thead><tr>
                        <th style="width:26%;">Merchant</th>
                        <th class="amount" style="width:6%;">Count</th>
                        <th class="amount" style="width:10%;">Spend</th>
                        <th style="width:11%;">Date range</th>
                        <th style="width:23%;">Category</th>
                        <th style="width:16%;">Class (business)</th>
                        <th style="width:8%;"></th>
                    </tr></thead>
                    <tbody id="cat-tbody">${rowsHtml}</tbody>
                </table>
            </div>`;
    },

    _categoryOptions() {
        // Group by account_kind. Fall back to "Other" for any category
        // that landed in the DB without a kind (legacy seeds before the
        // P&L kinds were added).
        const groups = {};
        for (const c of CategorizePage.state.categories) {
            const k = c.account_kind || 'other';
            (groups[k] = groups[k] || []).push(c);
        }
        const opt = c => `<option value="${c.id}">${escapeHtml(c.name)}${c.account_number ? ' (' + escapeHtml(c.account_number) + ')' : ''}</option>`;
        const orderedGroups = CategorizePage.KIND_ORDER
            .map(k => [k, groups[k] || []])
            .concat([['other', groups.other || []]])
            .filter(([_, list]) => list.length > 0);
        return `
            <option value="">— pick a category —</option>
            ${orderedGroups.map(([k, list]) => `
                <optgroup label="${CategorizePage.KIND_LABELS[k] || 'Other'}">
                    ${list.map(opt).join('')}
                </optgroup>
            `).join('')}
        `;
    },

    _classOptions() {
        // Class dropdown: blank-default for "no business attribution",
        // then archive-filtered classes alphabetically. The sentinel
        // value "__new__" triggers the inline-create flow.
        const opts = CategorizePage.state.classes
            .filter(c => !c.is_system_default)
            .map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`)
            .join('');
        return `
            <option value="">— no business —</option>
            ${opts}
            <option value="__new__">+ New class…</option>
        `;
    },

    _renderRow(item, catOpts, classOpts) {
        const sug = CategorizePage.state.suggestions[item.normalized];
        const selected = sug && sug.account_id ? sug.account_id : '';
        const confBadge = sug
            ? `<span class="badge badge-${CategorizePage._confClass(sug.confidence)}" title="${escapeHtml(sug.reason || '')}">${sug.confidence}</span>`
            : '';
        const datesText = (item.first_date === item.last_date)
            ? formatDate(item.first_date)
            : `${formatDate(item.first_date)} → ${formatDate(item.last_date)}`;
        const defaultPattern = CategorizePage._defaultPattern(item.payee);
        const rowId = `cat-row-${escapeHtml(item.normalized).replace(/[^a-z0-9]/gi, '_')}`;
        // The .replace at the end keeps the LLM-suggested category
        // pre-selected without rebuilding the whole optgroup HTML.
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
                    <select class="cat-select" style="width:100%;">${catOpts}</select>
                    <div style="margin-top:4px;">${confBadge}${sug && sug.reason ? `<span style="font-size:10px; color:var(--text-muted); margin-left:6px;">${escapeHtml(sug.reason)}</span>` : ''}</div>
                </td>
                <td>
                    <select class="cat-class-select" style="width:100%;"
                            onchange="CategorizePage.onClassChange(this)">${classOpts}</select>
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
        let s = payee.toLowerCase().trim();
        s = s.replace(/^(aplpay|nt_\w+|sq \*|sq\*|tst-|tst \*)\s*/i, '');
        const tokens = s.split(/\s+/).filter(t => /[a-z]/.test(t));
        if (tokens.length === 0) return s.slice(0, 30);
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

    async onClassChange(selectEl) {
        // The "+ New class…" sentinel triggers inline creation.
        if (selectEl.value !== '__new__') return;
        const name = (prompt('New class name (e.g. "Alex Music (1099)")') || '').trim();
        if (!name) {
            selectEl.value = '';
            return;
        }
        try {
            const created = await API.post('/categorize/classes', { name });
            // Push into local state and rebuild all class dropdowns. We
            // want EVERY row's dropdown to know about the new class, not
            // just the one that triggered it.
            const exists = CategorizePage.state.classes.find(c => c.id === created.id);
            if (!exists) {
                CategorizePage.state.classes.push({
                    id: created.id,
                    name: created.name,
                    is_system_default: created.is_system_default,
                });
            }
            // Refresh all dropdowns; preserve the current row selections.
            const selections = {};
            document.querySelectorAll('tr[data-normalized]').forEach(row => {
                const n = row.dataset.normalized;
                const cat = row.querySelector('.cat-select').value;
                const cls = row.querySelector('.cat-class-select').value;
                selections[n] = { cat, cls };
            });
            $('#page-content').innerHTML = CategorizePage._renderHtml();
            // Re-apply selections + set the triggering row to the new class.
            document.querySelectorAll('tr[data-normalized]').forEach(row => {
                const n = row.dataset.normalized;
                const sel = selections[n];
                if (sel) {
                    row.querySelector('.cat-select').value = sel.cat;
                    row.querySelector('.cat-class-select').value = sel.cls;
                }
            });
            // Set the triggering row to the new class.
            const triggerRow = selectEl.closest('tr');
            if (triggerRow) {
                triggerRow.querySelector('.cat-class-select').value = String(created.id);
            }
            toast(created.created ? `Class "${created.name}" created.` : `Class "${created.name}" already existed; selected.`);
        } catch (err) {
            toast(err.message, 'error');
            selectEl.value = '';
        }
    },

    async runSuggest() {
        const btn = $('#cat-suggest-btn');
        const items = CategorizePage.state.items;
        if (!items.length) return;
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
        const catSelect = rowEl.querySelector('.cat-select');
        const classSelect = rowEl.querySelector('.cat-class-select');
        const patternInput = rowEl.querySelector('.cat-pattern');
        const accountId = catSelect.value ? parseInt(catSelect.value, 10) : null;
        const classRaw = classSelect.value;
        const classId = (classRaw && classRaw !== '__new__') ? parseInt(classRaw, 10) : null;
        const pattern = (patternInput.value || '').trim();
        if (!accountId) {
            toast('Pick a category first', 'error');
            return;
        }
        if (!pattern) {
            toast('Pattern is empty', 'error');
            return;
        }
        const accountName = catSelect.options[catSelect.selectedIndex].text;
        const className = (classId && classSelect.selectedIndex >= 0)
            ? classSelect.options[classSelect.selectedIndex].text
            : '';
        // Rule name encodes both category and class so the Bank Rules
        // page is browsable without joining tables.
        const ruleName = className
            ? `${pattern} → ${accountName} [${className}]`
            : `${pattern} → ${accountName}`;
        try {
            const resp = await API.post('/categorize/accept', {
                name: ruleName.slice(0, 200),
                pattern,
                account_id: accountId,
                class_id: classId,
                rule_type: 'contains',
                priority: 0,
            });
            const classTail = resp.rule.class_name ? ` (${resp.rule.class_name})` : '';
            toast(`Rule created${classTail} — categorized ${resp.matched} txn${resp.matched === 1 ? '' : 's'}.`);
            CategorizePage.state.items = CategorizePage.state.items.filter(i => i.normalized !== normalized);
            CategorizePage.state.total = Math.max(0, CategorizePage.state.total - 1);
            $('#page-content').innerHTML = CategorizePage._renderHtml();
        } catch (err) {
            toast(err.message, 'error');
        }
    },
};
