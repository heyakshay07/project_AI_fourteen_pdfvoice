import { useEffect, useRef, useState } from 'react';
import * as pdfjsLib from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

/**
 * Renders one PDF page with PDF.js and overlays the currently spoken paragraph.
 * `highlight` is a bbox [x0, y0, x1, y1] in PDF points (top-left origin), exactly as stored by the backend.
 */
export default function PdfViewer({ data, page, zoom, highlight, onPageCount }) {
  const canvasRef = useRef(null);
  const wrapRef = useRef(null);
  const [doc, setDoc] = useState(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [error, setError] = useState(null);
  const [rendering, setRendering] = useState(false);

  useEffect(() => {
    if (!data) return undefined;
    let cancelled = false;
    const task = pdfjsLib.getDocument({ data: new Uint8Array(data.slice(0)) });
    task.promise.then((d) => { if (!cancelled) { setDoc(d); onPageCount?.(d.numPages); } })
      .catch((e) => !cancelled && setError(e.message));
    return () => { cancelled = true; task.destroy(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  useEffect(() => {
    if (!doc || !page) return undefined;
    let cancelled = false;
    let renderTask;
    setRendering(true);
    doc.getPage(page).then((p) => {
      if (cancelled) return;
      const viewport = p.getViewport({ scale: zoom });
      const dpr = window.devicePixelRatio || 1;
      const canvas = canvasRef.current;
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      setSize({ w: viewport.width, h: viewport.height });
      renderTask = p.render({ canvasContext: canvas.getContext('2d'), viewport, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null });
      return renderTask.promise;
    }).catch((e) => { if (e?.name !== 'RenderingCancelledException' && !cancelled) setError(e.message); })
      .finally(() => !cancelled && setRendering(false));
    return () => { cancelled = true; renderTask?.cancel(); };
  }, [doc, page, zoom]);

  // keep the highlighted paragraph visible
  useEffect(() => {
    if (!highlight || !wrapRef.current) return;
    const top = highlight[1] * zoom;
    const el = wrapRef.current;
    if (top < el.scrollTop + 40 || top > el.scrollTop + el.clientHeight - 120) el.scrollTo({ top: Math.max(0, top - 80), behavior: 'smooth' });
  }, [highlight, zoom]);

  if (error) return <div className="p-6 text-sm text-red-600">Could not display the PDF: {error}</div>;

  return (
    <div ref={wrapRef} className="relative h-[70vh] overflow-auto rounded-lg border border-slate-200 bg-slate-100 p-4 dark:border-slate-800 dark:bg-slate-900">
      {(!doc || rendering) && <div className="absolute right-4 top-4 z-10 rounded bg-white/80 px-2 py-1 text-xs dark:bg-slate-800"><span className="spinner" /> Loading…</div>}
      <div className="relative mx-auto shadow-lg" style={{ width: size.w || undefined, height: size.h || undefined }}>
        <canvas ref={canvasRef} className="block bg-white" />
        {highlight && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute rounded-sm bg-yellow-300/40 ring-2 ring-yellow-400 transition-all duration-150"
            style={{ left: highlight[0] * zoom - 3, top: highlight[1] * zoom - 3, width: (highlight[2] - highlight[0]) * zoom + 6, height: (highlight[3] - highlight[1]) * zoom + 6 }}
          />
        )}
      </div>
    </div>
  );
}
