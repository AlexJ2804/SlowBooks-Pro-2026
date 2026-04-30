/**
 * Make Deposits — Move funds from Undeposited Funds to a bank account
 * Classic QB deposit slip workflow
 */
const DepositsPage = {
    async render() {
        const [pending, accounts, classes] = await Promise.all([
            API.get('/deposits/pending'),
            API.get('/accounts'),
            API.get('/classes'),
        ]);

        DepositsPage._classes = classes;
        const bankAccts = accounts.filter(a => a.account_type === 'asset');
        const bankOpts = bankAccts.map(a => `<option value="${a.id}">${escapeHtml(a.name)} (${formatCurrency(a.balance)})</option>`).join('');

        let html = `
            <div class="page-header">
                <h2>Make Deposits</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    Select payments to deposit from Undeposited Funds to a bank account
                </div>
            </div>
            <div class="toolbar">
                <span class="form-group" style="display:inline-flex; align-items:center; gap:4px; flex-wrap:wrap;">
                    <label style="font-size:10px;font-weight:700;">Class *:</label>
                    <select id="deposit-class">${classOptions(classes)}</select>
                    <a href="#" style="font-size:10px;" onclick="event.preventDefault(); DepositsPage.newClass()">+ New</a>
                </span>
                <label style="font-size:10px;font-weight:700;">Deposit To:</label>
                <select id="deposit-bank-acct">${bankOpts.length ? bankOpts : '<option>No bank accounts</option>'}</select>
                <label style="font-size:10px;font-weight:700;">Date:</label>
                <input type="date" id="deposit-date" value="${todayISO()}">
                <label style="font-size:10px;font-weight:700;">Reference:</label>
                <input type="text" id="deposit-ref" placeholder="Deposit slip #" style="width:120px;">
            </div>`;

        if (pending.length === 0) {
            html += '<div class="empty-state"><p>No payments waiting to be deposited</p></div>';
        } else {
            html += `<div class="table-container"><table>
                <thead><tr>
                    <th style="width:30px;"><input type="checkbox" id="dep-select-all" onchange="DepositsPage.toggleAll()"></th>
                    <th>Date</th><th>Description</th><th>Reference</th><th>Source</th>
                    <th class="amount">Amount</th>
                </tr></thead><tbody>`;
            for (const p of pending) {
                html += `<tr>
                    <td><input type="checkbox" class="dep-check" data-lineid="${p.transaction_line_id}" data-amount="${p.amount}" onchange="DepositsPage.recalc()"></td>
                    <td>${formatDate(p.date)}</td>
                    <td>${escapeHtml(p.description)}</td>
                    <td>${escapeHtml(p.reference || '')}</td>
                    <td>${escapeHtml(p.source_type || '')}</td>
                    <td class="amount">${formatCurrency(p.amount)}</td>
                </tr>`;
            }
            html += `</tbody></table></div>
                <div style="margin-top:12px; display:flex; justify-content:space-between; align-items:center;">
                    <div id="deposit-total" style="font-size:16px; font-weight:700; color:var(--qb-navy);">
                        Selected: $0.00 (0 items)
                    </div>
                    <button class="btn btn-primary" onclick="DepositsPage.makeDeposit()">Make Deposit</button>
                </div>`;
        }
        return html;
    },

    toggleAll() {
        const checked = $('#dep-select-all').checked;
        $$('.dep-check').forEach(cb => { cb.checked = checked; });
        DepositsPage.recalc();
    },

    recalc() {
        let total = 0, count = 0;
        $$('.dep-check').forEach(cb => {
            if (cb.checked) {
                total += parseFloat(cb.dataset.amount) || 0;
                count++;
            }
        });
        const el = $('#deposit-total');
        if (el) el.textContent = `Selected: ${formatCurrency(total)} (${count} items)`;
    },

    async makeDeposit() {
        const lineIds = [];
        let total = 0;
        $$('.dep-check').forEach(cb => {
            if (cb.checked) {
                lineIds.push(parseInt(cb.dataset.lineid));
                total += parseFloat(cb.dataset.amount) || 0;
            }
        });

        if (lineIds.length === 0) { toast('Select payments to deposit', 'error'); return; }

        const bankAcctId = $('#deposit-bank-acct')?.value;
        if (!bankAcctId) { toast('Select a bank account', 'error'); return; }
        const classSel = $('#deposit-class');
        const classId = classSel?.value;
        if (!classId) {
            markFieldError(classSel, 'Class is required — please select one');
            toast('Pick a class before saving.', 'error');
            return;
        }
        markFieldError(classSel, null);

        try {
            await API.post('/deposits', {
                deposit_to_account_id: parseInt(bankAcctId),
                date: $('#deposit-date').value,
                total: total,
                reference: $('#deposit-ref')?.value || null,
                class_id: parseInt(classId),
                line_ids: lineIds,
            });
            toast(`Deposited ${formatCurrency(total)}`);
            App.navigate('#/deposits');
        } catch (err) { toast(err.message, 'error'); }
    },

    newClass() {
        InlineCreate.open('class', async (created) => {
            const fresh = await API.get('/classes');
            DepositsPage._classes = fresh;
            const sel = $('#deposit-class');
            if (sel) sel.innerHTML = classOptions(fresh, created.id);
        });
    },
};
