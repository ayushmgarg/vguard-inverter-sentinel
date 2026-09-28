import sohBand from '../assets/deck/soh_band.png';
import nilmEvents from '../assets/deck/nilm_events.png';
import pqDip from '../assets/deck/pq_dip.png';
import ladder from '../assets/deck/autopilot_ladder.png';
import tests from '../assets/deck/tests_per_module.png';
import failsafe from '../assets/deck/failsafe_flow.png';
import engine1 from '../assets/deck/engine1_flow.png';
import placement from '../assets/deck/placement.png';
import firmware from '../assets/deck/firmware_tasks.png';
import evidence from '../assets/deck/evidence_ladder.png';
import cost from '../assets/deck/cost_tiers.png';
import './theory.css';

// All content condensed from prototype/00–05, design/05, design/12 and the deck in vguard-sentinel-main.

function Boundary() {
  const L = [
    ['Battery +', 'J1 · fused sense + power'], ['Shunt S+/S−', 'J2 · Kelvin ≤ 50 mV'], ['NTC on battery', 'J4'],
    ['AC-OUT L/N', 'J5 · AMC1311 tap'], ['CT on AC-OUT live', 'J6 · ATM90E32AS'], ['Mode / mains line', 'J9 · PC817'],
  ];
  const R = [['Contactor coils ×4', 'J8 · ULN2003'], ['Charger feedback', 'J10 · MCP4725 (Embedded)'], ['App / cloud', 'Wi-Fi · BLE (optional)']];
  return (
    <svg viewBox="0 0 980 360" className="bnd">
      <defs>
        <marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#C084FC" /></marker>
        <marker id="ar2" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#FDC300" /></marker>
      </defs>
      <rect x="300" y="30" width="380" height="300" rx="18" fill="#0F131A" stroke="#FDC300" strokeWidth="1.5" />
      <text x="490" y="58" textAnchor="middle" fill="#FDC300" fontFamily="Anton" fontSize="20" letterSpacing="1.5">SENTINEL CORE</text>
      <text x="490" y="78" textAnchor="middle" fill="#7C8595" fontSize="11">90 × 70 × 35 mm · powered from the battery · no network on the critical path</text>
      {[
        ['ESP32-S3 · TFLM int8 CNN × 3 · EKF', 110], ['NILM · PQ (IEEE 1159) · Autopilot', 150], ['LittleFS · NVS · DS3231 RTC · ATECC608', 190], ['Supervisory timer · medical jumper', 230], ['MP2315 buck ≈ 2.6 mA avg', 270],
      ].map(([t, y]) => (
        <g key={t}>
          <rect x="325" y={y - 18} width="330" height="28" rx="7" fill="rgba(255,255,255,0.04)" stroke="rgba(255,255,255,0.08)" />
          <text x="490" y={y} textAnchor="middle" fill="#E8EBF0" fontSize="12.5">{t}</text>
        </g>
      ))}
      {L.map(([a, b], i) => {
        const y = 60 + i * 46;
        return (
          <g key={a}>
            <text x="20" y={y} fill="#E8EBF0" fontSize="13" fontWeight="700">{a}</text>
            <text x="20" y={y + 16} fill="#7C8595" fontSize="11">{b}</text>
            <line x1="200" y1={y + 4} x2="296" y2={y + 4} stroke="#C084FC" strokeWidth="1.5" markerEnd="url(#ar)" />
          </g>
        );
      })}
      {R.map(([a, b], i) => {
        const y = 110 + i * 70;
        return (
          <g key={a}>
            <line x1="684" y1={y + 4} x2="770" y2={y + 4} stroke="#FDC300" strokeWidth="1.5" markerEnd="url(#ar2)" strokeDasharray={i === 2 ? '4 4' : ''} />
            <text x="780" y={y} fill="#E8EBF0" fontSize="13" fontWeight="700">{a}</text>
            <text x="780" y={y + 16} fill="#7C8595" fontSize="11">{b}</text>
          </g>
        );
      })}
    </svg>
  );
}

function Ladder() {
  return (
    <div className="ladder">
      <div className="lad-bar">
        <div className="z z1" style={{ width: '20%' }}>cut-off</div>
        <div className="z z2" style={{ width: '20%' }}>T3 shed ≤ 40</div>
        <div className="z z3" style={{ width: '15%' }}>T2 defer ≤ 55</div>
        <div className="z z4" style={{ width: '45%' }}>all on</div>
      </div>
      <div className="lad-axis"><span>0</span><span style={{ left: '20%' }}>20</span><span style={{ left: '40%' }}>40</span><span style={{ left: '55%' }}>55</span><span style={{ left: '70%' }}>70</span><span style={{ left: '100%' }}>100 %</span></div>
      <div className="lad-notes">
        <div><b>Restore</b> T3 ≥ 55 % · T2 ≥ 70 % (15 pp hysteresis) · min OFF dwell 3 min · re-evaluate every 60 s</div>
        <div><b>Hard floor</b> shed T3 when E_avail &lt; 1.2 × forecast T1 energy · <b>T1 never</b> · <b>MED</b> jumper-locked</div>
        <div><b>Override</b> keep a tier on for 30 min (max 4 h) — cannot beat the hard floor</div>
      </div>
    </div>
  );
}

const ENGINES = [
  { k: 'E1', t: 'Battery health', d: '3-state EKF for SoC / R_int at 1 Hz → 14 per-cycle features → int8 1-D CNN (27,990 params, 105,600 MACs), 3 seeds, quantile heads + split-conformal band → grade and "replace within N weeks" window.' },
  { k: 'E2', t: 'Habit autopilot', d: '168-bin hour-of-week EWMA tables (≈ 4.7 KB) for load and outage; 2-of-3 outage vote; SoC ladder with hysteresis and dwell drives NC contactors.' },
  { k: 'E3', t: 'Energy Coach · Grid Shield', d: 'ATM90E32AS P/Q at 3 Hz on AC-OUT → event detector (ΔP ≥ 25 W) → rules + k-NN on 13 features. AMC1311 half-cycle RMS → sag / swell / interruption log (IEEE 1159, Class-S-like).' },
  { k: 'E4', t: 'Signed health log', d: 'Hash-chained records signed by the ATECC608 key (ECDSA-P256). Tamper, delete, replay and truncation are all detected — warranty evidence.' },
];

const PROOF = [
  ['176', 'automated tests across sim, EKF, model, autopilot, NILM, PQ, charger, health log, dashboard'],
  ['+0.04 pt', 'int8 vs float SoH MAE — 3 × 36,720 B .tflite, bit-exact golden self-test in C'],
  ['50 / 50', 'autopilot C scenarios with Python ↔ C parity'],
  ['1.00', 'NILM event recall · fridge F1 0.97 · iron 1.00 · 87 % energy assigned (synthetic)'],
  ['13 / 13', 'PQ dips detected · magnitude error ≤ 0.86 %'],
  ['8.2 pt', 'SoH MAE on synthetic test batteries — band calibrated but wide; real tubular data needs the aging campaign'],
];

export default function TheoryTab() {
  return (
    <div className="theory">
      <header className="th-hero">
        <div className="eyebrow">Engineering · what runs inside the box</div>
        <h1>A self-contained intelligence module for the home inverter–battery system</h1>
        <p>Measures the battery (V, I, T) and the inverter AC output (V, I, P, Q), runs estimation and TinyML on an ESP32-S3 without any network, and acts through NC contactors — and, on new V-Guard inverters, through the charger.</p>
      </header>

      <section className="th-sec">
        <h2>System boundary</h2>
        <Boundary />
      </section>

      <section className="th-sec">
        <h2>Two SKUs, one core</h2>
        <table className="th-table">
          <thead><tr><th /><th>Sentinel-Retrofit</th><th>Sentinel-Embedded</th></tr></thead>
          <tbody>
            <tr><td>Form</td><td>box beside the inverter</td><td>daughter-board inside the inverter</td></tr>
            <tr><td>Battery current</td><td>external busbar shunt in the negative lead</td><td>Kelvin tap on the inverter's own shunt</td></tr>
            <tr><td>AC sensing</td><td>CT on AC-OUT live + plug-in voltage tap</td><td>divider + isolator on the AC-OUT rail</td></tr>
            <tr><td>Mains present</td><td>own AC-IN sense / current sign</td><td>control-board signal (opto)</td></tr>
            <tr><td>Charger</td><td>advisory only</td><td>DAC on the PWM feedback node · hardware clamp · 2 s heartbeat revert</td></tr>
            <tr><td>Install</td><td>electrician, 30–45 min</td><td>factory</td></tr>
          </tbody>
        </table>
      </section>

      <section className="th-sec">
        <h2>Four engines</h2>
        <div className="eng">
          {ENGINES.map((e) => (
            <div key={e.k} className="eng-card"><span>{e.k}</span><h3>{e.t}</h3><p>{e.d}</p></div>
          ))}
        </div>
      </section>

      <section className="th-sec">
        <h2>Load prioritisation ladder</h2>
        <Ladder />
      </section>

      <section className="th-sec">
        <h2>Fail-safe: coil off means load on</h2>
        <div className="fs">
          {['NC contactors — de-energised = closed', 'Reset → pull-downs drop every coil', 'Hang → supervisory timer cuts coil rail in 2 s', 'Medical channel hard-wired never-shed', 'Sensor fault → never shed on bad data'].map((t, i) => (
            <div key={t} className="fs-step"><b>{i + 1}</b>{t}</div>
          ))}
        </div>
      </section>

      <section className="th-sec">
        <h2>Executed evidence (prototype/code)</h2>
        <div className="proof">
          {PROOF.map(([n, t]) => <div key={t} className="pf"><b>{n}</b><span>{t}</span></div>)}
        </div>
        <p className="th-note">Deliberately not in the prototype: federated learning (designed, cut — D15), charger control on a retrofit inverter, loads under ~40 W, SoH trained on real tubular data (campaign pending).</p>
      </section>

      <section className="th-sec">
        <h2>Figures from the prototype code</h2>
        <div className="gal">
          {[[engine1, 'Engine 1 pipeline'], [sohBand, 'SoH band on 3 held-out batteries'], [ladder, 'Autopilot ladder'], [failsafe, 'Fail-safe chain'], [nilmEvents, 'Energy Coach events'], [pqDip, 'Grid Shield dip detection'], [placement, 'Placement'], [firmware, 'Firmware tasks'], [tests, 'Tests per module'], [evidence, 'Evidence ladder'], [cost, 'Cost tiers']].map(([src, cap]) => (
            <figure key={cap}><img src={src} alt={cap} loading="lazy" /><figcaption>{cap}</figcaption></figure>
          ))}
        </div>
      </section>
    </div>
  );
}

