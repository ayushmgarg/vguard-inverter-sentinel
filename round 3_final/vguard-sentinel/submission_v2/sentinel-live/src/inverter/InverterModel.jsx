import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { Part } from './Part.jsx';
import SentinelBoard, { J } from './SentinelBoard.jsx';
import { FlowLine } from '../three/Flow.jsx';
import { COLORS } from '../sim/params.js';

// Inverter body (1 unit = 10 cm): x ∈ [-2.1, 2.1], y ∈ [0.4, 2.4], z ∈ [-1.7, 1.7]; front fascia at +z.
const X0 = -2.1, X1 = 2.1, Y0 = 0.4, Y1 = 2.4, Z0 = -1.7, Z1 = 1.7;
const BASE = 0.46;
export const BOARD_POS = [0.9, 1.34, 0.22];
const jb = (k) => [BOARD_POS[0] + J[k][0], BOARD_POS[1] + J[k][1], BOARD_POS[2] + J[k][2]];

// back-panel ports (inverter-local == world, inverter sits at origin)
export const PORTS = {
  acIn: [1.0, 1.95, Z0 - 0.05],
  acOut: [-0.35, 1.95, Z0 - 0.05],
  batPlus: [-0.1, 0.8, Z0 - 0.05],
  batMinus: [-0.6, 0.8, Z0 - 0.05],
  ntc: [-1.3, 1.95, Z0 - 0.05],
  coil: [0.35, 1.95, Z0 - 0.05],
};

const steel = { color: '#3A3F46', metalness: 0.75, roughness: 0.4 };

function Transformer() {
  const g = useRef();
  return (
    <Part id="I5">
      <group ref={g} position={[-1.15, BASE, -0.3]}>
        {/* laminated EI core */}
        <mesh position={[0, 0.6, 0]} castShadow receiveShadow>
          <boxGeometry args={[1.3, 1.2, 0.62]} />
          <meshStandardMaterial {...steel} color="#4A4F57" />
        </mesh>
        {Array.from({ length: 13 }).map((_, i) => (
          <mesh key={i} position={[0, 0.07 + i * 0.09, 0.312]}>
            <boxGeometry args={[1.3, 0.012, 0.004]} />
            <meshStandardMaterial color="#2c3036" />
          </mesh>
        ))}
        {/* copper windings around the centre leg */}
        <mesh position={[0, 0.6, 0]} castShadow>
          <boxGeometry args={[0.72, 0.92, 1.12]} />
          <meshStandardMaterial color="#B8692E" metalness={0.85} roughness={0.32} />
        </mesh>
        {Array.from({ length: 10 }).map((_, i) => (
          <mesh key={i} position={[0, 0.2 + i * 0.09, 0.561]}>
            <boxGeometry args={[0.72, 0.01, 0.004]} />
            <meshStandardMaterial color="#8A4A1C" />
          </mesh>
        ))}
        <mesh position={[0, 0.6, 0.566]}>
          <planeGeometry args={[0.45, 0.25]} />
          <meshStandardMaterial color="#E9E2C9" />
        </mesh>
        {/* clamp frame */}
        {[-0.34, 0.34].map((z) => (
          <mesh key={z} position={[0, 1.24, z]} castShadow>
            <boxGeometry args={[1.42, 0.06, 0.06]} />
            <meshStandardMaterial color="#1f2328" metalness={0.6} />
          </mesh>
        ))}
      </group>
    </Part>
  );
}

function Heatsink({ world }) {
  const h = world.houses[0];
  const glow = useRef([]);
  useFrame(() => {
    const k = Math.min(1, Math.abs(h.bat.i) / 45);
    glow.current.forEach((m) => { if (m) m.emissiveIntensity = k * 0.6; });
  });
  return (
    <Part id="I4">
      <group position={[0.55, BASE, -1.05]}>
        <mesh position={[0, 0.03, 0.05]} receiveShadow>
          <boxGeometry args={[1.7, 0.03, 0.35]} />
          <meshStandardMaterial color="#1D6B3A" roughness={0.6} />
        </mesh>
        <mesh position={[0, 0.42, 0]} castShadow>
          <boxGeometry args={[1.62, 0.72, 0.06]} />
          <meshStandardMaterial color="#C9CED6" metalness={0.8} roughness={0.35} />
        </mesh>
        {Array.from({ length: 15 }).map((_, i) => (
          <mesh key={i} position={[-0.77 + i * 0.11, 0.42, -0.24]} castShadow>
            <boxGeometry args={[0.02, 0.7, 0.44]} />
            <meshStandardMaterial color="#BFC5CD" metalness={0.8} roughness={0.35} />
          </mesh>
        ))}
        {Array.from({ length: 8 }).map((_, i) => (
          <group key={i} position={[-0.63 + i * 0.18, 0.42, 0.055]}>
            <mesh castShadow>
              <boxGeometry args={[0.11, 0.16, 0.045]} />
              <meshStandardMaterial ref={(m) => (glow.current[i] = m)} color="#141414" emissive="#FF5A1F" emissiveIntensity={0} />
            </mesh>
            <mesh position={[0, 0.12, -0.012]}>
              <boxGeometry args={[0.11, 0.09, 0.012]} />
              <meshStandardMaterial color="#D0D4DA" metalness={0.95} roughness={0.2} />
            </mesh>
            {[-0.035, 0, 0.035].map((x) => (
              <mesh key={x} position={[x, -0.2, 0.01]}>
                <boxGeometry args={[0.012, 0.24, 0.006]} />
                <meshStandardMaterial color="#C0C0C0" metalness={0.9} />
              </mesh>
            ))}
          </group>
        ))}
      </group>
    </Part>
  );
}

function Fan({ world }) {
  const h = world.houses[0];
  const rot = useRef();
  const spd = useRef(0);
  useFrame((_, dt) => {
    const on = (h.inv.state === 'S3' && h.stats.pOut > 60) || (h.inv.state === 'S1' && h.bat.i > 2) || h.bat.temp > 42;
    spd.current += ((on ? 22 : 0) - spd.current) * Math.min(1, dt * 1.5);
    if (rot.current) rot.current.rotation.z += spd.current * dt;
  });
  return (
    <Part id="I10">
      <group position={[1.55, 1.25, Z0 + 0.12]}>
        <mesh>
          <boxGeometry args={[0.82, 0.82, 0.16]} />
          <meshStandardMaterial color="#1c1e22" roughness={0.6} />
        </mesh>
        <group ref={rot} position={[0, 0, 0.09]}>
          <mesh>
            <cylinderGeometry args={[0.1, 0.1, 0.04, 16]} />
            <meshStandardMaterial color="#2a2d33" />
          </mesh>
          {Array.from({ length: 7 }).map((_, i) => (
            <mesh key={i} rotation={[0, 0, (i / 7) * Math.PI * 2]} position={[0, 0, 0]}>
              <boxGeometry args={[0.07, 0.62, 0.012]} />
              <meshStandardMaterial color="#34373d" />
            </mesh>
          ))}
        </group>
      </group>
    </Part>
  );
}

function Relay({ world }) {
  const h = world.houses[0];
  const arm = useRef();
  const spark = useRef();
  const coil = useRef();
  const ang = useRef(-0.28);
  useFrame((_, dt) => {
    const st = h.inv.state;
    const target = st === 'S1' ? -0.28 : 0.28;
    const rate = (world.slowmo ?? 1) < 0.5 ? 2.5 : 40;
    const prev = ang.current;
    ang.current += (target - ang.current) * Math.min(1, dt * rate);
    if (arm.current) arm.current.rotation.z = ang.current;
    const moving = Math.abs(ang.current - prev) > 0.002;
    if (spark.current) spark.current.emissiveIntensity = moving ? 8 : Math.max(0, spark.current.emissiveIntensity - dt * 20);
    if (coil.current) coil.current.emissiveIntensity = st !== 'S1' ? 0.6 : 0;
  });
  return (
    <Part id="I2">
      <group position={[1.62, BASE + 0.07, 0.95]}>
        {/* transparent relay housing */}
        <mesh position={[0, 0.17, 0]}>
          <boxGeometry args={[0.36, 0.34, 0.3]} />
          <meshPhysicalMaterial color="#6FA8FF" transparent opacity={0.28} roughness={0.1} transmission={0.4} depthWrite={false} />
        </mesh>
        <mesh position={[0, 0.02, 0]}>
          <boxGeometry args={[0.37, 0.04, 0.31]} />
          <meshStandardMaterial color="#1E4FA0" />
        </mesh>
        {/* coil */}
        <mesh position={[-0.08, 0.14, 0]} rotation={[0, 0, 0]}>
          <cylinderGeometry args={[0.06, 0.06, 0.18, 16]} />
          <meshStandardMaterial ref={coil} color="#B8692E" metalness={0.8} roughness={0.3} emissive="#FDC300" emissiveIntensity={0} />
        </mesh>
        {/* fixed contacts: NC (mains) left, NO (bridge) right */}
        <mesh position={[0.04, 0.3, 0]}>
          <boxGeometry args={[0.03, 0.03, 0.06]} />
          <meshStandardMaterial color="#FDC300" emissive="#FDC300" emissiveIntensity={0.3} metalness={0.9} />
        </mesh>
        <mesh position={[0.15, 0.3, 0]}>
          <boxGeometry args={[0.03, 0.03, 0.06]} />
          <meshStandardMaterial color="#22D3EE" emissive="#22D3EE" emissiveIntensity={0.3} metalness={0.9} />
        </mesh>
        {/* armature (moving contact) */}
        <group ref={arm} position={[0.095, 0.1, 0]}>
          <mesh position={[0, 0.1, 0]}>
            <boxGeometry args={[0.02, 0.2, 0.05]} />
            <meshStandardMaterial color="#D8DCE2" metalness={0.95} roughness={0.2} />
          </mesh>
          <mesh position={[0, 0.2, 0]}>
            <sphereGeometry args={[0.018, 10, 10]} />
            <meshStandardMaterial ref={spark} color="#fff" emissive="#FFE9A8" emissiveIntensity={0} toneMapped={false} />
          </mesh>
        </group>
      </group>
    </Part>
  );
}

function ControlBoard() {
  return (
    <group>
      <Part id="I3">
        <group position={[0.85, BASE + 0.06, 0.55]}>
          <mesh receiveShadow castShadow>
            <boxGeometry args={[1.62, 0.025, 1.05]} />
            <meshStandardMaterial color="#1E6B3C" roughness={0.6} />
          </mesh>
          {/* SG3525 DIP-16 */}
          <group position={[-0.55, 0.035, 0.32]}>
            <mesh castShadow>
              <boxGeometry args={[0.2, 0.045, 0.075]} />
              <meshStandardMaterial color="#141414" />
            </mesh>
            {Array.from({ length: 16 }).map((_, i) => (
              <mesh key={i} position={[-0.087 + (i % 8) * 0.025, -0.01, i < 8 ? 0.045 : -0.045]}>
                <boxGeometry args={[0.008, 0.03, 0.012]} />
                <meshStandardMaterial color="#C0C0C0" metalness={0.9} />
              </mesh>
            ))}
          </group>
          {/* trim pot (factory charge setpoint) */}
          <mesh position={[-0.3, 0.04, 0.4]} castShadow>
            <boxGeometry args={[0.07, 0.07, 0.07]} />
            <meshStandardMaterial color="#2F6FE0" />
          </mesh>
          {/* electrolytic caps */}
          {[[-0.7, -0.35, 0.13], [-0.52, -0.35, 0.1], [-0.35, -0.38, 0.09], [0.1, 0.35, 0.08], [0.25, 0.35, 0.08]].map(([x, z, r], i) => (
            <group key={i} position={[x, 0.012, z]}>
              <mesh position={[0, r * 1.1, 0]} castShadow>
                <cylinderGeometry args={[r * 0.55, r * 0.55, r * 2.2, 18]} />
                <meshStandardMaterial color={i < 3 ? '#1F2E6B' : '#101010'} roughness={0.35} />
              </mesh>
              <mesh position={[0, r * 2.21, 0]}>
                <cylinderGeometry args={[r * 0.55, r * 0.55, 0.004, 18]} />
                <meshStandardMaterial color="#A8ADB5" metalness={0.8} />
              </mesh>
            </group>
          ))}
          {/* resistors */}
          {Array.from({ length: 10 }).map((_, i) => (
            <mesh key={i} position={[-0.15 + (i % 5) * 0.07, 0.025, 0.1 + Math.floor(i / 5) * 0.08]} rotation={[0, 0, Math.PI / 2]}>
              <cylinderGeometry args={[0.012, 0.012, 0.05, 8]} />
              <meshStandardMaterial color={['#D8B98A', '#7FA7D8'][i % 2]} />
            </mesh>
          ))}
        </group>
      </Part>
      <Part id="I1">
        <group position={[0.2, BASE + 0.07, 0.95]}>
          <mesh position={[0, 0.12, 0]} castShadow>
            <boxGeometry args={[0.28, 0.24, 0.2]} />
            <meshStandardMaterial color="#3A3F46" metalness={0.6} roughness={0.4} />
          </mesh>
          <mesh position={[0, 0.12, 0]}>
            <boxGeometry args={[0.16, 0.2, 0.24]} />
            <meshStandardMaterial color="#E7C24A" roughness={0.6} />
          </mesh>
        </group>
      </Part>
    </group>
  );
}

function InternalShunt() {
  return (
    <Part id="I8">
      <group position={[-0.35, BASE + 0.04, -1.3]}>
        <mesh castShadow>
          <boxGeometry args={[0.5, 0.03, 0.18]} />
          <meshStandardMaterial color="#1E6B3C" />
        </mesh>
        {[-0.08, -0.03, 0.02, 0.07].map((x) => (
          <mesh key={x} position={[x, 0.04, 0]}>
            <boxGeometry args={[0.025, 0.05, 0.14]} />
            <meshStandardMaterial color="#C99A3A" metalness={0.9} roughness={0.25} />
          </mesh>
        ))}
        {[-0.2, 0.2].map((x) => (
          <mesh key={x} position={[x, 0.04, 0]}>
            <boxGeometry args={[0.1, 0.05, 0.16]} />
            <meshStandardMaterial color="#B87333" metalness={0.9} roughness={0.25} />
          </mesh>
        ))}
      </group>
    </Part>
  );
}

function FrontPanel({ world }) {
  const h = world.houses[0];
  const leds = useRef({});
  const lcd = useRef();
  const bars = useRef([]);
  useFrame(({ clock }) => {
    const st = h.inv.state;
    const L = leds.current;
    const blink = Math.sin(clock.elapsedTime * 5) > 0;
    if (L.mains) L.mains.emissiveIntensity = st === 'S1' || st === 'S6' ? 4 : 0;
    if (L.batt) L.batt.emissiveIntensity = st === 'S3' ? 4 : 0;
    if (L.chg) L.chg.emissiveIntensity = st === 'S1' && h.bat.i > 1 && blink ? 4 : 0;
    if (L.fault) L.fault.emissiveIntensity = st === 'S4' && blink ? 4 : 0;
    if (lcd.current) lcd.current.emissive.set(st === 'S3' ? '#FFB54A' : '#5BE3FF');
    const n = Math.ceil(h.bat.soc * 5);
    bars.current.forEach((m, i) => { if (m) m.emissiveIntensity = i < n ? 2.2 : 0.05; });
  });
  return (
    <Part id="I11">
      <group position={[0, 0, Z1]}>
        <mesh position={[0, (Y0 + Y1) / 2, 0.02]} castShadow>
          <boxGeometry args={[X1 - X0 + 0.1, Y1 - Y0, 0.06]} />
          <meshStandardMaterial color="#12151B" metalness={0.3} roughness={0.25} />
        </mesh>
        <mesh position={[0, Y0 + 0.18, 0.052]}>
          <planeGeometry args={[X1 - X0 - 0.2, 0.03]} />
          <meshStandardMaterial color="#FDC300" emissive="#FDC300" emissiveIntensity={0.4} />
        </mesh>
        {/* LCD */}
        <mesh position={[-0.9, 1.72, 0.052]}>
          <planeGeometry args={[1.2, 0.5]} />
          <meshStandardMaterial ref={(m) => { lcd.current = m; if (m) m.userData.live = true; }} color="#000" emissive="#5BE3FF" emissiveIntensity={0.55} toneMapped={false} />
        </mesh>
        {Array.from({ length: 5 }).map((_, i) => (
          <mesh key={i} position={[-1.35 + i * 0.13, 1.62, 0.056]}>
            <planeGeometry args={[0.09, 0.14]} />
            <meshStandardMaterial ref={(m) => { bars.current[i] = m; if (m) m.userData.live = true; }} color="#000" emissive="#FFFFFF" emissiveIntensity={0} toneMapped={false} />
          </mesh>
        ))}
        {[['mains', '#2BD67B', 0.25], ['batt', '#FFB020', 0.5], ['chg', '#35A6FF', 0.75], ['fault', '#FF4D6D', 1.0]].map(([k, c, x]) => (
          <mesh key={k} position={[x, 1.75, 0.056]}>
            <circleGeometry args={[0.05, 20]} />
            <meshStandardMaterial ref={(m) => { leds.current[k] = m; if (m) m.userData.live = true; }} color="#222" emissive={c} emissiveIntensity={0} toneMapped={false} />
          </mesh>
        ))}
        {/* switches: UPS/Normal + battery-type selector */}
        <mesh position={[1.55, 1.75, 0.08]}>
          <boxGeometry args={[0.18, 0.28, 0.06]} />
          <meshStandardMaterial color="#2A2E35" />
        </mesh>
        <mesh position={[1.55, 1.8, 0.12]} rotation={[0.35, 0, 0]}>
          <boxGeometry args={[0.1, 0.12, 0.05]} />
          <meshStandardMaterial color="#D6D9DE" />
        </mesh>
        <mesh position={[1.55, 1.22, 0.1]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.13, 0.13, 0.08, 24]} />
          <meshStandardMaterial color="#2A2E35" metalness={0.5} />
        </mesh>
        {/* grille + SENTINEL INSIDE badge */}
        {Array.from({ length: 6 }).map((_, i) => (
          <mesh key={i} position={[0.55, 0.9 + i * 0.08, 0.052]}>
            <planeGeometry args={[0.9, 0.025]} />
            <meshStandardMaterial color="#05070A" />
          </mesh>
        ))}
        <group position={[-0.9, 1.05, 0.056]}>
          <mesh>
            <planeGeometry args={[1.2, 0.3]} />
            <meshStandardMaterial color="#0A0B0E" />
          </mesh>
          <mesh position={[-0.45, 0, 0.003]}>
            <ringGeometry args={[0.06, 0.1, 28]} />
            <meshStandardMaterial color="#FDC300" emissive="#FDC300" emissiveIntensity={1.4} toneMapped={false} />
          </mesh>
          {[0, 1, 2].map((i) => (
            <mesh key={i} position={[0.05 + i * 0.25, 0, 0.003]}>
              <planeGeometry args={[0.2, 0.05]} />
              <meshStandardMaterial color="#FDC300" />
            </mesh>
          ))}
        </group>
      </group>
    </Part>
  );
}

function BackPanel() {
  return (
    <group position={[0, 0, Z0]}>
      <mesh position={[0, (Y0 + Y1) / 2, -0.02]} castShadow receiveShadow>
        <boxGeometry args={[X1 - X0 + 0.1, Y1 - Y0, 0.05]} />
        <meshStandardMaterial color="#2A2E35" metalness={0.5} roughness={0.45} />
      </mesh>
      {/* sockets */}
      {[[PORTS.acIn[0], '#111'], [PORTS.acOut[0], '#111'], [PORTS.acOut[0] - 0.45, '#111']].map(([x], i) => (
        <group key={i} position={[x, 1.95, -0.06]}>
          <mesh>
            <boxGeometry args={[0.36, 0.36, 0.05]} />
            <meshStandardMaterial color={i === 0 ? '#E9EDF2' : '#F4F5F7'} />
          </mesh>
          {[[-0.06, 0.05], [0.06, 0.05], [0, -0.07]].map(([a, b], k) => (
            <mesh key={k} position={[a, b, -0.03]}>
              <circleGeometry args={[0.022, 10]} />
              <meshStandardMaterial color="#222" side={THREE.DoubleSide} />
            </mesh>
          ))}
        </group>
      ))}
      {/* battery terminals */}
      {[[PORTS.batPlus[0], '#D93636'], [PORTS.batMinus[0], '#1d1d1f']].map(([x, c]) => (
        <group key={x} position={[x, 0.8, -0.08]}>
          <mesh rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.1, 0.1, 0.1, 18]} />
            <meshStandardMaterial color={c} />
          </mesh>
          <mesh position={[0, 0, -0.07]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.04, 0.04, 0.08, 10]} />
            <meshStandardMaterial color="#C0C0C0" metalness={0.9} />
          </mesh>
        </group>
      ))}
      {/* fan grille */}
      {Array.from({ length: 7 }).map((_, i) => (
        <mesh key={i} position={[1.55, 0.98 + i * 0.09, -0.05]}>
          <boxGeometry args={[0.8, 0.02, 0.02]} />
          <meshStandardMaterial color="#15171b" />
        </mesh>
      ))}
      {/* grommets for Sentinel leads */}
      {[PORTS.ntc, PORTS.coil].map((p, i) => (
        <mesh key={i} position={[p[0], p[1], -0.05]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.06, 0.02, 8, 18]} />
          <meshStandardMaterial color="#C084FC" emissive="#C084FC" emissiveIntensity={0.5} />
        </mesh>
      ))}
    </group>
  );
}

function Casing({ mode }) {
  const g = useRef();
  const mat = useMemo(() => new THREE.MeshStandardMaterial({ color: '#E9ECEF', metalness: 0.35, roughness: 0.35, transparent: true }), []);
  const edge = useMemo(() => new THREE.LineBasicMaterial({ color: '#FDC300', transparent: true, opacity: 0 }), []);
  const cur = useRef({ y: 0, o: 1 });
  useFrame((_, dt) => {
    const tgt = mode === 'closed' ? { y: 0, o: 1 } : mode === 'open' ? { y: 2.4, o: 0.12 } : { y: 0, o: 0.1 };
    const k = Math.min(1, dt * 3);
    cur.current.y += (tgt.y - cur.current.y) * k;
    cur.current.o += (tgt.o - cur.current.o) * k;
    if (g.current) g.current.position.y = cur.current.y;
    mat.opacity = cur.current.o;
    mat.depthWrite = cur.current.o > 0.9;
    edge.opacity = (1 - cur.current.o) * 0.7;
  });
  const top = useMemo(() => new THREE.BoxGeometry(X1 - X0 + 0.12, 0.05, Z1 - Z0 + 0.02), []);
  const side = useMemo(() => new THREE.BoxGeometry(0.05, Y1 - Y0, Z1 - Z0 + 0.02), []);
  const edgesTop = useMemo(() => new THREE.EdgesGeometry(top), [top]);
  const edgesSide = useMemo(() => new THREE.EdgesGeometry(side), [side]);
  return (
    <group ref={g}>
      <mesh geometry={top} material={mat} position={[0, Y1 + 0.02, 0]} castShadow />
      <lineSegments geometry={edgesTop} material={edge} position={[0, Y1 + 0.02, 0]} />
      {[X0 - 0.03, X1 + 0.03].map((x) => (
        <group key={x}>
          <mesh geometry={side} material={mat} position={[x, (Y0 + Y1) / 2, 0]} castShadow />
          <lineSegments geometry={edgesSide} material={edge} position={[x, (Y0 + Y1) / 2, 0]} />
        </group>
      ))}
    </group>
  );
}

export default function InverterModel({ world, casing }) {
  const h = world.houses[0];
  const st = () => h.inv.state;
  const src = () => (st() === 'S3' || st() === 'S6' ? COLORS.battery : COLORS.grid);
  const convOn = () => {
    const s = st();
    if (s === 'S3' || s === 'S6') return { on: true, color: COLORS.battery, dir: 1, speed: 0.8 + Math.abs(h.bat.i) / 20 };
    if (s === 'S1' && h.bat.i > 0.5) return { on: true, color: COLORS.grid, dir: -1, speed: 0.6 + h.bat.i / 10 };
    return { on: false };
  };
  const data = () => ({ on: h.sen.alive, color: COLORS.data, speed: 0.7 });

  // internal power paths
  const P = useMemo(() => ({
    acIn: [PORTS.acIn, [1.0, 1.95, -1.2], [0.2, 1.1, -1.2], [0.2, 0.85, 0.95]],
    i1i2: [[0.2, 0.85, 0.95], [0.9, 0.85, 1.3], [1.62, 0.85, 1.3], [1.62, 0.75, 0.95]],
    out: [[1.62, 0.75, 0.95], [1.95, 0.75, 0.95], [1.95, 1.95, 0.95], [1.95, 1.95, -1.3], [PORTS.acOut[0], 1.95, -1.3], PORTS.acOut],
    sec: [[1.62, 0.75, 0.95], [1.62, 0.62, 0.2], [-0.6, 0.62, 0.2], [-0.8, 1.05, 0.28]],
    pri: [[-1.15, 1.2, -0.62], [-1.15, 1.2, -0.85], [0.55, 1.1, -0.85], [0.55, 0.95, -0.96]],
    batNeg: [PORTS.batMinus, [-0.6, 0.55, -1.3], [-0.2, 0.55, -1.3], [0.55, 0.55, -0.96]],
    batPos: [PORTS.batPlus, [-0.1, 0.72, -1.4], [-1.15, 0.72, -1.4], [-1.15, 1.2, -0.62]],
  }), []);
  const D = useMemo(() => ({
    kelvin: [jb('J2'), [BOARD_POS[0] - 0.12, 0.9, -0.9], [-0.35, 0.62, -1.2]],
    opto: [jb('J9'), [0.5, 1.2, 0.95], [0.2, 0.9, 0.95]],
    dac: [jb('J10'), [0.3, 1.0, 0.9], [0.3, 0.62, 0.87]],
    vtap: [jb('J5'), [1.95, 1.4, 0.2], [1.95, 1.4, 0.7]],
    ct: [jb('J6'), [1.95, 1.62, -0.2], [1.95, 1.9, -0.6]],
    ntc: [jb('J4'), [BOARD_POS[0], 1.3, -1.4], [PORTS.ntc[0], 1.95, -1.4], PORTS.ntc],
    coil: [jb('J8'), [1.08, 1.5, -1.3], [PORTS.coil[0], 1.95, -1.3], PORTS.coil],
    pwr: [jb('J1'), [0.64, 0.8, 0.6], [0.64, 0.6, 0.6]],
  }), []);

  return (
    <group>
      {/* chassis base */}
      <mesh position={[0, BASE - 0.03, 0]} receiveShadow castShadow>
        <boxGeometry args={[X1 - X0, 0.06, Z1 - Z0]} />
        <meshStandardMaterial color="#8C939C" metalness={0.7} roughness={0.4} />
      </mesh>
      <mesh position={[0, 0.2, 0]} receiveShadow>
        <boxGeometry args={[X1 - X0 - 0.3, 0.4, Z1 - Z0 - 0.3]} />
        <meshStandardMaterial color="#1a1c20" />
      </mesh>
      <Transformer />
      <Heatsink world={world} />
      <Fan world={world} />
      <ControlBoard />
      <Relay world={world} />
      <InternalShunt />
      <FrontPanel world={world} />
      <BackPanel />
      {/* internal CT (X4-equivalent) on the AC-OUT live lead */}
      <Part id="X4">
        <mesh position={[1.95, 1.9, -0.6]} rotation={[0, 0, Math.PI / 2]}>
          <torusGeometry args={[0.07, 0.03, 10, 24]} />
          <meshStandardMaterial color="#1d1d1f" />
        </mesh>
      </Part>
      {/* standoffs + Sentinel-Embedded daughter board */}
      {[[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([a, b], i) => (
        <mesh key={i} position={[BOARD_POS[0] + a * 0.365, (BASE + 0.07 + BOARD_POS[1]) / 2, BOARD_POS[2] + b * 0.265]}>
          <cylinderGeometry args={[0.016, 0.016, BOARD_POS[1] - BASE - 0.07, 6]} />
          <meshStandardMaterial color="#C9A13B" metalness={0.9} roughness={0.3} />
        </mesh>
      ))}
      <SentinelBoard world={world} position={BOARD_POS} />

      {/* power flows */}
      <FlowLine points={P.acIn} radius={0.02} wireColor="#5a3b1a" count={6} pRadius={0.035} state={() => ({ on: world.grid.v > 90, color: COLORS.grid })} />
      <FlowLine points={P.i1i2} radius={0.02} wireColor="#5a3b1a" count={5} pRadius={0.035} state={() => ({ on: world.grid.v > 90, color: COLORS.grid })} />
      <FlowLine points={P.out} radius={0.022} wireColor="#5a3b1a" count={8} pRadius={0.04} state={() => ({ on: ['S1', 'S3', 'S6'].includes(st()) && h.stats.pOut > 0, color: src(), speed: 0.6 + h.stats.pOut / 300 })} />
      <FlowLine points={P.sec} radius={0.022} wireColor="#8A4A1C" count={6} pRadius={0.04} state={convOn} />
      <FlowLine points={P.pri} radius={0.04} wireColor="#B87333" count={6} pRadius={0.05} state={convOn} />
      <FlowLine points={P.batNeg} radius={0.045} wireColor="#222" count={6} pRadius={0.05} state={convOn} />
      <FlowLine points={P.batPos} radius={0.045} wireColor="#8E1F1F" count={6} pRadius={0.05} state={() => { const s = convOn(); return s.on ? { ...s, dir: -(s.dir || 1) } : s; }} />
      {/* Sentinel sensing / control links */}
      {Object.entries(D).map(([k, pts]) => (
        <FlowLine key={k} points={pts} radius={0.009} wireColor="#4b2f66" count={4} pRadius={0.02}
          state={k === 'coil' ? () => ({ on: h.sen.alive && Object.values(h.coils || {}).some(Boolean), color: '#FF4D6D', speed: 0.8 }) : k === 'dac' ? () => ({ on: h.sen.alive && h.sp && h.sp.source === 'sentinel', color: COLORS.data, dir: 1, speed: 0.6 }) : data} />
      ))}
      <Casing mode={casing} />
    </group>
  );
}
