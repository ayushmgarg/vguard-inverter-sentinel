import { useTicker } from '../sim/tick.js';
import { Icon, Ring, Spark, Pill, fmt, STATE_TEXT, socColor } from './bits.jsx';
import { fmtClock, gradeOf, resetMcu, hangMcu, overrideTier, setSentinel, forceAppliance, advisedSetpoints } from '../sim/engine.js';
import { TIER_META, P } from '../sim/params.js';

const KIND_ICON = { fridge: '🧊', router: '📶', tube: '💡', bulb: '💡', fan: '🌀', tv: '📺', iron: '🔥', cpap: '🫁', laptop: '💻', ac: '❄️' };

export default function HousePanel({ world, h, onClose, corner, setCorner }) {
  useTicker(world.bus);
  const s = h.sen;
  const b = h.bat;
  const st = h.inv.state;
  const g = gradeOf(h);
  const onBatt = st === 'S3';
  const dark = st === 'S4';
  const iron = h.appliances.find((a) => a.kind === 'iron');
  const adv = advisedSetpoints(h);

  return (
    <aside className="panel house-panel">
      <header className="hp-head">
        <div>
          <div className="eyebrow">{h.sentinel ? 'Sentinel-Retrofit installed' : 'Standard inverter'}</div>
          <h2>{h.name}</h2>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button className={`seg ${corner ? 'on' : ''}`} onClick={() => setCorner(!corner)}><Icon name="chip" /> {corner ? 'Whole house' : 'Power corner'}</button>
          <button className="icon-btn" onClick={onClose} title="Back to village"><Icon name="x" /></button>
        </div>
      </header>

      <div className={`hp-state ${dark ? 'bad' : onBatt ? 'batt' : 'grid'}`}>
        <Icon name={dark ? 'off' : onBatt ? 'battery' : 'bolt'} size={16} />
        <b>{st}</b> {STATE_TEXT[st]}{st === 'S1' ? ` · ${b.stage}` : ''}
      </div>

      <div className="hp-live">
        <Ring value={b.soc} size={104} label={`${Math.round(b.soc * 100)}%`} sub="SoC" />
        <div className="hp-grid">
          <div><span>Battery</span><b>{fmt.v(b.v)}</b></div>
          <div><span>Current</span><b style={{ color: b.i < 0 ? '#22D3EE' : b.i > 0.5 ? '#FDC300' : undefined }}>{fmt.a(b.i)}</b></div>
          <div><span>Temp</span><b>{fmt.t(b.temp)}</b></div>
          <div><span>AC-OUT</span><b>{fmt.w(h.stats.pOut)}</b></div>
          <div className="wide"><span>Backup left</span><b>{onBatt ? fmt.h(h.stats.backupH) : dark ? 'dead' : 'on mains'}</b></div>
        </div>
      </div>
      <Spark data={h.hist} w={300} h={46} color={socColor(b.soc)} bands={[{ v: 0.55, c: '#FDC300' }, { v: 0.4, c: '#F39200' }, { v: 0.2, c: '#FF4D6D' }]} />

      <section>
        <div className="sec-title">Circuits · NC contactors</div>
        {Object.entries(h.circuits).map(([ch, c]) => {
          const aps = h.appliances.filter((a) => a.circuit === ch);
          if (!aps.length && c.tier === 'MED') return null;
          const shed = h.coils && h.coils[ch];
          const tm = TIER_META[c.tier];
          return (
            <div key={ch} className={`circ ${shed ? 'shed' : ''}`}>
              <span className="circ-ch">{ch.toUpperCase()}</span>
              <span className="circ-tier" style={{ background: tm.color }}>{c.tier}</span>
              <div className="circ-body">
                <div className="circ-aps">
                  {aps.map((a) => (
                    <span key={a.id} className={`ap ${a.powered ? 'on' : a.demand ? 'cut' : 'idle'}`} title={`${a.name} ${a.w} W`}>
                      {KIND_ICON[a.kind]} {a.name.replace('LED ', '').replace('Ceiling ', '')}
                    </span>
                  ))}
                </div>
                {shed && <div className="circ-reason">coil ON → circuit open · {c.tier === 'T2' ? s.reason.T2 : s.reason.T3}</div>}
              </div>
              <span className={`circ-st ${dark ? 'dead' : shed ? 'shed' : 'on'}`}>{dark ? 'DEAD' : shed ? 'SHED' : 'ON'}</span>
            </div>
          );
        })}
        {h.appliances.some((a) => a.circuit === 'NI') && (
          <div className="circ ni">
            <span className="circ-ch">DB</span>
            <span className="circ-tier" style={{ background: '#8A94A6' }}>MAINS</span>
            <div className="circ-body"><div className="circ-aps">
              {h.appliances.filter((a) => a.circuit === 'NI').map((a) => (
                <span key={a.id} className={`ap ${a.powered ? 'on' : a.demand ? 'cut' : 'idle'}`}>{KIND_ICON[a.kind]} {a.name}</span>
              ))}
            </div></div>
            <span className={`circ-st ${world.grid.present ? 'on' : 'dead'}`}>{world.grid.present ? 'ON' : 'OFF'}</span>
          </div>
        )}
      </section>

      {h.sentinel && (
        <>
          <section className="two">
            <div>
              <div className="sec-title">Outage vote</div>
              <div className="votes">
                <Pill tone={s.votes.s1 ? 'warn' : s.votes.s1raw ? 'mid' : 'muted'}>s1 mains &lt; 0.1 pu</Pill>
                <Pill tone={h.sku === 'embedded' ? (s.votes.s2 ? 'warn' : 'muted') : 'ghost'}>s2 mode pin</Pill>
                <Pill tone={s.votes.s3 ? 'warn' : 'muted'}>s3 discharge</Pill>
              </div>
              <div className={`vote-result ${s.outage ? 'on' : ''}`}>{s.outage ? `OUTAGE · ${Math.round((world.t - s.outageStart) / 60)} min` : 'mains OK'}</div>
            </div>
            <div>
              <div className="sec-title">Battery health</div>
              <div className={`grade g-${g.grade.toLowerCase()}`}>{g.grade === 'REPLACE' ? `Replace in ${g.rul_p10}–${g.rul_p90} wk` : g.grade}</div>
              <div className="muted-s">SoH {g.soh_p50}% [{g.soh_p10}–{g.soh_p90}] · RUL P50 {g.rul_p50} wk · conf {g.confidence}</div>
            </div>
          </section>

          <section>
            <div className="sec-title">Sentinel decisions · hash-chained log</div>
            <div className="log">
              {s.log.slice(0, 7).map((e, i) => (
                <div key={i} className={`log-row k-${e.kind}`}>
                  <span className="log-t">{fmtClock(e.t)}</span>
                  <span className="log-m">{e.msg}</span>
                  {s.chain.find((c) => c.t === e.t && c.msg === e.msg) && <span className="log-h">{s.chain.find((c) => c.t === e.t && c.msg === e.msg).hash.slice(0, 6)}</span>}
                </div>
              ))}
              {!s.log.length && <div className="muted-s">No events yet</div>}
            </div>
          </section>

          <section className="two">
            <div>
              <div className="sec-title">Energy Coach (NILM)</div>
              <div className="nilm">
                {s.nilm.slice(0, 4).map((e, i) => (
                  <div key={i} className="nilm-row">
                    <span className={e.on ? 'up' : 'down'}>{e.on ? '▲' : '▼'} {Math.abs(e.dP)} W</span>
                    <span>{e.label}</span>
                    <Pill tone={e.conf === 'HIGH' ? 'good' : e.conf === 'MED' ? 'mid' : 'muted'}>{e.conf}</Pill>
                  </div>
                ))}
                {!s.nilm.length && <div className="muted-s">{s.outage ? 'paused during outage' : 'listening on AC-OUT CT'}</div>}
              </div>
            </div>
            <div>
              <div className="sec-title">Grid Shield</div>
              {s.pq.slice(0, 3).map((e, i) => (
                <div key={i} className="nilm-row"><span className="down">{e.type}</span><span>{e.type === 'SAG' ? '−' : '+'}{e.mag}% · {e.dur} ms</span></div>
              ))}
              {!s.pq.length && <div className="muted-s">no sag/swell logged</div>}
              <div className="muted-s" style={{ marginTop: 6 }}>Charger advice: float {adv.float.toFixed(2)} V @ {b.temp.toFixed(0)} °C</div>
            </div>
          </section>
        </>
      )}

      <section className="actions">
        {h.sentinel && (
          <>
            <button className="btn danger" onClick={() => resetMcu(world, h)} disabled={!s.alive}><Icon name="reset" /> Reset MCU</button>
            <button className="btn danger" onClick={() => hangMcu(world, h)} disabled={!s.alive}><Icon name="freeze" /> Freeze firmware</button>
            <button className="btn" onClick={() => overrideTier(world, h, 'T2', 30)} disabled={!s.alive || !s.shed.T2}>Keep fans on 30 min</button>
          </>
        )}
        {iron && (
          <button className="btn" onClick={() => forceAppliance(h, iron.id, iron.forced ? null : true)}>
            <Icon name="plug" /> {iron.forced ? 'Iron: auto' : 'Switch iron ON'}
          </button>
        )}
        <button className={`btn ${h.sentinel ? '' : 'gold'}`} onClick={() => setSentinel(world, h, !h.sentinel)}>
          {h.sentinel ? 'Remove Sentinel' : 'Install Sentinel'}
        </button>
      </section>
      {!s.alive && h.sentinel && (
        <div className="failsafe">
          {s.mode === 'reset' ? 'MCU in reset — pull-downs hold every coil OFF → all loads ON' : world.t - s.hangAt < P.SUPERVISOR_S ? 'Firmware frozen — supervisory timer counting…' : 'Supervisory timer cut the coil rail → all loads ON'}
        </div>
      )}
    </aside>
  );
}
