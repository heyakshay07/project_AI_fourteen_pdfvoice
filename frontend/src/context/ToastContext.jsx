import { createContext, useCallback, useContext, useMemo, useState } from 'react';

const Ctx = createContext(null);
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((message, kind = 'error') => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);
  const error = useCallback((message) => push(message, 'error'), [push]);
  const success = useCallback((message) => push(message, 'success'), [push]);
  const info = useCallback((message) => push(message, 'info'), [push]);
  const value = useMemo(() => ({ error, success, info }), [error, success, info]);
  const colors = { error: 'bg-red-600', success: 'bg-emerald-600', info: 'bg-slate-800' };
  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`rounded-lg px-4 py-3 text-sm text-white shadow-lg ${colors[t.kind]}`}>{t.message}</div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
