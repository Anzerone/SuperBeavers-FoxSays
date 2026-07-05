'use client';

import {
  Activity,
  CheckCircle2,
  Database,
  FileSearch,
  Layers3,
  Loader2,
  Play,
  RefreshCw,
  Square,
  Upload,
  Zap,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import PageHeader from '@/components/shell/PageHeader';

const STAGE_LABEL = {
  idle: 'Ожидание', loading: 'Загрузка…', done: 'Готово', error: 'Ошибка',
};
const TASK_LABEL = {
  idle: 'Ожидание', running: 'В работе', done: 'Готово',
  error: 'Ошибка', cancelled: 'Остановлено',
};
const EXTRACT_MODEL = 'qwen2.5:3b-instruct-q5_K_M';
const USEFUL_INFO_MODEL = 'qwen2.5:14b-instruct-q5_K_M';

export default function AdminPage() {
  const [status, setStatus] = useState(null);
  const [extractStatus, setExtractStatus] = useState(null);
  const [usefulInfoStatus, setUsefulInfoStatus] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [events, setEvents] = useState([]);
  const [graph, setGraph] = useState(null);
  const [quality, setQuality] = useState(null);
  const [taskBaselines, setTaskBaselines] = useState({ extract: null, usefulInfo: null });
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null); // { type: 'ok'|'err', text }
  const fileRef = useRef(null);

  const refresh = async () => {
    try {
      const [s, m, e, g, q, xs, us] = await Promise.all([
        api.adminStatus(),
        api.adminMetrics(),
        api.enrichmentEvents(30),
        api.adminStats().catch(() => null),
        api.dataQuality().catch(() => null),
        api.extractStatus().catch(() => null),
        api.usefulInfoEnrichStatus().catch(() => null),
      ]);
      setStatus(s); setMetrics(m); setEvents(e.events || []); setGraph(g); setQuality(q);
      setExtractStatus(xs); setUsefulInfoStatus(us);
      setTaskBaselines((prev) => ({
        extract: nextBaseline(prev.extract, xs, extractProgressFromQuality(q)),
        usefulInfo: nextBaseline(prev.usefulInfo, us, usefulInfoProgressFromQuality(q)),
      }));
    } catch {}
  };
  useEffect(() => { refresh(); const t = setInterval(refresh, 3000); return () => clearInterval(t); }, []);

  // Приоритет: последний ingest в этом процессе (status.stats), иначе — живой граф.
  const ingestStats = status?.stats || (graph ? {
    experiments: graph.nodes?.Experiment ?? graph.totals?.experiments ?? 0,
    documents: graph.nodes?.Document ?? 0,
    chunks: graph.totals?.chunks ?? 0,
  } : null);
  const ingestMain = status?.stage === 'idle' && ingestStats
    ? 'В базе'
    : STAGE_LABEL[status?.stage] || '—';

  const extractProgress = extractProgressFromQuality(quality);
  const usefulInfoProgress = usefulInfoProgressFromQuality(quality);
  const nowSec = Date.now() / 1000;

  const extractRunning = extractStatus?.stage === 'running';
  const enrichRunning = usefulInfoStatus?.stage === 'running';
  const ingestRunning = status?.stage === 'loading';
  const anyRunning = extractRunning || enrichRunning || ingestRunning;

  const showNotice = (type, text) => {
    setNotice({ type, text });
    setTimeout(() => setNotice(null), 6000);
  };

  const handlePickFiles = () => fileRef.current?.click();

  const handleUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = ''; // сброс, чтобы повторно можно было загрузить те же файлы
    if (!files.length) return;
    setUploading(true);
    try {
      const res = await api.corpusUpload(files);
      const parts = [`Загружено: ${res.count}`];
      if (res.skipped?.length) parts.push(`пропущено: ${res.skipped.length}`);
      if (res.ingest_queued) parts.push('ингест запущен');
      showNotice('ok', parts.join(', '));
      refresh();
    } catch (err) {
      showNotice('err', err.message);
    } finally {
      setUploading(false);
    }
  };

  const handleStart = async () => {
    setBusy(true);
    try {
      const calls = [];
      if (!extractRunning) calls.push(api.adminExtract('new').catch((e) => ({ err: e.message, task: 'extract' })));
      if (!enrichRunning) calls.push(api.usefulInfoEnrich().catch((e) => ({ err: e.message, task: 'enrich' })));
      if (!calls.length) {
        showNotice('ok', 'Обе задачи уже выполняются');
        return;
      }
      const results = await Promise.all(calls);
      const failed = results.filter((r) => r?.err);
      if (failed.length) {
        showNotice('err', failed.map((f) => `${f.task}: ${f.err}`).join('; '));
      } else {
        showNotice('ok', 'Обработка запущена');
      }
      refresh();
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    setBusy(true);
    try {
      const calls = [];
      if (extractRunning) calls.push(api.adminExtractCancel().catch((e) => ({ err: e.message, task: 'extract' })));
      if (enrichRunning) calls.push(api.usefulInfoEnrichCancel().catch((e) => ({ err: e.message, task: 'enrich' })));
      if (!calls.length) {
        showNotice('ok', 'Обработка не запущена');
        return;
      }
      const results = await Promise.all(calls);
      const failed = results.filter((r) => r?.err);
      if (failed.length) {
        showNotice('err', failed.map((f) => `${f.task}: ${f.err}`).join('; '));
      } else {
        showNotice('ok', 'Запрошена остановка (завершится после текущего документа)');
      }
      refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="animate-fade">
      <PageHeader
        eyebrow="Администрирование"
        title="Данные и обогащение"
        description="Прогресс загрузки корпуса, обогащения графа и метрики качества данных."
      />
      <div className="mx-auto max-w-7xl px-6 py-6 space-y-6">
        <section className="card">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="text-xs uppercase tracking-wider text-brand-red">Управление</div>
              <div className="text-lg font-semibold">Корпус и обработка</div>
              <div className="mt-1 text-xs text-ink-muted">
                Загрузите файлы в корпус, запустите извлечение и обогащение. Остановка сработает
                после текущего документа.
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <input
                ref={fileRef}
                type="file"
                multiple
                accept=".pdf,.docx,.doc,.docm,.pptx,.ppt,.xlsx,.xls,.txt"
                className="hidden"
                onChange={handleUpload}
              />
              <button
                type="button"
                onClick={handlePickFiles}
                disabled={uploading}
                className="btn-secondary"
                title="Добавить файлы в корпус — сохранит в data/corpus/uploads/ и запустит ingest"
              >
                {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                Добавить файлы
              </button>
              <button
                type="button"
                onClick={handleStart}
                disabled={busy || (extractRunning && enrichRunning)}
                className="btn-primary"
                title="Запустить извлечение экспериментов и обогащение useful_info"
              >
                <Play size={14} />
                Начать обработку
              </button>
              <button
                type="button"
                onClick={handleStop}
                disabled={busy || !(extractRunning || enrichRunning)}
                className="btn-secondary text-brand-red hover:bg-brand-red/5"
                title="Остановить обе задачи — extract и useful_info/enrich"
              >
                <Square size={14} />
                Остановить
              </button>
            </div>
          </div>
          {notice && (
            <div
              className={`mt-3 rounded-md border px-3 py-2 text-xs ${
                notice.type === 'ok'
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                  : 'border-brand-red/30 bg-brand-red/5 text-brand-red'
              }`}
            >
              {notice.text}
            </div>
          )}
          {anyRunning && (
            <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-ink-muted">
              {ingestRunning && <RunningPill label="ingest" />}
              {extractRunning && <RunningPill label="extract" />}
              {enrichRunning && <RunningPill label="useful_info/enrich" />}
            </div>
          )}
        </section>
        <div className="grid gap-4 md:grid-cols-3">
          <StatCard
            icon={<Database size={18} className="text-brand-blue" />}
            title="Ingest"
            main={ingestMain}
            details={ingestStats && [
              { label: 'Экспериментов', value: ingestStats.experiments },
              { label: 'Документов', value: ingestStats.documents },
              { label: 'Чанков', value: ingestStats.chunks },
            ]}
          />
          <StatCard
            icon={<Activity size={18} className="text-brand-red" />}
            title="Качество данных"
            main={quality?.extract_coverage
              ? `${quality.extract_coverage.pct}% покрытия`
              : '—'}
            details={[
              { label: 'Обогащено useful_info',
                value: quality?.useful_info
                  ? `${quality.useful_info.drafts_enriched}/${quality.useful_info.drafts_total} (${quality.useful_info.pct}%)`
                  : '—' },
              { label: 'Средняя достоверность',
                value: quality?.confidence?.avg != null
                  ? `${Math.round(quality.confidence.avg * 100)}%`
                  : '—' },
              { label: 'Русскоязычных описаний',
                value: quality?.language
                  ? `${quality.language.ru_pct}%`
                  : '—' },
            ]}
          />
          <StatCard
            icon={<Zap size={18} className="text-brand-navy" />}
            title="Обогащение графа"
            main={`${events.length} событий`}
            details={[
              { label: 'Тип последнего', value: events.at(-1)?.type || '—' },
            ]}
          />
        </div>

        <section className="grid gap-4 lg:grid-cols-2">
          <TaskCard
            icon={<FileSearch size={18} className="text-brand-blue" />}
            title="Extract: новые документы"
            model={EXTRACT_MODEL}
            status={extractStatus}
            progress={extractProgress}
            baseline={taskBaselines.extract}
            nowSec={nowSec}
          />
          <TaskCard
            icon={<Layers3 size={18} className="text-brand-blue" />}
            title="useful_info/enrich"
            model={USEFUL_INFO_MODEL}
            status={usefulInfoStatus}
            progress={usefulInfoProgress}
            baseline={taskBaselines.usefulInfo}
            nowSec={nowSec}
          />
        </section>

        <section className="card">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-wider text-brand-red">Лог событий</div>
              <div className="text-lg font-semibold">Auto-enrichment</div>
            </div>
            <button onClick={refresh} className="btn-ghost"><RefreshCw size={12} /> Обновить</button>
          </div>
          <div className="max-h-96 overflow-y-auto rounded-md border border-surface-divider bg-surface">
            {events.length === 0 ? (
              <div className="p-6 text-center text-xs text-ink-muted">Пока пусто. Загрузите корпус или запустите обогащение.</div>
            ) : (
              <ul className="divide-y divide-surface-divider">
                {events.map((ev, i) => (
                  <li key={i} className="flex items-start gap-3 p-3 text-xs">
                    <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-brand-blue" />
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold text-ink">{ev.type}</div>
                      <div className="font-mono text-[11px] text-ink-muted break-all">
                        {JSON.stringify(ev).slice(0, 180)}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function RunningPill({ label }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-brand-blue/10 px-2 py-0.5 text-brand-blue">
      <Loader2 size={10} className="animate-spin" />
      {label}
    </span>
  );
}

function TaskCard({ icon, title, model, status, progress, baseline, nowSec }) {
  const stage = status?.stage || 'idle';
  const running = stage === 'running';
  const done = progress?.done ?? null;
  const total = progress?.total ?? null;
  const remaining = done != null && total != null ? Math.max(total - done, 0) : null;
  const pct = done != null && total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const elapsed = status?.started_at ? Math.max(0, nowSec - status.started_at) : null;
  const runDone = baseline && done != null ? Math.max(done - baseline.done, 0) : null;
  const observedElapsed = baseline?.observedAt ? Math.max(0, nowSec - baseline.observedAt) : null;
  const rate = observedElapsed && observedElapsed > 30 && runDone ? runDone / observedElapsed : null;
  const eta = running && rate && remaining ? remaining / rate : null;
  const stageClass = running
    ? 'bg-brand-blue/10 text-brand-blue'
    : stage === 'done'
      ? 'bg-emerald-50 text-emerald-700'
      : stage === 'error'
        ? 'bg-brand-red/10 text-brand-red'
        : stage === 'cancelled'
          ? 'bg-amber-50 text-amber-700'
          : 'bg-surface-hover text-ink-muted';

  return (
    <div className="card">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-surface">{icon}</div>
          <div className="min-w-0">
            <div className="truncate text-xs uppercase tracking-wider text-ink-muted">{title}</div>
            <div className="truncate font-mono text-[11px] text-ink-soft" title={model}>{model}</div>
          </div>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${stageClass}`}>
          {TASK_LABEL[stage] || stage}
        </span>
      </div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="text-2xl font-bold tracking-tight">
            {done != null && total != null ? `${done}/${total}` : '—'}
          </div>
          <div className="text-xs text-ink-muted">{progress?.unit || 'объектов'}</div>
        </div>
        {running && <Loader2 size={18} className="mb-1 animate-spin text-brand-blue" />}
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-hover">
        <div className="h-full rounded-full bg-brand-blue transition-all" style={{ width: `${pct}%` }} />
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-2 border-t border-surface-divider pt-3 text-xs">
        <div>
          <dt className="text-ink-muted">Осталось</dt>
          <dd className="font-semibold text-ink">{remaining != null ? remaining : '—'}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">Прошло</dt>
          <dd className="font-semibold text-ink">{formatDuration(elapsed)}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">ETA</dt>
          <dd className="font-semibold text-ink">{eta ? `~${formatDuration(eta)}` : '—'}</dd>
        </div>
      </dl>
    </div>
  );
}

function StatCard({ icon, title, main, details }) {
  return (
    <div className="card">
      <div className="mb-2 flex items-center gap-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-md bg-surface">{icon}</div>
        <div className="text-xs uppercase tracking-wider text-ink-muted">{title}</div>
      </div>
      <div className="mb-3 text-2xl font-bold tracking-tight">{main}</div>
      {details && (
        <dl className="space-y-1 border-t border-surface-divider pt-3 text-xs">
          {details.map((d) => (
            <div key={d.label} className="flex justify-between">
              <dt className="text-ink-muted">{d.label}</dt>
              <dd className="font-semibold text-ink">{d.value ?? '—'}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return '—';
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} с`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 24) return rest ? `${hours} ч ${rest} мин` : `${hours} ч`;
  const days = Math.floor(hours / 24);
  const dayRest = hours % 24;
  return dayRest ? `${days} д ${dayRest} ч` : `${days} д`;
}

function extractProgressFromQuality(quality) {
  return quality?.extract_coverage ? {
    done: quality.extract_coverage.documents_extracted,
    total: quality.extract_coverage.documents_total,
    unit: 'документов',
  } : null;
}

function usefulInfoProgressFromQuality(quality) {
  return quality?.useful_info ? {
    done: quality.useful_info.drafts_enriched,
    total: quality.useful_info.drafts_total,
    unit: 'черновиков',
  } : null;
}

function nextBaseline(current, status, progress) {
  if (status?.stage !== 'running' || !status.started_at || !progress) return null;
  if (current?.startedAt === status.started_at) return current;
  return {
    startedAt: status.started_at,
    done: progress.done,
    observedAt: Date.now() / 1000,
  };
}
