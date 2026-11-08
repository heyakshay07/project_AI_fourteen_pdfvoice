import { useCallback, useEffect, useState } from 'react';
import UploadDropzone from '../components/UploadDropzone';
import DocumentCard from '../components/DocumentCard';
import VoiceSettings from '../components/VoiceSettings';
import { history, pdf, errorMessage } from '../services/api';
import { useToast } from '../context/ToastContext';

export default function DashboardPage() {
  const toast = useToast();
  const [items, setItems] = useState(null);

  const refresh = useCallback(() => history.list().then(setItems).catch((e) => toast.error(errorMessage(e))), [toast]);
  useEffect(() => { refresh(); }, [refresh]);

  async function remove(item) {
    if (!window.confirm(`Delete "${item.filename}" and its audio? This cannot be undone.`)) return;
    try { await pdf.remove(item.document_id); toast.success('Document deleted'); refresh(); }
    catch (e) { toast.error(errorMessage(e)); }
  }
  async function reset(item) {
    try { await history.clear(item.document_id); refresh(); } catch (e) { toast.error(errorMessage(e)); }
  }

  const continuing = (items || []).filter((i) => i.current_page != null && i.processing_status === 'completed' && i.progress_percentage < 100).slice(0, 3);

  return (
    <main className="mx-auto grid max-w-7xl gap-6 px-4 py-6 lg:grid-cols-[1fr_340px]">
      <div className="space-y-6">
        <UploadDropzone onUploaded={refresh} />

        {continuing.length > 0 && (
          <section aria-labelledby="continue">
            <h2 id="continue" className="mb-2 font-semibold">Continue reading</h2>
            <div className="space-y-2">{continuing.map((i) => <DocumentCard key={i.document_id} item={i} onDelete={remove} onClearHistory={reset} />)}</div>
          </section>
        )}

        <section aria-labelledby="docs">
          <h2 id="docs" className="mb-2 font-semibold">Your documents &amp; reading history</h2>
          {items === null && <p className="text-sm text-slate-500"><span className="spinner" /> Loading…</p>}
          {items?.length === 0 && <div className="card text-center text-sm text-slate-500">No documents yet. Upload a PDF to get started.</div>}
          <div className="space-y-2">{items?.map((i) => <DocumentCard key={i.document_id} item={i} onDelete={remove} onClearHistory={reset} />)}</div>
        </section>
      </div>
      <aside><VoiceSettings /></aside>
    </main>
  );
}
