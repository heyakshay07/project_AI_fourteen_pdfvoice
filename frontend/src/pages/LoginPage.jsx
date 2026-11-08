import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { errorMessage } from '../services/api';
import { Logo } from '../components/Header';

export default function LoginPage() {
  const { user, login, register } = useAuth();
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/" replace />;

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  async function submit(e) {
    e.preventDefault();
    setError(''); setBusy(true);
    try {
      if (mode === 'login') await login(form.email, form.password);
      else await register(form.name, form.email, form.password);
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center"><Logo /></div>
        <form onSubmit={submit} className="card space-y-4">
          <h1 className="text-xl font-semibold">{mode === 'login' ? 'Welcome back' : 'Create your account'}</h1>
          {mode === 'register' && (
            <div><label className="label" htmlFor="name">Name</label><input id="name" className="input" required value={form.name} onChange={set('name')} autoComplete="name" /></div>
          )}
          <div><label className="label" htmlFor="email">Email</label><input id="email" type="email" className="input" required value={form.email} onChange={set('email')} autoComplete="email" /></div>
          <div><label className="label" htmlFor="password">Password</label>
            <input id="password" type="password" className="input" required minLength={mode === 'register' ? 8 : 1} value={form.password} onChange={set('password')} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
            {mode === 'register' && <p className="mt-1 text-xs text-slate-500">At least 8 characters.</p>}
          </div>
          {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
          <button className="btn-primary w-full" disabled={busy}>{busy && <span className="spinner" />}{mode === 'login' ? 'Log in' : 'Sign up'}</button>
          <p className="text-center text-sm text-slate-500">
            {mode === 'login' ? 'New here?' : 'Already registered?'}{' '}
            <button type="button" className="text-brand-600 hover:underline" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}>
              {mode === 'login' ? 'Create an account' : 'Log in'}
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}
