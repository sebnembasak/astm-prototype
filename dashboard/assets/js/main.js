        const API_BASE = "http://localhost:8000";

        // ── Sayfalama yardımcısı ──────────────────────────────────────────────
        // Her sayfa kendi state'ini tutar; backend'e page numarası gönderilir.
        const PAGE_LIMIT = 50; // her sayfada gösterilecek kayıt sayısı

        let satCurrentPage    = 1;
        let alertCurrentPage  = 1;
        let maneuverCurrentPage = 1;

        /**
         * containerId altına uygulamanın cam/neon temasıyla uyumlu
         * özel pagination bileşeni render eder.
         */
        function renderPagination(containerId, page, pages, total, onPage) {
            const el = document.getElementById(containerId);
            if (!el) return;

            el.style.cssText = [
                'display:flex', 'justify-content:space-between', 'align-items:center',
                'padding:10px 2px 0', 'border-top:1px solid rgba(255,255,255,0.07)',
                'margin-top:6px'
            ].join(';');

            if (pages <= 1) {
                el.innerHTML = `<small style="color:rgba(255,255,255,0.35);font-size:12px">${total.toLocaleString()} kayıt</small><span></span>`;
                return;
            }

            // Aktif sayfa ±2 + ilk/son her zaman görünür
            const visible = new Set([1, pages]);
            for (let i = Math.max(1, page - 2); i <= Math.min(pages, page + 2); i++) visible.add(i);
            const sorted = [...visible].sort((a, b) => a - b);

            const btnStyle = (active, disabled) => [
                'min-width:30px', 'height:26px', 'padding:0 6px',
                'border-radius:5px', 'font-size:12px', 'cursor:' + (disabled ? 'default' : 'pointer'),
                'transition:all 0.15s', 'margin:0 2px', 'border:1px solid',
                active
                    ? 'border-color:#00f3ff;background:rgba(0,243,255,0.15);color:#00f3ff'
                    : disabled
                        ? 'border-color:rgba(255,255,255,0.08);background:transparent;color:rgba(255,255,255,0.2)'
                        : 'border-color:rgba(255,255,255,0.12);background:transparent;color:rgba(255,255,255,0.6)',
            ].join(';');

            const navBtn = (label, targetPage, disabled) =>
                `<button onclick="if(!${disabled})(${onPage})(${targetPage})"
                    style="${btnStyle(false, disabled)}">${label}</button>`;

            let inner = navBtn('‹', page - 1, page === 1);
            let prev = 0;
            for (const p of sorted) {
                if (prev && p - prev > 1)
                    inner += `<span style="color:rgba(255,255,255,0.25);padding:0 3px;font-size:12px">…</span>`;
                const isActive = p === page;
                inner += `<button onclick="(${onPage})(${p})" ${isActive ? 'disabled' : ''}
                    style="${btnStyle(isActive, isActive)}">${p}</button>`;
                prev = p;
            }
            inner += navBtn('›', page + 1, page === pages);

            el.innerHTML = `
                <small style="color:rgba(255,255,255,0.35);font-size:12px">
                    ${total.toLocaleString()} kayıt &nbsp;·&nbsp; sayfa ${page} / ${pages}
                </small>
                <div style="display:flex;align-items:center">${inner}</div>
            `;
        }

        const NEON_COLORS = [
            '#00f3ff',
            '#bc13fe',
            '#0aff60',
            '#ffae00',
            '#ff0055',
            '#ffff00'
        ];

        let map;
        let gsMap;
        let activeLayers = {};
        let selectedAlert = null;
        let searchTimeout;
        let realtimeInterval = null;
        let colorCounter = 0;

        function updateMapLiveBadge() {
            const badge = document.getElementById('map-live-badge');
            if (!badge) return;
            if (realtimeInterval && Object.keys(activeLayers).length > 0) {
                badge.textContent = '● CANLI TAKİP';
                badge.className = 'badge bg-danger bg-opacity-25 text-danger border border-danger';
            } else {
                badge.textContent = 'Henüz uydu eklenmedi';
                badge.className = 'badge bg-secondary';
            }
        }

        function startRealtimeTracking() {
            if (realtimeInterval) return;
            realtimeInterval = setInterval(() => {
                const now = Date.now();
                Object.entries(activeLayers).forEach(([id, layer]) => {
                    if (!layer.pathData || !layer.marker) return;
                    const data = layer.pathData;

                    // Path verisinin son noktasına yaklaşıldıysa (son 10 saniye içindeyse),
                    // marker'ın orada donmaması için arka planda yeni bir yörünge parçası
                    // çekiyoruz. refreshing bayrağı eşzamanlı çift istek atılmasını önler.
                    const lastTime = new Date(data[data.length - 1].time).getTime();
                    if (!layer.refreshing && now >= lastTime - 10000) {
                        refreshSatellitePath(id);
                    }

                    // İki ardışık nokta arasında now'u bul
                    let i = 0;
                    for (; i < data.length - 1; i++) {
                        if (new Date(data[i + 1].time).getTime() >= now) break;
                    }
                    const p0 = data[i];
                    const p1 = data[Math.min(i + 1, data.length - 1)];

                    // p0 ile p1 arasında doğrusal interpolasyon (0..1)
                    const t0 = new Date(p0.time).getTime();
                    const t1 = new Date(p1.time).getTime();
                    const frac = t1 > t0 ? Math.min((now - t0) / (t1 - t0), 1) : 0;

                    const lat = p0.lat + frac * (p1.lat - p0.lat);
                    const lon = p0.lon + frac * (p1.lon - p0.lon);
                    const alt = p0.alt_km + frac * (p1.alt_km - p0.alt_km);

                    layer.marker.setLatLng([lat, lon]);
                    layer.marker.setPopupContent(
                        `<strong>${layer.meta.sat_name}</strong><br>` +
                        `Anlık: ${lat.toFixed(3)}°, ${lon.toFixed(3)}°<br>` +
                        `Yükseklik: ${alt.toFixed(1)} km<br>` +
                        `<span class="text-muted" style="font-size:0.8em">${new Date(now).toLocaleTimeString()}</span>`
                    );
                });
            }, 1000);
            updateMapLiveBadge();
        }

        function stopRealtimeTracking() {
            if (realtimeInterval) { clearInterval(realtimeInterval); realtimeInterval = null; }
            updateMapLiveBadge();
        }

        document.addEventListener('DOMContentLoaded', () => {
            initMap();
            loadDashboardStats();
            loadSatellites();

            // Açıklayıcı (i) ikonları için Bootstrap tooltip'leri etkinleştir.
            // Bootstrap 5 tooltip'leri data-bs-toggle ile işaretlenmiş olsa da
            // otomatik başlatmaz, her eleman için elle new bootstrap.Tooltip()
            // çağrılması gerekir.
            document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));
        });

        function showSection(id, btn) {
            document.querySelectorAll('.content-section').forEach(el => el.classList.add('d-none'));
            document.getElementById(id).classList.remove('d-none');

            if(btn) {
                document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
                btn.classList.add('active');
            }

            if(id === 'conjunctions') loadAlerts();
            if(id === 'map-view' && map) setTimeout(() => map.invalidateSize(), 200);
            if(id === 'ssa-panel') {
                fetchAndRenderSSAResults();
                renderSpaceRegimeHeatmap();
                checkSSAClassificationStatus();
            }
            if(id === 'maneuver-detection') loadManeuverEvents();
            if(id === 'ground-scheduling') {
                if (!gsMap) initGroundStationMap();
                else setTimeout(() => gsMap.invalidateSize(), 200);
            }
        }

        function showLoading(show, text="İşleniyor...") {
            const el = document.getElementById('loadingOverlay');
            document.getElementById('loadingText').innerText = text;
            el.style.display = show ? 'flex' : 'none';
        }

        function initMap() {
            map = L.map('map', {zoomControl: false, attributionControl: false}).setView([20, 0], 2);
            L.control.zoom({ position: 'bottomright' }).addTo(map);
            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                maxZoom: 19,
                subdomains: 'abcd'
            }).addTo(map);
        }

        document.getElementById('map-sat-search').addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            const query = e.target.value;
            if (query.length < 2) {
                document.getElementById('search-results').style.display = 'none';
                return;
            }
            searchTimeout = setTimeout(async () => {
                try {
                    const res = await fetch(`${API_BASE}/tle/search?q=${query}`);
                    const data = await res.json();
                    renderMapSearchResults(data);
                } catch(e) { console.error(e); }
            }, 300);
        });

        function renderMapSearchResults(data) {
            const container = document.getElementById('search-results');
            container.innerHTML = '';
            if(data.length === 0) { container.style.display = 'none'; return; }

            data.slice(0, 8).forEach(sat => {
                const div = document.createElement('div');
                div.className = 'search-item';
                div.innerHTML = `<i class="fas fa-satellite me-2"></i><strong>${sat.sat_name}</strong> <small class="ms-1 opacity-50">(${sat.id})</small>`;
                div.onclick = () => {
                    addSatelliteToMap(sat.id, sat.sat_name);
                    container.style.display = 'none';
                    document.getElementById('map-sat-search').value = '';
                };
                container.appendChild(div);
            });
            container.style.display = 'block';
        }

const CLUSTER_COLORS = {
    0: '#00f3ff', // LEO - Mavi
    1: '#ffae00', // MEO - Turuncu
    2: '#bc13fe', // GEO - Mor
    3: '#0aff60', // Yüksek Eğiklik - Yeşil
    4: '#ff0055'  // Diğer - Kırmızı
};
        async function fetchOrbitPath(id) {
            const pathRes = await fetch(`${API_BASE}/orbit/propagate/${id}?duration_minutes=100&step_seconds=10`);
            return await pathRes.json();
        }

        function buildOrbitSegments(pathData) {
            const latlngs = pathData.map(p => [p.lat, p.lon]);

            // Anti-meridyen (±180°) geçişlerinde tek bir noktadan diğerine
            // doğrudan çizgi çekmek haritayı boydan boya kesen sahte segmentler
            // oluşturuyordu. Ardışık noktalar arasındaki boylam farkı 180°'yi
            // aşınca yörüngeyi ayrı segmentlere bölüyoruz; L.polyline bir
            // segment dizisi (multi-polyline) verildiğinde aralarına çizgi çekmez.
            const segments = [[latlngs[0]]];
            for (let i = 1; i < latlngs.length; i++) {
                const prevLon = latlngs[i - 1][1];
                const currLon = latlngs[i][1];
                if (Math.abs(currLon - prevLon) > 180) {
                    segments.push([]);
                }
                segments[segments.length - 1].push(latlngs[i]);
            }
            return segments;
        }

        async function refreshSatellitePath(id) {
            const layer = activeLayers[id];
            if (!layer || layer.refreshing) return;
            layer.refreshing = true;
            try {
                const pathData = await fetchOrbitPath(id);
                layer.pathData = pathData;

                const newPolyline = L.polyline(buildOrbitSegments(pathData), {
                    color: layer.color,
                    weight: 3,
                    opacity: 0.8,
                    smoothFactor: 1
                }).addTo(map);
                map.removeLayer(layer.polyline);
                layer.polyline = newPolyline;
            } catch (e) {
                console.error(`Yörünge yenilenemedi (sat ${id}):`, e);
            } finally {
                layer.refreshing = false;
            }
        }

        async function addSatelliteToMap(id, name, forcedColor = null) {
            if(activeLayers[id]) {
                alert("Bu uydu zaten haritada ekli!");
                return;
            }

            showLoading(true, "Yörünge hesaplanıyor...");
            try {
                const color = forcedColor || NEON_COLORS[colorCounter % NEON_COLORS.length];
                colorCounter++;

                const metaRes = await fetch(`${API_BASE}/tle/${id}`);
                const meta = await metaRes.json();

                const pathData = await fetchOrbitPath(id);
                const latlngs = pathData.map(p => [p.lat, p.lon]);
                const currentPt = latlngs[0];
                const currentData = pathData[0];

                // GEO tespiti: irtifa > 33 000 km → jeostasyon / jeo-senkron yörünge.
                // GEO uydular Dünya'ya göre neredeyse sabit durur; yer izi 100 dk'da
                // yalnızca ~0.006° hareket eder. Bu durumda:
                //   1. Polilini çizmek yanıltıcı — görünmez düzeyde küçük bir eğri olur.
                //   2. fitBounds bu minik kutu için zoom 18+ verir; tile sunucusu boş
                //      döner ve harita siyah görünür (asıl bug).
                // Çözüm: GEO uydusuna polilini değil, yalnızca büyük bir marker ekle
                // ve haritayı zoom 2'de küresel görünümde konumlandır.
                const isGeo = currentData.alt_km > 33000;

                let polyline;
                if (isGeo) {
                    // GEO: sabit nokta etrafında görünür bir daire çiz (dekoratif, yörünge değil)
                    polyline = L.circle(currentPt, {
                        radius: 200000,  // 200 km yarıçap — haritada görünür simgesel halka
                        color: color,
                        weight: 2,
                        opacity: 0.7,
                        fill: false,
                        dashArray: '6 4'
                    }).addTo(map);
                } else {
                    polyline = L.polyline(buildOrbitSegments(pathData), {
                        color: color,
                        weight: 3,
                        opacity: 0.8,
                        smoothFactor: 1
                    }).addTo(map);
                }

                const icon = L.divIcon({
                    className: 'custom-icon',
                    html: `<div style="width:14px;height:14px;background:${color};border-radius:50%;box-shadow:0 0 12px ${color};border:2px solid white;animation:pulse 1.5s infinite;"></div>`,
                    iconSize: [14, 14]
                });
                const geoNote = isGeo ? `<br><span style="color:#a78bfa;font-size:0.8em">♦ Jeostasyon — yer izine sabit</span>` : '';
                const marker = L.marker(currentPt, {icon: icon}).addTo(map)
                    .bindPopup(
                        `<strong>${name}</strong><br>` +
                        `Anlık: ${currentPt[0].toFixed(3)}°, ${currentPt[1].toFixed(3)}°<br>` +
                        `Yükseklik: ${currentData.alt_km.toFixed(1)} km` +
                        geoNote +
                        `<br><span class="text-muted" style="font-size:0.8em">${new Date(currentData.time).toLocaleTimeString()}</span>`
                    );

                activeLayers[id] = { polyline, marker, color, meta, pathData };
                updateActiveSatList();

                // fitBounds yerine akıllı konumlandırma:
                // GEO'da bounds neredeyse sıfır → extreme zoom → tile yüklenemez (siyah harita).
                // LEO'da normal fitBounds yeterli; eğer yörünge garip küçükse yine de
                // fallback olarak zoom 2 kullan.
                if (isGeo) {
                    map.setView(currentPt, 2);
                } else {
                    const bounds = polyline.getBounds ? polyline.getBounds() : null;
                    if (bounds && bounds.isValid()) {
                        const latSpan = bounds.getNorth() - bounds.getSouth();
                        const lonSpan = bounds.getEast() - bounds.getWest();
                        if (latSpan < 5 && lonSpan < 5) {
                            // Olağandışı küçük yörünge — tile patlamasını önle
                            map.setView(currentPt, 4);
                        } else {
                            map.fitBounds(bounds, {padding: [50, 50]});
                        }
                    }
                }

                showSatDetails(id);
                startRealtimeTracking();

            } catch(e) {
                alert("Hata: " + e);
            } finally {
                showLoading(false);
            }
        }

        function removeSatellite(id) {
            if(activeLayers[id]) {
                map.removeLayer(activeLayers[id].polyline);
                map.removeLayer(activeLayers[id].marker);
                delete activeLayers[id];
                updateActiveSatList();
                document.getElementById('sat-details-panel').classList.add('d-none');
                if (Object.keys(activeLayers).length === 0) stopRealtimeTracking();
            }
        }

        function clearMap() {
            stopRealtimeTracking();
            colorCounter = 0;
            Object.keys(activeLayers).forEach(id => removeSatellite(id));
            map.eachLayer(layer => {
                if (layer instanceof L.Marker || layer instanceof L.Polyline) {
                   if(!layer._tiles) map.removeLayer(layer);
                }
            });
            activeLayers = {};
            updateActiveSatList();
        }

        function updateActiveSatList() {
            const list = document.getElementById('active-sat-list');
            const ids = Object.keys(activeLayers);

            if(ids.length === 0) {
                list.innerHTML = `<div class="text-center small mt-4"><i class="fas fa-satellite fa-2x mb-2 opacity-25"></i><br>Henüz bir uydu seçilmedi.</div>`;
                return;
            }

            list.innerHTML = '';
            ids.forEach(id => {
                const sat = activeLayers[id];
                const div = document.createElement('div');
                div.className = 'active-sat-item animate__animated animate__fadeIn';
                div.style.borderLeftColor = sat.color;
                div.innerHTML = `
                    <div onclick="showSatDetails(${id})" style="cursor:pointer; flex-grow:1;">
                        <span class="sat-color-dot" style="color:${sat.color}"></span>
                        <span class="fw-bold small">${sat.meta.sat_name}</span>
                        <small class="ms-2">${id}</small>
                    </div>
                    <button class="btn btn-sm btn-link text-secondary p-0" onclick="removeSatellite(${id})"><i class="fas fa-times"></i></button>
                `;
                list.appendChild(div);
            });
        }

        function showSatDetails(id) {
            const sat = activeLayers[id];
            if(!sat) return;

            const panel = document.getElementById('sat-details-panel');
            panel.classList.remove('d-none');
            panel.classList.add('animate__animated', 'animate__fadeInUp');

            document.getElementById('detail-name').innerText = sat.meta.sat_name;
            document.getElementById('detail-name').style.color = sat.color;
            document.getElementById('detail-id').innerText = sat.meta.id;
            document.getElementById('detail-tle').innerText = `${sat.meta.line1}\n${sat.meta.line2}`;
        }

        async function visualizeConjunction(sat1Id, sat1Name, sat2Id, sat2Name, tcaStr) {
            showSection('map-view');
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));

            clearMap();
            showLoading(true, "Çarpışma Senaryosu Oluşturuluyor...");

            try {
                await addSatelliteToMap(sat1Id, sat1Name, '#00f3ff');
                await addSatelliteToMap(sat2Id, sat2Name, '#ff0055');
                const tcaTime = new Date(tcaStr).getTime();

                const sat1Data = activeLayers[sat1Id].pathData;
                let closestPoint = null;
                let minDiff = Infinity;

                sat1Data.forEach(p => {
                    const pTime = new Date(p.time).getTime();
                    const diff = Math.abs(pTime - tcaTime);
                    if(diff < minDiff) {
                        minDiff = diff;
                        closestPoint = p;
                    }
                });

                if(closestPoint) {
                    const dangerIcon = L.divIcon({
                        className: 'pulsating-marker',
                        iconSize: [20, 20]
                    });

                    L.marker([closestPoint.lat, closestPoint.lon], {icon: dangerIcon}).addTo(map)
                        .bindPopup(`<strong class="text-danger">TAHMİNİ ÇARPIŞMA NOKTASI</strong><br>TCA: ${new Date(tcaStr).toLocaleTimeString()}`)
                        .openPopup();

                    map.setView([closestPoint.lat, closestPoint.lon], 4);
                }

            } catch(e) {
                console.error(e);
                alert("Görselleştirme hatası oluştu.");
            } finally {
                showLoading(false);
            }
        }

        let _satSearchQuery = '';

        async function loadSatellites(page = 1) {
            satCurrentPage = page;
            try {
                const url = _satSearchQuery.length >= 2
                    ? `${API_BASE}/tle/search?q=${encodeURIComponent(_satSearchQuery)}&page=${page}&limit=${PAGE_LIMIT}`
                    : `${API_BASE}/tle/list?page=${page}&limit=${PAGE_LIMIT}`;
                const res = await fetch(url);
                const data = await res.json();
                renderSatTable(data.items);
                renderPagination('sat-pagination', data.page, data.pages, data.total,
                    function(p) { loadSatellites(p); });
            } catch (e) {
                console.error("Liste yüklenirken hata:", e);
                document.getElementById('sat-table-body').innerHTML = `<tr><td colspan="4" class="text-danger">Veri yüklenemedi! API çalışıyor mu?</td></tr>`;
            }
        }

        async function searchSatellitesForList() {
            _satSearchQuery = document.getElementById('sat-list-search').value;
            loadSatellites(1);
        }

        function renderSatTable(items) {
            const tbody = document.getElementById('sat-table-body');
            tbody.innerHTML = "";
            if (!items || items.length === 0) {
                tbody.innerHTML = `<tr><td colspan="4" class="text-center">Kayıt bulunamadı.</td></tr>`;
                return;
            }
            items.forEach(s => {
                tbody.innerHTML += `
                    <tr>
                        <td class="font-mono small">${s.id}</td>
                        <td class="fw-bold">${s.sat_name}</td>
                        <td class="small" style="max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${s.source || ''}">${s.source || 'N/A'}</td>
                        <td>
                            <button class="btn btn-sm btn-outline-info" onclick="goToMapWithSat(${s.id}, '${s.sat_name}')">
                                <i class="fas fa-eye"></i> İncele
                            </button>
                        </td>
                    </tr>
                `;
            });
        }

        function goToMapWithSat(id, name) {
            showSection('map-view');
            clearMap();
            addSatelliteToMap(id, name);
        }

        let currentAlertType = "COLLISION";

        function switchAlertType(type) {
            alertCurrentPage = 1;
            currentAlertType = type;
            const card = document.getElementById('conj-card');
            const headerText = document.getElementById('conj-header-text');

            if (type === 'COLLISION') {
                card.className = "card-glass border-danger border-opacity-25";
                headerText.className = "card-header-glass text-danger";
                headerText.innerHTML = '<span><i class="fas fa-exclamation-triangle me-2"></i>Kritik Yakınlaşmalar</span>';
            } else if (type === 'FORMATION') {
                card.className = "card-glass border-warning border-opacity-25";
                headerText.className = "card-header-glass text-warning";
                headerText.innerHTML = '<span><i class="fas fa-circle-nodes me-2"></i>Formasyon Uçuşu — Eş Yörüngeli Nesneler</span>';
            } else {
                card.className = "card-glass border-info border-opacity-25";
                headerText.className = "card-header-glass text-info";
                headerText.innerHTML = '<span><i class="fas fa-link me-2"></i>Tespit Edilen Kenetlenme</span>';
            }
            loadAlerts();
        }

        async function loadAlerts(page = alertCurrentPage) {
            alertCurrentPage = page;
            try {
                // Formasyon sekmesi hem FORMATION hem GEO_NEIGHBOR kayıtlarını gösterir.
                const fetchType = currentAlertType === 'FORMATION'
                    ? 'FORMATION,GEO_NEIGHBOR'
                    : currentAlertType;
                const res = await fetch(`${API_BASE}/conjunctions/alerts?limit=${PAGE_LIMIT}&page=${page}&type=${encodeURIComponent(fetchType)}`);
                const resp = await res.json();
                const data = resp.items;
                renderPagination('conj-pagination', resp.page, resp.pages, resp.total,
                    function(p) { loadAlerts(p); });
                const tbody = document.getElementById('conj-table-body');
                tbody.innerHTML = "";

                if (!data || data.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-3">Bu kategoride kayıt bulunamadı.</td></tr>`;
                    return;
                }

                data.forEach(a => {
                    let badgeHtml, distClass, actionButtons;

                    if (a.event_type === 'DOCKING') {
                        badgeHtml  = `<span class="badge bg-info text-dark">KENETLENME</span>`;
                        distClass  = 'text-info';
                        actionButtons = `<button class="btn btn-sm btn-outline-info" onclick="visualizeConjunction(${a.sat1_id}, '${a.sat1_name}', ${a.sat2_id}, '${a.sat2_name}', '${a.tca}')"><i class="fas fa-eye me-1"></i> İzle</button>`;
                    } else if (a.event_type === 'GEO_NEIGHBOR') {
                        badgeHtml  = `<span class="badge text-white" style="background:#7c3aed;">GEO KOMŞU</span>`;
                        distClass  = 'text-secondary';
                        actionButtons = `<button class="btn btn-sm btn-outline-secondary" onclick="visualizeConjunction(${a.sat1_id}, '${a.sat1_name}', ${a.sat2_id}, '${a.sat2_name}', '${a.tca}')"><i class="fas fa-eye me-1"></i> İzle</button>`;
                    } else if (a.event_type === 'FORMATION') {
                        badgeHtml  = `<span class="badge bg-warning text-dark">FORMASYON</span>`;
                        distClass  = 'text-warning';
                        actionButtons = `<button class="btn btn-sm btn-outline-warning" onclick="visualizeConjunction(${a.sat1_id}, '${a.sat1_name}', ${a.sat2_id}, '${a.sat2_name}', '${a.tca}')"><i class="fas fa-eye me-1"></i> İzle</button>`;
                    } else {
                        const bc  = a.score >= 0.8 ? 'bg-danger' : (a.score >= 0.4 ? 'bg-warning text-dark' : 'bg-success');
                        // Math.floor: 99.77 → "99%", toFixed(0) yuvarlardı → "100%"
                        badgeHtml  = `<span class="badge ${bc}">${Math.floor(a.score * 100)}%</span>`;
                        distClass  = 'text-danger';
                        actionButtons = `<div class="btn-group">
                                <button class="btn btn-sm btn-outline-info" onclick="visualizeConjunction(${a.sat1_id}, '${a.sat1_name}', ${a.sat2_id}, '${a.sat2_name}', '${a.tca}')"><i class="fas fa-eye"></i></button>
                                <button class="btn btn-sm btn-outline-warning" onclick='openManeuverModal(${JSON.stringify(a)})'><i class="fas fa-tools"></i></button>
                           </div>`;
                    }

                    tbody.innerHTML += `
                        <tr class="animate__animated animate__fadeIn">
                            <td>${badgeHtml}</td>
                            <td>
                                <div class="fw-bold">${a.sat1_name}</div>
                                <div class="small font-mono">${a.sat1_id}</div>
                            </td>
                            <td>
                                <div class="fw-bold">${a.sat2_name}</div>
                                <div class="small font-mono">${a.sat2_id}</div>
                            </td>
                            <td class="font-mono small">${new Date(a.tca).toLocaleString()}</td>
                            <td class="fw-bold ${distClass} font-mono">${a.miss_distance_km.toFixed(4)} km</td>
                            <td>${actionButtons}</td>
                        </tr>
                    `;
                });
            } catch(e) { console.error(e); }
        }

        function openManeuverModal(alertData) {
            selectedAlert = alertData;
            document.getElementById('m-sat1').innerText = `${alertData.sat1_name} (${alertData.sat1_id})`;
            document.getElementById('m-sat2').innerText = `${alertData.sat2_name} (${alertData.sat2_id})`;
            document.getElementById('m-tca').innerText = new Date(alertData.tca).toLocaleString();
            document.getElementById('m-miss').innerText = alertData.miss_distance_km.toFixed(4);
            document.getElementById('maneuver-result').classList.add('d-none');
            const modal = new bootstrap.Modal(document.getElementById('maneuverModal'));
            modal.show();
        }

async function calculateManeuver() {
    if(!selectedAlert) return;
    const targetMiss = parseFloat(document.getElementById('target-miss').value);
     try {
        showLoading(true);
        const res = await fetch(`${API_BASE}/maneuver/calculate`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                sat_id_primary: selectedAlert.sat1_id,
                sat_id_secondary: selectedAlert.sat2_id,
                tca: selectedAlert.tca,
                target_miss_km: targetMiss
            })
        });
        const result = await res.json();
        showLoading(false);

        if (result.success) {
            document.getElementById('maneuver-result').classList.remove('d-none');
            document.getElementById('maneuver-result').classList.remove('alert-danger');
            document.getElementById('maneuver-result').classList.add('alert-dark');

            document.getElementById('res-burn').innerText = new Date(result.burn_time).toLocaleTimeString();
            document.getElementById('res-dv').innerText = result.dv_magnitude_m_s.toFixed(5) + " m/s";
            document.getElementById('res-dist').innerText = result.predicted_miss_km.toFixed(4) + " km";
            document.getElementById('res-msg').innerText = result.message;

        } else {
            document.getElementById('maneuver-result').classList.remove('d-none');
            document.getElementById('maneuver-result').classList.remove('alert-dark');
            document.getElementById('maneuver-result').classList.add('alert-danger');

            document.getElementById('res-msg').innerText = "HATA: " + (result.error_detail || result.message);
            document.getElementById('res-burn').innerText = "-";
            document.getElementById('res-dv').innerText = "-";
            document.getElementById('res-dist').innerText = "-";
        }

    } catch(e) {
        showLoading(false);
        alert("Hata: " + e);
    }
}

        async function updateTLEs() {
            showLoading(true, "Celestrak Güncelleniyor...");
            try {
                const res = await fetch(`${API_BASE}/tle/refresh`, { method: 'POST' });
                const data = await res.json();
                alert(data.message);
                loadSatellites();
            } catch(e) { alert(e); }
            finally { showLoading(false); }
        }

        async function runScreening() {
            showLoading(true, "Tarama Başlatıldı...");
            try {
                const res = await fetch(`${API_BASE}/conjunctions/run-screening`, { method: 'POST' });
                const data = await res.json();
                alert(`Analiz Bitti. İşlenen: ${data.processed_pairs}`);
                loadAlerts();
                loadDashboardStats();
            } catch(e) { alert(e); }
            finally { showLoading(false); }
        }

        async function loadDashboardStats() {
            try {
                const maneuverRes = await fetch(`${API_BASE}/maneuver-detection/events?limit=1&page=1`);
                const maneuverData = await maneuverRes.json();
                document.getElementById('stat-maneuver-count').innerText = (maneuverData.total ?? 0).toLocaleString();
            } catch(e) {
                document.getElementById('stat-maneuver-count').innerText = "--";
            }

            try {
                const countRes = await fetch(`${API_BASE}/tle/count`);
                const countData = await countRes.json();
                document.getElementById('stat-sat-count').innerText = countData.count ? countData.count.toLocaleString() : "--";
            } catch(e) {
                 document.getElementById('stat-sat-count').innerText = "--";
            }

            try {
                const resAlert = await fetch(`${API_BASE}/conjunctions/alerts?limit=5&page=1`);
                const alertResp = await resAlert.json();
                const alerts = alertResp.items ?? [];
                document.getElementById('stat-alert-count').innerText = alerts.length;

                const tbody = document.getElementById('dashboard-alerts-body');
                tbody.innerHTML = "";
                if(alerts.length === 0) {
                     tbody.innerHTML = `<tr><td colspan="4" class="text-center">Aktif uyarı yok.</td></tr>`;
                } else {
                    alerts.forEach(a => {
                        tbody.innerHTML += `
                            <tr>
                                <td class="text-info">${a.sat1_name}</td>
                                <td class="text-warning">${a.sat2_name}</td>
                                <td class="font-mono small">${new Date(a.tca).toLocaleTimeString()}</td>
                                <td><span class="badge bg-danger">${a.miss_distance_km.toFixed(2)} km</span></td>
                            </tr>`;
                    });
                }
            } catch(e) {
                 document.getElementById('stat-alert-count').innerText = "!";
                 document.getElementById('dashboard-alerts-body').innerHTML = `<tr><td colspan="4" class="text-danger text-center">Veri alınamadı</td></tr>`;
            }
        }


    async function trainSSA() {
        showLoading(true, "Yapay Zeka Modeli Eğitiliyor... (UCS Database)");
        try {
            const res = await fetch(`${API_BASE}/ssa/train`, {
                method: 'POST'
            });
            const data = await res.json();
            alert("Başarılı: " + data.message);
        } catch (e) {
            console.error("Eğitim Hatası:", e);
            alert("Model eğitilirken bir hata oluştu. Backend loglarını kontrol edin.");
        } finally {
            showLoading(false);
        }
    }

    async function runSSAAnalysis() {
        showLoading(true, "Yapay Zeka Sınıflandırması Yapılıyor...");
        try {
            const res = await fetch(`${API_BASE}/ssa/run-analysis`, { method: 'POST' });
            const data = await res.json();
            alert(`Analiz Bitti! ${data.processed_satellites} uydu sınıflandırıldı.`);
            await fetchAndRenderSSAResults();
            await renderSpaceRegimeHeatmap();
            await checkSSAClassificationStatus();
        } catch (e) {
            alert("Hata: " + e);
        } finally {
            showLoading(false);
        }
    }

    async function checkSSAClassificationStatus() {
        const banner = document.getElementById('ssa-pending-banner');
        if (!banner) return;
        try {
            const res = await fetch(`${API_BASE}/ssa/status`);
            const { pending, total } = await res.json();
            if (pending > 0) {
                const pct = Math.round((pending / total) * 100);
                banner.style.cssText = [
                    'display:flex', 'align-items:center', 'gap:12px',
                    'padding:10px 16px', 'border-radius:8px', 'margin-bottom:12px',
                    'background:rgba(255,174,0,0.1)', 'border:1px solid rgba(255,174,0,0.35)'
                ].join(';');
                banner.innerHTML = `
                    <i class="fas fa-exclamation-triangle" style="color:#ffae00;font-size:18px;flex-shrink:0"></i>
                    <div style="flex:1">
                        <div style="color:#ffae00;font-weight:600;font-size:13px">
                            ${pending.toLocaleString()} uydu sınıflandırılmadı
                        </div>
                        <div style="color:rgba(255,255,255,0.5);font-size:12px">
                            Toplam ${total.toLocaleString()} uydunun %${pct}'i henüz analiz edilmedi.
                            TLE güncellemesinden sonra "Kataloğu Sınıflandır" butonunu çalıştırın.
                        </div>
                    </div>
                    <button onclick="runSSAAnalysis()" style="
                        padding:5px 14px;border-radius:6px;border:1px solid #ffae00;
                        background:rgba(255,174,0,0.15);color:#ffae00;font-size:12px;cursor:pointer
                    ">Şimdi Sınıflandır</button>
                `;
            } else {
                banner.style.display = 'none';
                banner.innerHTML = '';
            }
        } catch(e) { /* sessiz hata */ }
    }

    const MANEUVER_TYPE_BADGES = {
        ALTITUDE_CHANGE: { class: 'bg-warning text-dark', label: 'İrtifa Değişimi' },
        INCLINATION_CHANGE: { class: 'bg-danger', label: 'Eğim Değişimi' },
        ECCENTRICITY_CHANGE: { class: 'bg-info text-dark', label: 'Eksantriklik Değişimi' },
        ORBIT_ADJUSTMENT: { class: 'bg-secondary', label: 'Yörünge Ayarı' },
        COMBINED: { class: '', label: 'Kombine', style: 'background-color: var(--accent-magenta);' }
    };

    async function loadManeuverEvents(page = maneuverCurrentPage) {
        maneuverCurrentPage = page;
        const tbody = document.getElementById('maneuver-events-body');
        try {
            const res = await fetch(`${API_BASE}/maneuver-detection/events?limit=${PAGE_LIMIT}&page=${page}`);
            const resp = await res.json();
            const data = resp.items;
            renderPagination('maneuver-pagination', resp.page, resp.pages, resp.total,
                function(p) { loadManeuverEvents(p); });
            tbody.innerHTML = "";

            if (!data || data.length === 0) {
                tbody.innerHTML = `<tr><td colspan="8" class="text-center py-3">Tespit edilen manevra yok.</td></tr>`;
                return;
            }

            data.forEach(ev => {
                const badge = MANEUVER_TYPE_BADGES[ev.maneuver_type] || { class: 'bg-secondary', label: ev.maneuver_type };
                const conf = (ev.confidence * 100).toFixed(0);

                tbody.innerHTML += `
                    <tr class="animate__animated animate__fadeIn">
                        <td>
                            <div class="fw-bold">${ev.sat_name}</div>
                            <div class="small font-mono">${ev.norad_id}</div>
                        </td>
                        <td><span class="badge ${badge.class}" ${badge.style ? `style="${badge.style}"` : ''}>${badge.label}</span></td>
                        <td class="font-mono small">${new Date(ev.epoch_before).toLocaleString()} → ${new Date(ev.epoch_after).toLocaleString()}</td>
                        <td class="font-mono">${ev.delta_semi_major_km.toFixed(3)}</td>
                        <td class="font-mono">${ev.delta_inclination_deg.toFixed(4)}</td>
                        <td class="font-mono">${ev.delta_eccentricity.toFixed(6)}</td>
                        <td class="font-mono text-warning">${ev.estimated_dv_m_s.toFixed(3)}</td>
                        <td>
                            <div class="d-flex align-items-center">
                                <div class="progress flex-grow-1 me-2" style="height: 4px; background: rgba(255,255,255,0.1);">
                                    <div class="progress-bar bg-warning" style="width: ${conf}%"></div>
                                </div>
                                <small class="font-mono">%${conf}</small>
                            </div>
                        </td>
                    </tr>`;
            });
        } catch(e) {
            console.error("Manevra Tespiti Tablo Hatası:", e);
            tbody.innerHTML = `<tr><td colspan="8" class="text-danger text-center">Veri alınamadı</td></tr>`;
        }
    }

    async function runManeuverDetection() {
        showLoading(true, "Manevra Tespiti Taraması Yapılıyor...");
        try {
            const res = await fetch(`${API_BASE}/maneuver-detection/run`, { method: 'POST' });
            const data = await res.json();
            alert(`Tarama Bitti. Yeni tespit edilen manevra: ${data.new_events}`);
            await loadManeuverEvents();
        } catch (e) {
            alert("Hata: " + e);
        } finally {
            showLoading(false);
        }
    }

    // KÜME ANLAMLARI ---
    // cluster_id -> {name, color, icon}: GMM her eğitimde küme ID'lerini farklı
    // sırayla atayabildiği için bu eşleme backend'de küme merkezlerinden dinamik
    // hesaplanır (bkz. ssa_service._build_regime_map) ve /ssa/regimes'ten alınır.
    let SSA_REGIMES = {};

    async function fetchSSARegimes() {
        try {
            const res = await fetch(`${API_BASE}/ssa/regimes`);
            const data = await res.json();
            // JSON anahtarları string gelir; cluster_id sayısal karşılaştırmalarla
            // (örn. item.cluster_id) tutarlı kalması için sayıya çeviriyoruz.
            SSA_REGIMES = {};
            Object.entries(data).forEach(([cid, regime]) => { SSA_REGIMES[Number(cid)] = regime; });
        } catch (e) { console.error("Rejim Eşlemesi Hatası:", e); }
    }

    async function fetchAndRenderSSAResults() {
        const tbody = document.getElementById('ssa-results-body');
        try {
            if (Object.keys(SSA_REGIMES).length === 0) await fetchSSARegimes();
            const res = await fetch(`${API_BASE}/ssa/results`);
            const data = await res.json();
            tbody.innerHTML = "";

            data.forEach(item => {
                const conf = (item.confidence * 100).toFixed(1);
                const regime = SSA_REGIMES[item.cluster_id] || { name: "Tanımsız Bölge", color: "#666", icon: "fa-question" };
                const riskClass = item.decay_risk === 'KRİTİK' ? 'bg-danger animate__animated animate__flash animate__infinite' :
                                 (item.decay_risk === 'ORTA' ? 'bg-warning text-dark' : 'bg-success opacity-50');

                tbody.innerHTML += `
                    <tr class="animate__animated animate__fadeIn">
                        <td>
                            <div class="fw-bold text-white">
                                <i class="fas ${item.is_anomaly ? 'fa-exclamation-triangle text-danger' : 'fa-check-shield text-success'} me-2"></i>
                                ${item.sat_name}
                            </div>
                            <div class="small text-info opacity-75">
                              ${item.predicted_country === 'Bilinmiyor' ? '' : (" " + item.predicted_country || '')}
                            </div>

                        </td>
                        <td>
                            <div class="small" style="color: ${regime.color}">
                                <i class="fas ${regime.icon} me-1"></i> ${regime.name}
                            </div>
                        </td>
                        <td><span class="badge border border-info text-info">${item.predicted_category}</span></td>
                        <td><span class="badge ${riskClass}" style="font-size:0.65rem">${item.decay_risk}</span></td>
                        <td>
                            <div class="d-flex align-items-center">
                                <div class="progress flex-grow-1 me-2" style="height: 4px; background: rgba(255,255,255,0.1);">
                                    <div class="progress-bar bg-info" style="width: ${conf}%"></div>
                                </div>
                                <small class="font-mono">%${conf}</small>
                            </div>
                        </td>
                    </tr>`;
            });
        } catch (e) { console.error("SSA Tablo Hatası:", e); }
    }

    async function renderSpaceRegimeHeatmap() {
        const canvas = document.getElementById('regimeHeatmapChart');
        if (!canvas) return;
        try {
            if (Object.keys(SSA_REGIMES).length === 0) await fetchSSARegimes();
            const res = await fetch(`${API_BASE}/ssa/heatmap`);
            const points = await res.json();

            // Her noktayı küme rengine göre grupla (henüz sınıflandırılmamışlar gri)
            const datasets = {};
            points.forEach(p => {
                const regime = SSA_REGIMES[p.cluster_id];
                const key = (p.cluster_id === null || p.cluster_id === undefined) ? 'unknown' : p.cluster_id;
                if (!datasets[key]) {
                    datasets[key] = {
                        label: regime ? regime.name : 'Sınıflandırılmamış',
                        data: [],
                        backgroundColor: regime ? regime.color : 'rgba(255,255,255,0.25)',
                        pointRadius: 3
                    };
                }
                datasets[key].data.push({ x: p.x, y: p.y });
            });

            const ctx = canvas.getContext('2d');
            if (window.heatmapChartObj) window.heatmapChartObj.destroy();
            window.heatmapChartObj = new Chart(ctx, {
                type: 'scatter',
                data: { datasets: Object.values(datasets) },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            title: { display: true, text: 'Eğim (derece)', color: 'rgba(255,255,255,0.6)' },
                            ticks: { color: 'rgba(255,255,255,0.5)' },
                            grid: { color: 'rgba(255,255,255,0.05)' }
                        },
                        y: {
                            // Gerçek uydu popülasyonu LEO'da (200-2000km) yoğunlaşır; GEO/MEO
                            // noktaları 30.000+ km'de tekil kalır. Doğrusal eksende bu, LEO
                            // noktalarının tamamının görsel olarak Y=0'a yapışmasına yol açar
                            // (hesaplama hatası değil — gerçek dağılımın doğrusal ölçekte
                            // görselleştirme sorunu). Logaritmik eksen tüm rejimleri ayırt
                            // edilebilir kılar.
                            type: 'logarithmic',
                            min: 150,
                            title: { display: true, text: 'İrtifa (km, log ölçek)', color: 'rgba(255,255,255,0.6)' },
                            ticks: { color: 'rgba(255,255,255,0.5)' },
                            grid: { color: 'rgba(255,255,255,0.05)' }
                        }
                    },
                    plugins: {
                        legend: { labels: { color: 'rgba(255,255,255,0.7)', font: { size: 10 } } }
                    }
                }
            });
        } catch (e) { console.error("Heatmap Hatası:", e); }
    }


    function createPredictionBox() {
        const panel = document.getElementById('sat-details-panel');
        const div = document.createElement('div');
        div.id = 'detail-ai-prediction';
        panel.appendChild(div);
        return div;
    }


    async function loadPerformanceReport() {
        try {
            const res = await fetch(`${API_BASE}/ssa/performance-report`);
            if (!res.ok) return;
            const data = await res.json();
            document.getElementById('performance-report-content').classList.remove('d-none');
            document.getElementById('report-placeholder').classList.add('d-none');
            document.getElementById('m-accuracy').innerText = `%${(data.accuracy * 100).toFixed(1)}`;
            document.getElementById('m-f1').innerText = data.f1_score.toFixed(3);
            document.getElementById('m-samples').innerText = data.sample_size.toLocaleString();

            // Hata Payı Hesabı
            const errorRate = ((1 - data.accuracy) * 100).toFixed(1);
            if(document.getElementById('m-error')) {
                document.getElementById('m-error').innerText = `%${errorRate}`;
            }

            const dbStatsContainer = document.getElementById('db-stats-content');
            if (dbStatsContainer) {
                dbStatsContainer.innerHTML = `
                    <div class="d-flex justify-content-between mb-1"><span>Veri Kaynağı:</span><span class="text-info font-mono">UCS Database</span></div>
                    <div class="d-flex justify-content-between mb-1"><span>Toplam Sınıf:</span><span class="text-info font-mono">${data.classes.length} Birim</span></div>
                    <div class="d-flex justify-content-between mb-1"><span>Özellik (Features):</span><span class="text-info font-mono">${Object.keys(data.feature_importance).length} Parametre</span></div>
                    <div class="d-flex justify-content-between"><span>Eğitim Tarihi:</span><span class="text-info font-mono" style="font-size:0.6rem;">${new Date(data.timestamp).toLocaleString()}</span></div>
                `;
            }

            const reportBody = document.getElementById('class-report-body');
            if (reportBody) {
                reportBody.innerHTML = "";
                Object.entries(data.classification_report).forEach(([className, metrics]) => {
                    // 'accuracy', 'macro avg' gibi genel satırları atla, sadece sınıfları al
                    if (typeof metrics === 'object' && !['accuracy', 'macro avg', 'weighted avg'].includes(className)) {
                        reportBody.innerHTML += `
                            <tr class="border-bottom border-secondary border-opacity-10">
                                <td class="fw-bold text-info" style="max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${className}">${className}</td>
                                <td class="font-mono">${metrics.precision.toFixed(2)}</td>
                                <td class="font-mono text-warning">${metrics.recall.toFixed(2)}</td>
                                <td class="font-mono text-success">${metrics['f1-score'].toFixed(2)}</td>
                                <td class="font-mono opacity-50">${metrics.support}</td>
                            </tr>`;
                    }
                });
            }

            const ctxRadar = document.getElementById('metricsRadarChart').getContext('2d');
            if(window.radarChartObj) window.radarChartObj.destroy();
            window.radarChartObj = new Chart(ctxRadar, {
                type: 'radar',
                data: {
                    labels: ['Accuracy', 'F1-Score', 'ROC AUC', 'Recall (Avg)', 'Precision (Avg)'],
                    datasets: [{
                        label: 'Performans Değerleri',
                        data: [
                            data.accuracy,
                            data.f1_score,
                            data.roc_auc,
                            data.classification_report['macro avg'].recall,
                            data.classification_report['macro avg'].precision
                        ],
                        backgroundColor: 'rgba(0, 243, 255, 0.2)',
                        borderColor: '#00f3ff',
                        pointBackgroundColor: '#00f3ff',
                        borderWidth: 2
                    }]
                },
                options: {
                    scales: {
                        r: {
                            min: 0, max: 1,
                            ticks: { display: false },
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            angleLines: { color: 'rgba(255,255,255,0.1)' }
                        }
                    },
                    plugins: { legend: { display: false } }
                }
            });

            const cmContainer = document.getElementById('cm-container');
            if (cmContainer) {
                let cmHtml = '<table class="table table-bordered table-sm text-center m-0" style="border-color: #334155; font-size: 0.65rem;"><thead><tr><th></th>';
                data.classes.forEach(c => {
                    const shortName = c.length > 5 ? c.substring(0, 5) + '.' : c;
                    cmHtml += `<th class="p-1 text-info opacity-75" title="${c}">${shortName}</th>`;
                });
                cmHtml += '</tr></thead><tbody>';

                data.confusion_matrix.forEach((row, i) => {
                    const rowLabel = data.classes[i].length > 5 ? data.classes[i].substring(0, 5) + '.' : data.classes[i];
                    cmHtml += `<tr><th class="p-1 text-info opacity-75" style="text-align:left" title="${data.classes[i]}">${rowLabel}</th>`;
                    row.forEach((val, j) => {
                        // Isı haritası rengi (Doğru tahminler mavi tonlarında, yanlışlar kırmızımsı)
                        const maxInRow = Math.max(...row) || 1;
                        const intensity = Math.min(val / maxInRow, 1);
                        const bgColor = i === j
                            ? `rgba(0, 243, 255, ${0.1 + intensity * 0.6})`
                            : (val > 0 ? `rgba(255, 0, 85, ${0.1 + intensity * 0.3})` : 'transparent');

                        cmHtml += `<td style="background: ${bgColor}; color: ${val > 0 ? 'white' : 'rgba(255,255,255,0.1)'}; font-weight: ${i === j ? 'bold' : 'normal'}">${val}</td>`;
                    });
                    cmHtml += '</tr>';
                });
                cmHtml += '</tbody></table>';
                cmContainer.innerHTML = cmHtml;
            }

            const container = document.getElementById("feature-bars");
            if (container) {
                container.innerHTML = "";
                Object.entries(data.feature_importance).sort((a,b) => b[1] - a[1]).forEach(([feat, val]) => {
                    const pct = (val * 100).toFixed(1);
                    container.innerHTML += `
                        <div class="mb-2">
                            <div class="d-flex justify-content-between small text-white mb-1">
                                <span>${feat}</span>
                                <span class="text-info fw-bold">%${pct}</span>
                            </div>
                            <div class="progress" style="height:5px; background: rgba(255,255,255,0.05)">
                                <div class="progress-bar bg-info" style="width: ${pct}%; box-shadow: 0 0 10px rgba(0,243,255,0.5)"></div>
                            </div>
                        </div>`;
                });
            }

        } catch (e) {
            console.error("Metrik Yükleme Hatası:", e);
            alert("Teknik rapor yüklenirken bir hata oluştu. Lütfen önce modeli eğitin.");
        }

    }

    // ============== Yer İstasyonu Kapasite Planlama ==============

    async function initGroundStationMap() {
        gsMap = L.map('gs-map', {zoomControl: true, attributionControl: false}).setView([20, 20], 2);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            maxZoom: 19,
            subdomains: 'abcd'
        }).addTo(gsMap);

        try {
            const res = await fetch(`${API_BASE}/ground-scheduling/candidate-stations`);
            const stations = await res.json();
            stations.forEach(s => {
                L.circleMarker([s.lat_deg, s.lon_deg], {
                    radius: 7, color: '#00f3ff', fillColor: '#00f3ff', fillOpacity: 0.6, weight: 2
                }).addTo(gsMap).bindPopup(`<strong>${s.name}</strong><br>Yer İstasyonu (Aday)`);
            });
        } catch (e) { console.error("İstasyon haritası yüklenemedi:", e); }

        try {
            const satRes = await fetch(`${API_BASE}/tle/list?limit=30`);
            const sats = await satRes.json();
            for (const sat of sats.slice(0, 15)) {
                try {
                    const pathRes = await fetch(`${API_BASE}/orbit/propagate/${sat.id}?duration_minutes=1&step_seconds=1`);
                    const path = await pathRes.json();
                    if (path && path.length) {
                        L.circleMarker([path[0].lat, path[0].lon], {
                            radius: 3, color: '#0aff60', fillColor: '#0aff60', fillOpacity: 0.8, weight: 1
                        }).addTo(gsMap).bindPopup(`<strong>${sat.sat_name}</strong><br>Uydu`);
                    }
                } catch (e) { /* tekil uydu hatasını yut, haritanın kalanı yüklensin */ }
            }
        } catch (e) { console.error("Uydu görselleştirme yüklenemedi:", e); }
    }

    function renderGroundScenarioStats(result) {
        document.getElementById('gs-total-passes').innerText = result.total_passes;
        document.getElementById('gs-missed-passes').innerText = result.missed_passes;
        document.getElementById('gs-loss-pct').innerText = `%${result.capacity_loss_pct.toFixed(1)}`;

        const unreachable = (result.additional_stations_for_target === null || result.additional_stations_for_target === undefined);
        const extraEl = document.getElementById('gs-extra-stations');
        extraEl.innerText = unreachable ? 'Havuz Yetersiz' : `+${result.additional_stations_for_target} İstasyon`;
        // Renk semantiği sonuca göre: hedefe ulaşılabiliyorsa yeşil (başarı), ulaşılamıyorsa
        // sarı (uyarı) — "Havuz Yetersiz" olumsuz bir bulgu olduğu için yeşil göstermek yanıltıcıydı.
        extraEl.className = `h3 fw-bold my-1 ${unreachable ? 'text-warning' : 'text-success'}`;

        const noteEl = document.getElementById('gs-extra-stations-note');
        const path = result.additional_stations_path;
        if (!path || path.length === 0) {
            noteEl.innerText = '';
        } else if (unreachable) {
            noteEl.innerText = `En iyi sırayla (${path.join(' → ')}) bile mevcut ${path.length} adayla ulaşılamıyor`;
        } else {
            noteEl.innerText = `Seçilen sıra: ${path.join(' → ')}`;
        }
    }

    async function runGroundScenario() {
        const numSatellites = parseInt(document.getElementById('gs-num-satellites').value, 10);
        const numStations = parseInt(document.getElementById('gs-num-stations').value, 10);
        const durationHours = parseInt(document.getElementById('gs-duration-hours').value, 10);

        showLoading(true, "Geçiş pencereleri hesaplanıyor...");
        try {
            const res = await fetch(`${API_BASE}/ground-scheduling/scenario?num_satellites=${numSatellites}&num_stations=${numStations}&duration_hours=${durationHours}`);
            if (!res.ok) throw new Error(await res.text());
            const result = await res.json();
            renderGroundScenarioStats(result);
        } catch (e) {
            console.error("Senaryo hatası:", e);
            alert("Senaryo çalıştırılırken bir hata oluştu.");
        } finally {
            showLoading(false);
        }
    }

    async function runGroundScenarioGrid() {
        showLoading(true, "Senaryo ızgarası taranıyor (3/10/30/80 uydu × 1/2/3 istasyon)...");
        try {
            const res = await fetch(`${API_BASE}/ground-scheduling/scenarios`);
            if (!res.ok) throw new Error(await res.text());
            const results = await res.json();
            renderGroundScenarioTable(results);
            renderGroundScenarioChart(results);
        } catch (e) {
            console.error("Senaryo ızgarası hatası:", e);
            alert("Senaryo ızgarası çalıştırılırken bir hata oluştu.");
        } finally {
            showLoading(false);
        }
    }

    function renderGroundScenarioTable(results) {
        const body = document.getElementById('gs-scenario-table-body');
        body.innerHTML = "";
        results.forEach((r, i) => {
            const unreachable = (r.additional_stations_for_target === null || r.additional_stations_for_target === undefined);
            const extra = unreachable ? '<span class="text-secondary">Havuz Yetersiz</span>' : `+${r.additional_stations_for_target}`;
            const path = r.additional_stations_path;

            let pathCell;
            if (!path || path.length === 0) {
                pathCell = '<span class="opacity-50">—</span>';
            } else {
                // Greedy'nin gerçekten en iyiyi seçip seçmediğini görünür kılmak için
                // istasyon adlarını sıra numarasıyla birlikte, kutup-bölgesi istasyonları
                // (Svalbard/Punta Arenas/Reykjavik/Fairbanks) işaretlenmiş şekilde listeliyoruz.
                const POLAR_STATIONS = ['Svalbard', 'Punta Arenas', 'Reykjavik', 'Fairbanks'];
                const steps = path.map((name, idx) => {
                    const isPolar = POLAR_STATIONS.includes(name);
                    return `<span class="badge ${isPolar ? 'bg-warning text-dark' : 'bg-secondary'} bg-opacity-75 me-1 mb-1" `
                         + `title="${isPolar ? 'Kutup-bölgesi istasyonu — SSO uydularını her turda görür' : 'Orta/düşük enlem istasyonu'}" `
                         + `data-bs-toggle="tooltip">${idx + 1}. ${name}</span>`;
                });
                pathCell = `<div style="max-width: 360px; line-height: 1.9;">${steps.join('')}</div>`;
            }

            body.innerHTML += `
                <tr>
                    <td>${r.num_satellites}</td>
                    <td>${r.num_stations}</td>
                    <td>${r.total_passes}</td>
                    <td class="text-danger">${r.missed_passes}</td>
                    <td class="text-warning">%${r.capacity_loss_pct.toFixed(1)}</td>
                    <td>${extra}</td>
                    <td>${pathCell}</td>
                </tr>`;
        });
        // Yeni eklenen rozet tooltip'lerini etkinleştir (tablo dinamik olarak
        // yeniden oluşturulduğu için DOMContentLoaded'daki tek seferlik init bunları kapsamıyor).
        body.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));
    }

    function renderGroundScenarioChart(results) {
        const canvas = document.getElementById('gsScenarioChart');
        if (!canvas) return;

        const satCounts = [...new Set(results.map(r => r.num_satellites))].sort((a, b) => a - b);
        const stationCounts = [...new Set(results.map(r => r.num_stations))].sort((a, b) => a - b);

        const datasets = stationCounts.map((stationCount, idx) => ({
            label: `${stationCount} İstasyon`,
            data: satCounts.map(satCount => {
                const match = results.find(r => r.num_satellites === satCount && r.num_stations === stationCount);
                return match ? match.capacity_loss_pct : null;
            }),
            backgroundColor: NEON_COLORS[idx % NEON_COLORS.length],
            borderColor: NEON_COLORS[idx % NEON_COLORS.length],
            borderWidth: 1
        }));

        const ctx = canvas.getContext('2d');
        if (window.gsScenarioChartObj) window.gsScenarioChartObj.destroy();
        window.gsScenarioChartObj = new Chart(ctx, {
            type: 'bar',
            data: { labels: satCounts.map(c => `${c} Uydu`), datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { ticks: { color: 'rgba(255,255,255,0.6)' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                    y: {
                        title: { display: true, text: 'Kapasite Kaybı (%)', color: 'rgba(255,255,255,0.6)' },
                        ticks: { color: 'rgba(255,255,255,0.5)' },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    }
                },
                plugins: {
                    legend: { labels: { color: 'rgba(255,255,255,0.7)', font: { size: 10 } } }
                }
            }
        });
    }

    // ════════════════════════════════════════════════════════════════════════
    // BAKIM ETKİ ANALİZİ
    // ════════════════════════════════════════════════════════════════════════

    function _maintSetState(state) {
        // state: 'empty' | 'loading' | 'results'
        document.getElementById('maint-empty').classList.toggle('d-none',   state !== 'empty');
        document.getElementById('maint-loading').classList.toggle('d-none', state !== 'loading');
        document.getElementById('maint-results').classList.toggle('d-none', state !== 'results');
    }

    async function runMaintenanceAnalysis() {
        const stationName  = document.getElementById('maint-station').value;
        const durationHrs  = parseFloat(document.getElementById('maint-duration').value);
        const satLimit     = parseInt(document.getElementById('maint-sat-limit').value, 10);

        if (!stationName || isNaN(durationHrs) || durationHrs <= 0) {
            alert('Lütfen geçerli bir istasyon ve süre girin.');
            return;
        }

        _maintSetState('loading');

        const payload = {
            station_name: stationName,
            duration_hours: durationHrs,
            priority_satellite_norad_ids: null,
            satellite_limit: satLimit
        };

        try {
            const res = await fetch(`${API_BASE}/maintenance/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: res.statusText }));
                throw new Error(err.detail || res.statusText);
            }

            const data = await res.json();
            _renderMaintenanceResults(data);
            _maintSetState('results');

        } catch (e) {
            console.error('Bakım analiz hatası:', e);
            _maintSetState('empty');
            alert('Analiz sırasında hata: ' + e.message);
        }
    }

    function _fmtWindow(startUtc, endUtc) {
        // "26 Haz 14:00 → 18:00 UTC" gibi kısa format
        const s = new Date(startUtc);
        const e = new Date(endUtc);
        const dateStr = s.toLocaleDateString('tr-TR', { day:'numeric', month:'short' });
        const sTime   = s.toISOString().slice(11, 16);
        const eTime   = e.toISOString().slice(11, 16);
        return `${dateStr} ${sTime} → ${eTime} UTC`;
    }

    function _renderMaintenanceResults(data) {
        // Özet istatistikler
        document.getElementById('maint-stat-passes').textContent  = data.total_passes_in_period;
        document.getElementById('maint-stat-contact').textContent = data.total_contact_minutes.toFixed(0);
        document.getElementById('maint-stat-windows').textContent = data.candidate_windows_evaluated;
        document.getElementById('maint-stat-compute').textContent =
            `${data.total_satellites_analyzed} uydu · ${data.computation_time_s}s`;

        // En İyi Zaman Aralıkları
        const bestBody = document.getElementById('maint-best-body');
        bestBody.innerHTML = '';
        data.best_windows.forEach(w => {
            const noPassBadge = w.passes_lost === 0
                ? '<span class="badge bg-success bg-opacity-25 text-success ms-2">Sıfır Kayıp</span>'
                : '';
            bestBody.innerHTML += `
                <tr style="background: rgba(10,255,96,0.07);">
                    <td class="fw-bold text-success">#${w.rank}</td>
                    <td class="font-mono small">
                        ${_fmtWindow(w.start_utc, w.end_utc)}${noPassBadge}
                    </td>
                    <td class="text-center">
                        <span class="badge ${w.passes_lost === 0 ? 'bg-success' : 'bg-warning text-dark'} bg-opacity-25">
                            ${w.passes_lost}
                        </span>
                    </td>
                    <td class="text-center">
                        <span class="${w.contact_minutes_lost === 0 ? 'text-success' : 'text-warning'}">
                            ${w.contact_minutes_lost.toFixed(1)} dk
                        </span>
                    </td>
                    <td class="text-end font-mono">
                        <span class="text-success fw-bold">${w.cost_score.toFixed(0)}</span>
                    </td>
                </tr>`;
        });
        if (!data.best_windows.length) {
            bestBody.innerHTML = '<tr><td colspan="5" class="text-center opacity-50">Sonuç yok</td></tr>';
        }

        // En Kötü Zaman Aralıkları
        const worstBody = document.getElementById('maint-worst-body');
        worstBody.innerHTML = '';
        data.worst_windows.forEach(w => {
            worstBody.innerHTML += `
                <tr style="background: rgba(255,42,42,0.07);">
                    <td class="fw-bold text-danger">#${w.rank}</td>
                    <td class="font-mono small">${_fmtWindow(w.start_utc, w.end_utc)}</td>
                    <td class="text-center">
                        <span class="badge bg-danger bg-opacity-25 text-danger">${w.passes_lost}</span>
                    </td>
                    <td class="text-center text-danger">${w.contact_minutes_lost.toFixed(1)} dk</td>
                    <td class="text-end font-mono">
                        <span class="text-danger fw-bold">${w.cost_score.toFixed(0)}</span>
                    </td>
                </tr>`;
        });
        if (!data.worst_windows.length) {
            worstBody.innerHTML = '<tr><td colspan="5" class="text-center opacity-50">Sonuç yok</td></tr>';
        }

        // Uydu Ağırlık Detayları
        const weightsBody = document.getElementById('maint-weights-body');
        weightsBody.innerHTML = '';
        const weightColor = { 3.0: 'text-danger', 2.0: 'text-warning', 1.0: 'text-success' };
        (data.satellite_weight_details || []).forEach(d => {
            const lifetimeStr = d.estimated_lifetime_days != null
                ? `${d.estimated_lifetime_days.toFixed(0)} gün`
                : '<span class="opacity-40">—</span>';
            const srcBadge = d.bstar_source === 'regression'
                ? `<span class="badge bg-info bg-opacity-25 text-info">Regresyon <span class="opacity-75">${d.bstar_history_points}pt</span></span>`
                : `<span class="badge bg-secondary bg-opacity-25 text-secondary">Anlık TLE</span>`;
            const wClass = weightColor[d.weight] || 'text-white';
            weightsBody.innerHTML += `
                <tr>
                    <td>${d.sat_name}</td>
                    <td class="text-center font-mono">${d.altitude_km.toFixed(0)} km</td>
                    <td class="text-center font-mono">${d.bstar.toExponential(2)}</td>
                    <td class="text-center">${lifetimeStr}</td>
                    <td class="text-center fw-bold ${wClass}">${d.weight.toFixed(1)}</td>
                    <td class="text-center">${srcBadge}</td>
                </tr>`;
        });
        if (!data.satellite_weight_details || !data.satellite_weight_details.length) {
            weightsBody.innerHTML = '<tr><td colspan="6" class="text-center opacity-50">Veri yok</td></tr>';
        }
    }
