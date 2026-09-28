import { useMemo } from 'react';

export const socColor = (soc) => (soc > 0.55 ? '#2BD67B' : soc > 0.4 ? '#FDC300' : soc > 0.25 ? '#F39200' : '#FF4D6D');

export function Icon({ name, size = 14, color = 'currentColor' }) {
  const p = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: color, strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' };
  switch (name) {
    case 'bolt': return <svg {...p}><path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z" fill={color} stroke="none" /></svg>;
    case 'battery': return <svg {...p}><rect x="2" y="7" width="17" height="10" rx="2" /><path d="M22 11v2" /><rect x="5" y="10" width="8" height="4" fill={color} stroke="none" /></svg>;
    case 'off': return <svg {...p}><circle cx="12" cy="12" r="9" /><path d="M8 8l8 8M16 8l-8 8" /></svg>;
    case 'play': return <svg {...p}><path d="M7 5v14l12-7z" fill={color} stroke="none" /></svg>;
    case 'pause': return <svg {...p}><rect x="6" y="5" width="4" height="14" fill={color} stroke="none" /><rect x="14" y="5" width="4" height="14" fill={color} stroke="none" /></svg>;
    case 'x': return <svg {...p}><path d="M6 6l12 12M18 6 6 18" /></svg>;
    case 'reset': return <svg {...p}><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /></svg>;
    case 'wave': return <svg {...p}><path d="M2 12c2-6 4-6 6 0s4 6 6 0 4-6 6 0" /></svg>;
    case 'eye': return <svg {...p}><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg>;
    case 'shield': return <svg {...p}><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z" /></svg>;
    case 'freeze': return <svg {...p}><path d="M12 2v20M4 6l16 12M20 6 4 18" /></svg>;
    case 'plug': return <svg {...p}><path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4" /></svg>;
    case 'clock': return <svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>;
    case 'house': return <svg {...p}><path d="M3 11 12 4l9 7v9H3z" /></svg>;
    case 'chip': return <svg {...p}><rect x="6" y="6" width="12" height="12" rx="1" /><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></svg>;
    default: return null;
  }
}

export function Ring({ value, size = 96, stroke = 9, color, label, sub }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="rgba(255,255,255,0.08)" strokeWidth={stroke} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={color || socColor(v)} strokeWidth={stroke} fill="none"
          strokeDasharray={`${c * v} ${c}`} strokeLinecap="round" transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dasharray .3s, stroke .3s', filter: `drop-shadow(0 0 6px ${color || socColor(v)}66)` }} />
      </svg>
      <div className="ring-in">
        <div className="ring-val">{label}</div>
        {sub && <div className="ring-sub">{sub}</div>}
      </div>
    </div>
  );
}

export function Spark({ data, w = 260, h = 54, key1 = 'soc', min = 0, max = 1, color = '#FDC300', bands }) {
  const path = useMemo(() => {
    if (!data || data.length < 2) return null;
    const t0 = data[0].t, t1 = data[data.length - 1].t || t0 + 1;
    const X = (t) => ((t - t0) / Math.max(1, t1 - t0)) * w;
    const Y = (v) => h - ((v - min) / (max - min)) * h;
    let d = '';
    data.forEach((p, i) => { d += `${i ? 'L' : 'M'}${X(p.t).toFixed(1)},${Y(p[key1]).toFixed(1)}`; });
    const outages = [];
    let start = null;
    data.forEach((p) => {
      if (!p.grid && start == null) start = p.t;
      if (p.grid && start != null) { outages.push([start, p.t]); start = null; }
    });
    if (start != null) outages.push([start, t1]);
    return { d, outages: outages.map(([a, b]) => [X(a), X(b)]), Y };
  }, [data, w, h, key1, min, max]);
  if (!path) return <svg width={w} height={h} />;
  return (
    <svg width={w} height={h} className="spark">
      {path.outages.map(([a, b], i) => <rect key={i} x={a} y={0} width={Math.max(1, b - a)} height={h} fill="rgba(34,211,238,0.10)" />)}
      {bands && bands.map((b) => (
        <line key={b.v} x1={0} x2={w} y1={path.Y(b.v)} y2={path.Y(b.v)} stroke={b.c} strokeDasharray="3 4" strokeWidth={1} opacity={0.6} />
      ))}
      <path d={path.d} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  );
}

export function Pill({ children, tone = 'muted', title }) {
  return <span className={`pill ${tone}`} title={title}>{children}</span>;
}

export const fmt = {
  v: (x) => `${x.toFixed(2)} V`,
  a: (x) => `${x >= 0 ? '+' : ''}${x.toFixed(1)} A`,
  t: (x) => `${x.toFixed(1)} °C`,
  w: (x) => `${Math.round(x)} W`,
  pct: (x) => `${Math.round(x * 100)}%`,
  h: (x) => (x == null ? '—' : x > 20 ? '>20 h' : `${Math.floor(x)} h ${String(Math.round((x % 1) * 60)).padStart(2, '0')} m`),
};

export const STATE_TEXT = {
  S1: 'Mains · pass-through + charging',
  S2: 'Transfer (< 10 ms)',
  S3: 'Battery backup',
  S4: 'Low-battery cut-off',
  S5: 'Overload trip',
  S6: 'Mains returning',
};
