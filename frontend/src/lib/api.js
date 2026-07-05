// Все запросы — same-origin (относительные пути). Next.js в next.config.mjs
// проксирует /api/* на backend. Работает и с localhost, и через любой туннель.
function _token() {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem('st_token');
}

// Дедуп in-flight GET-запросов: React StrictMode в dev вызывает useEffect
// дважды, а /gaps/data стоит по 1-2 секунды. Второй одинаковый GET,
// пока первый не ответил, переиспользует его promise.
const _inflight = new Map();

async function _rawReq(path, opts) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const t = _token();
  if (t) headers['Authorization'] = `Bearer ${t}`;
  const res = await fetch(path, { headers, ...opts });
  // Читаем тело ОДИН раз, потом решаем что это. Иначе на не-JSON ответах
  // (HTML-страница таймаута прокси, plain-text ошибка) второй вызов
  // res.text() падал с "body stream already read".
  const raw = await res.text();
  if (!res.ok) {
    let detail = raw;
    try { detail = JSON.parse(raw).detail || raw; } catch { /* raw as-is */ }
    throw new Error(`API ${res.status}: ${detail}`);
  }
  try { return JSON.parse(raw); }
  catch { throw new Error(`Ответ не JSON (${res.status}): ${raw.slice(0, 120)}`); }
}

async function req(path, opts = {}) {
  const method = (opts.method || 'GET').toUpperCase();
  // Только идемпотентные GET дедупим: POST/PUT/DELETE могут иметь побочные
  // эффекты и одинаковый URL — разный body.
  if (method !== 'GET') return _rawReq(path, opts);
  const key = path;
  const existing = _inflight.get(key);
  if (existing) return existing;
  const p = _rawReq(path, opts).finally(() => { _inflight.delete(key); });
  _inflight.set(key, p);
  return p;
}

export const api = {
  health: () => req('/health'),
  explorer: (type, code, depth = 1) =>
    req(`/api/v1/explorer/${type}/${encodeURIComponent(code)}?depth=${depth}`),
  gapsData: (property, topMaterials = 15) => {
    const params = new URLSearchParams();
    if (property) params.set('property', property);
    params.set('top_materials', String(topMaterials));
    return req(`/api/v1/gaps/data?${params.toString()}`);
  },
  gapsStructural: (limit = 30) => req(`/api/v1/gaps/structural?limit=${limit}`),
  autocomplete: (q, type = 'all') =>
    req(`/api/v1/search/autocomplete?q=${encodeURIComponent(q)}&type=${type}`),
  adminStatus: () => req('/api/v1/admin/status'),
  adminMetrics: () => req('/api/v1/admin/metrics'),
  adminStats: () => req('/api/v1/admin/stats'),
  nl2cypher: (question) =>
    req('/api/v1/search/nl2cypher', { method: 'POST', body: JSON.stringify({ question }) }),
  adminLoad: (path = null, urls = null) =>
    req('/api/v1/admin/load', { method: 'POST', body: JSON.stringify({ path, urls }) }),
  adminEnrich: (scope = 'new') =>
    req('/api/v1/admin/enrich', { method: 'POST', body: JSON.stringify({ scope }) }),
  adminExtract: (scope = 'new', limit = null) =>
    req('/api/v1/admin/extract', { method: 'POST', body: JSON.stringify({ scope, limit }) }),
  adminExtractCancel: () =>
    req('/api/v1/admin/extract/cancel', { method: 'POST', body: '{}' }),
  extractStatus: () => req('/api/v1/admin/extract/status'),
  usefulInfoEnrich: (limit = null) =>
    req('/api/v1/admin/useful_info/enrich', { method: 'POST', body: JSON.stringify({ limit }) }),
  usefulInfoEnrichCancel: () =>
    req('/api/v1/admin/useful_info/enrich/cancel', { method: 'POST', body: '{}' }),
  usefulInfoEnrichStatus: () => req('/api/v1/admin/useful_info/enrich/status'),
  // multipart upload не через req() — там жёстко Content-Type: application/json.
  // FormData сам проставит корректный multipart/form-data с boundary.
  corpusUpload: async (files) => {
    const fd = new FormData();
    for (const f of files) fd.append('files', f, f.name);
    const t = _token();
    const headers = {};
    if (t) headers['Authorization'] = `Bearer ${t}`;
    const res = await fetch('/api/v1/admin/corpus/upload', {
      method: 'POST', headers, body: fd,
    });
    const raw = await res.text();
    if (!res.ok) {
      let detail = raw;
      try { detail = JSON.parse(raw).detail || raw; } catch { /* raw as-is */ }
      throw new Error(`API ${res.status}: ${detail}`);
    }
    try { return JSON.parse(raw); }
    catch { throw new Error(`Ответ не JSON: ${raw.slice(0, 120)}`); }
  },
  enrichmentEvents: (limit = 50) => req(`/api/v1/admin/enrichment/events?limit=${limit}`),
  dataQuality: () => req('/api/v1/admin/data_quality'),
  relatedOf: (type, code, limit = 20) =>
    req(`/api/v1/explorer/${type}/${encodeURIComponent(code)}/related?limit=${limit}`),
  listEntities: (type, limit = 200) =>
    req(`/api/v1/explorer/list/${type}?limit=${limit}`),
  llmAvailability: () => req('/api/v1/explain/availability'),

  // Gap #4: compare
  compare: (a, b) =>
    req('/api/v1/compare', { method: 'POST', body: JSON.stringify({ a, b }) }),

  // Gap #8: auth
  login: (username, password) =>
    req('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  me: () => req('/api/v1/auth/me'),
  roles: () => req('/api/v1/auth/roles'),
  auditLog: (limit = 100, username = null) =>
    req(`/api/v1/auth/audit?limit=${limit}${username ? `&username=${username}` : ''}`),

  // Gap #3: export. Относительный путь: same-origin через Next.js rewrite
  // (см. next.config.mjs). API_URL глобально не объявлен — использовать его
  // означало ловить ReferenceError при первом же экспорте/стриме.
  exportUrl: (format) => `/api/v1/export/${format}`,

  /**
   * SSE-стрим для /ask с geo-фильтром и intent-hint.
   */
  streamAsk({ question, expand = true, geoFilter = 'any', intentHint = null,
              answerId = null,
              onIntent, onMatch, onSubgraph, onSources, onToken, onDone, onError }) {
    const ctrl = new AbortController();
    (async () => {
      try {
        const headers = { 'Content-Type': 'application/json' };
        const t = _token();
        if (t) headers['Authorization'] = `Bearer ${t}`;
        const res = await fetch('/api/v1/ask', {
          method: 'POST', headers,
          body: JSON.stringify({
            question, expand_query: expand,
            geo_filter: geoFilter,
            intent_hint: intentHint,
            answer_id: answerId,
          }),
          signal: ctrl.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const reader = res.body.getReader();
        const dec = new TextDecoder('utf-8');
        let buf = '';
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const parts = buf.split('\n\n');
          buf = parts.pop();
          for (const p of parts) {
            const lines = p.split('\n');
            let ev = 'message', data = '';
            for (const l of lines) {
              if (l.startsWith('event:')) ev = l.slice(6).trim();
              else if (l.startsWith('data:')) data += l.slice(5).trim();
            }
            let payload;
            try { payload = JSON.parse(data); } catch { payload = data; }
            switch (ev) {
              case 'intent': onIntent?.(payload); break;
              case 'match': onMatch?.(payload); break;
              case 'subgraph': onSubgraph?.(payload); break;
              case 'sources': onSources?.(payload); break;
              case 'token': onToken?.(payload.text || ''); break;
              case 'done': onDone?.(payload); return;
              case 'error': onError?.(new Error(payload.message || 'unknown')); return;
              case 'info': break;
            }
          }
        }
        onDone?.();
      } catch (e) {
        if (e.name === 'AbortError') return;
        // TypeError с "Failed to fetch" / "NetworkError" = соединение прервано.
        // Отдаём наверх понятное сообщение вместо голого 'network error'.
        const msg = (e && (e.message === 'Failed to fetch' || /network/i.test(e.message)))
          ? 'Соединение прервано (бэкенд занят или упал). Проверьте логи и повторите.'
          : (e && e.message) || 'Ошибка стрима';
        onError?.(new Error(msg));
      }
    })();
    return () => ctrl.abort();
  },
};

export function setToken(t) {
  if (typeof window === 'undefined') return;
  if (t) window.localStorage.setItem('st_token', t);
  else window.localStorage.removeItem('st_token');
}

export function getStoredUser() {
  if (typeof window === 'undefined') return null;
  try { return JSON.parse(window.localStorage.getItem('st_user') || 'null'); }
  catch { return null; }
}

export function setStoredUser(u) {
  if (typeof window === 'undefined') return;
  if (u) window.localStorage.setItem('st_user', JSON.stringify(u));
  else window.localStorage.removeItem('st_user');
}
