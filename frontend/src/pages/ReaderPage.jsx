import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import PdfViewer from '../components/PdfViewer';
import TextPanel from '../components/TextPanel';
import AudioPlayer from '../components/AudioPlayer';
import VoiceSettings from '../components/VoiceSettings';
import useAudioPlayer from '../hooks/useAudioPlayer';
import { history, pdf, streamProgress, voice, errorMessage } from '../services/api';
import { useToast } from '../context/ToastContext';

const STAGES = {
  queued: 'Waiting for a worker…', starting: 'Starting…', analyzing: 'Analysing the PDF…', extracting: 'Extracting text (OCR for scanned pages)…',
  validating: 'Validating extracted text…', ocr_retry: 'Re-reading unclear pages with OCR…', chunking: 'Preparing sentences for reading…', saving: 'Saving…',
};

function Processing({ doc, progress, onRetry }) {
  if (doc.processing_status === 'failed') {
    return (
      <div className="card mx-auto mt-10 max-w-lg space-y-3 text-center">
        <div className="text-3xl">⚠️</div>
        <h2 className="font-semibold">This document could not be processed</h2>
        <p className="text-sm text-red-600">{doc.error_message}</p>
        <div className="flex justify-center gap-2"><button className="btn-primary" onClick={onRetry}>Try again</button><Link className="btn-ghost" to="/">Back</Link></div>
      </div>
    );
  }
  const pct = Math.round(progress?.percent ?? doc.progress_percent ?? 0);
  return (
    <div className="card mx-auto mt-10 max-w-lg space-y-3">
      <h2 className="font-semibold">Preparing “{doc.filename}”</h2>
      <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full bg-brand-600 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-sm text-slate-500"><span className="spinner" /> {STAGES[progress?.stage || doc.progress_stage] || 'Working…'} {pct}%</p>
      {progress && progress.total_pages > 0 && <p className="text-xs text-slate-500">{progress.pages_extracted}/{progress.total_pages} pages saved</p>}
    </div>
  );
}

export default function ReaderPage() {
  const { id } = useParams();
  const toast = useToast();
  const [doc, setDoc] = useState(null);
  const [progress, setProgress] = useState(null);
  const [segments, setSegments] = useState([]);
  const [pdfData, setPdfData] = useState(null);
  const [pages, setPages] = useState({}); // page number -> text/sentences/validation
  const [viewPage, setViewPage] = useState(1);
  const [zoom, setZoom] = useState(1.25);
  const [tab, setTab] = useState('pdf');
  const [voiceSettings, setVoiceSettings] = useState(null);
  const requested = useRef(new Set());

  const voiceKey = voiceSettings ? `${voiceSettings.voice_engine}|${voiceSettings.voice_name}|${voiceSettings.language}` : '';
  const player = useAudioPlayer({ documentId: id, segments, voiceKey, onError: (e) => toast.error(errorMessage(e)) });

  // ----- load + process
  const startProcessing = useCallback(async () => {
    try { await pdf.process(id); } catch (e) { if (e.response?.status !== 409) toast.error(errorMessage(e)); }
    setDoc(await pdf.get(id));
  }, [id, toast]);

  useEffect(() => {
    let alive = true;
    pdf.get(id).then(async (d) => {
      if (!alive) return;
      setDoc(d);
      if (d.processing_status === 'uploaded') startProcessing();
    }).catch((e) => toast.error(errorMessage(e)));
    return () => { alive = false; };
  }, [id, startProcessing, toast]);

  useEffect(() => {
    if (!doc || !['queued', 'processing'].includes(doc.processing_status)) return undefined;
    const ctrl = new AbortController();
    streamProgress(id, async (p) => {
      setProgress(p);
      if (p.processing_status === 'completed' || p.processing_status === 'failed') setDoc(await pdf.get(id));
    }, ctrl.signal).catch(() => {
      // fall back to polling if the stream is interrupted
      const t = setInterval(async () => {
        const d = await pdf.get(id).catch(() => null);
        if (d && !['queued', 'processing'].includes(d.processing_status)) { clearInterval(t); setDoc(d); }
      }, 2000);
    });
    return () => ctrl.abort();
  }, [id, doc?.processing_status]); // eslint-disable-line react-hooks/exhaustive-deps

  // ----- once processed: segments, original PDF, saved position
  useEffect(() => {
    if (doc?.processing_status !== 'completed') return;
    Promise.all([voice.segments(id), pdf.file(id), history.get(id).catch(() => null)]).then(([segs, buf, h]) => {
      setSegments(segs);
      setPdfData(buf);
      const start = h?.current_page ? { page: h.current_page, sentence: h.current_sentence || 0 } : { page: segs[0]?.page_number || 1, sentence: 0 };
      player.setPosition(start);
      setViewPage(start.page);
    }).catch((e) => toast.error(errorMessage(e)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.processing_status, id]);

  // ----- page text cache
  const ensurePage = useCallback((n) => {
    if (!n || requested.current.has(n)) return;
    requested.current.add(n);
    pdf.page(id, n).then((p) => setPages((m) => ({ ...m, [n]: p })))
      .catch((e) => { requested.current.delete(n); if (e.response?.status !== 404) toast.error(errorMessage(e)); else setPages((m) => ({ ...m, [n]: { page_number: n, sentences: [], validation_status: 'empty', validation_notes: ['This page has no extracted text.'], extraction_method: 'none' } })); });
  }, [id, toast]);
  useEffect(() => { if (doc?.processing_status === 'completed') { ensurePage(viewPage); ensurePage(player.position.page); } }, [viewPage, player.position.page, doc?.processing_status, ensurePage]);

  // follow the reader while audio is playing
  useEffect(() => { if (player.playing) setViewPage(player.position.page); }, [player.playing, player.position.page]);

  // apply the saved speaking speed as playback rate
  useEffect(() => { if (voiceSettings) player.setSpeed(voiceSettings.speaking_speed); }, [voiceSettings?.speaking_speed]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalPages = doc?.total_pages || 0;
  const goView = (n) => setViewPage(Math.min(Math.max(1, n), totalPages));

  const { page: curPage, sentence: curSentence } = player.position;
  const curPageData = pages[curPage];
  const viewData = pages[viewPage];
  const currentSentence = curPageData?.sentences?.[curSentence];

  const readingPct = useMemo(() => {
    if (!segments.length) return 0;
    const counts = {};
    segments.forEach((s) => { counts[s.page_number] = Math.max(counts[s.page_number] || 0, s.sentence_end + 1); });
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    const before = Object.entries(counts).filter(([p]) => Number(p) < curPage).reduce((a, [, n]) => a + n, 0);
    return total ? (100 * (before + curSentence)) / total : 0;
  }, [segments, curPage, curSentence]);

  if (!doc) return <div className="p-10 text-center text-slate-500"><span className="spinner" /> Loading…</div>;
  if (doc.processing_status !== 'completed') return <Processing doc={doc} progress={progress} onRetry={startProcessing} />;

  const warnPages = progress?.pages_with_warnings || 0;
  return (
    <main className="mx-auto grid max-w-7xl gap-6 px-4 py-6 lg:grid-cols-[1fr_380px]">
      <section aria-label="Document">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <Link to="/" className="text-xs text-brand-600 hover:underline">← All documents</Link>
            <h1 className="truncate text-lg font-semibold">{doc.filename}</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex overflow-hidden rounded-lg border border-slate-300 dark:border-slate-700" role="tablist">
              {[['pdf', 'PDF'], ['text', 'Text']].map(([k, label]) => (
                <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`px-3 py-1.5 text-sm ${tab === k ? 'bg-brand-600 text-white' : ''}`}>{label}</button>
              ))}
            </div>
            <div className="flex items-center gap-1">
              <button className="btn-ghost !px-2" onClick={() => goView(viewPage - 1)} disabled={viewPage <= 1} aria-label="Previous page">‹</button>
              <label className="sr-only" htmlFor="page-input">Page</label>
              <input id="page-input" type="number" min={1} max={totalPages} value={viewPage} onChange={(e) => goView(Number(e.target.value) || 1)} className="input !w-16 text-center" />
              <span className="text-sm text-slate-500">/ {totalPages}</span>
              <button className="btn-ghost !px-2" onClick={() => goView(viewPage + 1)} disabled={viewPage >= totalPages} aria-label="Next page">›</button>
            </div>
            {tab === 'pdf' && (
              <div className="flex items-center gap-1">
                <button className="btn-ghost !px-2" onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.25).toFixed(2)))} aria-label="Zoom out">−</button>
                <span className="w-12 text-center text-sm">{Math.round(zoom * 100)}%</span>
                <button className="btn-ghost !px-2" onClick={() => setZoom((z) => Math.min(3, +(z + 0.25).toFixed(2)))} aria-label="Zoom in">+</button>
              </div>
            )}
          </div>
        </div>

        {viewData && viewData.validation_status !== 'ok' && tab === 'pdf' && (
          <p className="mb-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
            Page {viewPage}: {viewData.validation_notes?.[0] || 'extraction warning'} (see the Text tab for details)
          </p>
        )}
        {tab === 'pdf'
          ? <PdfViewer data={pdfData} page={viewPage} zoom={zoom} highlight={viewPage === curPage && currentSentence ? currentSentence.bbox : null} />
          : <TextPanel pageData={viewData} activeSentence={viewPage === curPage ? curSentence : -1} onSelect={(i) => player.seekTo(viewPage, i)} />}
        {warnPages > 0 && <p className="mt-2 text-xs text-slate-500">{warnPages} page(s) had extraction warnings. Nothing was silently dropped; check the Text tab.</p>}
      </section>

      <aside className="space-y-4">
        <AudioPlayer player={player} totalPages={totalPages} readingPct={readingPct} disabled={!segments.length || !voiceSettings} currentSentenceText={currentSentence?.text} />
        <VoiceSettings documentId={id} compact onChange={setVoiceSettings} />
      </aside>
    </main>
  );
}
