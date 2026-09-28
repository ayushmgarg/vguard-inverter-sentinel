import { useSyncExternalStore, useEffect, useRef, useState } from 'react';
import { step } from './engine.js';

// tiny external store: UI components re-render at ~8 Hz while the 3D scene reads the world every frame
export function makeTicker() {
  let n = 0;
  const ls = new Set();
  return {
    emit() { n++; ls.forEach((l) => l()); },
    sub(l) { ls.add(l); return () => ls.delete(l); },
    get() { return n; },
  };
}

export function useTicker(ticker) {
  return useSyncExternalStore(ticker.sub, ticker.get, ticker.get);
}

// drives a world with requestAnimationFrame
export function useWorldLoop(world, ticker, { maxStep = 1, uiHz = 8, enabled = true } = {}) {
  useEffect(() => {
    if (!enabled) return undefined;
    let raf;
    let last = performance.now();
    let lastUi = 0;
    const loop = (now) => {
      const realDt = Math.min((now - last) / 1000, 0.1);
      last = now;
      if (!world.paused) {
        const simDt = realDt * world.speed * (world.slowmo ?? 1);
        if (simDt > 0) {
          const ms = world.maxStep ?? maxStep;
          const n = Math.min(4000, Math.ceil(simDt / ms));
          const d = simDt / n;
          for (let i = 0; i < n; i++) step(world, d);
        }
        if (world.onFrame) world.onFrame(realDt);
      }
      if (now - lastUi > 1000 / uiHz) { lastUi = now; ticker.emit(); }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [world, ticker, maxStep, uiHz, enabled]);
}

export function useOnce(fn) {
  const r = useRef(null);
  if (r.current === null) r.current = fn();
  return r.current;
}

export function useForce() {
  const [, s] = useState(0);
  return () => s((x) => x + 1);
}
