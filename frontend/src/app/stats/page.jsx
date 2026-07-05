'use client';

import { Loader2, Database, GitBranch, FileText, Flag, Globe, Layers, TrendingUp, HelpCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import PageHeader from '@/components/shell/PageHeader';

const NODE_LABELS_RU = {
  Material: 'Материалы', Property: 'Свойства', Mode: 'Режимы',
  Equipment: 'Оборудование', Experiment: 'Эксперименты',
  Conclusion: 'Выводы', Document: 'Документы', Author: 'Авторы',
  Team: 'Лаборатории', Tag: 'Теги', ModeParam: 'Параметры режимов',
};

// «Что это и зачем» — короткое описание типа узла с указанием ключевых
// рёбер. Показывается на дашборде статистики как tooltip над баром и
// подсказка на карточках. Тексты синхронизированы с /explorer/page.jsx.
const NODE_HINTS_RU = {
  Material: 'Сырьё, полупродукты и реагенты: концентраты (Cu / Ni / CuNi / PGM), штейны, шлаки, руды, электролиты, кислоты. Связаны с экспериментами через USED_MATERIAL.',
  Mode: 'Технологические процессы и их параметры: флотация, автоклавное выщелачивание, конвертирование, электролиз, обжиг. Связаны через USED_MODE; численные параметры — в ModeParam / HAS_PARAM.',
  Property: 'Что измеряли: извлечение металла (%), содержание в концентрате, выход по току, прочность, температура и т.п. Связаны через MEASURED со значением и единицей.',
  Experiment: 'Единичный опыт или наблюдение из документа. Узел-«ядро» графа: соединяет Material × Mode × Property, ссылается на источник через DOCUMENTED_IN.',
  Author: 'Исследователи и коллективы. Автор связан с экспериментом через CONDUCTED_BY, с коллективом — MEMBER_OF, с документом — как метаданные Document.authors.',
  Document: 'Первоисточники: доклады, статьи, обзоры, материалы конференций, журнальные выпуски. Метаданные doc_type / journal / year / geo_region тянутся из пути файла при загрузке.',
};

const EDGE_LABELS_RU = {
  USED_MATERIAL: 'использует материал', USED_MODE: 'применяет режим',
  USED_EQUIPMENT: 'на оборудовании', MEASURED: 'замер свойства',
  HAS_PARAM: 'параметр режима', RESULTED_IN: 'вывод',
  CONDUCTED_BY: 'провёл', MEMBER_OF: 'член команды',
  DOCUMENTED_IN: 'описано в', MENTIONS: 'упоминает',
  CITES: 'цитирует', SIMILAR_TO: 'тематически близка',
  TAGGED_WITH: 'тег', CONFIRMS: 'подтверждает',
  CONTRADICTS: 'противоречит', SUPERSEDED_BY: 'заменён на',
};

const DOC_TYPES_RU = {
  report: 'Доклады', journal: 'Журналы', article: 'Статьи',
  review: 'Обзоры', conference: 'Материалы конференций',
  document: 'Прочее', '—': 'Не классифицировано',
};

const GEO_LABELS = {
  domestic: { label: 'РФ / СНГ', color: '#E30613', icon: <Flag size={14} /> },
  foreign:  { label: 'Зарубежные', color: '#1D57A6', icon: <Globe size={14} /> },
  other:    { label: 'Не определено', color: '#94a3b8', icon: null },
};

export default function StatsPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const load = () => {
    setLoading(true); setErr(null);
    api.adminStats()
      .then((d) => { setData(d); setLoading(false); })
      .catch((e) => { setErr(e.message); setLoading(false); });
  };

  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);

  if (err) return (
    <main className="mx-auto max-w-3xl p-10">
      <div className="card border-brand-red/30 bg-brand-red/5 text-brand-red">Ошибка: {err}</div>
    </main>
  );

  if (!data) return (
    <main className="flex min-h-screen items-center justify-center text-ink-muted">
      <Loader2 className="animate-spin mr-2" /> Загружаем статистику…
    </main>
  );

  const totalNodes = Object.values(data.nodes || {}).reduce((s, n) => s + n, 0);
  const totalEdges = Object.values(data.edges || {}).reduce((s, n) => s + n, 0);
  const totalDocs = Object.values(data.documents_by_type || {}).reduce((s, n) => s + n, 0);
  const totalGeo = Object.values(data.geo || {}).reduce((s, n) => s + n, 0);

  const maxNode = Math.max(1, ...Object.values(data.nodes || {}));
  const maxEdge = Math.max(1, ...Object.values(data.edges || {}));
  const maxDoc = Math.max(1, ...Object.values(data.documents_by_type || {}));

  return (
    <div className="animate-fade">
      <PageHeader
        eyebrow="Дашборд"
        title="Покрытие знаний"
        description="Сколько сущностей и связей в графе, какие типы документов и распределение по географии. Обновляется каждые 15 секунд."
      />
      <div className="mx-auto max-w-7xl space-y-6 px-6 py-6">
        {/* Верхние метрики */}
        <div className="grid gap-4 md:grid-cols-4">
          <BigStat icon={<Database size={18} className="text-brand-blue" />}
                   label="Узлов в графе" value={totalNodes.toLocaleString('ru-RU')} />
          <BigStat icon={<GitBranch size={18} className="text-brand-red" />}
                   label="Связей" value={totalEdges.toLocaleString('ru-RU')} />
          <BigStat icon={<FileText size={18} className="text-brand-navy" />}
                   label="Документов" value={totalDocs.toLocaleString('ru-RU')} />
          <BigStat icon={<Layers size={18} className="text-purple-700" />}
                   label="Чанков в Qdrant" value={data.totals?.chunks?.toLocaleString('ru-RU') || '—'} />
        </div>

        {/* Узлы по типам */}
        <div className="grid gap-6 md:grid-cols-2">
          <section className="card">
            <div className="mb-3">
              <div className="text-xs uppercase tracking-wider text-brand-red">Онтология</div>
              <div className="text-lg font-semibold">Узлы по типам</div>
              <div className="text-xs text-ink-muted">Наведи на строку — что это за узел и какими рёбрами связан.</div>
            </div>
            <div className="space-y-2">
              {Object.entries(data.nodes || {}).sort(([, a], [, b]) => b - a).map(([label, cnt]) => (
                <BarRow key={label} label={NODE_LABELS_RU[label] || label}
                        hint={NODE_HINTS_RU[label]}
                        count={cnt} max={maxNode} color="#1D57A6" />
              ))}
            </div>
          </section>

          <section className="card">
            <div className="mb-3">
              <div className="text-xs uppercase tracking-wider text-brand-red">Связи</div>
              <div className="text-lg font-semibold">Рёбра по типам</div>
            </div>
            <div className="max-h-96 space-y-2 overflow-y-auto pr-2">
              {Object.entries(data.edges || {}).sort(([, a], [, b]) => b - a).map(([type, cnt]) => (
                <BarRow key={type} label={EDGE_LABELS_RU[type] || type}
                        count={cnt} max={maxEdge} color="#E30613" />
              ))}
            </div>
          </section>
        </div>

        {/* Документы + гео */}
        <div className="grid gap-6 md:grid-cols-2">
          <section className="card">
            <div className="mb-3">
              <div className="text-xs uppercase tracking-wider text-brand-red">Корпус</div>
              <div className="text-lg font-semibold">Документы по типам</div>
              <div className="text-xs text-ink-muted">Категоризация по пути (Доклады / Журналы / …)</div>
            </div>
            <div className="space-y-2">
              {Object.entries(data.documents_by_type || {}).sort(([, a], [, b]) => b - a).map(([t, cnt]) => (
                <BarRow key={t} label={DOC_TYPES_RU[t] || t} count={cnt} max={maxDoc} color="#7B1FA2" />
              ))}
            </div>
          </section>

          <section className="card">
            <div className="mb-3">
              <div className="text-xs uppercase tracking-wider text-brand-red">География</div>
              <div className="text-lg font-semibold">Отечественная vs зарубежная практика</div>
              <div className="text-xs text-ink-muted">По языку, аффилиации и хинтам из текста</div>
            </div>
            {totalGeo === 0 ? (
              <div className="rounded-md bg-surface p-4 text-xs text-ink-muted">Документы ещё не загружены.</div>
            ) : (
              <>
                <div className="mb-4 flex h-8 overflow-hidden rounded-md bg-surface">
                  {Object.entries(data.geo || {}).map(([g, cnt]) => {
                    const pct = (cnt / totalGeo) * 100;
                    const conf = GEO_LABELS[g] || { label: g, color: '#94a3b8' };
                    return (
                      <div key={g}
                           title={`${conf.label}: ${cnt} (${pct.toFixed(1)}%)`}
                           style={{ width: `${pct}%`, background: conf.color }}
                           className="flex items-center justify-center text-[10px] font-semibold text-white">
                        {pct >= 8 && `${pct.toFixed(0)}%`}
                      </div>
                    );
                  })}
                </div>
                <div className="space-y-2">
                  {Object.entries(data.geo || {}).sort(([, a], [, b]) => b - a).map(([g, cnt]) => {
                    const conf = GEO_LABELS[g] || { label: g, color: '#94a3b8', icon: null };
                    return (
                      <div key={g} className="flex items-center justify-between rounded-md border border-surface-divider bg-surface p-3 text-sm">
                        <div className="flex items-center gap-2">
                          <span style={{ color: conf.color }}>{conf.icon}</span>
                          <span className="font-medium">{conf.label}</span>
                        </div>
                        <div>
                          <span className="font-bold">{cnt.toLocaleString('ru-RU')}</span>
                          <span className="ml-2 text-xs text-ink-muted">
                            {((cnt / totalGeo) * 100).toFixed(1)}%
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </section>
        </div>

        {/* Извлечение структуры */}
        {data.totals?.experiments !== undefined && (
          <section className="card">
            <div className="mb-3 flex items-center gap-2">
              <TrendingUp size={16} className="text-brand-red" />
              <div>
                <div className="text-xs uppercase tracking-wider text-brand-red">Auto-enrichment</div>
                <div className="text-lg font-semibold">Извлечение экспериментов из документов</div>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-md bg-surface p-4">
                <div className="text-xs uppercase text-ink-muted">Всего Experiment</div>
                <div className="mt-1 text-2xl font-bold">{data.totals.experiments}</div>
              </div>
              <div className="rounded-md bg-surface p-4">
                <div className="text-xs uppercase text-ink-muted">Извлечено из документов</div>
                <div className="mt-1 text-2xl font-bold">{data.totals.experiments_extracted || 0}</div>
              </div>
              <div className="rounded-md bg-surface p-4">
                <div className="text-xs uppercase text-ink-muted">Покрытие</div>
                <div className="mt-1 text-2xl font-bold">
                  {data.totals.experiments > 0
                    ? ((data.totals.experiments_extracted / data.totals.experiments) * 100).toFixed(0) + '%'
                    : '—'}
                </div>
              </div>
            </div>
          </section>
        )}

        {data.error && (
          <div className="card border-brand-red/30 bg-brand-red/5 text-sm text-brand-red">
            Neo4j вернул ошибку: {data.error}
          </div>
        )}
      </div>
    </div>
  );
}

function BigStat({ icon, label, value }) {
  return (
    <div className="card">
      <div className="mb-2 flex items-center gap-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-md bg-surface">{icon}</div>
        <div className="text-xs uppercase tracking-wider text-ink-muted">{label}</div>
      </div>
      <div className="text-3xl font-bold tracking-tight">{value}</div>
    </div>
  );
}

function BarRow({ label, count, max, color, hint }) {
  const pct = (count / max) * 100;
  return (
    <div className="group" title={hint || undefined}>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="flex items-center gap-1 text-ink">
          {label}
          {hint && (
            <HelpCircle
              size={12}
              className="text-ink-soft/70 transition-colors group-hover:text-brand-navy"
              aria-label={hint}
            />
          )}
        </span>
        <span className="font-mono text-xs font-semibold text-ink">{count.toLocaleString('ru-RU')}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface">
        <div className="h-full rounded-full transition-all"
             style={{ width: `${pct}%`, background: color }} />
      </div>
      {hint && (
        <div className="mt-1 hidden text-[11px] leading-snug text-ink-muted group-hover:block">
          {hint}
        </div>
      )}
    </div>
  );
}
