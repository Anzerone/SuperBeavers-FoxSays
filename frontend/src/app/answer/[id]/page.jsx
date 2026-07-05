'use client';

import { Loader2, Sparkles, FileText, ArrowLeft, Download, FileJson, FileType, Flag, Globe, ShieldCheck, X } from 'lucide-react';
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
  const [selectedNode, setSelectedNode] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const abortRef = useRef(null);

  useEffect(() => {
    if (!question) return;
    setStatus('parsing');
    setErrorMsg(null);
    abortRef.current?.();
    abortRef.current = api.streamAsk({
      question, expand: true, geoFilter: geo, intentHint, answerId,
      onIntent: () => setStatus('matching'),
      onMatch: (m) => { setMatched(m.count); setRegions(m.regions); setStatus('rendering'); },
      onSubgraph: (s) => { setSubgraph(s); setStatus('synthesizing'); },
      onSources: setSources,
      onToken: (t) => setAnswer((prev) => prev + t),
      onDone: () => setStatus('done'),
      // Ошибку показываем отдельным баннером, а не подмешиваем в текст ответа —
      // раньше в ответ приезжало «[Ошибка: HTTP 500]», и это невозможно было
      // экспортировать в PDF.
      onError: (e) => { setErrorMsg(e.message || 'неизвестная ошибка'); setStatus('error'); },
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
              <div className="text-[11px] text-ink-soft">Локальная модель · Ollama qwen2.5:14b</div>
            </div>
          </div>
          <div className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink">
            {answer
              ? <AnswerText text={answer} sources={sources} />
              : (status === 'error' && !errorMsg
                ? <span className="text-ink-soft">Ответ не сформирован.</span>
                : <span className="text-ink-soft">Думаем…</span>)}
            {status === 'synthesizing' && (
              <span className="ml-0.5 inline-block h-4 w-[3px] animate-pulse bg-brand-red/70 align-middle" />
            )}
          </div>

          {errorMsg && (
            <div className="mt-3 rounded-md border border-brand-red/40 bg-brand-red/5 p-3 text-xs text-brand-red">
              Не удалось получить ответ: {errorMsg}. Попробуйте переформулировать
              вопрос или повторить запрос через минуту.
            </div>
          )}

          {sources.length > 0 && (
            <div className="mt-8 border-t border-surface-divider pt-5">
              <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wider text-ink-muted">
                <FileText size={12} /> Источники · {sources.length}
              </div>
              <ol className="space-y-2 text-xs">
                {sources.map((s, i) => (
                  <li key={i} id={`source-${i + 1}`}
                      className="scroll-mt-24 rounded-md border border-surface-divider bg-surface p-3 transition-colors target:border-brand-red target:bg-brand-red/5">
                    <div className="mb-1 flex items-center gap-2 flex-wrap">
                      {s.doc_id ? (
                        <a href={`/api/v1/explorer/document/${encodeURIComponent(s.doc_id)}/file`}
                           target="_blank" rel="noreferrer"
                           className="font-mono text-[11px] font-semibold text-brand-blue hover:underline">
                          [Doc#{i + 1}]
                        </a>
                      ) : (
                        <span className="font-mono text-[11px] font-semibold text-brand-blue">[Doc#{i + 1}]</span>
                      )}
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
          <div className="relative h-[calc(100vh-260px)] min-h-[400px]">
            <CytoscapeCanvas nodes={subgraph.nodes} edges={subgraph.edges} onSelectNode={setSelectedNode} />
            {selectedNode && <NodeDetails node={selectedNode} onClose={() => setSelectedNode(null)} />}
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

// Разбивает текст ответа на куски и превращает [Doc#N] в якорь на карточку
// источника ниже. Хэш `#source-N` подсвечивается через CSS `:target`.
// Клик на [Doc#N] с зажатым Ctrl/Cmd — открывает PDF/файл источника прямо
// (второй вариант навигации: через ссылку [Doc#N] в самом списке).
function AnswerText({ text, sources }) {
  if (!text) return null;
  const parts = String(text).split(/(\[Doc#\d+\])/g);
  return parts.map((part, i) => {
    const m = /^\[Doc#(\d+)\]$/.exec(part);
    if (!m) return <span key={i}>{part}</span>;
    const idx = parseInt(m[1], 10);
    const src = sources && sources[idx - 1];
    const title = src ? `${src.title || src.doc_id || ''}${src.page ? ` · стр. ${src.page}` : ''}` : `Источник ${idx}`;
    return (
      <a key={i} href={`#source-${idx}`}
         title={title}
         onClick={(e) => {
           if (!(e.ctrlKey || e.metaKey)) return;
           if (!src?.doc_id) return;
           e.preventDefault();
           window.open(`/api/v1/explorer/document/${encodeURIComponent(src.doc_id)}/file`, '_blank');
         }}
         className="mx-0.5 rounded bg-brand-blue/10 px-1 font-mono text-[12px] font-semibold text-brand-blue no-underline hover:bg-brand-blue/20">
        [Doc#{idx}]
      </a>
    );
  });
}

const NODE_TYPE_RU = {
  experiment: 'Эксперимент', material: 'Материал', property: 'Свойство', mode: 'Режим',
  equipment: 'Оборудование', author: 'Автор', team: 'Команда', document: 'Документ',
  conclusion: 'Вывод', tag: 'Тег',
};

const NODE_FIELD_RU = {
  title: 'Название', year: 'Год', date: 'Дата',
  unit: 'Единица', category: 'Категория', family: 'Семейство',
  base_element: 'Базовый элемент', gost: 'ГОСТ', description: 'Описание',
  temperature_c: 'Температура, °C', duration_h: 'Длительность, ч',
  summary: 'Реферат', text: 'Текст', confidence: 'Достоверность',
  journal: 'Журнал', doc_type: 'Тип документа',
  country_code: 'Страна', geo_region: 'Регион', page_count: 'Страниц',
  last_updated: 'Обновлено', last_fetched: 'Загружено',
  confirmation_count: 'Подтверждений', contradicts_count: 'Опровержений',
  full_name: 'ФИО', display_name: 'Название',
};

// Скрытые технические поля: id/code/*_id/*_at + служебные флаги. Не для пользователя.
const NODE_HIDDEN = new Set([
  'type', 'label', 'short_title', 'is_anchor', 'file_path',
  'aliases', 'extracted', 'source', 'provenance',
]);

function isTechFieldKey(k) {
  return /^(id|code|.*_id|.*_at)$/.test(k);
}

function NodeDetails({ node, onClose }) {
  // Description показываем отдельным блоком: одна строка «Описание: длинный
  // абзац» ломает layout dl. В entries ниже поле уже отфильтровано.
  const entries = Object.entries(node)
    .filter(([k, v]) => v !== null && v !== undefined && v !== '' &&
      !NODE_HIDDEN.has(k) && !isTechFieldKey(k) && k !== 'description');
  return (
    <div className="absolute right-3 top-3 z-10 w-[320px] max-h-[calc(100%-1.5rem)] overflow-y-auto rounded-lg border border-white/15 bg-brand-navy/95 p-4 text-sm text-white shadow-2xl backdrop-blur">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] uppercase tracking-wider">
            {NODE_TYPE_RU[node.type] || node.type}
          </span>
          {node.is_anchor && (
            <span className="rounded-full bg-brand-red/90 px-2 py-0.5 text-[10px] uppercase tracking-wider">Якорь</span>
          )}
        </div>
        <button onClick={onClose} className="rounded p-1 text-white/70 hover:bg-white/10 hover:text-white">
          <X size={14} />
        </button>
      </div>
      <div className="mb-3 text-[15px] font-semibold leading-snug">{node.title || '(без названия)'}</div>
      {node.description && (
        <div className="mb-3 rounded-md border border-white/10 bg-white/5 p-2.5 text-[12px] leading-relaxed text-white/90">
          {node.description}
        </div>
      )}
      <dl className="space-y-1 border-t border-white/10 pt-2 text-[11px]">
        {entries.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3">
            <dt className="text-white/50">{NODE_FIELD_RU[k] || k}</dt>
            <dd className="text-right text-white/90 break-all">
              {k === 'confidence' && typeof v === 'number'
                ? `${Math.round(v * 100)}%`
                : String(v).slice(0, 80)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
