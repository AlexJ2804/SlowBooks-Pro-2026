/**
 * Credit Card Charges — Enter CC expenses
 * DR Expense Account, CR Credit Card Payable (2100)
 */
const CCChargesPage = {
    async render() {
        const [charges, settings] = await Promise.all([
            API.get('/cc-charges'),
            API.get('/settings'),
        ]);
        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();
        let html = `
            <div class="page-header">
                <h2>Credit Card Charges</h2>
                <button class="btn btn-primary" onclick="CCChargesPage.showForm()">+ Enter Charge</button>
            </div>`;

        if (charges.length === 0) {
            html += '<div class="empty-state"><p>No credit card charges recorded yet</p></div>';
        } else {
            html += `<div class="table-container"><table>
                <thead><tr><th>Date</th><th>Payee</th><th>Account</th><th>Reference</th>
                <th class="amount">Amount</th>
                <th class="amount">Amount (${escapeHtml(homeCurrency)})</th>
                </tr></thead><tbody>`;
            for (const c of charges) {
                const ccy = (c.currency || 'USD').toUpperCase();
                html += `<tr>
                    <td>${formatDate(c.date)}</td>
                    <td>${escapeHtml(c.description || '')}</td>
                    <td>${escapeHtml(c.account_name || '')}</td>
                    <td>${escapeHtml(c.reference || '')}</td>
                    <td class="amount">${formatCurrency(c.amount, ccy)}</td>
                    <td class="amount">${formatCurrency(c.home_currency_amount, homeCurrency)}</td>
                </tr>`;
            }
            html += '</tbody></table></div>';
        }
        return html;
    },

    async showForm() {
        const [accounts, settings, classes] = await Promise.all([
            API.get('/accounts?account_type=expense'),
            API.get('/settings'),
            API.get('/classes'),
        ]);
        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();
        CCChargesPage._homeCurrency = homeCurrency;
        CCChargesPage._classes = classes;
        const acctOpts = accounts.map(a =>
            `<option value="${a.id}">${escapeHtml(a.account_number)} - ${escapeHtml(a.name)}</option>`
        ).join('');

        openModal('Enter Credit Card Charge', `
            <form onsubmit="CCChargesPage.save(event)">
                <div class="form-grid">
                    <div class="form-group"><label>Class *</label>
                        <select name="class_id" id="cc-class-select" required>${classOptions(classes)}</select>
                        <a href="#" style="font-size:11px;" onclick="event.preventDefault(); CCChargesPage.newClass()">+ New class</a></div>
                    <div class="form-group"><label>Date *</label>
                        <input name="date" type="date" required value="${todayISO()}"></div>
                    <div class="form-group"><label>Payee</label>
                        <input name="payee"></div>
                    <div class="form-group"><label>Expense Account *</label>
                        <select name="account_id" required><option value="">Select...</option>${acctOpts}</select></div>
                    <div class="form-group"><label>Amount *</label>
                        <input name="amount" type="number" step="0.01" required></div>
                    <div class="form-group"><label>Currency</label>
                        <select name="currency" id="cc-currency" onchange="CCChargesPage.currencyChanged()">
                            ${currencyOptions(homeCurrency)}
                        </select></div>
                    <div class="form-group"><label>Exchange Rate <span style="color:var(--gray-500); font-weight:normal;">(→ ${escapeHtml(homeCurrency)})</span></label>
                        <input name="exchange_rate" id="cc-exchange-rate" type="number" step="0.00000001" value="1" disabled></div>
                    <div class="form-group"><label>Reference</label>
                        <input name="reference"></div>
                    <div class="form-group full-width"><label>Memo</label>
                        <textarea name="memo"></textarea></div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save Charge</button>
                </div>
            </form>`);
    },

    newClass() {
        InlineCreate.open('class', async (created) => {
            const fresh = await API.get('/classes');
            CCChargesPage._classes = fresh;
            const sel = $('#cc-class-select');
            if (sel) sel.innerHTML = classOptions(fresh, created.id);
        });
    },

    async currencyChanged() {
        const ccy = $('#cc-currency').value;
        const rateField = $('#cc-exchange-rate');
        if (ccy === CCChargesPage._homeCurrency) {
            rateField.value = '1';
            rateField.disabled = true;
            return;
        }
        rateField.disabled = false;
        try {
            const res = await API.get(`/fx/rate?from=${encodeURIComponent(ccy)}&to=${encodeURIComponent(CCChargesPage._homeCurrency)}`);
            if (res.rate) {
                rateField.value = parseFloat(res.rate);
                if (res.source === 'bankofcanada-cross') {
                    toast(`FX rate ${ccy}→${CCChargesPage._homeCurrency}: ${parseFloat(res.rate).toFixed(4)} (cross-rate via CAD)`);
                }
            } else {
                rateField.value = '1';
                toast(`FX rate ${ccy}→${CCChargesPage._homeCurrency} unavailable; using 1.0`, 'error');
            }
        } catch (err) {
            rateField.value = '1';
            toast('FX lookup failed; using 1.0', 'error');
        }
    },

    async save(e) {
        e.preventDefault();
        const form = e.target;
        if (!form.class_id.value) { toast('Pick a class before saving.', 'error'); return; }
        try {
            await API.post('/cc-charges', {
                date: form.date.value,
                payee: form.payee.value || null,
                account_id: parseInt(form.account_id.value),
                amount: parseFloat(form.amount.value),
                reference: form.reference.value || null,
                memo: form.memo.value || null,
                currency: (form.currency.value || 'USD').toUpperCase(),
                exchange_rate: parseFloat(form.exchange_rate.value) || 1,
                class_id: parseInt(form.class_id.value),
            });
            toast('Credit card charge recorded');
            closeModal();
            App.navigate('#/cc-charges');
        } catch (err) { toast(err.message, 'error'); }
    },
};
