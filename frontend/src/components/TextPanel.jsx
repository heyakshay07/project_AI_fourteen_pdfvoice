import { useEffect, useRef } from 'react';

export default function TextPanel({ pageData, activeSentence, onSelect }) {
  const activeRef = useRef(null);
  useEffect(() => { activeRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }); }, [activeSentence, pageData?.page_number]);

  if (!pageData) return <div className="p-6 text-sm text-slate-500"><span className="spinner" /> Loading page text…</div>;

  const warn = pageData.validation_status !== 'ok';
  return (
    <div className="h-[70vh] overflow-auto rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="badge bg-slate-100 dark:bg-slate-800">Extracted by {pageData.extraction_method === 'ocr' ? 'OCR' : pageData.extraction_method === 'text' ? 'text layer' : 'n/a'}</span>
        {warn && <span className="badge bg-amber-100 text-amber-800">Validation: {pageData.validation_status}</span>}
      </div>
      {warn && pageData.validation_notes?.length > 0 && (
        <ul className="mb-4 list-disc space-y-1 rounded-lg bg-amber-50 p-3 pl-7 text-xs text-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
          {pageData.validation_notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
      {pageData.sentences.length === 0 && <p className="text-sm text-slate-500">No readable text was found on this page.</p>}
      <p className="leading-8">
        {pageData.sentences.map((s) => (
          <span key={s.i}>
            <span
              ref={s.i === activeSentence ? activeRef : null}
              onClick={() => onSelect(s.i)}
              className={`cursor-pointer rounded px-0.5 hover:bg-slate-100 dark:hover:bg-slate-800 ${s.heading ? 'text-lg font-semibold' : ''} ${s.i === activeSentence ? 'sentence-active' : ''}`}
            >
              {s.text}
            </span>
            {s.para_end ? <><br /><br /></> : ' '}
          </span>
        ))}
      </p>
    </div>
  );
}
