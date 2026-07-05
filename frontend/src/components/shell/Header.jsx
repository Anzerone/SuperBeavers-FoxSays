'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

// Мультиролевая архитектура убрана: MANAGER/user-badge/login больше не показываем.
const NAV = [
  { href: '/', label: 'Вопрос' },
  { href: '/gaps', label: 'Пробелы' },
  { href: '/compare', label: 'Сравнение' },
  { href: '/explorer', label: 'Эксплорер' },
  { href: '/stats', label: 'Статистика' },
  { href: '/admin', label: 'Данные' },
];

export default function Header() {
  const pathname = usePathname() || '/';
  return (
    <header className="app-header">
      <div className="stripe-accent" />
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
        <Link href="/" className="flex items-center gap-3">
          <span className="flex h-9 w-12 items-center justify-center" aria-hidden="true">
            <img src="/nornickel-mark.png" alt="" className="h-8 w-auto object-contain" />
          </span>
          <div className="leading-tight">
            <div className="text-sm font-bold text-white">Научный клубок</div>
            <div className="text-[10px] uppercase tracking-wider text-white/60">AI Science Hack · Норникель</div>
          </div>
        </Link>
        <nav className="ml-auto flex items-center gap-1">
          {NAV.map((item) => {
            const active =
              item.href === '/' ? pathname === '/'
              : pathname.startsWith(item.href.split('/').slice(0, 2).join('/'));
            return (
              <Link key={item.href} href={item.href}
                className={`app-nav-link ${active ? 'app-nav-link-active' : ''}`}>
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
