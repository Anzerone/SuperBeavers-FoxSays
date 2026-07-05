export default function Footer() {
  return (
    <footer className="border-t border-surface-divider bg-white">
      <div className="mx-auto flex max-w-7xl flex-col items-start justify-between gap-3 px-6 py-6 text-xs text-ink-muted sm:flex-row sm:items-center">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-brand-navy">Научный клубок</span>
          <span>· MVP для трека НОРНИКЕЛЬ AI SCIENCE HACK 2026</span>
        </div>
        <div className="flex items-center gap-4">
          <span>MIT License</span>
        </div>
      </div>
    </footer>
  );
}
