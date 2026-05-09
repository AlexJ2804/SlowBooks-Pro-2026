/**
 * Airline Miles — household loyalty-programme tracker.
 *
 * Visual design: "Cabin Pass" — boarding-pass card geometry (perforated stub +
 * body, ticket-stub member numbers in JetBrains Mono) in the cabin palette.
 * Real airline logos sit on a white tile inside each tinted stub.
 *
 * Styles live in /static/css/components.css (`.sb-card`, `.sb-card-stub`,
 * `.sb-card-body`, `.sb-card-row`, `.sb-pcard`, `.sb-prow`). This module only
 * builds DOM and passes per-airline accents in via inline custom properties.
 */
const AirlineMilesPage = {
    PEOPLE: [
        { id: 'alex',     name: 'Alex',     role: 'Primary' },
        { id: 'alexa',    name: 'Alexa',    role: 'Spouse'  },
        { id: 'theodore', name: 'Theodore', role: 'Child'   },
    ],

    PROGRAMS: [
        {
            id: 'aa',
            airline: 'American Airlines',
            program: 'AAdvantage',
            logo: '/static/airline_logos/aadvantage.jpeg',
            accent: '#c8102e',
            accentSoft: '#FBE5E8',
            balances: {
                alex:     { member: '1TU70K8',  balance: 18730, asOf: 'May 8, 2026' },
                alexa:    { member: null,       balance: null,  asOf: null },
                theodore: { member: null,       balance: null,  asOf: null },
            },
        },
        {
            id: 'dl',
            airline: 'Delta Air Lines',
            program: 'SkyMiles',
            logo: '/static/airline_logos/skymiles.png',
            accent: '#003366',
            accentSoft: '#DDE5EE',
            balances: {
                alex:     { member: '9283122365', balance: 57670, asOf: 'May 8, 2026' },
                alexa:    { member: null,         balance: null,  asOf: null },
                theodore: { member: null,         balance: null,  asOf: null },
            },
        },
        {
            id: 'ua',
            airline: 'United Airlines',
            program: 'MileagePlus',
            logo: '/static/airline_logos/mileageplus.png',
            accent: '#002244',
            accentSoft: '#DCE2EC',
            balances: {
                alex:     { member: 'UF461456', balance: 10304, asOf: 'May 8, 2026' },
                alexa:    { member: null,       balance: null,  asOf: null },
                theodore: { member: null,       balance: null,  asOf: null },
            },
        },
        {
            id: 'ei',
            airline: 'Aer Lingus',
            program: 'AerClub',
            logo: '/static/airline_logos/aerclub.jpg',
            accent: '#00754a',
            accentSoft: '#DCEBE2',
            balances: {
                alex:     { member: 'alexj2804', balance: 5446, asOf: 'May 8, 2026' },
                alexa:    { member: null,        balance: null, asOf: null },
                theodore: { member: null,        balance: null, asOf: null },
            },
        },
        {
            id: 'ac',
            airline: 'Air Canada',
            program: 'Aeroplan',
            logo: '/static/airline_logos/aeroplan.png',
            accent: '#d22630',
            accentSoft: '#FBE2E4',
            balances: {
                alex:     { member: '370845117', balance: 4, asOf: 'May 8, 2026' },
                alexa:    { member: null,        balance: null, asOf: null },
                theodore: { member: null,        balance: null, asOf: null },
            },
        },
    ],

    state: { view: 'program' },

    fmt(n) { return n == null ? '&mdash;' : n.toLocaleString('en-US'); },

    setView(view) {
        AirlineMilesPage.state.view = view;
        const root = document.getElementById('miles-root');
        if (root) root.outerHTML = AirlineMilesPage.body();
    },

    programCard(p) {
        const total = Object.values(p.balances).reduce((s, b) => s + (b.balance || 0), 0);
        const rows = AirlineMilesPage.PEOPLE.map(person => {
            const b = p.balances[person.id];
            const empty = b.balance == null;
            return `
                <div class="sb-card-row cols-4">
                    <span class="who">${escapeHtml(person.name)}<small>${escapeHtml(person.role)}</small></span>
                    <span class="num">${b.member ? escapeHtml(b.member) : '&mdash;'}</span>
                    <span class="bal${empty ? ' empty' : ''}">${AirlineMilesPage.fmt(b.balance)}</span>
                    <button class="btn btn-sm btn-secondary" type="button">Update</button>
                </div>`;
        }).join('');

        return `
            <article class="sb-card" style="--accent:${p.accent};--accent-soft:${p.accentSoft};">
                <span class="sb-notch-top"></span>
                <span class="sb-notch-bot"></span>
                <div class="sb-card-stub">
                    <div class="sb-card-tile">
                        <img src="${p.logo}" alt="${escapeHtml(p.airline)} ${escapeHtml(p.program)}">
                    </div>
                    <div>
                        <div class="sb-card-class">${escapeHtml(p.airline)}</div>
                        <div class="sb-card-name">${escapeHtml(p.program)}</div>
                    </div>
                    <div class="sb-card-meta">
                        <div class="lbl">Programme balance</div>
                        <div class="val">${AirlineMilesPage.fmt(total)}<span>PTS</span></div>
                    </div>
                </div>
                <div class="sb-card-body">${rows}</div>
            </article>`;
    },

    personCard(person) {
        const total = AirlineMilesPage.PROGRAMS.reduce(
            (s, p) => s + (p.balances[person.id].balance || 0), 0
        );
        const programsWith    = AirlineMilesPage.PROGRAMS.filter(p => p.balances[person.id].balance != null);
        const programsWithout = AirlineMilesPage.PROGRAMS.filter(p => p.balances[person.id].balance == null);
        const ordered = [...programsWith, ...programsWithout];

        const rows = ordered.map(p => {
            const b = p.balances[person.id];
            const empty = b.balance == null;
            return `
                <div class="sb-prow">
                    <div class="pmono"><img src="${p.logo}" alt=""></div>
                    <div class="pname">${escapeHtml(p.program)}<small>${escapeHtml(p.airline)}</small></div>
                    <div class="pmember">${b.member ? escapeHtml(b.member) : '&mdash;'}</div>
                    <div class="pbal${empty ? ' empty' : ''}">${AirlineMilesPage.fmt(b.balance)}</div>
                    <button class="btn btn-sm btn-secondary" type="button">Update</button>
                </div>`;
        }).join('');

        return `
            <article class="sb-pcard">
                <div class="sb-pstub">
                    <div>
                        <div class="role">${escapeHtml(person.role)}</div>
                        <div class="name">${escapeHtml(person.name)}</div>
                    </div>
                    <div class="meta">
                        <div class="lbl">Total across programmes</div>
                        <div class="val">${AirlineMilesPage.fmt(total)}<span>PTS</span></div>
                    </div>
                </div>
                <div class="sb-pbody">${rows}</div>
            </article>`;
    },

    body() {
        const view = AirlineMilesPage.state.view;
        const cards = view === 'program'
            ? AirlineMilesPage.PROGRAMS.map(AirlineMilesPage.programCard).join('')
            : AirlineMilesPage.PEOPLE.map(AirlineMilesPage.personCard).join('');

        return `
            <div id="miles-root">
                <header class="sb-head">
                    <div class="sb-crumb">Travel &middot; Loyalty</div>
                    <h1>Airline Miles</h1>
                    <div class="sb-sub">${AirlineMilesPage.PROGRAMS.length} programmes &middot; ${AirlineMilesPage.PEOPLE.length} members</div>
                </header>
                <div class="sb-segs">
                    <button type="button" class="sb-pill${view === 'program' ? ' on' : ''}"
                        onclick="AirlineMilesPage.setView('program')">By programme</button>
                    <button type="button" class="sb-pill${view === 'person' ? ' on' : ''}"
                        onclick="AirlineMilesPage.setView('person')">By person</button>
                    <button type="button" class="sb-pill sb-grow">Sort: Balance &darr;</button>
                    <button type="button" class="sb-pill primary">+ Add programme</button>
                </div>
                <div class="sb-grid${view === 'person' ? ' cols-1' : ''}">${cards}</div>
            </div>`;
    },

    render() {
        return AirlineMilesPage.body();
    },
};
