'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Loader2, LogIn, ShieldCheck } from 'lucide-react';
import { api, setStoredUser, setToken } from '@/lib/api';
import PageHeader from '@/components/shell/PageHeader';

const DEMO = [
  { u: 'researcher', desc: 'Исследователь: базовые запросы' },
  { u: 'analyst', desc: 'Аналитик: сравнение, экспорт' },
  { u: 'manager', desc: 'Руководитель: дашборды, аудит' },
  { u: 'admin', desc: 'Администратор: загрузка данных' },
];

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('demo123');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  async function submit(e) {
    e?.preventDefault();
    setLoading(true); setErr(null);
    try {
      const r = await api.login(username, password);
      setToken(r.token); setStoredUser(r.user);
      router.push('/');
      if (typeof window !== 'undefined') window.location.reload();
    } catch (e) { setErr(e.message); }
    setLoading(false);
  }

  return (
    <div className="animate-fade">
      <PageHeader
        eyebrow="Доступ"
        title="Вход в систему"
        description="Демо-учётки с одинаковым паролем demo123. У каждой роли свой набор прав."
      />
      <div className="mx-auto grid max-w-5xl gap-6 px-6 py-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <form onSubmit={submit} className="card space-y-4">
          <div className="flex items-center gap-2 text-brand-red">
            <ShieldCheck size={18} />
            <div className="text-xs uppercase tracking-wider">Учётные данные</div>
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wider text-ink-muted">Логин</label>
            <input className="input" value={username}
                   onChange={(e) => setUsername(e.target.value)} placeholder="researcher / analyst / manager / admin" />
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wider text-ink-muted">Пароль</label>
            <input className="input" type="password" value={password}
                   onChange={(e) => setPassword(e.target.value)} />
          </div>
          {err && (
            <div className="rounded-md border border-brand-red/40 bg-brand-red/5 p-3 text-sm text-brand-red">
              {err}
            </div>
          )}
          <button className="btn-primary w-full" disabled={loading || !username}>
            {loading ? <Loader2 className="animate-spin" size={16} /> : <LogIn size={16} />}
            Войти
          </button>
        </form>

        <aside className="card">
          <div className="mb-3 text-xs uppercase tracking-wider text-brand-red">Демо-пользователи</div>
          <ul className="space-y-2">
            {DEMO.map((d) => (
              <li key={d.u}>
                <button onClick={() => { setUsername(d.u); }}
                        className="flex w-full items-center justify-between rounded-md border border-surface-divider bg-surface p-3 text-left text-sm hover:border-brand-blue/40">
                  <div>
                    <div className="font-semibold">{d.u}</div>
                    <div className="text-xs text-ink-muted">{d.desc}</div>
                  </div>
                  <span className="text-xs text-ink-soft">→</span>
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-3 text-xs text-ink-muted">Пароль у всех: <code className="font-mono text-ink">demo123</code></div>
        </aside>
      </div>
    </div>
  );
}
