/**
 * Airline Miles — household loyalty-programme tracker (Cabin Pass design).
 *
 * Two views, both driven from the same /api/airline-miles payload:
 *   - "By programme" — one boarding-pass card per loyalty programme,
 *     stub on the left with the airline logo and accent colour, body
 *     on the right listing every household member.
 *   - "By person" — one larger card per person, stub on the left with
 *     their name and total miles, body on the right listing every
 *     programme they're enrolled in (or could be).
 *
 * Per-programme accent comes in via inline custom properties on each
 * card: `--accent` from the API's brand_color column and `--accent-soft`
 * derived inline via color-mix so we don't need a second backend column.
 *
 * Snapshot edits go through the existing /api/airline-miles/snapshots
 * upsert (re-entering the same date overwrites). Membership-add buttons
 * surface for any (person, programme) pair that doesn't yet have a row.
 */
const AirlineMilesPage = {
    _programs: [],
    _people: [],
    _state: { view: 'program' },

    async render() {
        const [programs, people] = await Promise.all([
            API.get('/airline-miles'),
            API.get('/people'),
        ]);
        AirlineMilesPage._programs = programs || [];
        AirlineMilesPage._people = (people || []).slice().sort(
            (a, b) => a.display_order - b.display_order
        );
        return AirlineMilesPage._body();
    },

    setView(view) {
        AirlineMilesPage._state.view = view;
        const root = document.getElementById('miles-root');
        if (root) root.outerHTML = AirlineMilesPage._body();
    },

    // ----------------------------------------------------------------
    // Helpers
    // ----------------------------------------------------------------
    _fmt(n) {
        if (n == null) return '&mdash;';
        return Number(n).toLocaleString('en-US');
    },

    _accentStyle(hex) {
        // --accent comes from the API; --accent-soft is a 12% tint so
        // the stub gets a faint wash without needing a second column
        // on the airline_programs table.
        return `--accent:${escapeHtml(hex)};`
             + `--accent-soft:color-mix(in srgb, ${escapeHtml(hex)} 12%, white);`;
    },

    _logoUrl(prog) {
        return prog.logo_path ? `/static/${escapeHtml(prog.logo_path)}` : '';
    },

    _personById(id) {
        return AirlineMilesPage._people.find(p => p.id === id);
    },

    _membershipFor(prog, personId) {
        return (prog.memberships || []).find(m => m.person_id === personId);
    },

    _personRoleLabel(person) {
        // Cabin Pass design surfaces the role above the name in mono
        // uppercase. Map our DB roles to a readable label and let the
        // CSS handle the uppercase styling.
        if (!person) return '';
        if (person.role === 'parent') return 'Parent';
        if (person.role === 'child')  return 'Child';
        return person.role || 'Member';
    },

    // ----------------------------------------------------------------
    // Programme card (one airline, lists all household members)
    // ----------------------------------------------------------------
    _programCard(prog) {
        const total = prog.total_balance || 0;
        const accentStyle = AirlineMilesPage._accentStyle(prog.brand_color || '#1F4FA8');
        const logoUrl = AirlineMilesPage._logoUrl(prog);

        const tile = logoUrl
            ? `<div class="sb-card-tile"><img src="${logoUrl}" alt="${escapeHtml(prog.name)}"></div>`
            : `<div class="sb-card-tile letter">${escapeHtml((prog.name || '?').charAt(0).toUpperCase())}</div>`;

        const presentIds = new Set((prog.memberships || []).map(m => m.person_id));
        const memberRows = AirlineMilesPage._people.map(person => {
            const m = AirlineMilesPage._membershipFor(prog, person.id);
            if (!m) {
                // No membership row yet for this (person, programme).
                // Render a stub line with an "Add" button so the user
                // can create the placeholder in one click.
                return `
                    <div class="sb-card-row cols-4">
                        <span class="who">${escapeHtml(person.name)}<small>${escapeHtml(AirlineMilesPage._personRoleLabel(person))}</small></span>
                        <span class="num muted">&mdash;</span>
                        <span class="bal empty">&mdash;</span>
                        <button class="btn btn-sm btn-secondary" type="button"
                                onclick="AirlineMilesPage.addMembership(${prog.id}, ${person.id})">Add</button>
                    </div>`;
            }
            const balCls = m.latest_balance == null ? ' empty' : '';
            const memberStr = m.member_number ? escapeHtml(m.member_number) : '&mdash;';
            const memberTitle = m.member_number ? ` title="${escapeHtml(m.member_number)}"` : '';
            return `
                <div class="sb-card-row cols-4">
                    <span class="who">${escapeHtml(person.name)}<small>${escapeHtml(AirlineMilesPage._personRoleLabel(person))}</small></span>
                    <span class="num"${memberTitle}>${memberStr}</span>
                    <span class="bal${balCls}">${AirlineMilesPage._fmt(m.latest_balance)}</span>
                    <button class="btn btn-sm btn-secondary" type="button"
                            onclick="AirlineMilesPage.openUpdate(${m.id})">Update</button>
                </div>`;
        }).join('');

        // Pull airline name out of the programme name where possible
        // ("American AAdvantage" → ["American", "AAdvantage"]); falls
        // back to the full name in the stub class slot.
        const parts = (prog.name || '').split(' ');
        const airlineName = parts.length > 1 ? parts.slice(0, -1).join(' ') : (prog.name || '');
        const programName = parts.length > 1 ? parts[parts.length - 1] : '';

        return `
            <article class="sb-card" style="${accentStyle}">
                <span class="sb-notch-top"></span>
                <span class="sb-notch-bot"></span>
                <div class="sb-card-stub">
                    ${tile}
                    <div>
                        <div class="sb-card-class">${escapeHtml(airlineName)}</div>
                        <div class="sb-card-name">${escapeHtml(programName)}</div>
                    </div>
                    <div class="sb-card-meta">
                        <div class="lbl">Programme balance</div>
                        <div class="val">${AirlineMilesPage._fmt(total)}<span>PTS</span></div>
                    </div>
                </div>
                <div class="sb-card-body">${memberRows}</div>
            </article>
        `;
    },

    // ----------------------------------------------------------------
    // Person card (one household member, lists their programmes)
    // ----------------------------------------------------------------
    _personCard(person) {
        // Programmes where this person already has a membership land
        // on top, sorted by latest balance desc; placeholders for
        // programmes they haven't joined sit underneath.
        const enrolled = [];
        const unenrolled = [];
        for (const prog of AirlineMilesPage._programs) {
            const m = AirlineMilesPage._membershipFor(prog, person.id);
            if (m) enrolled.push({ prog, m });
            else   unenrolled.push({ prog, m: null });
        }
        enrolled.sort(
            (a, b) => (b.m.latest_balance || 0) - (a.m.latest_balance || 0)
        );
        const ordered = [...enrolled, ...unenrolled];
        const total = enrolled.reduce(
            (s, e) => s + (e.m.latest_balance || 0), 0
        );

        const rows = ordered.map(({ prog, m }) => {
            const logoUrl = AirlineMilesPage._logoUrl(prog);
            const tile = logoUrl
                ? `<div class="pmono"><img src="${logoUrl}" alt=""></div>`
                : `<div class="pmono letter">${escapeHtml((prog.name || '?').charAt(0).toUpperCase())}</div>`;

            const parts = (prog.name || '').split(' ');
            const airlineName = parts.length > 1 ? parts.slice(0, -1).join(' ') : (prog.name || '');
            const programName = parts.length > 1 ? parts[parts.length - 1] : '';

            if (!m) {
                return `
                    <div class="sb-prow">
                        ${tile}
                        <div class="pname">${escapeHtml(programName || airlineName)}<small>${escapeHtml(airlineName)}</small></div>
                        <div class="pmember muted">&mdash;</div>
                        <div class="pbal empty">&mdash;</div>
                        <button class="btn btn-sm btn-secondary" type="button"
                                onclick="AirlineMilesPage.addMembership(${prog.id}, ${person.id})">Add</button>
                    </div>`;
            }
            const balCls = m.latest_balance == null ? ' empty' : '';
            const memberTitle = m.member_number ? ` title="${escapeHtml(m.member_number)}"` : '';
            return `
                <div class="sb-prow">
                    ${tile}
                    <div class="pname">${escapeHtml(programName || airlineName)}<small>${escapeHtml(airlineName)}</small></div>
                    <div class="pmember"${memberTitle}>${m.member_number ? escapeHtml(m.member_number) : '&mdash;'}</div>
                    <div class="pbal${balCls}">${AirlineMilesPage._fmt(m.latest_balance)}</div>
                    <button class="btn btn-sm btn-secondary" type="button"
                            onclick="AirlineMilesPage.openUpdate(${m.id})">Update</button>
                </div>`;
        }).join('');

        return `
            <article class="sb-pcard">
                <div class="sb-pstub">
                    <div>
                        <div class="role">${escapeHtml(AirlineMilesPage._personRoleLabel(person))}</div>
                        <div class="name">${escapeHtml(person.name)}</div>
                    </div>
                    <div class="meta">
                        <div class="lbl">Total across programmes</div>
                        <div class="val">${AirlineMilesPage._fmt(total)}<span>PTS</span></div>
                    </div>
                </div>
                <div class="sb-pbody">${rows}</div>
            </article>
        `;
    },

    // ----------------------------------------------------------------
    // Page shell
    // ----------------------------------------------------------------
    _body() {
        const view = AirlineMilesPage._state.view;
        const cards = view === 'program'
            ? AirlineMilesPage._programs.map(p => AirlineMilesPage._programCard(p)).join('')
            : AirlineMilesPage._people.map(p => AirlineMilesPage._personCard(p)).join('');

        const empty = AirlineMilesPage._programs.length === 0
            ? `<div class="empty-state"><p>No airline programmes yet.</p></div>`
            : '';

        return `
            <div id="miles-root">
                <header class="sb-head">
                    <div class="sb-crumb">Travel &middot; Loyalty</div>
                    <h1>Airline Miles</h1>
                    <div class="sb-sub">
                        ${AirlineMilesPage._programs.length} programme${AirlineMilesPage._programs.length === 1 ? '' : 's'}
                        &middot;
                        ${AirlineMilesPage._people.length} member${AirlineMilesPage._people.length === 1 ? '' : 's'}
                    </div>
                </header>
                <div class="sb-segs">
                    <button type="button" class="sb-pill${view === 'program' ? ' on' : ''}"
                            onclick="AirlineMilesPage.setView('program')">By programme</button>
                    <button type="button" class="sb-pill${view === 'person' ? ' on' : ''}"
                            onclick="AirlineMilesPage.setView('person')">By person</button>
                    <span class="sb-grow"></span>
                </div>
                <div class="sb-grid${view === 'person' ? ' cols-1' : ''}">${cards}</div>
                ${empty}
            </div>
        `;
    },

    // ----------------------------------------------------------------
    // Update-balance modal — same backend as the previous design.
    // ----------------------------------------------------------------
    openUpdate(membershipId) {
        const today = todayISO();
        const html = `
            <form id="miles-update-form" onsubmit="AirlineMilesPage.saveSnapshot(event, ${membershipId})">
                <div class="form-group">
                    <label>Balance *</label>
                    <input name="balance" type="number" min="0" step="1" required autofocus>
                </div>
                <div class="form-group">
                    <label>As-of Date *</label>
                    <input name="as_of_date" type="date" required value="${today}">
                </div>
                <div class="form-group">
                    <label>Notes</label>
                    <input name="notes" type="text" maxlength="200">
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
                <div style="font-size:10px; color:var(--ink-3); margin-top:6px;">
                    Re-entering the same date overwrites the previous balance.
                </div>
            </form>
        `;
        openModal('Update balance', html);
    },

    async saveSnapshot(e, membershipId) {
        e.preventDefault();
        const form = e.target;
        const data = Object.fromEntries(new FormData(form).entries());
        const payload = {
            membership_id: membershipId,
            as_of_date: data.as_of_date,
            balance: parseInt(data.balance, 10),
        };
        if (data.notes) payload.notes = data.notes;
        try {
            await API.post('/airline-miles/snapshots', payload);
            toast('Balance updated');
            closeModal();
            const html = await AirlineMilesPage.render();
            document.getElementById('page-content').innerHTML = html;
        } catch (err) {
            toast(err.message || 'Save failed', 'error');
        }
    },

    async addMembership(programId, personId) {
        try {
            await API.post('/airline-miles/memberships', {
                program_id: programId,
                person_id: personId,
            });
            toast('Membership added');
            const html = await AirlineMilesPage.render();
            document.getElementById('page-content').innerHTML = html;
        } catch (err) {
            toast(err.message || 'Add failed', 'error');
        }
    },
};
