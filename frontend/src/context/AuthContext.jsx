import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { auth, getToken, setToken } from '../services/api';

const Ctx = createContext(null);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(!!getToken());

  const logout = useCallback(() => { setToken(null); setUser(null); }, []);

  useEffect(() => {
    if (!getToken()) return;
    auth.me().then(setUser).catch(logout).finally(() => setLoading(false));
  }, [logout]);

  useEffect(() => {
    window.addEventListener('auth:logout', logout);
    return () => window.removeEventListener('auth:logout', logout);
  }, [logout]);

  const accept = (res) => { setToken(res.access_token); setUser(res.user); };
  const login = async (email, password) => accept(await auth.login({ email, password }));
  const register = async (name, email, password) => accept(await auth.register({ name, email, password }));

  return <Ctx.Provider value={{ user, loading, login, register, logout }}>{children}</Ctx.Provider>;
}
