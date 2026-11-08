import { Link } from 'react-router-dom';
import { formatBytes, timeAgo } from '../utils/format';

const STATUS = {
  uploaded: ['Not processed', 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'],
  queued: ['Queued', 'bg-amber-100 text-amber-700'],
  processing: ['Processing', 'bg-amber-100 text-amber-700'],
  completed: ['Ready', 'bg-emerald-100 text-emerald-700'],
  failed: ['Failed', 'bg-red-100 text-red-700'],
};

export default function DocumentCard({ item, onDelete, onClearHistory }) {
  const [label, cls] = STATUS[item.processing_status] || STATUS.uploaded;
  const pct = Math.round(item.progress_percentage || 0);
  const started = item.current_page != null;
  return (
    <div className="card flex flex-col gap-3 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Link to={`/read/${item.document_id}`} className="truncate font-medium hover:text-brand-600">{item.filename}</Link>
          <span className={`badge ${cls}`}>{label}</span>
        </div>
        <p className="mt-0.5 text-xs text-slate-500">
          {item.total_pages} pages{item.file_size ? ` · ${formatBytes(item.file_size)}` : ''}
          {item.last_read_at ? ` · read ${timeAgo(item.last_read_at)}` : ` · added ${timeAgo(item.created_at)}`}
          {started && item.processing_status === 'completed' ? ` · stopped on page ${item.current_page}` : ''}
        </p>
        {item.processing_status === 'completed' && (
          <div className="mt-2 flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full bg-brand-600" style={{ width: `${pct}%` }} />
            </div>
            <span className="w-10 text-right text-xs text-slate-500">{pct}%</span>
          </div>
        )}
      </div>
      <div className="flex shrink-0 gap-2">
        <Link to={`/read/${item.document_id}`} className="btn-primary">{started && item.processing_status === 'completed' ? 'Continue' : 'Open'}</Link>
        {started && <button className="btn-ghost" onClick={() => onClearHistory(item)} title="Reset reading progress">Reset</button>}
        <button className="btn-danger" onClick={() => onDelete(item)} aria-label={`Delete ${item.filename}`}>Delete</button>
      </div>
    </div>
  );
}
