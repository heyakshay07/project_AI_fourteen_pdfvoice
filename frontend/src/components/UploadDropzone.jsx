import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { pdf, errorMessage } from '../services/api';
import { formatBytes } from '../utils/format';
import { useToast } from '../context/ToastContext';

const MAX_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB || 100);

export default function UploadDropzone({ onUploaded }) {
  const input = useRef(null);
  const toast = useToast();
  const navigate = useNavigate();
  const [drag, setDrag] = useState(false);
  const [file, setFile] = useState(null);
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  async function handle(f) {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith('.pdf') && f.type !== 'application/pdf') return toast.error('Please choose a PDF file.');
    if (f.size > MAX_MB * 1024 * 1024) return toast.error(`That file is larger than ${MAX_MB} MB.`);
    setFile(f); setResult(null); setProgress(0); setBusy(true);
    try {
      const doc = await pdf.upload(f, setProgress);
      setResult(doc);
      onUploaded?.(doc);
    } catch (e) {
      toast.error(errorMessage(e));
      setFile(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div
        role="button" tabIndex={0} aria-label="Upload a PDF"
        onClick={() => !busy && input.current?.click()}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && !busy && input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); handle(e.dataTransfer.files?.[0]); }}
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition
          ${drag ? 'border-brand-500 bg-brand-50 dark:bg-brand-700/10' : 'border-slate-300 hover:border-brand-500 dark:border-slate-700'}`}
      >
        <div className="text-3xl" aria-hidden="true">📄</div>
        <p className="font-medium">Drag &amp; drop a PDF here, or <span className="text-brand-600">browse</span></p>
        <p className="text-xs text-slate-500">PDF only · up to {MAX_MB} MB · scanned PDFs are read with OCR</p>
        <input ref={input} type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => { handle(e.target.files?.[0]); e.target.value = ''; }} />
      </div>

      {file && (
        <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800/50">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-medium">{file.name}</span>
            <span className="shrink-0 text-slate-500">{formatBytes(file.size)}</span>
          </div>
          {busy && (
            <div className="mt-2">
              <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                <div className="h-full bg-brand-600 transition-all" style={{ width: `${progress}%` }} />
              </div>
              <p className="mt-1 text-xs text-slate-500">Uploading… {progress}%</p>
            </div>
          )}
          {result && (
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-emerald-600">✓ Uploaded · {result.total_pages} page{result.total_pages === 1 ? '' : 's'}
                {result.pdf_type === 'scanned' ? ' · scanned (OCR needed)' : result.pdf_type === 'mixed' ? ' · partly scanned' : ''}</span>
              <button className="btn-primary" onClick={() => navigate(`/read/${result.id}`)}>Process &amp; read →</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
