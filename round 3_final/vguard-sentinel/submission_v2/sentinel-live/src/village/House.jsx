import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import {
  CeilingFan, TubeLight, Bulb, TV, Sofa, Bed, Fridge, Counter, Router, Table, Laptop,
  IroningBoard, CPAP, ACIndoor, ACOutdoor, Shelf, Plant,
} from '../three/Appliances.jsx';
import { TubularBattery, InverterBox, SentinelBox, DBPanel, Shunt, CTClamp } from '../three/Power.jsx';
import { FlowLine } from '../three/Flow.jsx';
import { COLORS } from '../sim/params.js';

const W = 9.2, D = 8.2, FLOOR = 0.3, WALL_TOP = 3.3, WALL_H = WALL_TOP - FLOOR;
export const METER_LOCAL = [-3.8, 2.05, 4.28];

// ---------- procedural textures ----------
let tileTex = null;
function getTileTexture() {
  if (tileTex) return tileTex;
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const g = c.getContext('2d');
  g.fillStyle = '#ffffff';
  g.fillRect(0, 0, 256, 256);
  for (let row = 0; row < 4; row++) {
    const y = row * 64;
    const grad = g.createLinearGradient(0, y, 0, y + 64);
    grad.addColorStop(0, '#f2f2f2');
    grad.addColorStop(0.75, '#d9d9d9');
    grad.addColorStop(1, '#8a8a8a');
    g.fillStyle = grad;
    g.fillRect(0, y, 256, 64);
    const off = row % 2 ? 32 : 0;
    g.fillStyle = 'rgba(0,0,0,0.28)';
    for (let x = -64; x < 320; x += 64) g.fillRect(x + off, y, 3, 64);
  }
  tileTex = new THREE.CanvasTexture(c);
  tileTex.wrapS = tileTex.wrapT = THREE.RepeatWrapping;
  tileTex.repeat.set(1.6, 1.6);
  tileTex.colorSpace = THREE.SRGBColorSpace;
  tileTex.anisotropy = 8;
  return tileTex;
}
let floorTexCache = {};
function getFloorTexture(a, b) {
  const key = a + b;
  if (floorTexCache[key]) return floorTexCache[key];
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
    g.fillStyle = (i + j) % 2 ? a : b;
    g.fillRect(i * 32, j * 32, 32, 32);
  }
  g.strokeStyle = 'rgba(0,0,0,0.12)';
  for (let i = 0; i <= 4; i++) { g.beginPath(); g.moveTo(i * 32, 0); g.lineTo(i * 32, 128); g.stroke(); g.beginPath(); g.moveTo(0, i * 32); g.lineTo(128, i * 32); g.stroke(); }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(2, 2);
  t.colorSpace = THREE.SRGBColorSpace;
  floorTexCache[key] = t;
  return t;
}

// ---------- hip roof built from 4 shaped faces ----------
function HipRoof({ color, overhang = 0.6, height = 2.1, mat }) {
  const Wb = W + overhang * 2, Db = D + overhang * 2, L = Wb - Db;
  const s = Math.sqrt((Db / 2) ** 2 + height ** 2);
  const phi = -Math.atan2(Db / 2, height);
  const trap = useMemo(() => {
    const sh = new THREE.Shape();
    sh.moveTo(-Wb / 2, 0); sh.lineTo(Wb / 2, 0); sh.lineTo(L / 2, s); sh.lineTo(-L / 2, s); sh.closePath();
    return new THREE.ShapeGeometry(sh);
  }, [Wb, L, s]);
  const tri = useMemo(() => {
    const sh = new THREE.Shape();
    sh.moveTo(-Db / 2, 0); sh.lineTo(Db / 2, 0); sh.lineTo(0, s); sh.closePath();
    return new THREE.ShapeGeometry(sh);
  }, [Db, s]);
  return (
    <group>
      {[0, Math.PI].map((ry) => (
        <group key={ry} rotation={[0, ry, 0]}>
          <mesh geometry={trap} material={mat} position={[0, 0, Db / 2]} rotation={[phi, 0, 0]} castShadow receiveShadow />
        </group>
      ))}
      {[Math.PI / 2, -Math.PI / 2].map((ry) => (
        <group key={ry} rotation={[0, ry, 0]}>
          <mesh geometry={tri} material={mat} position={[0, 0, Wb / 2]} rotation={[phi, 0, 0]} castShadow receiveShadow />
        </group>
      ))}
      <mesh position={[0, height + 0.03, 0]} material={mat}>
        <boxGeometry args={[L + 0.1, 0.12, 0.22]} />
      </mesh>
      {/* fascia board */}
      <mesh position={[0, -0.08, 0]}>
        <boxGeometry args={[Wb + 0.02, 0.16, Db + 0.02]} />
        <meshStandardMaterial color="#5a3322" transparent opacity={1} />
      </mesh>
    </group>
  );
}

function Window({ position, rotation, w = 1.2, h = 1.2, mat, trim }) {
  return (
    <group position={position} rotation={rotation}>
      <mesh>
        <boxGeometry args={[w + 0.14, h + 0.14, 0.06]} />
        <meshStandardMaterial color={trim} roughness={0.6} />
      </mesh>
      <mesh position={[0, 0, 0.032]} material={mat}>
        <planeGeometry args={[w, h]} />
      </mesh>
      <mesh position={[0, 0, 0.04]}>
        <boxGeometry args={[0.04, h, 0.02]} />
        <meshStandardMaterial color={trim} />
      </mesh>
      {[-h / 4, h / 4].map((y) => (
        <mesh key={y} position={[0, y, 0.045]}>
          <boxGeometry args={[w, 0.025, 0.015]} />
          <meshStandardMaterial color="#333" metalness={0.6} />
        </mesh>
      ))}
      {/* concrete sunshade (chajja) */}
      <mesh position={[0, h / 2 + 0.22, 0.24]} castShadow>
        <boxGeometry args={[w + 0.6, 0.07, 0.5]} />
        <meshStandardMaterial color="#e9e4da" />
      </mesh>
    </group>
  );
}

// ---------- appliance slots (local coords, front = +z) ----------
const SLOTS = {
  hallTube: { anchor: [-2.25, 3.15, 0.4] },
  hallFan: { anchor: [-2.25, 3.3, 2.2] },
  tv: { anchor: [-4.35, 1.2, 2.0] },
  bedFan: { anchor: [2.25, 3.3, 2.2] },
  bedBulb: { anchor: [1.2, 3.3, 3.3] },
  kitBulb: { anchor: [-2.25, 3.3, -2.0] },
  fridge: { anchor: [-4.25, 1.75, -3.55] },
  router: { anchor: [4.05, 0.85, -0.95] },
  laptop: { anchor: [3.75, 0.85, -0.95] },
  iron: { anchor: [2.35, 0.95, -1.55] },
  cpap: { anchor: [3.95, 0.95, 3.55] },
  ac: { anchor: [4.45, 2.6, 2.2] },
};
const CH_X = { ch1: 3.11, ch2: 3.3, ch3: 3.5, ch4: 3.69, NI: 2.9 };
const DB_POS = [3.4, 1.75, -3.94];

function circuitPath(chX, anchor, k) {
  const yc = 3.18 - (k % 5) * 0.035;
  const zOff = (k % 7) * 0.05;
  const startY = 2.25;
  const [ax, ay, az] = anchor;
  const zRun = Math.min(3.6, Math.max(-3.6, az)) + (az > 0 ? -zOff : zOff);
  return [
    [chX, startY, -3.9], [chX, yc, -3.9], [chX, yc, zRun], [ax, yc, zRun], [ax, yc, az], [ax, ay, az],
  ];
}

export default function House({ h, world, interior, focused, xray, onSelect, hovered, setHovered }) {
  const reveal = useRef(0);
  const roof = useRef();
  const frontMat = useMemo(() => new THREE.MeshStandardMaterial({ color: h.wall, roughness: 0.85, transparent: true }), [h.wall]);
  const sideMat = useMemo(() => new THREE.MeshStandardMaterial({ color: h.wall, roughness: 0.85, transparent: true }), [h.wall]);
  const partMat = useMemo(() => new THREE.MeshStandardMaterial({ color: '#F4F1EA', roughness: 0.9, transparent: true }), []);
  const backMat = useMemo(() => new THREE.MeshStandardMaterial({ color: h.wall, roughness: 0.85 }), [h.wall]);
  const roofMat = useMemo(() => {
    const m = new THREE.MeshStandardMaterial({ color: h.roof, roughness: 0.75, transparent: true, side: THREE.DoubleSide });
    if (h.style === 'hip') m.map = getTileTexture();
    return m;
  }, [h.roof, h.style]);
  const winMats = useMemo(() => {
    const mk = () => new THREE.MeshStandardMaterial({ color: '#1f2c3d', emissive: '#FFC977', emissiveIntensity: 0, roughness: 0.15, metalness: 0.3, toneMapped: false });
    return { hall: mk(), bed: mk(), kitchen: mk(), utility: mk() };
  }, []);
  const winGroup = useRef();
  const glass = useRef();

  const byId = useMemo(() => Object.fromEntries(h.appliances.map((a) => [a.id, a])), [h]);
  const roomLight = useMemo(() => ({
    hall: [byId.hallTube, byId.tv].filter(Boolean),
    bed: [byId.bedBulb, byId.cpap].filter(Boolean),
    kitchen: [byId.kitBulb].filter(Boolean),
    utility: [byId.laptop].filter(Boolean),
  }), [byId]);

  const open = focused || xray;
  useFrame((state, dt) => {
    const target = open ? 1 : 0;
    reveal.current += (target - reveal.current) * Math.min(1, dt * 3.5);
    const r = reveal.current;
    frontMat.opacity = 1 - r;
    frontMat.visible = r < 0.98;
    frontMat.depthWrite = r < 0.05;
    sideMat.opacity = 1 - r * 0.84;
    sideMat.depthWrite = r < 0.05;
    partMat.opacity = 1 - r * 0.7;
    partMat.depthWrite = r < 0.05;
    roofMat.opacity = 1 - r;
    roofMat.depthWrite = r < 0.05;
    if (roof.current) {
      roof.current.position.y = WALL_TOP + r * 6;
      roof.current.visible = r < 0.97;
    }
    if (winGroup.current) winGroup.current.visible = r < 0.4;
    const night = state.scene.userData.night ?? 0;
    for (const [room, list] of Object.entries(roomLight)) {
      const lit = list.some((a) => a.powered);
      const m = winMats[room];
      const tgt = lit ? 0.4 + night * 2.2 : 0;
      m.emissiveIntensity += (tgt - m.emissiveIntensity) * Math.min(1, dt * 8);
    }
  });

  const isHip = h.style === 'hip';
  const src = () => (h.inv.state === 'S3' ? COLORS.battery : COLORS.grid);

  // appliance flow lines
  const flows = useMemo(() => {
    if (!interior) return [];
    let k = 0;
    return h.appliances.filter((a) => SLOTS[a.id]).map((a) => {
      const chX = CH_X[a.circuit] + (a.circuit === 'NI' ? 0 : 0);
      const pts = circuitPath(chX, SLOTS[a.id].anchor, k++);
      return { a, pts };
    });
  }, [h, interior]);

  const dcPlus = useMemo(() => [[1.215, 0.93, -3.68], [1.215, 1.18, -3.8], [1.69, 1.18, -3.8]], []);
  const dcMinus = [[0.585, 0.93, -3.68], [0.585, 1.02, -3.86], [1.0, 1.02, -3.9]];
  const dcMinus2 = [[1.2, 1.02, -3.9], [1.66, 1.12, -3.82]];
  const svc = useMemo(() => [METER_LOCAL, [-3.8, 3.2, 3.95], [-3.8, 3.2, -3.72], [3.4, 3.2, -3.72], [3.4, 2.46, -3.9]], []);
  const acIn = useMemo(() => [[2.7, 1.55, -3.9], [2.2, 1.55, -3.9], [2.2, 1.3, -3.78], [2.1, 1.3, -3.72]], []);
  const acOut = useMemo(() => [[2.1, 1.14, -3.72], [2.55, 1.14, -3.86], [2.9, 1.3, -3.9]], []);
  const kelvin = useMemo(() => [[1.1, 1.04, -3.92], [1.1, 1.3, -3.96], [1.05, 1.4, -3.96]], []);
  const ntc = useMemo(() => [[0.585, 0.97, -3.66], [0.585, 1.45, -3.93], [0.93, 1.45, -3.96]], []);
  const ctLine = useMemo(() => [[2.55, 1.2, -3.9], [2.55, 1.62, -3.97], [1.2, 1.62, -3.97], [1.2, 1.5, -3.97]], []);
  const coil = useMemo(() => [[1.2, 1.57, -3.97], [1.2, 2.05, -3.97], [3.1, 2.05, -3.97], [3.1, 1.95, -3.95]], []);

  const liveOn = () => h.inv.state === 'S1' || h.inv.state === 'S3' || h.inv.state === 'S6';
  const dataOn = () => ({ on: h.sentinel && h.sen.alive, color: COLORS.data, speed: 0.6 });

  return (
    <group
      position={h.pos}
      rotation={[0, h.rot, 0]}
      onClick={(e) => { e.stopPropagation(); onSelect && onSelect(h.id); }}
      onPointerOver={(e) => { e.stopPropagation(); setHovered && setHovered(h.id); document.body.style.cursor = 'pointer'; }}
      onPointerOut={() => { setHovered && setHovered(null); document.body.style.cursor = ''; }}
    >
      {/* plinth + steps */}
      <mesh position={[0, FLOOR / 2, 0]} receiveShadow castShadow>
        <boxGeometry args={[W + 0.4, FLOOR, D + 0.4]} />
        <meshStandardMaterial color="#B9B2A5" roughness={0.9} />
      </mesh>
      {[0, 1].map((i) => (
        <mesh key={i} position={[-1.0, 0.1 + i * 0.1, D / 2 + 0.5 - i * 0.25]} receiveShadow>
          <boxGeometry args={[1.6, 0.2 + i * 0.2 - i * 0.1, 0.5]} />
          <meshStandardMaterial color="#A9A295" />
        </mesh>
      ))}
      {/* floors */}
      {[
        ['hall', [-2.25, 2], '#E9DCC3', '#DDCCAE'], ['bed', [2.25, 2], '#C89B6D', '#B98B5E'],
        ['kitchen', [-2.25, -2], '#D7DCE0', '#C4CBD1'], ['utility', [2.25, -2], '#CFC8BC', '#C1B9AC'],
      ].map(([k, [x, z], a, b]) => (
        <mesh key={k} position={[x, FLOOR + 0.005, z]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
          <planeGeometry args={[4.4, 3.95]} />
          <meshStandardMaterial map={getFloorTexture(a, b)} roughness={0.7} />
        </mesh>
      ))}

      {/* exterior walls */}
      <mesh position={[0, FLOOR + WALL_H / 2, -D / 2]} material={backMat} castShadow receiveShadow>
        <boxGeometry args={[W, WALL_H, 0.2]} />
      </mesh>
      {[-1, 1].map((sx) => (
        <mesh key={sx} position={[(sx * W) / 2, FLOOR + WALL_H / 2, 0]} material={sideMat} castShadow receiveShadow>
          <boxGeometry args={[0.2, WALL_H, D]} />
        </mesh>
      ))}
      <mesh position={[0, FLOOR + WALL_H / 2, D / 2]} material={frontMat} castShadow receiveShadow>
        <boxGeometry args={[W, WALL_H, 0.2]} />
      </mesh>
      {/* skirting band */}
      <mesh position={[0, FLOOR + 0.2, -D / 2 - 0.105]}>
        <boxGeometry args={[W, 0.4, 0.02]} />
        <meshStandardMaterial color={h.trim} />
      </mesh>

      {/* partitions */}
      {[[-3.7, 1.6], [-0.5, 2.8], [3.2, 2.6]].map(([x, w], i) => (
        <mesh key={'pz' + i} position={[x, FLOOR + WALL_H / 2, 0]} material={partMat}>
          <boxGeometry args={[w, WALL_H, 0.12]} />
        </mesh>
      ))}
      {[[-3.3, 1.4], [-0.8, 1.6], [0.6, 1.2], [3.1, 1.8]].map(([z, w], i) => (
        <mesh key={'px' + i} position={[0, FLOOR + WALL_H / 2, z]} material={partMat}>
          <boxGeometry args={[0.12, WALL_H, w]} />
        </mesh>
      ))}

      {/* windows + door (outside surfaces) */}
      <group ref={winGroup}>
        <Window position={[-3.0, 1.9, D / 2 + 0.11]} mat={winMats.hall} trim={h.trim} />
        <Window position={[2.4, 1.9, D / 2 + 0.11]} mat={winMats.bed} trim={h.trim} w={1.5} />
        <Window position={[-W / 2 - 0.11, 1.9, 2.2]} rotation={[0, -Math.PI / 2, 0]} mat={winMats.hall} trim={h.trim} />
        <Window position={[-W / 2 - 0.11, 1.9, -2.2]} rotation={[0, -Math.PI / 2, 0]} mat={winMats.kitchen} trim={h.trim} w={1.0} h={1.0} />
        <Window position={[W / 2 + 0.11, 1.9, 2.2]} rotation={[0, Math.PI / 2, 0]} mat={winMats.bed} trim={h.trim} />
        <Window position={[W / 2 + 0.11, 2.2, -2.2]} rotation={[0, Math.PI / 2, 0]} mat={winMats.utility} trim={h.trim} w={0.8} h={0.6} />
        {/* door */}
        <mesh position={[-1.0, FLOOR + 1.1, D / 2 + 0.11]}>
          <boxGeometry args={[1.05, 2.2, 0.06]} />
          <meshStandardMaterial color="#6B3F24" roughness={0.6} />
        </mesh>
        {[0.45, 1.05, 1.65].map((y) => (
          <mesh key={y} position={[-1.0, FLOOR + y, D / 2 + 0.145]}>
            <boxGeometry args={[0.8, 0.45, 0.01]} />
            <meshStandardMaterial color="#5a341d" />
          </mesh>
        ))}
        <mesh position={[-1.0, FLOOR + 2.45, D / 2 + 0.3]} castShadow>
          <boxGeometry args={[1.7, 0.07, 0.6]} />
          <meshStandardMaterial color="#e9e4da" />
        </mesh>
        {/* meter box (E1) */}
        <mesh position={[METER_LOCAL[0], METER_LOCAL[1], METER_LOCAL[2] - 0.08]}>
          <boxGeometry args={[0.35, 0.45, 0.14]} />
          <meshStandardMaterial color="#9ea5ad" metalness={0.3} />
        </mesh>
        {h.sentinel && (
          <group position={[-0.15, FLOOR + 1.6, D / 2 + 0.12]}>
            <mesh>
              <boxGeometry args={[0.26, 0.26, 0.02]} />
              <meshStandardMaterial color="#111" />
            </mesh>
            <mesh position={[0, 0, 0.012]}>
              <ringGeometry args={[0.05, 0.08, 24]} />
              <meshStandardMaterial color="#FDC300" emissive="#FDC300" emissiveIntensity={1.4} toneMapped={false} />
            </mesh>
          </group>
        )}
      </group>

      {/* AC outdoor unit on the right wall (non-inverter group) */}
      {byId.ac && <ACOutdoor ap={byId.ac} position={[W / 2 + 0.28, 1.1, 1.0]} rotation={[0, Math.PI / 2, 0]} />}

      {/* roof */}
      <group ref={roof} position={[0, WALL_TOP, 0]}>
        {isHip ? (
          <HipRoof color={h.roof} mat={roofMat} />
        ) : (
          <FlatRoof h={h} mat={roofMat} />
        )}
      </group>

      {/* compound wall + gate */}
      <Compound trim={h.trim} />

      {interior && (
        <group>
          {/* HALL */}
          {byId.tv && <TV ap={byId.tv} position={[-4.15, FLOOR, 2.0]} rotation={[0, Math.PI / 2, 0]} />}
          <Sofa position={[-0.95, FLOOR, 2.0]} rotation={[0, -Math.PI / 2, 0]} color={h.id === 'h2' ? '#5B7F9C' : '#8C5A7A'} />
          <Table position={[-2.3, FLOOR, 2.0]} w={0.9} d={0.5} h={0.42} color="#7B5438" />
          {byId.hallFan && <CeilingFan ap={byId.hallFan} position={[-2.25, WALL_TOP, 2.2]} />}
          {byId.hallTube && <TubeLight ap={byId.hallTube} position={[-2.25, 3.12, 0.4]} light={focused} />}
          <Plant position={[-4.1, FLOOR, 3.7]} />
          {/* BEDROOM */}
          <Bed position={[3.3, FLOOR, 2.1]} rotation={[0, -Math.PI / 2, 0]} sheet={h.id === 'h2' ? '#D98E73' : '#4E7DD1'} />
          <Table position={[3.95, FLOOR, 3.55]} w={0.45} d={0.4} h={0.5} color="#6A4630" />
          {byId.bedFan && <CeilingFan ap={byId.bedFan} position={[2.25, WALL_TOP, 2.2]} />}
          {byId.bedBulb && <Bulb ap={byId.bedBulb} position={[1.2, WALL_TOP, 3.3]} light={focused} />}
          {byId.cpap && <CPAP ap={byId.cpap} position={[3.95, FLOOR + 0.58, 3.55]} rotation={[0, -Math.PI / 2, 0]} />}
          {byId.ac && <ACIndoor ap={byId.ac} position={[4.43, 2.6, 2.2]} rotation={[0, -Math.PI / 2, 0]} />}
          {/* KITCHEN */}
          {byId.fridge && <Fridge ap={byId.fridge} position={[-4.12, FLOOR, -3.5]} rotation={[0, Math.PI / 2, 0]} color={h.id === 'h3' ? '#8E2F3C' : '#B7BEC8'} />}
          <Counter position={[-1.9, FLOOR, -3.66]} length={2.6} />
          {byId.kitBulb && <Bulb ap={byId.kitBulb} position={[-2.25, WALL_TOP, -2.0]} light={focused} />}
          {/* UTILITY: inverter + battery + Sentinel + DB */}
          <TubularBattery h={h} position={[0.9, FLOOR, -3.6]} scale={1.5} />
          <Shelf position={[1.9, 1.05, -3.84]} w={0.75} />
          <InverterBox h={h} position={[1.9, 1.07, -3.74]} scale={1.5} />
          {h.sentinel && <SentinelBox h={h} position={[1.1, 1.47, -3.97]} scale={2.6} />}
          {h.sentinel && <Shunt position={[1.1, 1.02, -3.9]} rotation={[Math.PI / 2, 0, 0]} scale={2} />}
          {h.sentinel && <CTClamp position={[2.55, 1.16, -3.86]} rotation={[0, Math.PI / 2, 0]} scale={2} />}
          <DBPanel h={h} world={world} position={DB_POS} scale={1.5} />
          <Table position={[3.85, FLOOR, -0.95]} w={1.1} d={0.55} h={0.72} />
          {byId.router && <Router ap={byId.router} position={[4.1, FLOOR + 0.76, -0.95]} rotation={[0, -Math.PI / 2, 0]} />}
          {byId.laptop && <Laptop ap={byId.laptop} position={[3.75, FLOOR + 0.75, -0.95]} rotation={[0, -Math.PI / 2, 0]} />}
          {byId.iron && <IroningBoard ap={byId.iron} position={[2.1, FLOOR, -1.55]} />}

          {focused && [
            ['B1', 'Tubular battery', [0.9, 1.35, -3.6]],
            ['INV', 'Inverter', [1.9, 1.9, -3.74]],
            ...(h.sentinel ? [['S', 'Sentinel Core', [1.1, 1.85, -3.95]], ['X1', 'Shunt', [1.1, 0.72, -3.85]], ['X4', 'CT', [2.55, 0.85, -3.85]]] : []),
            ['X7', 'DB + NC contactors', [3.4, 2.75, -3.94]],
          ].map(([id, name, p]) => (
            <Html key={id} position={p} center zIndexRange={[15, 0]} style={{ pointerEvents: 'none' }}>
              <div className={`part-tag ${id === 'S' || id === 'X1' || id === 'X4' ? 'g-sentinel' : ''}`}><b>{id}</b>{name}</div>
            </Html>
          ))}
          {/* power + data wiring */}
          <FlowLine points={svc} radius={0.018} state={() => ({ on: world.grid.present, color: COLORS.grid })} />
          <FlowLine points={acIn} radius={0.018} state={() => ({ on: world.grid.present, color: COLORS.grid })} />
          <FlowLine points={acOut} radius={0.018} state={() => ({ on: liveOn() && h.stats.pOut > 0, color: src() })} />
          <FlowLine points={dcPlus} radius={0.028} wireColor="#B32424" count={6}
            state={() => ({ on: Math.abs(h.bat.i) > 0.5, color: h.bat.i > 0 ? COLORS.grid : COLORS.battery, dir: h.bat.i > 0 ? -1 : 1, speed: Math.min(3, 0.6 + Math.abs(h.bat.i) / 12) })} />
          <FlowLine points={dcMinus} radius={0.028} wireColor="#151515" count={0} state={() => ({ on: false })} />
          <FlowLine points={dcMinus2} radius={0.028} wireColor="#151515" count={0} state={() => ({ on: false })} />
          {h.sentinel && (
            <>
              <FlowLine points={kelvin} radius={0.008} wireColor="#5b3b7a" count={3} pRadius={0.025} state={dataOn} />
              <FlowLine points={ntc} radius={0.008} wireColor="#5b3b7a" count={4} pRadius={0.025} state={dataOn} />
              <FlowLine points={ctLine} radius={0.008} wireColor="#5b3b7a" count={5} pRadius={0.025} state={dataOn} />
              <FlowLine points={coil} radius={0.01} wireColor="#5b3b7a" count={5} pRadius={0.03}
                state={() => ({ on: h.sen.alive && Object.values(h.coils || {}).some(Boolean), color: '#FF4D6D', speed: 0.8 })} />
            </>
          )}
          {flows.map(({ a, pts }) => (
            <FlowLine key={a.id} points={pts} radius={0.014}
              wireColor={a.circuit === 'NI' ? '#3a3f48' : '#2a2f3a'}
              state={() => ({ on: a.powered, color: a.circuit === 'NI' ? COLORS.grid : src(), speed: 0.6 + Math.min(2.5, a.w / 150) })} />
          ))}
        </group>
      )}
    </group>
  );
}

function FlatRoof({ h, mat }) {
  return (
    <group>
      <mesh position={[0, 0.1, 0]} material={mat} castShadow receiveShadow>
        <boxGeometry args={[W + 0.4, 0.2, D + 0.4]} />
      </mesh>
      {[[0, D / 2 + 0.1, W + 0.4, 0.15], [0, -D / 2 - 0.1, W + 0.4, 0.15]].map(([x, z, w, d], i) => (
        <mesh key={i} position={[x, 0.55, z]} material={mat} castShadow>
          <boxGeometry args={[w, 0.7, d]} />
        </mesh>
      ))}
      {[-1, 1].map((s) => (
        <mesh key={s} position={[(s * (W + 0.25)) / 2, 0.55, 0]} material={mat} castShadow>
          <boxGeometry args={[0.15, 0.7, D + 0.4]} />
        </mesh>
      ))}
      <mesh position={[0, 0.92, D / 2 + 0.1]}>
        <boxGeometry args={[W + 0.45, 0.06, 0.2]} />
        <meshStandardMaterial color={h.trim} transparent />
      </mesh>
      {/* stair headroom */}
      <mesh position={[-3.2, 1.3, -2.6]} material={mat} castShadow>
        <boxGeometry args={[2.2, 2.4, 2.4]} />
      </mesh>
      {/* black water tank on stand */}
      <group position={[-3.2, 2.5, -2.6]}>
        <mesh position={[0, 0.55, 0]} castShadow>
          <cylinderGeometry args={[0.62, 0.66, 1.1, 20]} />
          <meshStandardMaterial color="#141414" roughness={0.6} transparent />
        </mesh>
        {[0.2, 0.55, 0.9].map((y) => (
          <mesh key={y} position={[0, y, 0]}>
            <torusGeometry args={[0.655, 0.025, 6, 24]} />
            <meshStandardMaterial color="#222" transparent />
          </mesh>
        ))}
        <mesh position={[0, 1.15, 0]}>
          <cylinderGeometry args={[0.2, 0.2, 0.08, 14]} />
          <meshStandardMaterial color="#222" transparent />
        </mesh>
      </group>
    </group>
  );
}

function Compound({ trim }) {
  const wall = '#D8D2C6';
  const segs = [
    [-3.35, 6.0, 3.7, 0.2], [3.1, 6.0, 4.2, 0.2],
    [-5.2, 0.5, 0.2, 11.2], [5.2, 0.5, 0.2, 11.2],
  ];
  return (
    <group>
      {segs.map(([x, z, w, d], i) => (
        <group key={i}>
          <mesh position={[x, 0.45, z]} castShadow receiveShadow>
            <boxGeometry args={[w, 0.9, d]} />
            <meshStandardMaterial color={wall} roughness={0.95} />
          </mesh>
          <mesh position={[x, 0.93, z]}>
            <boxGeometry args={[w + 0.06, 0.06, d + 0.06]} />
            <meshStandardMaterial color={trim} />
          </mesh>
        </group>
      ))}
      {[-1.5, 1.0].map((x) => (
        <mesh key={x} position={[x, 0.65, 6.0]} castShadow>
          <boxGeometry args={[0.35, 1.3, 0.35]} />
          <meshStandardMaterial color={trim} />
        </mesh>
      ))}
      {Array.from({ length: 9 }).map((_, i) => (
        <mesh key={i} position={[-1.2 + i * 0.25, 0.55, 6.0]}>
          <boxGeometry args={[0.03, 0.9, 0.03]} />
          <meshStandardMaterial color="#2f2f35" metalness={0.6} />
        </mesh>
      ))}
      <mesh position={[-0.25, 0.95, 6.0]}>
        <boxGeometry args={[2.2, 0.04, 0.04]} />
        <meshStandardMaterial color="#2f2f35" metalness={0.6} />
      </mesh>
    </group>
  );
}
