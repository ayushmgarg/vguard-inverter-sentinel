import { useState } from 'react';
import VillageTab, { makeVillage } from './village/VillageTab.jsx';
import { useOnce, useTicker, useWorldLoop } from './sim/tick.js';
import * as engine from './sim/engine.js';
import { fmtClock } from './sim/engine.js';
import { Icon } from './ui/bits.jsx';
import InverterTab, { makeBench } from './inverter/InverterTab.jsx';
import TheoryTab from './theory/TheoryTab.jsx';

const hide = (h) => (h ? { visibility: 'hidden', pointerEvents: 'none', zIndex: 0 } : { visibility: 'visible', zIndex: 1 });

const TABS = [
  { id: 'village', label: 'Village Live', icon: 'house' },
  { id: 'inverter', label: 'Inverter + Sentinel', icon: 'chip' },
  { id: 'theory', label: 'Engineering', icon: 'shield' },
];

function Clock({ world }) {
  useTicker(world.bus);
  const on = world.grid.present;
  return (
    <div className="clock">
      <div className={`grid-pill ${on ? 'on' : 'off'}`}><span className="dot" />{on ? 'MAINS' : 'OUTAGE'}</div>
      <div className="clock-t">{fmtClock(world.t)}</div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState(() => {
    try { return localStorage.getItem('sentinel.tab') || 'village'; } catch { return 'village'; }
  });
  const village = useOnce(makeVillage);
  const bench = useOnce(makeBench);
  if (typeof window !== 'undefined') window.__sentinel = { village, bench, engine };
  useWorldLoop(village, village.bus, { maxStep: 1, enabled: tab === 'village' });
  useWorldLoop(bench, bench.bus, { maxStep: 0.004, uiHz: 12, enabled: tab === 'inverter' });

  const go = (id) => {
    setTab(id);
    try { localStorage.setItem('sentinel.tab', id); } catch { /* storage blocked */ }
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" />
          <div>
            <div className="brand-name">V-GUARD <b>SENTINEL</b></div>
            <div className="brand-sub">Big Idea Tech 2026 · Team Codey Tingle</div>
          </div>
        </div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button key={t.id} className={`tab ${tab === t.id ? 'on' : ''}`} onClick={() => go(t.id)}>
              <Icon name={t.icon} size={15} /> {t.label}
            </button>
          ))}
        </nav>
        {tab === 'village' && <Clock world={village} />}
        {tab === 'inverter' && <Clock world={bench} />}
        {tab === 'theory' && <div className="clock" />}
      </header>
      <main className="stage">
        <div className="tab-host" style={hide(tab !== 'village')}>
          <VillageTab world={village} active={tab === 'village'} />
        </div>
        <div className="tab-host" style={hide(tab !== 'inverter')}>
          <InverterTab world={bench} active={tab === 'inverter'} />
        </div>
        {tab === 'theory' && <div className="tab-host scroll"><TheoryTab /></div>}
      </main>
    </div>
  );
}
