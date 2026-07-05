'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Search, Loader2, ArrowUpRight, Sparkles, GitBranch, Database, Zap, Scale, BookOpen, Globe, Flag } from 'lucide-react';

const EXAMPLES = [
  {
    tag: 'Q&A',
    text: 'Какие методы обессоливания воды подходят для обогатительной фабрики при сульфатах и хлоридах 200–300 мг/л и требовании сухого остатка ≤1000 мг/дм³?',
  },
  {
    tag: 'Литобзор',
    text: 'Какие технические решения циркуляции католита при электроэкстракции никеля описаны в мировой практике?',
  },
  {
    tag: 'Пробелы',
    text: 'Покажите эксперименты и публикации по распределению Au, Ag и МПГ между медным штейном и шлаком за 5 лет',
  },
  {
    tag: 'Сравнение',
    text: 'Какие способы закачки шахтных вод в глубокие горизонты применялись в России и за рубежом? Технико-экономические показатели',
  },
];

const FEATURES = [
  { icon: <Sparkles className="text-brand-red" size={22} />, title: 'Q&A с цитатами',
    desc: 'Задайте вопрос — получите связный ответ с ссылками на конкретные эксперименты и документы.' },
  { icon: <BookOpen className="text-brand-blue" size={22} />, title: 'Литобзор',
    desc: 'Автогенерация обзора с группировкой по методу, году, отечественной/зарубежной практике.' },
  { icon: <Scale className="text-brand-navy" size={22} />, title: 'Сравнение',
    desc: 'Материалы, режимы, технологии — таблица параметров с разбросом значений.' },
  { icon: <GitBranch className="text-brand-red" size={22} />, title: 'Пробелы',
    desc: 'Тепловая карта покрытия + топологические пробелы через Link Prediction.' },
  { icon: <Zap className="text-brand-navy" size={22} />, title: 'Самообогащение',
    desc: 'При добавлении данных система сама создаёт связи через NER и семантику.' },
];

const INTENTS = [
  { key: null,                     label: 'Обычный ответ',   icon: <Sparkles size={12} /> },
  { key: 'literature_review',      label: 'Литобзор',        icon: <BookOpen size={12} /> },
  { key: 'comparison',             label: 'Сравнение',       icon: <Scale size={12} /> },
];

const GEOS = [
  { key: 'any',      label: 'Все источники',       icon: <Globe size={12} /> },
  { key: 'domestic', label: 'Только РФ / СНГ',     icon: <Flag size={12} /> },
  { key: 'foreign',  label: 'Только зарубежные',   icon: <Globe size={12} /> },
];

export default function HomePage() {
  const router = useRouter();
  const [q, setQ] = useState('');
  const [geo, setGeo] = useState('any');
  const [intentHint, setIntentHint] = useState(null);
  const [loading, setLoading] = useState(false);

  function ask(text) {
    const target = (text ?? q).trim();
    if (!target) return;
    setLoading(true);
    const id = btoa(unescape(encodeURIComponent(target + Date.now())))
      .replace(/[^a-zA-Z0-9]/g, '').slice(0, 24);
    const params = new URLSearchParams({ q: target, geo, ...(intentHint ? { intent: intentHint } : {}) });
    router.push(`/answer/${id}?${params}`);
  }

  return (
    <div className="animate-fade">
      <section className="relative overflow-hidden bg-brand-navy text-white">
        <div className="pointer-events-none absolute inset-0 opacity-30"
             style={{ backgroundImage: 'radial-gradient(circle at 20% 20%, #1D57A6 0%, transparent 45%), radial-gradient(circle at 80% 60%, #E30613 0%, transparent 40%)' }} />
        <div className="relative mx-auto max-w-5xl px-6 py-20 md:py-28">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/5 px-3 py-1 text-xs font-medium backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-red" />
            AI Science Hack 2026 · Трек «Научный клубок»
          </div>
          <h1 className="text-hero md:text-display font-bold text-white">
            Спросите вашу
            <br />
            <span className="text-white/60">R&D-базу знаний</span>
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-relaxed text-white/70 md:text-lg">
            Knowledge graph, семантический поиск и Q&A по экспериментам, материалам,
            свойствам и техническим отчётам. Отечественная и зарубежная практика — в одном графе.
          </p>

          <div className="mt-10 rounded-xl bg-white p-2 shadow-2xl shadow-black/30">
            <div className="flex items-start gap-2">
              <textarea rows={2}
                className="flex-1 resize-none rounded-lg border-0 bg-transparent px-4 py-3 text-ink placeholder:text-ink-soft focus:outline-none text-base"
                placeholder="Например: методы обессоливания воды при сульфатах 200–300 мг/л"
                value={q} onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); } }}
                disabled={loading} />
              <button onClick={() => ask()} disabled={loading || !q.trim()} className="btn-accent shrink-0">
                {loading ? <Loader2 className="animate-spin" size={18} /> : <Search size={18} />}
                Спросить
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2 border-t border-surface-divider px-3 pt-3 pb-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">Формат:</span>
              {INTENTS.map((it) => (
                <button key={String(it.key)}
                        onClick={() => setIntentHint(it.key)}
                        className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-xs transition ${intentHint === it.key ? 'bg-brand-blue text-white' : 'bg-surface text-ink hover:bg-surface-hover'}`}>
                  {it.icon}{it.label}
                </button>
              ))}
              <span className="mx-2 text-ink-soft">·</span>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">Гео:</span>
              {GEOS.map((g) => (
                <button key={g.key}
                        onClick={() => setGeo(g.key)}
                        className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-xs transition ${geo === g.key ? 'bg-brand-red text-white' : 'bg-surface text-ink hover:bg-surface-hover'}`}>
                  {g.icon}{g.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-6 py-12">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Примеры вопросов</h2>
          <span className="text-xs text-ink-muted">Нажмите, чтобы задать</span>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {EXAMPLES.map((ex) => (
            <button key={ex.text} onClick={() => ask(ex.text)} disabled={loading}
                    className="card card-hover text-left group">
              <div className="mb-2 flex items-center justify-between">
                <span className="chip">{ex.tag}</span>
                <ArrowUpRight size={16} className="text-ink-soft transition-colors group-hover:text-brand-blue" />
              </div>
              <div className="text-sm leading-relaxed text-ink">{ex.text}</div>
            </button>
          ))}
        </div>
      </section>

      <section className="border-t border-surface-divider bg-white">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="mb-10 max-w-2xl">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-brand-red">Возможности</div>
            <h2 className="text-3xl font-bold">Что умеет система</h2>
          </div>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="rounded-lg border border-surface-divider bg-surface p-6">
                <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-md bg-white shadow-sm">{f.icon}</div>
                <div className="mb-1.5 font-semibold">{f.title}</div>
                <div className="text-sm leading-relaxed text-ink-muted">{f.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
