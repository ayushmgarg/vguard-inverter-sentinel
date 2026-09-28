import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { Part } from './Part.jsx';

// Board is 80 × 60 mm → 0.8 × 0.6 scene units (1 unit = 10 cm). Top surface at y = 0.
const BW = 0.8, BD = 0.6, T = 0.016;

// board-local layout (x across, z depth). Small packages are drawn ~1.6× for legibility.
export const L = {
  C1: [-0.215, -0.13], C6: [0.04, -0.16], C5: [0.235, -0.2], C3: [0.05, 0.04], C13: [-0.06, 0.0],
  C7: [0.2, 0.1], C8: [0.3, 0.02], C10: [-0.05, 0.17], BAT: [-0.21, 0.17], C11: [0.09, 0.19],
  C12: [0.31, -0.07], C2: [-0.34, 0.08], USB: [-0.39, -0.02], C9: [0.335, 0.2],
};

function makeSilk() {
  const W = 1024, H = 768;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const g = c.getContext('2d');
  g.fillStyle = '#0B0D10';
  g.fillRect(0, 0, W, H);
  const X = (x) => ((x + BW / 2) / BW) * W;
  const Y = (z) => ((z + BD / 2) / BD) * H;
  // copper pour texture
  g.strokeStyle = 'rgba(253,195,0,0.10)';
  g.lineWidth = 3;
  for (let i = 0; i < 40; i++) {
    g.beginPath();
    const y = 30 + i * 18;
    g.moveTo(20, y);
    g.lineTo(W * (0.3 + ((i * 37) % 50) / 100), y);
    g.lineTo(W * (0.35 + ((i * 37) % 50) / 100), y + 14);
    g.stroke();
  }
  // HV / SELV isolation moat
  g.fillStyle = '#000';
  g.fillRect(X(0.285), Y(-0.3), 10, Y(0.02) - Y(-0.3));
  g.setLineDash([10, 8]);
  g.strokeStyle = 'rgba(255,77,109,0.8)';
  g.lineWidth = 3;
  g.strokeRect(X(0.29), Y(-0.29), X(0.395) - X(0.29), Y(0.01) - Y(-0.29));
  g.setLineDash([]);
  g.fillStyle = 'rgba(255,77,109,0.9)';
  g.font = 'bold 20px sans-serif';
  g.fillText('HV', X(0.32), Y(-0.02));
  // footprints outline
  g.strokeStyle = 'rgba(255,255,255,0.75)';
  g.lineWidth = 2.5;
  g.font = 'bold 22px sans-serif';
  g.fillStyle = 'rgba(255,255,255,0.85)';
  const lab = (t, x, z) => g.fillText(t, X(x), Y(z));
  lab('C1', -0.33, 0.035); lab('C6', 0.0, -0.085); lab('C5', 0.2, -0.13); lab('C3', 0.02, 0.1);
  lab('C13', -0.1, 0.06); lab('C7', 0.16, 0.155); lab('C8', 0.27, 0.075); lab('C10', -0.1, 0.24);
  lab('C11', 0.06, 0.25); lab('C12', 0.28, -0.12); lab('C2', -0.38, 0.15); lab('JP1 MED', 0.3, 0.27);
  // title
  g.fillStyle = '#FDC300';
  g.font = 'bold 44px sans-serif';
  g.fillText('V-GUARD SENTINEL', X(-0.13), Y(-0.235));
  g.font = '24px sans-serif';
  g.fillStyle = 'rgba(255,255,255,0.7)';
  g.fillText('CORE · EMBEDDED · rev T1', X(-0.13), Y(-0.19));
  // gold pads
  g.fillStyle = '#C9A13B';
  for (let i = 0; i < 90; i++) {
    const x = (i * 97) % W, y = (i * 53) % H;
    g.beginPath();
    g.arc(x, y, 5, 0, Math.PI * 2);
    g.fill();
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

function Chip({ at, w, d, h = 0.012, color = '#15161A', pins = 0, pinSide = 'x' }) {
  return (
    <group position={[at[0], h / 2, at[1]]}>
      <mesh castShadow>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial color={color} roughness={0.45} />
      </mesh>
      <mesh position={[-w / 2 + 0.008, h / 2 + 0.0005, -d / 2 + 0.008]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.003, 8]} />
        <meshStandardMaterial color="#666" />
      </mesh>
      {pins > 0 && Array.from({ length: pins }).map((_, i) => {
        const side = i % 2 ? 1 : -1;
        const k = Math.floor(i / 2);
        const n = Math.ceil(pins / 2);
        const p = -((n - 1) / 2) * 0.012 + k * 0.012;
        return (
          <mesh key={i} position={pinSide === 'x' ? [side * (w / 2 + 0.004), -h / 2 + 0.002, p] : [p, -h / 2 + 0.002, side * (d / 2 + 0.004)]}>
            <boxGeometry args={pinSide === 'x' ? [0.008, 0.003, 0.004] : [0.004, 0.003, 0.008]} />
            <meshStandardMaterial color="#D8D8D8" metalness={0.9} roughness={0.2} />
          </mesh>
        );
      })}
    </group>
  );
}

function Terminal({ at, n = 2, rot = 0 }) {
  return (
    <group position={[at[0], 0.025, at[1]]} rotation={[0, rot, 0]}>
      <mesh castShadow>
        <boxGeometry args={[0.05 * n, 0.05, 0.05]} />
        <meshStandardMaterial color="#2E8B57" roughness={0.5} />
      </mesh>
      {Array.from({ length: n }).map((_, i) => (
        <mesh key={i} position={[-0.025 * (n - 1) + i * 0.05, 0.027, 0]}>
          <cylinderGeometry args={[0.011, 0.011, 0.006, 10]} />
          <meshStandardMaterial color="#C0C0C0" metalness={0.9} roughness={0.25} />
        </mesh>
      ))}
    </group>
  );
}

export default function SentinelBoard({ world, position, scale = 1 }) {
  const silk = useMemo(makeSilk, []);
  const h = world.houses[0];
  const leds = useRef({});
  const hb = useRef();
  useFrame(({ clock }) => {
    const s = h.sen;
    const t = clock.elapsedTime;
    const alive = s.alive;
    if (leds.current.pwr) leds.current.pwr.emissiveIntensity = 3;
    if (leds.current.hb) leds.current.hb.emissiveIntensity = alive && (t % 1) < 0.5 ? 4 : 0;
    if (leds.current.st) {
      leds.current.st.emissive.set(!alive ? '#FF4D6D' : s.outage ? '#FFB020' : '#2BD67B');
      leds.current.st.emissiveIntensity = !alive ? (Math.sin(t * 14) > 0 ? 4 : 0) : 3;
    }
    if (hb.current) hb.current.emissiveIntensity = alive ? 0.15 + 0.1 * Math.sin(t * 6) : 0;
  });
  return (
    <group position={position} scale={scale}>
      {/* PCB */}
      <mesh position={[0, -T / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[BW, T, BD]} />
        <meshStandardMaterial color="#0B0D10" roughness={0.6} />
      </mesh>
      <mesh position={[0, 0.0006, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[BW, BD]} />
        <meshStandardMaterial map={silk} roughness={0.55} metalness={0.1} />
      </mesh>
      {/* mounting holes */}
      {[[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([a, b], i) => (
        <mesh key={i} position={[a * (BW / 2 - 0.035), 0.002, b * (BD / 2 - 0.035)]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.012, 0.022, 20]} />
          <meshStandardMaterial color="#C9A13B" metalness={0.9} roughness={0.3} side={THREE.DoubleSide} />
        </mesh>
      ))}

      {/* C1 ESP32-S3-WROOM-1: PCB + RF shield + PCB antenna */}
      <Part id="C1">
        <group position={[L.C1[0], 0, L.C1[1]]}>
          <mesh position={[0, 0.004, 0]} castShadow>
            <boxGeometry args={[0.18, 0.008, 0.255]} />
            <meshStandardMaterial color="#1F3A5F" roughness={0.5} />
          </mesh>
          <mesh position={[0, 0.017, 0.035]} castShadow>
            <boxGeometry args={[0.16, 0.018, 0.17]} />
            <meshStandardMaterial ref={hb} color="#C8CDD3" metalness={0.95} roughness={0.22} emissive="#35A6FF" emissiveIntensity={0} />
          </mesh>
          {[0, 1, 2, 3, 4].map((i) => (
            <mesh key={i} position={[-0.06 + i * 0.03, 0.0085, -0.1]}>
              <boxGeometry args={[0.006, 0.001, 0.045]} />
              <meshStandardMaterial color="#C9A13B" metalness={0.9} />
            </mesh>
          ))}
        </group>
      </Part>
      <Part id="C6"><Chip at={L.C6} w={0.1} d={0.1} pins={24} /></Part>
      <Part id="C5"><Chip at={L.C5} w={0.07} d={0.06} pins={8} /></Part>
      <Part id="C3"><Chip at={L.C3} w={0.05} d={0.05} pins={10} /></Part>
      <Part id="C13"><Chip at={L.C13} w={0.04} d={0.04} pins={6} /></Part>
      <Part id="C7"><Chip at={L.C7} w={0.11} d={0.045} pins={16} pinSide="z" /></Part>
      <Part id="C8"><Chip at={L.C8} w={0.05} d={0.045} pins={8} /></Part>
      <Part id="C10">
        <Chip at={L.C10} w={0.1} d={0.075} pins={16} pinSide="z" />
        <group position={[L.BAT[0], 0.012, L.BAT[1]]}>
          <mesh castShadow>
            <cylinderGeometry args={[0.085, 0.085, 0.024, 32]} />
            <meshStandardMaterial color="#1a1a1a" />
          </mesh>
          <mesh position={[0, 0.013, 0]}>
            <cylinderGeometry args={[0.075, 0.075, 0.004, 32]} />
            <meshStandardMaterial color="#C8CDD3" metalness={0.95} roughness={0.2} />
          </mesh>
        </group>
      </Part>
      <Part id="C11"><Chip at={L.C11} w={0.05} d={0.045} pins={8} /></Part>
      <Part id="C12"><Chip at={L.C12} w={0.065} d={0.05} h={0.02} pins={4} color="#202226" /></Part>
      <Part id="C2">
        <Chip at={L.C2} w={0.04} d={0.04} pins={6} />
        <mesh position={[L.C2[0], 0.02, L.C2[1] + 0.07]} castShadow>
          <boxGeometry args={[0.06, 0.04, 0.06]} />
          <meshStandardMaterial color="#303236" roughness={0.6} />
        </mesh>
        {[0, 1].map((i) => (
          <mesh key={i} position={[L.C2[0] + 0.05, 0.02, L.C2[1] - 0.02 + i * 0.07]} castShadow>
            <cylinderGeometry args={[0.018, 0.018, 0.04, 14]} />
            <meshStandardMaterial color="#6C6F75" metalness={0.7} roughness={0.3} />
          </mesh>
        ))}
      </Part>
      <Part id="C14">
        <mesh position={[L.USB[0], 0.016, L.USB[1]]} castShadow>
          <boxGeometry args={[0.04, 0.032, 0.09]} />
          <meshStandardMaterial color="#B8BCC2" metalness={0.95} roughness={0.2} />
        </mesh>
        {[['pwr', '#2BD67B'], ['hb', '#35A6FF'], ['st', '#2BD67B']].map(([k, c], i) => (
          <mesh key={k} position={[-0.31 + i * 0.03, 0.006, 0.26]}>
            <boxGeometry args={[0.018, 0.01, 0.012]} />
            <meshStandardMaterial ref={(m) => { if (m) { leds.current[k] = m; m.userData.live = true; } }} color="#111" emissive={c} emissiveIntensity={0} toneMapped={false} />
          </mesh>
        ))}
      </Part>
      <Part id="C9">
        <group position={[L.C9[0], 0, L.C9[1]]}>
          {[-0.012, 0.012].map((x) => (
            <mesh key={x} position={[x, 0.02, 0]}>
              <boxGeometry args={[0.006, 0.04, 0.006]} />
              <meshStandardMaterial color="#D4AF37" metalness={0.9} />
            </mesh>
          ))}
          <mesh position={[0, 0.03, 0]} castShadow>
            <boxGeometry args={[0.04, 0.025, 0.02]} />
            <meshStandardMaterial color="#1E5BD8" />
          </mesh>
        </group>
      </Part>
      {/* connectors J1…J10 */}
      <Terminal at={[-0.26, 0.265]} n={2} />
      <Terminal at={[-0.12, 0.265]} n={2} />
      <Terminal at={[0.01, 0.265]} n={2} />
      <Terminal at={[0.18, 0.265]} n={5} />
      <Terminal at={[0.355, -0.14]} n={2} rot={Math.PI / 2} />
      <mesh position={[-0.37, 0.02, -0.2]} castShadow>
        <boxGeometry args={[0.03, 0.04, 0.1]} />
        <meshStandardMaterial color="#111" />
      </mesh>
    </group>
  );
}

// connector anchor points (board-local, top) for wiring
export const J = {
  J1: [-0.26, 0.05, 0.265], J2: [-0.12, 0.05, 0.265], J4: [0.01, 0.05, 0.265], J8: [0.18, 0.05, 0.265],
  J5: [0.355, 0.05, -0.14], J9: [-0.37, 0.04, -0.23], J10: [-0.37, 0.04, -0.17], J6: [0.355, 0.05, -0.2],
};
