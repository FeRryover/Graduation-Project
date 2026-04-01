const forms = document.querySelectorAll('.api-form');
const resultEl = document.getElementById('result');
const clearBtn = document.getElementById('clearBtn');
const taskMetaEl = document.getElementById('taskMeta');
const progressFillEl = document.getElementById('progressFill');
const artifactListEl = document.getElementById('artifactList');
const downloadAllBtn = document.getElementById('downloadAllBtn');
const cancelTaskBtn = document.getElementById('cancelTaskBtn');
const refreshHistoryBtn = document.getElementById('refreshHistoryBtn');
const clearHistoryBtn = document.getElementById('clearHistoryBtn');
const historyListEl = document.getElementById('historyList');
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const chatImage = document.getElementById('chatImage');
const chatMessages = document.getElementById('chatMessages');
const mapHintEl = document.getElementById('mapHint');
const mapOrientationEl = document.getElementById('mapOrientation');
const toolsPanelEl = document.getElementById('toolsPanel');
const toolsToggleBtn = document.getElementById('toolsToggleBtn');
const confirmDialogEl = document.getElementById('confirmDialog');
const confirmDialogMessageEl = document.getElementById('confirmDialogMessage');
const confirmDialogCancelBtn = document.getElementById('confirmDialogCancel');
const confirmDialogConfirmBtn = document.getElementById('confirmDialogConfirm');
let activeEventSource = null;
let currentTaskId = null;
let mapRenderVersion = 0;
let lastArtifacts = [];
let confirmDialogResolver = null;
let confirmDialogLastActiveEl = null;
const CHAT_STORAGE_KEY = 'mixsimgpt.chat.messages';
const CHAT_PENDING_TASK_KEY = 'mixsimgpt.chat.pendingTask';
const CHAT_SERVER_SESSION_KEY = 'mixsimgpt.chat.serverSession';
const MAX_CHAT_HISTORY = 100;
const MAX_UPLOAD_SIZE = 10 * 1024 * 1024;
const ALLOWED_UPLOAD_EXTS = new Set(['.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff']);

function updateToolsPanelState(expanded) {
  if (!toolsPanelEl || !toolsToggleBtn) {
    return;
  }
  toolsPanelEl.classList.toggle('is-collapsed', !expanded);
  toolsToggleBtn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  toolsToggleBtn.textContent = expanded ? '收起工具' : '展开工具';
}

const expandedArtifactGroups = new Set(['geojson']);

function formatBytes(size) {
  if (!Number.isFinite(size) || size < 0) {
    return '-';
  }
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}

function bindUploadStatusHints() {
  const fileInputs = document.querySelectorAll('input[type="file"][name="image_file"]');
  fileInputs.forEach((input) => {
    let status = input.parentElement && input.parentElement.querySelector('.upload-status');
    if (!status) {
      status = document.createElement('p');
      status.className = 'upload-status';
      status.textContent = '未选择文件';
      if (input.parentElement) {
        input.parentElement.appendChild(status);
      }
    }

    const update = () => {
      const oldUrl = status.dataset.blobUrl;
      if (oldUrl) {
        URL.revokeObjectURL(oldUrl);
        delete status.dataset.blobUrl;
      }

      if (!input.files || input.files.length === 0) {
        status.textContent = '未选择文件';
        return;
      }
      const f = input.files[0];
      const blobUrl = URL.createObjectURL(f);
      status.dataset.blobUrl = blobUrl;
      status.innerHTML = '';

      const link = document.createElement('a');
      link.className = 'upload-status-link';
      link.href = blobUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.download = f.name;
      link.textContent = `已选择：${f.name}（${formatBytes(f.size)}）`;

      status.appendChild(link);
    };

    input.addEventListener('change', update);
    update();
  });
}

const map = L.map('networkMap', {
  zoomControl: true,
}).setView([39.9042, 116.4074], 11);

const mapBaseSourceEl = document.getElementById('mapBaseSource');
const toggleBaseModeBtn = document.getElementById('toggleBaseModeBtn');

let baseMapMode = 'vector'; // 'vector' | 'imagery'

function setBaseSourceText(text) {
  if (!mapBaseSourceEl) {
    return;
  }
  mapBaseSourceEl.textContent = text;
}

function setBaseModeUi() {
  if (!toggleBaseModeBtn) {
    return;
  }
  toggleBaseModeBtn.textContent = baseMapMode === 'imagery' ? '切换为矢图' : '切换为影像图';
}

// 国内部署场景下，部分海外瓦片服务可能出现链路抖动/限流。
// 这里做“多源兜底 + 自动切换”，优先使用高德，保留天地图（需要 key）作为备用源。
// 注意：高德/腾讯等国内常见底图通常为 GCJ-02 偏移坐标系，若叠加的路网是 WGS84（OSM 常见），会出现位置偏移。

// 1) 若你有天地图 key，填在这里（前端可见，请在天地图控制台限制域名）。
const TIANDITU_KEY = 'ab9109f928cefd3bfe7cc2f60fe50786';

// 2) 若你有高德 key，可填在这里（部分瓦片服务可能不需要该参数，但更建议使用官方授权方式并限制 Referer/域名）。
const AMAP_KEY = '97267e642f34dc2df3c890f74c6b8205';

// 3) 底图坐标系与路网坐标系对齐
// - 高德底图为 GCJ-02，OSM/常见经纬度为 WGS84。
// - 当当前底图为 GCJ-02 时，这里会把叠加路网从 WGS84 转换到 GCJ-02（仅对地理坐标生效）。
// - 如果你的输入路网本身已经是 GCJ-02，把它改成 'gcj02' 可关闭转换。
const OVERLAY_INPUT_CRS = 'wgs84'; // 'wgs84' | 'gcj02'
let currentBaseCrs = 'wgs84'; // 'wgs84' | 'gcj02'

function outOfChina(lat, lon) {
  return lon < 72.004 || lon > 137.8347 || lat < 0.8293 || lat > 55.8271;
}

function transformLat(x, y) {
  let ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
  ret += (20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0 / 3.0;
  ret += (20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin(y / 3.0 * Math.PI)) * 2.0 / 3.0;
  ret += (160.0 * Math.sin(y / 12.0 * Math.PI) + 320.0 * Math.sin(y * Math.PI / 30.0)) * 2.0 / 3.0;
  return ret;
}

function transformLon(x, y) {
  let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  ret += (20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0 / 3.0;
  ret += (20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin(x / 3.0 * Math.PI)) * 2.0 / 3.0;
  ret += (150.0 * Math.sin(x / 12.0 * Math.PI) + 300.0 * Math.sin(x / 30.0 * Math.PI)) * 2.0 / 3.0;
  return ret;
}

function wgs84ToGcj02(lat, lon) {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return [lat, lon];
  }
  if (outOfChina(lat, lon)) {
    return [lat, lon];
  }
  const a = 6378245.0;
  const ee = 0.00669342162296594323;
  let dLat = transformLat(lon - 105.0, lat - 35.0);
  let dLon = transformLon(lon - 105.0, lat - 35.0);
  const radLat = lat / 180.0 * Math.PI;
  let magic = Math.sin(radLat);
  magic = 1 - ee * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180.0) / ((a * (1 - ee)) / (magic * sqrtMagic) * Math.PI);
  dLon = (dLon * 180.0) / (a / sqrtMagic * Math.cos(radLat) * Math.PI);
  return [lat + dLat, lon + dLon];
}

function applyBaseCrsTransform(pt, coordMode) {
  if (!pt) {
    return null;
  }
  // 非地理坐标（例如图像管线输出的 near-origin 小数/像素系）不要做 GCJ 偏移。
  if (coordMode !== 'geo') {
    return pt;
  }
  if (currentBaseCrs !== 'gcj02') {
    return pt;
  }
  if (OVERLAY_INPUT_CRS !== 'wgs84') {
    return pt;
  }
  const res = wgs84ToGcj02(pt[0], pt[1]);
  return [res[0], res[1]];
}

function createTianDiTuLayer(type) {
  if (!TIANDITU_KEY) {
    return null;
  }
  const baseProvider = type === 'img' ? 'TianDiTu.Satellite.Map' : 'TianDiTu.Normal.Map';
  const annoProvider = type === 'img' ? 'TianDiTu.Satellite.Annotion' : 'TianDiTu.Normal.Annotion';
  const base = L.tileLayer.chinaProvider(baseProvider, {
    key: TIANDITU_KEY,
    maxZoom: 18,
    updateWhenIdle: true,
    keepBuffer: 2,
    crossOrigin: true,
  });
  const anno = L.tileLayer.chinaProvider(annoProvider, {
    key: TIANDITU_KEY,
    maxZoom: 18,
    updateWhenIdle: true,
    keepBuffer: 2,
    crossOrigin: true,
  });
  return L.layerGroup([base, anno]);
}

const TILE_SOURCES = [
  {
    name: '天地图矢量',
    crs: 'wgs84',
    mode: 'vector',
    createLayer: () => createTianDiTuLayer('vec'),
  },
  {
    name: '高德矢量',
    crs: 'gcj02',
    mode: 'vector',
    createLayer: () => {
      return L.tileLayer.chinaProvider('GaoDe.Normal.Map', {
        key: AMAP_KEY,
        attribution: '&copy; 高德地图',
        maxZoom: 19,
        updateWhenIdle: true,
        keepBuffer: 2,
        crossOrigin: true,
      });
    },
  },
  {
    name: '天地图影像',
    crs: 'wgs84',
    mode: 'imagery',
    createLayer: () => createTianDiTuLayer('img'),
  },
  {
    name: '高德影像',
    crs: 'gcj02',
    mode: 'imagery',
    createLayer: () => {
      return L.tileLayer.chinaProvider('GaoDe.Satellite.Map', {
        key: AMAP_KEY,
        attribution: '&copy; 高德地图',
        maxZoom: 19,
        updateWhenIdle: true,
        keepBuffer: 2,
        crossOrigin: true,
      });
    },
  },
  {
    name: 'OpenStreetMap',
    crs: 'wgs84',
    mode: 'vector',
    createLayer: () => L.tileLayer.chinaProvider('OSM.Normal.Map', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19,
      updateWhenIdle: true,
      keepBuffer: 2,
      crossOrigin: true,
    }),
  },
  {
    name: 'OSM DE',
    crs: 'wgs84',
    mode: 'vector',
    createLayer: () => L.tileLayer.chinaProvider('OSM.DE.Map', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19,
      updateWhenIdle: true,
      keepBuffer: 2,
      crossOrigin: true,
    }),
  },
];

let baseTileLayer = null;
let baseTileSourceIndex = -1;

function activeTileSourceIndices() {
  const indices = [];
  for (let i = 0; i < TILE_SOURCES.length; i += 1) {
    const source = TILE_SOURCES[i];
    const mode = source && source.mode ? String(source.mode) : 'vector';
    if (mode === baseMapMode) {
      indices.push(i);
    }
  }
  return indices;
}

function layerOffRecursive(layer) {
  if (!layer) return;
  if (typeof layer.off === 'function') {
    layer.off();
  }
  if (typeof layer.eachLayer === 'function') {
    layer.eachLayer((child) => {
      if (child && typeof child.off === 'function') {
        child.off();
      }
    });
  }
}

function bindTileFallback(layer) {
  const handleTileError = (evt) => {
    const now = Date.now();
    tileErrorTimestamps = tileErrorTimestamps.filter((t) => now - t <= TILE_ERROR_WINDOW_MS);
    tileErrorTimestamps.push(now);

    if (now < tileSwitchCooldownUntil) {
      return;
    }
    if (tileErrorTimestamps.length < TILE_ERROR_THRESHOLD) {
      return;
    }

    tileErrorTimestamps = [];
    tileSwitchCooldownUntil = now + 15_000;

    const errUrl = (evt && evt.tile && evt.tile.src) ? evt.tile.src : '';
    const indices = activeTileSourceIndices();
    if (indices.length === 0) {
      return;
    }
    const pos = Math.max(0, indices.indexOf(baseTileSourceIndex));
    const next = indices[(pos + 1) % indices.length];
    setBaseTileLayer(next, errUrl ? `tileerror: ${errUrl}` : 'tileerror burst');
  };

  if (!layer) return;
  if (typeof layer.on === 'function') {
    layer.on('tileerror', handleTileError);
  }
  if (typeof layer.eachLayer === 'function') {
    layer.eachLayer((child) => {
      if (child && typeof child.on === 'function') {
        child.on('tileerror', handleTileError);
      }
    });
  }
}

function setBaseTileLayer(nextIndex, reason = '') {
  // 跳过 createLayer() 返回 null 的源（例如没填天地图 key）。
  const indices = activeTileSourceIndices();
  if (indices.length === 0) {
    return;
  }

  const startPos = Math.max(0, indices.indexOf(nextIndex));
  for (let offset = 0; offset < indices.length; offset += 1) {
    const idx = indices[(startPos + offset) % indices.length];
    const source = TILE_SOURCES[idx];
    const layer = source.createLayer();
    if (!layer) {
      continue;
    }

    if (baseTileLayer) {
      map.removeLayer(baseTileLayer);
      layerOffRecursive(baseTileLayer);
      baseTileLayer = null;
    }

    baseTileSourceIndex = idx;
    baseTileLayer = layer;
    currentBaseCrs = (source && source.crs) ? String(source.crs) : 'wgs84';
    baseTileLayer.addTo(map);
    bindTileFallback(baseTileLayer);
    setBaseSourceText(`底图：${source.name}`);

    if (reason) {
      // eslint-disable-next-line no-console
      console.warn(`[Map] Base tile switched to ${source.name}: ${reason}`);
    }
    return;
  }
}

const TILE_ERROR_WINDOW_MS = 12_000;
const TILE_ERROR_THRESHOLD = 8;
let tileErrorTimestamps = [];
let tileSwitchCooldownUntil = 0;

setBaseTileLayer(0);

setBaseModeUi();
if (toggleBaseModeBtn) {
  toggleBaseModeBtn.addEventListener('click', () => {
    baseMapMode = baseMapMode === 'imagery' ? 'vector' : 'imagery';
    setBaseModeUi();
    const indices = activeTileSourceIndices();
    if (indices.length > 0) {
      setBaseTileLayer(indices[0], 'user toggle base mode');
    }
  });
}

const mapLayers = {
  nodes: L.layerGroup().addTo(map),
  links: L.layerGroup().addTo(map),
};

function scheduleMapResize() {
  window.requestAnimationFrame(() => {
    map.invalidateSize();
  });
}

window.addEventListener('load', () => {
  scheduleMapResize();
});

window.addEventListener('resize', () => {
  scheduleMapResize();
});

function appendResult(title, payload, isError = false) {
  const now = new Date().toLocaleString();
  const head = `[${now}] ${title}`;
  const body = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
  const chunk = `${head}\n${body}\n${'-'.repeat(64)}\n`;
  resultEl.textContent = chunk + resultEl.textContent;
  if (isError) {
    resultEl.style.borderColor = '#d04f31';
  } else {
    resultEl.style.borderColor = '#a7c0b1';
  }
}

function createChatMessageElement(role, text) {
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  div.textContent = text;
  return div;
}

function readStoredChatMessages() {
  try {
    const raw = window.localStorage.getItem(CHAT_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed
      .filter((item) => item && typeof item.text === 'string' && typeof item.role === 'string')
      .map((item) => ({
        role: item.role === 'user' ? 'user' : 'assistant',
        text: item.text,
      }));
  } catch (err) {
    return [];
  }
}

function persistChatMessages() {
  if (!chatMessages) {
    return;
  }

  try {
    const items = Array.from(chatMessages.querySelectorAll('.chat-msg'))
      .map((node) => ({
        role: node.classList.contains('user') ? 'user' : 'assistant',
        text: node.textContent || '',
      }))
      .filter((item) => item.text.trim().length > 0)
      .slice(-MAX_CHAT_HISTORY);
    window.localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(items));
  } catch (err) {
    // Ignore storage failures and keep chat usable in-memory.
  }
}

function restoreChatMessages() {
  if (!chatMessages) {
    return;
  }

  const stored = readStoredChatMessages();
  if (stored.length > 0) {
    chatMessages.innerHTML = '';
    stored.forEach((item) => {
      chatMessages.appendChild(createChatMessageElement(item.role, item.text));
    });
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return;
  }

  persistChatMessages();
}

function setPendingChatTask(taskId) {
  try {
    if (!taskId) {
      window.localStorage.removeItem(CHAT_PENDING_TASK_KEY);
      return;
    }
    window.localStorage.setItem(CHAT_PENDING_TASK_KEY, String(taskId));
  } catch (_err) {
    // Ignore storage failures.
  }
}

function getPendingChatTask() {
  try {
    const taskId = window.localStorage.getItem(CHAT_PENDING_TASK_KEY);
    return taskId ? String(taskId) : null;
  } catch (_err) {
    return null;
  }
}

function clearPendingChatTask(taskId = null) {
  try {
    const storedTaskId = window.localStorage.getItem(CHAT_PENDING_TASK_KEY);
    if (!storedTaskId) {
      return;
    }
    if (taskId && storedTaskId !== String(taskId)) {
      return;
    }
    window.localStorage.removeItem(CHAT_PENDING_TASK_KEY);
  } catch (_err) {
    // Ignore storage failures.
  }
}

function clearStoredChatState() {
  try {
    window.localStorage.removeItem(CHAT_STORAGE_KEY);
    window.localStorage.removeItem(CHAT_PENDING_TASK_KEY);
  } catch (_err) {
    // Ignore storage failures.
  }

  if (chatMessages) {
    chatMessages.innerHTML = '';
    chatMessages.appendChild(createChatMessageElement('assistant', '你好，我可以帮你生成路网、抓取 OSM 或识别上传图片。'));
    persistChatMessages();
  }
}

async function syncServerSession() {
  try {
    const resp = await fetch('/api/session', { cache: 'no-store' });
    if (!resp.ok) {
      return;
    }
    const data = await resp.json();
    if (!data.ok || !data.session_id) {
      return;
    }

    const nextSessionId = String(data.session_id);
    const lastSessionId = window.localStorage.getItem(CHAT_SERVER_SESSION_KEY);
    if (lastSessionId && lastSessionId !== nextSessionId) {
      clearStoredChatState();
    }
    window.localStorage.setItem(CHAT_SERVER_SESSION_KEY, nextSessionId);
  } catch (_err) {
    // Ignore session sync failures.
  }
}

function appendChatMessage(role, text) {
  const div = createChatMessageElement(role, text);
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  persistChatMessages();
}

function validateUploadFile(file) {
  if (!file) {
    return { ok: true };
  }
  const name = (file.name || '').toLowerCase();
  const dot = name.lastIndexOf('.');
  const ext = dot >= 0 ? name.slice(dot) : '';
  if (!ALLOWED_UPLOAD_EXTS.has(ext)) {
    return { ok: false, message: '上传文件类型不支持，仅允许 png/jpg/jpeg/bmp/webp/tif/tiff。' };
  }
  if (file.size > MAX_UPLOAD_SIZE) {
    return { ok: false, message: '上传文件过大，最大支持 10MB。' };
  }
  return { ok: true };
}

function setCancelButtonEnabled(enabled) {
  cancelTaskBtn.disabled = !enabled || !currentTaskId;
}

function clearMapNetwork() {
  mapLayers.nodes.clearLayers();
  mapLayers.links.clearLayers();
}

function invalidateMapRender() {
  mapRenderVersion += 1;
  return mapRenderVersion;
}

function setMapOrientationMode(mode) {
  if (mode === 'geo') {
    mapOrientationEl.textContent = '方向模式：地理坐标（上北下南，左西右东）';
    return;
  }
  if (mode === 'image') {
    mapOrientationEl.textContent = '方向模式：非地理坐标（与预览图同向）';
    return;
  }
  mapOrientationEl.textContent = '方向模式：未确定';
}

function parseCsvRow(line) {
  const cells = [];
  let cur = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        cur += '"';
        i += 1;
      } else {
        quoted = !quoted;
      }
      continue;
    }
    if (ch === ',' && !quoted) {
      cells.push(cur);
      cur = '';
      continue;
    }
    cur += ch;
  }
  cells.push(cur);
  return cells;
}

function parseCsvText(text) {
  const lines = text.split(/\r?\n/).filter((x) => x.trim().length > 0);
  if (lines.length < 2) {
    return [];
  }
  const headers = parseCsvRow(lines[0]).map((h) => h.trim());
  return lines.slice(1).map((line) => {
    const values = parseCsvRow(line);
    const row = {};
    headers.forEach((h, idx) => {
      row[h] = (values[idx] || '').trim();
    });
    return row;
  });
}

function asNumber(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function normalizeLatLon(lat, lon) {
  if (lat === null || lon === null) {
    return null;
  }

  if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
    return [lat, lon];
  }

  // Satellite recognition CSV may use pixel coordinates (0~800).
  // The paired link geometry is scaled by 1e6, so normalize here.
  const scaledLat = lat / 1000000;
  const scaledLon = lon / 1000000;
  if (scaledLat >= -90 && scaledLat <= 90 && scaledLon >= -180 && scaledLon <= 180) {
    return [scaledLat, scaledLon];
  }

  return null;
}

function rowLatLon(row) {
  const latKeys = ['Latitude', 'latitude', 'lat', 'y_coord', 'Y', 'y'];
  const lonKeys = ['Longitude', 'longitude', 'lon', 'lng', 'x_coord', 'X', 'x'];
  let lat = null;
  let lon = null;

  latKeys.some((k) => {
    if (Object.prototype.hasOwnProperty.call(row, k)) {
      lat = asNumber(row[k]);
    }
    return lat !== null;
  });

  lonKeys.some((k) => {
    if (Object.prototype.hasOwnProperty.call(row, k)) {
      lon = asNumber(row[k]);
    }
    return lon !== null;
  });

  return normalizeLatLon(lat, lon);
}

function parseLinestringWkt(wkt) {
  if (!wkt || typeof wkt !== 'string') {
    return [];
  }
  const match = wkt.match(/LINESTRING\s*\((.*)\)/i);
  if (!match) {
    return [];
  }
  return match[1]
    .split(',')
    .map((pair) => pair.trim().split(/\s+/))
    .map((parts) => normalizeLatLon(asNumber(parts[1]), asNumber(parts[0])))
    .filter((pt) => pt !== null);
}

function detectCoordinateMode(points) {
  if (!Array.isArray(points) || points.length === 0) {
    return 'geo';
  }

  let geoLike = 0;
  let tinyLike = 0;
  points.forEach((pt) => {
    const lat = pt[0];
    const lon = pt[1];
    if (Math.abs(lat) > 1 || Math.abs(lon) > 1) {
      geoLike += 1;
    }
    if (Math.abs(lat) < 0.01 && Math.abs(lon) < 0.01) {
      tinyLike += 1;
    }
  });

  // Non-georeferenced outputs from image pipelines are usually tiny near-origin values.
  if (tinyLike >= Math.max(8, Math.floor(points.length * 0.4)) && geoLike === 0) {
    return 'image';
  }
  return 'geo';
}

function orientPoint(pt, mode) {
  if (!pt) {
    return null;
  }
  if (mode === 'image') {
    // Keep same visual orientation as preview image (image y grows downward).
    return [-pt[0], pt[1]];
  }
  return pt;
}

function getValueByKeys(row, keys) {
  for (const k of keys) {
    if (Object.prototype.hasOwnProperty.call(row, k) && row[k] !== '') {
      return row[k];
    }
  }
  return null;
}

async function fetchArtifactCsv(artifact) {
  if (!artifact || !artifact.download_url) {
    return [];
  }
  const resp = await fetch(artifact.download_url);
  if (!resp.ok) {
    return [];
  }
  const text = await resp.text();
  return parseCsvText(text);
}

async function fetchArtifactGeoJson(artifact) {
  if (!artifact || !artifact.download_url) {
    return null;
  }
  const resp = await fetch(artifact.download_url);
  if (!resp.ok) {
    return null;
  }
  return resp.json();
}

function geoJsonCoordToLatLon(coord) {
  if (!Array.isArray(coord) || coord.length < 2) {
    return null;
  }
  const lon = asNumber(coord[0]);
  const lat = asNumber(coord[1]);
  return normalizeLatLon(lat, lon);
}

function collectGeoJsonSamplePoints(geojson, points = []) {
  if (!geojson || typeof geojson !== 'object') {
    return points;
  }

  if (geojson.type === 'FeatureCollection' && Array.isArray(geojson.features)) {
    geojson.features.forEach((feature) => collectGeoJsonSamplePoints(feature, points));
    return points;
  }

  if (geojson.type === 'Feature') {
    collectGeoJsonSamplePoints(geojson.geometry, points);
    return points;
  }

  if (geojson.type === 'GeometryCollection' && Array.isArray(geojson.geometries)) {
    geojson.geometries.forEach((geometry) => collectGeoJsonSamplePoints(geometry, points));
    return points;
  }

  if (geojson.type === 'Point') {
    const pt = geoJsonCoordToLatLon(geojson.coordinates);
    if (pt) {
      points.push(pt);
    }
    return points;
  }

  if (geojson.type === 'MultiPoint' && Array.isArray(geojson.coordinates)) {
    geojson.coordinates.forEach((coord) => {
      const pt = geoJsonCoordToLatLon(coord);
      if (pt) {
        points.push(pt);
      }
    });
    return points;
  }

  if (geojson.type === 'LineString' && Array.isArray(geojson.coordinates)) {
    geojson.coordinates.forEach((coord) => {
      const pt = geoJsonCoordToLatLon(coord);
      if (pt) {
        points.push(pt);
      }
    });
    return points;
  }

  if (geojson.type === 'MultiLineString' && Array.isArray(geojson.coordinates)) {
    geojson.coordinates.forEach((line) => {
      if (!Array.isArray(line)) {
        return;
      }
      line.forEach((coord) => {
        const pt = geoJsonCoordToLatLon(coord);
        if (pt) {
          points.push(pt);
        }
      });
    });
  }

  return points;
}

function drawGeoJsonGeometry(geometry, coordMode, bounds) {
  if (!geometry || typeof geometry !== 'object') {
    return { nodes: 0, links: 0 };
  }

  if (geometry.type === 'GeometryCollection' && Array.isArray(geometry.geometries)) {
    return geometry.geometries.reduce((acc, item) => {
      const res = drawGeoJsonGeometry(item, coordMode, bounds);
      return { nodes: acc.nodes + res.nodes, links: acc.links + res.links };
    }, { nodes: 0, links: 0 });
  }

  if (geometry.type === 'Point') {
    const pt = applyBaseCrsTransform(orientPoint(geoJsonCoordToLatLon(geometry.coordinates), coordMode), coordMode);
    if (!pt) {
      return { nodes: 0, links: 0 };
    }
    L.circleMarker(pt, {
      radius: 3,
      color: '#ef6c2f',
      fillColor: '#ef6c2f',
      fillOpacity: 0.85,
      weight: 1,
    }).addTo(mapLayers.nodes);
    bounds.push(pt);
    return { nodes: 1, links: 0 };
  }

  if (geometry.type === 'MultiPoint' && Array.isArray(geometry.coordinates)) {
    return geometry.coordinates.reduce((acc, coord) => {
      const res = drawGeoJsonGeometry({ type: 'Point', coordinates: coord }, coordMode, bounds);
      return { nodes: acc.nodes + res.nodes, links: acc.links + res.links };
    }, { nodes: 0, links: 0 });
  }

  if (geometry.type === 'LineString' && Array.isArray(geometry.coordinates)) {
    const line = geometry.coordinates
      .map((coord) => geoJsonCoordToLatLon(coord))
      .filter((pt) => pt !== null)
      .map((pt) => orientPoint(pt, coordMode))
      .map((pt) => applyBaseCrsTransform(pt, coordMode))
      .filter((pt) => pt !== null);

    if (line.length < 2) {
      return { nodes: 0, links: 0 };
    }
    L.polyline(line, { color: '#0b6e4f', weight: 3.5, opacity: 0.95 }).addTo(mapLayers.links);
    line.forEach((pt) => bounds.push(pt));
    return { nodes: 0, links: 1 };
  }

  if (geometry.type === 'MultiLineString' && Array.isArray(geometry.coordinates)) {
    return geometry.coordinates.reduce((acc, line) => {
      const res = drawGeoJsonGeometry({ type: 'LineString', coordinates: line }, coordMode, bounds);
      return { nodes: acc.nodes + res.nodes, links: acc.links + res.links };
    }, { nodes: 0, links: 0 });
  }

  return { nodes: 0, links: 0 };
}

async function renderGeoJsonOnMap(geojsonArtifacts, renderVersion) {
  const geojsonDocs = [];
  for (const art of geojsonArtifacts) {
    // eslint-disable-next-line no-await-in-loop
    const payload = await fetchArtifactGeoJson(art);
    if (renderVersion !== mapRenderVersion) {
      return false;
    }
    if (payload) {
      geojsonDocs.push(payload);
    }
  }

  if (!geojsonDocs.length) {
    return false;
  }

  const rawSamplePoints = [];
  geojsonDocs.forEach((doc) => collectGeoJsonSamplePoints(doc, rawSamplePoints));
  const coordMode = detectCoordinateMode(rawSamplePoints);
  setMapOrientationMode(coordMode);

  const bounds = [];
  let drawnNodes = 0;
  let drawnLinks = 0;

  geojsonDocs.forEach((doc) => {
    const features = doc && doc.type === 'FeatureCollection' && Array.isArray(doc.features)
      ? doc.features
      : [doc];
    features.forEach((feature) => {
      const geometry = feature && feature.type === 'Feature' ? feature.geometry : feature;
      const counts = drawGeoJsonGeometry(geometry, coordMode, bounds);
      drawnNodes += counts.nodes;
      drawnLinks += counts.links;
    });
  });

  if (!bounds.length) {
    mapHintEl.textContent = '找到 GeoJSON，但无法解析为可绘制坐标。';
    return true;
  }

  if (renderVersion !== mapRenderVersion) {
    return true;
  }
  scheduleMapResize();
  map.fitBounds(bounds, { padding: [20, 20] });
  mapHintEl.textContent = `已从 GeoJSON 绘制节点 ${drawnNodes} 个，路段 ${drawnLinks} 条。`;
  return true;
}

async function renderNetworkOnMap(artifacts) {
  const renderVersion = mapRenderVersion;
  clearMapNetwork();
  scheduleMapResize();
  mapHintEl.textContent = '正在解析路网数据...';
  setMapOrientationMode('unknown');

  const geojsonArtifacts = (artifacts || []).filter((a) => {
    const name = (a.name || '').toLowerCase();
    return name.endsWith('.geojson');
  });

  if (geojsonArtifacts.length > 0) {
    const rendered = await renderGeoJsonOnMap(geojsonArtifacts, renderVersion);
    if (rendered) {
      return;
    }
  }

  const csvArtifacts = (artifacts || []).filter((a) => {
    const name = (a.name || '').toLowerCase();
    return name.endsWith('.csv');
  });

  if (csvArtifacts.length === 0) {
    mapHintEl.textContent = '未找到可绘制的 CSV 路网文件。';
    return;
  }

  const bounds = [];
  let drawnNodes = 0;
  let drawnLinks = 0;

  const csvRows = [];
  for (const art of csvArtifacts) {
    // eslint-disable-next-line no-await-in-loop
    const rows = await fetchArtifactCsv(art);
    if (renderVersion !== mapRenderVersion) {
      return;
    }
    csvRows.push({ art, rows });
  }

  const rawSamplePoints = [];
  csvRows.forEach(({ rows }) => {
    rows.forEach((row) => {
      const pt = rowLatLon(row);
      if (pt) {
        rawSamplePoints.push(pt);
      }
      const geometryText = getValueByKeys(row, ['geometry', 'Geometry']);
      if (geometryText) {
        const line = parseLinestringWkt(geometryText);
        if (line.length >= 2) {
          rawSamplePoints.push(line[0], line[line.length - 1]);
        }
      }
    });
  });

  const coordMode = detectCoordinateMode(rawSamplePoints);
  if (renderVersion !== mapRenderVersion) {
    return;
  }
  setMapOrientationMode(coordMode);

  const nodeCoordById = new Map();
  csvRows.forEach(({ rows }) => {
    if (!rows.length) return;
    rows.forEach((row) => {
      const nodeIdRaw = getValueByKeys(row, ['node_id', 'Node_ID', 'ID']);
      const pt = applyBaseCrsTransform(orientPoint(rowLatLon(row), coordMode), coordMode);
      if (nodeIdRaw === null || !pt) return;
      nodeCoordById.set(String(nodeIdRaw), pt);
    });
  });

  for (const item of csvRows) {
    const { rows } = item;
    if (!rows.length) {
      continue;
    }
    const sampleKeys = Object.keys(rows[0]);
    const hasGeometry = sampleKeys.some((k) => k.toLowerCase() === 'geometry');
    const hasFromTo = (
      (sampleKeys.includes('From_Latitude') && sampleKeys.includes('From_Longitude'))
      || (sampleKeys.includes('from_node_id') && sampleKeys.includes('to_node_id'))
      || (sampleKeys.includes('From_Node') && sampleKeys.includes('To_Node'))
    );

    if (hasGeometry || hasFromTo) {
      rows.forEach((row) => {
        let line = [];
        const geometryText = getValueByKeys(row, ['geometry', 'Geometry']);
        if (geometryText) {
          line = parseLinestringWkt(geometryText)
            .map((pt) => orientPoint(pt, coordMode))
            .map((pt) => applyBaseCrsTransform(pt, coordMode));
        }
        if (!line.length && hasFromTo) {
          const fromLat = asNumber(getValueByKeys(row, ['From_Latitude', 'from_lat', 'from_latitude']));
          const fromLon = asNumber(getValueByKeys(row, ['From_Longitude', 'from_lon', 'from_longitude']));
          const toLat = asNumber(getValueByKeys(row, ['To_Latitude', 'to_lat', 'to_latitude']));
          const toLon = asNumber(getValueByKeys(row, ['To_Longitude', 'to_lon', 'to_longitude']));
          const p1 = applyBaseCrsTransform(orientPoint(normalizeLatLon(fromLat, fromLon), coordMode), coordMode);
          const p2 = applyBaseCrsTransform(orientPoint(normalizeLatLon(toLat, toLon), coordMode), coordMode);
          if (p1 && p2) {
            line = [p1, p2];
          }
        }

        if (!line.length) {
          const fromId = getValueByKeys(row, ['from_node_id', 'From_Node', 'from_node']);
          const toId = getValueByKeys(row, ['to_node_id', 'To_Node', 'to_node']);
          if (fromId !== null && toId !== null) {
            const p1 = nodeCoordById.get(String(fromId));
            const p2 = nodeCoordById.get(String(toId));
            if (p1 && p2) {
              line = [p1, p2];
            }
          }
        }
        if (line.length >= 2) {
          if (renderVersion !== mapRenderVersion) {
            return;
          }
          L.polyline(line, { color: '#0b6e4f', weight: 3.5, opacity: 0.95 }).addTo(mapLayers.links);
          line.forEach((pt) => bounds.push(pt));
          drawnLinks += 1;
        }
      });
      continue;
    }

    rows.forEach((row) => {
      const pt = applyBaseCrsTransform(orientPoint(rowLatLon(row), coordMode), coordMode);
      if (!pt) {
        return;
      }
      if (renderVersion !== mapRenderVersion) {
        return;
      }
      L.circleMarker(pt, {
        radius: 3,
        color: '#ef6c2f',
        fillColor: '#ef6c2f',
        fillOpacity: 0.85,
        weight: 1,
      }).addTo(mapLayers.nodes);
      bounds.push(pt);
      drawnNodes += 1;
    });
  }

  if (!bounds.length) {
    if (renderVersion !== mapRenderVersion) {
      return;
    }
    mapHintEl.textContent = '找到 CSV，但无法解析为经纬度坐标。';
    return;
  }

  if (renderVersion !== mapRenderVersion) {
    return;
  }
  scheduleMapResize();
  map.fitBounds(bounds, { padding: [20, 20] });
  mapHintEl.textContent = `已绘制节点 ${drawnNodes} 个，路段 ${drawnLinks} 条。`;
}

function renderProcess(data) {
  const lines = [];
  lines.push(`状态: ${data.status || '-'}`);
  lines.push(`进度: ${data.progress || 0}%`);
  lines.push(`当前步骤: ${data.current_stage || '-'}`);
  lines.push('');
  lines.push('步骤轨迹:');

  const history = Array.isArray(data.stage_history) ? data.stage_history : [];
  if (history.length === 0) {
    lines.push('- 暂无');
  } else {
    history.forEach((step, idx) => lines.push(`${idx + 1}. ${step}`));
  }

  const result = data.result || {};
  const stageDurations = Array.isArray(result.stage_durations) ? result.stage_durations : [];
  if (stageDurations.length > 0) {
    lines.push('');
    lines.push('阶段耗时:');
    stageDurations.forEach((item, idx) => {
      const name = (item && item.stage) ? String(item.stage) : `阶段${idx + 1}`;
      const sec = Number(item && item.seconds);
      let durationText = '-';
      if (Number.isFinite(sec)) {
        if (sec < 0.01) {
          durationText = `${(sec * 1000).toFixed(3)}ms`;
        } else {
          durationText = `${sec.toFixed(3)}s`;
        }
      }
      lines.push(`- ${name}: ${durationText}`);
    });
  }

  const agentToolSteps = Array.isArray(result.agent_tool_steps) ? result.agent_tool_steps : [];
  if (agentToolSteps.length > 0) {
    lines.push('');
    lines.push('Agent 工具调用摘要:');
    agentToolSteps.forEach((step, idx) => {
      const tool = step && step.tool ? String(step.tool) : 'unknown';
      const input = step && step.input ? String(step.input) : '';
      const observation = step && step.observation ? String(step.observation) : '';
      lines.push(`${idx + 1}. 工具: ${tool}`);
      if (input) {
        lines.push(`   输入: ${input}`);
      }
      if (observation) {
        lines.push(`   输出: ${observation}`);
      }
    });
  }

  if (data.status === 'completed' && result && result.message) {
    lines.push('');
    lines.push('结果摘要:');
    lines.push(String(result.message));
  }

  if (data.status === 'failed' && data.error) {
    lines.push('');
    lines.push('失败信息:');
    lines.push(String(data.error));
  }

  resultEl.textContent = lines.join('\n');
}

function setProgress(value) {
  const p = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
  progressFillEl.style.width = `${p}%`;
}

function closeEventSource() {
  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
  }
}

function setBatchDownload(taskId, enabled) {
  currentTaskId = taskId || null;
  downloadAllBtn.disabled = !enabled;
  setCancelButtonEnabled(Boolean(taskId) && enabled === false);
}

async function cancelTask(taskId) {
  if (!taskId) {
    return;
  }
  try {
    const resp = await fetch(`/api/tasks/${taskId}/cancel`, { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      appendResult('取消任务失败', data.error || data, true);
      return;
    }
    appendResult('取消任务', data.message || '已提交取消请求');
    if (taskId === currentTaskId) {
      setCancelButtonEnabled(false);
    }
    fetchTaskHistory();
  } catch (err) {
    appendResult('取消任务异常', String(err), true);
  }
}

function closeConfirmDialog(confirmed) {
  if (!confirmDialogEl || !confirmDialogResolver) {
    return;
  }
  confirmDialogEl.classList.add('is-hidden');
  confirmDialogEl.setAttribute('aria-hidden', 'true');
  const resolve = confirmDialogResolver;
  confirmDialogResolver = null;
  if (confirmDialogLastActiveEl && typeof confirmDialogLastActiveEl.focus === 'function') {
    confirmDialogLastActiveEl.focus();
  }
  confirmDialogLastActiveEl = null;
  resolve(Boolean(confirmed));
}

function handleConfirmDialogKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault();
    closeConfirmDialog(false);
  }
}

function confirmHistoryDeletion(message) {
  if (!confirmDialogEl || !confirmDialogMessageEl || !confirmDialogCancelBtn || !confirmDialogConfirmBtn) {
    return Promise.resolve(window.confirm(message));
  }

  if (confirmDialogResolver) {
    return Promise.resolve(false);
  }

  confirmDialogLastActiveEl = document.activeElement;
  confirmDialogMessageEl.textContent = message;
  confirmDialogEl.classList.remove('is-hidden');
  confirmDialogEl.setAttribute('aria-hidden', 'false');

  return new Promise((resolve) => {
    confirmDialogResolver = resolve;
    window.setTimeout(() => {
      confirmDialogConfirmBtn.focus();
    }, 0);
  });
}

async function deleteTask(taskId) {
  if (!taskId) {
    return;
  }
  if (!(await confirmHistoryDeletion('确认删除这条任务记录吗？'))) {
    return;
  }
  try {
    const resp = await fetch(`/api/tasks/${taskId}/delete`, { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      appendResult('删除任务失败', data.error || data, true);
      return;
    }

    appendResult('删除任务', data.message || '任务记录已删除');
    if (taskId === currentTaskId) {
      closeEventSource();
      setBatchDownload(null, false);
      setCancelButtonEnabled(false);
      taskMetaEl.textContent = '当前无任务';
      setProgress(0);
      renderArtifacts([]);
      clearMapNetwork();
      scheduleMapResize();
      mapHintEl.textContent = '等待任务结果...';
      setMapOrientationMode('unknown');
    }
    fetchTaskHistory();
  } catch (err) {
    appendResult('删除任务异常', String(err), true);
  }
}

async function clearTaskHistory() {
  if (!(await confirmHistoryDeletion('确认一键删除所有已结束的任务历史吗？运行中或排队中的任务会保留。'))) {
    return;
  }
  try {
    const resp = await fetch('/api/tasks/clear', { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      appendResult('一键删除失败', data.error || data, true);
      return;
    }

    const deletedIds = Array.isArray(data.deleted_task_ids) ? data.deleted_task_ids.map((x) => String(x)) : [];
    appendResult('一键删除', data.message || '已清理历史记录');

    if (currentTaskId && deletedIds.includes(String(currentTaskId))) {
      closeEventSource();
      setBatchDownload(null, false);
      setCancelButtonEnabled(false);
      taskMetaEl.textContent = '当前无任务';
      setProgress(0);
      renderArtifacts([]);
      clearMapNetwork();
      scheduleMapResize();
      mapHintEl.textContent = '等待任务结果...';
      setMapOrientationMode('unknown');
      setBaseSourceText('底图：-');
    }

    fetchTaskHistory();
  } catch (err) {
    appendResult('一键删除异常', String(err), true);
  }
}

function renderTaskHistory(tasks) {
  historyListEl.innerHTML = '';
  if (!Array.isArray(tasks) || tasks.length === 0) {
    historyListEl.innerHTML = '<p class="artifact-empty">暂无任务历史</p>';
    return;
  }

  tasks.forEach((task) => {
    const item = document.createElement('article');
    item.className = 'history-item';

    const titleRow = document.createElement('div');
    titleRow.className = 'history-title-row';

    const title = document.createElement('h4');
    const displayTitle = task.display_title || task.task_type || '任务';
    title.textContent = displayTitle;
    title.title = displayTitle;
    titleRow.appendChild(title);

    const status = document.createElement('span');
    status.className = `history-status status-${task.status || 'unknown'}`;
    const rawStatus = String(task.status || 'unknown');
    status.textContent = rawStatus
      .split(/[-_\s]+/)
      .filter((x) => x)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(' ');
    titleRow.appendChild(status);

    item.appendChild(titleRow);

    const meta = document.createElement('p');
    meta.className = 'history-meta';
    meta.textContent = `ID: ${task.task_id} | 进度: ${task.progress || 0}% | 当前步骤: ${task.current_stage || '-'}`;
    item.appendChild(meta);

    const time = document.createElement('p');
    time.className = 'history-time';
    time.textContent = `创建: ${task.created_at || '-'}  结束: ${task.ended_at || '-'}`;
    item.appendChild(time);

    const row = document.createElement('div');
    row.className = 'history-actions';

    const loadBtn = document.createElement('button');
    loadBtn.type = 'button';
    loadBtn.className = 'ghost';
    loadBtn.textContent = '查看进度';
    loadBtn.addEventListener('click', () => monitorTask(task.task_id, '/api/tasks'));
    row.appendChild(loadBtn);

    const canCancel = ['pending', 'running'].includes(task.status);
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'ghost cancel-action';
    cancelBtn.textContent = canCancel ? '取消' : '不可取消';
    cancelBtn.disabled = !canCancel;
    cancelBtn.addEventListener('click', () => cancelTask(task.task_id));
    row.appendChild(cancelBtn);

    const canDelete = !['pending', 'running'].includes(task.status);
    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'ghost danger';
    deleteBtn.textContent = canDelete ? '删除' : '运行中';
    deleteBtn.disabled = !canDelete;
    deleteBtn.addEventListener('click', () => deleteTask(task.task_id));
    row.appendChild(deleteBtn);

    item.appendChild(row);
    historyListEl.appendChild(item);
  });
}

async function fetchTaskHistory() {
  try {
    const resp = await fetch('/api/tasks?limit=30');
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      return;
    }
    renderTaskHistory(data.tasks || []);
  } catch (_err) {
    // no-op
  }
}

function classifyArtifact(item) {
  const name = String(item?.name || '').toLowerCase();
  const label = String(item?.label || '').toLowerCase();
  const path = String(item?.path || '').toLowerCase();
  const haystack = `${name} ${label} ${path}`;

  if (item?.is_image) {
    if (haystack.includes('输入图片') || haystack.includes('input')) {
      return 'input';
    }
    return 'preview';
  }

  if (name.endsWith('.geojson')) {
    return 'geojson';
  }

  if (
    name.endsWith('.zip')
    || name.endsWith('.csv')
    || haystack.includes('gmns')
    || name === 'node.csv'
    || name === 'link.csv'
    || name.startsWith('nodes_')
    || name.startsWith('edges_')
  ) {
    return 'gmns';
  }

  return 'other';
}

function classifyArtifactBucket(item) {
  const groupKey = classifyArtifact(item);
  const name = String(item?.name || '').toLowerCase();

  if (groupKey === 'gmns') {
    if (name.endsWith('.zip')) {
      return 'gmns_zip';
    }
    return 'gmns_table';
  }

  return groupKey;
}

function extractArtifactResultIndex(item) {
  const candidates = [String(item?.label || ''), String(item?.name || ''), String(item?.path || '')];
  for (const candidate of candidates) {
    const match = candidate.match(/结果文件\s*(\d+)/);
    if (match) {
      return Number.parseInt(match[1], 10);
    }
  }
  return Number.POSITIVE_INFINITY;
}

function compareArtifacts(left, right) {
  const leftIndex = extractArtifactResultIndex(left);
  const rightIndex = extractArtifactResultIndex(right);
  if (leftIndex !== rightIndex) {
    return leftIndex - rightIndex;
  }

  const leftLabel = String(left?.label || left?.name || '');
  const rightLabel = String(right?.label || right?.name || '');
  return leftLabel.localeCompare(rightLabel, 'zh-CN', { numeric: true, sensitivity: 'base' });
}

function getGroupSortIndex(config) {
  const items = [];
  if (Array.isArray(config?.items)) {
    items.push(...config.items);
  }
  if (Array.isArray(config?.subgroups)) {
    config.subgroups.forEach((subgroup) => {
      if (Array.isArray(subgroup?.items)) {
        items.push(...subgroup.items);
      }
    });
  }

  if (!items.length) {
    return Number.POSITIVE_INFINITY;
  }

  return items.reduce((minValue, item) => {
    const currentIndex = extractArtifactResultIndex(item);
    return currentIndex < minValue ? currentIndex : minValue;
  }, Number.POSITIVE_INFINITY);
}

function getArtifactGroupMeta(groupKey) {
  const mapping = {
    geojson: {
      title: 'GeoJSON',
      desc: 'Leaflet 优先使用的展示与交换格式',
    },
    gmns: {
      title: 'GMNS / CSV',
      desc: '标准路网交换文件，按压缩包和明细表分开展示',
    },
    gmns_zip: {
      title: '压缩包',
      desc: '适合打包下载和整体转交的 GMNS 结果',
    },
    gmns_table: {
      title: '明细表',
      desc: '节点、路段等 CSV 明细文件',
    },
    preview: {
      title: '预览图',
      desc: '任务结果图像与可视化输出',
    },
    input: {
      title: '输入图片',
      desc: '本次任务上传的原始图像',
    },
    other: {
      title: '其他文件',
      desc: '未归类的补充结果文件',
    },
  };
  return mapping[groupKey] || mapping.other;
}

function getArtifactDownloadLabel(item) {
  const name = String(item?.name || '').toLowerCase();
  const rawName = String(item?.name || '').trim();
  if (name.endsWith('.geojson')) {
    return '下载 GeoJSON';
  }
  if (name.endsWith('.csv')) {
    return rawName ? `下载 ${rawName}` : '下载 CSV';
  }
  if (name.endsWith('.zip')) {
    return rawName ? `下载 ${rawName}` : '下载 ZIP';
  }
  if (item?.is_image) {
    return '下载图片';
  }
  return '下载';
}

function formatArtifactMetaText(desc, itemCount) {
  if (!desc) {
    return `${itemCount} 个文件`;
  }
  return `${desc}（${itemCount} 个文件）`;
}

function buildArtifactCard(item) {
  const card = document.createElement('article');
  card.className = 'artifact-item';

  const title = document.createElement('h4');
  title.textContent = item.label || item.name || '产物文件';
  card.appendChild(title);

  if (item.is_image && item.view_url) {
    const img = document.createElement('img');
    img.src = item.view_url;
    img.alt = item.name || '预览图';
    img.className = 'artifact-preview';
    card.appendChild(img);
  }

  const btnRow = document.createElement('div');
  btnRow.className = 'artifact-actions';

  if (item.view_url && item.is_image) {
    const viewBtn = document.createElement('button');
    viewBtn.type = 'button';
    viewBtn.className = 'ghost mini-tool-btn map-mode-toggle artifact-download-btn';
    viewBtn.textContent = '查看预览';
    viewBtn.addEventListener('click', () => window.open(item.view_url, '_blank'));
    btnRow.appendChild(viewBtn);
  }

  const downBtn = document.createElement('button');
  downBtn.type = 'button';
  downBtn.className = 'ghost mini-tool-btn map-mode-toggle artifact-download-btn';
  downBtn.textContent = getArtifactDownloadLabel(item);
  downBtn.addEventListener('click', () => {
    if (item.download_url) {
      window.open(item.download_url, '_blank');
    }
  });
  btnRow.appendChild(downBtn);

  card.appendChild(btnRow);
  return card;
}

function buildArtifactGroupToggle(groupKey, meta, itemCount, expanded) {
  const head = document.createElement('div');
  head.className = 'artifact-group-head';

  const headText = document.createElement('div');
  headText.className = 'artifact-group-title-wrap';

  const title = document.createElement('h4');
  title.className = 'artifact-group-title';
  title.textContent = meta.title;
  headText.appendChild(title);

  const metaLine = document.createElement('p');
  metaLine.className = 'artifact-group-meta';

  const metaText = document.createElement('span');
  metaText.className = 'artifact-group-meta-text';
  metaText.textContent = formatArtifactMetaText(meta.desc, itemCount);
  metaLine.appendChild(metaText);

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'artifact-group-toggle ghost mini-tool-btn';
  button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  button.textContent = expanded ? '收起' : '展开';

  button.addEventListener('click', () => {
    if (expandedArtifactGroups.has(groupKey)) {
      expandedArtifactGroups.delete(groupKey);
    } else {
      expandedArtifactGroups.add(groupKey);
    }
    renderArtifacts(lastArtifacts);
  });

  metaLine.appendChild(button);

  headText.appendChild(metaLine);
  head.appendChild(headText);

  return head;
}

function buildArtifactList(items) {
  const list = document.createElement('div');
  list.className = 'artifact-group-list';
  items.forEach((item) => {
    list.appendChild(buildArtifactCard(item));
  });
  return list;
}

function buildArtifactSubgroup(groupKey, items) {
  const meta = getArtifactGroupMeta(groupKey);
  const section = document.createElement('section');
  section.className = 'artifact-subgroup';

  const head = document.createElement('div');
  head.className = 'artifact-subgroup-head';

  const textWrap = document.createElement('div');
  textWrap.className = 'artifact-subgroup-title-wrap';

  const title = document.createElement('h5');
  title.className = 'artifact-subgroup-title';
  title.textContent = meta.title;
  textWrap.appendChild(title);

  const metaLine = document.createElement('p');
  metaLine.className = 'artifact-subgroup-meta';

  const metaText = document.createElement('span');
  metaText.className = 'artifact-subgroup-meta-text';
  metaText.textContent = formatArtifactMetaText(meta.desc, items.length);
  metaLine.appendChild(metaText);

  textWrap.appendChild(metaLine);

  head.appendChild(textWrap);
  section.appendChild(head);
  section.appendChild(buildArtifactList(items));

  return section;
}

function buildArtifactGroupSection(groupKey, config) {
  const meta = getArtifactGroupMeta(groupKey);
  const section = document.createElement('section');
  const expanded = expandedArtifactGroups.has(groupKey);
  section.className = `artifact-group${expanded ? '' : ' is-collapsed'}`;

  section.appendChild(buildArtifactGroupToggle(groupKey, meta, config.count, expanded));

  const body = document.createElement('div');
  body.className = 'artifact-group-body';
  body.hidden = !expanded;

  if (Array.isArray(config.subgroups) && config.subgroups.length) {
    config.subgroups.forEach((subgroup) => {
      body.appendChild(buildArtifactSubgroup(subgroup.key, subgroup.items));
    });
  } else {
    body.appendChild(buildArtifactList(config.items || []));
  }

  section.appendChild(body);
  return section;
}

function renderArtifacts(artifacts) {
  artifactListEl.innerHTML = '';
  if (!Array.isArray(artifacts) || artifacts.length === 0) {
    lastArtifacts = [];
    artifactListEl.innerHTML = '<p class="artifact-empty">暂无可下载文件</p>';
    return;
  }

  lastArtifacts = artifacts.slice();

  const fallbackGroupOrder = ['geojson', 'gmns', 'preview', 'input', 'other'];
  const bucketOrder = ['geojson', 'gmns_zip', 'gmns_table', 'preview', 'input', 'other'];
  const buckets = new Map(bucketOrder.map((key) => [key, []]));

  artifacts.forEach((item) => {
    const bucketKey = classifyArtifactBucket(item);
    if (!buckets.has(bucketKey)) {
      buckets.set(bucketKey, []);
    }
    buckets.get(bucketKey).push(item);
  });

  const groups = new Map();
  groups.set('geojson', {
    count: (buckets.get('geojson') || []).length,
    items: (buckets.get('geojson') || []).slice().sort(compareArtifacts),
  });
  groups.set('gmns', {
    count: (buckets.get('gmns_zip') || []).length + (buckets.get('gmns_table') || []).length,
    subgroups: [
      { key: 'gmns_zip', items: (buckets.get('gmns_zip') || []).slice().sort(compareArtifacts) },
      { key: 'gmns_table', items: (buckets.get('gmns_table') || []).slice().sort(compareArtifacts) },
    ].filter((entry) => entry.items.length > 0),
  });
  groups.set('preview', {
    count: (buckets.get('preview') || []).length,
    items: (buckets.get('preview') || []).slice().sort(compareArtifacts),
  });
  groups.set('input', {
    count: (buckets.get('input') || []).length,
    items: (buckets.get('input') || []).slice().sort(compareArtifacts),
  });
  groups.set('other', {
    count: (buckets.get('other') || []).length,
    items: (buckets.get('other') || []).slice().sort(compareArtifacts),
  });

  if (!groups.get('geojson')?.count && expandedArtifactGroups.size === 1 && expandedArtifactGroups.has('geojson')) {
    const firstNonEmptyKey = fallbackGroupOrder.find((key) => (groups.get(key)?.count || 0) > 0);
    if (firstNonEmptyKey && firstNonEmptyKey !== 'geojson') {
      expandedArtifactGroups.clear();
      expandedArtifactGroups.add(firstNonEmptyKey);
    }
  }

  const orderedGroupKeys = Array.from(groups.entries())
    .filter(([, config]) => config && config.count)
    .sort((leftEntry, rightEntry) => {
      const leftKey = leftEntry[0];
      const rightKey = rightEntry[0];
      const leftIndex = getGroupSortIndex(leftEntry[1]);
      const rightIndex = getGroupSortIndex(rightEntry[1]);
      if (leftIndex !== rightIndex) {
        return leftIndex - rightIndex;
      }
      return fallbackGroupOrder.indexOf(leftKey) - fallbackGroupOrder.indexOf(rightKey);
    })
    .map(([groupKey]) => groupKey);

  orderedGroupKeys.forEach((groupKey) => {
    const config = groups.get(groupKey);
    if (!config || !config.count) {
      return;
    }

    artifactListEl.appendChild(buildArtifactGroupSection(groupKey, config));
  });
}

async function fetchTaskSnapshot(taskId) {
  const resp = await fetch(`/api/tasks/${taskId}`);
  if (!resp.ok) {
    throw new Error(`任务查询失败: HTTP ${resp.status}`);
  }
  const data = await resp.json();
  if (!data.ok || !data.task) {
    throw new Error('任务查询返回异常');
  }
  return data.task;
}

async function pollTaskFallback(taskId, isChatFlow) {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    try {
      // eslint-disable-next-line no-await-in-loop
      const task = await fetchTaskSnapshot(taskId);
      setProgress(task.progress ?? 0);
      const queueText = task.status === 'pending' ? `，队列位置 ${task.queue_position || 0}` : '';
      const taskName = task.display_title || task.task_type || '任务';
      taskMetaEl.textContent = `任务：${taskName} | ${task.status}${queueText} | ${task.progress || 0}%`;
      renderProcess(task);

      if (task.status !== 'completed') {
        if (task.status === 'pending') {
          mapHintEl.textContent = '任务排队中，正在轮询获取最新状态。';
        } else if (task.status === 'running') {
          mapHintEl.textContent = '任务运行中，正在轮询获取最新状态。';
        }
      }

      if (task.status === 'completed') {
        const artifacts = (task.result && task.result.artifacts) || [];
        invalidateMapRender();
        renderArtifacts(artifacts);
        renderNetworkOnMap(artifacts).catch(() => {
          mapHintEl.textContent = '地图绘制失败，请检查结果文件格式。';
        });
        if (isChatFlow) {
          const msg = (task.result && (task.result.chat_message || task.result.message)) || '任务已完成。';
          appendChatMessage('assistant', String(msg));
        }
        setBatchDownload(task.task_id, artifacts.length > 0);
        setCancelButtonEnabled(false);
        if (isChatFlow) {
          clearPendingChatTask(task.task_id);
        }
        fetchTaskHistory();
        return;
      }

      if (task.status === 'failed') {
        if (isChatFlow) {
          const errMsg = task.error || '任务执行失败。';
          appendChatMessage('assistant', `任务失败：${String(errMsg)}`);
        }
        setBatchDownload(task.task_id, false);
        setCancelButtonEnabled(false);
        if (isChatFlow) {
          clearPendingChatTask(task.task_id);
        }
        fetchTaskHistory();
        return;
      }

      if (task.status === 'canceled') {
        if (isChatFlow) {
          appendChatMessage('assistant', '任务已取消。');
        }
        setBatchDownload(task.task_id, false);
        setCancelButtonEnabled(false);
        if (isChatFlow) {
          clearPendingChatTask(task.task_id);
        }
        fetchTaskHistory();
        return;
      }
    } catch (_err) {
      // ignore transient polling failures
    }

    // eslint-disable-next-line no-await-in-loop
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }

  try {
    const task = await fetchTaskSnapshot(taskId);
    setProgress(task.progress ?? 0);
    renderProcess(task);
  } catch (_err) {
    // ignore final snapshot failure
  }

  if (isChatFlow) {
    appendChatMessage('assistant', '连接已切换为轮询，但任务仍未结束。你可以在任务历史里继续查看进度。');
  }
}

function monitorTask(taskId, endpointLabel) {
  closeEventSource();
  invalidateMapRender();
  const isChatFlow = endpointLabel === '/api/chat';
  if (isChatFlow) {
    setPendingChatTask(taskId);
  }
  const eventUrl = `/api/tasks/${taskId}/events`;
  const es = new EventSource(eventUrl);
  activeEventSource = es;
  setBatchDownload(taskId, false);
  setCancelButtonEnabled(true);
  taskMetaEl.textContent = '任务已创建，等待执行...';
  setProgress(0);
  renderArtifacts([]);
  clearMapNetwork();
  scheduleMapResize();
  mapHintEl.textContent = '该任务尚未完成，暂无路网图可展示。';
  setMapOrientationMode('unknown');

  es.onmessage = (event) => {
    const data = JSON.parse(event.data);
    setProgress(data.progress ?? 0);
    const queueText = data.status === 'pending' ? `，队列位置 ${data.queue_position || 0}` : '';
    const taskName = data.display_title || data.task_type || '任务';
    taskMetaEl.textContent = `任务：${taskName} | ${data.status}${queueText} | ${data.progress || 0}%`;
    renderProcess(data);

    if (data.status !== 'completed') {
      invalidateMapRender();
      renderArtifacts([]);
      clearMapNetwork();
      if (data.status === 'pending') {
        mapHintEl.textContent = '任务排队中，暂无路网图可展示。';
      } else if (data.status === 'running') {
        mapHintEl.textContent = '任务运行中，暂无路网图可展示。';
      } else if (data.status === 'failed') {
        mapHintEl.textContent = '任务失败，暂无路网图可展示。';
      } else if (data.status === 'canceled') {
        mapHintEl.textContent = '任务已取消，暂无路网图可展示。';
      }
      setMapOrientationMode('unknown');
    }

    if (data.status === 'completed') {
      const artifacts = (data.result && data.result.artifacts) || [];
      invalidateMapRender();
      renderArtifacts(artifacts);
      renderNetworkOnMap(artifacts).catch(() => {
        mapHintEl.textContent = '地图绘制失败，请检查结果文件格式。';
      });
      if (isChatFlow) {
        const msg = (data.result && (data.result.chat_message || data.result.message)) || '任务已完成。';
        appendChatMessage('assistant', String(msg));
      }
      setBatchDownload(data.task_id, artifacts.length > 0);
      setCancelButtonEnabled(false);
      if (isChatFlow) {
        clearPendingChatTask(data.task_id);
      }
      fetchTaskHistory();
      es.close();
      activeEventSource = null;
    }

    if (data.status === 'failed') {
      if (isChatFlow) {
        const errMsg = data.error || '任务执行失败。';
        appendChatMessage('assistant', `任务失败：${String(errMsg)}`);
      }
      setBatchDownload(data.task_id, false);
      setCancelButtonEnabled(false);
      if (isChatFlow) {
        clearPendingChatTask(data.task_id);
      }
      fetchTaskHistory();
      es.close();
      activeEventSource = null;
    }

    if (data.status === 'canceled') {
      if (isChatFlow) {
        appendChatMessage('assistant', '任务已取消。');
      }
      setBatchDownload(data.task_id, false);
      setCancelButtonEnabled(false);
      if (isChatFlow) {
        clearPendingChatTask(data.task_id);
      }
      fetchTaskHistory();
      es.close();
      activeEventSource = null;
    }
  };

  es.onerror = () => {
    resultEl.textContent += '\n\n[提示] 过程流中断，请检查服务状态。';
    es.close();
    activeEventSource = null;

    if (isChatFlow) {
      appendChatMessage('assistant', '过程流连接中断，正在自动重试获取结果...');
      pollTaskFallback(taskId, true);
    }
  };
}

async function resumePendingChatTask() {
  const pendingTaskId = getPendingChatTask();
  if (!pendingTaskId) {
    return;
  }

  try {
    const task = await fetchTaskSnapshot(pendingTaskId);
    const queueText = task.status === 'pending' ? `，队列位置 ${task.queue_position || 0}` : '';
    const taskName = task.display_title || task.task_type || '任务';
    taskMetaEl.textContent = `任务：${taskName} | ${task.status}${queueText} | ${task.progress || 0}%`;
    setProgress(task.progress ?? 0);
    renderProcess(task);

    if (task.status === 'pending' || task.status === 'running') {
      appendChatMessage('assistant', '检测到有未完成的对话任务，已自动恢复结果跟踪。');
      monitorTask(pendingTaskId, '/api/chat');
      return;
    }

    if (task.status === 'completed') {
      const artifacts = (task.result && task.result.artifacts) || [];
      invalidateMapRender();
      renderArtifacts(artifacts);
      renderNetworkOnMap(artifacts).catch(() => {
        mapHintEl.textContent = '地图绘制失败，请检查结果文件格式。';
      });
      setBatchDownload(task.task_id, artifacts.length > 0);
      setCancelButtonEnabled(false);
      fetchTaskHistory();
      const msg = (task.result && (task.result.chat_message || task.result.message)) || '任务已完成。';
      appendChatMessage('assistant', String(msg));
      clearPendingChatTask(pendingTaskId);
      return;
    }

    if (task.status === 'failed') {
      renderArtifacts([]);
      clearMapNetwork();
      scheduleMapResize();
      mapHintEl.textContent = '任务失败，暂无路网图可展示。';
      setMapOrientationMode('unknown');
      setBatchDownload(task.task_id, false);
      setCancelButtonEnabled(false);
      fetchTaskHistory();
      appendChatMessage('assistant', `任务失败：${String(task.error || '任务执行失败。')}`);
      clearPendingChatTask(pendingTaskId);
      return;
    }

    if (task.status === 'canceled') {
      renderArtifacts([]);
      clearMapNetwork();
      scheduleMapResize();
      mapHintEl.textContent = '任务已取消，暂无路网图可展示。';
      setMapOrientationMode('unknown');
      setBatchDownload(task.task_id, false);
      setCancelButtonEnabled(false);
      fetchTaskHistory();
      appendChatMessage('assistant', '任务已取消。');
      clearPendingChatTask(pendingTaskId);
      return;
    }
  } catch (_err) {
    // Keep the pending task id and try again on next refresh.
  }
}

async function submitForm(form) {
  const endpoint = form.dataset.endpoint;
  const fd = new FormData(form);
  const fileInput = form.querySelector('input[type="file"][name="image_file"]');
  const imagePathInput = form.querySelector('input[name="image_path"]');
  if (fileInput && fileInput.files && fileInput.files.length > 0) {
    const check = validateUploadFile(fileInput.files[0]);
    if (!check.ok) {
      appendResult('上传校验失败', check.message, true);
      return;
    }
    appendResult('已选择上传文件', `${fileInput.files[0].name} (${formatBytes(fileInput.files[0].size)})`);
  } else if (imagePathInput && (imagePathInput.value || '').trim()) {
    appendResult('已使用图片路径', (imagePathInput.value || '').trim());
  }
  const submitBtn = form.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  const oldText = submitBtn.textContent;
  submitBtn.textContent = '执行中...';

  try {
    const resp = await fetch(endpoint, {
      method: 'POST',
      body: fd,
    });
    const data = await resp.json();

    if (!resp.ok || !data.ok) {
      appendResult(`${endpoint} 失败`, data.error || data, true);
      return;
    }
    form.reset();
    if (fileInput) {
      fileInput.dispatchEvent(new Event('change'));
    }
    renderArtifacts([]);
    resultEl.textContent = `任务已入队\n任务ID: ${data.task_id}\n队列位置: ${data.queue_position || 0}`;
    monitorTask(data.task_id, endpoint);
    fetchTaskHistory();
  } catch (err) {
    appendResult(`${endpoint} 异常`, String(err), true);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = oldText;
  }
}

forms.forEach((form) => {
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    submitForm(form);
  });
});

if (chatForm) {
  if (chatInput) {
    chatInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        chatForm.requestSubmit();
      }
    });
  }

  chatForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const msg = (chatInput.value || '').trim();
    const hasFile = chatImage.files && chatImage.files.length > 0;
    if (!msg && !hasFile) {
      appendChatMessage('assistant', '请输入文字或上传图片后再发送。');
      return;
    }

    if (msg) {
      appendChatMessage('user', msg);
    } else if (hasFile) {
      appendChatMessage('user', `已上传图片：${chatImage.files[0].name}`);
    }

    const fd = new FormData();
    fd.append('message', msg);
    if (hasFile) {
      const check = validateUploadFile(chatImage.files[0]);
      if (!check.ok) {
        appendChatMessage('assistant', check.message);
        return;
      }
      fd.append('image_file', chatImage.files[0]);
    }

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        body: fd,
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        appendChatMessage('assistant', `请求失败：${(data && data.error) || '未知错误'}`);
        return;
      }

      appendChatMessage('assistant', data.assistant || '已收到你的请求。');
      chatInput.value = '';
      chatImage.value = '';
      chatImage.dispatchEvent(new Event('change'));

      if (data.task && data.task.task_id) {
        renderArtifacts([]);
        resultEl.textContent = `任务已入队\n任务ID: ${data.task.task_id}\n队列位置: ${data.task.queue_position || 0}`;
        monitorTask(data.task.task_id, '/api/chat');
        fetchTaskHistory();
      }
    } catch (err) {
      appendChatMessage('assistant', `请求异常：${String(err)}`);
    }
  });
}

bindUploadStatusHints();
restoreChatMessages();
syncServerSession().finally(() => {
  resumePendingChatTask();
});

if (toolsToggleBtn && toolsPanelEl) {
  updateToolsPanelState(false);
  toolsToggleBtn.addEventListener('click', () => {
    const currentlyCollapsed = toolsPanelEl.classList.contains('is-collapsed');
    updateToolsPanelState(currentlyCollapsed);
    scheduleMapResize();
  });
}

clearBtn.addEventListener('click', () => {
  closeEventSource();
  invalidateMapRender();
  setBatchDownload(null, false);
  setCancelButtonEnabled(false);
  taskMetaEl.textContent = '当前无任务';
  setProgress(0);
  resultEl.textContent = '等待操作...';
  renderArtifacts([]);
  clearMapNetwork();
  scheduleMapResize();
  mapHintEl.textContent = '等待任务结果...';
  setMapOrientationMode('unknown');
  resultEl.style.borderColor = '#a7c0b1';
});

downloadAllBtn.addEventListener('click', () => {
  if (!currentTaskId) {
    return;
  }
  window.open(`/api/tasks/${currentTaskId}/download-all`, '_blank');
});

cancelTaskBtn.addEventListener('click', () => {
  cancelTask(currentTaskId);
});

refreshHistoryBtn.addEventListener('click', () => {
  fetchTaskHistory();
});

if (clearHistoryBtn) {
  clearHistoryBtn.addEventListener('click', () => {
    clearTaskHistory();
  });
}

if (confirmDialogEl) {
  confirmDialogEl.addEventListener('click', (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.dataset.confirmClose === 'backdrop') {
      closeConfirmDialog(false);
    }
  });
  confirmDialogEl.addEventListener('keydown', handleConfirmDialogKeydown);
}

if (confirmDialogCancelBtn) {
  confirmDialogCancelBtn.addEventListener('click', () => {
    closeConfirmDialog(false);
  });
}

if (confirmDialogConfirmBtn) {
  confirmDialogConfirmBtn.addEventListener('click', () => {
    closeConfirmDialog(true);
  });
}

fetchTaskHistory();
