import { useState, Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { EffectComposer, Bloom, Vignette, ToneMapping } from '@react-three/postprocessing';
import { ToneMappingMode } from 'postprocessing';
import VillageScene from './VillageScene.jsx';
import HousePanel from '../ui/HousePanel.jsx';
import { Icon, socColor } from '../ui/bits.jsx';
import { useTicker, useWorldLoop, useOnce, makeTicker } from '../sim/tick.js';
import { createWorld, fmtClock, setGrid, injectSag, injectSwell, jumpTo, setSentinel, inOutageSchedule } from '../sim/engine.js';
import { VILLAGE_HOUSES, VILLAGE_OUTAGES, VILLAGE_T0 } from '../sim/village.js';

export function makeVillage() {
  const w = createWorld({ houses: VILLAGE_HOUSES, t0: VILLAGE_T0, outages: VILLAGE_OUTAGES, speed: 60 });
  w.bus = makeTicker();
  return w;
}

const SPEEDS = [1, 10, 60, 180, 600];

export default function VillageTab({ world, active }) {
  const [focus, setFocus] = useState(null);
  const [xray, setXray] = useState(false);
  const [corner, setCorner] = useState(false);
  useTicker(world.bus);
  const focused = focus && world.houses.find((h) => h.id === focus);
  const scheduled = inOutageSchedule(world);
  const allOn = world.houses.filter((h) => h.id !== 'h6').every((h) => h.sentinel);

  return (
    <div className="tab-village">
      <Canvas
        shadows="percentage"
        dpr={[1, 1.75]}
        camera={{ position: [6, 36, 50], fov: 42, near: 0.1, far: 900 }}
        gl={{ antialias: false, powerPreference: 'high-performance' }}
        frameloop={active ? 'always' : 'never'}
        onPointerMissed={() => { setFocus(null); setCorner(false); }}
      >
        <Suspense fallback={null}>
          <VillageScene world={world} focus={focus} xray={xray} onSelect={(id) => { setFocus(id); setCorner(false); }} corner={corner} />
          <EffectComposer multisampling={4}>
            <Bloom mipmapBlur intensity={0.85} luminanceThreshold={0.95} luminanceSmoothing={0.2} radius={0.7} />
            <Vignette offset={0.25} darkness={0.55} />
            <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
          </EffectComposer>
        </Suspense>
      </Canvas>

      {/* village roster */}
      <div className="panel roster">
        <div className="eyebrow">Village · 6 homes · one feeder</div>
        {world.houses.map((h) => {
          const st = h.inv.state;
          const dark = st === 'S4';
          return (
            <button key={h.id} className={`roster-row ${focus === h.id ? 'sel' : ''} ${dark ? 'dark' : ''}`} onClick={() => setFocus(focus === h.id ? null : h.id)}>
              <span className={`src ${dark ? 'bad' : st === 'S3' ? 'batt' : 'grid'}`}><Icon name={dark ? 'off' : st === 'S3' ? 'battery' : 'bolt'} size={13} /></span>
              <span className="rname">{h.name.split(' · ')[0]}<small>{h.name.split(' · ')[1]}</small></span>
              <span className="rbar"><span style={{ width: `${h.bat.soc * 100}%`, background: socColor(h.bat.soc) }} /></span>
              <span className="rpct">{Math.round(h.bat.soc * 100)}%</span>
              <span className={`rsen ${h.sentinel ? 'on' : ''}`}>{h.sentinel ? 'S' : '—'}</span>
            </button>
          );
        })}
        <div className="legend">
          <span><i style={{ background: '#FDC300' }} />mains power</span>
          <span><i style={{ background: '#22D3EE' }} />battery power</span>
          <span><i style={{ background: '#C084FC' }} />Sentinel sensing</span>
        </div>
      </div>

      {focused && <HousePanel world={world} h={focused} onClose={() => { setFocus(null); setCorner(false); }} corner={corner} setCorner={setCorner} />}

      {/* event ticker */}
      <div className="ticker">
        {world.ticker.slice(0, 5).map((e, i) => (
          <div key={`${e.t}-${i}`} className={`tick k-${e.kind}`} style={{ opacity: 1 - i * 0.16 }} onClick={() => setFocus(e.hid)}>
            <span className="tick-t">{fmtClock(e.t)}</span><b>{e.house}</b> {e.msg}
          </div>
        ))}
      </div>

      {/* control dock */}
      <div className="dock">
        <div className="dock-group">
          <button className="icon-btn" onClick={() => { world.paused = !world.paused; world.bus.emit(); }}>
            <Icon name={world.paused ? 'play' : 'pause'} />
          </button>
          {SPEEDS.map((s) => (
            <button key={s} className={`seg ${world.speed === s ? 'on' : ''}`} onClick={() => { world.speed = s; world.bus.emit(); }}>{s}×</button>
          ))}
        </div>
        <div className="dock-group">
          <button className={`btn ${world.grid.present ? 'danger' : 'gold'}`} onClick={() => setGrid(world, world.grid.present ? 'off' : 'on')}>
            <Icon name={world.grid.present ? 'off' : 'bolt'} /> {world.grid.present ? 'Cut feeder' : 'Restore feeder'}
          </button>
          <button className={`seg ${world.grid.manual == null ? 'on' : ''}`} onClick={() => setGrid(world, null)} title="Scheduled outage 19:00–23:00">
            <Icon name="clock" /> Roster {scheduled ? 'OUT' : '19–23'}
          </button>
          <button className="seg" onClick={() => injectSag(world, 0.18, 340)} disabled={!world.grid.present}><Icon name="wave" /> Sag</button>
          <button className="seg" onClick={() => injectSwell(world, 0.12, 220)} disabled={!world.grid.present}><Icon name="wave" /> Swell</button>
        </div>
        <div className="dock-group">
          <button className="seg" onClick={() => jumpTo(world, 18 * 60 + 58)}>⏭ 18:58</button>
          <button className="seg" onClick={() => jumpTo(world, 20 * 60 + 20)}>⏭ 20:20</button>
          <button className="seg" onClick={() => jumpTo(world, 21 * 60 + 55)}>⏭ 21:55</button>
          <button className={`seg ${xray ? 'on' : ''}`} onClick={() => setXray(!xray)}><Icon name="eye" /> X-ray</button>
          <button className={`seg ${allOn ? 'on' : ''}`} onClick={() => world.houses.filter((h) => h.id !== 'h6').forEach((h) => setSentinel(world, h, !allOn))}>
            <Icon name="shield" /> Sentinel {allOn ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>
    </div>
  );
}
