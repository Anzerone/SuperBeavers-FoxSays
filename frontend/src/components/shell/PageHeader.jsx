'use client';

export default function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <section className="border-b border-surface-divider bg-white">
      <div className="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-8 md:flex-row md:items-end md:justify-between">
        <div>
          {eyebrow && (
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-brand-red">
              {eyebrow}
            </div>
          )}
          <h1 className="text-3xl font-bold tracking-tight md:text-4xl">{title}</h1>
          {description && (
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-muted md:text-base">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex gap-2">{actions}</div>}
      </div>
    </section>
  );
}
