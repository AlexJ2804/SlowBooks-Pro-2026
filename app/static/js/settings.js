/**
 * Decompiled from QBW32.EXE!CPreferencesDialog  Offset: 0x0023F800
 * Original: tabbed dialog (IDD_PREFERENCES) with 12 tabs. We condensed
 * everything into a single page because nobody needs 12 tabs for
 * company name and tax rate. The registry writes at 0x00240200 are now
 * PostgreSQL INSERTs. Progress.
 */
const SettingsPage = {
    async render() {
        const s = await API.get('/settings');
        setTimeout(() => {
            SettingsPage.loadBackups();
            SettingsPage.loadEmailTemplates();
            SettingsPage.loadClasses();
            SettingsPage.renderParseCounter(s);
        }, 0);
        return `
            <div class="page-header">
                <h2>Company Settings</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    CPreferencesDialog — IDD_PREFERENCES @ 0x0023F800
                </div>
            </div>
            <form id="settings-form" onsubmit="SettingsPage.save(event)">
                <div class="settings-section">
                    <h3>Company Information</h3>
                    <div class="form-grid">
                        <div class="form-group full-width"><label>Company Name *</label>
                            <input name="company_name" value="${escapeHtml(s.company_name || '')}" required></div>
                        <div class="form-group"><label>Address Line 1</label>
                            <input name="company_address1" value="${escapeHtml(s.company_address1 || '')}"></div>
                        <div class="form-group"><label>Address Line 2</label>
                            <input name="company_address2" value="${escapeHtml(s.company_address2 || '')}"></div>
                        <div class="form-group"><label>City</label>
                            <input name="company_city" value="${escapeHtml(s.company_city || '')}"></div>
                        <div class="form-group"><label>State</label>
                            <input name="company_state" value="${escapeHtml(s.company_state || '')}"></div>
                        <div class="form-group"><label>ZIP</label>
                            <input name="company_zip" value="${escapeHtml(s.company_zip || '')}"></div>
                        <div class="form-group"><label>Phone</label>
                            <input name="company_phone" value="${escapeHtml(s.company_phone || '')}"></div>
                        <div class="form-group"><label>Email</label>
                            <input name="company_email" type="email" value="${escapeHtml(s.company_email || '')}"></div>
                        <div class="form-group"><label>Website</label>
                            <input name="company_website" value="${escapeHtml(s.company_website || '')}"></div>
                        <div class="form-group"><label>Tax ID / EIN</label>
                            <input name="company_tax_id" value="${escapeHtml(s.company_tax_id || '')}"></div>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>Company Logo</h3>
                    <div class="form-grid">
                        <div class="form-group">
                            ${s.company_logo_path ? `<img src="${escapeHtml(s.company_logo_path)}" style="max-width:200px; max-height:80px; margin-bottom:8px; display:block;">` : ''}
                            <input type="file" id="logo-upload" accept="image/*" onchange="SettingsPage.uploadLogo(this)">
                            <div style="font-size:10px; color:var(--text-muted); margin-top:4px;">PNG, JPG, GIF, WebP, or SVG &middot; max 5 MB &middot; 200&times;80 px recommended.</div>
                        </div>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>Invoice Defaults</h3>
                    <div class="form-grid">
                        <div class="form-group"><label>Default Terms</label>
                            <select name="default_terms">
                                ${['Net 15','Net 30','Net 45','Net 60','Due on Receipt'].map(t =>
                                    `<option ${s.default_terms===t?'selected':''}>${t}</option>`).join('')}
                            </select></div>
                        <div class="form-group"><label>Default Tax Rate (%)</label>
                            <input name="default_tax_rate" type="number" step="0.01" value="${s.default_tax_rate || '0.0'}"></div>
                        <div class="form-group"><label>Invoice Prefix</label>
                            <input name="invoice_prefix" value="${escapeHtml(s.invoice_prefix || '')}" placeholder="e.g. INV-"></div>
                        <div class="form-group"><label>Next Invoice #</label>
                            <input name="invoice_next_number" value="${escapeHtml(s.invoice_next_number || '1001')}"></div>
                        <div class="form-group"><label>Estimate Prefix</label>
                            <input name="estimate_prefix" value="${escapeHtml(s.estimate_prefix || '')}" placeholder="e.g. E-"></div>
                        <div class="form-group"><label>Next Estimate #</label>
                            <input name="estimate_next_number" value="${escapeHtml(s.estimate_next_number || '1001')}"></div>
                        <div class="form-group full-width"><label>Default Invoice Notes</label>
                            <textarea name="invoice_notes">${escapeHtml(s.invoice_notes || '')}</textarea></div>
                        <div class="form-group full-width"><label>Invoice Footer</label>
                            <input name="invoice_footer" value="${escapeHtml(s.invoice_footer || '')}"></div>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>Classes</h3>
                    <div style="font-size:10px; color:var(--text-muted); margin-bottom:8px;">
                        Tag every transaction with a class so reports can slice by Alex W-2,
                        Wife 1099, Ireland Projects, etc. Archived classes stay attached to
                        their existing transactions but are hidden from new-transaction dropdowns.
                        The "Uncategorized" class is the system default for auto-generated
                        entries (Stripe webhooks, payroll, late fees) and cannot be renamed
                        or archived.
                    </div>
                    <div style="margin-bottom:8px;">
                        <button type="button" class="btn btn-sm btn-primary" onclick="SettingsPage.newClass()">+ New Class</button>
                    </div>
                    <div id="settings-classes-list"></div>
                </div>

                <div class="settings-section">
                    <h3>Multi-Currency</h3>
                    <div style="font-size:10px; color:var(--text-muted); margin-bottom:8px;">
                        Home currency is used for the YTD total and the home-currency
                        column on the invoices list. Changing this does not retroactively
                        recalculate existing invoices.
                    </div>
                    <div class="form-grid">
                        <div class="form-group"><label>Home Currency</label>
                            <select name="home_currency">
                                ${currencyOptions((s.home_currency || 'USD').toUpperCase())}
                            </select></div>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>Closing Date</h3>
                    <div style="font-size:10px; color:var(--text-muted); margin-bottom:8px;">
                        Prevent modifications to transactions before this date.
                    </div>
                    <div class="form-grid">
                        <div class="form-group"><label>Closing Date</label>
                            <input name="closing_date" type="date" value="${escapeHtml(s.closing_date || '')}"></div>
                        <div class="form-group"><label>Password (optional)</label>
                            <input name="closing_date_password" type="password" value="${escapeHtml(s.closing_date_password || '')}"
                                placeholder="Leave blank for no password"></div>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>Email (SMTP)</h3>
                    <div style="font-size:10px; color:var(--text-muted); margin-bottom:8px;">
                        Configure SMTP for sending invoices by email.
                    </div>
                    <div class="form-grid">
                        <div class="form-group"><label>SMTP Host</label>
                            <input name="smtp_host" value="${escapeHtml(s.smtp_host || '')}" placeholder="smtp.gmail.com"></div>
                        <div class="form-group"><label>SMTP Port</label>
                            <input name="smtp_port" type="number" value="${escapeHtml(s.smtp_port || '587')}"></div>
                        <div class="form-group"><label>Username</label>
                            <input name="smtp_user" value="${escapeHtml(s.smtp_user || '')}"></div>
                        <div class="form-group"><label>Password</label>
                            <input name="smtp_password" type="password" value="${escapeHtml(s.smtp_password || '')}"></div>
                        <div class="form-group"><label>From Email</label>
                            <input name="smtp_from_email" type="email" value="${escapeHtml(s.smtp_from_email || '')}"></div>
                        <div class="form-group"><label>From Name</label>
                            <input name="smtp_from_name" value="${escapeHtml(s.smtp_from_name || '')}"></div>
                        <div class="form-group"><label>Use TLS</label>
                            <select name="smtp_use_tls">
                                <option value="true" ${s.smtp_use_tls !== 'false' ? 'selected' : ''}>Yes</option>
                                <option value="false" ${s.smtp_use_tls === 'false' ? 'selected' : ''}>No</option>
                            </select></div>
                    </div>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="SettingsPage.testEmail()" style="margin-top:8px;">
                        Send Test Email</button>
                </div>

                <div class="settings-section">
                    <h3>Online Payments (Stripe)</h3>
                    <div style="font-size:10px; color:var(--text-muted); margin-bottom:8px;">
                        Accept online payments via Stripe Checkout. Customers can pay invoices directly from emailed links.
                    </div>
                    <div class="form-grid">
                        <div class="form-group"><label>Enable Online Payments</label>
                            <select name="stripe_enabled">
                                <option value="false" ${s.stripe_enabled !== 'true' ? 'selected' : ''}>Disabled</option>
                                <option value="true" ${s.stripe_enabled === 'true' ? 'selected' : ''}>Enabled</option>
                            </select></div>
                        <div class="form-group"><label>Publishable Key</label>
                            <input name="stripe_publishable_key" value="${escapeHtml(s.stripe_publishable_key || '')}" placeholder="pk_..."></div>
                        <div class="form-group"><label>Secret Key</label>
                            <input name="stripe_secret_key" type="password" value="${escapeHtml(s.stripe_secret_key || '')}" placeholder="sk_..."></div>
                        <div class="form-group"><label>Webhook Secret</label>
                            <input name="stripe_webhook_secret" type="password" value="${escapeHtml(s.stripe_webhook_secret || '')}" placeholder="whsec_..."></div>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>QuickBooks Online</h3>
                    <div style="font-size:10px; color:var(--text-muted); margin-bottom:8px;">
                        Configure your Intuit Developer app credentials for QBO integration.
                        Get these from <a href="https://developer.intuit.com" target="_blank" style="color:var(--qb-blue);">developer.intuit.com</a>.
                    </div>
                    <div class="form-grid">
                        <div class="form-group"><label>Enable QBO Integration</label>
                            <select name="qbo_enabled">
                                <option value="false" ${s.qbo_enabled !== 'true' ? 'selected' : ''}>Disabled</option>
                                <option value="true" ${s.qbo_enabled === 'true' ? 'selected' : ''}>Enabled</option>
                            </select></div>
                        <div class="form-group"><label>Environment</label>
                            <select name="qbo_environment">
                                <option value="sandbox" ${s.qbo_environment !== 'production' ? 'selected' : ''}>Sandbox</option>
                                <option value="production" ${s.qbo_environment === 'production' ? 'selected' : ''}>Production</option>
                            </select></div>
                        <div class="form-group"><label>Client ID</label>
                            <input name="qbo_client_id" value="${escapeHtml(s.qbo_client_id || '')}" placeholder="ABo8gw..."></div>
                        <div class="form-group"><label>Client Secret</label>
                            <input name="qbo_client_secret" type="password" value="${escapeHtml(s.qbo_client_secret || '')}" placeholder="tJCdgW..."></div>
                        <div class="form-group full-width"><label>Redirect URI</label>
                            <input name="qbo_redirect_uri" value="${escapeHtml(s.qbo_redirect_uri || 'http://localhost:8000/api/qbo/callback')}"
                                placeholder="http://localhost:8000/api/qbo/callback"></div>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>Late Fees</h3>
                    <div style="font-size:10px; color:var(--text-muted); margin-bottom:8px;">
                        Automatically apply late fees to overdue invoices. Use "Apply Late Fees" on the AR Aging report.
                    </div>
                    <div class="form-grid">
                        <div class="form-group"><label>Enable Late Fees</label>
                            <select name="late_fee_enabled">
                                <option value="false" ${s.late_fee_enabled !== 'true' ? 'selected' : ''}>Disabled</option>
                                <option value="true" ${s.late_fee_enabled === 'true' ? 'selected' : ''}>Enabled</option>
                            </select></div>
                        <div class="form-group"><label>Late Fee Rate (%)</label>
                            <input name="late_fee_rate" type="number" step="0.1" value="${escapeHtml(s.late_fee_rate || '1.5')}"></div>
                        <div class="form-group"><label>Grace Days</label>
                            <input name="late_fee_grace_days" type="number" value="${escapeHtml(s.late_fee_grace_days || '15')}"></div>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>Receipt Parsing (Anthropic API)</h3>
                    <div style="font-size:10px; color:var(--text-muted); margin-bottom:8px;">
                        Upload receipt images or PDFs and have them auto-filled into a bill confirm form.
                        Requires an Anthropic API key. The user always reviews the extracted data before saving.
                        <strong>Single-worker only:</strong> the post-parse attachment handoff uses an in-process
                        token store; running with multiple workers will break the attach step.
                    </div>
                    <div class="form-grid">
                        <div class="form-group"><label>Enable AI receipt parsing</label>
                            <select name="receipt_parser_enabled">
                                <option value="false" ${s.receipt_parser_enabled !== 'true' ? 'selected' : ''}>Disabled</option>
                                <option value="true" ${s.receipt_parser_enabled === 'true' ? 'selected' : ''}>Enabled</option>
                            </select></div>
                        <div class="form-group"><label>Model</label>
                            <select name="receipt_parser_model">
                                <option value="claude-haiku-4-5-20251001" ${(s.receipt_parser_model || 'claude-haiku-4-5-20251001') === 'claude-haiku-4-5-20251001' ? 'selected' : ''}>Haiku 4.5 (cheapest, recommended)</option>
                                <option value="claude-sonnet-4-6" ${s.receipt_parser_model === 'claude-sonnet-4-6' ? 'selected' : ''}>Sonnet 4.6 (more accurate, ~10× cost)</option>
                            </select>
                            <div style="font-size:10px; color:var(--text-muted); margin-top:2px;">Haiku handles typical receipts well. Pick Sonnet only if you see frequent extraction errors.</div>
                        </div>
                        <div class="form-group full-width"><label>API key</label>
                            <input name="anthropic_api_key" type="password" value="${escapeHtml(s.anthropic_api_key || '')}" placeholder="sk-ant-..." autocomplete="off">
                            <div style="font-size:10px; color:var(--text-muted); margin-top:2px;">
                                Stored server-side. After save, this field shows the masked value (••••••••<em>last4</em>); leave it as-is to keep the saved key.
                            </div>
                            <button type="button" class="btn btn-sm btn-secondary" id="receipt-test-conn-btn" style="margin-top:6px;" onclick="SettingsPage.testReceiptParser()">Test Connection</button>
                            <span id="receipt-test-conn-result" style="font-size:11px; margin-left:8px;"></span>
                        </div>
                        <div class="form-group"><label>Max upload size</label>
                            <select name="receipt_parser_max_file_size_mb">
                                <option value="5" ${s.receipt_parser_max_file_size_mb === '5' ? 'selected' : ''}>5 MB</option>
                                <option value="10" ${(s.receipt_parser_max_file_size_mb || '10') === '10' ? 'selected' : ''}>10 MB</option>
                                <option value="25" ${s.receipt_parser_max_file_size_mb === '25' ? 'selected' : ''}>25 MB (PDF only — Anthropic caps images at 5 MB regardless)</option>
                            </select>
                            <div style="font-size:10px; color:var(--text-muted); margin-top:2px;">Images are hard-capped at 5 MB by the Anthropic API even if you raise this. PDFs honor the chosen limit.</div>
                        </div>
                        <div class="form-group">
                            <label>Usage this month</label>
                            <div id="receipt-parse-counter" style="padding-top:6px; font-weight:600;">— receipts parsed</div>
                        </div>
                    </div>
                </div>

                <div class="settings-section">
                    <h3>Email Templates</h3>
                    <div style="font-size:10px; color:var(--text-muted); margin-bottom:8px;">
                        Customize email templates for invoices, payment receipts, and collection notices.
                        Templates use Jinja2 syntax. Available variables: {{ invoice }}, {{ customer_name }}, {{ company }}, {{ pay_url }}.
                    </div>
                    <div style="display:flex; gap:8px; margin-bottom:12px;">
                        <button type="button" class="btn btn-sm btn-secondary" onclick="SettingsPage.seedTemplates()">Seed Default Templates</button>
                    </div>
                    <div id="email-template-list"></div>
                </div>

                <div class="settings-section">
                    <h3>Backup / Restore</h3>
                    <div style="display:flex; gap:8px; margin-bottom:12px;">
                        <button type="button" class="btn btn-primary" onclick="SettingsPage.createBackup()">Create Backup</button>
                    </div>
                    <div id="backup-list"></div>
                </div>

                <div class="form-actions">
                    <button type="submit" class="btn btn-primary">Save Settings</button>
                </div>
            </form>`;
    },

    async save(e) {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        // Remove file input from data
        delete data.file;
        try {
            await API.put('/settings', data);
            toast('Settings saved');
        } catch (err) {
            toast(err.message, 'error');
        }
    },

    async uploadLogo(input) {
        if (!input.files[0]) return;
        const formData = new FormData();
        formData.append('file', input.files[0]);
        try {
            const resp = await fetch('/api/uploads/logo', { method: 'POST', body: formData });
            // Parse JSON defensively — a reverse-proxy or framework error can
            // return a non-JSON body, and the raw SyntaxError ("Unexpected
            // token <") confuses end users worse than the actual problem.
            let data = null;
            try { data = await resp.json(); }
            catch (_) { data = null; }
            if (!resp.ok) {
                const msg = (data && data.detail) ||
                    `Upload failed (HTTP ${resp.status}). The file may be too large or the server returned an unexpected response.`;
                throw new Error(msg);
            }
            toast('Logo uploaded');
            App.navigate('#/settings');
        } catch (err) { toast(err.message, 'error'); }
    },

    async testEmail() {
        try {
            await API.post('/settings/test-email');
            toast('Test email sent');
        } catch (err) { toast(err.message, 'error'); }
    },

    async createBackup() {
        try {
            const result = await API.post('/backups');
            toast(`Backup created: ${result.filename}`);
            SettingsPage.loadBackups();
        } catch (err) { toast(err.message, 'error'); }
    },

    async loadBackups() {
        try {
            const backups = await API.get('/backups');
            const el = $('#backup-list');
            if (!el) return;
            if (backups.length === 0) {
                el.innerHTML = '<div style="font-size:11px; color:var(--text-muted);">No backups yet.</div>';
                return;
            }
            el.innerHTML = `<div class="table-container"><table>
                <thead><tr><th>Filename</th><th>Size</th><th>Created</th><th>Actions</th></tr></thead>
                <tbody>${backups.map(b => `<tr>
                    <td>${escapeHtml(b.filename)}</td>
                    <td>${(b.file_size / 1024).toFixed(1)} KB</td>
                    <td>${formatDate(b.created_at)}</td>
                    <td class="actions">
                        <a href="/api/backups/download/${encodeURIComponent(b.filename)}" class="btn btn-sm btn-secondary" download>Download</a>
                    </td>
                </tr>`).join('')}</tbody>
            </table></div>`;
        } catch (e) { /* ignore */ }
    },

    async seedTemplates() {
        try {
            const result = await API.post('/email-templates/seed-defaults');
            toast(`Created ${result.created} default templates`);
            SettingsPage.loadEmailTemplates();
        } catch (err) { toast(err.message, 'error'); }
    },

    async loadEmailTemplates() {
        try {
            const templates = await API.get('/email-templates');
            const el = $('#email-template-list');
            if (!el) return;
            if (templates.length === 0) {
                el.innerHTML = '<div style="font-size:11px; color:var(--text-muted);">No templates. Click "Seed Default Templates" to create them.</div>';
                return;
            }
            el.innerHTML = `<div class="table-container"><table>
                <thead><tr><th>Name</th><th>Type</th><th>Subject</th><th>Actions</th></tr></thead>
                <tbody>${templates.map(t => `<tr>
                    <td><strong>${escapeHtml(t.name)}</strong></td>
                    <td>${escapeHtml(t.template_type)}</td>
                    <td style="font-size:11px;">${escapeHtml(t.subject_template)}</td>
                    <td class="actions">
                        <button class="btn btn-sm btn-secondary" onclick="SettingsPage.editTemplate(${t.id})">Edit</button>
                    </td>
                </tr>`).join('')}</tbody>
            </table></div>`;
        } catch (e) { /* ignore */ }
    },

    async editTemplate(id) {
        const t = await API.get(`/email-templates/${id}`);
        openModal('Edit Email Template', `
            <form onsubmit="SettingsPage.saveTemplate(event, ${id})">
                <div class="form-grid">
                    <div class="form-group"><label>Name</label>
                        <input name="name" value="${escapeHtml(t.name)}" readonly style="background:var(--gray-100);"></div>
                    <div class="form-group"><label>Type</label>
                        <input name="template_type" value="${escapeHtml(t.template_type)}" readonly style="background:var(--gray-100);"></div>
                    <div class="form-group full-width"><label>Subject Template</label>
                        <input name="subject_template" value="${escapeHtml(t.subject_template)}"></div>
                    <div class="form-group full-width"><label>Body Template (HTML + Jinja2)</label>
                        <textarea name="body_template" rows="10" style="font-family:monospace; font-size:11px;">${escapeHtml(t.body_template)}</textarea></div>
                </div>
                <div style="font-size:10px; color:var(--text-muted); margin:8px 0;">
                    Variables: {{ invoice.invoice_number }}, {{ invoice.total }}, {{ invoice.due_date }}, {{ customer_name }},
                    {{ company.company_name }}, {{ pay_url }}, {{ amount }}. Filters: | currency, | fdate
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save Template</button>
                </div>
            </form>`);
    },

    async saveTemplate(e, id) {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        try {
            await API.put(`/email-templates/${id}`, { subject_template: data.subject_template, body_template: data.body_template });
            toast('Template saved');
            closeModal();
            SettingsPage.loadEmailTemplates();
        } catch (err) { toast(err.message, 'error'); }
    },

    async loadClasses() {
        try {
            const classes = await API.get('/classes?include_archived=true');
            const el = $('#settings-classes-list');
            if (!el) return;
            if (classes.length === 0) {
                el.innerHTML = '<div style="font-size:11px; color:var(--text-muted);">No classes.</div>';
                return;
            }
            el.innerHTML = `<div class="table-container"><table>
                <thead><tr><th>Name</th><th>Status</th><th>Actions</th></tr></thead>
                <tbody>${classes.map(c => {
                    const locked = c.is_system_default;
                    const archivedBadge = c.is_archived
                        ? '<span style="font-size:10px; padding:1px 6px; background:var(--gray-200); border-radius:4px;">archived</span>'
                        : '';
                    const sysBadge = locked
                        ? '<span style="font-size:10px; padding:1px 6px; background:var(--primary-light); color:var(--qb-blue); border-radius:4px;">system</span>'
                        : '';
                    return `<tr>
                        <td><strong>${escapeHtml(c.name)}</strong> ${sysBadge} ${archivedBadge}</td>
                        <td>${c.is_archived ? 'Archived' : 'Active'}</td>
                        <td class="actions">
                            <button class="btn btn-sm btn-secondary" ${locked ? 'disabled title="System default — cannot be renamed"' : `onclick="SettingsPage.renameClass(${c.id}, '${escapeHtml(c.name).replace(/'/g, "\\'")}')"`}>Rename</button>
                            <button class="btn btn-sm btn-secondary" ${locked ? 'disabled title="System default — cannot be archived"' : `onclick="SettingsPage.toggleArchiveClass(${c.id}, ${!c.is_archived})"`}>${c.is_archived ? 'Unarchive' : 'Archive'}</button>
                        </td>
                    </tr>`;
                }).join('')}</tbody>
            </table></div>`;
        } catch (e) { /* ignore */ }
    },

    newClass() {
        InlineCreate.open('class', () => {
            SettingsPage.loadClasses();
        });
    },

    async renameClass(classId, currentName) {
        const name = prompt('New name:', currentName);
        if (!name || name.trim() === currentName) return;
        try {
            await API.patch(`/classes/${classId}`, { name: name.trim() });
            toast('Class renamed');
            SettingsPage.loadClasses();
        } catch (err) { toast(err.message, 'error'); }
    },

    async toggleArchiveClass(classId, archive) {
        try {
            await API.patch(`/classes/${classId}`, { is_archived: archive });
            toast(archive ? 'Class archived' : 'Class unarchived');
            SettingsPage.loadClasses();
        } catch (err) { toast(err.message, 'error'); }
    },

    renderParseCounter(settings) {
        // Settings comes from GET /api/settings; the per-month counter
        // surfaces as a key like receipts_parsed_count_202604 if any
        // parse has happened this month, otherwise it just isn't there.
        const el = document.getElementById('receipt-parse-counter');
        if (!el) return;
        const now = new Date();
        const yyyymm = now.getFullYear() + String(now.getMonth() + 1).padStart(2, '0');
        const key = `receipts_parsed_count_${yyyymm}`;
        const raw = settings[key];
        const n = raw ? parseInt(raw, 10) : 0;
        el.textContent = `${Number.isFinite(n) ? n : 0} receipts parsed`;
    },

    _lastTestConnClick: 0,
    async testReceiptParser() {
        // 1-second debounce — Test Connection fires a real (~sub-cent)
        // API call. Click-spam would be wasteful even if cheap.
        const now = Date.now();
        if (now - SettingsPage._lastTestConnClick < 1000) return;
        SettingsPage._lastTestConnClick = now;

        const btn = document.getElementById('receipt-test-conn-btn');
        const result = document.getElementById('receipt-test-conn-result');
        if (btn) btn.disabled = true;
        if (result) { result.textContent = 'Testing…'; result.style.color = 'var(--gray-500)'; }
        try {
            const r = await API.post('/settings/test-receipt-parser', {});
            if (r.ok) {
                if (result) { result.textContent = '✓ ' + (r.detail || 'Connected'); result.style.color = 'var(--success, #1a7f37)'; }
            } else {
                if (result) { result.textContent = '✗ ' + (r.detail || 'Failed'); result.style.color = 'var(--danger, #b42318)'; }
            }
        } catch (err) {
            if (result) { result.textContent = '✗ ' + (err.message || 'Failed'); result.style.color = 'var(--danger, #b42318)'; }
        } finally {
            if (btn) btn.disabled = false;
        }
    },
};
