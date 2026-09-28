import { memo, useContext, useEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { CameraControls, Html, Grid, Environment, Lightformer, ContactShadows } from '@react-three/drei';
import * as THREE from 'three';
import InverterModel, { PORTS } from './InverterModel.jsx';
import { Part, PartCtx } from './Part.jsx';
import { PARTS, CAM_PRESETS } from './parts.js';
import { TubularBattery, DBPanel } from '../three/Power.jsx';
import { Router, CPAP } from '../three/Appliances.jsx';
import { FlowLine } from '../three/Flow.jsx';
import { COLORS, TIER_META } from '../sim/params.js';
import { setGrid, forceAppliance } from '../sim/engine.js';
import { useTicker } from '../sim/tick.js';

const BAT_POS = [-6.4, 0, -0.4];
const WALL_Z = -6;
const MCB_POS = [4.2, 5.2, WALL_Z + 0.12];
const PANEL_POS = [9.6, 5.0, WALL_Z + 0.45];
const PANEL_S = 8;
const LOAD_X = { bulb: 6.2, router: 6.2, fan: 8.4, iron: 10.8, cpap: 13.0 };
const LOAD_Z = -2.2;
const CH_OF = { bulb: 'ch1', router: 'ch1', fan: 'ch2', iron: 'ch3', cpap: 'ch4' };
const chX = (ch) => PANEL_POS[0] + (-0.195 + ['ch1', 'ch2', 'ch3', 'ch4'].indexOf(ch) * 0.13) * PANEL_S;

function Studio() {
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[40, 64]} />
        <meshStandardMaterial color="#0C0F14" roughness={0.85} />
      </mesh>
      <Grid position={[0, 0.01, 0]} args={[80, 80]} cellSize={1} cellThickness={0.5} cellColor="#1B222C" sectionSize={5} sectionThickness={1} sectionColor="#2A3340" fadeDistance={45} fadeStrength={1.5} infiniteGrid />
      {/* wall */}
      <mesh position={[3, 5, WALL_Z - 0.1]} receiveShadow>
        <boxGeometry args={[30, 10, 0.2]} />
        <meshStandardMaterial color="#1A1F27" roughness={0.9} />
      </mesh>
      {Array.from({ length: 7 }).map((_, i) => (
        <mesh key={i} position={[-11 + i * 4.5, 5, WALL_Z + 0.005]}>
          <planeGeometry args={[0.02, 10]} />
          <meshStandardMaterial color="#232A34" />
        </mesh>
      ))}
      {/* inverter stand */}
      <mesh position={[0, 0.2, 0]} castShadow receiveShadow>
        <boxGeometry args={[4.6, 0.02, 3.8]} />
        <meshStandardMaterial color="#20262F" metalness={0.4} roughness={0.5} />
      </mesh>
      {/* battery tray */}
      <mesh position={[BAT_POS[0], 0.08, BAT_POS[2]]} receiveShadow castShadow>
        <boxGeometry args={[5.8, 0.16, 2.6]} />
        <meshStandardMaterial color="#2A2F37" roughness={0.7} />
      </mesh>
    </group>
  );
}

function MCBBox({ world }) {
  const lever = useRef();
  const ind = useRef();
  useFrame((_, dt) => {
    const on = world.grid.manual !== 'off';
    if (lever.current) lever.current.rotation.x += ((on ? -0.5 : 0.5) - lever.current.rotation.x) * Math.min(1, dt * 18);
    if (ind.current) { ind.current.emissive.set(on ? '#2BD67B' : '#FF4D6D'); ind.current.emissiveIntensity = 2.5; }
  });
  return (
    <Part id="MCB">
      <group position={MCB_POS} onClick={(e) => { e.stopPropagation(); setGrid(world, world.grid.manual === 'off' ? 'on' : 'off'); }}>
        <mesh castShadow>
          <boxGeometry args={[2.2, 2.6, 0.5]} />
          <meshStandardMaterial color="#D9DDE2" metalness={0.35} roughness={0.45} />
        </mesh>
        <mesh position={[0, 0, 0.26]}>
          <planeGeometry args={[1.9, 2.3]} />
          <meshStandardMaterial color="#2B3038" />
        </mesh>
        <mesh position={[0, 0.1, 0.4]} castShadow>
          <boxGeometry args={[0.7, 1.4, 0.3]} />
          <meshStandardMaterial color="#F5F5F2" roughness={0.4} />
        </mesh>
        <group ref={lever} position={[0, 0.15, 0.56]}>
          <mesh position={[0, 0.18, 0]}>
            <boxGeometry args={[0.26, 0.4, 0.16]} />
            <meshStandardMaterial color="#1d1d1f" />
          </mesh>
        </group>
        <mesh position={[0, -0.8, 0.27]}>
          <circleGeometry args={[0.08, 16]} />
          <meshStandardMaterial ref={ind} color="#111" emissive="#2BD67B" toneMapped={false} />
        </mesh>
        <mesh position={[0, 1.3, 0]} rotation={[0, 0, 0]}>
          <boxGeometry args={[0.18, 1.2, 0.18]} />
          <meshStandardMaterial color="#333" />
        </mesh>
      </group>
    </Part>
  );
}

function TableFan({ ap, position }) {
  const blades = useRef();
  const head = useRef();
  const spd = useRef(0);
  useFrame(({ clock }, dt) => {
    spd.current += ((ap && ap.powered ? 20 : 0) - spd.current) * Math.min(1, dt * 1.2);
    if (blades.current) blades.current.rotation.z += spd.current * dt;
    if (head.current) head.current.rotation.y = ap && ap.powered ? Math.sin(clock.elapsedTime * 0.4) * 0.5 : head.current.rotation.y;
  });
  return (
    <group position={position}>
      <mesh position={[0, 0.12, 0]} castShadow>
        <cylinderGeometry args={[0.9, 1.0, 0.24, 28]} />
        <meshStandardMaterial color="#E9ECEF" roughness={0.4} />
      </mesh>
      <mesh position={[0, 1.4, 0]} castShadow>
        <cylinderGeometry args={[0.1, 0.12, 2.5, 12]} />
        <meshStandardMaterial color="#D0D4DA" metalness={0.6} roughness={0.3} />
      </mesh>
      <group ref={head} position={[0, 2.9, 0]}>
        <mesh position={[0, 0, -0.45]} rotation={[Math.PI / 2, 0, 0]} castShadow>
          <cylinderGeometry args={[0.4, 0.45, 0.8, 20]} />
          <meshStandardMaterial color="#E9ECEF" roughness={0.35} />
        </mesh>
        <group ref={blades} position={[0, 0, 0.1]}>
          {[0, 1, 2].map((i) => (
            <mesh key={i} rotation={[0, 0.35, (i * Math.PI * 2) / 3]} position={[0, 0, 0]}>
              <boxGeometry args={[0.45, 1.5, 0.04]} />
              <meshStandardMaterial color="#35A6FF" transparent opacity={0.8} />
            </mesh>
          ))}
        </group>
        {[0.3, 0.8, 1.25].map((r) => (
          <mesh key={r} position={[0, 0, 0.18]}>
            <torusGeometry args={[r, 0.025, 6, 40]} />
            <meshStandardMaterial color="#D0D4DA" metalness={0.7} />
          </mesh>
        ))}
        {Array.from({ length: 12 }).map((_, i) => (
          <mesh key={i} position={[Math.cos((i / 12) * Math.PI * 2) * 0.65, Math.sin((i / 12) * Math.PI * 2) * 0.65, 0.18]} rotation={[0, 0, (i / 12) * Math.PI * 2]}>
            <boxGeometry args={[1.25, 0.02, 0.02]} />
            <meshStandardMaterial color="#D0D4DA" metalness={0.7} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

function Lamp({ ap, position }) {
  const m = useRef();
  const l = useRef();
  const lv = useRef(0);
  useFrame((_, dt) => {
    lv.current += ((ap && ap.powered ? 1 : 0) - lv.current) * Math.min(1, dt * 14);
    if (m.current) m.current.emissiveIntensity = 0.05 + lv.current * 7;
    if (l.current) l.current.intensity = lv.current * 30;
  });
  return (
    <group position={position}>
      <mesh position={[0, 0.1, 0]} castShadow>
        <cylinderGeometry args={[0.55, 0.6, 0.2, 24]} />
        <meshStandardMaterial color="#2A2E35" />
      </mesh>
      <mesh position={[0, 1.1, 0]}>
        <cylinderGeometry args={[0.05, 0.05, 1.9, 8]} />
        <meshStandardMaterial color="#C0C0C0" metalness={0.8} />
      </mesh>
      <mesh position={[0, 2.15, 0]}>
        <cylinderGeometry args={[0.2, 0.28, 0.35, 16]} />
        <meshStandardMaterial color="#ddd" />
      </mesh>
      <mesh position={[0, 2.75, 0]}>
        <sphereGeometry args={[0.55, 24, 24]} />
        <meshStandardMaterial ref={m} color="#fff" emissive="#FFD9A0" emissiveIntensity={0} toneMapped={false} />
      </mesh>
      <pointLight ref={l} position={[0, 2.8, 0.6]} color="#FFD9A0" intensity={0} distance={9} decay={1.5} />
    </group>
  );
}

function Iron({ ap, position }) {
  const plate = useRef();
  const lv = useRef(0);
  useFrame((_, dt) => {
    lv.current += ((ap && ap.powered ? 1 : 0) - lv.current) * Math.min(1, dt * 1.2);
    if (plate.current) plate.current.emissiveIntensity = lv.current * 3.5;
  });
  return (
    <group position={position}>
      <mesh position={[0, 0.18, 0]} castShadow>
        <boxGeometry args={[2.4, 0.35, 1.2]} />
        <meshStandardMaterial ref={plate} color="#C9CCD1" metalness={0.8} roughness={0.2} emissive="#FF5A1F" emissiveIntensity={0} toneMapped={false} />
      </mesh>
      <mesh position={[-0.1, 0.6, 0]} castShadow>
        <boxGeometry args={[2.0, 0.55, 1.0]} />
        <meshStandardMaterial color="#E24B4B" roughness={0.35} />
      </mesh>
      <mesh position={[-0.25, 1.15, 0]} castShadow>
        <boxGeometry args={[1.4, 0.26, 0.34]} />
        <meshStandardMaterial color="#222" />
      </mesh>
    </group>
  );
}

function Pedestal({ x, w = 2.6, hgt = 1.6 }) {
  return (
    <mesh position={[x, hgt / 2, LOAD_Z]} castShadow receiveShadow>
      <boxGeometry args={[w, hgt, 2.4]} />
      <meshStandardMaterial color="#1F242C" roughness={0.7} />
    </mesh>
  );
}

function LoadTag({ world, h, ch, pos }) {
  useTicker(world.bus);
  const c = h.circuits[ch];
  const shed = h.coils && h.coils[ch];
  const aps = h.appliances.filter((a) => a.circuit === ch);
  const on = aps.some((a) => a.powered);
  return (
    <Html position={pos} center distanceFactor={14} zIndexRange={[20, 0]}>
      <div className={`load-tag ${shed ? 'shed' : on ? 'on' : 'off'}`}>
        <span className="lt-ch">{ch.toUpperCase()}</span>
        <span className="lt-tier" style={{ background: TIER_META[c.tier].color }}>{c.tier}</span>
        <span className="lt-st">{shed ? 'SHED' : on ? 'ON' : 'OFF'}</span>
        <div className="lt-names">{aps.map((a) => (
          <button key={a.id} className={a.demand ? 'on' : ''} onClick={(e) => { e.stopPropagation(); forceAppliance(h, a.id, a.demand ? false : true); world.bus.emit(); }}>
            {a.name} {a.w} W
          </button>
        ))}</div>
      </div>
    </Html>
  );
}

function PartLabel() {
  const { hov, sel } = useContext(PartCtx);
  const p = hov || sel;
  if (!p) return null;
  const info = PARTS[p.id];
  if (!info) return null;
  return (
    <Html position={p.pos} center zIndexRange={[40, 0]} style={{ pointerEvents: 'none', transform: 'translateY(-26px)' }}>
      <div className={`part-tag g-${info.grp}`}><b>{p.id}</b> {info.name}</div>
    </Html>
  );
}

function CameraRig({ controls, view }) {
  useEffect(() => {
    const c = controls.current;
    const p = CAM_PRESETS[view];
    if (c && p) c.setLookAt(...p.pos, ...p.look, true);
  }, [view, controls]);
  return null;
}

function BenchScene({ world, casing, view }) {
  const h = world.houses[0];
  const controls = useRef();
  const byId = useMemo(() => Object.fromEntries(h.appliances.map((a) => [a.id, a])), [h]);
  const batTerm = (sx) => [BAT_POS[0] + sx * 0.21 * 10, 4.2, BAT_POS[2] - 0.55];
  const convOn = () => {
    const s = h.inv.state;
    if (s === 'S3' || s === 'S6') return { on: true, color: COLORS.battery, dir: 1, speed: 0.8 + Math.abs(h.bat.i) / 20 };
    if (s === 'S1' && h.bat.i > 0.5) return { on: true, color: COLORS.grid, dir: -1, speed: 0.6 + h.bat.i / 10 };
    return { on: false };
  };
  const cables = useMemo(() => ({
    pos: [batTerm(1), [BAT_POS[0] + 2.1, 4.8, BAT_POS[2] - 0.55], [BAT_POS[0] + 2.1, 4.8, -2.6], [-0.1, 2.2, -2.6], [-0.1, 0.8, -2.2], PORTS.batPlus],
    neg: [batTerm(-1), [BAT_POS[0] - 2.1, 5.0, BAT_POS[2] - 0.55], [BAT_POS[0] - 2.1, 5.0, -2.9], [-0.6, 2.4, -2.9], [-0.6, 0.8, -2.3], PORTS.batMinus],
    ntc: [PORTS.ntc, [-1.3, 2.6, -2.4], [BAT_POS[0] - 2.1, 5.4, -2.4], [BAT_POS[0] - 2.1, 5.4, BAT_POS[2] - 0.3], [BAT_POS[0] - 2.1, 4.45, BAT_POS[2] - 0.35]],
    mains: [[MCB_POS[0], MCB_POS[1] - 1.3, MCB_POS[2] + 0.1], [MCB_POS[0], 0.15, WALL_Z + 0.3], [PORTS.acIn[0], 0.15, WALL_Z + 0.3], [PORTS.acIn[0], 0.15, -2.4], [PORTS.acIn[0], PORTS.acIn[1], -2.4], PORTS.acIn],
    acOut: [PORTS.acOut, [PORTS.acOut[0], 3.1, -2.2], [PORTS.acOut[0], 3.1, WALL_Z + 0.3], [PANEL_POS[0] - 1.8, 3.1, WALL_Z + 0.3], [PANEL_POS[0] - 1.8, PANEL_POS[1] - 0.2, WALL_Z + 0.3]],
    coil: [PORTS.coil, [PORTS.coil[0], 2.7, -2.0], [PORTS.coil[0], 2.7, WALL_Z + 0.35], [PANEL_POS[0] - 2.2, 2.7, WALL_Z + 0.35], [PANEL_POS[0] - 2.2, PANEL_POS[1], WALL_Z + 0.35]],
  }), []);
  const loadLines = useMemo(() => Object.entries(LOAD_X).map(([id, x], i) => {
    const ch = CH_OF[id];
    const cx = chX(ch) + (id === 'router' ? 0.25 : 0);
    const top = id === 'router' ? 1.7 : id === 'fan' ? 0.3 : id === 'iron' ? 1.7 : id === 'cpap' ? 1.7 : 0.4;
    return {
      id,
      pts: [[cx, PANEL_POS[1] - 2.6, WALL_Z + 0.4], [cx, 0.12, WALL_Z + 0.4 + i * 0.05], [x + (id === 'router' ? 0.9 : 0), 0.12, WALL_Z + 0.4 + i * 0.05], [x + (id === 'router' ? 0.9 : 0), 0.12, LOAD_Z - 1.0], [x + (id === 'router' ? 0.9 : 0), top, LOAD_Z - 1.0]],
    };
  }), []);

  return (
    <>
      <color attach="background" args={['#07090D']} />
      <fog attach="fog" args={['#07090D', 30, 70]} />
      <ambientLight intensity={0.25} />
      <directionalLight position={[8, 16, 10]} intensity={1.6} castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-18} shadow-camera-right={18} shadow-camera-top={18} shadow-camera-bottom={-18} shadow-bias={-0.0004} />
      <directionalLight position={[-10, 8, -4]} intensity={0.6} color="#8FB8FF" />
      <spotLight position={[0, 12, 4]} angle={0.45} penumbra={0.8} intensity={60} distance={30} color="#FFF3DA" />
      <Environment resolution={256} frames={1}>
        <Lightformer form="rect" intensity={2} position={[0, 6, 6]} scale={[12, 4, 1]} />
        <Lightformer form="rect" intensity={1.2} color="#FDC300" position={[-8, 3, 0]} rotation-y={Math.PI / 2} scale={[6, 2, 1]} />
        <Lightformer form="rect" intensity={1} color="#8FB8FF" position={[8, 4, -4]} rotation-y={-Math.PI / 2} scale={[8, 3, 1]} />
        <Lightformer form="ring" intensity={1.5} position={[0, 8, -2]} scale={3} />
      </Environment>

      <Studio />
      <InverterModel world={world} casing={casing} />

      <Part id="B1">
        <TubularBattery h={h} position={BAT_POS} scale={10} />
      </Part>
      <Part id="X2">
        <mesh position={[BAT_POS[0] - 2.1, 4.45, BAT_POS[2] - 0.35]}>
          <sphereGeometry args={[0.13, 14, 14]} />
          <meshStandardMaterial color="#C084FC" emissive="#C084FC" emissiveIntensity={0.8} />
        </mesh>
      </Part>

      <MCBBox world={world} />
      <Part id="X7">
        <DBPanel h={h} world={world} position={PANEL_POS} scale={PANEL_S} />
      </Part>

      {/* loads */}
      <Pedestal x={LOAD_X.bulb + 0.45} w={3.2} />
      <Lamp ap={byId.bulb} position={[LOAD_X.bulb - 0.4, 1.6, LOAD_Z]} />
      <group position={[LOAD_X.router + 0.9, 1.63, LOAD_Z]} scale={6}>
        <Router ap={byId.router} position={[0, 0, 0]} rotation={[0, -0.3, 0]} />
      </group>
      <TableFan ap={byId.fan} position={[LOAD_X.fan, 0, LOAD_Z]} />
      <Pedestal x={LOAD_X.iron} />
      <Iron ap={byId.iron} position={[LOAD_X.iron, 1.6, LOAD_Z]} />
      <Pedestal x={LOAD_X.cpap} />
      <group position={[LOAD_X.cpap, 1.6 + 0.65, LOAD_Z]} scale={10}>
        <CPAP ap={byId.cpap} position={[0, 0, 0]} rotation={[0, -0.4, 0]} />
      </group>
      <LoadTag world={world} h={h} ch="ch1" pos={[LOAD_X.bulb + 0.3, 4.6, LOAD_Z]} />
      <LoadTag world={world} h={h} ch="ch2" pos={[LOAD_X.fan, 5.0, LOAD_Z]} />
      <LoadTag world={world} h={h} ch="ch3" pos={[LOAD_X.iron, 3.8, LOAD_Z]} />
      <LoadTag world={world} h={h} ch="ch4" pos={[LOAD_X.cpap, 4.3, LOAD_Z]} />
      {/* Router scaled for bench */}

      {/* external wiring */}
      <FlowLine points={cables.pos} radius={0.09} wireColor="#8E1F1F" count={8} pRadius={0.12} state={() => { const s = convOn(); return s.on ? { ...s, dir: -(s.dir || 1) } : s; }} />
      <FlowLine points={cables.neg} radius={0.09} wireColor="#1b1b1b" count={8} pRadius={0.12} state={convOn} />
      <FlowLine points={cables.ntc} radius={0.03} wireColor="#4b2f66" count={6} pRadius={0.06} state={() => ({ on: h.sen.alive, color: COLORS.data, speed: 0.6 })} />
      <FlowLine points={cables.mains} radius={0.06} wireColor="#3a3f48" count={10} pRadius={0.1} state={() => ({ on: world.grid.v > 90, color: COLORS.grid, speed: 1.2 })} />
      <FlowLine points={cables.acOut} radius={0.06} wireColor="#3a3f48" count={10} pRadius={0.1}
        state={() => ({ on: ['S1', 'S3', 'S6'].includes(h.inv.state) && h.stats.pOut > 0, color: ['S3', 'S6'].includes(h.inv.state) ? COLORS.battery : COLORS.grid, speed: 0.8 + h.stats.pOut / 300 })} />
      <FlowLine points={cables.coil} radius={0.035} wireColor="#4b2f66" count={8} pRadius={0.07}
        state={() => ({ on: h.sen.alive && Object.values(h.coils || {}).some(Boolean), color: '#FF4D6D', speed: 0.8 })} />
      {loadLines.map(({ id, pts }) => (
        <FlowLine key={id} points={pts} radius={0.04} wireColor="#2a2f3a" count={7} pRadius={0.08}
          state={() => ({ on: byId[id].powered, color: ['S3', 'S6'].includes(h.inv.state) ? COLORS.battery : COLORS.grid, speed: 0.6 + byId[id].w / 200 })} />
      ))}

      <ContactShadows position={[0, 0.02, 0]} opacity={0.5} scale={40} blur={2.4} far={8} />
      <PartLabel />
      <CameraControls ref={controls} makeDefault minDistance={1.2} maxDistance={60} maxPolarAngle={1.5} smoothTime={0.55} />
      <CameraRig controls={controls} view={view} />
    </>
  );
}

export default memo(BenchScene);
