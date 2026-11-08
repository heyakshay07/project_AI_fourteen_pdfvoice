import { createContext, useCallback, useContext, useState } from 'react';

const Ctx = createContext(null);
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((message, kind = 'error') => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);
  const colors = { error: 'bg-red-600', success: 'bg-emerald-600', info: 'bg-slate-800' };
  return (
    <Ctx.Provider value={{ error: (m) => push(m, 'error'), success: (m) => push(m, 'success'), info: (m) => push(m, 'info') }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`rounded-lg px-4 py-3 text-sm text-white shadow-lg ${colors[t.kind]}`}>{t.message}</div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
