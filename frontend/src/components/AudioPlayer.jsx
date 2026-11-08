import { SPEEDS } from './VoiceSettings';
import { formatTime } from '../utils/format';

const Btn = ({ label, onClick, disabled, children, primary }) => (
  <button className={primary ? 'btn-primary h-12 w-12 rounded-full text-lg' : 'btn-ghost h-10 w-10 !px-0'} onClick={onClick} disabled={disabled} aria-label={label} title={label}>
    {children}
  </button>
);

export default function AudioPlayer({ player, totalPages, readingPct, disabled, currentSentenceText }) {
  const { playing, loading, position, time, speed, volume } = player;
  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">Page {position.page} <span className="text-slate-500">of {totalPages}</span></span>
        <span className="text-slate-500">{Math.round(readingPct)}% read</span>
      </div>
      <p className="-mt-3 text-xs text-slate-500">Keeps reading page by page until the PDF ends or you stop playback.</p>
      <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700" role="progressbar" aria-label="Reading progress" aria-valuenow={Math.round(readingPct)} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full bg-brand-600 transition-all" style={{ width: `${readingPct}%` }} />
      </div>

      <div className="min-h-[3.5rem] rounded-lg bg-slate-50 p-3 text-sm italic text-slate-600 dark:bg-slate-800/50 dark:text-slate-300" aria-live="off">
        {currentSentenceText || 'Press play to start reading.'}
      </div>

      <div className="flex items-center justify-center gap-1.5">
        <Btn label="Previous page" onClick={player.prevPage} disabled={disabled}>⏮</Btn>
        <Btn label="Previous sentence" onClick={player.prevSentence} disabled={disabled}>⏪</Btn>
        {playing
          ? <Btn primary label="Pause" onClick={player.pause}>⏸</Btn>
          : <Btn primary label="Play" onClick={player.play} disabled={disabled || loading}>{loading ? <span className="spinner" /> : '▶'}</Btn>}
        <Btn label="Stop" onClick={player.stop} disabled={disabled}>⏹</Btn>
        <Btn label="Next sentence" onClick={player.nextSentence} disabled={disabled}>⏩</Btn>
        <Btn label="Next page" onClick={player.nextPage} disabled={disabled}>⏭</Btn>
      </div>

      <div>
        <input type="range" min={0} max={time.duration || 1} step={0.1} value={Math.min(time.current, time.duration || 1)}
          onChange={(e) => player.seekWithinSegment(Number(e.target.value))} className="w-full accent-brand-600" aria-label="Audio position in current section" disabled={disabled} />
        <div className="flex justify-between text-xs text-slate-500"><span>{formatTime(time.current)}</span><span>{formatTime(time.duration)}</span></div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label" htmlFor="pb-speed">Playback speed</label>
          <select id="pb-speed" className="input" value={speed} onChange={(e) => player.setSpeed(Number(e.target.value))}>
            {SPEEDS.map((x) => <option key={x} value={x}>{x}×</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="volume">Volume</label>
          <input id="volume" type="range" min={0} max={1} step={0.05} value={volume} onChange={(e) => player.setVolume(Number(e.target.value))} className="mt-2 w-full accent-brand-600" />
        </div>
      </div>
    </div>
  );
}
