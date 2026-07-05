'use client';

import { Loader2, ExternalLink } from 'lucide-react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import PageHeader from '@/components/shell/PageHeader';

const CytoscapeCanvas = dynamic(() => import('@/components/graph/CytoscapeCanvas'), { ssr: false });

const TYPE_LABEL = {
  material: 'Материал', property: 'Свойство', mode: 'Режим', equipment: 'Оборудование',
  experiment: 'Эксперимент', author: 'Автор', team: 'Команда', document: 'Документ',
  conclusion: 'Вывод', tag: 'Тег',
};

// В карточку выводим только «человеческие» поля. Идентификаторы (id/code/…_id/…_at)
// не показываем: пользователь ищет смысл, а не отладочные значения.
const FIELD_LABEL = {
  year: 'Год', date: 'Дата', journal: 'Издание', doc_type: 'Тип источника',
  category: 'Категория', unit: 'Ед. изм.', temperature_c: 'Температура, °C',
  duration_h: 'Длительность, ч', country_code: 'Страна', page_count: 'Страниц',
  confidence: 'Достоверность', geo_region: 'География', family: 'Семейство',
  base_element: 'Базовый элемент', gost: 'ГОСТ', kind: 'Тип', format: 'Формат',
  value: 'Значение', title: 'Название', full_name: 'ФИО', display_name: 'Название',
  lab_code: 'Лаборатория',
};

const HIDDEN_FIELDS = new Set([
  'type', 'title', 'short_title', 'is_anchor', 'text', 'label', 'summary', 'description',
  'file_path', 'aliases', 'extracted', 'source', 'provenance',
]);

function isTechKey(k) {
  return /^(id|code|.*_id|.*_at)$/.test(k);
}

function fmtValue(k, v) {
  if (k === 'confidence' && typeof v === 'number') return `${Math.round(v * 100)}%`;
  if (k === 'geo_region') {
    return v === 'domestic' ? 'РФ/СНГ' : v === 'foreign' ? 'зарубежная' : 'н/д';
  }
  if (k === 'doc_type') {
    return ({
      report: 'Доклад', journal: 'Журнал', article: 'Статья',
      review: 'Обзор', conference: 'Материалы конференций',
    })[v] || v;
  }
  return String(v).slice(0, 80);
}

function graphNodeKey(node) {
  const id = node?.code || node?.id;
  return node?.type && id ? `${node.type}:${id}` : null;
}

function mergeGraphs(current, incoming) {
  if (!current) return incoming;
  const nodeMap = new Map();
  for (const node of [...(current.nodes || []), ...(incoming.nodes || [])]) {
    const key = graphNodeKey(node) || `${node.type || 'node'}:${node.id}`;
    const prev = nodeMap.get(key);
    nodeMap.set(key, prev ? { ...prev, ...node, is_anchor: prev.is_anchor } : node);
  }

  const edgeMap = new Map();
  for (const edge of [...(current.edges || []), ...(incoming.edges || [])]) {
    const key = [
      edge.source, edge.target, edge.type,
      edge.value ?? '', edge.unit ?? '', edge.score ?? '',
    ].join('|');
    if (!edgeMap.has(key)) edgeMap.set(key, edge);
  }

  return {
    nodes: Array.from(nodeMap.values()),
    edges: Array.from(edgeMap.values()),
  };
}

export default function ExplorerPage() {
  const { type, code } = useParams();
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [related, setRelated] = useState(null);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [expandedIds, setExpandedIds] = useState(new Set());
  const [expandingNodeId, setExpandingNodeId] = useState(null);
  const [expandError, setExpandError] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setData(null); setErr(null); setSelected(null); setRelated(null);
    setExpandedIds(new Set()); setExpandingNodeId(null); setExpandError(null);
    api.explorer(type, code, 1)
      .then((graph) => {
        if (cancelled) return;
        setData(graph);
        const anchors = new Set(
          (graph.nodes || []).filter((n) => n.is_anchor).map(graphNodeKey).filter(Boolean)
        );
        setExpandedIds(anchors);
      })
      .catch((e) => {
        if (!cancelled) setErr(e.message);
      });
    return () => { cancelled = true; };
  }, [type, code]);

  const selectAndExpand = useCallback(async (node) => {
    setSelected(node);
    setRelated(null);
    setExpandError(null);
    if (!node) return;

    const key = graphNodeKey(node);
    const nodeCode = node.code || node.id;
    if (!key || !node.type || !nodeCode || expandedIds.has(key)) return;

    setExpandingNodeId(key);
    try {
      const graph = await api.explorer(node.type, nodeCode, 1);
      setData((current) => mergeGraphs(current, graph));
      setExpandedIds((prev) => {
        const next = new Set(prev);
        next.add(key);
        return next;
      });
    } catch (e) {
      setExpandError(e.message || 'Не удалось раскрыть соседей');
    } finally {
      setExpandingNodeId(null);
    }
  }, [expandedIds]);

  async function loadRelated(t, c) {
    setRelatedLoading(true);
    try {
      const r = await api.relatedOf(t, c, 30);
      setRelated(r.items || []);
    } catch (e) {
      setRelated([]);
    }
    setRelatedLoading(false);
  }

  if (err) return (
    <div className="mx-auto max-w-2xl p-10">
      <div className="card border-brand-red/30 bg-brand-red/5">
        <div className="mb-2 text-sm font-semibold text-brand-red">Ошибка</div>
        <div className="text-sm text-ink">{err}</div>
        <Link href="/" className="btn-secondary mt-4">На главную</Link>
      </div>
    </div>
  );

  return (
    <div className="animate-fade">
      <PageHeader
        eyebrow={`Эксплорер · ${TYPE_LABEL[type] || type}`}
        title={decodeURIComponent(code)}
        description={data ? `${data.nodes.length} узлов · ${data.edges.length} рёбер в текущем раскрытии` : 'Загружаем эго-сеть…'}
      />
      <div className="mx-auto grid max-w-7xl gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="overflow-hidden rounded-lg border border-surface-divider bg-surface-dark shadow-card">
          <div className="border-b border-white/10 px-4 py-2.5 text-xs uppercase tracking-wider text-ink-inverseMuted">
            Интерактивный граф
          </div>
          <div className="h-[calc(100vh-260px)] min-h-[500px]">
            {data ? (
              <CytoscapeCanvas nodes={data.nodes} edges={data.edges} onSelectNode={selectAndExpand} />
            ) : (
              <div className="flex h-full items-center justify-center text-ink-inverseMuted">
                <Loader2 className="mr-2 animate-spin" /> Загружаем…
              </div>
            )}
          </div>
        </div>

        <aside className="card">
          {selected ? (
            <div>
              <div className="mb-2 flex items-center gap-2">
                <span className="chip">{TYPE_LABEL[selected.type] || selected.type}</span>
                {selected.is_anchor && <span className="chip-accent">Якорь</span>}
              </div>
              <h2 className="mb-3 text-base font-semibold leading-snug">{selected.title}</h2>
              {selected.description && (
                <div className="mb-3 rounded-md border border-surface-divider bg-surface px-3 py-2 text-xs leading-relaxed text-ink">
                  <div className="mb-1 font-semibold uppercase tracking-wider text-ink-muted">Описание</div>
                  <p>{selected.description}</p>
                </div>
              )}
              <dl className="space-y-1.5 border-t border-surface-divider pt-3 text-xs">
                {Object.entries(selected)
                  .filter(([k, v]) => v !== null && v !== undefined && v !== '' &&
                    !HIDDEN_FIELDS.has(k) && !isTechKey(k))
                  .map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-3">
                      <dt className="font-medium text-ink-muted">{FIELD_LABEL[k] || k}</dt>
                      <dd className="text-right text-ink">{fmtValue(k, v)}</dd>
                    </div>
                  ))}
                {selected.text && (
                  <div className="border-t border-surface-divider pt-3 text-ink-muted">
                    {String(selected.text).slice(0, 400)}
                  </div>
                )}
              </dl>
              {selected.type === 'document' && (selected.code || selected.id) && (
                <a
                  href={`/api/v1/explorer/document/${encodeURIComponent(selected.code || selected.id)}/file`}
                  target="_blank" rel="noreferrer"
                  className="btn-primary mt-4 w-full justify-center">
                  <ExternalLink size={14} /> Открыть файл документа
                </a>
              )}
              {selected.source_doc_id && (
                <a
                  href={`/api/v1/explorer/document/${encodeURIComponent(selected.source_doc_id)}/file`}
                  target="_blank" rel="noreferrer"
                  className="btn-secondary mt-2 w-full justify-center">
                  <ExternalLink size={14} /> Открыть файл-источник
                </a>
              )}
              {expandingNodeId === graphNodeKey(selected) && (
                <div className="mt-3 flex items-center justify-center rounded-md bg-surface px-3 py-2 text-xs text-ink-muted">
                  <Loader2 size={14} className="mr-2 animate-spin" /> Раскрываем соседей…
                </div>
              )}
              {expandError && (
                <div className="mt-3 rounded-md border border-brand-red/20 bg-brand-red/5 px-3 py-2 text-xs text-brand-red">
                  {expandError}
                </div>
              )}
              <button
                onClick={() => loadRelated(selected.type, selected.code || selected.id)}
                className="btn-secondary mt-4 w-full justify-center">
                {relatedLoading ? 'Ищу связанные…' : 'Показать связанные'}
              </button>
              {related && related.length > 0 && (
                <div className="mt-3 max-h-64 overflow-y-auto border-t border-surface-divider pt-2 text-xs">
                  {related.map((r, i) => (
                    <Link key={i}
                          href={`/explorer/${r.type}/${encodeURIComponent(r.code)}`}
                          className="flex items-center justify-between gap-2 rounded py-1.5 hover:bg-surface">
                      <span className="truncate">
                        <span className="mr-1 rounded bg-surface px-1.5 py-0.5 text-[10px] uppercase text-ink-muted">
                          {TYPE_LABEL[r.type] || r.type}
                        </span>
                        {r.title}
                      </span>
                      <span className="shrink-0 text-[10px] text-ink-muted">{r.relation}</span>
                    </Link>
                  ))}
                </div>
              )}
              {related && related.length === 0 && (
                <div className="mt-3 text-center text-xs text-ink-muted">Нет связанных сущностей</div>
              )}
            </div>
          ) : (
            <div className="text-center">
              <div className="mb-2 text-xs uppercase tracking-wider text-ink-muted">Подсказка</div>
              <div className="text-sm text-ink">Кликните на любой узел графа, чтобы увидеть подробности сущности.</div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
