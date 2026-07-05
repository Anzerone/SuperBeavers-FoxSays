'use client';

import { Loader2, Scale, ArrowLeftRight } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import PageHeader from '@/components/shell/PageHeader';

export default function ComparePage() {
  const [aKind, setAKind] = useState('material');
  const [aCode, setACode] = useState('');
  const [bKind, setBKind] = useState('material');
  const [bCode, setBCode] = useState('');
  const [aOptions, setAOptions] = useState([]);
  const [bOptions, setBOptions] = useState([]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.listEntities(aKind, 500).then((r) => {
      setAOptions(r.items || []);
      if (r.items?.length && !r.items.find((x) => x.code === aCode)) setACode(r.items[0].code);
    }).catch(() => setAOptions([]));
  }, [aKind]);

  useEffect(() => {
    api.listEntities(bKind, 500).then((r) => {
      setBOptions(r.items || []);
      if (r.items?.length && !r.items.find((x) => x.code === bCode)) setBCode(r.items[0].code);
    }).catch(() => setBOptions([]));
  }, [bKind]);

  async function run() {
    setLoading(true); setErr(null);
    try {
      setData(await api.compare(
        { kind: aKind, code: aCode }, { kind: bKind, code: bCode },
      ));
    } catch (e) { setErr(e.message); }
    setLoading(false);
  }

  function trend(delta) {
    if (delta === null || delta === undefined) return null;
    if (delta > 0) return { color: 'text-green-700', symbol: '↗', label: '+' };
    if (delta < 0) return { color: 'text-brand-red', symbol: '↘', label: '' };
    return { color: 'text-ink-muted', symbol: '=', label: '' };
  }

  return (
    <div className="animate-fade">
      <PageHeader
        eyebrow="Аналитика"
        title="Сравнительный анализ"
        description="Сравните два материала, режима или технологии по всем свойствам, замеренным в экспериментах."
      />
      <div className="mx-auto max-w-7xl space-y-6 px-6 py-6">
        <div className="card">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
            <Option label="Вариант A" kind={aKind} setKind={setAKind} code={aCode} setCode={setACode} options={aOptions} accent="blue" />
            <div className="flex items-center justify-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-navy text-white">
                <ArrowLeftRight size={18} />
              </div>
            </div>
            <Option label="Вариант B" kind={bKind} setKind={setBKind} code={bCode} setCode={setBCode} options={bOptions} accent="red" />
          </div>
          <div className="mt-4 flex items-center justify-end gap-2">
            <button className="btn-primary" onClick={run} disabled={loading}>
              {loading ? <Loader2 className="animate-spin" size={16} /> : <Scale size={16} />}
              Сравнить
            </button>
          </div>
          {err && (
            <div className="mt-3 rounded-md border border-brand-red/40 bg-brand-red/5 p-3 text-sm text-brand-red">{err}</div>
          )}
        </div>

        {data && (
          <div className="card overflow-x-auto p-0">
            <div className="p-5 pb-2">
              <div className="text-xs uppercase tracking-wider text-brand-red">Свойства</div>
              <div className="text-lg font-semibold">Значения из экспериментов</div>
              <div className="text-xs text-ink-muted">
                Найдено: A — {data.experiments_a?.length || 0} эксп., B — {data.experiments_b?.length || 0}
              </div>
            </div>
            <table className="min-w-max text-sm">
              <thead>
                <tr className="border-y border-surface-divider bg-surface text-xs uppercase text-ink-muted">
                  <th className="p-3 text-left font-medium">Свойство</th>
                  <th className="p-3 text-left font-medium text-brand-blue">A · среднее</th>
                  <th className="p-3 text-left font-medium">A · разброс</th>
                  <th className="p-3 text-left font-medium text-brand-red">B · среднее</th>
                  <th className="p-3 text-left font-medium">B · разброс</th>
                  <th className="p-3 text-left font-medium">Δ</th>
                </tr>
              </thead>
              <tbody>
                {(data.properties || []).filter(p => p.property !== '_ids').map((p) => {
                  const t = trend(p.delta);
                  return (
                    <tr key={p.property} className="border-b border-surface-divider">
                      <td className="p-3 font-medium">{p.property}</td>
                      <td className="p-3">
                        {p.a?.mean ?? '—'} <span className="text-xs text-ink-muted">{p.a?.unit}</span>
                        <div className="text-[10px] text-ink-soft">n={p.a?.count || 0}</div>
                      </td>
                      <td className="p-3 text-xs text-ink-muted">
                        {p.a?.min ?? '—'} … {p.a?.max ?? '—'}
                        {p.a?.std !== null && p.a?.std !== undefined && <div>σ={p.a.std}</div>}
                      </td>
                      <td className="p-3">
                        {p.b?.mean ?? '—'} <span className="text-xs text-ink-muted">{p.b?.unit}</span>
                        <div className="text-[10px] text-ink-soft">n={p.b?.count || 0}</div>
                      </td>
                      <td className="p-3 text-xs text-ink-muted">
                        {p.b?.min ?? '—'} … {p.b?.max ?? '—'}
                        {p.b?.std !== null && p.b?.std !== undefined && <div>σ={p.b.std}</div>}
                      </td>
                      <td className="p-3">
                        {t ? (
                          <span className={`flex items-center gap-1 font-semibold ${t.color}`}>
                            {t.symbol} {t.label}{Math.abs(p.delta).toFixed(2)}
                          </span>
                        ) : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Option({ label, kind, setKind, code, setCode, options, accent }) {
  return (
    <div>
      <div className={`mb-2 text-xs uppercase tracking-wider ${accent === 'blue' ? 'text-brand-blue' : 'text-brand-red'}`}>{label}</div>
      <div className="flex gap-2">
        <select className="input max-w-36" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="material">Материал</option>
          <option value="mode">Режим</option>
          <option value="property">Свойство</option>
          <option value="equipment">Оборудование</option>
        </select>
        <select className="input flex-1 text-sm" value={code} onChange={(e) => setCode(e.target.value)}>
          {options.length === 0 ? (
            <option value="">— нет данных —</option>
          ) : options.map((o) => (
            <option key={o.code} value={o.code}>{o.title}</option>
          ))}
        </select>
      </div>
    </div>
  );
}
