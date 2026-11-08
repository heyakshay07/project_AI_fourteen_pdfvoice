import axios from 'axios';

const TOKEN_KEY = 'pdfvoice_token';
export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY));

const BASE = import.meta.env.VITE_API_URL || '';
const http = axios.create({ baseURL: BASE });

http.interceptors.request.use((cfg) => {
  const t = getToken();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});
http.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && getToken()) window.dispatchEvent(new Event('auth:logout'));
    return Promise.reject(err);
  },
);

/** Turns the backend's {"error": {code, message}} (or a network failure) into readable text. */
export function errorMessage(err) {
  const e = err?.response?.data?.error;
  if (e) {
    if (e.details?.length) return `${e.message}: ${e.details.map((d) => `${d.field} ${d.message}`).join('; ')}`;
    return e.message;
  }
  if (err?.code === 'ERR_NETWORK') return 'Cannot reach the server. Is the backend running?';
  return err?.message || 'Something went wrong';
}

const d = (p) => p.then((r) => r.data);

export const auth = {
  register: (body) => d(http.post('/api/v1/auth/register', body)),
  login: (body) => d(http.post('/api/v1/auth/login', body)),
  me: () => d(http.get('/api/v1/auth/me')),
};

export const pdf = {
  upload: (file, onProgress) => {
    const form = new FormData();
    form.append('file', file);
    return d(http.post('/api/v1/pdf/upload', form, {
      onUploadProgress: (e) => onProgress?.(e.total ? Math.round((100 * e.loaded) / e.total) : 0),
    }));
  },
  get: (id) => d(http.get(`/api/v1/pdf/${id}`)),
  process: (id) => d(http.post(`/api/v1/pdf/${id}/process`)),
  remove: (id) => http.delete(`/api/v1/pdf/${id}`),
  pages: (id) => d(http.get(`/api/v1/pdf/${id}/pages`)),
  page: (id, n) => d(http.get(`/api/v1/pdf/${id}/text`, { params: { page: n } })).then((r) => r.pages[0]),
  file: (id) => http.get(`/api/v1/pdf/${id}/file`, { responseType: 'arraybuffer' }).then((r) => r.data),
};

/** Server-Sent Events over fetch so the Authorization header can be sent (EventSource cannot). */
export async function streamProgress(id, onEvent, signal) {
  const res = await fetch(`${BASE}/api/v1/pdf/${id}/progress/stream`, {
    headers: { Authorization: `Bearer ${getToken()}` },
    signal,
  });
  if (!res.ok || !res.body) throw new Error('Could not open progress stream');
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = chunk.split('\n').find((l) => l.startsWith('data:'));
      if (line) onEvent(JSON.parse(line.slice(5).trim()));
    }
  }
}

export const voice = {
  available: () => d(http.get('/api/v1/voice/available-voices')),
  getSettings: () => d(http.get('/api/v1/voice/settings')),
  putSettings: (body) => d(http.put('/api/v1/voice/settings', body)),
  generate: (documentId) => d(http.post('/api/v1/voice/generate', { document_id: documentId })),
  segments: (id) => d(http.get(`/api/v1/voice/${id}/segments`)),
  segmentDetail: (id, segId) => d(http.get(`/api/v1/voice/${id}/segments/${segId}`)),
  audio: (id, segId) =>
    http.get(`/api/v1/voice/${id}/audio/${segId}`, { responseType: 'blob' }).then((r) => URL.createObjectURL(r.data)),
};

export const playback = {
  start: (document_id) => d(http.post('/api/v1/playback/start', { document_id })),
  send: (action, body) => d(http.post(`/api/v1/playback/${action}`, body)), // pause | resume | stop | seek
};

export const history = {
  list: () => d(http.get('/api/v1/history')),
  get: (id) => d(http.get(`/api/v1/history/${id}`)),
  saveProgress: (id, page, sentence) => d(http.put(`/api/v1/history/${id}/progress`, { page, sentence })),
  clear: (id) => http.delete(`/api/v1/history/${id}`),
};
