/**
 * Statement imports — Phase 2 PDF ingestion frontend (issue #1).
 *
 * Uploads a PDF bank/CC statement, runs it through the Anthropic vision
 * parser via /api/statement-imports/upload/{bank_account_id}, shows the
 * parsed transactions in a preview modal, and lets the user post them
 * into bank_transactions or discard.
 *
 * The list view groups every import (parsed, posted, failed) so re-
 * uploading or drilling back to the source PDF is one click. Status
 * badges use the same color scheme as the bills page (green=done,
 * amber=ready-for-action, slate=pending, red=failed).
 *
 * Cabin layout (cabin: true in app.js routes) — page provides its own
 * .sb-head + .sb-section gutter; router skips the legacy wrapper.
 */
const StatementImportsPage = {
    _imports: [],
    _bankAccounts: [],

    async render() {
        const [imports, bankAccounts] = await Promise.all([
            API.get('/statement-imports/?limit=200'),
            API.get('/banking/accounts'),
        ]);
        StatementImportsPage._imports = imports;
        StatementImportsPage._bankAccounts = bankAccounts;

        const totalCost = imports.reduce(
            (sum, i) => sum + (i.vision_cost_cents || 0), 0,
        );
        const postedCount = imports.filter(i => i.status === 'posted').length;

        const uploadDisabled = bankAccounts.length === 0;
        const uploadHint = uploadDisabled
            ? 'Add a bank account first'
            : 'Upload a PDF statement';

        return `
            <header class="sb-head">
                <div class="sb-crumb">Banking &middot; PDF Statements</div>
                <h1>Statement Imports</h1>
                <div class="sb-sub">
                    ${imports.length} import${imports.length === 1 ? '' : 's'}
                    &middot;
                    ${postedCount} posted
                    &middot;
                    ${StatementImportsPage._formatCents(totalCost)} parser cost
                </div>
            </header>
            <div class="sb-segs">
                <span class="sb-grow"></span>
                <button type="button" class="sb-pill primary"
                        title="${uploadHint}"
                        ${uploadDisabled ? 'disabled' : ''}
                        onclick="StatementImportsPage.openUploadModal()">+ Upload statement</button>
            </div>
            <div class="sb-section">
                ${StatementImportsPage._renderTable(imports, bankAccounts)}
            </div>
        `;
    },

    // ----------------------------------------------------------------
    // List table
    // ----------------------------------------------------------------
    _renderTable(imports, bankAccounts) {
        if (imports.length === 0) {
            return `
                <div class="empty-state">
                    <p>No statement imports yet.</p>
                    <p style="margin-top:8px; font-size:12px; color:var(--ink-3);">
                        Click <strong>+ Upload statement</strong> to parse a PDF
                        with the Anthropic vision API.
                    </p>
                </div>
            `;
        }
        const baMap = new Map(bankAccounts.map(a => [a.id, a]));
        const rows = imports.map(im => {
            const ba = baMap.get(im.bank_account_id);
            const baLabel = ba
                ? `${escapeHtml(ba.name)}${ba.last_four ? ` <span style="color:var(--ink-3); font-family:var(--font-mono-ds);">${escapeHtml(ba.last_four)}</span>` : ''}`
                : `<span style="color:var(--ink-3);">acct ${im.bank_account_id}</span>`;
            const period = (im.period_start && im.period_end)
                ? `${formatDate(im.period_start)} &ndash; ${formatDate(im.period_end)}`
                : '<span style="color:var(--ink-3);">&mdash;</span>';
            const txCount = StatementImportsPage._txCountFor(im);
            return `
                <tr>
                    <td>${baLabel}</td>
                    <td>${period}</td>
                    <td>${StatementImportsPage._statusBadge(im.status)}</td>
                    <td class="amount" style="font-family:var(--font-mono-ds);">${txCount}</td>
                    <td class="amount" style="font-family:var(--font-mono-ds);">${StatementImportsPage._formatCents(im.vision_cost_cents)}</td>
                    <td style="font-size:11px; color:var(--ink-3);">${im.uploaded_at ? formatDate(im.uploaded_at.slice(0, 10)) : ''}</td>
                    <td class="actions" style="white-space:nowrap;">
                        ${StatementImportsPage._actionButtons(im)}
                    </td>
                </tr>
            `;
        }).join('');
        return `
            <h2 style="font-size:14px; font-weight:600; margin:0 0 12px;">All imports</h2>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Bank account</th>
                            <th>Period</th>
                            <th>Status</th>
                            <th class="amount">Txns</th>
                            <th class="amount">Cost</th>
                            <th>Uploaded</th>
                            <th style="width:1%;"></th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    },

    _statusBadge(status) {
        // Same colour vocabulary as the rest of the app: green = done,
        // amber = needs action, slate = in progress, red = failed.
        const palette = {
            posted:  { bg: '#e6f4ea', fg: '#1b5e20', label: 'Posted' },
            parsed:  { bg: '#fff8e1', fg: '#7a5b00', label: 'Parsed — ready to post' },
            parsing: { bg: '#e3eaf2', fg: '#1f3a5f', label: 'Parsing…' },
            pending: { bg: '#eef0f2', fg: '#3f4a55', label: 'Pending' },
            failed:  { bg: '#fde7e7', fg: '#8a1a1a', label: 'Failed' },
        };
        const p = palette[status] || palette.pending;
        return `<span style="display:inline-block; padding:2px 8px; border-radius:10px;
                              background:${p.bg}; color:${p.fg};
                              font-size:11px; font-weight:600; letter-spacing:0.02em;">
                  ${p.label}
                </span>`;
    },

    _actionButtons(im) {
        const buttons = [];
        if (im.status === 'parsed') {
            buttons.push(`<button class="btn btn-sm btn-primary"
                onclick="StatementImportsPage.openPreview(${im.id})">Preview &amp; post</button>`);
        } else if (im.status === 'posted') {
            buttons.push(`<button class="btn btn-sm"
                onclick="StatementImportsPage.openPreview(${im.id})">View</button>`);
        } else if (im.status === 'failed') {
            buttons.push(`<button class="btn btn-sm"
                onclick="StatementImportsPage.showFailure(${im.id})">Why?</button>`);
        }
        buttons.push(`<a class="btn btn-sm" target="_blank"
                rel="noopener" href="/api/statement-imports/${im.id}/pdf">PDF</a>`);
        buttons.push(`<button class="btn btn-sm btn-danger"
                onclick="StatementImportsPage.deleteImport(${im.id})">Delete</button>`);
        return buttons.join(' ');
    },

    _txCountFor(im) {
        // For posted rows we know the count is in bank_transactions; we
        // only have the parsed payload after a fetch, so stash transaction
        // counts opportunistically when previewing. Falls back to '—' if
        // unknown so the column never shows a misleading 0.
        if (im._cachedTxCount != null) return im._cachedTxCount;
        return '<span style="color:var(--ink-3);">&mdash;</span>';
    },

    // ----------------------------------------------------------------
    // Upload modal
    // ----------------------------------------------------------------
    openUploadModal() {
        const accts = StatementImportsPage._bankAccounts;
        if (accts.length === 0) {
            toast('Add a bank account first', 'error');
            return;
        }
        // Active accounts first, closed (is_active=false) at the bottom
        // and visually deprioritised.
        const active = accts.filter(a => a.is_active);
        const closed = accts.filter(a => !a.is_active);
        const optHtml = (a) => `<option value="${a.id}">${escapeHtml(a.name)}${a.last_four ? ` (${escapeHtml(a.last_four)})` : ''}${!a.is_active ? ' — closed' : ''}</option>`;
        const options = [...active.map(optHtml), ...closed.map(optHtml)].join('');

        openModal('Upload statement PDF', `
            <form id="si-upload-form" onsubmit="StatementImportsPage.submitUpload(event)">
                <div class="form-group">
                    <label>Bank account *</label>
                    <select name="bank_account_id" required>${options}</select>
                </div>
                <div class="form-group">
                    <label>PDF file *</label>
                    <input type="file" name="file" accept="application/pdf" required>
                </div>
                <p style="font-size:11px; color:var(--ink-3); margin:6px 0 0;">
                    Anthropic Sonnet 4.6 reads the PDF and extracts every
                    transaction. Typical 5-10 page statement: ~30-60 seconds,
                    ~5&cent;. The same PDF can't be uploaded twice (SHA-256 dedup).
                </p>
                <div id="si-upload-status" style="display:none; margin-top:12px; font-size:12px; color:var(--ink-2);">
                    <span class="si-spinner" style="display:inline-block; width:10px; height:10px; border:2px solid var(--rule); border-top-color:var(--ink); border-radius:50%; animation:si-spin 0.8s linear infinite; vertical-align:-1px; margin-right:6px;"></span>
                    Parsing… this can take up to a minute for a multi-page statement.
                </div>
                <style>@keyframes si-spin { to { transform: rotate(360deg); } }</style>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary"
                            onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary" id="si-upload-submit">Upload &amp; parse</button>
                </div>
            </form>
        `);
    },

    async submitUpload(e) {
        e.preventDefault();
        const form = e.target;
        const fd = new FormData(form);
        const bankAccountId = fd.get('bank_account_id');
        const file = fd.get('file');
        if (!file || !file.size) {
            toast('Choose a PDF first', 'error');
            return;
        }
        // Lock the form, show the spinner row.
        const submit = form.querySelector('#si-upload-submit');
        const statusRow = form.querySelector('#si-upload-status');
        submit.disabled = true;
        submit.textContent = 'Parsing…';
        statusRow.style.display = '';

        const upload = new FormData();
        upload.append('file', file);
        try {
            const result = await API.upload(
                `/statement-imports/upload/${bankAccountId}`, upload,
            );
            closeModal();
            if (!result.parsed) {
                toast(`Parse failed: ${result.import.error_message || 'unknown error'}`, 'error');
            } else {
                toast(`Parsed ${result.parsed.transactions.length} transactions for ${StatementImportsPage._formatCents(result.import.vision_cost_cents)}`);
            }
            await StatementImportsPage._refresh();
            if (result.parsed) {
                StatementImportsPage._showPreviewWith(result.import, result.parsed);
            }
        } catch (err) {
            submit.disabled = false;
            submit.textContent = 'Upload & parse';
            statusRow.style.display = 'none';
            // Special-case the 409 dedup so the user sees a useful pointer.
            if (err.status === 409 && err.detail && err.detail.existing_import_id) {
                toast(`Already imported as #${err.detail.existing_import_id} (status: ${err.detail.existing_status})`, 'error');
            } else {
                toast(err.message || 'Upload failed', 'error');
            }
        }
    },

    // ----------------------------------------------------------------
    // Preview / post modal
    // ----------------------------------------------------------------
    async openPreview(importId) {
        try {
            const data = await API.get(`/statement-imports/${importId}`);
            StatementImportsPage._showPreviewWith(data.import, data.parsed);
        } catch (err) {
            toast(err.message || 'Could not load import', 'error');
        }
    },

    _showPreviewWith(im, parsed) {
        const txs = (parsed && parsed.transactions) || [];
        // Cache the count on the in-memory list row so the table column
        // shows it without a re-fetch.
        const cached = StatementImportsPage._imports.find(x => x.id === im.id);
        if (cached) cached._cachedTxCount = txs.length;

        const header = parsed && parsed.statement
            ? `${escapeHtml(parsed.statement.bank_name || '')}${parsed.statement.account_last_four ? ` &middot; •••${escapeHtml(parsed.statement.account_last_four)}` : ''}`
            : '';
        const period = (im.period_start && im.period_end)
            ? `${formatDate(im.period_start)} &ndash; ${formatDate(im.period_end)}`
            : '—';

        const txRows = txs.map((t, i) => `
            <tr>
                <td style="font-family:var(--font-mono-ds); font-size:12px;">${formatDate(t.date)}</td>
                <td style="font-size:12px;" title="${escapeHtml(t.description || '')}">
                    ${escapeHtml((t.description || '').slice(0, 80))}${(t.description || '').length > 80 ? '…' : ''}
                </td>
                <td class="amount" style="font-family:var(--font-mono-ds); font-size:12px; ${t.amount < 0 ? 'color:#8a1a1a;' : 'color:#1b5e20;'}">
                    ${t.amount < 0 ? '-' : '+'}$${Math.abs(t.amount).toFixed(2)}
                </td>
                <td style="font-family:var(--font-mono-ds); font-size:11px; color:var(--ink-3);">${escapeHtml(t.check_number || '')}</td>
            </tr>
        `).join('');

        const postBtn = im.status === 'parsed'
            ? `<button class="btn btn-primary" onclick="StatementImportsPage.postImport(${im.id})">Post ${txs.length} transaction${txs.length === 1 ? '' : 's'}</button>`
            : (im.status === 'posted'
                ? `<span style="color:var(--ink-3); font-size:12px;">Posted ${im.posted_at ? formatDate(im.posted_at.slice(0, 10)) : ''}</span>`
                : '');

        const summary = `
            <div style="display:flex; flex-wrap:wrap; gap:14px; margin-bottom:10px; font-size:12px; color:var(--ink-2);">
                <span><strong>Period:</strong> ${period}</span>
                <span><strong>Transactions:</strong> ${txs.length}</span>
                <span><strong>Cost:</strong> ${StatementImportsPage._formatCents(im.vision_cost_cents)}</span>
                <span><strong>Tokens:</strong> ${im.input_tokens || 0} in / ${im.output_tokens || 0} out</span>
                <span><strong>Status:</strong> ${StatementImportsPage._statusBadge(im.status)}</span>
            </div>
        `;

        openModal(`Statement #${im.id}${header ? ` — ${header}` : ''}`, `
            ${summary}
            <div class="table-container" style="max-height:50vh; overflow:auto;">
                <table>
                    <thead><tr>
                        <th style="width:90px;">Date</th>
                        <th>Description</th>
                        <th class="amount" style="width:100px;">Amount</th>
                        <th style="width:80px;">Check #</th>
                    </tr></thead>
                    <tbody>${txRows || `<tr><td colspan="4" style="text-align:center; color:var(--ink-3); padding:20px;">No transactions parsed</td></tr>`}</tbody>
                </table>
            </div>
            <div class="form-actions" style="margin-top:14px;">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Close</button>
                <a class="btn" target="_blank" rel="noopener"
                   href="/api/statement-imports/${im.id}/pdf">View source PDF</a>
                ${postBtn}
            </div>
        `);
    },

    async postImport(importId) {
        try {
            const result = await API.post(
                `/statement-imports/${importId}/post`, null,
            );
            const dup = result.duplicate_count || 0;
            const msg = dup
                ? `Posted ${result.created_count} new (skipped ${dup} duplicate${dup === 1 ? '' : 's'})`
                : `Posted ${result.created_count} transaction${result.created_count === 1 ? '' : 's'}`;
            toast(msg);
            closeModal();
            await StatementImportsPage._refresh();
        } catch (err) {
            toast(err.message || 'Post failed', 'error');
        }
    },

    async showFailure(importId) {
        try {
            const data = await API.get(`/statement-imports/${importId}`);
            openModal(`Statement #${importId} — failed`, `
                <p>The vision parser couldn't read this PDF.</p>
                <pre style="background:var(--card); border:1px solid var(--rule); padding:10px; font-size:11px; max-height:40vh; overflow:auto; white-space:pre-wrap;">${escapeHtml(data.import.error_message || 'No error message recorded.')}</pre>
                <div class="form-actions" style="margin-top:12px;">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Close</button>
                    <a class="btn" target="_blank" rel="noopener"
                       href="/api/statement-imports/${importId}/pdf">View source PDF</a>
                </div>
            `);
        } catch (err) {
            toast(err.message || 'Could not load import', 'error');
        }
    },

    async deleteImport(importId) {
        if (!confirm('Delete this statement import? Posted bank transactions will keep their data but lose the drill-back link to the PDF.')) {
            return;
        }
        try {
            await API.del(`/statement-imports/${importId}`);
            toast('Import deleted');
            await StatementImportsPage._refresh();
        } catch (err) {
            toast(err.message || 'Delete failed', 'error');
        }
    },

    // ----------------------------------------------------------------
    // Internals
    // ----------------------------------------------------------------
    async _refresh() {
        const html = await StatementImportsPage.render();
        document.getElementById('page-content').innerHTML = html;
    },

    _formatCents(cents) {
        if (cents == null) return '<span style="color:var(--ink-3);">&mdash;</span>';
        return `$${(cents / 100).toFixed(2)}`;
    },
};
