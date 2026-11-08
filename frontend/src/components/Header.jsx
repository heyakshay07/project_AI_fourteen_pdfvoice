import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';

export function Logo() {
  return (
    <span className="flex items-center gap-2 text-lg font-semibold">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-white" aria-hidden="true">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 4h10l6 6v10H4z" /><path d="M9 14v2m3-4v6m3-5v4" />
        </svg>
      </span>
      PDFVoice <span className="text-brand-600">AI</span>
    </span>
  );
}

export default function Header() {
  const { user, logout } = useAuth();
  const { dark, toggle } = useTheme();
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
        <Link to="/" aria-label="PDFVoice AI home"><Logo /></Link>
        <div className="flex items-center gap-2">
          <button className="btn-ghost" onClick={toggle} aria-label="Toggle dark mode">{dark ? '☀ Light' : '🌙 Dark'}</button>
          {user && (
            <>
              <span className="hidden text-sm text-slate-500 sm:inline">{user.name}</span>
              <button className="btn-ghost" onClick={logout}>Log out</button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
