const DEFAULT_CENTER = [window.BLACKICE_BOOTSTRAP.schoolLat, window.BLACKICE_BOOTSTRAP.schoolLon];
const DEFAULT_ZOOM = 16;
const REFRESH_MS = 15000;
const STATUS_ORDER = { danger: 0, caution: 1, safe: 2, unknown: 3 };
const STATUS_LABEL = { safe: '안전', caution: '주의', danger: '위험', unknown: '없음' };

const map = L.map('map', { zoomControl: true }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

const markers = new Map();
let nodeCache = [];
let selectedDeviceId = null;
let activeFilter = 'all';
let lastDataSyncedAt = null;

function normalizeStatus(status) {
  return ['safe', 'caution', 'danger'].includes(status) ? status : 'unknown';
}

function statusLabel(status) {
  return STATUS_LABEL[normalizeStatus(status)] || '없음';
}

function badge(status) {
  const normalized = normalizeStatus(status);
  return `<span class="badge ${normalized}">${statusLabel(normalized)}</span>`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function statusColor(status) {
  const normalized = normalizeStatus(status);
  if (normalized === 'danger') return '#dc2626';
  if (normalized === 'caution') return '#f59e0b';
  if (normalized === 'safe') return '#16a34a';
  return '#64748b';
}

function formatNumber(value, digits = 1) {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(digits) : '-';
}

function formatRisk(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) return 0;
  return Math.max(0, Math.min(100, score));
}

function formatKoreanTime(date) {
  return date.toLocaleTimeString('ko-KR', {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });
}


function parseMeasuredDate(value) {
  if (!value || value === '데이터 없음') return null;
  const raw = String(value).trim();

  // DB 값이 "YYYY-MM-DD HH:mm:ss" 또는 "YYYY-MM-DDTHH:mm:ss"이면 화면에는 원본 시각을 그대로 사용
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (m) {
    return {
      year: m[1], month: m[2], day: m[3], hour: m[4], minute: m[5], second: m[6] || '00',
      display: `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6] || '00'}`,
      hourNumber: Number(m[4]),
    };
  }

  const parsed = new Date(raw);
  if (!Number.isNaN(parsed.getTime())) {
    const pad = (n) => String(n).padStart(2, '0');
    return {
      year: String(parsed.getFullYear()),
      month: pad(parsed.getMonth() + 1),
      day: pad(parsed.getDate()),
      hour: pad(parsed.getHours()),
      minute: pad(parsed.getMinutes()),
      second: pad(parsed.getSeconds()),
      display: `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`,
      hourNumber: parsed.getHours(),
    };
  }

  return null;
}

function formatMeasuredAt(value) {
  const parsed = parseMeasuredDate(value);
  return parsed ? parsed.display : escapeHtml(value || '-');
}

function normalizeReasonTime(reason, measuredAt) {
  const text = String(reason || '-');
  const parsed = parseMeasuredDate(measuredAt);
  if (!parsed || !Number.isFinite(parsed.hourNumber)) return text;

  // 백엔드/모델 reason에 UTC 또는 잘못 계산된 "시간:5시" 같은 값이 들어오면 측정시간 기준으로 맞춤
  return text.replace(/시간\s*:\s*\d{1,2}\s*시/g, `시간:${parsed.hourNumber}시`);
}

function updateLiveClock() {
  const el = document.getElementById('last-updated');
  if (!el) return;

  const nowText = formatKoreanTime(new Date());
  const syncedText = lastDataSyncedAt ? formatKoreanTime(lastDataSyncedAt) : '-';
  el.textContent = `현재 시간: ${nowText} · 데이터 동기화: ${syncedText}`;
}

function setLastUpdated() {
  lastDataSyncedAt = new Date();
  updateLiveClock();
}

function setBackendStatus(ok, text) {
  const el = document.getElementById('backend-status');
  el.textContent = text;
  el.className = `status-chip ${ok ? 'ok' : 'fail'}`;
}

function goToSchool() {
  map.setView(DEFAULT_CENTER, DEFAULT_ZOOM, { animate: true });
}

function fitAllNodes() {
  if (!nodeCache.length) {
    goToSchool();
    return;
  }
  const bounds = L.latLngBounds(nodeCache.map((node) => [node.latitude, node.longitude]));
  bounds.extend(DEFAULT_CENTER);
  map.fitBounds(bounds.pad(0.22), { animate: true });
}

function sortedNodes(nodes) {
  return [...nodes].sort((a, b) => {
    const aStatus = normalizeStatus(a.road_status);
    const bStatus = normalizeStatus(b.road_status);
    const statusDiff = STATUS_ORDER[aStatus] - STATUS_ORDER[bStatus];
    if (statusDiff !== 0) return statusDiff;
    return Number(b.risk_score || 0) - Number(a.risk_score || 0);
  });
}

function filteredNodes() {
  const sorted = sortedNodes(nodeCache);
  if (activeFilter === 'all') return sorted;
  return sorted.filter((node) => normalizeStatus(node.road_status) === activeFilter);
}

function updateSummary(nodes) {
  const counts = { safe: 0, caution: 0, danger: 0, unknown: 0 };
  nodes.forEach((node) => {
    counts[normalizeStatus(node.road_status)] += 1;
  });
  document.getElementById('node-count').textContent = `${nodes.length}개`;
  document.getElementById('node-summary').innerHTML = `
    <div class="summary-box safe"><div class="summary-label">안전</div><div class="summary-value">${counts.safe}</div></div>
    <div class="summary-box caution"><div class="summary-label">주의</div><div class="summary-value">${counts.caution}</div></div>
    <div class="summary-box danger"><div class="summary-label">위험</div><div class="summary-value">${counts.danger}</div></div>
    <div class="summary-box unknown"><div class="summary-label">없음</div><div class="summary-value">${counts.unknown}</div></div>
  `;
}

function renderNodeList() {
  const list = document.getElementById('node-list');
  const nodes = filteredNodes();
  if (!nodes.length) {
    list.innerHTML = '<div class="empty-state">선택한 상태에 해당하는 노드가 없습니다.</div>';
    return;
  }

  list.innerHTML = nodes.map((node) => {
    const status = normalizeStatus(node.road_status);
    return `
      <button class="node-list-item ${status} ${selectedDeviceId === String(node.device_id) ? 'active' : ''}" data-device-id="${escapeHtml(node.device_id)}" type="button">
        <div class="node-list-top">
          <div class="node-list-id"><strong>${escapeHtml(node.device_id)}</strong><span class="muted">위험 ${formatRisk(node.risk_score)}</span></div>
          ${badge(status)}
        </div>
        <div class="node-list-name">${escapeHtml(node.name || '학교 주변 노드')}</div>
        <div class="node-list-actions">
          <span>${formatNumber(node.latitude, 4)}, ${formatNumber(node.longitude, 4)}</span>
          <span class="link-like">지도에서 보기</span>
        </div>
      </button>
    `;
  }).join('');

  list.querySelectorAll('.node-list-item').forEach((button) => {
    button.addEventListener('click', () => {
      const { deviceId } = button.dataset;
      focusNode(deviceId);
      loadNodeDetail(deviceId);
    });
  });
}

function makePopup(node) {
  const status = normalizeStatus(node.road_status);
  return `
    <div class="map-popup">
      <div class="map-popup-title">${escapeHtml(node.name || '학교 주변 노드')}</div>
      <div class="map-popup-sub">ID: ${escapeHtml(node.device_id)} · 위험 ${formatRisk(node.risk_score)}</div>
      ${badge(status)}
      <div style="margin-top:8px; color:#334155; font-size:13px;">
        온도 ${formatNumber(node.temperature_c, 1)}°C · 습도 ${formatNumber(node.humidity_pct, 0)}%<br>
        주파수 ${escapeHtml(node.conductivity ?? node.frequency_hz ?? '-')} · ${formatMeasuredAt(node.measured_at)}
      </div>
    </div>
  `;
}

function updateMarkers(nodes) {
  const liveIds = new Set(nodes.map((node) => String(node.device_id)));
  markers.forEach((marker, id) => {
    if (!liveIds.has(id)) {
      marker.remove();
      markers.delete(id);
    }
  });

  nodes.forEach((node) => {
    const id = String(node.device_id);
    const status = normalizeStatus(node.road_status);
    const radius = status === 'danger' ? 13 : status === 'caution' ? 11 : 10;
    let marker = markers.get(id);
    if (!marker) {
      marker = L.circleMarker([node.latitude, node.longitude], {
        radius,
        color: '#ffffff',
        weight: 3,
        fillColor: statusColor(status),
        fillOpacity: 0.94,
      }).addTo(map);
      markers.set(id, marker);
    } else {
      marker.setLatLng([node.latitude, node.longitude]);
      marker.setStyle({ fillColor: statusColor(status), radius });
    }

    marker.bindPopup(makePopup(node));
    marker.off('click');
    marker.on('click', () => {
      selectedDeviceId = id;
      renderNodeList();
      loadNodeDetail(id);
    });
  });
}

function focusNode(deviceId) {
  const node = nodeCache.find((item) => String(item.device_id) === String(deviceId));
  const marker = markers.get(String(deviceId));
  if (node) map.setView([node.latitude, node.longitude], 17, { animate: true });
  if (marker) marker.openPopup();
  selectedDeviceId = String(deviceId);
  renderNodeList();
}

async function fetchJson(url) {
  const res = await fetch(url, { cache: 'no-store' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || `${res.status} ${res.statusText}`);
  }
  return data;
}

async function loadNodes() {
  const data = await fetchJson('/api/map/nodes');
  nodeCache = (data.nodes || []).map((node) => ({ ...node, device_id: String(node.device_id) }));
  updateSummary(nodeCache);
  updateMarkers(nodeCache);
  renderNodeList();

  if (selectedDeviceId && nodeCache.some((node) => String(node.device_id) === selectedDeviceId)) {
    await loadNodeDetail(selectedDeviceId, false);
  } else if (nodeCache.length) {
    selectedDeviceId = sortedNodes(nodeCache)[0].device_id;
    await loadNodeDetail(selectedDeviceId, false);
  }
}

function renderDetail(node) {
  const status = normalizeStatus(node.road_status);
  const risk = formatRisk(node.risk_score);
  const detailContainer = document.getElementById('node-detail');
  detailContainer.className = '';
  detailContainer.innerHTML = `
    <div class="detail-head">
      <div>
        <div class="detail-id">노드 ${escapeHtml(node.device_id)}</div>
        <div class="detail-name">${escapeHtml(node.name || '학교 주변 노드')}</div>
      </div>
      ${badge(status)}
    </div>
    <div class="risk-visual ${status}">
      <div class="metric-head">
        <span class="metric-label">위험 점수</span>
        <strong>${risk} / 100</strong>
      </div>
      <div class="risk-bar"><div class="risk-fill" style="width:${risk}%;"></div></div>
    </div>
    <div class="metric-grid">
      <div class="metric-card"><div class="metric-label">측정시간</div><div class="metric-value">${formatMeasuredAt(node.measured_at)}</div></div>
      <div class="metric-card"><div class="metric-label">온도</div><div class="metric-value">${formatNumber(node.temperature_c, 1)} °C</div></div>
      <div class="metric-card"><div class="metric-label">습도</div><div class="metric-value">${formatNumber(node.humidity_pct, 0)} %</div></div>
      <div class="metric-card"><div class="metric-label">주파수/전도도</div><div class="metric-value">${escapeHtml(node.conductivity ?? node.frequency_hz ?? '-')}</div></div>
      <div class="metric-card"><div class="metric-label">위도</div><div class="metric-value">${formatNumber(node.latitude, 5)}</div></div>
      <div class="metric-card"><div class="metric-label">경도</div><div class="metric-value">${formatNumber(node.longitude, 5)}</div></div>
    </div>
    <div class="reason-box">판단 사유: ${escapeHtml(normalizeReasonTime(node.reason, node.measured_at))}</div>
  `;
}

async function loadNodeDetail(deviceId, openPopup = true) {
  const node = await fetchJson(`/api/map/node/${encodeURIComponent(deviceId)}`);
  if (node.error) return;

  selectedDeviceId = String(deviceId);
  renderNodeList();
  renderDetail(node);

  const marker = markers.get(String(deviceId));
  if (marker) {
    marker.setPopupContent(makePopup(node));
    if (openPopup) marker.openPopup();
  }
}

async function loadRecent() {
  const data = await fetchJson('/api/readings/recent?limit=10');
  const list = document.getElementById('recent-list');
  const items = data.items || [];
  if (!items.length) {
    list.innerHTML = '<div class="empty-state">최근 측정값이 없습니다. 게이트웨이 또는 AWS 데이터 입력을 확인하세요.</div>';
    return;
  }

  list.innerHTML = items.map((item) => `
    <div class="item recent-item" data-device-id="${escapeHtml(item.device_id)}">
      <div class="node-list-top"><strong>노드 ${escapeHtml(item.device_id)}</strong> ${badge(item.road_status)}</div>
      <div class="recent-meta">
        ${formatMeasuredAt(item.measured_at)}<br>
        온도 ${formatNumber(item.temperature_c, 1)} °C / 습도 ${formatNumber(item.humidity_pct, 0)} % / 주파수 ${escapeHtml(item.conductivity ?? item.frequency_hz ?? '-')}
      </div>
    </div>
  `).join('');

  document.querySelectorAll('.recent-item').forEach((item) => {
    item.addEventListener('click', () => {
      const { deviceId } = item.dataset;
      focusNode(deviceId);
      loadNodeDetail(deviceId);
    });
  });
}

async function refresh() {
  try {
    await loadNodes();
    await loadRecent();
    setLastUpdated();
    setBackendStatus(true, '서버 정상');
  } catch (error) {
    console.error(error);
    setBackendStatus(false, '연결 오류');
    document.getElementById('recent-list').innerHTML = `<div class="empty-state">데이터를 불러오지 못했습니다.<br>${escapeHtml(error.message)}</div>`;
  }
}

document.getElementById('reset-view-btn').addEventListener('click', goToSchool);
document.getElementById('fit-nodes-btn').addEventListener('click', fitAllNodes);
document.querySelectorAll('.filter-pill').forEach((button) => {
  button.addEventListener('click', () => {
    activeFilter = button.dataset.filter;
    document.querySelectorAll('.filter-pill').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    renderNodeList();
  });
});

updateLiveClock();
setInterval(updateLiveClock, 1000);
refresh();
setInterval(refresh, REFRESH_MS);
