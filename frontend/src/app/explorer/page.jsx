'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { HelpCircle, Loader2, Search } from 'lucide-react';
import { api } from '@/lib/api';
import PageHeader from '@/components/shell/PageHeader';

// Тип узла → человекочитаемое описание. Показываем как подсказку под
// выбранной вкладкой и в tooltip на самих кнопках, чтобы пользователь
// сразу понимал, что именно он листает.
const TABS = [
  {
    type: 'material',
    label: 'Материалы',
    hint: 'Сырьё, полупродукты и реагенты: концентраты (Cu / Ni / CuNi / PGM), штейны, шлаки, руды, электролиты, кислоты. Связаны с экспериментами через USED_MATERIAL.',
  },
  {
    type: 'mode',
    label: 'Режимы',
    hint: 'Технологические процессы и их параметры: флотация, автоклавное выщелачивание, конвертирование, электролиз, обжиг. Связаны через USED_MODE; численные параметры — в ModeParam / HAS_PARAM.',
  },
  {
    type: 'property',
    label: 'Свойства',
    hint: 'Что измеряли: извлечение металла (%), содержание в концентрате, выход по току, прочность, температура и т.п. Связаны через MEASURED со значением и единицей.',
  },
  {
    type: 'experiment',
    label: 'Эксперименты',
    hint: 'Единичный опыт или наблюдение из документа. Узел-«ядро» графа: соединяет Material × Mode × Property, ссылается на источник через DOCUMENTED_IN.',
  },
  {
    type: 'author',
    label: 'Авторы',
    hint: 'Исследователи и коллективы. Автор связан с экспериментом через CONDUCTED_BY, с коллективом — MEMBER_OF, с документом — как метаданные Document.authors.',
  },
  {
    type: 'document',
    label: 'Документы',
    hint: 'Первоисточники: доклады, статьи, обзоры, материалы конференций, журнальные выпуски. Метаданные doc_type / journal / year / geo_region тянутся из пути файла при загрузке.',
  },
];

export default function ExplorerIndex() {
  const [type, setType] = useState('material');
  const [items, setItems] = useState(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    setItems(null);
    api.listEntities(type, 500).then((r) => setItems(r.items || [])).catch(() => setItems([]));
  }, [type]);

  const filtered = (items || []).filter((x) =>
    !query || x.title.toLowerCase().includes(query.toLowerCase()) ||
    (x.code || '').toLowerCase().includes(query.toLowerCase())
  );

  const activeTab = TABS.find((t) => t.type === type) || TABS[0];

  return (
    <div className="animate-fade">
      <PageHeader
        eyebrow="Аналитика"
        title="Эксплорер сущностей"
        description="Выберите сущность и увидьте её эго-сеть: связанные материалы, режимы, эксперименты, авторов, документы."
      />
      <div className="mx-auto max-w-5xl space-y-4 px-6 py-6">
        <div className="flex flex-wrap gap-2">
          {TABS.map((t) => (
            <button key={t.type} onClick={() => setType(t.type)}
              title={t.hint}
              className={`rounded-full px-3 py-1.5 text-sm ${type === t.type ? 'bg-brand-navy text-white' : 'bg-white border border-surface-divider'}`}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-start gap-2 rounded-lg border border-surface-divider bg-brand-navy/5 px-3 py-2.5 text-sm text-ink-muted">
          <HelpCircle size={16} className="mt-0.5 shrink-0 text-brand-navy" />
          <p>
            <span className="font-medium text-ink">{activeTab.label}.</span>{' '}
            {activeTab.hint}
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-surface-divider bg-white px-3 py-2">
          <Search size={16} className="text-ink-muted" />
          <input
            className="w-full border-0 bg-transparent text-sm outline-none"
            placeholder="Поиск по названию…"
            value={query} onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {items === null ? (
          <div className="flex items-center justify-center p-10 text-ink-muted"><Loader2 className="mr-2 animate-spin" /> Загружаем…</div>
        ) : filtered.length === 0 ? (
          <div className="rounded-lg border border-surface-divider bg-white p-8 text-center text-sm text-ink-muted">
            Ничего не нашли.
          </div>
        ) : (
          <ul className="divide-y divide-surface-divider rounded-lg border border-surface-divider bg-white">
            {filtered.slice(0, 200).map((x) => (
              <li key={x.code}>
                <Link href={`/explorer/${type}/${encodeURIComponent(x.code)}`}
                      className="block px-4 py-2.5 text-sm hover:bg-surface">
                  {x.title}
                </Link>
              </li>
            ))}
            {filtered.length > 200 && (
              <li className="px-4 py-2 text-xs text-ink-muted">Показаны первые 200 из {filtered.length}. Уточните запрос.</li>
            )}
          </ul>
        )}
      </div>
    </div>
  );
}
