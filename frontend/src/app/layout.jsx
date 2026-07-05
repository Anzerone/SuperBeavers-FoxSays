import './globals.css';
import Header from '@/components/shell/Header';
import Footer from '@/components/shell/Footer';

export const metadata = {
  title: 'Научный клубок — Норникель AI Science Hack 2026',
  description: 'Knowledge graph и Q&A по научной базе экспериментов и документов',
};

export default function RootLayout({ children }) {
  return (
    <html lang="ru">
      <body className="flex min-h-screen flex-col bg-surface">
        <Header />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
