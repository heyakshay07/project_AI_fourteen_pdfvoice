import { useEffect, useMemo, useState } from 'react';
import { voice, errorMessage } from '../services/api';
import { useToast } from '../context/ToastContext';

export const SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2];

export default function VoiceSettings({ onChange, documentId, compact = false }) {
  const toast = useToast();
  const [catalog, setCatalog] = useState(null);
  const [s, setS] = useState(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    Promise.all([voice.available(), voice.getSettings()])
      .then(([cat, settings]) => { setCatalog(cat); setS(settings); onChange?.(settings); })
      .catch((e) => toast.error(errorMessage(e)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const engine = catalog?.engines.find((e) => e.engine === s?.voice_engine);
  const languages = useMemo(() => catalog?.languages || [], [catalog]);
  const voices = useMemo(() => (engine ? engine.voices.filter((v) => v.language === s.language) : []), [engine, s]);

  async function save(next) {
    const prev = s;
    setS(next);
    try {
      const saved = await voice.putSettings(next);
      setS(saved);
      onChange?.(saved);
    } catch (e) {
      setS(prev);
      toast.error(errorMessage(e));
    }
  }

  function changeEngine(name) {
    const e = catalog.engines.find((x) => x.engine === name);
    const v = e.voices.find((x) => x.language === s.language) || e.voices[0];
    save({ ...s, voice_engine: name, voice_name: v.id, language: v.language });
  }

  function changeLanguage(lang) {
    let e = engine;
    let v = e.voices.find((x) => x.language === lang);
    if (!v) { // current engine has no voice for this language (e.g. Kokoro has no Marathi): switch engine
      e = catalog.engines.find((x) => x.available && x.voices.some((y) => y.language === lang));
      if (!e) return toast.error('No installed engine supports that language.');
      v = e.voices.find((x) => x.language === lang);
      toast.info(`Switched to ${e.label} for this language.`);
    }
    save({ ...s, voice_engine: e.engine, voice_name: v.id, language: lang });
  }

  async function pregenerate() {
    setGenerating(true);
    try { await voice.generate(documentId); toast.success('Generating audio in the background. Playback will start faster.'); }
    catch (e) { toast.error(errorMessage(e)); }
    finally { setGenerating(false); }
  }

  if (!catalog || !s) return <div className="card text-sm text-slate-500"><span className="spinner" /> Loading voices…</div>;

  return (
    <div className="card space-y-3">
      {!compact && <h2 className="font-semibold">Voice settings</h2>}
      <div>
        <label className="label" htmlFor="engine">Engine</label>
        <select id="engine" className="input" value={s.voice_engine} onChange={(e) => changeEngine(e.target.value)}>
          {catalog.engines.map((e) => (
            <option key={e.engine} value={e.engine} disabled={!e.available}>{e.label}{e.available ? '' : ' — not installed'}</option>
          ))}
        </select>
        {engine && !engine.available && <p className="mt-1 text-xs text-red-600">{engine.reason}</p>}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label" htmlFor="language">Language</label>
          <select id="language" className="input" value={s.language} onChange={(e) => changeLanguage(e.target.value)}>
            {languages.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="voice">Voice</label>
          <select id="voice" className="input" value={s.voice_name} onChange={(e) => save({ ...s, voice_name: e.target.value })}>
            {voices.map((v) => <option key={v.id + v.name} value={v.id}>{v.name} · {v.gender}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="label" htmlFor="speed">Speaking speed</label>
        <select id="speed" className="input" value={s.speaking_speed} onChange={(e) => save({ ...s, speaking_speed: Number(e.target.value) })}>
          {SPEEDS.map((x) => <option key={x} value={x}>{x}×</option>)}
        </select>
      </div>
      {documentId && (
        <button className="btn-ghost w-full" onClick={pregenerate} disabled={generating || !engine?.available}>
          {generating ? <span className="spinner" /> : '⚙'} Pre-generate all audio
        </button>
      )}
    </div>
  );
}
