import { useEffect, useRef, useState, Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { EffectComposer, Bloom, Vignette, ToneMapping } from '@react-three/postprocessing';
import { ToneMappingMode } from 'postprocessing';
import BenchScene from './BenchScene.jsx';
import { PartCtx } from './Part.jsx';
import { PARTS } from './parts.js';
import { makeTicker, useTicker } from '../sim/tick.js';
import {
  createWorld, setGrid, resetMcu, hangMcu, injectSag, evaluate, forceAppliance, outputLive, setpoints, gradeOf,
} from '../sim/engine.js';
import { sha256hex } from '../sim/sha256.js';
import { P, GRADES, TIER_META } from '../sim/params.js';
import { Icon, Ring, Pill, fmt, STATE_TEXT } from '../ui/bits.jsx';

// ---------- bench world: one V-Guard-class inverter with Sentinel-Embedded (prototype/05 Tier 0 loads) ----------
export function makeBench() {
  const cfg = {
    id: 'bench', name: 'Bench', short: 'Bench', sentinel: true, sku: 'embedded',
    ah: 150, soh: 0.93, gradeIdx: 1, soc0: 0.78, temp0: 31, ambient: 31, pos: [0, 0, 0], rot: 0,
    circuits: {
      ch1: { tier: 'T1', label: 'Lamp + router', locked: true },
      ch2: { tier: 'T2', label: 'Table fan' },
      ch3: { tier: 'T3', label: 'Iron' },
      ch4: { tier: 'MED', label: 'CPAP', locked: true },
    },
    appliances: [
      { id: 'bulb', kind: 'bulb', name: 'LED bulb', circuit: 'ch1', sched: 'always' },
      { id: 'router', kind: 'router', circuit: 'ch1', sched: 'always' },
      { id: 'fan', kind: 'fan', name: 'Table fan', w: 50, q: 25, circuit: 'ch2', sched: 'always' },
      { id: 'iron', kind: 'iron', circuit: 'ch3', sched: 'always' },
      { id: 'cpap', kind: 'cpap', circuit: 'ch4', sched: 'always' },
    ],
  };
  const w = createWorld({ houses: [cfg], t0: 19 * 3600, outages: [], speed: 1 });
  const h = w.houses[0];
  w.grid.manual = 'on';
  h.appliances.find((a) => a.id === 'iron').forced = false;
  h.histEvery = 1;
  w.bus = makeTicker();
  w.slowmo = 1;
  w.scope = { seg: [{ t: w.t, live: true, src: 'mains', amp: 325 }], ibat: [], events: [], ref: null };
  const prev = { grid: true, state: 'S1', outage: false, coils: '' };
  const ev = (text, kind = 'info') => {
    w.scope.events.unshift({ t: w.t, text, kind });
    if (w.scope.events.length > 14) w.scope.events.pop();
  };
  w.onStep = () => {
    const g = w.grid;
    if (prev.grid !== g.present) {
      w.scope.ref = w.t;
      ev(g.present ? 'Mains restored (MCB closed)' : 'Mains lost (MCB open)', g.present ? 'good' : 'bad');
      w.slowmo = 1 / 60;
      w.slowUntil = w.t + 0.05;
      prev.grid = g.present;
    }
    if (prev.state !== h.inv.state) {
      const s = h.inv.state;
      if (s === 'S2') ev('Inverter: S2 transfer — relay I2 moving', 'warn');
      if (s === 'S3') ev('Inverter: S3 battery mode — relay on bridge', 'batt');
      if (s === 'S4') ev('Inverter: S4 low-battery cut-off', 'bad');
      if (s === 'S6') ev('Inverter: S6 mains stable check (5 s)', 'info');
      if (s === 'S1') ev('Inverter: S1 pass-through — charger bulk', 'good');
      prev.state = s;
    }
    if (prev.outage !== h.sen.outage) {
      if (h.sen.outage) {
        const v = ['s1', h.sen.votes.s2 && 's2', h.sen.votes.s3 && 's3'].filter(Boolean).join('+');
        ev(`Sentinel: outage confirmed (${v})`, 'warn');
      } else ev('Sentinel: restore confirmed (> 0.9 pu, 15 s)', 'good');
      prev.outage = h.sen.outage;
    }
    const cs = JSON.stringify(h.coils || {});
    if (cs !== prev.coils) {
      const was = prev.coils ? JSON.parse(prev.coils) : {};
      for (const [ch, on] of Object.entries(h.coils || {})) {
        if (!!was[ch] !== on) ev(`${ch.toUpperCase()} coil ${on ? 'energised → circuit OPEN (shed)' : 'released → circuit CLOSED (load on)'}`, on ? 'shed' : 'good');
      }
      prev.coils = cs;
    }
    // scope segments (AC-OUT source / amplitude)
    const live = outputLive(h) && h.inv.state !== 'S2';
    const src = h.inv.state === 'S1' ? 'mains' : 'bridge';
    const amp = src === 'mains' ? g.v * Math.SQRT2 : 230 * Math.SQRT2;
    const last = w.scope.seg[w.scope.seg.length - 1];
    if (last.live !== live || last.src !== src || Math.abs(last.amp - amp) > 8) {
      w.scope.seg.push({ t: w.t, live, src, amp });
      if (w.scope.seg.length > 400) w.scope.seg.shift();
    }
    const ib = w.scope.ibat;
    if (!ib.length || w.t - ib[ib.length - 1].t >= 0.05) {
      ib.push({ t: w.t, i: h.bat.i });
      if (ib.length > 1200) ib.shift();
    }
  };
  w.onFrame = () => {
    if (w.slowmo < 1 && w.t > w.slowUntil) w.slowmo = Math.min(1, w.slowmo * 1.07);
  };
  return w;
}

// ---------- scope ----------
function Scope({ world }) {
  const cv = useRef();
  useEffect(() => {
    let raf;
    const draw = () => {
      const c = cv.current;
      if (c) {
        const g = c.getContext('2d');
        const W = c.width, H = c.height;
        g.clearRect(0, 0, W, H);
        const hv = H * 0.62;
        // grid
        g.strokeStyle = 'rgba(255,255,255,0.06)';
        g.lineWidth = 1;
        for (let i = 0; i <= 10; i++) { g.beginPath(); g.moveTo((i / 10) * W, 0); g.lineTo((i / 10) * W, hv); g.stroke(); }
        for (let i = 0; i <= 4; i++) { g.beginPath(); g.moveTo(0, (i / 4) * hv); g.lineTo(W, (i / 4) * hv); g.stroke(); }
        const segs = world.scope.seg;
        const tEnd = world.t, win = 0.1;
        const N = 700;
        let si = segs.length - 1;
        const pts = [];
        for (let k = N; k >= 0; k--) {
          const ts = tEnd - (win * (N - k)) / N;
          while (si > 0 && segs[si].t > ts) si--;
          const s = segs[si];
          const v = s.live ? s.amp * Math.sin(2 * Math.PI * 50 * ts) : 0;
          pts.push({ x: (k / N) * W, y: hv / 2 - (v / 420) * (hv / 2), c: !s.live ? '#FF4D6D' : s.src === 'mains' ? '#FDC300' : '#22D3EE' });
        }
        pts.reverse();
        g.lineWidth = 2;
        for (let k = 1; k < pts.length; k++) {
          g.strokeStyle = pts[k].c;
          g.beginPath(); g.moveTo(pts[k - 1].x, pts[k - 1].y); g.lineTo(pts[k].x, pts[k].y); g.stroke();
        }
        g.fillStyle = 'rgba(255,255,255,0.5)';
        g.font = '10px JetBrains Mono, monospace';
        g.fillText('AC-OUT · 10 ms/div', 6, 12);
        if ((world.slowmo ?? 1) < 0.99) {
          g.fillStyle = '#FDC300';
          g.fillText(`SLOW-MO ×${(1 / world.slowmo).toFixed(0)}`, W - 90, 12);
        }
        // battery current trend (30 s)
        const ib = world.scope.ibat;
        const y0 = hv + 8, hh = H - y0 - 4;
        g.strokeStyle = 'rgba(255,255,255,0.08)';
        g.beginPath(); g.moveTo(0, y0 + hh / 2); g.lineTo(W, y0 + hh / 2); g.stroke();
        g.lineWidth = 1.6;
        g.beginPath();
        let first = true;
        for (const p of ib) {
          const x = W - ((tEnd - p.t) / 30) * W;
          if (x < 0) continue;
          const y = y0 + hh / 2 - (p.i / 60) * (hh / 2);
          if (first) { g.moveTo(x, y); first = false; } else g.lineTo(x, y);
        }
        const li = ib.length ? ib[ib.length - 1].i : 0;
        g.strokeStyle = li < 0 ? '#22D3EE' : '#FDC300';
        g.stroke();
        g.fillStyle = 'rgba(255,255,255,0.5)';
        g.fillText('I_batt · 30 s', 6, y0 + 10);
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [world]);
  return <canvas ref={cv} width={620} height={170} className="scope-cv" />;
}

function verifyChain(chain, id) {
  // oldest → newest
  const list = [...chain].reverse();
  for (let i = 0; i < list.length; i++) {
    const r = list[i];
    const hash = sha256hex(`${Math.round(r.t * 1000)}|${id}|${r.msg}|${r.prev}`);
    if (hash !== r.hash) return { ok: false, at: list.length - 1 - i };
    if (i > 0 && r.prev !== list[i - 1].hash) return { ok: false, at: list.length - 1 - i };
  }
  return { ok: true };
}

const STATES = ['S1', 'S2', 'S3', 'S4', 'S6'];

function LivePanel({ world }) {
  useTicker(world.bus);
  const h = world.houses[0];
  const b = h.bat, s = h.sen;
  const sp = setpoints(h);
  const g = gradeOf(h);
  const [verify, setVerify] = useState(null);
  const tampered = useRef(null);
  const rel = (t) => (world.scope.ref != null ? `${((t - world.scope.ref) * 1000).toFixed(t - world.scope.ref < 10 ? 1 : 0)} ms` : '');
  return (
    <aside className="panel bench-live">
      <div className="sm-row">
        {STATES.map((x) => (
          <div key={x} className={`sm ${h.inv.state === x ? 'on' : ''} sm-${x}`} title={STATE_TEXT[x]}>
            <b>{x}</b><span>{STATE_TEXT[x].split(' ·')[0].split(' (')[0]}</span>
          </div>
        ))}
      </div>
      <div className="hp-live">
        <Ring value={b.soc} size={96} label={`${Math.round(b.soc * 100)}%`} sub="SoC · EKF" />
        <div className="hp-grid">
          <div><span>V_batt</span><b>{fmt.v(b.v)}</b></div>
          <div><span>I_batt</span><b style={{ color: b.i < 0 ? '#22D3EE' : b.i > 0.5 ? '#FDC300' : undefined }}>{fmt.a(b.i)}</b></div>
          <div><span>T_batt</span><b>{fmt.t(b.temp)}</b></div>
          <div><span>AC-OUT</span><b>{fmt.w(h.stats.pOut)}</b></div>
          <div className="wide"><span>Backup left</span><b>{h.inv.state === 'S3' ? fmt.h(h.stats.backupH) : h.inv.state === 'S4' ? 'cut-off' : 'on mains'}</b></div>
        </div>
      </div>

      <section>
        <div className="sec-title">Charger control · MCP4725 → SG3525 feedback</div>
        <div className="chg">
          <div><span>Stage</span><b>{h.inv.state === 'S1' ? b.stage : '—'}</b></div>
          <div><span>Absorption</span><b>{sp.abs.toFixed(2)} V</b>{sp.source === 'sentinel' && Math.abs(sp.abs - P.V_ABS) > 0.005 && <s>{P.V_ABS.toFixed(2)}</s>}</div>
          <div><span>Float</span><b>{sp.float.toFixed(2)} V</b>{sp.source === 'sentinel' && Math.abs(sp.float - P.V_FLOAT) > 0.005 && <s>{P.V_FLOAT.toFixed(2)}</s>}</div>
          <div><span>I limit</span><b>{sp.iMax.toFixed(1)} A</b>{sp.derate < 1 && <em>{Math.round(sp.derate * 100)}%</em>}</div>
        </div>
        <div className={`dac ${sp.source === 'sentinel' ? 'on' : 'off'}`}>
          {sp.source === 'sentinel' ? `DAC link active · temp-compensated −24 mV/°C from 25 °C${sp.derate < 1 ? ` · derating above ${P.DERATE_START} °C` : ''}` : 'Heartbeat lost → charger reverted to factory setpoints'}
        </div>
      </section>

      <section className="two">
        <div>
          <div className="sec-title">2-of-3 outage vote</div>
          <div className="votes">
            <Pill tone={s.votes.s1 ? 'warn' : s.votes.s1raw ? 'mid' : 'muted'}>s1 mains &lt; 0.1 pu {s.votes.s1raw && !s.votes.s1 ? `${s.s1Timer.toFixed(1)} s` : ''}</Pill>
            <Pill tone={s.votes.s2 ? 'warn' : 'muted'}>s2 mode pin (opto)</Pill>
            <Pill tone={s.votes.s3 ? 'warn' : 'muted'}>s3 discharge</Pill>
          </div>
          <div className={`vote-result ${s.outage ? 'on' : ''}`}>{!s.alive ? 'MCU OFFLINE' : s.outage ? `OUTAGE · detected in ${s.detectLatency?.toFixed(2)} s` : 'mains OK'}</div>
        </div>
        <div>
          <div className="sec-title">Contactors</div>
          {Object.entries(h.circuits).map(([ch, c]) => {
            const on = h.coils && h.coils[ch];
            return (
              <div key={ch} className="cont">
                <span className="circ-tier" style={{ background: TIER_META[c.tier].color }}>{c.tier}</span>
                <span>{ch.toUpperCase()}</span>
                <span className={`circ-st ${on ? 'shed' : 'on'}`}>{on ? 'OPEN' : 'CLOSED'}</span>
              </div>
            );
          })}
        </div>
      </section>

      <section>
        <div className="sec-title">SoH / RUL · int8 CNN × 3 seeds + conformal band</div>
        <div className="soh">
          <div className={`grade g-${g.grade.toLowerCase()}`}>{g.grade === 'REPLACE' ? `Replace within ${g.rul_p10} weeks (${g.rul_p10}–${g.rul_p90})` : g.grade}</div>
          <div className="soh-bar">
            <div className="soh-band" style={{ left: `${(g.soh_p10 - 50) * 2}%`, width: `${(g.soh_p90 - g.soh_p10) * 2}%` }} />
            <div className="soh-mid" style={{ left: `${(g.soh_p50 - 50) * 2}%` }} />
            <div className="soh-eol" style={{ left: `${(80 - 50) * 2}%` }} />
          </div>
          <div className="muted-s">SoH P50 {g.soh_p50}% [{g.soh_p10}–{g.soh_p90}] · RUL {g.rul_p10}–{g.rul_p90} wk · conf {g.confidence} · EoL 80%</div>
        </div>
      </section>

      <section>
        <div className="sec-title">Health log · SHA-256 chain · ATECC608 signs</div>
        <div className="log">
          {s.chain.slice(0, 5).map((r, i) => (
            <div key={r.hash} className={`log-row ${verify && !verify.ok && verify.at === i ? 'k-bad' : ''}`}>
              <span className="log-t">{rel(r.t) || ''}</span>
              <span className="log-m">{r.msg}</span>
              <span className="log-h">{r.hash.slice(0, 8)}</span>
            </div>
          ))}
        </div>
        <div className="actions" style={{ marginTop: 6 }}>
          <button className="btn" onClick={() => setVerify(verifyChain(s.chain, h.id))}>Verify chain</button>
          <button className="btn danger" disabled={!s.chain.length} onClick={() => {
            const r = s.chain[Math.min(1, s.chain.length - 1)];
            if (!tampered.current) { tampered.current = { r, msg: r.msg }; r.msg = r.msg.replace(/[a-z]/, (c) => c.toUpperCase()); }
            setVerify(verifyChain(s.chain, h.id));
          }}>Alter one byte</button>
          {tampered.current && <button className="btn" onClick={() => { tampered.current.r.msg = tampered.current.msg; tampered.current = null; setVerify(verifyChain(s.chain, h.id)); }}>Undo</button>}
          {verify && <span className={`verify ${verify.ok ? 'ok' : 'bad'}`}>{verify.ok ? `✓ ${s.chain.length} records verify` : '✗ chain broken'}</span>}
        </div>
      </section>
    </aside>
  );
}

function Controls({ world }) {
  useTicker(world.bus);
  const h = world.houses[0];
  const b = h.bat;
  const mainsOn = world.grid.manual !== 'off';
  return (
    <aside className="panel bench-ctrl">
      <div className="eyebrow">Bench · Sentinel-Embedded</div>
      <button className={`mcb ${mainsOn ? 'on' : 'off'}`} onClick={() => setGrid(world, mainsOn ? 'off' : 'on')}>
        <span className="mcb-lever" />
        <span><b>MAINS MCB</b><small>{mainsOn ? 'ON · click to cut mains' : 'OFF · click to restore'}</small></span>
      </button>

      <div className="sec-title" style={{ marginTop: 10 }}>Loads on AC-OUT</div>
      <div className="loads">
        {h.appliances.map((a) => {
          const c = h.circuits[a.circuit];
          return (
            <button key={a.id} className={`load ${a.demand ? 'dem' : ''} ${a.powered ? 'pow' : ''}`} onClick={() => forceAppliance(h, a.id, a.demand ? false : null)}>
              <span className="circ-tier" style={{ background: TIER_META[c.tier].color }}>{c.tier}</span>
              <span className="load-n">{a.name}</span>
              <span className="load-w">{a.w} W</span>
              <span className={`sw ${a.demand ? 'on' : ''}`} />
            </button>
          );
        })}
      </div>

      <div className="sec-title" style={{ marginTop: 10 }}>Bench overrides</div>
      <label className="slider">
        <span>SoC <b>{Math.round(b.soc * 100)}%</b></span>
        <input type="range" min={20} max={100} value={Math.round(b.soc * 100)} onChange={(e) => { b.soc = +e.target.value / 100; evaluate(world, h, 'bench'); world.bus.emit(); }} />
        <i className="marks"><em style={{ left: '43.75%' }}>55</em><em style={{ left: '25%' }}>40</em></i>
      </label>
      <label className="slider">
        <span>Battery temp <b>{b.temp.toFixed(0)} °C</b></span>
        <input type="range" min={15} max={60} value={Math.round(b.temp)} onChange={(e) => { b.temp = +e.target.value; b.tempLocked = true; world.bus.emit(); }} />
      </label>

      <div className="sec-title" style={{ marginTop: 10 }}>Fault injection</div>
      <div className="actions">
        <button className="btn danger" onClick={() => resetMcu(world, h)} disabled={!h.sen.alive}><Icon name="reset" /> Reset MCU</button>
        <button className="btn danger" onClick={() => hangMcu(world, h)} disabled={!h.sen.alive}><Icon name="freeze" /> Freeze FW</button>
        <button className="btn" onClick={() => injectSag(world, 0.18, 340)} disabled={!world.grid.present}><Icon name="wave" /> Sag −18% · 340 ms</button>
      </div>
      {!h.sen.alive && (
        <div className="failsafe">
          {h.sen.mode === 'reset' ? 'Reset: pull-downs drop every coil → loads ON · charger back to factory' : world.t - h.sen.hangAt < P.SUPERVISOR_S ? `Heartbeat missing ${(world.t - h.sen.hangAt).toFixed(1)} s…` : 'Supervisory timer cut the coil rail → loads ON'}
        </div>
      )}

      <div className="sec-title" style={{ marginTop: 10 }}>SoH replay (synthetic aging)</div>
      <div className="steps">
        {GRADES.map((gr, i) => (
          <button key={gr.grade} className={`seg ${h.gradeIdx === i ? 'on' : ''}`} onClick={() => { h.gradeIdx = i; world.bus.emit(); }}>{gr.n_weeks} wk</button>
        ))}
      </div>

      <div className="sec-title" style={{ marginTop: 10 }}>Time</div>
      <div className="steps">
        <button className="icon-btn" onClick={() => { world.paused = !world.paused; world.bus.emit(); }}><Icon name={world.paused ? 'play' : 'pause'} /></button>
        {[1, 10, 60].map((s) => (
          <button key={s} className={`seg ${world.speed === s ? 'on' : ''}`} onClick={() => { world.speed = s; world.bus.emit(); }}>{s}×</button>
        ))}
      </div>
    </aside>
  );
}

function Timeline({ world }) {
  useTicker(world.bus);
  const ref = world.scope.ref;
  return (
    <div className="timeline">
      {world.scope.events.slice(0, 6).map((e, i) => (
        <div key={`${e.t}-${i}`} className={`tl k-${e.kind}`}>
          <span className="tl-t">{ref != null && e.t >= ref ? `+${((e.t - ref) * 1000).toFixed(e.t - ref < 1 ? 1 : 0)} ms` : ''}</span>
          <span>{e.text}</span>
        </div>
      ))}
    </div>
  );
}

const VIEWS = [['overview', 'Overview'], ['inside', 'Inside'], ['board', 'Sentinel board'], ['relay', 'Relay I2'], ['loads', 'Contactors + loads'], ['battery', 'Battery']];

export default function InverterTab({ world, active }) {
  const [casing, setCasing] = useState('open');
  const [view, setView] = useState('overview');
  const [hov, setHov] = useState(null);
  const [sel, setSel] = useState(null);
  const info = sel && PARTS[sel.id];
  return (
    <div className="tab-inverter">
      <Canvas
        shadows="percentage"
        dpr={[1, 1.75]}
        camera={{ position: [11, 10.5, 20], fov: 40, near: 0.05, far: 300 }}
        gl={{ antialias: false }}
        frameloop={active ? 'always' : 'never'}
        onPointerMissed={() => setSel(null)}
      >
        <PartCtx.Provider value={{ hov, sel, setHov, setSel }}>
          <Suspense fallback={null}>
            <BenchScene world={world} casing={casing} view={view} />
            <EffectComposer multisampling={4}>
              <Bloom mipmapBlur intensity={0.8} luminanceThreshold={0.95} luminanceSmoothing={0.2} />
              <Vignette offset={0.3} darkness={0.5} />
              <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
            </EffectComposer>
          </Suspense>
        </PartCtx.Provider>
      </Canvas>

      <div className="viewbar">
        {VIEWS.map(([k, l]) => <button key={k} className={`seg ${view === k ? 'on' : ''}`} onClick={() => setView(k === view ? `${k}` : k)}>{l}</button>)}
        <span className="vsep" />
        {['closed', 'open', 'xray'].map((m) => <button key={m} className={`seg ${casing === m ? 'on' : ''}`} onClick={() => setCasing(m)}>{m === 'xray' ? 'X-ray' : m === 'open' ? 'Lid off' : 'Closed'}</button>)}
      </div>

      <Controls world={world} />
      <LivePanel world={world} />

      <div className="panel scope">
        <Scope world={world} />
        <Timeline world={world} />
      </div>

      {info && (
        <div className="panel part-card">
          <div className="pc-id">{sel.id}</div>
          <div>
            <div className="pc-name">{info.name}</div>
            <div className="pc-role">{info.role}</div>
          </div>
          <button className="icon-btn" onClick={() => setSel(null)}><Icon name="x" /></button>
        </div>
      )}
    </div>
  );
}
