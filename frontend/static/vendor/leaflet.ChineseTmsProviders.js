/*
  Minimal Leaflet.ChineseTmsProviders-compatible helper.
  Provides: L.tileLayer.chinaProvider(providerName, options)

  Notes:
  - This is a small, self-contained subset tailored for this project.
  - It supports the providers we use in app.js: TianDiTu / GaoDe / OSM.
*/

(function initChineseTmsProviders(factory) {
  if (typeof window !== 'undefined' && window.L) {
    factory(window.L);
  }
})(function factory(L) {
  if (!L || !L.tileLayer) {
    return;
  }

  const providers = {
    // 天地图（经纬度瓦片：*_w）
    'TianDiTu.Normal.Map': {
      url: 'https://t{s}.tianditu.gov.cn/DataServer?T=vec_w&x={x}&y={y}&l={z}&tk={key}',
      options: { subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'], maxZoom: 18 },
    },
    'TianDiTu.Normal.Annotion': {
      url: 'https://t{s}.tianditu.gov.cn/DataServer?T=cva_w&x={x}&y={y}&l={z}&tk={key}',
      options: { subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'], maxZoom: 18 },
    },
    'TianDiTu.Satellite.Map': {
      url: 'https://t{s}.tianditu.gov.cn/DataServer?T=img_w&x={x}&y={y}&l={z}&tk={key}',
      options: { subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'], maxZoom: 18 },
    },
    'TianDiTu.Satellite.Annotion': {
      url: 'https://t{s}.tianditu.gov.cn/DataServer?T=cia_w&x={x}&y={y}&l={z}&tk={key}',
      options: { subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'], maxZoom: 18 },
    },

    // 高德（GCJ-02）
    'GaoDe.Normal.Map': {
      url: 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={x}&y={y}&z={z}{keyPart}',
      options: { subdomains: ['1', '2', '3', '4'], maxZoom: 19 },
    },
    'GaoDe.Satellite.Map': {
      url: 'https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}{keyPart}',
      options: { subdomains: ['1', '2', '3', '4'], maxZoom: 19 },
    },

    // OSM
    'OSM.Normal.Map': {
      url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      options: { maxZoom: 19, subdomains: ['a', 'b', 'c'] },
    },
    'OSM.DE.Map': {
      url: 'https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png',
      options: { maxZoom: 19, subdomains: ['a', 'b', 'c'] },
    },
  };

  function encodeKey(key) {
    if (!key) return '';
    try {
      return encodeURIComponent(String(key));
    } catch (_err) {
      return '';
    }
  }

  function normalizeOptions(options) {
    if (!options || typeof options !== 'object') {
      return {};
    }
    return options;
  }

  function buildUrl(template, options) {
    const key = encodeKey(options.key);
    // TianDiTu uses tk={key}, GaoDe uses &key=... appended.
    const keyPart = key ? `&key=${key}` : '';
    return String(template)
      .replaceAll('{key}', key)
      .replaceAll('{keyPart}', keyPart);
  }

  L.tileLayer.chinaProvider = function chinaProvider(providerName, options) {
    const def = providers[String(providerName || '')];
    if (!def) {
      throw new Error(`Unknown chinaProvider: ${providerName}`);
    }

    const opts = normalizeOptions(options);
    const url = buildUrl(def.url, opts);
    const merged = Object.assign({}, def.options || {}, opts);
    // Don't leak our helper-only options into Leaflet tileLayer options.
    delete merged.key;
    delete merged.keyPart;
    return L.tileLayer(url, merged);
  };
});
