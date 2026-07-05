'use client';

import { Loader2, GitBranch, Layers, Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import PageHeader from '@/components/shell/PageHeader';

export default function GapsPage() {
  const [tab, setTab] = useState('data');
  const [data, setData] = useState(null);
  const [struct, setStruct] = useState(null);
  const [loading, setLoading] = useState(false);
  const [hypo, setHypo] = useState({ cell: null, text: '' });
  const [topN, setTopN] = useState(30);

  useEffect(() => {
    setLoading(true);
    if (tab === 'data') {
      api.gapsData(null, topN).then((r) => { setData(r); setLoading(false); }).catch(() => setLoading(false));
    } else {
      api.gapsStructural().then((r) => { setStruct(r); setLoading(false); }).catch(() => setLoading(false));
    }
  }, [tab, topN]);

  function maxCount() {
    if (!data?.counts) return 1;
    let m = 1;
    for (const row of data.counts) for (const v of row) if (v > m) m = v;
    return m;
  }
  function cellColor(v) {
    if (!v) return '#FAFCFE';
    const alpha = Math.min(0.9, 0.18 + (v / maxCount()) * 0.7);
    return `rgba(29,87,166,${alpha})`;
  }

  async function askHypothesis(rowCode, colIdx, colLabel) {
    setHypo({ cell: `${rowCode}|${colIdx}`, text: 'Формулируем гипотезу…' });
    try {
      const url = '/api/v1/gaps/hypothesis';
      const res = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ material: rowCode, process: colLabel, property: data.property_code || 'unknown' }),
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buf = '', out = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop();
        for (const p of parts) {
          const line = p.replace(/^data:\s?/, '');
          if (line === '[DONE]') { setHypo({ cell: `${rowCode}|${colIdx}`, text: out }); return; }
          out += line.replace(/\\n/g, '\n');
          setHypo({ cell: `${rowCode}|${colIdx}`, text: out });
        }
      }
    } catch (e) {
      setHypo({ cell: `${rowCode}|${colIdx}`, text: `Ошибка: ${e.message}` });
    }
  }

  return (
    <div className="animate-fade">
      <PageHeader
        eyebrow="Аналитика"
        title="Пробелы в данных"
        description="Что уже покрыто экспериментами, а какие комбинации материал × режим × свойство остаются неизученными. Кликните на белую ячейку — LLM сформулирует гипотезу «почему»."
      />
      <div className="mx-auto max-w-7xl px-6 py-6">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="inline-flex rounded-lg border border-surface-divider bg-white p-1 shadow-sm">
            <TabBtn active={tab === 'data'} onClick={() => setTab('data')} icon={<Layers size={14} />}>По данным (count)</TabBtn>
            <TabBtn active={tab === 'structural'} onClick={() => setTab('structural')} icon={<GitBranch size={14} />}>По структуре (link prediction)</TabBtn>
          </div>
          {tab === 'data' && (
            <label className="flex items-center gap-2 text-xs text-ink-muted">
              Материалов в матрице:
              <select className="input" value={topN} onChange={(e) => setTopN(Number(e.target.value))}>
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={30}>30</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </label>
          )}
        </div>

        {loading && (
          <div className="card flex items-center gap-2 text-ink-muted">
            <Loader2 className="animate-spin" size={16} /> Загружаем…
          </div>
        )}

        {tab === 'data' && data && (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="card overflow-x-auto p-0">
              <div className="p-5 pb-3">
                <div className="text-xs uppercase tracking-wider text-brand-red">Матрица покрытия</div>
                <div className="text-lg font-semibold">Материалы × процессы</div>
                <div className="mt-1 text-xs text-ink-muted">Насыщенность цвета — количество экспериментов с таким пересечением. Белое — пробел.</div>
              </div>
              <table className="min-w-max text-xs">
                <thead>
                  <tr className="border-b border-surface-divider bg-surface">
                    <th className="sticky left-0 z-10 border-r border-surface-divider bg-surface p-3 text-left font-medium text-ink-muted">Материал / Процесс</th>
                    {data.cols.map((c, i) => (
                      <th key={i} className="p-2 text-center font-normal text-ink-muted">{c.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r, ri) => (
                    <tr key={r.code} className="border-b border-surface-divider">
                      <td className="sticky left-0 z-10 border-r border-surface-divider bg-white p-3 font-medium">
                        <div>{r.name}</div>
                        <div className="text-[10px] font-mono text-ink-soft">{r.code}</div>
                      </td>
                      {data.counts[ri].map((v, ci) => {
                        const selected = hypo.cell === `${r.code}|${ci}`;
                        return (
                          <td key={ci}
                              onClick={() => v === 0 && askHypothesis(r.code, ci, data.cols[ci].label)}
                              title={v === 0 ? 'Клик — гипотеза LLM' : `${v} эксперимент(ов)`}
                              className={`relative h-12 min-w-20 border-r border-surface-divider p-1 text-center transition-all ${v === 0 ? 'cursor-pointer hover:ring-2 hover:ring-brand-red/60' : ''} ${selected ? 'ring-2 ring-brand-red' : ''}`}
                              style={{ background: cellColor(v) }}>
                            <span className={v > 0 ? 'font-semibold text-white' : 'text-ink-soft'}>{v || '·'}</span>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <aside className="card">
              <div className="mb-3 flex items-center gap-2">
                <div className="flex h-9 w-9 items-center justify-center rounded-md bg-brand-red/10">
                  <Sparkles size={16} className="text-brand-red" />
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wider text-brand-red">Гипотеза LLM</div>
                  <div className="text-xs text-ink-soft">Появится при клике на белую ячейку</div>
                </div>
              </div>
              {hypo.text ? (
                <div className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{hypo.text}</div>
              ) : (
                <div className="rounded-md bg-surface p-4 text-xs text-ink-muted">
                  Кликните на пустую ячейку матрицы — модель предположит, почему эта комбинация
                  не исследовалась и стоит ли начать.
                </div>
              )}
            </aside>
          </div>
        )}

        {tab === 'structural' && struct?.pairs && (
          <div>
            <div className="mb-3 text-xs text-ink-muted">
              Пары экспериментов, которые «должны» быть связаны по топологии графа
              (Adamic-Adar score), но связи ещё нет. Возможные упущенные аналогии.
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {struct.pairs.map((p, i) => (
                <div key={i} className="card">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="chip">score {p.score.toFixed(3)}</span>
                    <span className="font-mono text-[11px] text-ink-soft">#{i + 1}</span>
                  </div>
                  <div className="text-sm">
                    <div className="font-medium">{p.a_title || p.a_id}</div>
                    <div className="my-1 flex items-center gap-2 text-xs text-ink-muted">
                      <span className="h-px flex-1 bg-surface-divider" />
                      возможно похоже на
                      <span className="h-px flex-1 bg-surface-divider" />
                    </div>
                    <div className="font-medium">{p.b_title || p.b_id}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function TabBtn({ active, onClick, icon, children }) {
  return (
    <button onClick={onClick}
      className={`inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition-colors ${active ? 'bg-brand-navy text-white' : 'text-ink-muted hover:bg-surface-hover'}`}>
      {icon}{children}
    </button>
  );
}
