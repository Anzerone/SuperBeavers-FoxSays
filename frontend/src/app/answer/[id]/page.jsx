'use client';

import { Loader2, Sparkles, FileText, ArrowLeft, Download, FileJson, FileType, Flag, Globe, ShieldCheck } from 'lucide-react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';

const CytoscapeCanvas = dynamic(() => import('@/components/graph/CytoscapeCanvas'), {
  ssr: false,
  loading: () => <div className="flex h-full items-center justify-center text-ink-inverseMuted"><Loader2 className="mr-2 animate-spin" /> Загружаем граф…</div>,
});

const STATUS_LABEL = {
  starting: 'Запуск', parsing: 'Разбираем вопрос', matching: 'Ищем эксперименты',
  rendering: 'Рисуем граф', synthesizing: 'Формулируем ответ', done: 'Готово', error: 'Ошибка',
};

const DOC_TYPE_RU = {
  report: 'Доклад', journal: 'Журнал', article: 'Статья', review: 'Обзор',
  conference: 'Конференция', patent: 'Патент', thesis: 'Диссертация', document: 'Документ',
};
const GEO_RU = {
  domestic: { t: 'РФ / СНГ', c: '#1D57A6' },
  foreign: { t: 'Зарубеж', c: '#7c3aed' },
  other: { t: 'геонеизв.', c: '#6b7280' },
};
function fmtRuDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso).slice(0, 10) : d.toLocaleDateString('ru-RU');
}

export default function AnswerPage() {
  const params = useSearchParams();
  const { id: answerId } = useParams();
  const question = params.get('q') || '';
  const geo = params.get('geo') || 'any';
  const intentHint = params.get('intent');

  const [subgraph, setSubgraph] = useState({ nodes: [], edges: [] });
  const [sources, setSources] = useState([]);
  const [answer, setAnswer] = useState('');
  const [status, setStatus] = useState('starting');
  const [matched, setMatched] = useState(0);
  const [regions, setRegions] = useState(null);
  const abortRef = useRef(null);

  useEffect(() => {
    if (!question) return;
    setStatus('parsing');
    abortRef.current?.();
    abortRef.current = api.streamAsk({
      question, expand: true, geoFilter: geo, intentHint, answerId,
      onIntent: () => setStatus('matching'),
      onMatch: (m) => { setMatched(m.count); setRegions(m.regions); setStatus('rendering'); },
      onSubgraph: (s) => { setSubgraph(s); setStatus('synthesizing'); },
      onSources: setSources,
      onToken: (t) => setAnswer((prev) => prev + t),
      onDone: () => setStatus('done'),
      onError: (e) => { setAnswer((p) => p + `\n\n[Ошибка: ${e.message}]`); setStatus('error'); },
    });
    return () => abortRef.current?.();
  }, [question, geo, intentHint, answerId]);

  async function download(format) {
    try {
      const url = api.exportUrl(format);
      const t = typeof window !== 'undefined' ? window.localStorage.getItem('st_token') : null;
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(t ? { Authorization: `Bearer ${t}` } : {}),
        },
        body: JSON.stringify({ answer_id: answerId }),
      });
      if (!res.ok) throw new Error(`Ошибка ${res.status}`);
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `answer_${answerId.slice(0,12)}.${format === 'jsonld' ? 'jsonld' : format}`;
      document.body.appendChild(a); a.click();
      URL.revokeObjectURL(a.href);
      a.remove();
    } catch (e) {
      alert(`Экспорт не удался: ${e.message}`);
    }
  }

  const streaming = ['starting','parsing','matching','rendering','synthesizing'].includes(status);
  const doneOrError = status === 'done' || status === 'error';

  return (
    <div className="animate-fade">
      <section className="border-b border-surface-divider bg-white">
        <div className="mx-auto max-w-7xl px-6 py-5">
          <div className="flex items-start gap-4">
            <Link href="/" className="btn-ghost mt-1"><ArrowLeft size={14} /> Назад</Link>
            <div className="flex-1">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                <span className={`chip ${status === 'done' ? 'chip-accent' : ''}`}>
                  {streaming && <Loader2 className="animate-spin" size={10} />}
                  {STATUS_LABEL[status] || status}
                </span>
                <span className="text-ink-muted">·</span>
                <span className="text-ink-muted">Эксперименты: <b className="text-ink">{matched}</b></span>
                {regions && (
                  <>
                    <span className="text-ink-soft">·</span>
                    {regions.domestic > 0 && (
                      <span className="chip"><Flag size={10} /> РФ: {regions.domestic}</span>
                    )}
                    {regions.foreign > 0 && (
                      <span className="chip"><Globe size={10} /> Зарубеж: {regions.foreign}</span>
                    )}
                  </>
                )}
                {intentHint && <span className="chip-accent">{intentHint === 'literature_review' ? 'Литобзор' : 'Сравнение'}</span>}
              </div>
              <div className="text-lg font-semibold leading-snug text-ink">{question}</div>
            </div>
            {doneOrError && answer && (
              <div className="flex gap-2">
                <button onClick={() => download('markdown')} className="btn-ghost" title="Экспорт в Markdown">
                  <FileType size={14} /> MD
                </button>
                <button onClick={() => download('jsonld')} className="btn-ghost" title="Экспорт JSON-LD">
                  <FileJson size={14} /> JSON-LD
                </button>
                <button onClick={() => download('pdf')} className="btn-primary">
                  <Download size={14} /> PDF
                </button>
              </div>
            )}
          </div>
        </div>
      </section>

      <div className="mx-auto grid max-w-7xl gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="card flex flex-col">
          <div className="mb-4 flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-brand-red/10">
              <Sparkles className="text-brand-red" size={18} />
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider text-brand-red">Ответ AI</div>
              <div className="text-[11px] text-ink-soft">YandexGPT · Yandex AI Studio (облако)</div>
            </div>
          </div>
          <div className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink">
            {answer || <span className="text-ink-soft">Думаем…</span>}
            {status === 'synthesizing' && (
              <span className="ml-0.5 inline-block h-4 w-[3px] animate-pulse bg-brand-red/70 align-middle" />
            )}
          </div>

          {sources.length > 0 && (
            <div className="mt-8 border-t border-surface-divider pt-5">
              <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wider text-ink-muted">
                <FileText size={12} /> Источники · {sources.length}
              </div>
              <ol className="space-y-2 text-xs">
                {sources.map((s, i) => (
                  <li key={i} className="rounded-md border border-surface-divider bg-surface p-3">
                    <div className="mb-1 flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-[11px] font-semibold text-brand-blue">[Doc#{i + 1}]</span>
                      <span className="text-ink-soft">{s.title || s.doc_id} · стр. {s.page}</span>
                      {s.doc_type && (
                        <span className="chip">
                          {DOC_TYPE_RU[s.doc_type] || s.doc_type}{s.year ? ` · ${s.year}` : ''}
                        </span>
                      )}
                      {s.geo_region && GEO_RU[s.geo_region] && (
                        <span className="chip"
                              style={{ color: GEO_RU[s.geo_region].c, background: `${GEO_RU[s.geo_region].c}1a` }}>
                          {GEO_RU[s.geo_region].t}
                        </span>
                      )}
                      {typeof s.score === 'number' && (
                        <span className="chip"><ShieldCheck size={10} /> релевантность {(s.score * 100).toFixed(0)}%</span>
                      )}
                    </div>
                    {s.last_fetched && (
                      <div className="mb-1 text-[10px] text-ink-muted">актуально на {fmtRuDate(s.last_fetched)}</div>
                    )}
                    <div className="text-ink-muted leading-relaxed">«{(s.text || '').slice(0, 260)}…»</div>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </section>

        <section className="overflow-hidden rounded-lg border border-surface-divider bg-surface-dark shadow-card">
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
            <div className="text-xs uppercase tracking-wider text-ink-inverseMuted">Подграф релевантных сущностей</div>
            <div className="flex items-center gap-3 text-[10px] text-ink-inverseMuted">
              <Dot color="#1D57A6" label="Эксп." />
              <Dot color="#E30613" label="Матер." />
              <Dot color="#2E7D32" label="Свойство" />
              <Dot color="#7B1FA2" label="Режим" />
            </div>
          </div>
          <div className="h-[calc(100vh-260px)] min-h-[400px]">
            <CytoscapeCanvas nodes={subgraph.nodes} edges={subgraph.edges} />
          </div>
        </section>
      </div>
    </div>
  );
}

function Dot({ color, label }) {
  return (
    <span className="flex items-center gap-1">
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}
