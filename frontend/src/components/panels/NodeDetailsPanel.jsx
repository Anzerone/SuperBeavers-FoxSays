'use client';

import {
  ExternalLink, X, ShieldCheck, CalendarClock, MapPin, FileText,
  CheckCircle2, AlertTriangle,
} from 'lucide-react';

const TYPE_LABELS = {
  experiment: 'Эксперимент', conclusion: 'Вывод', document: 'Документ',
  material: 'Материал', property: 'Свойство', mode: 'Режим',
  equipment: 'Оборудование', author: 'Автор', team: 'Команда', tag: 'Тег',
  mode_param: 'Параметр режима',
};

const DOC_TYPE_LABELS = {
  report: 'Доклад', journal: 'Журнал', article: 'Статья', review: 'Обзор',
  conference: 'Материалы конференций', patent: 'Патент', thesis: 'Диссертация',
  document: 'Документ',
};

function fmtDate(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
  return d.toLocaleDateString('ru-RU', { year: 'numeric', month: 'long', day: 'numeric' });
}

function confInfo(c) {
  if (c == null) return null;
  const pct = Math.round(c * 100);
  if (c >= 0.75) return { pct, label: 'высокая', color: '#16a34a' };
  if (c >= 0.5) return { pct, label: 'средняя', color: '#d97706' };
  return { pct, label: 'низкая', color: '#dc2626' };
}

function geoInfo(region) {
  if (region === 'domestic') return { label: 'Отечественная (РФ/СНГ)', color: '#1D57A6' };
  if (region === 'foreign') return { label: 'Зарубежная практика', color: '#7c3aed' };
  if (region === 'other') return { label: 'География не определена', color: '#6b7280' };
  return null;
}

function Row({ k, v }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="shrink-0 text-text-muted">{k}</dt>
      <dd className="text-right">{v}</dd>
    </div>
  );
}

export default function NodeDetailsPanel({ node, onClose }) {
  if (!node) return null;

  const typeLabel = TYPE_LABELS[node.type] || node.label || node.type;
  const conf = confInfo(node.confidence);
  const geo = geoInfo(node.geo_region);
  const updated = fmtDate(node.last_updated || node.last_fetched || node.date);
  const hasVerification =
    node.confidence != null || updated || geo || node.doc_type ||
    node.source_doc_id || node.confirmation_count != null;

  return (
    <aside className="flex h-full w-80 flex-col border-l border-text-muted/10 bg-bg-surface">
      <header className="flex items-start justify-between gap-2 border-b border-text-muted/10 p-4">
        <span className="rounded bg-text-muted/15 px-2 py-0.5 text-xs font-medium text-text">
          {typeLabel}{node.extracted ? ' · извлечён из текста' : ''}
        </span>
        <button onClick={onClose} className="text-text-muted hover:text-text" aria-label="Закрыть">
          <X size={18} />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto p-4">
        <h2 className="mb-3 text-lg font-semibold leading-snug">{node.title}</h2>

        {node.description && (
          <section className="mb-4 rounded-lg border border-text-muted/15 bg-text-muted/5 p-3">
            <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
              Описание
            </div>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-text">
              {node.description}
            </p>
          </section>
        )}

        <dl className="space-y-2 text-sm">
          {node.year && <Row k="Год" v={node.year} />}
          {node.journal && <Row k="Издание" v={node.journal} />}
          {node.doc_type && <Row k="Тип источника" v={DOC_TYPE_LABELS[node.doc_type] || node.doc_type} />}
          {node.family && <Row k="Семейство" v={node.family} />}
          {node.base_element && <Row k="Базовый элемент" v={node.base_element} />}
          {node.gost && <Row k="ГОСТ" v={node.gost} />}
          {node.category && <Row k="Категория" v={node.category} />}
          {node.unit && <Row k="Ед. изм." v={node.unit} />}
          {node.temperature_c != null && <Row k="Температура" v={`${node.temperature_c} °C`} />}
          {node.duration_h != null && <Row k="Длительность" v={`${node.duration_h} ч`} />}
          {node.country_code && <Row k="Страна" v={node.country_code} />}
          {node.page_count != null && <Row k="Страниц" v={node.page_count} />}
        </dl>

        {hasVerification && (
          <section className="mt-4 rounded-lg border border-text-muted/15 p-3">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
              <ShieldCheck size={13} /> Верификация факта
            </div>

            {conf && (
              <div className="mb-3">
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="text-text-muted">Достоверность</span>
                  <span className="font-medium" style={{ color: conf.color }}>
                    {conf.label} · {conf.pct}%
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-text-muted/15">
                  <div className="h-full rounded-full" style={{ width: `${conf.pct}%`, background: conf.color }} />
                </div>
              </div>
            )}

            {updated && (
              <div className="mb-2 flex items-center gap-1.5 text-xs">
                <CalendarClock size={13} className="text-text-muted" />
                <span className="text-text-muted">Актуально на</span>
                <span className="ml-auto font-medium">{updated}</span>
              </div>
            )}

            {geo && (
              <div className="mb-2 flex items-center gap-1.5 text-xs">
                <MapPin size={13} style={{ color: geo.color }} />
                <span className="rounded px-1.5 py-0.5 font-medium"
                      style={{ color: geo.color, background: `${geo.color}1a` }}>
                  {geo.label}
                </span>
              </div>
            )}

            {(node.confirmation_count != null || node.contradicts_count > 0) && (
              <div className="flex flex-wrap items-center gap-3 text-xs">
                {node.confirmation_count != null && (
                  <span className="inline-flex items-center gap-1" style={{ color: '#16a34a' }}>
                    <CheckCircle2 size={13} /> подтверждений: {node.confirmation_count}
                  </span>
                )}
                {node.contradicts_count > 0 && (
                  <span className="inline-flex items-center gap-1" style={{ color: '#dc2626' }}>
                    <AlertTriangle size={13} /> разногласий: {node.contradicts_count}
                  </span>
                )}
              </div>
            )}
          </section>
        )}

        {(node.text || node.summary) && (
          <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-text-muted">
            {(node.text || node.summary).slice(0, 600)}
          </p>
        )}

        {node.is_anchor && (
          <div className="mt-4 rounded border border-accent/30 bg-accent/10 p-2 text-xs text-accent">
            Якорь — стартовая сущность подграфа.
          </div>
        )}
      </div>

      {(node.source_doc_id || node.doc_id || node.file_path) && (
        <footer className="border-t border-text-muted/10 p-4 space-y-2">
          <div className="mb-1 flex items-center gap-1.5 text-xs text-text-muted">
            <FileText size={13} /> Источник
          </div>
          {(node.source_doc_id || (node.type === 'document' && node.id)) && (
            <a href={`/explorer/document/${encodeURIComponent(node.source_doc_id || node.id)}`}
               className="btn-secondary w-full justify-center">
              <ExternalLink size={14} /> Открыть в эксплорере
            </a>
          )}
          {(node.source_doc_id || (node.type === 'document' && node.id)) && (
            <a href={`/api/v1/explorer/document/${encodeURIComponent(node.source_doc_id || node.id)}/file`}
               target="_blank" rel="noreferrer"
               className="btn-primary w-full justify-center">
              <ExternalLink size={14} /> Открыть файл документа
            </a>
          )}
        </footer>
      )}
    </aside>
  );
}
