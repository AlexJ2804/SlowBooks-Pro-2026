/**
 * Multi-Company — switch between company databases
 * Feature 16: Company list and creation UI
 */
const CompaniesPage = {
    async render() {
        const companies = await API.get('/companies');
        let html = `
            <div class="page-header">
                <h2>Company Files</h2>
                <button class="btn btn-primary" onclick="CompaniesPage.showCreate()">+ New Company</button>
            </div>
            <p style="font-size:11px;color:var(--text-muted);margin-bottom:12px;">
                Each company uses a separate PostgreSQL database. Switch between companies below.
            </p>`;

        if (companies.length === 0) {
            html += '<div class="empty-state"><p>No additional companies created</p></div>';
        } else {
            html += '<div class="card-grid">';
            for (const c of companies) {
                html += `<div class="card" style="cursor:pointer;" onclick="CompaniesPage.switchTo('${escapeHtml(c.database_name)}')">
                    <div class="card-header">${escapeHtml(c.name)}</div>
                    <div style="font-size:10px;color:var(--text-muted);">${escapeHtml(c.database_name)}</div>
                    ${c.description ? `<div style="font-size:11px;margin-top:4px;">${escapeHtml(c.description)}</div>` : ''}
                    <div style="font-size:9px;color:var(--text-light);margin-top:4px;">Last accessed: ${c.last_accessed ? new Date(c.last_accessed).toLocaleDateString() : 'Never'}</div>
                </div>`;
            }
            html += '</div>';
        }
        return html;
    },

    showCreate() {
        openModal('New Company', `
            <form onsubmit="CompaniesPage.create(event)">
                <div class="form-grid">
                    <div class="form-group"><label>Company Name *</label>
                        <input name="name" required></div>
                    <div class="form-group"><label>Database Name *</label>
                        <input name="database_name" required pattern="[a-z0-9_]+" title="Lowercase letters, numbers, underscores only"></div>
                    <div class="form-group full-width"><label>Description</label>
                        <textarea name="description"></textarea></div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Create Company</button>
                </div>
            </form>`);
    },

    async create(e) {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        try {
            await API.post('/companies', data);
            toast('Company created');
            closeModal();
            App.navigate('#/companies');
        } catch (err) { toast(err.message, 'error'); }
    },

    switchTo(dbName) {
        // Store selected company in localStorage
        localStorage.setItem('slowbooks_company', dbName);
        toast(`Switched to ${dbName}. Reload to apply.`);
        // In a full implementation, this would reload with X-Company-Id header
        location.reload();
    },
};
