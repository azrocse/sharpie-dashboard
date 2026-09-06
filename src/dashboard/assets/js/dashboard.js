let PICKS = [];

// Reloj en tiempo real
function startRealtimeClock() {
    const clockEl = document.getElementById("clock");
    function updateClock() {
        if (!clockEl) return;
        const now = new Date();
        const hrs = String(now.getHours()).padStart(2, '0');
        const mins = String(now.getMinutes()).padStart(2, '0');
        const secs = String(now.getSeconds()).padStart(2, '0');
        clockEl.innerText = `${hrs}:${mins}:${secs}`;
    }
    updateClock();
    setInterval(updateClock, 1000);
}

// Función para sanitizar HTML y prevenir fallas o XSS
function escapeHTML(str) {
    return String(str || '').replace(/[&<>"']/g, function(m) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m];
    });
}

// Función híbrida para obtener los datos
async function loadData() {
    if (Array.isArray(window.SHARPIE_PICKS)) {
        PICKS = window.SHARPIE_PICKS;
        return;
    } 
    if (typeof window.picksData !== "undefined" && Array.isArray(window.picksData)) {
        PICKS = window.picksData;
        return;
    }
    
    try {
        const response = await fetch('picks.json?v=' + Date.now());
        if (response.ok) {
            PICKS = await response.json();
        }
    } catch (e) {
        console.warn("Carga externa vía fetch omitida o fallida:", e);
    }
}

// Auto-refresh: revisa picks.json cada 60s y actualiza el dashboard solo si
// hay datos nuevos -- sin recargar la página (no pierde filtros ni scroll).
// Si el archivo se abre como file:// local (sin servidor), el fetch falla y
// simplemente no hace nada -- el resto del dashboard sigue funcionando igual.
let RECENTLY_ADDED_IDS = new Set();
let RECENTLY_UPDATED_IDS = new Set();
let ACTIVE_FILTER_MATCH_KEYS = new Set();

async function checkForNewPicks() {
    try {
        const response = await fetch('picks.json?v=' + Date.now(), { cache: 'no-store' });
        if (!response.ok) return;

        const freshData = await response.json();
        if (!Array.isArray(freshData)) return;

        const changed = JSON.stringify(freshData) !== JSON.stringify(PICKS);
        if (!changed) return;

        const oldByKey = new Map(PICKS.map(p => [getWatchlistId(p), p]));
        const newKeys = new Set(freshData.map(getWatchlistId));
        const addedKeys = [...newKeys].filter(k => !oldByKey.has(k));
        const removedCount = [...oldByKey.keys()].filter(k => !newKeys.has(k)).length;

        // Picks que YA existían pero cambiaron de valor (Bets/Handle/Cuota/Stake/etc)
        const updatedKeys = freshData
            .filter(p => {
                const key = getWatchlistId(p);
                const prev = oldByKey.get(key);
                return prev && JSON.stringify(prev) !== JSON.stringify(p);
            })
            .map(getWatchlistId);

        // Comprobación de filtro activo: si el usuario dejó un filtro puesto
        // (ej. Hora/Rango: próxima 1h, Cuota>-150, Edge>1.5, EV>2.0), se
        // revisa en cada refresh qué picks entran o salen de ese filtro
        // específico -- aviso aparte del genérico de arriba. El snapshot
        // "antes" se toma justo antes de renderizar (render() resincroniza
        // ACTIVE_FILTER_MATCH_KEYS siempre, incluso si el usuario cambió el
        // filtro a mano entre revisiones).
        const beforeMatchKeys = new Set(ACTIVE_FILTER_MATCH_KEYS);

        PICKS = freshData;
        RECENTLY_ADDED_IDS = new Set(addedKeys);
        RECENTLY_UPDATED_IDS = new Set(updatedKeys);
        populateSelectOptions();
        render();

        // La hora de "Última actualización" del header estaba horneada al
        // generar el HTML y nunca se movía aunque el polling trajera datos
        // nuevos -- ahora se refresca cada vez que se detecta un cambio real.
        const generatedAtEl = document.getElementById("generatedAtVal");
        if (generatedAtEl) {
            const now = new Date();
            const pad = (n) => String(n).padStart(2, '0');
            generatedAtEl.textContent = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
        }

        const parts = [];
        if (addedKeys.length > 0) parts.push(`${addedKeys.length} nuevo(s)`);
        if (updatedKeys.length > 0) parts.push(`${updatedKeys.length} actualizado(s)`);
        if (removedCount > 0) parts.push(`${removedCount} finalizado(s)/fuera de tiempo`);
        showAttractiveNotification({
            title: "🔄 Dashboard actualizado",
            body: parts.length > 0 ? parts.join(" · ") : "Los datos se actualizaron",
            variant: "success"
        });

        // Badges temporales (NUEVO / ACTUALIZADO) se limpian solos a los 3 min
        if (addedKeys.length > 0 || updatedKeys.length > 0) {
            setTimeout(() => { RECENTLY_ADDED_IDS.clear(); RECENTLY_UPDATED_IDS.clear(); render(); }, 180000);
        }

        // Comprobación de filtro activo: si el usuario dejó un filtro puesto
        // (ej. Hora/Rango: próxima 1h, Cuota>-150, Edge>1.5, EV>2.0), se
        // revisa en cada refresh qué picks entran o salen de ese filtro
        // específico -- aviso aparte del genérico de arriba.
        if (isAnyFilterActive() && beforeMatchKeys.size > 0) {
            const matchingKeys = new Set(ACTIVE_FILTER_MATCH_KEYS);
            const enteredCount = [...matchingKeys].filter(k => !beforeMatchKeys.has(k)).length;
            const exitedCount = [...beforeMatchKeys].filter(k => !matchingKeys.has(k)).length;

            if (enteredCount > 0 || exitedCount > 0) {
                const fparts = [];
                if (enteredCount > 0) fparts.push(`${enteredCount} nuevo(s) cumplen`);
                if (exitedCount > 0) fparts.push(`${exitedCount} ya no cumplen`);
                showAttractiveNotification({
                    title: "🎯 Tu filtro activo cambió",
                    body: fparts.join(" · "),
                    variant: "info"
                });
            }
        }

        // El badge "NUEVO" se muestra 3 min y luego se limpia solo
        if (addedKeys.length > 0) {
            setTimeout(() => { RECENTLY_ADDED_IDS.clear(); render(); }, 180000);
        }
    } catch (e) {
        // picks.json no accesible (ej. archivo local sin servidor) -- se omite en silencio
    }
}

function startAutoRefresh() {
    setInterval(checkForNewPicks, 90000); // cada 90s -- proporcional al ciclo de 5 min del scraper
}

const state = {
    search: "",
    date: "",
    league: "",
    trend: "",
    featuredOnly: false,
    freeReleaseOnly: false,
    watchlistOnly: false,
    showFullMarket: false,
    sort: "time",
    autoThemeEnabled: true,
    advancedView: false,  // Arranca en Simple -- el botón siempre muestra el modo AL QUE CAMBIAS, no el actual
    
    timeRange: "",
    modeloMin: null,
    modeloMax: null,
    cuotaMin: null,
    cuotaMax: null,
    edgeMin: null,
    edgeMax: null,
    betsMin: null,
    betsMax: null,
    handleMin: null,
    handleMax: null,
    evMin: null,
    evMax: null,
    stakeMin: null,
    stakeMax: null,
    divergenciaMin: null,
    divergenciaMax: null,
    recommendation: ""
};

function isAnyFilterActive() {
    const s = state;
    const numericKeys = [
        "modeloMin","modeloMax","cuotaMin","cuotaMax","edgeMin","edgeMax",
        "betsMin","betsMax","handleMin","handleMax",
        "evMin","evMax","stakeMin","stakeMax","divergenciaMin","divergenciaMax",
    ];
    if (numericKeys.some(k => s[k] !== null && s[k] !== undefined)) return true;
    if (s.search || s.date || s.league || s.trend || s.timeRange || s.recommendation) return true;
    if (s.featuredOnly || s.freeReleaseOnly || s.watchlistOnly) return true;
    return false;
}

// ============ FILTROS GUARDADOS (localStorage) ============
const FILTER_KEYS = [
    "search", "date", "league", "trend", "timeRange", "recommendation",
    "featuredOnly", "freeReleaseOnly", "watchlistOnly",
    "modeloMin", "modeloMax", "cuotaMin", "cuotaMax", "edgeMin", "edgeMax",
    "betsMin", "betsMax", "handleMin", "handleMax",
    "evMin", "evMax", "stakeMin", "stakeMax", "divergenciaMin", "divergenciaMax",
];
const SAVED_FILTERS_KEY = "sharpie_saved_filters_v1";

function loadSavedFilters() {
    try { return JSON.parse(localStorage.getItem(SAVED_FILTERS_KEY)) || []; }
    catch (e) { return []; }
}

function saveSavedFilters(list) {
    try { localStorage.setItem(SAVED_FILTERS_KEY, JSON.stringify(list)); }
    catch (e) { console.error("Error al guardar filtros:", e); }
}

function saveCurrentFilterPreset() {
    if (!isAnyFilterActive()) {
        showAttractiveNotification({ title: "⚠️ Sin filtros activos", body: "Aplica al menos un filtro antes de guardarlo.", variant: "info" });
        return;
    }
    const name = prompt("Nombre para este filtro:");
    if (!name || !name.trim()) return;

    const snapshot = {};
    FILTER_KEYS.forEach(k => { snapshot[k] = state[k]; });

    const list = loadSavedFilters();
    list.push({ id: Date.now().toString(36), name: name.trim(), filters: snapshot });
    saveSavedFilters(list);
    renderSavedFilterChips();
    showAttractiveNotification({ title: "💾 Filtro guardado", body: name.trim(), variant: "success" });
}

function syncFilterInputsFromState() {
    const idMap = {
        search: "search", date: "fDate", league: "fLeague", trend: "fTrend", timeRange: "fTimeRange",
        modeloMin: "fModeloMin", modeloMax: "fModeloMax", cuotaMin: "fCuotaMin", cuotaMax: "fCuotaMax",
        edgeMin: "fEdgeMin", edgeMax: "fEdgeMax", betsMin: "fBetsMin", betsMax: "fBetsMax",
        handleMin: "fHandleMin", handleMax: "fHandleMax",
        evMin: "fEvMin", evMax: "fEvMax", stakeMin: "fStakeMin", stakeMax: "fStakeMax",
        divergenciaMin: "fDivergenciaMin", divergenciaMax: "fDivergenciaMax"
    };
    Object.keys(idMap).forEach(key => {
        const el = document.getElementById(idMap[key]);
        if (!el) return;
        const val = state[key];
        el.value = (val === null || val === undefined) ? "" : val;
    });

    const featuredBtn = document.getElementById("featuredOnly");
    const freeReleaseBtn = document.getElementById("freeReleaseOnly");
    const watchlistBtn = document.getElementById("watchlistOnly");
    const fullMarketBtn = document.getElementById("fullMarketToggle");
    if (featuredBtn) featuredBtn.setAttribute("aria-pressed", String(state.featuredOnly));
    if (freeReleaseBtn) freeReleaseBtn.setAttribute("aria-pressed", String(state.freeReleaseOnly));
    if (watchlistBtn) watchlistBtn.setAttribute("aria-pressed", String(state.watchlistOnly));
    if (fullMarketBtn) {
        fullMarketBtn.setAttribute("aria-pressed", String(state.showFullMarket));
        fullMarketBtn.textContent = state.showFullMarket ? "🎯 Mostrar solo apuestas" : "🔎 Mostrar mercado completo";
    }
}

function applyFilterPreset(preset) {
    FILTER_KEYS.forEach(k => {
        const isToggle = ["featuredOnly", "freeReleaseOnly", "watchlistOnly"].includes(k);
        const defaultVal = isToggle ? false : (typeof state[k] === "string" ? "" : null);
        state[k] = (preset.filters[k] !== undefined) ? preset.filters[k] : defaultVal;
    });
    syncFilterInputsFromState();
    render();
    showAttractiveNotification({ title: "🎯 Filtro aplicado", body: preset.name, variant: "info" });
}

function deleteFilterPreset(id) {
    saveSavedFilters(loadSavedFilters().filter(p => p.id !== id));
    renderSavedFilterChips();
}

function renderSavedFilterChips() {
    const container = document.getElementById("savedFiltersRow");
    if (!container) return;
    const list = loadSavedFilters();

    if (list.length === 0) {
        container.style.display = "none";
        container.innerHTML = "";
        return;
    }

    container.style.display = "flex";
    container.innerHTML = list.map(p => `
        <span class="saved-filter-chip">
            <button type="button" class="saved-filter-apply" data-id="${p.id}">🎯 ${escapeHTML(p.name)}</button>
            <button type="button" class="saved-filter-delete" data-id="${p.id}" aria-label="Eliminar filtro guardado">✕</button>
        </span>
    `).join("");

    container.querySelectorAll(".saved-filter-apply").forEach(btn => {
        btn.addEventListener("click", () => {
            const preset = list.find(p => p.id === btn.dataset.id);
            if (preset) applyFilterPreset(preset);
        });
    });
    container.querySelectorAll(".saved-filter-delete").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            deleteFilterPreset(btn.dataset.id);
        });
    });
}

// Catálogo exclusivo calculado en analyze.py; el frontend solo presenta.
const TREND_LABEL = {
    STEAM_MOVE: "STEAM MOVE",
    REVERSE_LINE_MOVEMENT: "REVERSE LINE MOVEMENT",
    SMART_MONEY: "SMART MONEY",
    PUBLIC_HEAVY: "PUBLIC HEAVY",
    CONSENSUS: "CONSENSUS",
    SHARP_VS_PUBLIC: "SHARP VS PUBLIC",
    BALANCED_ACTION: "BALANCED ACTION",
    LOW_LIQUIDITY: "LOW LIQUIDITY",
    NO_ACTION: "NO ACTION"
};
const TREND_ICON = {
    STEAM_MOVE: "💨",
    REVERSE_LINE_MOVEMENT: "↩️",
    SMART_MONEY: "🐋",
    PUBLIC_HEAVY: "🚨",
    CONSENSUS: "📊",
    SHARP_VS_PUBLIC: "⚔️",
    BALANCED_ACTION: "⚖️",
    LOW_LIQUIDITY: "💧",
    NO_ACTION: "⚪"
};
const MARKET_SIGNAL_KEYS = Object.keys(TREND_LABEL);
const MARKET_SIGNAL_COLORS = {
    STEAM_MOVE: '#06b6d4',
    REVERSE_LINE_MOVEMENT: '#8b5cf6',
    SMART_MONEY: '#2563eb',
    PUBLIC_HEAVY: '#fb7185',
    CONSENSUS: '#2dd4bf',
    SHARP_VS_PUBLIC: '#f59e0b',
    BALANCED_ACTION: '#64748b',
    LOW_LIQUIDITY: '#38bdf8',
    NO_ACTION: '#94a3b8'
};

let edgeChartInstance = null;
let marketChartInstance = null;

function initCharts() {
    if (typeof Chart === "undefined") return;
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    const textColor = isDark ? "#94a3b8" : "#64748b";
    const gridColor = isDark ? "#243572" : "#e2e8f0";

    const ctxScatter = document.getElementById("edgeScatterChart");
    if (ctxScatter) {
        if (edgeChartInstance) edgeChartInstance.destroy();
        edgeChartInstance = new Chart(ctxScatter, {
            type: 'scatter',
            data: { datasets: [{ label: 'Picks Activos', data: [], backgroundColor: '#2dd4bf', pointRadius: 6 }] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { title: { display: true, text: 'Modelo Prob. (%)', color: textColor }, ticks: { color: textColor }, grid: { color: gridColor } },
                    y: { title: { display: true, text: 'EV (%)', color: textColor }, ticks: { color: textColor }, grid: { color: gridColor } }
                },
                plugins: { legend: { display: false } }
            }
        });
    }

    const ctxDoughnut = document.getElementById("marketDoughnutChart");
    if (ctxDoughnut) {
        if (marketChartInstance) marketChartInstance.destroy();
        marketChartInstance = new Chart(ctxDoughnut, {
            type: 'doughnut',
            data: {
                labels: [],
                datasets: [{ data: [], backgroundColor: [], borderWidth: 0 }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, color: textColor, font: { size: 10 } } } },
                cutout: '70%'
            }
        });
    }
}

// Sincronización exacta de gráfica con conteos de mercado
function updateChartsData(activeList) {
    if (edgeChartInstance) {
        edgeChartInstance.data.datasets[0].data = activeList.map(p => ({ x: p.modelProb || 0, y: Number(p.ev) || 0 }));
        edgeChartInstance.update();
    }

    if (marketChartInstance) {
        const counts = Object.fromEntries(MARKET_SIGNAL_KEYS.map(key => [key, 0]));
        activeList.forEach(p => { counts[classifyMarketBucket(p)]++; });
        const activeKeys = MARKET_SIGNAL_KEYS.filter(key => counts[key] > 0);
        marketChartInstance.data.labels = activeKeys.map(key => TREND_LABEL[key]);
        marketChartInstance.data.datasets[0].data = activeKeys.map(key => counts[key]);
        marketChartInstance.data.datasets[0].backgroundColor = activeKeys.map(key => MARKET_SIGNAL_COLORS[key]);
        marketChartInstance.update();
    }
}

function evBadgeClass(ev) {
    const v = Number(ev || 0);
    if (v >= 6) return "good";
    if (v > 0) return "warn";
    return "bad";
}

function stakeBadgeClass(stake) {
    const s = Number(stake || 0);
    if (s <= 0) return "bad";
    if (s >= 3) return "good";
    if (s >= 1.5) return "warn";
    return "bad";
}

function confidenceBadgeClass(score) {
    const s = Number(score);
    if (isNaN(s)) return "neutral";
    if (s >= 60) return "good";
    if (s >= 40) return "warn";
    return "bad";
}

function modelProbColorClass(prob) {
    const p = Number(prob || 0);
    if (p >= 65) return "var(--teal)";
    if (p >= 50) return "var(--amber)";
    return "var(--text)";
}

function oddsColorClass(odds) {
    const dec = parseOddsToDecimal(odds);
    if (dec >= 2.0) return "var(--teal)";
    if (dec > 0) return "var(--amber)";
    return "var(--text)";
}

function edgeColorClass(edge) {
    const e = Number(edge || 0);
    if (e >= 5) return "var(--teal)";
    if (e > 0) return "var(--amber)";
    return "var(--red)";
}

function modelBadgeClass(prob) {
    const p = Number(prob);
    if (isNaN(p)) return "neutral";
    if (p >= 55) return "good";
    if (p >= 50) return "warn";
    return "bad";
}

function edgeModBadgeClass(edge) {
    const e = Number(edge);
    if (isNaN(e)) return "neutral";
    if (e >= 2) return "good";
    if (e > 0) return "warn";
    return "bad";
}

function oddsBadgeClass(odds) {
    const decimal = parseOddsToDecimal(odds);
    if (!decimal || decimal <= 1) return "bad";
    if (decimal >= 1.70 && decimal <= 2.40) return "good";
    if ((decimal >= 1.50 && decimal < 1.70) || (decimal > 2.40 && decimal <= 3.00)) return "warn";
    return "bad";
}

function divergenceBadgeClass(value) {
    const divergence = Number(value);
    if (divergence >= 15) return "good";
    if (divergence >= 0) return "warn";
    return "bad";
}

// ============================================================
// Panel compacto. No recalcula categorías ni métricas eliminadas.
function unifiedDecisionPanelHtml(p) {
    const displayStake = Number(p.stake) || 0;
    const stakeText = displayStake.toFixed(1) + 'u';

    if (!state.advancedView) {
        // Modo Simple: solo 3 datos -- Modelo, Cuota, Stake.
        const simpleChips = [
            `<span class="badge-tag ${modelBadgeClass(p.modelProb)}">🤖 Modelo <b>${p.modelProb != null ? p.modelProb + '%' : '—'}</b></span>`,
            `<span class="badge-tag ${oddsBadgeClass(p.odds || p.cuota)}">💵 Cuota <b>${escapeHTML(p.odds || p.cuota || '—')}</b></span>`,
            `<span class="badge-tag ${stakeBadgeClass(displayStake)}">🎯 Stake <b>${stakeText}</b></span>`
        ];
        return `<div class="decision-panel"><div class="decision-panel-title">📐 Decisión</div><div class="badge-tag-grid">${simpleChips.join('')}</div></div>`;
    }

    const modelEdgeVal = p.modelEdge != null ? Number(p.modelEdge) : null;
    const smartMoneyVal = calculateSmartMoney(p);

    // Métricas calculadas por la única autoridad matemática: analyze.py.
    const advGrid = [
        `<span class="badge-tag ${modelBadgeClass(p.modelProb)}">🤖 Modelo <b>${p.modelProb != null ? p.modelProb + '%' : '—'}</b></span>`,
        `<span class="badge-tag ${edgeModBadgeClass(modelEdgeVal)}">📈 Edge Modelo <b>${modelEdgeVal != null ? (modelEdgeVal > 0 ? '+' : '') + modelEdgeVal + '%' : '—'}</b></span>`,
        `<span class="badge-tag ${evBadgeClass(p.ev)}">📊 EV <b>${p.ev != null ? p.ev + '%' : '—'}</b></span>`,

        `<span class="badge-tag ${oddsBadgeClass(p.odds || p.cuota)}">💵 Cuota <b>${escapeHTML(p.odds || p.cuota || '—')}</b></span>`,
        `<span class="badge-tag ${stakeBadgeClass(displayStake)}">🎯 Stake <b>${stakeText}</b></span>`,
        `<span class="badge-tag ${divergenceBadgeClass(smartMoneyVal)}">⚡ Divergencia <b>${smartMoneyVal > 0 ? '+' : ''}${smartMoneyVal}%</b></span>`
    ];

    return `<div class="decision-panel"><div class="decision-panel-title">📐 Panel de Decisión (Avanzado)</div><div class="badge-tag-grid-3x3">${advGrid.join('')}</div></div>`;
}

function trendTag(key) { return `${TREND_ICON[key] || "⚙️"} ${TREND_LABEL[key] || "Normal"}`; }

function updateThemeByTime() {
    if (!state.autoThemeEnabled) return; 

    const hour = new Date().getHours();
    const doc = document.documentElement;
    const targetTheme = (hour >= 6 && hour < 19) ? 'light' : 'dark';
    
    if (doc.getAttribute("data-theme") !== targetTheme) {
        doc.setAttribute("data-theme", targetTheme);
        initCharts();
    }
}

function setupThemeToggle() {
    const themeToggle = document.getElementById("themeToggle");
    if (themeToggle) {
        themeToggle.addEventListener("click", () => {
            state.autoThemeEnabled = false; 
            const doc = document.documentElement;
            const currentTheme = doc.getAttribute("data-theme");
            doc.setAttribute("data-theme", currentTheme === "dark" ? "light" : "dark");
            initCharts();
            render();
        });
    }
}

function isEventPending(p) {
    const status = (p.status || "").toUpperCase();
    if (status === "FINISHED" || status === "WON" || status === "LOST" || status === "CANCELLED") return false;

    if (p.iso) {
        const kickoff = new Date(p.iso).getTime();
        if (!isNaN(kickoff)) {
            const minutesSinceKickoff = (Date.now() - kickoff) / 60000;
            if (minutesSinceKickoff > 0) return false;
        }
    }
    return true;
}

function calculateEdge(p) { 
    return p.modelEdge !== undefined && p.modelEdge !== null ? Number(p.modelEdge) : 0;
}

function calculateSmartMoney(p) {
    return p.signedDivergence != null ? Number(p.signedDivergence) : 0;
}

const RECOMMENDED_CATEGORIES = new Set(["VALUE", "PREMIUM"]);

function isRecommendedPick(p) {
    return Boolean(p && p.actionKey === "bet" && RECOMMENDED_CATEGORIES.has(p.pickCategory));
}

// ============================================================
// La categoría viene resuelta por el backend y solo se presenta aquí.

let TOP_PICK_ID = null;

// El KPI y el filtro "Pick Destacado" son conceptos distintos:
// - TOP_PICK_ID: mejor oportunidad operable del momento.
// - MEDIA_TEAM_ALIASES: equipos/selecciones mediáticos que alimentan el filtro.
const MEDIA_TEAM_ALIASES = [
    // Fútbol europeo
    "real madrid", "barcelona", "atletico madrid", "manchester united", "man united",
    "manchester city", "man city", "liverpool", "arsenal", "chelsea", "tottenham",
    "bayern munich", "bayern munchen", "borussia dortmund", "psg", "paris saint germain",
    "juventus", "inter milan", "internazionale", "ac milan", "napoli", "roma", "lazio",
    "benfica", "porto", "sporting lisbon", "sporting cp", "ajax", "psv", "feyenoord",
    "celtic", "rangers", "galatasaray", "fenerbahce", "besiktas",
    // América y otras regiones
    "america", "club america", "chivas", "guadalajara", "cruz azul", "pumas",
    "tigres", "monterrey", "rayados", "boca juniors", "river plate", "flamengo",
    "palmeiras", "corinthians", "sao paulo", "santos", "gremio", "internacional",
    "inter miami", "la galaxy", "al nassr", "al hilal",
    // Selecciones
    "mexico", "argentina", "brazil", "brasil", "spain", "espana", "france", "francia",
    "england", "inglaterra", "germany", "alemania", "italy", "italia", "portugal",
    "netherlands", "paises bajos", "uruguay", "colombia", "united states", "usa",
    // NBA / WNBA
    "lakers", "celtics", "warriors", "bulls", "knicks", "nets", "heat", "mavericks",
    "spurs", "suns", "bucks", "nuggets", "clippers", "76ers", "liberty", "aces",
    // NFL
    "cowboys", "chiefs", "patriots", "packers", "49ers", "steelers", "eagles",
    "giants", "raiders", "broncos", "dolphins", "bills", "ravens", "rams",
    // MLB / NHL
    "yankees", "dodgers", "red sox", "cubs", "mets", "braves", "astros", "phillies",
    "cardinals", "blue jays", "maple leafs", "canadiens", "bruins", "blackhawks",
    "red wings", "penguins", "oilers", "golden knights"
];

function normalizeMediaText(value) {
    return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function isMediaFeaturedPick(p) {
    const source = normalizeMediaText([p.game, p.away, p.home, p.pick].filter(Boolean).join(" | "));
    return MEDIA_TEAM_ALIASES.some(alias => source.includes(normalizeMediaText(alias)));
}

function topPickRank(p) {
    if (!isRecommendedPick(p)) return -Infinity;
    const categoryWeight = { PREMIUM: 3000, VALUE: 1500 }[p.pickCategory] || 0;
    const signals = new Set(Array.isArray(p.marketSignals) ? p.marketSignals : [p.marketSignal]);
    const signalWeight =
        (signals.has("REVERSE_LINE_MOVEMENT") ? 600 : 0) +
        (signals.has("STEAM_MOVE") ? 500 : 0) +
        (signals.has("SMART_MONEY") ? 400 : 0) +
        (signals.has("SHARP_VS_PUBLIC") ? 250 : 0) +
        (signals.has("CONSENSUS") ? 100 : 0);
    const minutes = p.iso ? (new Date(p.iso) - new Date()) / 60000 : Infinity;
    const urgencyWeight = minutes >= 0 && minutes <= 120 ? 50 : 0;
    return categoryWeight + signalWeight + Number(p.confidenceScore || 0) * 20 + Math.min(Number(p.ev || 0), 10) * 5 + calculateEdge(p) * 5 + Number(p.stake || 0) * 20 + urgencyWeight;
}

function selectTopPick(picks) {
    return [...picks].filter(isRecommendedPick).sort((a, b) => topPickRank(b) - topPickRank(a))[0] || null;
}

function isTopPick(p) {
    return TOP_PICK_ID !== null && getWatchlistId(p) === TOP_PICK_ID;
}

// Devuelve únicamente las mediciones donde Bets, Handle o Cuota realmente cambiaron
// respecto a la medición anterior. Fuente única usada tanto por la Evolución Histórica
// como por el Análisis Destacado, para que ninguna de las dos repita mediciones idénticas.
function getChangedHistoryEntries(p) {
    const rawHistory = Array.isArray(p.history) ? p.history.filter(h =>
        h && (h.betsPct != null || h.handlePct != null || h.odds != null)
    ) : [];
    if (rawHistory.length === 0) return [];

    const hasOdds = rawHistory.some(h => h.odds != null && h.odds !== '');

    return rawHistory.filter((h, i) => {
        if (i === 0) return true;
        const prev = rawHistory[i - 1];
        const betsChanged = h.betsPct !== prev.betsPct;
        const handleChanged = h.handlePct !== prev.handlePct;
        const oddsChanged = hasOdds && h.odds !== prev.odds;
        return betsChanged || handleChanged || oddsChanged;
    });
}

// Parámetros de análisis de evolución para destacar automáticamente los picks.
// Se mantienen separados de los filtros/clasificaciones existentes para no alterar su comportamiento.
function trendArrow(curr, prev) {
    if (curr == null || prev == null || isNaN(curr) || isNaN(prev)) return { arrow: '', cls: '' };
    const c = parseFloat(curr), pv = parseFloat(prev);
    if (c > pv) return { arrow: '▲', cls: 'evo-up' };
    if (c < pv) return { arrow: '▼', cls: 'evo-down' };
    return { arrow: '—', cls: 'evo-flat' };
}

const HISTORY_ROWS_CACHE = {};

function historyDateTimeParts(point) {
    const source = point.timestamp || point.time || '';
    if (String(source).includes('T')) {
        const parsed = new Date(source);
        if (!isNaN(parsed.getTime())) {
            return {
                date: parsed.toLocaleDateString('sv-SE', { year: 'numeric', month: '2-digit', day: '2-digit' }),
                time: parsed.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit', hour12: false })
            };
        }
    }
    return {
        date: point.timestamp ? String(point.timestamp).split('T')[0] : '—',
        time: /^\d{1,2}:\d{2}/.test(String(point.time || '')) ? String(point.time).slice(0, 5) : '—'
    };
}

function buildHistoryRows(list, hasOdds) {
    let rows = '';
    list.forEach((h, i) => {
        const prev = i > 0 ? list[i - 1] : null;
        const betsTrend = prev ? trendArrow(h.betsPct, prev.betsPct) : { arrow: '', cls: '' };
        const handleTrend = prev ? trendArrow(h.handlePct, prev.handlePct) : { arrow: '', cls: '' };
        const oddsTrend = (prev && hasOdds) ? trendArrow(h.odds, prev.odds) : { arrow: '', cls: '' };
        const when = historyDateTimeParts(h);

        rows += `
            <tr>
                <td><span class="history-cell-icon">📅</span>${escapeHTML(when.date)}</td>
                <td><span class="history-cell-icon">🕒</span>${escapeHTML(when.time)}</td>
                <td>${h.betsPct != null ? h.betsPct + '%' : '—'} <span class="${betsTrend.cls}">${betsTrend.arrow}</span></td>
                <td style="color:var(--teal)">${h.handlePct != null ? h.handlePct + '%' : '—'} <span class="${handleTrend.cls}">${handleTrend.arrow}</span></td>
                ${hasOdds ? `<td>${h.odds != null ? escapeHTML(h.odds) : '—'} <span class="${oddsTrend.cls}">${oddsTrend.arrow}</span></td>` : ''}
            </tr>
        `;
    });
    return rows;
}

function toggleHistoryExpand(uid, total) {
    const tbody = document.getElementById(uid + '_body');
    const btn = document.getElementById(uid + '_btn');
    if (!tbody || !HISTORY_ROWS_CACHE[uid]) return;

    const expanded = tbody.dataset.expanded === '1';
    if (expanded) {
        tbody.innerHTML = HISTORY_ROWS_CACHE[uid].collapsed;
        tbody.dataset.expanded = '0';
        if (btn) btn.textContent = `Ver historial completo (${total})`;
    } else {
        tbody.innerHTML = HISTORY_ROWS_CACHE[uid].full;
        tbody.dataset.expanded = '1';
        if (btn) btn.textContent = 'Ver últimos 5';
    }
}

function buildEvolutionHtml(p) {
    const filteredHistory = getChangedHistoryEntries(p);
    if (filteredHistory.length === 0) return '';

    const hasOdds = filteredHistory.some(h => h.odds != null && h.odds !== '');

    // Por defecto solo los últimos 5 movimientos -- el resto se ve a petición
    // del usuario (botón "Ver historial completo"), para no saturar la card.
    const DEFAULT_VISIBLE = 5;
    const hasMore = filteredHistory.length > DEFAULT_VISIBLE;
    const collapsedHistory = filteredHistory.slice(-DEFAULT_VISIBLE);

    const collapsedRows = buildHistoryRows(collapsedHistory, hasOdds);
    const uid = `hist_${p.id != null ? p.id : Math.random().toString(36).slice(2)}`;

    if (hasMore) {
        HISTORY_ROWS_CACHE[uid] = {
            collapsed: collapsedRows,
            full: buildHistoryRows(filteredHistory, hasOdds)
        };
    }

    return `
        <div class="history-evolution-box">
            <div class="history-evolution-title">📊 Evolución Histórica (Bets / Handle${hasOdds ? ' / Cuota' : ''})</div>
            <table class="history-evolution-table">
                <thead>
                    <tr>
                        <th>Fecha</th>
                        <th>Hora</th>
                        <th>Tickets</th>
                        <th>Dinero</th>
                        ${hasOdds ? '<th>Cuota</th>' : ''}
                    </tr>
                </thead>
                <tbody id="${uid}_body" data-expanded="0">
                    ${collapsedRows}
                </tbody>
            </table>
            ${hasMore ? `<button type="button" class="history-expand-btn" id="${uid}_btn" onclick="toggleHistoryExpand('${uid}', ${filteredHistory.length})">Ver historial completo (${filteredHistory.length})</button>` : ''}
        </div>
    `;
}

// Panel de Decisión unificado (ver unifiedDecisionPanelHtml más abajo) --
// esta versión anterior por secciones ya no se usa, se deja fuera para no
// tener dos fuentes de verdad del mismo panel.

// Presentación de la señal calculada por el backend.
function marketSignalVisualConfig(marketSignal) {
    switch (marketSignal) {
        case "STEAM_MOVE":
            return { bg: "var(--teal-soft)", border: "var(--teal)", text: "var(--teal)", label: "💨 STEAM MOVE" };
        case "REVERSE_LINE_MOVEMENT":
            return { bg: "rgba(139,92,246,.12)", border: "#8b5cf6", text: "#8b5cf6", label: "↩️ REVERSE LINE MOVEMENT" };
        case "SMART_MONEY":
            return { bg: "var(--blue-soft)", border: "var(--blue)", text: "var(--blue)", label: "🐋 SMART MONEY" };
        case "PUBLIC_HEAVY":
            return { bg: "var(--red-soft)", border: "var(--red)", text: "var(--red)", label: "🚨 PUBLIC HEAVY" };
        case "CONSENSUS":
            return { bg: "var(--teal-soft)", border: "var(--teal)", text: "var(--teal)", label: "📊 CONSENSUS" };
        case "SHARP_VS_PUBLIC":
            return { bg: "var(--amber-soft)", border: "var(--amber)", text: "var(--amber)", label: "⚔️ SHARP VS PUBLIC" };
        case "BALANCED_ACTION":
            return { bg: "var(--panel2)", border: "var(--muted)", text: "var(--muted)", label: "⚖️ BALANCED ACTION" };
        case "LOW_LIQUIDITY":
            return { bg: "var(--blue-soft)", border: "#38bdf8", text: "#38bdf8", label: "💧 LOW LIQUIDITY" };
        default:
            return { bg: "var(--panel2)", border: "var(--border)", text: "var(--muted)", label: "⚪ NO ACTION" };
    }
}

function getCountdownText(isoString) {
    if (!isoString) return { text: "--:--:--", urgent: false, expired: false, diffMin: 99999 };
    const diffMs = new Date(isoString) - new Date();
    const diffMin = diffMs / 60000;

    if (diffMs <= 0) return { text: "⚽ EN JUEGO", urgent: true, expired: true, diffMin };
    
    const hrs = Math.floor(diffMs / 3600000);
    const mins = Math.floor((diffMs % 3600000) / 60000);
    const secs = Math.floor((diffMs % 60000) / 1000);
    const pad = (n) => String(n).padStart(2, '0');
    
    let timeStr = "";
    if (hrs > 0) timeStr += `${pad(hrs)}h `;
    timeStr += `${pad(mins)}m ${pad(secs)}s`;
    
    return { text: `⏳ ${timeStr}`, urgent: diffMs < 900000, expired: false, diffMin };
}

// Contador dinámico (Parte 1): tick real cada segundo sobre el DOM, sin
// re-renderizar toda la lista de cards -- solo actualiza el texto/estado de
// cada timer visible ahora mismo.
function tickAllCountdowns() {
    document.querySelectorAll(".countdown-timer[data-iso]").forEach(el => {
        const iso = el.getAttribute("data-iso");
        if (!iso) return;
        const t = getCountdownText(iso);
        el.textContent = t.text;
        el.classList.toggle("urgent", t.urgent);
    });
}

setInterval(tickAllCountdowns, 1000);

const statState = {
    proximos: [],
    mercado: Object.fromEntries(MARKET_SIGNAL_KEYS.map(key => [key, []])),
    mejor: []
};

function classifyMarketBucket(p) {
    return p.marketSignal || "NO_ACTION";
}

function updateMetrics(activePicks, allPendingPicks = activePicks) {
    const opportunityCount = allPendingPicks.filter(isRecommendedPick).length;
    const elAnalizados = document.getElementById("statAnalizados");
    const elAnalizadosSub = document.getElementById("statAnalizadosSub");
    if(elAnalizados) elAnalizados.innerText = opportunityCount;
    if(elAnalizadosSub) elAnalizadosSub.innerText = `${allPendingPicks.length} picks analizados`;

    const soonPicks = activePicks.filter(p => {
        if (!p.iso) return false;
        const d = (new Date(p.iso) - new Date()) / 60000;
        return d >= 0 && d <= 30;
    }).sort((a, b) => new Date(a.iso || 0) - new Date(b.iso || 0));
    const elProximos = document.getElementById("statProximos");
    if(elProximos) elProximos.innerText = soonPicks.length;
    statState.proximos = soonPicks;

    const buckets = Object.fromEntries(MARKET_SIGNAL_KEYS.map(key => [key, []]));
    activePicks.forEach(p => buckets[classifyMarketBucket(p)].push(p));
    statState.mercado = buckets;
    
    const elMercado = document.getElementById("statMercado");
    if (elMercado) {
        const activeKeys = MARKET_SIGNAL_KEYS.filter(key => buckets[key].length > 0);
        elMercado.innerHTML = activeKeys.length ? activeKeys.map(key => {
            const cfg = marketSignalVisualConfig(key);
            return `<span title="${TREND_LABEL[key]}" style="color:${cfg.text}">${TREND_ICON[key]} ${buckets[key].length}</span>`;
        }).join('') : `<span style="color:var(--muted)">Sin señales activas</span>`;
    }

    // El Top Pick es global: los filtros de pantalla no deben sustituir al
    // mejor pick operativo disponible en este momento.
    const best = selectTopPick(allPendingPicks);
    TOP_PICK_ID = best ? getWatchlistId(best) : null;
    statState.mejor = best ? [best] : [];
    
    const elMejor = document.getElementById("statMejor");
    if (elMejor) {
        elMejor.innerText = best ? `${best.pick} · EV ${Number(best.ev || 0).toFixed(1)}% · ${Number(best.stake || 0).toFixed(1)}u` : "Sin pick operable";
    }
}

function renderStatRows(items) {
    if (!items || !items.length) {
        return `<div class="stat-empty">Sin picks en esta categoría.</div>`;
    }
    
    const sortedUpcoming = [...items]
        .sort((a, b) => new Date(a.iso || 0) - new Date(b.iso || 0))
        .slice(0, 3);

    return sortedUpcoming.map(p => {
        const e = calculateEdge(p);
        const formattedEdge = e > 0 ? `+${e}%` : `${e}%`;
        const edgeColor = e >= 0 ? 'var(--teal)' : 'var(--red)';
        const cuota = escapeHTML(p.odds || p.cuota || "—");
        const timeStr = escapeHTML(p.time || "--:--");
        return `
            <div class="stat-row">
                <div class="stat-row-main">
                    <div class="stat-row-game">🕒 ${timeStr} · ${escapeHTML(p.game) || 'Evento'}</div>
                    <div class="stat-row-pick"><b>${escapeHTML(p.pick)}</b> (${escapeHTML(p.market) || 'Mercado'}) · ${escapeHTML(p.league) || ''}</div>
                </div>
                <div class="stat-row-nums">
                    <span style="color:${edgeColor}">${formattedEdge}</span>
                    <span style="color:var(--amber)">${cuota}</span>
                </div>
            </div>
        `;
    }).join("");
}

function setupStatPopups() {
    document.querySelectorAll(".stat-card.expandable").forEach(card => {
        card.addEventListener("click", (e) => {
            e.stopPropagation();
            const targetId = card.dataset.target;
            const box = document.getElementById(targetId);
            if(!box) return;
            
            const isCurrentlyOpen = card.classList.contains("open");
            
            document.querySelectorAll(".stat-card.expandable").forEach(c => c.classList.remove("open"));
            document.querySelectorAll(".stat-popup").forEach(p => p.style.display = "none");

            if (!isCurrentlyOpen) {
                card.classList.add("open");

                let items = [];
                let popupTitle = "Detalle de Eventos";
                
                if (targetId === "detailProximos") { items = statState.proximos; popupTitle = "Próximos 30 Min"; }
                else if (targetId === "detailMejor") { items = statState.mejor; popupTitle = "Top Pick Análisis"; }

                box.innerHTML = `
                    <div class="stat-popup-title">
                        <span>${popupTitle}</span>
                        <span>Total: ${items.length}</span>
                    </div>
                    ${renderStatRows(items)}
                `;
                box.style.display = "block";
            }
        });
    });

    document.addEventListener("click", () => {
        document.querySelectorAll(".stat-card.expandable").forEach(c => c.classList.remove("open"));
        document.querySelectorAll(".stat-popup").forEach(p => p.style.display = "none");
    });
}

function getAmericanOddsValue(oddsRaw) {
    if (oddsRaw == null || oddsRaw === '') return null;
    const val = parseFloat(String(oddsRaw).trim());
    return isNaN(val) ? null : val;
}

function parseOddsToDecimal(odds) {
    if (odds == null || odds === "") return 0;
    
    let str = String(odds).trim();
    let val = parseFloat(str);
    if (isNaN(val)) return 0;

    if (str.startsWith('+') || str.startsWith('-')) {
        if (val > 0) {
            return (val / 100) + 1;
        } else if (val < 0) {
            return (100 / Math.abs(val)) + 1;
        }
    }
    
    return val;
}

function renderActiveChips() {
    const box = document.getElementById("activeFilterChips");
    if (!box) return;

    const chips = [];

    if (state.timeRange) {
        const labels = {
            in_play: "En Juego",
            "30m": "Próx. 30m",
            "1h": "Próx. 1h",
            "2h": "Próx. 2h",
            today: "Hoy"
        };
        chips.push({ key: "timeRange", label: `⏰ Hora: ${labels[state.timeRange] || state.timeRange}` });
    }
    if (state.modeloMin !== null || state.modeloMax !== null) {
        chips.push({ key: "modelo", label: `🤖 Modelo: ${state.modeloMin ?? 0}% - ${state.modeloMax ?? 100}%` });
    }
    if (state.cuotaMin !== null || state.cuotaMax !== null) {
        chips.push({ key: "cuota", label: `💵 Cuota: ${state.cuotaMin ?? 'Min'} - ${state.cuotaMax ?? 'Max'}` });
    }
    if (state.edgeMin !== null || state.edgeMax !== null) {
        chips.push({ key: "edge", label: `📈 Edge Mod: ${state.edgeMin ?? '-∞'}% - ${state.edgeMax ?? '+∞'}%` });
    }
    if (state.betsMin !== null || state.betsMax !== null) {
        chips.push({ key: "bets", label: `🎟️ Bets: ${state.betsMin ?? 0}% - ${state.betsMax ?? 100}%` });
    }
    if (state.handleMin !== null || state.handleMax !== null) {
        chips.push({ key: "handle", label: `💵 Handle: ${state.handleMin ?? 0}% - ${state.handleMax ?? 100}%` });
    }
    if (state.evMin !== null || state.evMax !== null) {
        chips.push({ key: "ev", label: `📊 EV: ${state.evMin ?? '-∞'}% - ${state.evMax ?? '+∞'}%` });
    }
    if (state.stakeMin !== null || state.stakeMax !== null) {
        chips.push({ key: "stake", label: `🎯 Stake: ${state.stakeMin ?? 1}u - ${state.stakeMax ?? 5}u` });
    }
    if (state.divergenciaMin !== null || state.divergenciaMax !== null) {
        chips.push({ key: "divergencia", label: `⚡ Divergencia: ${state.divergenciaMin ?? '-∞'}% - ${state.divergenciaMax ?? '+∞'}%` });
    }

    if (chips.length === 0) {
        box.innerHTML = `<span style="font-size:11px; color:var(--muted);">No hay filtros cuantitativos activos.</span>`;
        return;
    }

    box.innerHTML = chips.map(c => `
        <span class="fchip">
            ${c.label}
            <span class="fchip-remove" onclick="clearSpecificAdvFilter('${c.key}')">✕</span>
        </span>
    `).join("");
}

function clearSpecificAdvFilter(type) {
    if (type === "timeRange") { state.timeRange = ""; const el = document.getElementById("fTimeRange"); if (el) el.value = ""; }
    if (type === "modelo") { state.modeloMin = null; state.modeloMax = null; document.getElementById("fModeloMin").value = ""; document.getElementById("fModeloMax").value = ""; }
    if (type === "cuota") { state.cuotaMin = null; state.cuotaMax = null; document.getElementById("fCuotaMin").value = ""; document.getElementById("fCuotaMax").value = ""; }
    if (type === "edge") { state.edgeMin = null; state.edgeMax = null; document.getElementById("fEdgeMin").value = ""; document.getElementById("fEdgeMax").value = ""; }
    if (type === "bets") { state.betsMin = null; state.betsMax = null; document.getElementById("fBetsMin").value = ""; document.getElementById("fBetsMax").value = ""; }
    if (type === "handle") { state.handleMin = null; state.handleMax = null; document.getElementById("fHandleMin").value = ""; document.getElementById("fHandleMax").value = ""; }
    if (type === "ev") { state.evMin = null; state.evMax = null; document.getElementById("fEvMin").value = ""; document.getElementById("fEvMax").value = ""; }
    if (type === "stake") { state.stakeMin = null; state.stakeMax = null; document.getElementById("fStakeMin").value = ""; document.getElementById("fStakeMax").value = ""; }
    if (type === "divergencia") { state.divergenciaMin = null; state.divergenciaMax = null; document.getElementById("fDivergenciaMin").value = ""; document.getElementById("fDivergenciaMax").value = ""; }
    render();
}

function applyFiltersAndSort(list) {
    if (!Array.isArray(list)) return [];
    const text = state.search.toLowerCase().trim();

    let result = list.filter(p => {
        if (state.league && p.league !== state.league) return false;
        if (state.date && p.date !== state.date) return false;
        if (state.trend && p.trendKey !== state.trend) return false;

        if (state.timeRange && p.iso) {
            const timer = getCountdownText(p.iso);
            const nowLocal = new Date();
            const toDateStr = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
            const todayStr = toDateStr(nowLocal);

            const tomorrowDate = new Date(nowLocal);
            tomorrowDate.setDate(tomorrowDate.getDate() + 1);
            const tomorrowStr = toDateStr(tomorrowDate);

            const weekEndDate = new Date(nowLocal);
            weekEndDate.setDate(weekEndDate.getDate() + 6);
            const weekEndStr = toDateStr(weekEndDate);

            if (state.timeRange === "in_play" && !timer.expired) return false;
            if (state.timeRange === "30m" && (timer.diffMin < 0 || timer.diffMin > 30)) return false;
            if (state.timeRange === "1h" && (timer.diffMin < 0 || timer.diffMin > 60)) return false;
            if (state.timeRange === "2h" && (timer.diffMin < 0 || timer.diffMin > 120)) return false;
            if (state.timeRange === "today" && p.date !== todayStr) return false;
            if (state.timeRange === "tomorrow" && p.date !== tomorrowStr) return false;
            if (state.timeRange === "this_week" && (p.date < todayStr || p.date > weekEndStr)) return false;
        }

        if (state.modeloMin !== null && !isNaN(state.modeloMin) && (p.modelProb || 0) < state.modeloMin) return false;
        if (state.modeloMax !== null && !isNaN(state.modeloMax) && (p.modelProb || 0) > state.modeloMax) return false;

        const itemOddsDec = parseOddsToDecimal(p.odds || p.cuota);
        if (state.cuotaMin !== null) {
            const minDec = parseOddsToDecimal(state.cuotaMin);
            if (minDec > 0 && itemOddsDec < minDec) return false;
        }
        if (state.cuotaMax !== null) {
            const maxDec = parseOddsToDecimal(state.cuotaMax);
            if (maxDec > 0 && itemOddsDec > maxDec) return false;
        }

        const edgeVal = calculateEdge(p);
        if (state.edgeMin !== null && !isNaN(state.edgeMin) && edgeVal < state.edgeMin) return false;
        if (state.edgeMax !== null && !isNaN(state.edgeMax) && edgeVal > state.edgeMax) return false;

        const betsVal = Number(p.betsPct || 0);
        if (state.betsMin !== null && !isNaN(state.betsMin) && betsVal < state.betsMin) return false;
        if (state.betsMax !== null && !isNaN(state.betsMax) && betsVal > state.betsMax) return false;

        const handleVal = Number(p.handlePct || 0);
        if (state.handleMin !== null && !isNaN(state.handleMin) && handleVal < state.handleMin) return false;
        if (state.handleMax !== null && !isNaN(state.handleMax) && handleVal > state.handleMax) return false;

        const evVal = Number(p.ev || 0);
        if (state.evMin !== null && !isNaN(state.evMin) && evVal < state.evMin) return false;
        if (state.evMax !== null && !isNaN(state.evMax) && evVal > state.evMax) return false;

        const stakeVal = Number(p.stake) || 0;
        if (state.stakeMin !== null && !isNaN(state.stakeMin) && stakeVal < state.stakeMin) return false;
        if (state.stakeMax !== null && !isNaN(state.stakeMax) && stakeVal > state.stakeMax) return false;

        const divVal = calculateSmartMoney(p);
        if (state.divergenciaMin !== null && !isNaN(state.divergenciaMin) && divVal < state.divergenciaMin) return false;
        if (state.divergenciaMax !== null && !isNaN(state.divergenciaMax) && divVal > state.divergenciaMax) return false;

        if (state.watchlistOnly && !isInWatchlist(p)) return false;

        if (state.featuredOnly && !isMediaFeaturedPick(p)) return false;
        if (state.freeReleaseOnly && !p.freeRelease) return false;

        if (text) {
            const blob = `${p.game || ''} ${p.pick || ''} ${p.market || ''} ${p.reason || ''}`.toLowerCase();
            if (!blob.includes(text)) return false;
        }
        return true;
    });

    return result.sort((a, b) => {
        if (state.sort === "time") return new Date(a.iso || 0) - new Date(b.iso || 0);
        if (state.sort === "ev") return Number(b.ev || 0) - Number(a.ev || 0);
        if (state.sort === "edge") return calculateEdge(b) - calculateEdge(a);
        return 0;
    });
}
function fallbackCopyText(text) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    // Evita desplazamiento en la pantalla al enfocar
    textArea.style.position = "fixed";
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.opacity = "0";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        document.execCommand('copy');
        showToastX();
    } catch (err) {
        console.error('Error al copiar al portapapeles:', err);
    }
    document.body.removeChild(textArea);
}

function getHeaderTag(category, freeRelease = false) {
    if (freeRelease) return "🔓 FREE PICK";
    switch (category) {
        case 'WHALE':
            return "🐳 WHALE ALERT PICK";
        case 'LONGSHOT':
            return "🎲 LONGSHOT · ALTA VARIANZA";
        case 'PREMIUM':
            return "💎 PREMIUM PICK";
        case 'VALUE':
            return "📈 VALUE PICK";
        default:
            return "👀 PICK EN OBSERVACIÓN";
    }
}

function copyPickForX(p) {
    // 1. Encabezado dinámico según la categoría real del pick (misma fuente que el borde/etiqueta de la card)
    const header = getHeaderTag(p.pickCategory, Boolean(p.freeRelease));

    // 2. Extracción y formateo de datos
    const dateStr = p.date || new Date().toISOString().split('T')[0];
    const timeStr = p.time || "--:--";
    const league = p.league || p.sport || "SPORTS";
    const game = p.game || "Evento";
    
    const pickName = p.pick || "Selección";
    const market = p.market ? ` (${p.market})` : "";
    const odds = p.odds || p.cuota || "Ev";

    // 3. Stake en unidades, ya ajustado a escala de 0.5 por el backend.
    const displayStake = Number(p.stake) || 0;
    const stakeStr = `${displayStake.toFixed(1)}u`;

    // 4. Construcción del mensaje con la salida idéntica requerida
    const tweetText = `${header}\n` +
        `📅 ${dateStr} | ⏰ ${timeStr}\n` +
        `🏆 ${league}\n` +
        `🏟️ ${game}\n` +
        `🎯 Pick: ${pickName}${market}\n` +
        `💵 Cuota: ${odds}\n` +
        `💰 Stake: ${stakeStr}`;

    // 5. Copiar al portapapeles
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(tweetText)
            .then(() => {
                showToastX();
            })
            .catch(err => {
                console.error("Error al copiar vía Clipboard API:", err);
                fallbackCopyText(tweetText);
            });
    } else {
        fallbackCopyText(tweetText);
    }
}

function showToastX() {
    const toast = document.getElementById("toast-x");
    if (!toast) return;
    toast.classList.add("show");
    setTimeout(() => {
        toast.classList.remove("show");
    }, 3000);
}

// ============ MY WATCHLIST (Parte 1: reemplaza el Recordatorio de 60 min) ============
// Al "Seguir" un pick se guarda un snapshot (bets/handle/divergencia/cuota)
// en localStorage. Cada vez que el dashboard se regenera y se recarga, se
// compara el dato actual contra ese snapshot para mostrar si la línea
// mejoró o empeoró desde que se empezó a seguir.
const WATCHLIST_STORAGE_KEY = "sharpie_watchlist_v1";

function getWatchlistId(p) {
    return `${(p.league || '').toLowerCase()}|${(p.game || '').toLowerCase()}|${(p.market || '').toLowerCase()}|${(p.pick || '').toLowerCase()}`.trim();
}

function loadWatchlist() {
    try {
        return JSON.parse(localStorage.getItem(WATCHLIST_STORAGE_KEY)) || {};
    } catch (e) {
        return {};
    }
}

function saveWatchlist(list) {
    try {
        localStorage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify(list));
    } catch (e) {
        console.error("Error al guardar watchlist:", e);
    }
}

function isInWatchlist(p) {
    const list = loadWatchlist();
    return !!list[getWatchlistId(p)];
}

function toggleWatchlist(p) {
    const list = loadWatchlist();
    const id = getWatchlistId(p);

    if (list[id]) {
        delete list[id];
        saveWatchlist(list);
        showAttractiveNotification({
            title: "👁 Dejaste de seguir",
            body: `${p.game || 'Evento'} — ${p.pick || ''}`,
            variant: "info"
        });
    } else {
        const entry = {
            followedAt: new Date().toISOString(),
            league: p.league || '',
            game: p.game || '',
            pick: p.pick || '',
            market: p.market || '',
            snapshot: {
                odds: p.odds || p.cuota || null,
                edge: p.modelEdge != null ? Number(p.modelEdge) : null,
                ev: p.ev != null ? Number(p.ev) : null
            }
        };
        list[id] = entry;
        saveWatchlist(list);
        showAttractiveNotification({
            title: "👁 Ahora sigues este pick",
            body: `${p.game || 'Evento'} — ${p.pick || ''}`,
            variant: "success"
        });
    }
    render();
}

// Flecha de comparación actual vs snapshot -- usada en el panel de watchlist
function watchlistDeltaArrow(current, snapshot) {
    if (current == null || snapshot == null) return '';
    const diff = current - snapshot;
    if (Math.abs(diff) < 0.05) return ' <span class="wl-delta wl-flat">＝</span>';
    return diff > 0 ? ` <span class="wl-delta wl-up">▲ +${diff.toFixed(1)}</span>` : ` <span class="wl-delta wl-down">▼ ${diff.toFixed(1)}</span>`;
}

// Veredicto de SEGUIMIENTO (distinto de la Señal de la card -- esto compara
// el movimiento desde que se empezó a seguir, no el estado actual del
// mercado). Solo 3 métricas: Cuota, Stake y EV.
//
// Umbrales de DESCARTAR:
//  - Cuota se abarata >=35 pts americanos (ej. -110 -> -145) -- el valor
//    original ya no está.
//  - EV cae a 0 o negativo -- ya no hay ventaja matemática.
//  - EV cae >=50% respecto al de apertura -- la ventaja se redujo a la mitad.
//  - Edge Modelo cae a 0 o negativo habiendo empezado en positivo.
function pctChange(current, snapshot) {
    if (current == null || snapshot == null || snapshot === 0) return null;
    return ((current - snapshot) / Math.abs(snapshot)) * 100;
}

function watchlistVerdict(p, snap) {
    const oddsNowRaw = parseInt(String(p.odds || p.cuota || '').replace('+', ''), 10);
    const oddsSnapRaw = parseInt(String(snap.odds || '').replace('+', ''), 10);
    const hasOdds = !isNaN(oddsNowRaw) && !isNaN(oddsSnapRaw);
    const oddsDelta = hasOdds ? (oddsNowRaw - oddsSnapRaw) : null; // positivo = "sube" (favorable)

    const evNow = p.ev != null ? Number(p.ev) : null;
    const evSnap = snap.ev != null ? Number(snap.ev) : null;
    const edgeNow = p.modelEdge != null ? Number(p.modelEdge) : null;
    const edgeSnap = snap.edge != null ? Number(snap.edge) : null;

    if (evSnap == null || edgeSnap == null) {
        return { verdict: 'MONITOREAR', text: 'Datos insuficientes para comparar contra el punto de apertura del seguimiento.' };
    }

    const evPctMove = pctChange(evNow, evSnap);

    // DESCARTAR -- basta con que se cumpla UNA condición severa
    if (hasOdds && oddsDelta <= -35) {
        return { verdict: 'DESCARTAR', text: `Cuota se abarató con fuerza (${snap.odds} → ${p.odds || p.cuota}) -- el valor original ya no está.` };
    }
    if (evNow == null || evNow <= 0) {
        return { verdict: 'DESCARTAR', text: 'El EV cayó a cero o negativo desde que se sigue -- ya no hay ventaja matemática.' };
    }
    if (evPctMove !== null && evPctMove <= -50) {
        return { verdict: 'DESCARTAR', text: `EV cayó ${evPctMove.toFixed(0)}% desde que se sigue (${evSnap}% → ${evNow}%).` };
    }
    if (edgeSnap > 0 && (edgeNow == null || edgeNow <= 0)) {
        return { verdict: 'DESCARTAR', text: 'El Edge Modelo cayó a cero o negativo -- perdió la ventaja que tenía al momento de seguirlo.' };
    }

    // APOSTAR -- las 3 métricas se mantienen o mejoran
    const cond1 = hasOdds && oddsDelta >= 0;
    const cond2 = evNow >= evSnap;
    const cond3 = edgeNow != null && edgeNow >= edgeSnap;

    if (cond1 && cond2 && cond3) {
        return { verdict: 'APOSTAR', text: `Cuota, EV y Edge Modelo se mantienen o mejoran desde que se sigue -- línea confirmando a favor.` };
    }

    // MONITOREAR -- movimiento leve en contra, sin cruzar el umbral de descarte
    return { verdict: 'MONITOREAR', text: 'Movimiento leve en contra desde que se sigue -- todavía dentro de rango normal, sin señal de descarte.' };
}

function watchlistPanelHtml(p) {
    const list = loadWatchlist();
    const entry = list[getWatchlistId(p)];
    if (!entry) return '';

    const snap = entry.snapshot || {};
    const followedDate = entry.followedAt ? new Date(entry.followedAt) : null;
    const followedText = followedDate ? followedDate.toLocaleString() : '';
    const v = watchlistVerdict(p, snap);
    const verdictCls = v.verdict === 'APOSTAR' ? 'good' : (v.verdict === 'DESCARTAR' ? 'bad' : 'warn');
    const verdictIcon = v.verdict === 'APOSTAR' ? '✅' : (v.verdict === 'DESCARTAR' ? '🗑️' : '👀');

    return `<div class="watchlist-panel">
        <div class="watchlist-panel-title">👁 En seguimiento desde ${escapeHTML(followedText)}</div>
        <div class="badge-tag-grid">
            <span class="badge-tag neutral">💰 Cuota apertura <b>${escapeHTML(String(snap.odds ?? '—'))}</b> → <b>${escapeHTML(p.odds || p.cuota || '—')}</b></span>
            <span class="badge-tag neutral">📈 Edge Modelo <b>${snap.edge != null ? snap.edge + '%' : '—'}</b>${watchlistDeltaArrow(p.modelEdge, snap.edge)}</span>
            <span class="badge-tag neutral">📊 EV <b>${snap.ev != null ? snap.ev + '%' : '—'}</b>${watchlistDeltaArrow(p.ev, snap.ev)}</span>
        </div>
        <div class="reasoning-text"><span class="badge-tag ${verdictCls}" style="margin-right:6px;">${verdictIcon} ${v.verdict} (desde seguimiento)</span>${escapeHTML(v.text)}</div>
    </div>`;
}

function showAttractiveNotification({ title, body, variant = "info" }) {
    const container = document.getElementById("reminderNotifContainer");
    if (!container) return;

    const el = document.createElement("div");
    el.className = `reminder-notif reminder-notif-${variant}`;
    el.innerHTML = `
        <button class="reminder-notif-close" aria-label="Cerrar">&times;</button>
        <div class="reminder-notif-title">${escapeHTML(title)}</div>
        <div class="reminder-notif-body">${escapeHTML(body).replace(/\n/g, '<br>')}</div>
    `;
    el.querySelector(".reminder-notif-close").addEventListener("click", () => dismissNotif(el));

    // Si ya hay notificaciones visibles, se da tiempo extra -- leer 2-3
    // apiladas necesita más que el tiempo de una sola.
    const alreadyVisible = container.querySelectorAll(".reminder-notif").length;
    container.appendChild(el);

    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("show")));

    const baseDuration = variant === "urgent" ? 20000 : 10000;
    const extraPerStacked = 3000;
    setTimeout(() => dismissNotif(el), baseDuration + (alreadyVisible * extraPerStacked));
}

function dismissNotif(el) {
    if (!el || !el.parentNode) return;
    el.classList.remove("show");
    setTimeout(() => el.remove(), 300);
}

function populateSelectOptions() {
    const dates = new Set();
    const leagues = new Set();
    const suggestions = new Set();

    PICKS.forEach(p => {
        if (p.date) dates.add(p.date);
        if (p.league) leagues.add(p.league);
        if (p.league) suggestions.add(p.league);
        if (p.away) suggestions.add(p.away);
        if (p.home) suggestions.add(p.home);
        if (p.pick) suggestions.add(p.pick);
        if (p.market) suggestions.add(p.market);
    });

    const searchList = document.getElementById("searchSuggestions");
    if (searchList) {
        searchList.innerHTML = Array.from(suggestions).sort()
            .map(s => `<option value="${escapeHTML(s)}"></option>`).join("");
    }

    const fDate = document.getElementById("fDate");
    if (fDate) {
        const sortedDates = Array.from(dates).sort();
        fDate.innerHTML = `<option value="">📆 Todas las fechas (${sortedDates.length})</option>` +
            sortedDates.map(d => `<option value="${escapeHTML(d)}">${escapeHTML(d)}</option>`).join("");
        fDate.value = state.date;
    }

    const fLeague = document.getElementById("fLeague");
    if (fLeague) {
        const sortedLeagues = Array.from(leagues).sort();
        fLeague.innerHTML = `<option value="">🏆 Todas las ligas (${sortedLeagues.length})</option>` +
            sortedLeagues.map(l => `<option value="${escapeHTML(l)}">${escapeHTML(l)}</option>`).join("");
        fLeague.value = state.league;
    }
}

function syncAdvCardActiveStates() {
    document.querySelectorAll("#advFiltersPanel .adv-card").forEach(card => {
        const anyFilled = Array.from(card.querySelectorAll("input, select")).some(i => i.value !== "" && i.value != null);
        card.classList.toggle("adv-card-active", anyFilled);
    });
}

function updateFilterCounts(pendingPicks) {
    const fTimeRange = document.getElementById("fTimeRange");
    if (fTimeRange) {
        const counts = { in_play: 0, "30m": 0, "1h": 0, "2h": 0, today: 0, tomorrow: 0, this_week: 0 };
        const nowLocal = new Date();
        const toDateStr = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        const todayStr = toDateStr(nowLocal);
        const tomorrowDate = new Date(nowLocal); tomorrowDate.setDate(tomorrowDate.getDate() + 1);
        const tomorrowStr = toDateStr(tomorrowDate);
        const weekEndDate = new Date(nowLocal); weekEndDate.setDate(weekEndDate.getDate() + 6);
        const weekEndStr = toDateStr(weekEndDate);

        pendingPicks.forEach(p => {
            if (!p.iso) return;
            const timer = getCountdownText(p.iso);
            if (timer.expired) counts.in_play++;
            if (!timer.expired && timer.diffMin >= 0 && timer.diffMin <= 30) counts["30m"]++;
            if (!timer.expired && timer.diffMin >= 0 && timer.diffMin <= 60) counts["1h"]++;
            if (!timer.expired && timer.diffMin >= 0 && timer.diffMin <= 120) counts["2h"]++;
            if (p.date === todayStr) counts.today++;
            if (p.date === tomorrowStr) counts.tomorrow++;
            if (p.date >= todayStr && p.date <= weekEndStr) counts.this_week++;
        });

        const labels = {
            in_play: "🔴 En juego", "30m": "⏳ Próximos 30 min", "1h": "⏳ Próxima 1 hora",
            "2h": "⏳ Próximas 2 horas", today: "📅 Eventos de Hoy", tomorrow: "📅 Eventos de Mañana",
            this_week: "📆 Eventos de Esta Semana"
        };
        Array.from(fTimeRange.options).forEach(opt => {
            if (!opt.value) { opt.textContent = "⏱️ Hora / Rango"; return; }
            opt.textContent = `${labels[opt.value]} (${counts[opt.value] || 0})`;
        });
    }

    const fTrend = document.getElementById("fTrend");
    if (fTrend) {
        const counts = Object.fromEntries(MARKET_SIGNAL_KEYS.map(key => [key, 0]));
        pendingPicks.forEach(p => { if (p.marketSignal in counts) counts[p.marketSignal]++; });
        Array.from(fTrend.options).forEach(opt => {
            if (!opt.value) {
                opt.textContent = "📊 Todas las señales";
                opt.hidden = false;
                opt.disabled = false;
                return;
            }
            const count = counts[opt.value] || 0;
            opt.textContent = `${TREND_ICON[opt.value]} ${TREND_LABEL[opt.value]} (${count})`;
            const unavailable = count === 0 && state.trend !== opt.value;
            opt.hidden = unavailable;
            opt.disabled = unavailable;
        });
    }

    const watchlistBtn = document.getElementById("watchlistOnly");
    if (watchlistBtn) watchlistBtn.textContent = `👁 My Watchlist (${pendingPicks.filter(p => isInWatchlist(p)).length})`;
    const freeReleaseBtn = document.getElementById("freeReleaseOnly");
    if (freeReleaseBtn) freeReleaseBtn.textContent = `📣 Free para redes (${pendingPicks.filter(p => p.freeRelease).length})`;
}

function render() {
    updateThemeByTime();
    syncAdvCardActiveStates();

    const pendingPicks = PICKS.filter(p => isEventPending(p));
    const recommendedPicks = pendingPicks.filter(isRecommendedPick);
    const visibleUniverse = state.showFullMarket ? pendingPicks : recommendedPicks;
    const activeList = applyFiltersAndSort(visibleUniverse);

    updateFilterCounts(visibleUniverse);

    ACTIVE_FILTER_MATCH_KEYS = new Set(activeList.map(getWatchlistId));

    updateMetrics(activeList, pendingPicks);
    updateChartsData(activeList);

    const filteredCountEl = document.getElementById("filteredCount");
    const totalCountEl = document.getElementById("totalCount");
    const recordsContext = document.getElementById("recordsContext");
    const recordsTotalLabel = document.getElementById("recordsTotalLabel");
    const analyzedCountSummary = document.getElementById("analyzedCountSummary");
    if (filteredCountEl) filteredCountEl.innerText = activeList.length;
    if (totalCountEl) totalCountEl.innerText = state.showFullMarket ? pendingPicks.length : recommendedPicks.length;
    if (recordsContext) recordsContext.textContent = state.showFullMarket ? "picks de" : "oportunidades de";
    if (recordsTotalLabel) recordsTotalLabel.textContent = state.showFullMarket ? "analizados" : "recomendadas";
    if (analyzedCountSummary) {
        analyzedCountSummary.textContent = state.showFullMarket
            ? " · vista completa"
            : ` · ${pendingPicks.length} picks analizados`;
    }

    renderActiveChips();

    const cardsView = document.getElementById("cardsView");
    const emptyState = document.getElementById("emptyState");

    if (!cardsView) return;

    if (activeList.length === 0) {
        cardsView.style.display = "none";
        if (emptyState) {
            emptyState.style.display = "block";
            const message = document.getElementById("emptyStateMsg");
            if (message) {
                message.textContent = state.showFullMarket
                    ? "No se encontraron picks con los filtros actuales."
                    : "No hay apuestas recomendadas en este momento. El mercado completo continúa bajo análisis.";
            }
        }
        return;
    }

    if (emptyState) emptyState.style.display = "none";
    cardsView.style.display = "grid";

    cardsView.innerHTML = activeList.map(p => {
        const isWhale = p.whale === true || (Array.isArray(p.marketSignals) && p.marketSignals.includes("SMART_MONEY"));
        const isLongshot = p.pickCategory === "LONGSHOT";
        const isValue = p.pickCategory === "VALUE";
        const isPremiumPick = p.pickCategory === "PREMIUM";
        const isFreeRelease = Boolean(p.freeRelease);
        const isTop = isTopPick(p);
        const isMediaFeatured = isMediaFeaturedPick(p);
        const isNew = RECENTLY_ADDED_IDS.has(getWatchlistId(p));
        const isUpdated = !isNew && RECENTLY_UPDATED_IDS.has(getWatchlistId(p));

        let cardClasses = "pcard";
        if (isLongshot) cardClasses += " longshot-card";
        else if (isWhale) cardClasses += " whale-alert";
        else if (isFreeRelease) cardClasses += " free-pick";

        const config = marketSignalVisualConfig(p.marketSignal);
        const allSignals = Array.isArray(p.marketSignals) && p.marketSignals.length ? p.marketSignals : [p.marketSignal];
        const signalSummary = allSignals.map(key => `${TREND_ICON[key] || ''} ${TREND_LABEL[key] || key}`).join(' · ');
        const primarySignalIcon = TREND_ICON[p.marketSignal] || '⚪';
        const primarySignalName = TREND_LABEL[p.marketSignal] || 'NO ACTION';
        const timer = getCountdownText(p.iso);
        const edgeVal = calculateEdge(p);
        const formattedEdge = edgeVal > 0 ? `+${edgeVal}%` : `${edgeVal}%`;
        const smartMoney = calculateSmartMoney(p);

        const betsPct = p.betsPct != null ? p.betsPct : 50;
        const handlePct = p.handlePct != null ? p.handlePct : 50;

        const displayStake = Number(p.stake) || 0;
        const isFollowed = isInWatchlist(p);

        const dateDisplay = escapeHTML(p.date || "--/--/----");
        const timeDisplay = escapeHTML(p.time || "--:--");

        return `
            <div class="${cardClasses}">
                <div>
                    <div class="card-hero-header" style="--signal-color:${config.text}; --signal-bg:${config.bg};">
                        <div class="signal-main">
                            <div class="signal-orb" title="${escapeHTML(signalSummary)}">${primarySignalIcon}</div>
                            <div class="signal-copy" title="${escapeHTML(signalSummary)}">
                                <span class="signal-kicker">SEÑAL DE MERCADO</span>
                                <strong class="signal-name">${primarySignalName}</strong>
                            </div>
                        </div>
                        <span class="countdown-timer ${timer.urgent ? 'urgent' : ''}" data-iso="${p.iso || ''}">${timer.text}</span>
                        <div class="card-hero-tags">
                            ${isNew ? `<span class="status-icon" title="Pick nuevo">🆕</span>` : ''}
                            ${isUpdated ? `<span class="status-icon" title="Pick actualizado">🔄</span>` : ''}
                            ${isTop ? `<span class="status-icon" title="Mejor pick del momento">🏆</span>` : ''}
                            ${isMediaFeatured ? `<span class="status-icon" title="Equipo mediático destacado">⭐</span>` : ''}
                            ${isWhale ? `<span class="whale-header-badge">WHALE SIGNAL</span>` : ''}
                            ${isLongshot ? `<span class="longshot-pick-badge">LONGSHOT · MÁX. 0.5u</span>` : ''}
                            ${isValue ? `<span class="value-pick-badge">VALUE</span>` : ''}
                            ${isPremiumPick ? `<span class="premium-pick-badge">PREMIUM</span>` : ''}
                            ${isFreeRelease ? `<span class="free-pick-badge" title="Seleccionado para publicación gratuita #${p.freeReleaseRank || ''}">FREE RELEASE${p.freeReleaseRank ? ` #${p.freeReleaseRank}` : ''}</span>` : ''}
                        </div>
                    </div>

                    <div style="margin-top: 8px; margin-bottom: 4px;">
                        <span style="font-size: 11px; font-weight: 800; color: var(--teal); text-transform: uppercase;">
                            ${escapeHTML(p.league) || 'LIGA DESCONOCIDA'}
                        </span>
                        <h3 class="game-title">${escapeHTML(p.game) || 'Evento no especificado'}</h3>
                    </div>

                    <div class="meta-row">
                        <div class="datetime-container">
                            <span class="date-badge">📅 ${dateDisplay}</span>
                            <span class="time-badge">🕒 ${timeDisplay}</span>
                        </div>
                    </div>

                    <div class="pick-details">
                        <div class="pick-name">${escapeHTML(p.pick) || 'Selección'}</div>
                        <div class="market-type">${escapeHTML(p.market) || 'Mercado General'}</div>
                    </div>

                    <div class="volume-container">
                        <div class="volume-labels">
                            <span>🎟️ Tickets (Bets): <b>${p.betsPct != null ? p.betsPct + '%' : '—'}</b></span>
                            <span>💵 Dinero (Handle): <b>${p.handlePct != null ? p.handlePct + '%' : '—'}</b></span>
                        </div>
                        <div class="volume-bar-wrapper">
                            <div class="v-bets" style="width: ${betsPct}%;"></div>
                            <div class="v-handle" style="width: ${handlePct}%;"></div>
                        </div>
                    </div>

                    ${buildEvolutionHtml(p)}
                    ${unifiedDecisionPanelHtml(p)}

                </div>

                <div style="margin-top: 14px;">
                    ${isFollowed ? watchlistPanelHtml(p) : ''}
                    <div class="pcard-action-row">
                        <button class="btn-copy-x pcard-action-row-item" onclick='copyPickForX(${JSON.stringify(p).replace(/'/g, "&#39;")})'>
                            <span>✨</span>
                            <span>Copiar para X</span>
                        </button>
                        <button class="btn-reminder ${isFollowed ? 'active' : ''}" onclick='toggleWatchlist(${JSON.stringify(p).replace(/'/g, "&#39;")})'>
                            <span>${isFollowed ? '👁' : '👁‍🗨'}</span>
                            <span>${isFollowed ? 'Siguiendo' : 'Seguir'}</span>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join("");
}

function setupListeners() {
    const searchEl = document.getElementById("search");
    let searchDebounceTimer = null;
    if (searchEl) searchEl.addEventListener("input", (e) => {
        state.search = e.target.value;
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(render, 300);
    });

    const viewModeBtn = document.getElementById("viewModeToggle");
    if (viewModeBtn) {
        const syncViewModeBtn = () => {
            viewModeBtn.textContent = state.advancedView ? "🎓 Modo Simple" : "🔬 Modo Avanzado";
            viewModeBtn.classList.toggle("active", state.advancedView);
        };
        syncViewModeBtn();
        viewModeBtn.addEventListener("click", () => {
            state.advancedView = !state.advancedView;
            syncViewModeBtn();
            render();
        });
    }

    const fSortEl = document.getElementById("fSort");
    if (fSortEl) fSortEl.addEventListener("change", (e) => { state.sort = e.target.value; render(); });

    const fDateEl = document.getElementById("fDate");
    if (fDateEl) fDateEl.addEventListener("change", (e) => { state.date = e.target.value; render(); });

    const fLeagueEl = document.getElementById("fLeague");
    if (fLeagueEl) fLeagueEl.addEventListener("change", (e) => { state.league = e.target.value; render(); });

    const fTrendEl = document.getElementById("fTrend");
    if (fTrendEl) fTrendEl.addEventListener("change", (e) => { state.trend = e.target.value; render(); });

    const featuredBtn = document.getElementById("featuredOnly");

    // Pick destacado por equipo mediático.
    if (featuredBtn) featuredBtn.addEventListener("click", () => {
        state.featuredOnly = !state.featuredOnly;
        featuredBtn.setAttribute("aria-pressed", String(state.featuredOnly));
        render();
    });

    const freeReleaseBtn = document.getElementById("freeReleaseOnly");
    if (freeReleaseBtn) freeReleaseBtn.addEventListener("click", () => {
        state.freeReleaseOnly = !state.freeReleaseOnly;
        freeReleaseBtn.setAttribute("aria-pressed", String(state.freeReleaseOnly));
        render();
    });

    const fullMarketBtn = document.getElementById("fullMarketToggle");
    if (fullMarketBtn) fullMarketBtn.addEventListener("click", () => {
        state.showFullMarket = !state.showFullMarket;
        fullMarketBtn.setAttribute("aria-pressed", String(state.showFullMarket));
        fullMarketBtn.textContent = state.showFullMarket ? "🎯 Mostrar solo apuestas" : "🔎 Mostrar mercado completo";
        render();
    });

    // My Watchlist -- filtra solo por picks seguidos (localStorage), independiente
    // de las demás categorías.
    const watchlistBtn = document.getElementById("watchlistOnly");
    if (watchlistBtn) watchlistBtn.addEventListener("click", () => {
        state.watchlistOnly = !state.watchlistOnly;
        watchlistBtn.setAttribute("aria-pressed", String(state.watchlistOnly));
        render();
    });

    const btnAdvToggle = document.getElementById("btnAdvToggle");
    const advPanel = document.getElementById("advFiltersPanel");
    if (btnAdvToggle && advPanel) {
        btnAdvToggle.addEventListener("click", () => {
            const isShown = advPanel.classList.contains("show");
            if (isShown) {
                advPanel.classList.remove("show");
                btnAdvToggle.setAttribute("aria-pressed", "false");
            } else {
                advPanel.classList.add("show");
                btnAdvToggle.setAttribute("aria-pressed", "true");
            }
        });
    }

    // Escuchadores de Filtros Avanzados Cuantitativos
    const bindInput = (id, prop, isFloat = true) => {
        const el = document.getElementById(id);
        if (el) {
            const card = el.closest(".adv-card");
            const syncCardActive = () => {
                if (!card) return;
                const anyFilled = Array.from(card.querySelectorAll("input, select")).some(i => i.value !== "" && i.value != null);
                card.classList.toggle("adv-card-active", anyFilled);
            };
            let debounceTimer = null;
            el.addEventListener("input", (e) => {
                const val = e.target.value;
                if (val === "" || val === null) {
                    state[prop] = null;
                } else {
                    state[prop] = isFloat ? parseFloat(val) : val;
                }
                syncCardActive();
                // El render completo (recalcula ~todos los picks, gráficas y
                // métricas) es pesado -- se espera a que el usuario pare de
                // escribir en vez de dispararlo en cada tecla.
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(render, 300);
            });
        }
    };

    const fTimeRangeEl = document.getElementById("fTimeRange");
    if (fTimeRangeEl) fTimeRangeEl.addEventListener("change", (e) => { state.timeRange = e.target.value; render(); });

    bindInput("fCuotaMin", "cuotaMin", false);
    bindInput("fCuotaMax", "cuotaMax", false);

    bindInput("fModeloMin", "modeloMin");
    bindInput("fModeloMax", "modeloMax");
    bindInput("fDivergenciaMin", "divergenciaMin");
    bindInput("fDivergenciaMax", "divergenciaMax");
    bindInput("fStakeMin", "stakeMin");
    bindInput("fStakeMax", "stakeMax");
    bindInput("fBetsMin", "betsMin");
    bindInput("fBetsMax", "betsMax");
    bindInput("fHandleMin", "handleMin");
    bindInput("fHandleMax", "handleMax");
    bindInput("fEdgeMin", "edgeMin");
    bindInput("fEdgeMax", "edgeMax");
    bindInput("fEvMin", "evMin");
    bindInput("fEvMax", "evMax");

    const clearBtn = document.getElementById("clearBtn");

    const btnSaveFilter = document.getElementById("btnSaveFilter");
    if (btnSaveFilter) btnSaveFilter.addEventListener("click", saveCurrentFilterPreset);

    if (clearBtn) {
        clearBtn.addEventListener("click", () => {
            state.search = "";
            state.date = "";
            state.league = "";
            state.trend = "";
            state.featuredOnly = false;
            state.freeReleaseOnly = false;
            state.watchlistOnly = false;
            state.showFullMarket = false;
            state.sort = "time";
            
            state.timeRange = "";
            state.modeloMin = null;
            state.modeloMax = null;
            state.cuotaMin = null;
            state.cuotaMax = null;
            state.edgeMin = null;
            state.edgeMax = null;
            state.betsMin = null;
            state.betsMax = null;
            state.handleMin = null;
            state.handleMax = null;
            state.evMin = null;
            state.evMax = null;
            state.stakeMin = null;
            state.stakeMax = null;
            state.divergenciaMin = null;
            state.divergenciaMax = null;

            document.querySelectorAll(".toolbar input, .toolbar select").forEach(i => i.value = "");
            document.querySelectorAll(".adv-filters-panel input, .adv-filters-panel select").forEach(i => i.value = "");
            
            if (fSortEl) fSortEl.value = "time";

            if (featuredBtn) featuredBtn.setAttribute("aria-pressed", "false");
            if (freeReleaseBtn) freeReleaseBtn.setAttribute("aria-pressed", "false");
            if (watchlistBtn) watchlistBtn.setAttribute("aria-pressed", "false");
            if (fullMarketBtn) {
                fullMarketBtn.setAttribute("aria-pressed", "false");
                fullMarketBtn.textContent = "🔎 Mostrar mercado completo";
            }

            render();
        });
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    startRealtimeClock();
    setupThemeToggle();
    initCharts();
    await loadData();
    populateSelectOptions();
    setupListeners();
    renderSavedFilterChips();
    setupStatPopups();
    render();

    // Actualización de timers cada 30s
    setInterval(() => {
        render();
    }, 30000);

    // Auto-refresh: detecta picks nuevos sin necesitar F5
    startAutoRefresh();
});
