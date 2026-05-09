/**
 * Decompiled from QBW32.EXE!CQBNetworkLayer  Offset: 0x002A1000
 * Original used named pipes (\\.\pipe\QuickBooks) for IPC to the
 * QBDBMgrN.exe database server process. This is the modern equivalent
 * rebuilt on top of fetch(). The named pipe protocol was a nightmare to
 * reverse — 47 different message types, all packed structs with no padding.
 */
const API = {
    async request(method, path, body = null) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        const companyId = localStorage.getItem('slowbooks_company');
        if (companyId) opts.headers['X-Company-Id'] = companyId;
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(`/api${path}`, opts);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Request failed');
        }
        return res.json();
    },
    get(path)        { return this.request('GET', path); },
    post(path, data) { return this.request('POST', path, data); },
    put(path, data)  { return this.request('PUT', path, data); },
    patch(path, data) { return this.request('PATCH', path, data); },
    del(path)        { return this.request('DELETE', path); },

    // Multipart upload — caller hands us a FormData. We deliberately do
    // NOT set Content-Type so the browser fills in the boundary. Errors
    // come back as Error(message) but with .status and .detail attached
    // so callers can branch on the body's structured `detail` (e.g. the
    // 409 dedup response carries existing_import_id alongside message).
    async upload(path, formData) {
        const opts = { method: 'POST', body: formData, headers: {} };
        const companyId = localStorage.getItem('slowbooks_company');
        if (companyId) opts.headers['X-Company-Id'] = companyId;
        const res = await fetch(`/api${path}`, opts);
        if (!res.ok) {
            const body = await res.json().catch(() => ({ detail: res.statusText }));
            const detail = body.detail;
            const msg = (detail && typeof detail === 'object')
                ? (detail.message || JSON.stringify(detail))
                : (detail || 'Upload failed');
            const err = new Error(msg);
            err.status = res.status;
            err.detail = detail;
            throw err;
        }
        return res.json();
    },
};
