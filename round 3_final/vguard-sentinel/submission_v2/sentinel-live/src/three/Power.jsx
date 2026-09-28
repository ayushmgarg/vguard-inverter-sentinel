import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { TIER_META } from '../sim/params.js';

const socColor = (soc) => (soc > 0.55 ? '#2BD67B' : soc > 0.4 ? '#FDC300' : soc > 0.25 ? '#F39200' : '#FF4D6D');

// 12 V tubular flooded battery (≈ 505 × 190 × 410 mm)
export function TubularBattery({ h, position, rotation, scale = 1, gauge = true }) {
  const bar = useRef();
  const barMat = useRef();
  useFrame(() => {
    if (!h || !bar.current) return;
    const soc = h.bat.soc;
    bar.current.scale.y = Math.max(0.02, soc);
    bar.current.position.y = 0.02 + (0.34 * Math.max(0.02, soc)) / 2;
    barMat.current.color.set(socColor(soc));
  });
  return (
    <group position={position} rotation={rotation} scale={scale}>
      <mesh position={[0, 0.19, 0]} castShadow receiveShadow>
        <boxGeometry args={[0.505, 0.38, 0.19]} />
        <meshPhysicalMaterial color="#EDEAE2" roughness={0.35} clearcoat={0.4} />
      </mesh>
      {/* ribs */}
      {[-0.18, -0.06, 0.06, 0.18].map((x) => (
        <mesh key={x} position={[x, 0.19, 0.0955]}>
          <boxGeometry args={[0.012, 0.34, 0.004]} />
          <meshStandardMaterial color="#DAD6CC" />
        </mesh>
      ))}
      {/* label band */}
      <mesh position={[0, 0.25, 0.0965]}>
        <planeGeometry args={[0.44, 0.08]} />
        <meshStandardMaterial color="#1B2A55" />
      </mesh>
      <mesh position={[0, 0.25, 0.0968]}>
        <planeGeometry args={[0.16, 0.03]} />
        <meshStandardMaterial color="#FDC300" />
      </mesh>
      {/* lid */}
      <mesh position={[0, 0.395, 0]} castShadow>
        <boxGeometry args={[0.51, 0.03, 0.195]} />
        <meshStandardMaterial color="#1B2A55" roughness={0.5} />
      </mesh>
      {/* vent plugs */}
      {[-0.19, -0.114, -0.038, 0.038, 0.114, 0.19].map((x) => (
        <mesh key={x} position={[x, 0.42, 0.02]}>
          <cylinderGeometry args={[0.014, 0.016, 0.022, 12]} />
          <meshStandardMaterial color="#E24B4B" />
        </mesh>
      ))}
      {/* float indicators */}
      {[-0.152, 0.152].map((x) => (
        <group key={x} position={[x, 0.415, -0.05]}>
          <mesh>
            <sphereGeometry args={[0.018, 12, 12, 0, Math.PI * 2, 0, Math.PI / 2]} />
            <meshPhysicalMaterial color="#fff" transmission={0.8} roughness={0.05} transparent opacity={0.6} />
          </mesh>
          <mesh position={[0, 0.006, 0]}>
            <sphereGeometry args={[0.009, 10, 10]} />
            <meshStandardMaterial color="#2BD67B" emissive="#2BD67B" emissiveIntensity={0.6} />
          </mesh>
        </group>
      ))}
      {/* terminals */}
      <Terminal position={[0.21, 0.41, -0.055]} color="#D93636" />
      <Terminal position={[-0.21, 0.41, -0.055]} color="#1d1d1f" />
      {gauge && h && (
        <group position={[0.275, 0, 0]}>
          <mesh position={[0, 0.19, 0]}>
            <boxGeometry args={[0.018, 0.36, 0.05]} />
            <meshStandardMaterial color="#111" transparent opacity={0.6} />
          </mesh>
          <mesh ref={bar} position={[0, 0.1, 0]}>
            <boxGeometry args={[0.022, 0.34, 0.04]} />
            <meshBasicMaterial ref={barMat} color="#2BD67B" toneMapped={false} />
          </mesh>
        </group>
      )}
    </group>
  );
}

function Terminal({ position, color }) {
  return (
    <group position={position}>
      <mesh>
        <cylinderGeometry args={[0.018, 0.022, 0.04, 14]} />
        <meshStandardMaterial color="#8d8d8d" metalness={0.8} roughness={0.35} />
      </mesh>
      <mesh position={[0, 0.03, 0]}>
        <cylinderGeometry args={[0.026, 0.026, 0.026, 14]} />
        <meshStandardMaterial color={color} roughness={0.5} />
      </mesh>
    </group>
  );
}

// Home inverter exterior (V-Guard Prime class, ~275 × 250 × 120 mm)
export function InverterBox({ h, position, rotation, scale = 1 }) {
  const leds = useRef({});
  const lcd = useRef();
  useFrame(({ clock }) => {
    if (!h) return;
    const st = h.inv.state;
    const L = leds.current;
    const blink = Math.sin(clock.elapsedTime * 5) > 0;
    if (L.mains) L.mains.emissiveIntensity = st === 'S1' || st === 'S6' ? 3 : 0;
    if (L.batt) L.batt.emissiveIntensity = st === 'S3' ? 3 : 0;
    if (L.chg) L.chg.emissiveIntensity = st === 'S1' && h.bat.i > 1 && blink ? 3 : 0;
    if (L.fault) L.fault.emissiveIntensity = st === 'S4' && blink ? 3 : 0;
    if (lcd.current) {
      lcd.current.emissiveIntensity = st === 'S4' ? 0.2 : 1.2;
      lcd.current.emissive.set(st === 'S3' ? '#FFB54A' : '#5BE3FF');
    }
  });
  return (
    <group position={position} rotation={rotation} scale={scale}>
      <mesh position={[0, 0.125, 0]} castShadow receiveShadow>
        <boxGeometry args={[0.275, 0.25, 0.12]} />
        <meshStandardMaterial color="#F1F2F4" roughness={0.35} />
      </mesh>
      <mesh position={[0, 0.14, 0.0605]}>
        <planeGeometry args={[0.25, 0.2]} />
        <meshStandardMaterial color="#141820" roughness={0.2} metalness={0.3} />
      </mesh>
      <mesh position={[0, 0.2, 0.061]}>
        <planeGeometry args={[0.12, 0.045]} />
        <meshStandardMaterial ref={lcd} color="#000" emissive="#5BE3FF" emissiveIntensity={1} toneMapped={false} />
      </mesh>
      <mesh position={[0, 0.07, 0.061]}>
        <planeGeometry args={[0.2, 0.006]} />
        <meshStandardMaterial color="#FDC300" emissive="#FDC300" emissiveIntensity={0.5} />
      </mesh>
      {[
        ['mains', '#2BD67B', -0.075], ['batt', '#FFB020', -0.025], ['chg', '#35A6FF', 0.025], ['fault', '#FF4D6D', 0.075],
      ].map(([k, c, x]) => (
        <mesh key={k} position={[x, 0.135, 0.062]}>
          <circleGeometry args={[0.007, 12]} />
          <meshStandardMaterial ref={(m) => (leds.current[k] = m)} color="#222" emissive={c} emissiveIntensity={0} toneMapped={false} />
        </mesh>
      ))}
      {/* side vents */}
      {[0.06, 0.09, 0.12, 0.15, 0.18].map((y) => (
        <mesh key={y} position={[0.1385, y, 0]}>
          <boxGeometry args={[0.002, 0.008, 0.08]} />
          <meshStandardMaterial color="#9aa0a8" />
        </mesh>
      ))}
    </group>
  );
}

// Sentinel Core box (90 × 70 × 35 mm, UL94 V-0)
export function SentinelBox({ h, position, rotation, scale = 1 }) {
  const L = useRef({});
  useFrame(({ clock }) => {
    if (!h) return;
    const s = h.sen;
    const t = clock.elapsedTime;
    const alive = h.sentinel && s.alive;
    if (L.current.pwr) L.current.pwr.emissiveIntensity = h.sentinel ? 3 : 0;
    if (L.current.hb) L.current.hb.emissiveIntensity = alive && (t % 1) < 0.5 ? 3 : 0;
    if (L.current.out) L.current.out.emissiveIntensity = alive && s.outage ? 3 : 0;
    if (L.current.shed) L.current.shed.emissiveIntensity = alive && (s.shed.T2 || s.shed.T3) ? 3 : !alive && h.sentinel && Math.sin(t * 12) > 0 ? 3 : 0;
    if (L.current.ring) L.current.ring.emissiveIntensity = alive ? 1.2 + Math.sin(t * 2) * 0.4 : 0.1;
  });
  return (
    <group position={position} rotation={rotation} scale={scale}>
      <mesh castShadow>
        <boxGeometry args={[0.09, 0.07, 0.035]} />
        <meshStandardMaterial color="#15171C" roughness={0.55} />
      </mesh>
      <mesh position={[0, 0.029, 0.0176]}>
        <planeGeometry args={[0.09, 0.012]} />
        <meshStandardMaterial color="#FDC300" metalness={0.4} roughness={0.3} />
      </mesh>
      <mesh position={[-0.022, 0.0, 0.018]}>
        <ringGeometry args={[0.009, 0.013, 24]} />
        <meshStandardMaterial ref={(m) => (L.current.ring = m)} color="#FDC300" emissive="#FDC300" emissiveIntensity={1} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
      {[['pwr', '#2BD67B'], ['hb', '#35A6FF'], ['out', '#FFB020'], ['shed', '#FF4D6D']].map(([k, c], i) => (
        <mesh key={k} position={[0.004 + i * 0.011, -0.018, 0.0178]}>
          <circleGeometry args={[0.0032, 10]} />
          <meshStandardMaterial ref={(m) => (L.current[k] = m)} color="#222" emissive={c} emissiveIntensity={0} toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
}

// Distribution board: main MCBs on top rail, Sentinel contactor panel below (4 × NC DIN contactors)
export function DBPanel({ h, world, position, rotation, scale = 1 }) {
  const win = useRef({});
  const leds = useRef({});
  const levers = useRef({});
  useFrame(() => {
    if (!h) return;
    for (const ch of ['ch1', 'ch2', 'ch3', 'ch4']) {
      const c = h.circuits[ch];
      const energised = h.coils ? h.coils[ch] : false;
      const m = win.current[ch];
      if (m) {
        m.emissive.set(energised ? '#FF4D6D' : '#2BD67B');
        m.emissiveIntensity = h.sentinel ? 2.2 : 0.3;
      }
      if (leds.current[ch]) leds.current[ch].emissiveIntensity = energised ? 3 : 0;
      if (levers.current[ch]) {
        const target = energised ? -0.012 : 0.012;
        levers.current[ch].position.y += (target - levers.current[ch].position.y) * 0.25;
      }
      void c;
    }
    if (levers.current.main) {
      const on = world ? world.grid.present : true;
      void on;
    }
  });
  const mcbs = [0, 1, 2, 3, 4, 5];
  return (
    <group position={position} rotation={rotation} scale={scale}>
      <mesh castShadow receiveShadow>
        <boxGeometry args={[0.62, 0.62, 0.1]} />
        <meshStandardMaterial color="#D9DDE2" metalness={0.4} roughness={0.45} />
      </mesh>
      <mesh position={[0, 0, 0.051]}>
        <planeGeometry args={[0.58, 0.58]} />
        <meshStandardMaterial color="#2B3038" roughness={0.6} />
      </mesh>
      {/* top rail: MCB/RCCB modules */}
      <mesh position={[0, 0.17, 0.056]}>
        <boxGeometry args={[0.54, 0.012, 0.008]} />
        <meshStandardMaterial color="#8f969f" metalness={0.7} />
      </mesh>
      {mcbs.map((i) => (
        <group key={i} position={[-0.23 + i * 0.075 + (i > 1 ? 0.03 : 0), 0.17, 0.07]}>
          <mesh>
            <boxGeometry args={[i < 2 ? 0.07 : 0.034, 0.13, 0.04]} />
            <meshStandardMaterial color="#F5F5F2" roughness={0.4} />
          </mesh>
          <mesh position={[0, 0.02, 0.022]}>
            <boxGeometry args={[0.014, 0.03, 0.01]} />
            <meshStandardMaterial color={i === 0 ? '#2F6FE0' : '#1d1d1f'} />
          </mesh>
        </group>
      ))}
      {/* contactor panel */}
      <mesh position={[0, -0.06, 0.056]}>
        <boxGeometry args={[0.54, 0.012, 0.008]} />
        <meshStandardMaterial color="#8f969f" metalness={0.7} />
      </mesh>
      {['ch1', 'ch2', 'ch3', 'ch4'].map((ch, i) => {
        const c = h ? h.circuits[ch] : { tier: 'T1' };
        const tc = TIER_META[c.tier].color;
        return (
          <group key={ch} position={[-0.195 + i * 0.13, -0.08, 0.078]}>
            <mesh castShadow>
              <boxGeometry args={[0.1, 0.19, 0.05]} />
              <meshStandardMaterial color="#6E757F" roughness={0.5} />
            </mesh>
            <mesh position={[0, 0.082, 0.026]}>
              <planeGeometry args={[0.09, 0.018]} />
              <meshStandardMaterial color={tc} emissive={tc} emissiveIntensity={0.6} toneMapped={false} />
            </mesh>
            <mesh position={[0, 0.02, 0.026]}>
              <planeGeometry args={[0.05, 0.05]} />
              <meshStandardMaterial ref={(m) => (win.current[ch] = m)} color="#111" emissive="#2BD67B" emissiveIntensity={0.3} toneMapped={false} />
            </mesh>
            <mesh ref={(m) => (levers.current[ch] = m)} position={[0, -0.045, 0.03]}>
              <boxGeometry args={[0.03, 0.02, 0.012]} />
              <meshStandardMaterial color="#1d1d1f" />
            </mesh>
            <mesh position={[0.032, -0.075, 0.026]}>
              <circleGeometry args={[0.006, 10]} />
              <meshStandardMaterial ref={(m) => (leds.current[ch] = m)} color="#222" emissive="#FF4D6D" emissiveIntensity={0} toneMapped={false} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}

// 4-terminal busbar shunt (500 A / 75 mV)
export function Shunt({ position, rotation, scale = 1 }) {
  return (
    <group position={position} rotation={rotation} scale={scale}>
      <mesh castShadow>
        <boxGeometry args={[0.1, 0.012, 0.025]} />
        <meshStandardMaterial color="#C99A3A" metalness={0.85} roughness={0.25} />
      </mesh>
      <mesh position={[0, -0.009, 0]}>
        <boxGeometry args={[0.13, 0.008, 0.03]} />
        <meshStandardMaterial color="#1d1d1f" />
      </mesh>
      {[-0.035, 0.035].map((x) => (
        <group key={x}>
          <mesh position={[x, 0.012, 0]}>
            <cylinderGeometry args={[0.007, 0.007, 0.014, 6]} />
            <meshStandardMaterial color="#aaa" metalness={0.9} />
          </mesh>
          <mesh position={[x * 0.45, 0.01, 0]}>
            <cylinderGeometry args={[0.003, 0.003, 0.01, 6]} />
            <meshStandardMaterial color="#aaa" metalness={0.9} />
          </mesh>
        </group>
      ))}
      {[-0.012, -0.004, 0.004, 0.012].map((x) => (
        <mesh key={x} position={[x, 0.0065, 0]}>
          <boxGeometry args={[0.0035, 0.001, 0.02]} />
          <meshStandardMaterial color="#6d5220" />
        </mesh>
      ))}
    </group>
  );
}

// Split-core CT (SCT-013)
export function CTClamp({ position, rotation, scale = 1 }) {
  return (
    <group position={position} rotation={rotation} scale={scale}>
      <mesh>
        <torusGeometry args={[0.02, 0.009, 10, 24]} />
        <meshStandardMaterial color="#1d1d1f" roughness={0.6} />
      </mesh>
      <mesh position={[0, 0.03, 0]}>
        <boxGeometry args={[0.026, 0.018, 0.02]} />
        <meshStandardMaterial color="#26282e" />
      </mesh>
    </group>
  );
}
