/**
 * Bills & Bill Payments — Accounts Payable workflow
 * Feature 1: Enter bills, pay bills
 */
const BillsPage = {
    async render() {
        const [bills, settings] = await Promise.all([
            API.get('/bills'),
            API.get('/settings'),
        ]);
        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();

        const receiptParserOn = settings.receipt_parser_enabled === 'true';
        const uploadBtn = receiptParserOn
            ? `<button class="btn btn-secondary" onclick="BillsPage.showUploadReceipt()">Upload Receipt</button>`
            : '';
        let html = `
            <div class="page-header">
                <h2>Bills (Accounts Payable)</h2>
                <div class="btn-group">
                    <button class="btn btn-primary" onclick="BillsPage.showForm()">+ Enter Bill</button>
                    ${uploadBtn}
                    <button class="btn btn-secondary" onclick="BillsPage.showPayForm()">Pay Bills</button>
                </div>
            </div>
            <div class="toolbar">
                <select id="bill-status-filter" onchange="BillsPage.applyFilter()">
                    <option value="">All Statuses</option>
                    <option value="unpaid">Unpaid</option>
                    <option value="partial">Partial</option>
                    <option value="paid">Paid</option>
                    <option value="void">Void</option>
                </select>
            </div>`;

        if (bills.length === 0) {
            html += '<div class="empty-state"><p>No bills entered yet</p></div>';
        } else {
            html += `<div class="table-container"><table>
                <thead><tr><th>Bill #</th><th>Vendor</th><th>Date</th><th>Due</th><th>Status</th>
                <th class="amount">Total</th>
                <th class="amount">Total (${escapeHtml(homeCurrency)})</th>
                <th class="amount">Balance</th><th>Actions</th></tr></thead><tbody id="bill-tbody">`;
            for (const b of bills) {
                const ccy = (b.currency || 'USD').toUpperCase();
                html += `<tr class="bill-row" data-status="${b.status}">
                    <td><strong>${escapeHtml(b.bill_number)}</strong></td>
                    <td>${escapeHtml(b.vendor_name || '')}</td>
                    <td>${formatDate(b.date)}</td>
                    <td>${formatDate(b.due_date)}</td>
                    <td>${statusBadge(b.status)}</td>
                    <td class="amount">${formatCurrency(b.total, ccy)}</td>
                    <td class="amount">${formatCurrency(b.home_currency_amount, homeCurrency)}</td>
                    <td class="amount">${formatCurrency(b.balance_due, ccy)}</td>
                    <td class="actions">
                        <button class="btn btn-sm btn-secondary" onclick="BillsPage.view(${b.id})">View</button>
                        ${b.status !== 'void' && b.status !== 'paid' ? `<button class="btn btn-sm btn-danger" onclick="BillsPage.void(${b.id})">Void</button>` : ''}
                    </td>
                </tr>`;
            }
            html += '</tbody></table></div>';
        }
        return html;
    },

    applyFilter() {
        const status = $('#bill-status-filter')?.value;
        $$('.bill-row').forEach(row => {
            row.style.display = (!status || row.dataset.status === status) ? '' : 'none';
        });
    },

    async view(id) {
        const [bill, settings] = await Promise.all([
            API.get(`/bills/${id}`),
            API.get('/settings'),
        ]);
        const ccy = (bill.currency || 'USD').toUpperCase();
        const homeCcy = (settings.home_currency || 'USD').toUpperCase();
        const showHome = ccy !== homeCcy;
        const totalLine = showHome
            ? `${formatCurrency(bill.total, ccy)} <span style="color:var(--gray-500); font-weight:normal;">(≈ ${formatCurrency(bill.home_currency_amount, homeCcy)})</span>`
            : formatCurrency(bill.total, ccy);

        let linesHtml = bill.lines.map(l =>
            `<tr><td>${escapeHtml(l.description || '')}</td><td class="amount">${l.quantity}</td>
             <td class="amount">${formatCurrency(l.rate, ccy)}</td><td class="amount">${formatCurrency(l.amount, ccy)}</td></tr>`
        ).join('');

        openModal(`Bill ${bill.bill_number}`, `
            <div style="margin-bottom:12px;">
                <strong>Vendor:</strong> ${escapeHtml(bill.vendor_name || '')}<br>
                <strong>Date:</strong> ${formatDate(bill.date)}<br>
                <strong>Due:</strong> ${formatDate(bill.due_date)}<br>
                <strong>Status:</strong> ${statusBadge(bill.status)}<br>
                <strong>Currency:</strong> ${escapeHtml(ccy)}${showHome ? ` <span style="color:var(--gray-500);">(rate ${parseFloat(bill.exchange_rate).toFixed(4)} → ${escapeHtml(homeCcy)})</span>` : ''}
            </div>
            <div class="table-container"><table>
                <thead><tr><th>Description</th><th class="amount">Qty</th><th class="amount">Rate</th><th class="amount">Amount</th></tr></thead>
                <tbody>${linesHtml}</tbody>
            </table></div>
            <div class="invoice-totals">
                <div class="total-row grand-total"><span class="label">Total</span><span class="value">${totalLine}</span></div>
                <div class="total-row"><span class="label">Paid</span><span class="value">${formatCurrency(bill.amount_paid, ccy)}</span></div>
                <div class="total-row grand-total"><span class="label">Balance</span><span class="value">${formatCurrency(bill.balance_due, ccy)}</span></div>
            </div>
            <div style="margin-top:16px; border-top:1px solid var(--gray-200); padding-top:12px;">
                <h3 style="font-size:13px; margin-bottom:8px;">Attachments</h3>
                <div id="bill-attachments-list" style="margin-bottom:8px; font-size:11px;">Loading...</div>
                <input type="file" id="bill-attach-file" style="font-size:11px;">
                <button class="btn btn-sm btn-secondary" onclick="BillsPage.uploadAttachment(${bill.id})" style="margin-left:4px;">Upload</button>
            </div>
            <div class="form-actions">
                ${bill.status === 'paid' ? `<button class="btn btn-secondary" onclick="window.open('/api/bills/${bill.id}/pdf','_blank')">Save PDF</button>` : ''}
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>`);
        BillsPage.loadAttachments(bill.id);
    },

    _items: [],
    _vendors: [],
    lineCount: 0,

    vendorSelected(vendorId) {
        if (!vendorId) return;
        const vendor = BillsPage._vendors.find(v => v.id == vendorId);
        if (vendor && vendor.default_expense_account_id) {
            // Store for use when adding lines
            BillsPage._defaultExpenseAccountId = vendor.default_expense_account_id;
        } else {
            BillsPage._defaultExpenseAccountId = null;
        }
    },

    // Optional `prefill` (used by the receipt-upload flow) shape:
    //   { vendor_id|null, vendor_name_for_inline_create|null,
    //     date|null, currency|null, lines: [{description, quantity, rate}],
    //     suggested_account_id|null, attachment_token|null }
    async showForm(prefill = null) {
        const [vendors, items, accounts, settings, classes] = await Promise.all([
            API.get('/vendors?active_only=true'),
            API.get('/items?active_only=true'),
            API.get('/accounts?account_type=expense'),
            API.get('/settings'),
            API.get('/classes'),
        ]);
        BillsPage._items = items;
        BillsPage._classes = classes;
        BillsPage._accounts = accounts;
        BillsPage.lineCount = 1;

        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();
        BillsPage._homeCurrency = homeCurrency;
        BillsPage._formCurrency = (prefill && prefill.currency) || homeCurrency;

        // Stash the receipt token (if any) so save() can call /attach
        // after the bill is committed. Cleared by save() on success or
        // on the next form open.
        BillsPage._receiptAttachmentToken = (prefill && prefill.attachment_token) || null;
        BillsPage._receiptFilename = (prefill && prefill.receipt_filename) || null;

        BillsPage._vendors = vendors;
        const selectedVendorId = (prefill && prefill.vendor_id) || '';
        const vendorOpts = vendors.map(v =>
            `<option value="${v.id}"${v.id == selectedVendorId ? ' selected' : ''}>${escapeHtml(v.name)}</option>`
        ).join('');
        const itemOpts = items.map(i => `<option value="${i.id}">${escapeHtml(i.name)}</option>`).join('');

        // Banner — only when this form was opened from a receipt upload.
        const reviewBanner = prefill ? `
            <div style="margin-bottom:10px; padding:8px 10px; background:#fff7e6; border-left:3px solid #f5a623; font-size:12px;">
                <strong>Review extracted data before saving.</strong> AI may make mistakes.
                ${BillsPage._receiptFilename ? `Receipt: <em>${escapeHtml(BillsPage._receiptFilename)}</em>.` : ''}
            </div>
        ` : '';

        // Lines: either parsed from receipt (multi-row) or a single empty default row.
        const parsedLines = (prefill && Array.isArray(prefill.lines) && prefill.lines.length)
            ? prefill.lines
            : [{ description: '', quantity: 1, rate: 0 }];
        BillsPage.lineCount = parsedLines.length;
        const linesHtml = parsedLines.map((l, idx) => `
            <tr data-billline="${idx}">
                <td><select class="line-item"><option value="">--</option>${itemOpts}</select></td>
                <td><input class="line-desc" value="${escapeHtml(l.description || '')}"></td>
                <td><input class="line-qty" type="number" step="0.01" value="${l.quantity || 1}"></td>
                <td><input class="line-rate" type="number" step="0.01" value="${l.rate || 0}"></td>
                <td class="col-amount">$0.00</td>
            </tr>
        `).join('');

        // Pre-select an expense account on the vendor's default if we
        // matched a keyword via prefill.suggested_account_id. The bill's
        // existing form doesn't expose a per-bill default account picker,
        // so we stash this on BillsPage._defaultExpenseAccountId where
        // future line additions can pick it up.
        if (prefill && prefill.suggested_account_id) {
            BillsPage._defaultExpenseAccountId = prefill.suggested_account_id;
        }

        const dateValue = (prefill && prefill.date) || todayISO();

        openModal('Enter Bill', `
            ${reviewBanner}
            <form onsubmit="BillsPage.save(event)">
                <div class="form-grid">
                    <div class="form-group"><label>Class *</label>
                        <select name="class_id" id="bill-class-select" aria-required="true">${classOptions(classes)}</select>
                        <a href="#" style="font-size:11px;" onclick="event.preventDefault(); BillsPage.newClass('bill-class-select')">+ New class</a></div>
                    <div class="form-group"><label>Vendor *</label>
                        <select name="vendor_id" id="bill-vendor-select" required onchange="BillsPage.vendorSelected(this.value)"><option value="">Select...</option>${vendorOpts}</select>
                        <a href="#" style="font-size:11px;" onclick="event.preventDefault(); BillsPage.newVendor()">+ New vendor</a>
                        ${(prefill && prefill.vendor_name_for_inline_create) ? `
                          <div style="font-size:10px; color:var(--text-muted); margin-top:2px;">
                            Receipt vendor "<strong>${escapeHtml(prefill.vendor_name_for_inline_create)}</strong>" didn't match an existing vendor.
                            <a href="#" onclick="event.preventDefault(); BillsPage.newVendorPrefilled('${escapeHtml(prefill.vendor_name_for_inline_create).replace(/'/g, "\\'")}')">Create it →</a>
                          </div>` : ''}
                    </div>
                    <div class="form-group"><label>Bill Number *</label>
                        <input name="bill_number" required value="${escapeHtml((prefill && prefill.bill_number) || '')}"></div>
                    <div class="form-group"><label>Date *</label>
                        <input name="date" type="date" required value="${dateValue}"></div>
                    <div class="form-group"><label>Terms</label>
                        <select name="terms">
                            ${['Net 15','Net 30','Net 45','Net 60','Due on Receipt'].map(t =>
                                `<option ${t==='Net 30'?'selected':''}>${t}</option>`).join('')}
                        </select></div>
                    <div class="form-group"><label>Currency</label>
                        <select name="currency" id="bill-currency" onchange="BillsPage.currencyChanged()">
                            ${currencyOptions(BillsPage._formCurrency)}
                        </select></div>
                    <div class="form-group"><label>Exchange Rate <span style="color:var(--gray-500); font-weight:normal;">(→ ${escapeHtml(homeCurrency)})</span></label>
                        <input name="exchange_rate" id="bill-exchange-rate" type="number" step="0.00000001" value="1" ${BillsPage._formCurrency === homeCurrency ? 'disabled' : ''}></div>
                </div>
                <h3 style="margin:12px 0 8px;font-size:14px;">Line Items</h3>
                <table class="line-items-table">
                    <thead><tr><th>Item</th><th>Description</th><th class="col-qty">Qty</th><th class="col-rate">Rate</th><th class="col-amount">Amount</th></tr></thead>
                    <tbody id="bill-lines">
                        ${linesHtml}
                    </tbody>
                </table>
                <button type="button" class="btn btn-sm btn-secondary" style="margin-top:8px;" onclick="BillsPage.addLine()">+ Add Line</button>
                <a href="#" style="font-size:11px; margin-left:12px;" onclick="event.preventDefault(); BillsPage.newItem()">+ New item</a>
                <div class="form-group" style="margin-top:12px;"><label>Notes</label>
                    <textarea name="notes"></textarea></div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save Bill</button>
                </div>
            </form>`);

        // If receipt prefilled a non-home currency, run the FX lookup so
        // the rate field gets a sensible default.
        if (BillsPage._formCurrency && BillsPage._formCurrency !== homeCurrency) {
            BillsPage.currencyChanged();
        }
    },

    newVendorPrefilled(name) {
        InlineCreate.open('vendor', async (created) => {
            const fresh = await API.get('/vendors?active_only=true');
            BillsPage._vendors = fresh;
            const sel = $('#bill-vendor-select');
            if (sel) {
                const opts = fresh.map(v =>
                    `<option value="${v.id}"${v.id == created.id ? ' selected' : ''}>${escapeHtml(v.name)}</option>`
                ).join('');
                sel.innerHTML = `<option value="">Select...</option>${opts}`;
                sel.value = String(created.id);
            }
        }, { name });
    },

    // ----- Receipt upload flow ------------------------------------------
    showUploadReceipt() {
        openModal('Upload Receipt', `
            <div style="font-size:12px; color:var(--gray-600); margin-bottom:12px;">
                Upload a JPEG, PNG, WebP, or PDF receipt. We'll extract the vendor, date, total, and line items
                using the Anthropic API; you'll review the extracted data on the bill confirm form before saving.
                The original file is attached to the bill if you save.
            </div>
            <form id="receipt-upload-form" onsubmit="BillsPage.parseReceipt(event)">
                <div class="form-group full-width">
                    <input type="file" name="file" id="receipt-file-input" accept="image/jpeg,image/png,image/webp,application/pdf" required>
                </div>
                <div id="receipt-parse-status" style="font-size:12px; color:var(--gray-600); margin:8px 0;"></div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary" id="receipt-parse-submit">Parse</button>
                </div>
            </form>
        `);
    },

    async parseReceipt(e) {
        e.preventDefault();
        const fileInput = $('#receipt-file-input');
        const file = fileInput && fileInput.files && fileInput.files[0];
        if (!file) { toast('Pick a file first', 'error'); return; }

        const submitBtn = $('#receipt-parse-submit');
        const status = $('#receipt-parse-status');
        if (submitBtn) submitBtn.disabled = true;
        // The backend may retry once with Sonnet when the primary model
        // can't extract a total — that pushes worst-case end-to-end to
        // ~60s on dense receipts. Copy reflects worst case.
        if (status) status.textContent = 'Reading your receipt… (up to a minute)';

        const fd = new FormData();
        fd.append('file', file);

        let payload;
        try {
            const resp = await fetch('/api/receipts/parse', { method: 'POST', body: fd });
            payload = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                throw new Error(payload.detail || `HTTP ${resp.status}`);
            }
        } catch (err) {
            if (status) {
                status.innerHTML = `Could not parse: ${escapeHtml(err.message || 'unknown error')}.
                    <a href="#" onclick="event.preventDefault(); closeModal(); BillsPage.showForm();">Enter the bill manually instead.</a>`;
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }

        // Soft-failure path: HTTP 200 but parse couldn't extract anything.
        // Still pass the attachment_token through so the user can attach the
        // original even if they have to fill the bill manually.
        if (!payload.parsed) {
            if (status) {
                status.innerHTML = `Couldn't extract receipt data: ${escapeHtml(payload.error || 'unknown')}.
                    Open the bill form anyway with this file attached?
                    <button class="btn btn-sm btn-secondary" type="button" onclick="BillsPage._fallbackToManual('${escapeHtml(payload.attachment_token || '').replace(/'/g, "\\'")}', '${escapeHtml(payload.filename || 'receipt').replace(/'/g, "\\'")}')">Continue manually</button>`;
            }
            if (submitBtn) submitBtn.disabled = false;
            return;
        }

        const prefill = await BillsPage._buildPrefillFromParse(payload);
        closeModal();
        BillsPage.showForm(prefill);
    },

    _fallbackToManual(token, filename) {
        closeModal();
        BillsPage.showForm({
            attachment_token: token || null,
            receipt_filename: filename || null,
            lines: [{ description: '', quantity: 1, rate: 0 }],
        });
    },

    async _buildPrefillFromParse(payload) {
        const parsed = payload.parsed || {};
        // Vendor: case-insensitive substring match against existing vendors.
        // First hit wins. If nothing matches, leave vendor_id null and
        // surface vendor_name_for_inline_create so the form can offer a
        // pre-filled "+ New vendor" link.
        const vendors = await API.get('/vendors?active_only=true');
        let vendor_id = null;
        let vendor_name_for_inline_create = null;
        if (parsed.vendor_name) {
            const needle = parsed.vendor_name.toLowerCase();
            const match = vendors.find(v =>
                (v.name || '').toLowerCase().includes(needle) ||
                needle.includes((v.name || '').toLowerCase())
            );
            if (match) {
                vendor_id = match.id;
            } else {
                vendor_name_for_inline_create = parsed.vendor_name;
            }
        }

        // Expense account: case-insensitive substring match between any
        // suggested keyword and any expense-account name. First hit wins.
        let suggested_account_id = null;
        const keywords = parsed.suggested_expense_account_keywords || [];
        if (keywords.length) {
            const accounts = await API.get('/accounts?account_type=expense');
            outer: for (const kw of keywords) {
                const k = (kw || '').toLowerCase();
                if (!k) continue;
                for (const a of accounts) {
                    if ((a.name || '').toLowerCase().includes(k)) {
                        suggested_account_id = a.id;
                        break outer;
                    }
                }
            }
        }

        // Lines: prefer parsed line items; if there are none but a total
        // exists, synthesize a single line row from the total.
        let lines = parsed.line_items || [];
        if (lines.length === 0 && parsed.total) {
            lines = [{
                description: parsed.vendor_name || 'Receipt',
                quantity: 1,
                rate: parsed.total,
            }];
        }

        return {
            vendor_id,
            vendor_name_for_inline_create,
            date: parsed.date || null,
            currency: parsed.currency || null,
            // Parser returns `order_number`; the SlowBooks form input
            // is named `bill_number`. The naming difference is
            // deliberate — "order number" generalises across vendor
            // types (utilities call it Account Number, airlines call
            // it Confirmation Number). We map at this boundary.
            bill_number: parsed.order_number || null,
            lines,
            suggested_account_id,
            attachment_token: payload.attachment_token,
            receipt_filename: payload.filename,
        };
    },

    addLine() {
        const idx = BillsPage.lineCount++;
        const itemOpts = BillsPage._items.map(i => `<option value="${i.id}">${escapeHtml(i.name)}</option>`).join('');
        $('#bill-lines').insertAdjacentHTML('beforeend', `
            <tr data-billline="${idx}">
                <td><select class="line-item"><option value="">--</option>${itemOpts}</select></td>
                <td><input class="line-desc"></td>
                <td><input class="line-qty" type="number" step="0.01" value="1"></td>
                <td><input class="line-rate" type="number" step="0.01" value="0"></td>
                <td class="col-amount">$0.00</td>
            </tr>`);
    },

    async currencyChanged() {
        const ccy = $('#bill-currency').value;
        const rateField = $('#bill-exchange-rate');
        BillsPage._formCurrency = ccy;
        if (ccy === BillsPage._homeCurrency) {
            rateField.value = '1';
            rateField.disabled = true;
            return;
        }
        rateField.disabled = false;
        try {
            const res = await API.get(`/fx/rate?from=${encodeURIComponent(ccy)}&to=${encodeURIComponent(BillsPage._homeCurrency)}`);
            if (res.rate) {
                rateField.value = parseFloat(res.rate);
                if (res.source === 'bankofcanada-cross') {
                    toast(`FX rate ${ccy}→${BillsPage._homeCurrency}: ${parseFloat(res.rate).toFixed(4)} (cross-rate via CAD)`);
                }
            } else {
                rateField.value = '1';
                toast(`FX rate ${ccy}→${BillsPage._homeCurrency} unavailable; using 1.0`, 'error');
            }
        } catch (err) {
            rateField.value = '1';
            toast('FX lookup failed; using 1.0', 'error');
        }
    },

    newClass(targetSelectId) {
        InlineCreate.open('class', async (created) => {
            const fresh = await API.get('/classes');
            BillsPage._classes = fresh;
            const sel = $(`#${targetSelectId}`);
            if (sel) sel.innerHTML = classOptions(fresh, created.id);
        });
    },

    newVendor() {
        InlineCreate.open('vendor', async (created) => {
            const fresh = await API.get('/vendors?active_only=true');
            BillsPage._vendors = fresh;
            const sel = $('#bill-vendor-select');
            if (sel) {
                const opts = fresh.map(v =>
                    `<option value="${v.id}"${v.id == created.id ? ' selected' : ''}>${escapeHtml(v.name)}</option>`
                ).join('');
                sel.innerHTML = `<option value="">Select...</option>${opts}`;
                sel.value = String(created.id);
            }
        });
    },

    newItem() {
        InlineCreate.open('item', async (created) => {
            const fresh = await API.get('/items?active_only=true');
            BillsPage._items = fresh;
            $$('#bill-lines tr').forEach(row => {
                const sel = row.querySelector('.line-item');
                if (!sel) return;
                const current = sel.value;
                const opts = fresh.map(i =>
                    `<option value="${i.id}"${i.id == current ? ' selected' : ''}>${escapeHtml(i.name)}</option>`
                ).join('');
                sel.innerHTML = `<option value="">--</option>${opts}`;
            });
        });
    },

    async save(e) {
        e.preventDefault();
        const form = e.target;
        if (!requireClassPicked(form)) return;
        const lines = [];
        $$('#bill-lines tr').forEach((row, i) => {
            lines.push({
                item_id: row.querySelector('.line-item')?.value ? parseInt(row.querySelector('.line-item').value) : null,
                description: row.querySelector('.line-desc')?.value || '',
                quantity: parseFloat(row.querySelector('.line-qty')?.value) || 1,
                rate: parseFloat(row.querySelector('.line-rate')?.value) || 0,
                line_order: i,
            });
        });
        try {
            const created = await API.post('/bills', {
                vendor_id: parseInt(form.vendor_id.value),
                bill_number: form.bill_number.value,
                date: form.date.value,
                terms: form.terms.value,
                notes: form.notes.value || null,
                currency: (form.currency.value || 'USD').toUpperCase(),
                exchange_rate: parseFloat(form.exchange_rate.value) || 1,
                class_id: parseInt(form.class_id.value),
                lines,
            });
            // If this bill was opened from a receipt upload, persist the
            // original receipt as an Attachment now that the bill is saved.
            // Failure here is non-fatal — the bill is already created.
            if (BillsPage._receiptAttachmentToken && created && created.id) {
                try {
                    const fd = new FormData();
                    fd.append('bill_id', String(created.id));
                    fd.append('attachment_token', BillsPage._receiptAttachmentToken);
                    await fetch('/api/receipts/attach', { method: 'POST', body: fd });
                } catch (_) {
                    // Surface to user but don't block the save flow.
                    toast('Bill saved, but attaching the original receipt failed', 'error');
                }
                BillsPage._receiptAttachmentToken = null;
                BillsPage._receiptFilename = null;
            }
            toast('Bill saved');
            closeModal();
            App.navigate('#/bills');
        } catch (err) { toast(err.message, 'error'); }
    },

    async void(id) {
        if (!confirm('Void this bill?')) return;
        try {
            await API.post(`/bills/${id}/void`);
            toast('Bill voided');
            App.navigate('#/bills');
        } catch (err) { toast(err.message, 'error'); }
    },

    async showPayForm() {
        const [vendors, bills, accounts, settings, classes] = await Promise.all([
            API.get('/vendors?active_only=true'),
            API.get('/bills?status=unpaid'),
            API.get('/accounts?account_type=asset'),
            API.get('/settings'),
            API.get('/classes'),
        ]);
        const partials = await API.get('/bills?status=partial');
        const openBills = [...bills, ...partials];

        const homeCurrency = (settings.home_currency || 'USD').toUpperCase();
        BillsPage._homeCurrency = homeCurrency;
        BillsPage._payCurrency = homeCurrency;
        BillsPage._classes = classes;

        const vendorOpts = vendors.map(v => `<option value="${v.id}">${escapeHtml(v.name)}</option>`).join('');
        const acctOpts = accounts.map(a => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('');

        let billRows = openBills.map(b => {
            const ccy = (b.currency || 'USD').toUpperCase();
            return `
            <tr data-currency="${ccy}">
                <td><input type="checkbox" class="pay-check" data-bill="${b.id}" data-balance="${b.balance_due}"></td>
                <td>${escapeHtml(b.bill_number)}</td>
                <td>${escapeHtml(b.vendor_name || '')}</td>
                <td>${formatDate(b.due_date)}</td>
                <td><span style="font-size:10px; padding:1px 6px; background:var(--gray-100); border-radius:4px;">${escapeHtml(ccy)}</span></td>
                <td class="amount">${formatCurrency(b.balance_due, ccy)}</td>
                <td><input type="number" step="0.01" class="pay-amount" data-bill="${b.id}" value="0" style="width:80px;"></td>
            </tr>`;
        }).join('');

        if (!billRows) billRows = '<tr><td colspan="7" style="color:var(--text-muted);">No open bills</td></tr>';

        openModal('Pay Bills', `
            <form onsubmit="BillsPage.savePay(event)">
                <div style="font-size:11px; color:var(--text-muted); margin-bottom:8px; padding:6px 8px; background:var(--gray-50); border-left:2px solid var(--qb-blue);">
                    <strong>Note:</strong> Cross-currency reconciliation is not supported. If any
                    selected bill is in a different currency than the payment, the server will
                    reject the request with HTTP 400 and no payment will be saved.
                </div>
                <div class="form-grid">
                    <div class="form-group"><label>Class *</label>
                        <select name="class_id" id="billpay-class-select" aria-required="true">${classOptions(classes)}</select>
                        <a href="#" style="font-size:11px;" onclick="event.preventDefault(); BillsPage.newClass('billpay-class-select')">+ New class</a></div>
                    <div class="form-group"><label>Pay From Account</label>
                        <select name="pay_from_account_id"><option value="">Select...</option>${acctOpts}</select></div>
                    <div class="form-group"><label>Date *</label>
                        <input name="date" type="date" required value="${todayISO()}"></div>
                    <div class="form-group"><label>Method</label>
                        <select name="method">
                            <option value="check">Check</option><option value="ach">ACH</option>
                            <option value="cash">Cash</option><option value="credit_card">Credit Card</option>
                        </select></div>
                    <div class="form-group"><label>Check #</label>
                        <input name="check_number"></div>
                    <div class="form-group"><label>Currency</label>
                        <select name="currency" id="billpay-currency" onchange="BillsPage.payCurrencyChanged()">
                            ${currencyOptions(homeCurrency)}
                        </select></div>
                    <div class="form-group"><label>Exchange Rate <span style="color:var(--gray-500); font-weight:normal;">(→ ${escapeHtml(homeCurrency)})</span></label>
                        <input name="exchange_rate" id="billpay-exchange-rate" type="number" step="0.00000001" value="1" disabled></div>
                </div>
                <div class="table-container" style="margin-top:12px;"><table>
                    <thead><tr><th style="width:30px;"></th><th>Bill #</th><th>Vendor</th><th>Due</th>
                    <th>Ccy</th>
                    <th class="amount">Balance</th><th class="amount">Payment</th></tr></thead>
                    <tbody>${billRows}</tbody>
                </table></div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Pay Selected Bills</button>
                </div>
            </form>`);

        // Auto-fill payment amount on check
        $$('.pay-check').forEach(cb => {
            cb.addEventListener('change', () => {
                const billId = cb.dataset.bill;
                const amtInput = $(`.pay-amount[data-bill="${billId}"]`);
                amtInput.value = cb.checked ? cb.dataset.balance : '0';
            });
        });
    },

    async payCurrencyChanged() {
        const ccy = $('#billpay-currency').value;
        const rateField = $('#billpay-exchange-rate');
        BillsPage._payCurrency = ccy;
        if (ccy === BillsPage._homeCurrency) {
            rateField.value = '1';
            rateField.disabled = true;
            return;
        }
        rateField.disabled = false;
        try {
            const res = await API.get(`/fx/rate?from=${encodeURIComponent(ccy)}&to=${encodeURIComponent(BillsPage._homeCurrency)}`);
            if (res.rate) {
                rateField.value = parseFloat(res.rate);
                if (res.source === 'bankofcanada-cross') {
                    toast(`FX rate ${ccy}→${BillsPage._homeCurrency}: ${parseFloat(res.rate).toFixed(4)} (cross-rate via CAD)`);
                }
            } else {
                rateField.value = '1';
                toast(`FX rate ${ccy}→${BillsPage._homeCurrency} unavailable; using 1.0`, 'error');
            }
        } catch (err) {
            rateField.value = '1';
            toast('FX lookup failed; using 1.0', 'error');
        }
    },

    async savePay(e) {
        e.preventDefault();
        const form = e.target;
        if (!requireClassPicked(form)) return;
        const payCcy = (form.currency.value || 'USD').toUpperCase();
        const allocations = [];
        let total = 0;
        let mismatch = null;
        $$('.pay-amount').forEach(input => {
            const amt = parseFloat(input.value) || 0;
            if (amt > 0) {
                const row = input.closest('tr');
                const rowCcy = (row?.dataset.currency || 'USD').toUpperCase();
                if (rowCcy !== payCcy && !mismatch) mismatch = rowCcy;
                allocations.push({ bill_id: parseInt(input.dataset.bill), amount: amt });
                total += amt;
            }
        });
        if (allocations.length === 0) { toast('Select bills to pay', 'error'); return; }
        if (mismatch) {
            toast(`Selected bill is in ${mismatch}, but payment is in ${payCcy}. All selected bills must match the payment currency.`, 'error');
            return;
        }

        // Get vendor from first bill
        const firstBill = await API.get(`/bills/${allocations[0].bill_id}`);

        try {
            await API.post('/bill-payments', {
                vendor_id: firstBill.vendor_id,
                date: form.date.value,
                amount: total,
                method: form.method.value,
                check_number: form.check_number.value || null,
                pay_from_account_id: form.pay_from_account_id.value ? parseInt(form.pay_from_account_id.value) : null,
                currency: payCcy,
                exchange_rate: parseFloat(form.exchange_rate.value) || 1,
                class_id: parseInt(form.class_id.value),
                allocations,
            });
            toast('Bills paid');
            closeModal();
            App.navigate('#/bills');
        } catch (err) { toast(err.message, 'error'); }
    },

    async loadAttachments(billId) {
        const el = $('#bill-attachments-list');
        if (!el) return;
        try {
            const attachments = await API.get(`/attachments/bill/${billId}`);
            if (attachments.length === 0) {
                el.innerHTML = '<span style="color:var(--text-muted);">No attachments</span>';
            } else {
                el.innerHTML = attachments.map(a =>
                    `<div style="display:flex; align-items:center; gap:8px; padding:2px 0;">
                        <a href="/api/attachments/download/${a.id}" target="_blank">${escapeHtml(a.filename)}</a>
                        <span style="color:var(--gray-400);">(${(a.file_size/1024).toFixed(1)} KB)</span>
                        <button class="btn btn-sm btn-danger" onclick="BillsPage.deleteAttachment(${a.id},${billId})" style="padding:0 4px; font-size:10px;">X</button>
                    </div>`
                ).join('');
            }
        } catch (e) { el.innerHTML = ''; }
    },

    async uploadAttachment(billId) {
        const fileInput = $('#bill-attach-file');
        if (!fileInput?.files[0]) { toast('Select a file first', 'error'); return; }
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        try {
            const resp = await fetch(`/api/attachments/bill/${billId}`, { method: 'POST', body: formData });
            if (!resp.ok) { const d = await resp.json(); throw new Error(d.detail || 'Upload failed'); }
            toast('Attachment uploaded');
            fileInput.value = '';
            BillsPage.loadAttachments(billId);
        } catch (err) { toast(err.message, 'error'); }
    },

    async deleteAttachment(attachId, billId) {
        if (!confirm('Delete this attachment?')) return;
        try {
            await API.del(`/attachments/${attachId}`);
            toast('Attachment deleted');
            BillsPage.loadAttachments(billId);
        } catch (err) { toast(err.message, 'error'); }
    },
};
