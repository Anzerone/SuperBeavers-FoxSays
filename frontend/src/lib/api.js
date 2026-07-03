const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function _token() {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem('st_token');
}

async function req(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const t = _token();
  if (t) headers['Authorization'] = `Bearer ${t}`;
  const res = await fetch(`${API_URL}${path}`, { headers, ...opts });
  if (!res.ok) {
    let d;
    try { d = (await res.json()).detail; } catch { d = await res.text(); }
    throw new Error(`API ${res.status}: ${d}`);
  }
  return res.json();
}

export const api = {
  health: () => req('/health'),
  explorer: (type, code, depth = 2) =>
    req(`/api/v1/explorer/${type}/${encodeURIComponent(code)}?depth=${depth}`),
  gapsData: (property) =>
    req(`/api/v1/gaps/data${property ? `?property=${encodeURIComponent(property)}` : ''}`),
  gapsStructural: (limit = 30) => req(`/api/v1/gaps/structural?limit=${limit}`),
  timeline: (material, property) =>
    req(`/api/v1/timeline?material=${encodeURIComponent(material)}&property=${encodeURIComponent(property)}`),
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
  enrichmentEvents: (limit = 50) => req(`/api/v1/admin/enrichment/events?limit=${limit}`),
  llmAvailability: () => req('/api/v1/explain/availability'),

  // Gap #4: compare
  compare: (a, b) =>
    req('/api/v1/compare', { method: 'POST', body: JSON.stringify({ a, b }) }),

  // Gap #7: history
  historyOf: (conclusionId) => req(`/api/v1/history/conclusion/${conclusionId}`),

  // Gap #8: auth
  login: (username, password) =>
    req('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  me: () => req('/api/v1/auth/me'),
  roles: () => req('/api/v1/auth/roles'),
  auditLog: (limit = 100, username = null) =>
    req(`/api/v1/auth/audit?limit=${limit}${username ? `&username=${username}` : ''}`),

  // Gap #3: export
  exportUrl: (format) => `${API_URL}/api/v1/export/${format}`,

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
        const res = await fetch(`${API_URL}/api/v1/ask`, {
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
        if (e.name !== 'AbortError') onError?.(e);
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
