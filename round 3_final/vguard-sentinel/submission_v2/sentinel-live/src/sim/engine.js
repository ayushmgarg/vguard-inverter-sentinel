import { P, KINDS, GRADES } from './params.js';
import { sha256hex } from './sha256.js';

export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const smooth = (e0, e1, x) => {
  const t = clamp((x - e0) / (e1 - e0), 0, 1);
  return t * t * (3 - 2 * t);
};

export const fmtClock = (t) => {
  const m = Math.floor(((t % 86400) + 86400) % 86400 / 60);
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
};
export const fmtClockS = (t) => {
  const s = Math.floor(((t % 86400) + 86400) % 86400);
  return `${fmtClock(t)}:${String(s % 60).padStart(2, '0')}`;
};

// ---------- battery electrochemistry (12 V flooded tubular, simplified) ----------
const ocv = (soc) => 11.55 + 1.2 * soc;
const rInt = (soc, soh) => (0.01 + 0.028 * Math.pow(1 - soc, 3)) * (1 + (1 - soh) * 2.5);
export const capWh = (h) => P.V_NOM * h.ah * h.soh;

// charger setpoints; Embedded SKU gets temperature compensation + derating (design 03)
export function setpoints(h) {
  const T = h.bat.temp;
  const controlled = h.sentinel && h.sku === 'embedded' && h.sen.alive && h.sen.chargerLink;
  const iBulk = P.BULK_C * h.ah;
  if (!controlled) {
    return { abs: P.V_ABS, float: P.V_FLOAT, iMax: iBulk, source: 'factory', derate: 1 };
  }
  const dT = T - P.T_REF;
  const abs = clamp(P.V_ABS + P.TEMP_COEF * dT, 13.8, 14.9);
  const float = clamp(P.V_FLOAT + P.TEMP_COEF * dT, 13.1, 13.8);
  const derate = T <= P.DERATE_START ? 1 : T >= P.DERATE_STOP ? 0 : 1 - (T - P.DERATE_START) / (P.DERATE_STOP - P.DERATE_START);
  return { abs, float, iMax: iBulk * derate, source: 'sentinel', derate };
}

// retrofit: advisory only
export function advisedSetpoints(h) {
  const dT = h.bat.temp - P.T_REF;
  return { abs: P.V_ABS + P.TEMP_COEF * dT, float: P.V_FLOAT + P.TEMP_COEF * dT };
}

// ---------- schedules ----------
function inWindow(min, [a, b]) {
  if (b > 1440) return min >= a || min < b - 1440;
  return min >= a && min < b;
}
function scheduled(ap, t) {
  const min = ((t % 86400) + 86400) % 86400 / 60;
  const s = ap.sched;
  if (s === 'always') return true;
  if (s.duty) {
    const [on, off, ph] = s.duty;
    const cyc = (t / 60 + ph) % (on + off);
    return cyc < on;
  }
  return s.some((w) => inWindow(min, w));
}

// ---------- world ----------
export function createWorld({ houses, t0, outages = [], speed = 60 }) {
  const world = {
    t: t0,
    speed,
    paused: false,
    grid: { manual: null, outages, v: P.V_MAINS, present: true, sag: null, lostAt: null },
    houses: houses.map((cfg) => createHouse(cfg, t0)),
    ticker: [],
    lastEvent: null,
  };
  world.houses.forEach((h) => primeAppliances(world, h));
  return world;
}

function createHouse(cfg, t0) {
  const h = {
    ...cfg,
    sku: cfg.sku || 'retrofit',
    gradeIdx: cfg.gradeIdx ?? 1,
    appliances: cfg.appliances.map((a, i) => ({
      id: a.id || `${a.kind}-${i}`,
      name: a.name || KINDS[a.kind].name,
      ...a,
      w: a.w ?? KINDS[a.kind].w,
      q: a.q ?? KINDS[a.kind].q,
      forced: null,
      demand: false,
      powered: false,
      wh: 0,
    })),
    bat: { soc: cfg.soc0, v: 13.5, i: 0, temp: cfg.temp0 ?? 31, stage: 'float', override: null },
    inv: { state: 'S1', s2Remain: 0, s6Remain: 0, relay: 'mains', since: t0 },
    sen: {
      alive: true, mode: 'ok', hangAt: null, bootAt: null,
      chargerLink: cfg.sku === 'embedded',
      s1Timer: 0, restoreTimer: 0, votes: { s1: false, s2: false, s3: false },
      outage: false, outageStart: null, detectLatency: null,
      shed: { T2: false, T3: false }, lastChange: { T2: -1e9, T3: -1e9 }, reason: { T2: '', T3: '' },
      nextEval: t0 + 5, alertsFired: [],
      habitOutageH: 4,
      log: [], nilm: [], pq: [], chain: [], prevHash: '0'.repeat(64),
    },
    stats: { pOut: 0, pNI: 0, pBatt: 0, backupH: null, dark: false, darkSince: null, essentialsOn: true },
    hist: [],
    lastHist: -1e9,
  };
  return h;
}

function primeAppliances(world, h) {
  h.appliances.forEach((a) => { a.demand = scheduled(a, world.t); a.prevPowered = null; });
}

export function inOutageSchedule(world) {
  const min = ((world.t % 86400) + 86400) % 86400 / 60;
  return world.grid.outages.some((w) => inWindow(min, w));
}

function log(world, h, msg, kind = 'info', extra = {}) {
  const entry = { t: world.t, msg, kind, ...extra };
  h.sen.log.unshift(entry);
  if (h.sen.log.length > 60) h.sen.log.pop();
  world.ticker.unshift({ t: world.t, house: h.short || h.name, hid: h.id, msg, kind });
  if (world.ticker.length > 40) world.ticker.pop();
  // hash-chained health log (design 09): each record commits to the previous hash
  if (h.sentinel && kind !== 'nilm') {
    const rec = `${Math.round(world.t * 1000)}|${h.id}|${msg}|${h.sen.prevHash}`;
    const hash = sha256hex(rec);
    h.sen.chain.unshift({ t: world.t, msg, hash, prev: h.sen.prevHash });
    if (h.sen.chain.length > 40) h.sen.chain.pop();
    h.sen.prevHash = hash;
  }
}
function tick(world, h, msg, kind) {
  world.ticker.unshift({ t: world.t, house: h.short || h.name, hid: h.id, msg, kind });
  if (world.ticker.length > 40) world.ticker.pop();
}

export const circuitOf = (h, a) => (a.circuit === 'NI' ? null : h.circuits[a.circuit]);
export const tierOf = (h, a) => (a.circuit === 'NI' ? 'NI' : h.circuits[a.circuit].tier);

export function coilEnergised(world, h, ch) {
  if (!h.sentinel) return false;
  const c = h.circuits[ch];
  if (!c || c.tier === 'T1' || c.tier === 'MED') return false; // hardware-locked / never shed
  const s = h.sen;
  if (s.mode === 'reset') return false; // pull-downs: reset = coils off instantly
  if (s.mode === 'hang' && world.t - s.hangAt >= P.SUPERVISOR_S) return false; // supervisory timer cut
  return !!s.shed[c.tier];
}

export function outputLive(h) {
  return h.inv.state === 'S1' || h.inv.state === 'S3' || h.inv.state === 'S6';
}

// ---------- main step ----------
export function step(world, dt) {
  world.t += dt;
  const g = world.grid;
  const wasPresent = g.present;
  g.present = g.manual != null ? g.manual === 'on' : !inOutageSchedule(world);
  if (g.sag && world.t > g.sag.until) g.sag = null;
  g.v = g.present ? P.V_MAINS * (g.sag ? 1 - g.sag.depth : 1) + Math.sin(world.t * 0.7) * 2 : 0;
  if (wasPresent && !g.present) { g.lostAt = world.t; world.lastEvent = { type: 'loss', t: world.t }; }
  if (!wasPresent && g.present) { world.lastEvent = { type: 'return', t: world.t }; }
  for (const h of world.houses) stepHouse(world, h, dt);
  if (world.onStep) world.onStep(world);
}

function stepHouse(world, h, dt) {
  const g = world.grid;
  const b = h.bat;
  const inv = h.inv;
  const s = h.sen;
  const gridOk = g.v >= P.NORMAL_WIN[0];

  // --- inverter state machine (prototype 01 §3) ---
  const prev = inv.state;
  if (gridOk) {
    if (inv.state === 'S2' || inv.state === 'S3' || inv.state === 'S4') {
      inv.state = 'S6'; inv.s6Remain = P.MAINS_RETURN_S;
    }
    if (inv.state === 'S6') {
      inv.s6Remain -= dt;
      if (inv.s6Remain <= 0) {
        inv.state = 'S1'; inv.relay = 'mains';
        b.stage = b.soc < 0.97 ? 'bulk' : 'float';
      }
    }
  } else {
    if (inv.state === 'S1' || inv.state === 'S6') {
      inv.state = 'S2'; inv.s2Remain = P.TRANSFER_MS / 1000; inv.lossAt = world.t;
    }
    if (inv.state === 'S2') {
      inv.s2Remain -= dt;
      if (inv.s2Remain <= 0) { inv.state = 'S3'; inv.relay = 'bridge'; }
    }
  }
  if (inv.state !== prev) inv.since = world.t;

  const live = outputLive(h);

  // --- appliance demand & power ---
  let pOut = 0, qOut = 0, pNI = 0;
  const coils = {};
  for (const ch of Object.keys(h.circuits)) coils[ch] = coilEnergised(world, h, ch);
  h.coils = coils;
  for (const a of h.appliances) {
    a.demand = a.forced != null ? a.forced : scheduled(a, world.t);
    let on;
    if (a.circuit === 'NI') on = a.demand && gridOk;
    else on = a.demand && live && !coils[a.circuit];
    a.powered = on;
    if (on) {
      if (a.circuit === 'NI') pNI += a.w;
      else { pOut += a.w; qOut += a.q; }
      a.wh += (a.w * dt) / 3600;
    }
  }
  h.stats.pOut = pOut; h.stats.qOut = qOut; h.stats.pNI = pNI;

  // --- battery ---
  const r = rInt(b.soc, h.soh);
  const cap = capWh(h);
  if (b.override != null) { b.soc = b.override; }
  if (inv.state === 'S3') {
    const pb = (pOut + P.IDLE_W) / P.ETA_INV + (h.sentinel ? 0.03 : 0);
    const o = ocv(b.soc);
    const disc = Math.max(o * o - 4 * r * pb, 0);
    const I = (o - Math.sqrt(disc)) / (2 * r);
    b.i = -I;
    b.v = o - I * r;
    h.stats.pBatt = pb;
    b.soc = clamp(b.soc - (pb * dt) / (cap * 3600), 0, 1);
    if (b.soc <= P.CUTOFF_SOC) {
      inv.state = 'S4'; inv.since = world.t; inv.relay = 'off';
      tick(world, h, 'Low-battery cut-off — inverter output dead', 'bad');
      if (h.sentinel) log(world, h, 'Low-battery cut-off (S4) recorded', 'bad');
    }
  } else if (inv.state === 'S1') {
    const sp = setpoints(h);
    h.sp = sp;
    let I = 0, V;
    const gas = 1.8 * smooth(0.55, 0.9, b.soc);
    if (b.stage === 'bulk') {
      I = sp.iMax;
      V = ocv(b.soc) + I * r + gas;
      if (V >= sp.abs) { b.stage = 'absorption'; V = sp.abs; }
    } else if (b.stage === 'absorption') {
      V = sp.abs;
      I = clamp(sp.iMax * (1 - b.soc) / 0.16, 0, sp.iMax);
      if (I < 1.5) b.stage = 'float';
    } else {
      V = sp.float;
      I = clamp(0.3 + 4 * (1 - b.soc), 0, sp.iMax);
      if (b.soc < 0.9) b.stage = 'bulk';
    }
    if (sp.iMax <= 0) I = 0;
    b.i = I; b.v = V;
    h.stats.pBatt = -(I * V) / P.ETA_INV;
    b.soc = clamp(b.soc + (I * P.ETA_CHG * dt) / (h.ah * h.soh * 3600), 0, 1);
  } else {
    b.i = 0; b.v = ocv(b.soc); h.stats.pBatt = 0;
  }
  if (b.override != null) b.soc = b.override;

  // temperature (first order toward ambient + I²R heating)
  if (!b.tempLocked) {
    const target = (h.ambient ?? 31) + 0.004 * b.i * b.i;
    b.temp += (target - b.temp) * clamp(dt / 1200, 0, 1);
  }

  // --- essentials / darkness ---
  const essentials = h.appliances.filter((a) => a.circuit !== 'NI' && ['T1', 'MED'].includes(h.circuits[a.circuit].tier) && a.demand);
  const essOn = essentials.every((a) => a.powered);
  h.stats.essentialsOn = essOn;
  h.stats.dark = !live;
  if (!live && h.stats.darkSince == null) h.stats.darkSince = world.t;
  if (live) h.stats.darkSince = null;

  // backup estimate
  if (inv.state === 'S3' && h.stats.pBatt > 0) {
    h.stats.backupH = (cap * Math.max(0, b.soc - P.CUTOFF_SOC)) / h.stats.pBatt;
  } else h.stats.backupH = null;

  if (h.sentinel) stepSentinel(world, h, dt);

  // history (SoC trace) every 60 sim-s
  if (world.t - h.lastHist >= (h.histEvery ?? 60)) {
    h.lastHist = world.t;
    h.hist.push({ t: world.t, soc: b.soc, p: pOut, grid: gridOk, v: b.v, i: b.i });
    if (h.hist.length > 600) h.hist.shift();
  }
}

// ---------- Sentinel firmware behaviour ----------
function stepSentinel(world, h, dt) {
  const s = h.sen;
  const b = h.bat;
  const g = world.grid;

  // fail-safe paths
  if (s.mode === 'hang') {
    if (!s.supervisorLogged && world.t - s.hangAt >= P.SUPERVISOR_S) {
      s.supervisorLogged = true;
      tick(world, h, 'Heartbeat lost 2 s → supervisory timer cut all coils → loads ON', 'warn');
    }
    if (world.t >= s.bootAt) boot(world, h);
    return;
  }
  if (s.mode === 'reset') {
    if (world.t >= s.bootAt) boot(world, h);
    return;
  }

  // --- outage detection: 2-of-3 votes (design 05 §7) ---
  const s1raw = g.v < P.S1_PU * P.V_MAINS;
  s.s1Timer = s1raw ? s.s1Timer + dt : 0;
  s.votes.s1 = s.s1Timer >= P.S1_DEBOUNCE_S;
  s.votes.s1raw = s1raw;
  s.votes.s2 = h.sku === 'embedded' && ['S2', 'S3', 'S4'].includes(h.inv.state);
  s.votes.s3 = b.i < -P.S3_DISCHARGE_A;
  if (!s.outage) {
    const confirmed = (s.votes.s1 && (s.votes.s2 || s.votes.s3)) || s.s1Timer >= P.S1_ALONE_S;
    if (confirmed) {
      s.outage = true;
      s.outageStart = world.t - s.s1Timer;
      s.detectLatency = s.s1Timer;
      const v = ['s1', s.votes.s2 && 's2', s.votes.s3 && 's3'].filter(Boolean).join('+');
      log(world, h, `Outage confirmed (${v}) · Wi-Fi off · NILM paused`, 'warn');
      evaluate(world, h, 'outage');
    }
    s.restoreTimer = 0;
  } else {
    const ok = g.v > P.RESTORE_PU * P.V_MAINS;
    s.restoreTimer = ok ? s.restoreTimer + dt : 0;
    if (s.restoreTimer >= P.RESTORE_DEBOUNCE_S) {
      s.outage = false;
      s.alertsFired = [];
      const mins = Math.round((world.t - s.outageStart) / 60);
      log(world, h, `Mains restored after ${mins} min · recharge first, tiers return by SoC`, 'good');
      evaluate(world, h, 'restore');
    }
  }

  // staged low-SoC alerts (independent of shedding)
  if (s.outage) {
    for (const a of P.ALERTS) {
      if (b.soc <= a && !s.alertsFired.includes(a)) {
        s.alertsFired.push(a);
        log(world, h, `Reserve alert: SoC ${Math.round(a * 100)} %`, a <= 0.2 ? 'bad' : 'warn');
      }
    }
  }

  // periodic autopilot tick
  if (world.t >= s.nextEval) evaluate(world, h, 'tick');

  // --- NILM on AC-OUT (paused in outage) ---
  if (!s.outage && h.inv.state === 'S1') {
    for (const a of h.appliances) {
      if (a.circuit === 'NI' && !h.ct2) continue;
      if (a.prevPowered == null) { a.prevPowered = a.powered; continue; }
      if (a.powered !== a.prevPowered) {
        const dP = a.powered ? a.w : -a.w;
        if (Math.abs(dP) >= P.NILM_PTH_W) {
          const conf = a.w >= 80 ? 'HIGH' : a.w >= 40 ? 'MED' : 'LOW';
          const ev = { t: world.t, dP, dQ: a.powered ? a.q : -a.q, label: a.name, conf, on: a.powered };
          s.nilm.unshift(ev);
          if (s.nilm.length > 30) s.nilm.pop();
        }
      }
      a.prevPowered = a.powered;
    }
  } else {
    for (const a of h.appliances) a.prevPowered = a.powered;
  }
}

function boot(world, h) {
  const s = h.sen;
  s.alive = true; s.mode = 'ok'; s.hangAt = null; s.bootAt = null; s.supervisorLogged = false;
  s.shed = { T2: false, T3: false };
  s.outage = false; s.s1Timer = 0; s.restoreTimer = 0;
  s.nextEval = world.t + P.EVAL_S;
  log(world, h, 'Rebooted · state restored from NVS · golden self-test passed', 'info');
}

export function evaluate(world, h, why) {
  const s = h.sen;
  if (!s.alive) return;
  s.nextEval = world.t + P.EVAL_S;
  const soc = h.bat.soc;
  const pct = `${Math.round(soc * 100)} %`;
  const want = { ...s.shed };
  const reason = { T2: '', T3: '' };

  if (s.outage) {
    const eAvail = capWh(h) * Math.max(0, soc - P.CUTOFF_SOC);
    const pT1 = h.appliances
      .filter((a) => a.circuit !== 'NI' && ['T1', 'MED'].includes(h.circuits[a.circuit].tier) && a.demand)
      .reduce((acc, a) => acc + (a.kind === 'fridge' ? a.w * 0.5 : a.w), 0);
    const remH = Math.max(0.5, s.habitOutageH - (world.t - s.outageStart) / 3600);
    const fcst = (pT1 / P.ETA_INV + P.IDLE_W) * remH;
    s.forecast = { eAvail, fcst, remH };
    if (eAvail < P.ENDURANCE_MARGIN * fcst) { want.T3 = true; reason.T3 = 'T1 endurance at risk'; }
    if (soc <= P.T3_SHED) { want.T3 = true; reason.T3 = `SoC ${pct} ≤ 40 %`; }
    if (soc <= P.T2_SHED) { want.T2 = true; reason.T2 = `SoC ${pct} ≤ 55 %`; }
  }
  const chargeOk = !s.outage && (h.bat.stage === 'absorption' || h.bat.stage === 'float');
  for (const [tier, thr] of [['T3', P.T3_RESTORE], ['T2', P.T2_RESTORE]]) {
    if (s.shed[tier] && !reason[tier]) {
      const dwellOk = world.t - s.lastChange[tier] >= P.MIN_OFF_DWELL_S;
      if ((soc >= thr || chargeOk) && dwellOk) want[tier] = false;
      else want[tier] = true;
    }
  }
  // user override (design 05 §4.4): SoC-ladder tiers only, never beats the hard floor, times out
  if (s.override && world.t >= s.override.until) {
    log(world, h, `User override on ${s.override.tier} timed out`, 'info');
    s.override = null;
  }
  if (s.override && reason[s.override.tier] !== 'T1 endurance at risk') {
    want[s.override.tier] = false;
  }
  for (const tier of ['T3', 'T2']) {
    // min ON dwell applies to compressor loads only (design 05 §4.2)
    const compressor = h.appliances.some((x) => x.circuit !== 'NI' && h.circuits[x.circuit].tier === tier && (x.kind === 'fridge' || x.kind === 'ac'));
    if (compressor && want[tier] && !s.shed[tier] && world.t - s.lastChange[tier] < P.MIN_ON_DWELL_S) continue;
    if (want[tier] !== s.shed[tier]) {
      s.shed[tier] = want[tier];
      s.lastChange[tier] = world.t;
      const chs = Object.entries(h.circuits).filter(([, c]) => c.tier === tier).map(([k]) => k.toUpperCase());
      if (want[tier]) {
        s.reason[tier] = reason[tier];
        log(world, h, `${tier} ${tier === 'T2' ? 'deferred' : 'shed'} (${chs.join(',')}) — ${reason[tier]}`, 'shed', { tier, action: 'shed' });
      } else {
        s.reason[tier] = '';
        log(world, h, `${tier} restored (${chs.join(',')}) — SoC ${pct}${chargeOk ? ', charger in ' + h.bat.stage : ''}`, 'good', { tier, action: 'restore' });
      }
    } else if (want[tier] && reason[tier]) s.reason[tier] = reason[tier];
  }
  if (s.shed.T2 && !reason.T2 && !s.outage) s.reason.T2 = `held for recharge (restore ≥ 70 %)`;
  if (s.shed.T3 && !reason.T3 && !s.outage) s.reason.T3 = `held for recharge (restore ≥ 55 %)`;
}

// ---------- actions ----------
export function setGrid(world, mode) { world.grid.manual = mode; }

export function injectSag(world, depth = 0.18, ms = 340) {
  world.grid.sag = { until: world.t + ms / 1000, depth };
  const v = Math.round(P.V_MAINS * (1 - depth));
  for (const h of world.houses) {
    if (!h.sentinel || !h.sen.alive || !world.grid.present) continue;
    h.sen.pq.unshift({ t: world.t, type: 'SAG', mag: Math.round(depth * 100), dur: ms, v, ride: v >= P.UPS_WIN[0] });
    if (h.sen.pq.length > 20) h.sen.pq.pop();
    log(world, h, `Grid Shield: SAG −${Math.round(depth * 100)} % (${v} V) for ${ms} ms · logged`, 'pq');
  }
}
export function injectSwell(world, rise = 0.12, ms = 220) {
  const v = Math.round(P.V_MAINS * (1 + rise));
  for (const h of world.houses) {
    if (!h.sentinel || !h.sen.alive || !world.grid.present) continue;
    h.sen.pq.unshift({ t: world.t, type: 'SWELL', mag: Math.round(rise * 100), dur: ms, v, ride: v <= P.UPS_WIN[1] });
    if (h.sen.pq.length > 20) h.sen.pq.pop();
    log(world, h, `Grid Shield: SWELL +${Math.round(rise * 100)} % (${v} V) for ${ms} ms · logged`, 'pq');
  }
}

export function resetMcu(world, h) {
  if (!h.sentinel || !h.sen.alive) return;
  const s = h.sen;
  tick(world, h, 'MCU reset → pull-downs drop every coil → all loads ON', 'warn');
  s.alive = false; s.mode = 'reset'; s.hangAt = world.t; s.bootAt = world.t + P.REBOOT_S;
}
export function hangMcu(world, h) {
  if (!h.sentinel || !h.sen.alive) return;
  const s = h.sen;
  tick(world, h, 'Firmware hang injected — heartbeat stops', 'warn');
  s.alive = false; s.mode = 'hang'; s.hangAt = world.t; s.bootAt = world.t + 8; s.supervisorLogged = false;
}
export function setSentinel(world, h, on) {
  h.sentinel = on;
  if (!on) { h.sen.shed = { T2: false, T3: false }; }
  else { h.sen.alive = true; h.sen.mode = 'ok'; h.sen.outage = false; h.sen.s1Timer = 0; h.sen.nextEval = world.t + 2; }
}
export function overrideTier(world, h, tier, minutes = 30) {
  if (!h.sentinel || !h.sen.alive) return;
  h.sen.override = { tier, until: world.t + Math.min(minutes, 240) * 60 };
  log(world, h, `User override: keep ${tier} on for ${minutes} min`, 'info');
  evaluate(world, h, 'override');
}
export function forceAppliance(h, id, val) {
  const a = h.appliances.find((x) => x.id === id);
  if (a) a.forced = val;
}
export function jumpTo(world, clockMin, dt = 5) {
  // fast-forward the whole simulation to a clock time (keeps physics consistent)
  const target = Math.floor(world.t / 86400) * 86400 + clockMin * 60;
  let goal = target <= world.t ? target + 86400 : target;
  let n = 0;
  while (world.t < goal && n < 40000) { step(world, Math.min(dt, goal - world.t)); n++; }
}

export const gradeOf = (h) => GRADES[h.gradeIdx];
