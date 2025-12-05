        const API_BASE = "http://localhost:8000";

        const NEON_COLORS = [
            '#00f3ff',
            '#bc13fe',
            '#0aff60',
            '#ffae00',
            '#ff0055',
            '#ffff00'
        ];

        let map;
        let activeLayers = {};
        let selectedAlert = null;
        let searchTimeout;

        document.addEventListener('DOMContentLoaded', () => {
            initMap();
            loadDashboardStats();
            loadSatellites();
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

        async function addSatelliteToMap(id, name, forcedColor = null) {
            if(activeLayers[id]) {
                alert("Bu uydu zaten haritada ekli!");
                return;
            }

            showLoading(true, "Yörünge hesaplanıyor...");
            try {
                const metaRes = await fetch(`${API_BASE}/tle/${id}`);
                const meta = await metaRes.json();

                const pathRes = await fetch(`${API_BASE}/orbit/propagate/${id}?duration_minutes=100&step_seconds=60`);
                const pathData = await pathRes.json();

                const colorIndex = Object.keys(activeLayers).length % NEON_COLORS.length;
                const color = forcedColor || NEON_COLORS[colorIndex];

                const latlngs = pathData.map(p => [p.lat, p.lon]);

                const polyline = L.polyline(latlngs, {
                    color: color,
                    weight: 3,
                    opacity: 0.8,
                    smoothFactor: 1
                }).addTo(map);

                const endPt = latlngs[latlngs.length - 1];
                const icon = L.divIcon({
                    className: 'custom-icon',
                    html: `<div style="width:12px;height:12px;background:${color};border-radius:50%;box-shadow:0 0 10px ${color};border:2px solid white;"></div>`,
                    iconSize: [12, 12]
                });
                const marker = L.marker(endPt, {icon: icon}).addTo(map)
                    .bindPopup(`<strong>${name}</strong><br>Lat: ${endPt[0].toFixed(2)}, Lon: ${endPt[1].toFixed(2)}`);

                activeLayers[id] = { polyline, marker, color, meta, pathData };
                updateActiveSatList();
                map.fitBounds(polyline.getBounds(), {padding: [50, 50]});
                showSatDetails(id);

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
            }
        }

        function clearMap() {
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

        async function loadDashboardStats() {
            try {
                const res = await fetch(`${API_BASE}/tle/list?limit=1`);
                document.getElementById('stat-sat-count').innerText = "12,540";

                const resAlert = await fetch(`${API_BASE}/conjunctions/alerts?limit=5`);
                const alerts = await resAlert.json();
                document.getElementById('stat-alert-count').innerText = alerts.length;

                const tbody = document.getElementById('dashboard-alerts-body');
                tbody.innerHTML = "";
                alerts.forEach(a => {
                    tbody.innerHTML += `
                        <tr>
                            <td class="text-info">${a.sat1_name}</td>
                            <td class="text-warning">${a.sat2_name}</td>
                            <td class="font-mono small">${new Date(a.tca).toLocaleTimeString()}</td>
                            <td><span class="badge bg-danger">${a.miss_distance_km.toFixed(2)} km</span></td>
                        </tr>`;
                });
            } catch(e) {}
        }

        async function loadSatellites() {
            try {
                const res = await fetch(`${API_BASE}/tle/list?limit=50`);
                const data = await res.json();
                renderSatTable(data);
            } catch (e) {
                console.error("Liste yüklenirken hata:", e);
                document.getElementById('sat-table-body').innerHTML = `<tr><td colspan="4" class="text-danger">Veri yüklenemedi! API çalışıyor mu?</td></tr>`;
            }
        }

        async function searchSatellitesForList() {
            const query = document.getElementById('sat-list-search').value;
            if(query.length < 2) return;
            try {
                const res = await fetch(`${API_BASE}/tle/search?q=${query}`);
                const data = await res.json();
                renderSatTable(data);
            } catch (e) {
                console.error(e);
            }
        }

        function renderSatTable(data) {
            const tbody = document.getElementById('sat-table-body');
            tbody.innerHTML = "";
            if(data.length === 0) {
                tbody.innerHTML = `<tr><td colspan="4" class="text-center">Kayıt bulunamadı.</td></tr>`;
                return;
            }
            data.forEach(s => {
                tbody.innerHTML += `
                    <tr>
                        <td class="font-mono small">${s.id}</td>
                        <td class="fw-bold">${s.sat_name}</td>
                        <td class="small">${s.source || 'N/A'}</td>
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
            currentAlertType = type;
            const card = document.getElementById('conj-card');
            const headerText = document.getElementById('conj-header-text');

            if(type === 'COLLISION') {
                card.className = "card-glass border-danger border-opacity-25";
                headerText.className = "card-header-glass text-danger";
                headerText.innerHTML = '<span><i class="fas fa-exclamation-triangle me-2"></i>Kritik Yakınlaşmalar</span>';
            } else {
                card.className = "card-glass border-info border-opacity-25";
                headerText.className = "card-header-glass text-info";
                headerText.innerHTML = '<span><i class="fas fa-link me-2"></i>Tespit Edilen Formasyon/Docking</span>';
            }
            loadAlerts();
        }

        async function loadAlerts() {
            try {
                const res = await fetch(`${API_BASE}/conjunctions/alerts?limit=100&type=${currentAlertType}`);
                const data = await res.json();
                const tbody = document.getElementById('conj-table-body');
                tbody.innerHTML = "";

                if(data.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-3">Bu kategoride kayıt bulunamadı.</td></tr>`;
                    return;
                }

                data.forEach(a => {
                    let badgeClass = 'bg-danger';
                    if (a.event_type === 'DOCKING') {
                        badgeClass = 'bg-info text-dark';
                    } else if (a.score < 0.4) {
                        badgeClass = 'bg-success';
                    } else if (a.score < 0.8) {
                        badgeClass = 'bg-warning text-dark';
                    }

                    const actionButtons = a.event_type === 'DOCKING'
                        ? `<button class="btn btn-sm btn-outline-info" onclick="visualizeConjunction(${a.sat1_id}, '${a.sat1_name}', ${a.sat2_id}, '${a.sat2_name}', '${a.tca}')"><i class="fas fa-eye me-1"></i> İzle</button>`
                        : `<div class="btn-group">
                                <button class="btn btn-sm btn-outline-info" onclick="visualizeConjunction(${a.sat1_id}, '${a.sat1_name}', ${a.sat2_id}, '${a.sat2_name}', '${a.tca}')"><i class="fas fa-eye"></i></button>
                                <button class="btn btn-sm btn-outline-warning" onclick='openManeuverModal(${JSON.stringify(a)})'><i class="fas fa-tools"></i></button>
                           </div>`;

                    tbody.innerHTML += `
                        <tr class="animate__animated animate__fadeIn">
                            <td><span class="badge ${badgeClass}">${a.event_type === 'DOCKING' ? 'FORMASYON' : (a.score * 100).toFixed(0) + '%'}</span></td>
                            <td>
                                <div class="fw-bold">${a.sat1_name}</div>
                                <div class="small font-mono">${a.sat1_id}</div>
                            </td>
                            <td>
                                <div class="fw-bold">${a.sat2_name}</div>
                                <div class="small  font-mono">${a.sat2_id}</div>
                            </td>
                            <td class="font-mono small">${new Date(a.tca).toLocaleString()}</td>
                            <td class="fw-bold ${a.event_type === 'DOCKING' ? 'text-info' : 'text-danger'} font-mono">${a.miss_distance_km.toFixed(4)} km</td>
                            <td>${actionButtons}</td>
                        </tr>
                    `;
                });
            } catch(e) { console.error(e); }
        }

        // Manevra Modal
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

        // --- İstenen Başarı/Hata Mantığı Başlangıcı ---
        if (result.success) {
            document.getElementById('maneuver-result').classList.remove('d-none');
            document.getElementById('maneuver-result').classList.remove('alert-danger');
            document.getElementById('maneuver-result').classList.add('alert-dark');

            // Başarılı değerleri yazdır
            document.getElementById('res-burn').innerText = new Date(result.burn_time).toLocaleTimeString();
            document.getElementById('res-dv').innerText = result.dv_magnitude_m_s.toFixed(5) + " m/s";
            document.getElementById('res-dist').innerText = result.predicted_miss_km.toFixed(4) + " km";
            document.getElementById('res-msg').innerText = result.message; // Başarı mesajını ayarla

        } else {
            document.getElementById('maneuver-result').classList.remove('d-none');
            document.getElementById('maneuver-result').classList.remove('alert-dark');
            document.getElementById('maneuver-result').classList.add('alert-danger');

            // Hata değerlerini ve mesajı ayarla
            document.getElementById('res-msg').innerText = "HATA: " + (result.error_detail || result.message);
            document.getElementById('res-burn').innerText = "-";
            document.getElementById('res-dv').innerText = "-";
            document.getElementById('res-dist').innerText = "-";
        }
        // --- İstenen Başarı/Hata Mantığı Sonu ---

    } catch(e) {
        showLoading(false);
        alert("Hata: " + e);
        // Ağ hatası durumunda da hata div'ini gösterebilirsiniz,
        // ancak orijinal talepte sadece alert() kullanılmış.
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
            } catch(e) { alert(e); }
            finally { showLoading(false); }
        }

        // --- DATA LOADING & OTHER ---
        async function loadDashboardStats() {
            // MOCK VERİ İPTAL EDİLDİ. Gerçek endpointler çağrılıyor.

            // 1. Sistem Sağlığı Kontrolü
            try {
                const healthRes = await fetch(`${API_BASE}/health`);
                // Backend'den { status: 'OK', services: [...] } bekleniyor
                if(healthRes.ok) {
                    const healthData = await healthRes.json();
                    document.getElementById('stat-sys-health').innerText = healthData.status || "OK";
                    document.getElementById('stat-sys-msg').innerHTML = '<i class="fas fa-check-circle"></i> Sistemler Aktif';
                    document.getElementById('stat-sys-health').classList.replace('text-danger', 'text-info');
                } else {
                     throw new Error("API Error");
                }
            } catch(e) {
                document.getElementById('stat-sys-health').innerText = "ERR";
                document.getElementById('stat-sys-health').className = "display-5 fw-bold text-danger my-2";
                document.getElementById('stat-sys-msg').innerHTML = '<i class="fas fa-times-circle"></i> API Bağlantı Hatası';
            }

            // 2. Uydu Sayısı (Count)
            try {
                const countRes = await fetch(`${API_BASE}/tle/count`); // Backend'de bu endpoint olmalı
                const countData = await countRes.json();
                document.getElementById('stat-sat-count').innerText = countData.count ? countData.count.toLocaleString() : "--";
            } catch(e) {
                 document.getElementById('stat-sat-count').innerText = "--";
            }

            // 3. Kritik Riskler (Alert Count) ve Tablo
            try {
                const resAlert = await fetch(`${API_BASE}/conjunctions/alerts?limit=5`);
                const alerts = await resAlert.json();
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