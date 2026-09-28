import { useTicker } from '../sim/tick.js';
import { Icon, socColor } from './bits.jsx';
import { gradeOf } from '../sim/engine.js';

export default function HouseBadge({ world, h, onClick, hovered }) {
  useTicker(world.bus);
  const st = h.inv.state;
  const dark = st === 'S4';
  const onBatt = st === 'S3';
  const soc = h.bat.soc;
  const g = gradeOf(h);
  const tiers = ['T1', 'T2', 'T3'].map((t) => {
    const shed = h.sentinel && (t === 'T1' ? false : h.sen.shed[t] && h.sen.alive);
    return { t, state: dark ? 'dead' : shed ? 'shed' : 'on' };
  });
  return (
    <div className={`badge ${hovered ? 'hov' : ''} ${dark ? 'dark' : ''}`} onClick={onClick}>
      <div className="badge-top">
        <span className="badge-name">{h.short}</span>
        {h.sentinel ? <span className="badge-sen"><span className="sen-dot" />SENTINEL</span> : <span className="badge-nosen">NO SENTINEL</span>}
      </div>
      <div className="badge-row">
        <span className={`badge-src ${dark ? 'bad' : onBatt ? 'batt' : 'grid'}`}>
          <Icon name={dark ? 'off' : onBatt ? 'battery' : 'bolt'} size={13} />
          {dark ? 'DARK' : onBatt ? 'BACKUP' : 'MAINS'}
        </span>
        <div className="badge-soc">
          <div className="badge-soc-fill" style={{ width: `${soc * 100}%`, background: socColor(soc) }} />
        </div>
        <span className="badge-pct">{Math.round(soc * 100)}%</span>
      </div>
      <div className="badge-row">
        {tiers.map((x) => <span key={x.t} className={`tchip ${x.state}`}>{x.t}</span>)}
        {g.grade === 'REPLACE' && <span className="tchip warn">SoH {g.soh_p50}%</span>}
        {g.grade === 'DEGRADING' && <span className="tchip mid">SoH {g.soh_p50}%</span>}
      </div>
    </div>
  );
}
