import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { playback, history, voice } from '../services/api';

const PREFETCH_AHEAD = 2;

/**
 * Sentence-synchronised audio playback.
 *
 * The server splits each page into chunks (segments). For every segment it returns the audio file plus
 * per-sentence timings, so the highlighted sentence is derived from audio.currentTime.
 * Segments are fetched through axios (so the JWT is sent) and played from blob URLs; the next segments
 * are prefetched so playback continues without gaps.
 */
export default function useAudioPlayer({ documentId, segments, voiceKey, initialPosition, onError }) {
  const audioRef = useRef(null);
  if (audioRef.current === null && typeof Audio !== 'undefined') audioRef.current = new Audio();

  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [position, setPosition] = useState(initialPosition || { page: 1, sentence: 0 });
  const [segIndex, setSegIndex] = useState(-1);
  const [time, setTime] = useState({ current: 0, duration: 0 });
  const [speed, setSpeedState] = useState(1);
  const [volume, setVolumeState] = useState(1);

  const cache = useRef(new Map()); // segId -> Promise<{meta, url}>
  const timings = useRef([]);
  const segIdxRef = useRef(-1);
  const posRef = useRef(position);
  const resumeAt = useRef(null); // {idx, sentence} used when seeking while paused
  const playToken = useRef(0); // invalidates stale async loads
  const saveTimer = useRef(null);
  const raf = useRef(0);
  const speedRef = useRef(1);
  const playingRef = useRef(false);
  const shouldContinue = useRef(false);

  const segs = segments || [];
  const segsRef = useRef(segs);
  segsRef.current = segs;
  const report = useCallback((e) => onError?.(e), [onError]);

  const setPos = useCallback((p) => { posRef.current = p; setPosition(p); }, []);
  const setPlayingBoth = (v) => { playingRef.current = v; setPlaying(v); };

  const findSegIndex = useCallback((page, sentence) => {
    return segsRef.current.findIndex((s) => s.page_number === page && sentence >= s.sentence_start && sentence <= s.sentence_end);
  }, []);

  // ---------------------------------------------------------------- loading & cache
  const load = useCallback((idx) => {
    const seg = segsRef.current[idx];
    if (!seg) return Promise.resolve(null);
    if (!cache.current.has(seg.id)) {
      const p = (async () => {
        const meta = await voice.segmentDetail(documentId, seg.id); // generates audio on first request
        const url = await voice.audio(documentId, seg.id);
        return { meta, url };
      })();
      p.catch(() => cache.current.delete(seg.id)); // allow a retry after failure
      cache.current.set(seg.id, p);
    }
    return cache.current.get(seg.id);
  }, [documentId]);

  const prefetch = useCallback((idx) => {
    for (let k = 1; k <= PREFETCH_AHEAD; k += 1) load(idx + k)?.catch?.(() => {});
    // free blob URLs for segments we've moved well past
    segsRef.current.forEach((s, i) => {
      if (i < idx - 2 && cache.current.has(s.id)) {
        cache.current.get(s.id).then((v) => v && URL.revokeObjectURL(v.url)).catch(() => {});
        cache.current.delete(s.id);
      }
    });
  }, [load]);

  const clearCache = useCallback(() => {
    cache.current.forEach((p) => p.then((v) => v && URL.revokeObjectURL(v.url)).catch(() => {}));
    cache.current.clear();
  }, []);

  // ---------------------------------------------------------------- progress persistence
  const saveSoon = useCallback((page, sentence) => {
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => history.saveProgress(documentId, page, sentence).catch(() => {}), 2500);
  }, [documentId]);

  const sync = useCallback((action, extra = {}) => {
    const { page, sentence } = posRef.current;
    return playback.send(action, { document_id: documentId, page, sentence, ...extra }).catch(() => {});
  }, [documentId]);

  // ---------------------------------------------------------------- highlight loop
  const stopLoop = () => cancelAnimationFrame(raf.current);
  const startLoop = useCallback(() => {
    stopLoop();
    const tick = () => {
      const a = audioRef.current;
      const seg = segsRef.current[segIdxRef.current];
      if (a && seg && timings.current.length) {
        const t = a.currentTime + 0.02;
        let cur = timings.current[0];
        for (const x of timings.current) { if (x.start <= t) cur = x; else break; }
        if (cur.sentence !== posRef.current.sentence || seg.page_number !== posRef.current.page) {
          setPos({ page: seg.page_number, sentence: cur.sentence });
          saveSoon(seg.page_number, cur.sentence);
        }
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
  }, [saveSoon, setPos]);

  // ---------------------------------------------------------------- core: play a segment
  const playSegment = useCallback(async (idx, startSentence = null) => {
    const a = audioRef.current;
    const seg = segsRef.current[idx];
    if (!a || !seg) return false;
    const token = ++playToken.current;
    setLoading(true);
    try {
      const { meta, url } = await load(idx);
      if (token !== playToken.current) return false; // superseded by a newer request
      segIdxRef.current = idx;
      setSegIndex(idx);
      timings.current = meta.timings;
      const target = startSentence ?? seg.sentence_start;
      const t = meta.timings.find((x) => x.sentence === target)?.start ?? 0;
      a.src = url;
      a.playbackRate = speedRef.current;
      await new Promise((resolve, reject) => {
        a.onloadedmetadata = () => { a.currentTime = t; resolve(); };
        a.onerror = () => reject(new Error('Audio could not be decoded'));
      });
      if (token !== playToken.current) return false;
      setPos({ page: seg.page_number, sentence: target });
      if (!shouldContinue.current) return false;
      await a.play();
      setPlayingBoth(true);
      startLoop();
      prefetch(idx);
      return true;
    } catch (e) {
      if (token === playToken.current) {
        shouldContinue.current = false;
        setPlayingBoth(false);
        report(e);
      }
      return false;
    } finally {
      if (token === playToken.current) setLoading(false);
    }
  }, [load, prefetch, report, setPos, startLoop]);

  // ---------------------------------------------------------------- audio element events
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return undefined;
    const onTime = () => setTime({ current: a.currentTime, duration: a.duration || 0 });
    const onEnded = async () => {
      if (!shouldContinue.current) return;
      const next = segIdxRef.current + 1;
      if (next < segsRef.current.length) {
        await playSegment(next);
      } else {
        shouldContinue.current = false;
        stopLoop();
        setPlayingBoth(false);
        const last = segsRef.current[segsRef.current.length - 1];
        if (last) { history.saveProgress(documentId, last.page_number, last.sentence_end).catch(() => {}); }
      }
    };
    a.addEventListener('timeupdate', onTime);
    a.addEventListener('ended', onEnded);
    return () => { a.removeEventListener('timeupdate', onTime); a.removeEventListener('ended', onEnded); };
  }, [documentId, playSegment]);

  // ---------------------------------------------------------------- public controls
  const play = useCallback(async () => {
    const a = audioRef.current;
    if (!a || !segsRef.current.length) return;
    shouldContinue.current = true;
    if (a.src && segIdxRef.current >= 0 && !resumeAt.current) {
      await a.play();
      setPlayingBoth(true);
      startLoop();
      sync('resume');
      return;
    }
    let idx; let sentence;
    if (resumeAt.current) {
      ({ idx, sentence } = resumeAt.current);
      resumeAt.current = null;
    } else {
      const st = await playback.start(documentId).catch(() => null); // resume from the saved position
      if (!shouldContinue.current) return;
      const p = st ? { page: st.page, sentence: st.sentence } : posRef.current;
      idx = findSegIndex(p.page, p.sentence);
      sentence = p.sentence;
      if (idx < 0) { idx = 0; sentence = segsRef.current[0].sentence_start; }
    }
    await playSegment(idx, sentence);
  }, [documentId, findSegIndex, playSegment, startLoop, sync]);

  const pause = useCallback(() => {
    shouldContinue.current = false;
    audioRef.current?.pause();
    stopLoop();
    setPlayingBoth(false);
    clearTimeout(saveTimer.current);
    sync('pause', { position_seconds: audioRef.current?.currentTime });
  }, [sync]);

  const stop = useCallback(() => {
    shouldContinue.current = false;
    const a = audioRef.current;
    if (a) { a.pause(); a.currentTime = 0; }
    stopLoop();
    playToken.current += 1;
    setPlayingBoth(false);
    clearTimeout(saveTimer.current);
    sync('stop');
  }, [sync]);

  const seekTo = useCallback(async (page, sentence) => {
    const idx = findSegIndex(page, sentence);
    if (idx < 0) return;
    const seg = segsRef.current[idx];
    if (idx === segIdxRef.current && audioRef.current?.src) {
      const t = timings.current.find((x) => x.sentence === sentence)?.start;
      if (t !== undefined) {
        audioRef.current.currentTime = t;
        setPos({ page, sentence });
        saveSoon(page, sentence);
        if (!playingRef.current) { resumeAt.current = null; }
        return;
      }
    }
    setPos({ page: seg.page_number, sentence });
    saveSoon(page, sentence);
    if (playingRef.current) await playSegment(idx, sentence);
    else resumeAt.current = { idx, sentence };
  }, [findSegIndex, playSegment, saveSoon, setPos]);

  const nextSentence = useCallback(() => {
    const idx = segIdxRef.current >= 0 ? segIdxRef.current : findSegIndex(posRef.current.page, posRef.current.sentence);
    const seg = segsRef.current[idx];
    if (!seg) return;
    const { sentence } = posRef.current;
    if (sentence < seg.sentence_end) seekTo(seg.page_number, sentence + 1);
    else if (segsRef.current[idx + 1]) seekTo(segsRef.current[idx + 1].page_number, segsRef.current[idx + 1].sentence_start);
  }, [findSegIndex, seekTo]);

  const prevSentence = useCallback(() => {
    const idx = segIdxRef.current >= 0 ? segIdxRef.current : findSegIndex(posRef.current.page, posRef.current.sentence);
    const seg = segsRef.current[idx];
    if (!seg) return;
    const { sentence } = posRef.current;
    const start = timings.current.find((x) => x.sentence === sentence)?.start ?? 0;
    const restart = audioRef.current && audioRef.current.currentTime - start > 1.2;
    if (restart || (sentence === seg.sentence_start && !segsRef.current[idx - 1])) seekTo(seg.page_number, sentence);
    else if (sentence > seg.sentence_start) seekTo(seg.page_number, sentence - 1);
    else { const p = segsRef.current[idx - 1]; seekTo(p.page_number, p.sentence_end); }
  }, [findSegIndex, seekTo]);

  const goToPage = useCallback((page) => {
    const s = segsRef.current.find((x) => x.page_number === page);
    if (s) seekTo(page, s.sentence_start);
  }, [seekTo]);

  const nextPage = useCallback(() => {
    const s = segsRef.current.find((x) => x.page_number > posRef.current.page);
    if (s) seekTo(s.page_number, s.sentence_start);
  }, [seekTo]);

  const prevPage = useCallback(() => {
    const earlier = segsRef.current.filter((x) => x.page_number < posRef.current.page);
    if (!earlier.length) return;
    const page = earlier[earlier.length - 1].page_number;
    goToPage(page);
  }, [goToPage]);

  const setSpeed = useCallback((v) => {
    speedRef.current = v;
    setSpeedState(v);
    if (audioRef.current) audioRef.current.playbackRate = v;
  }, []);

  const setVolume = useCallback((v) => {
    setVolumeState(v);
    if (audioRef.current) audioRef.current.volume = v;
  }, []);

  const seekWithinSegment = useCallback((seconds) => {
    if (audioRef.current) audioRef.current.currentTime = seconds;
  }, []);

  // ---------------------------------------------------------------- voice change / unmount
  const firstVoiceKey = useRef(voiceKey);
  useEffect(() => {
    if (firstVoiceKey.current === voiceKey) return;
    firstVoiceKey.current = voiceKey;
    // new voice: drop cached audio and restart the current sentence with the new voice
    const wasPlaying = playingRef.current;
    const { page, sentence } = posRef.current;
    audioRef.current?.pause();
    if (audioRef.current) audioRef.current.removeAttribute('src');
    stopLoop();
    playToken.current += 1;
    setPlayingBoth(false);
    clearCache();
    segIdxRef.current = -1;
    timings.current = [];
    const idx = findSegIndex(page, sentence);
    if (wasPlaying && idx >= 0) playSegment(idx, sentence);
    else if (idx >= 0) resumeAt.current = { idx, sentence };
  }, [voiceKey, clearCache, findSegIndex, playSegment]);

  useEffect(() => () => {
    shouldContinue.current = false;
    stopLoop();
    clearTimeout(saveTimer.current);
    const a = audioRef.current;
    if (a) { a.pause(); a.removeAttribute('src'); }
    const { page, sentence } = posRef.current;
    if (documentId) history.saveProgress(documentId, page, sentence).catch(() => {});
    clearCache();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  const totalPages = useMemo(() => (segs.length ? Math.max(...segs.map((s) => s.page_number)) : 0), [segs]);

  return {
    playing, loading, position, segIndex, time, speed, volume, totalPages,
    play, pause, stop, seekTo, nextSentence, prevSentence, nextPage, prevPage, goToPage,
    setSpeed, setVolume, seekWithinSegment, setPosition: setPos,
  };
}
