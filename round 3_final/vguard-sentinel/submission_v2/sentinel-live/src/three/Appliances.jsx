import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

// read ap.powered each frame, smoothed 0..1
function useLevel(ap, rate = 5) {
  const lvl = useRef(0);
  useFrame((_, dt) => {
    const t = ap && ap.powered ? 1 : 0;
    lvl.current += (t - lvl.current) * Math.min(1, dt * rate);
  });
  return lvl;
}

export function CeilingFan({ ap, position, color = '#F4F1EA', blade = '#8B5A3C' }) {
  const rot = useRef();
  const speed = useRef(0);
  useFrame((_, dt) => {
    const target = ap && ap.powered ? 13 : 0;
    speed.current += (target - speed.current) * Math.min(1, dt * (target ? 1.2 : 0.5));
    if (rot.current) rot.current.rotation.y += speed.current * dt;
  });
  return (
    <group position={position}>
      <mesh position={[0, -0.18, 0]}>
        <cylinderGeometry args={[0.02, 0.02, 0.36, 8]} />
        <meshStandardMaterial color="#bbb" metalness={0.6} roughness={0.3} />
      </mesh>
      <group ref={rot} position={[0, -0.4, 0]}>
        <mesh castShadow>
          <cylinderGeometry args={[0.13, 0.15, 0.11, 20]} />
          <meshStandardMaterial color={color} metalness={0.3} roughness={0.35} />
        </mesh>
        {[0, 1, 2].map((i) => (
          <group key={i} rotation={[0, (i * Math.PI * 2) / 3, 0]}>
            <mesh position={[0.45, 0, 0]} rotation={[0.12, 0, 0]} castShadow>
              <boxGeometry args={[0.66, 0.012, 0.13]} />
              <meshStandardMaterial color={blade} roughness={0.6} />
            </mesh>
          </group>
        ))}
      </group>
    </group>
  );
}

export function TubeLight({ ap, position, rotation = [0, 0, 0], light = true }) {
  const lvl = useLevel(ap, 12);
  const mat = useRef();
  const pl = useRef();
  useFrame(() => {
    if (mat.current) mat.current.emissiveIntensity = 0.05 + lvl.current * 5;
    if (pl.current) pl.current.intensity = lvl.current * 9;
  });
  return (
    <group position={position} rotation={rotation}>
      <mesh>
        <boxGeometry args={[1.25, 0.05, 0.07]} />
        <meshStandardMaterial color="#e8e8e8" />
      </mesh>
      <mesh position={[0, -0.05, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.028, 0.028, 1.18, 12]} />
        <meshStandardMaterial ref={mat} color="#fffaf0" emissive="#FFF4DC" emissiveIntensity={0} toneMapped={false} />
      </mesh>
      {light && <pointLight ref={pl} position={[0, -0.3, 0]} color="#FFF1D6" intensity={0} distance={7} decay={1.6} />}
    </group>
  );
}

export function Bulb({ ap, position, drop = 0.35, light = true, color = '#FFD9A0' }) {
  const lvl = useLevel(ap, 12);
  const mat = useRef();
  const pl = useRef();
  useFrame(() => {
    if (mat.current) mat.current.emissiveIntensity = 0.05 + lvl.current * 6;
    if (pl.current) pl.current.intensity = lvl.current * 7;
  });
  return (
    <group position={position}>
      <mesh position={[0, -drop / 2, 0]}>
        <cylinderGeometry args={[0.006, 0.006, drop, 4]} />
        <meshStandardMaterial color="#222" />
      </mesh>
      <mesh position={[0, -drop - 0.03, 0]}>
        <cylinderGeometry args={[0.035, 0.05, 0.07, 12]} />
        <meshStandardMaterial color="#ddd" />
      </mesh>
      <mesh position={[0, -drop - 0.12, 0]}>
        <sphereGeometry args={[0.075, 16, 16]} />
        <meshStandardMaterial ref={mat} color="#fff" emissive={color} emissiveIntensity={0} toneMapped={false} />
      </mesh>
      {light && <pointLight ref={pl} position={[0, -drop - 0.2, 0]} color={color} intensity={0} distance={6} decay={1.6} />}
    </group>
  );
}

export function TV({ ap, position, rotation }) {
  const lvl = useLevel(ap, 8);
  const scr = useRef();
  const col = useMemo(() => new THREE.Color(), []);
  useFrame(({ clock }) => {
    if (!scr.current) return;
    const t = clock.elapsedTime;
    col.setHSL((t * 0.07) % 1, 0.7, 0.45 + 0.1 * Math.sin(t * 3.1));
    scr.current.emissive.copy(col);
    scr.current.emissiveIntensity = lvl.current * (1.6 + 0.4 * Math.sin(t * 7.3));
  });
  return (
    <group position={position} rotation={rotation}>
      {/* stand */}
      <mesh position={[0, 0.25, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.5, 0.5, 0.42]} />
        <meshStandardMaterial color="#6B4430" roughness={0.7} />
      </mesh>
      <mesh position={[0, 0.25, 0.212]}>
        <boxGeometry args={[1.4, 0.02, 0.005]} />
        <meshStandardMaterial color="#3d271b" />
      </mesh>
      {/* panel */}
      <mesh position={[0, 0.55, 0]}>
        <boxGeometry args={[0.3, 0.04, 0.18]} />
        <meshStandardMaterial color="#111" />
      </mesh>
      <mesh position={[0, 0.98, 0]} castShadow>
        <boxGeometry args={[1.24, 0.72, 0.05]} />
        <meshStandardMaterial color="#0c0c0e" roughness={0.3} metalness={0.4} />
      </mesh>
      <mesh position={[0, 0.98, 0.027]}>
        <planeGeometry args={[1.16, 0.64]} />
        <meshStandardMaterial ref={scr} color="#050608" emissive="#000" toneMapped={false} />
      </mesh>
    </group>
  );
}

export function Sofa({ position, rotation, color = '#8C5A7A' }) {
  return (
    <group position={position} rotation={rotation}>
      <mesh position={[0, 0.22, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.9, 0.44, 0.85]} />
        <meshStandardMaterial color={color} roughness={0.9} />
      </mesh>
      <mesh position={[0, 0.62, -0.35]} castShadow>
        <boxGeometry args={[1.9, 0.5, 0.18]} />
        <meshStandardMaterial color={color} roughness={0.9} />
      </mesh>
      {[-0.93, 0.93].map((x) => (
        <mesh key={x} position={[x, 0.42, 0]} castShadow>
          <boxGeometry args={[0.16, 0.42, 0.85]} />
          <meshStandardMaterial color={color} roughness={0.9} />
        </mesh>
      ))}
      {[-0.45, 0.45].map((x) => (
        <mesh key={x} position={[x, 0.5, 0.02]}>
          <boxGeometry args={[0.8, 0.12, 0.7]} />
          <meshStandardMaterial color={new THREE.Color(color).offsetHSL(0, 0, 0.08)} roughness={0.95} />
        </mesh>
      ))}
    </group>
  );
}

export function Bed({ position, rotation, sheet = '#4E7DD1' }) {
  return (
    <group position={position} rotation={rotation}>
      <mesh position={[0, 0.2, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.6, 0.4, 2.0]} />
        <meshStandardMaterial color="#7A5236" roughness={0.7} />
      </mesh>
      <mesh position={[0, 0.48, 0]} castShadow>
        <boxGeometry args={[1.5, 0.18, 1.92]} />
        <meshStandardMaterial color="#F3F1EC" roughness={0.9} />
      </mesh>
      <mesh position={[0, 0.58, 0.25]}>
        <boxGeometry args={[1.52, 0.06, 1.3]} />
        <meshStandardMaterial color={sheet} roughness={0.95} />
      </mesh>
      {[-0.4, 0.4].map((x) => (
        <mesh key={x} position={[x, 0.62, -0.72]}>
          <boxGeometry args={[0.55, 0.12, 0.34]} />
          <meshStandardMaterial color="#fff" roughness={1} />
        </mesh>
      ))}
      <mesh position={[0, 0.65, -1.02]} castShadow>
        <boxGeometry args={[1.6, 0.9, 0.08]} />
        <meshStandardMaterial color="#6A4630" roughness={0.7} />
      </mesh>
    </group>
  );
}

export function Fridge({ ap, position, rotation, color = '#B7BEC8' }) {
  const body = useRef();
  const led = useRef();
  useFrame(({ clock }) => {
    const on = ap && ap.powered;
    if (body.current) body.current.position.x = on ? Math.sin(clock.elapsedTime * 90) * 0.0025 : 0;
    if (led.current) {
      led.current.emissive.set(on ? '#2BD67B' : ap && ap.demand && !ap.powered ? '#FF4D6D' : '#1a5');
      led.current.emissiveIntensity = on ? 3 : ap && ap.demand && !ap.powered ? 2.5 * (Math.sin(clock.elapsedTime * 6) > 0 ? 1 : 0) : 0.4;
    }
  });
  return (
    <group position={position} rotation={rotation}>
      <group ref={body}>
        <mesh position={[0, 0.85, 0]} castShadow receiveShadow>
          <boxGeometry args={[0.66, 1.7, 0.66]} />
          <meshStandardMaterial color={color} metalness={0.55} roughness={0.28} />
        </mesh>
        <mesh position={[0, 1.22, 0.332]}>
          <boxGeometry args={[0.64, 0.01, 0.01]} />
          <meshStandardMaterial color="#555" />
        </mesh>
        <mesh position={[0.26, 1.0, 0.345]}>
          <boxGeometry args={[0.03, 0.42, 0.03]} />
          <meshStandardMaterial color="#666" metalness={0.8} roughness={0.2} />
        </mesh>
        <mesh position={[0.26, 1.42, 0.345]}>
          <boxGeometry args={[0.03, 0.22, 0.03]} />
          <meshStandardMaterial color="#666" metalness={0.8} roughness={0.2} />
        </mesh>
        <mesh position={[-0.2, 1.52, 0.335]}>
          <boxGeometry args={[0.06, 0.03, 0.01]} />
          <meshStandardMaterial ref={led} color="#111" emissive="#2BD67B" toneMapped={false} />
        </mesh>
      </group>
    </group>
  );
}

export function Counter({ position, rotation, length = 2.4 }) {
  return (
    <group position={position} rotation={rotation}>
      <mesh position={[0, 0.43, 0]} castShadow receiveShadow>
        <boxGeometry args={[length, 0.86, 0.6]} />
        <meshStandardMaterial color="#EDE6DA" roughness={0.8} />
      </mesh>
      <mesh position={[0, 0.88, 0]}>
        <boxGeometry args={[length + 0.04, 0.04, 0.64]} />
        <meshStandardMaterial color="#2E2E33" roughness={0.3} metalness={0.2} />
      </mesh>
      <mesh position={[-length / 4, 0.93, 0]}>
        <boxGeometry args={[0.6, 0.06, 0.4]} />
        <meshStandardMaterial color="#111" metalness={0.5} roughness={0.3} />
      </mesh>
      {[-0.15, 0.15].map((dx) => (
        <mesh key={dx} position={[-length / 4 + dx, 0.965, 0]}>
          <torusGeometry args={[0.07, 0.012, 8, 20]} />
          <meshStandardMaterial color="#555" />
        </mesh>
      ))}
    </group>
  );
}

export function Router({ ap, position, rotation }) {
  const leds = useRef([]);
  useFrame(({ clock }) => {
    const on = ap && ap.powered;
    leds.current.forEach((m, i) => {
      if (!m) return;
      const blink = Math.sin(clock.elapsedTime * (6 + i * 3.7) + i) > 0.2;
      m.emissiveIntensity = on ? (i === 0 ? 3 : blink ? 3 : 0.3) : 0;
    });
  });
  return (
    <group position={position} rotation={rotation}>
      <mesh castShadow>
        <boxGeometry args={[0.26, 0.045, 0.17]} />
        <meshStandardMaterial color="#F2F2F2" roughness={0.4} />
      </mesh>
      {[-0.1, 0.1].map((x) => (
        <mesh key={x} position={[x, 0.12, -0.075]} rotation={[-0.15, 0, x > 0 ? -0.2 : 0.2]}>
          <cylinderGeometry args={[0.008, 0.01, 0.22, 6]} />
          <meshStandardMaterial color="#222" />
        </mesh>
      ))}
      {[0, 1, 2, 3].map((i) => (
        <mesh key={i} position={[-0.075 + i * 0.05, 0.001, 0.0855]}>
          <boxGeometry args={[0.014, 0.01, 0.002]} />
          <meshStandardMaterial ref={(m) => (leds.current[i] = m)} color="#111" emissive={i === 0 ? '#2BD67B' : '#35A6FF'} emissiveIntensity={0} toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
}

export function Table({ position, rotation, w = 1.2, d = 0.6, h = 0.75, color = '#8A6240' }) {
  return (
    <group position={position} rotation={rotation}>
      <mesh position={[0, h, 0]} castShadow receiveShadow>
        <boxGeometry args={[w, 0.04, d]} />
        <meshStandardMaterial color={color} roughness={0.6} />
      </mesh>
      {[[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([a, b], i) => (
        <mesh key={i} position={[(a * (w - 0.08)) / 2, h / 2, (b * (d - 0.08)) / 2]}>
          <boxGeometry args={[0.04, h, 0.04]} />
          <meshStandardMaterial color={color} />
        </mesh>
      ))}
    </group>
  );
}

export function Laptop({ ap, position, rotation }) {
  const lvl = useLevel(ap, 8);
  const scr = useRef();
  useFrame(() => { if (scr.current) scr.current.emissiveIntensity = lvl.current * 1.8; });
  return (
    <group position={position} rotation={rotation}>
      <mesh position={[0, 0.01, 0]}>
        <boxGeometry args={[0.34, 0.02, 0.24]} />
        <meshStandardMaterial color="#9aa1ab" metalness={0.6} roughness={0.3} />
      </mesh>
      <group position={[0, 0.02, -0.12]} rotation={[-0.25, 0, 0]}>
        <mesh position={[0, 0.115, 0]}>
          <boxGeometry args={[0.34, 0.23, 0.012]} />
          <meshStandardMaterial color="#9aa1ab" metalness={0.6} roughness={0.3} />
        </mesh>
        <mesh position={[0, 0.115, 0.007]}>
          <planeGeometry args={[0.31, 0.2]} />
          <meshStandardMaterial ref={scr} color="#0a0a0a" emissive="#7FB2FF" emissiveIntensity={0} toneMapped={false} />
        </mesh>
      </group>
    </group>
  );
}

export function IroningBoard({ ap, position, rotation }) {
  const lvl = useLevel(ap, 1.5);
  const plate = useRef();
  useFrame(() => { if (plate.current) plate.current.emissiveIntensity = lvl.current * 3; });
  return (
    <group position={position} rotation={rotation}>
      <mesh position={[0, 0.85, 0]} castShadow>
        <boxGeometry args={[1.25, 0.03, 0.36]} />
        <meshStandardMaterial color="#5C8FD6" roughness={0.9} />
      </mesh>
      {[-0.3, 0.3].map((x) => (
        <mesh key={x} position={[x, 0.42, 0]} rotation={[0, 0, x > 0 ? 0.5 : -0.5]}>
          <boxGeometry args={[0.03, 0.95, 0.03]} />
          <meshStandardMaterial color="#aaa" metalness={0.6} />
        </mesh>
      ))}
      {/* iron */}
      <group position={[0.2, 0.9, 0]}>
        <mesh position={[0, 0.02, 0]}>
          <boxGeometry args={[0.24, 0.035, 0.12]} />
          <meshStandardMaterial ref={plate} color="#C9CCD1" metalness={0.8} roughness={0.2} emissive="#FF5A1F" emissiveIntensity={0} toneMapped={false} />
        </mesh>
        <mesh position={[-0.01, 0.07, 0]}>
          <boxGeometry args={[0.2, 0.06, 0.1]} />
          <meshStandardMaterial color="#E24B4B" roughness={0.4} />
        </mesh>
        <mesh position={[-0.02, 0.13, 0]}>
          <boxGeometry args={[0.14, 0.03, 0.035]} />
          <meshStandardMaterial color="#222" />
        </mesh>
      </group>
    </group>
  );
}

export function CPAP({ ap, position, rotation }) {
  const lvl = useLevel(ap, 6);
  const scr = useRef();
  const hose = useMemo(() => {
    const c = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0.1, 0.05, 0), new THREE.Vector3(0.35, 0.02, 0.05),
      new THREE.Vector3(0.55, 0.25, 0.15), new THREE.Vector3(0.72, 0.18, 0.35),
    ]);
    return new THREE.TubeGeometry(c, 30, 0.018, 8, false);
  }, []);
  useFrame(({ clock }) => {
    if (scr.current) scr.current.emissiveIntensity = lvl.current * (2 + 0.6 * Math.sin(clock.elapsedTime * 1.4));
  });
  return (
    <group position={position} rotation={rotation}>
      <mesh castShadow>
        <boxGeometry args={[0.22, 0.13, 0.18]} />
        <meshStandardMaterial color="#E9EDF2" roughness={0.3} />
      </mesh>
      <mesh position={[0, 0.02, 0.091]}>
        <planeGeometry args={[0.1, 0.05]} />
        <meshStandardMaterial ref={scr} color="#0a0a0a" emissive="#34C3FF" emissiveIntensity={0} toneMapped={false} />
      </mesh>
      <mesh geometry={hose}>
        <meshStandardMaterial color="#9fb3c8" roughness={0.6} />
      </mesh>
    </group>
  );
}

export function ACIndoor({ ap, position, rotation }) {
  const lvl = useLevel(ap, 3);
  const flap = useRef();
  const led = useRef();
  useFrame(() => {
    if (flap.current) flap.current.rotation.x = -0.1 - lvl.current * 0.7;
    if (led.current) led.current.emissiveIntensity = lvl.current * 3;
  });
  return (
    <group position={position} rotation={rotation}>
      <mesh castShadow>
        <boxGeometry args={[0.95, 0.3, 0.22]} />
        <meshStandardMaterial color="#F7F8FA" roughness={0.35} />
      </mesh>
      <group ref={flap} position={[0, -0.13, 0.1]}>
        <mesh position={[0, 0, 0.02]}>
          <boxGeometry args={[0.8, 0.012, 0.06]} />
          <meshStandardMaterial color="#e2e4e8" />
        </mesh>
      </group>
      <mesh position={[0.36, 0.02, 0.111]}>
        <circleGeometry args={[0.012, 12]} />
        <meshStandardMaterial ref={led} color="#111" emissive="#35A6FF" emissiveIntensity={0} toneMapped={false} />
      </mesh>
    </group>
  );
}

export function ACOutdoor({ ap, position, rotation }) {
  const fan = useRef();
  const spd = useRef(0);
  useFrame((_, dt) => {
    const target = ap && ap.powered ? 18 : 0;
    spd.current += (target - spd.current) * Math.min(1, dt * 0.8);
    if (fan.current) fan.current.rotation.z += spd.current * dt;
  });
  return (
    <group position={position} rotation={rotation}>
      <mesh castShadow>
        <boxGeometry args={[0.85, 0.6, 0.3]} />
        <meshStandardMaterial color="#EEF0F2" roughness={0.4} />
      </mesh>
      <mesh position={[-0.12, 0, 0.152]}>
        <circleGeometry args={[0.22, 28]} />
        <meshStandardMaterial color="#2a2d33" />
      </mesh>
      <group ref={fan} position={[-0.12, 0, 0.155]}>
        {[0, 1, 2].map((i) => (
          <mesh key={i} rotation={[0, 0, (i * Math.PI * 2) / 3]} position={[0, 0, 0]}>
            <boxGeometry args={[0.06, 0.38, 0.005]} />
            <meshStandardMaterial color="#9aa0a8" />
          </mesh>
        ))}
      </group>
      {[-0.2, -0.1, 0, 0.1, 0.2].map((y) => (
        <mesh key={y} position={[-0.12, y, 0.158]}>
          <boxGeometry args={[0.46, 0.006, 0.004]} />
          <meshStandardMaterial color="#cfd3d8" />
        </mesh>
      ))}
    </group>
  );
}

export function Shelf({ position, rotation, w = 0.9 }) {
  return (
    <mesh position={position} rotation={rotation} castShadow receiveShadow>
      <boxGeometry args={[w, 0.03, 0.28]} />
      <meshStandardMaterial color="#9C7452" />
    </mesh>
  );
}

export function Plant({ position, s = 1 }) {
  return (
    <group position={position} scale={s}>
      <mesh position={[0, 0.18, 0]} castShadow>
        <cylinderGeometry args={[0.16, 0.12, 0.36, 14]} />
        <meshStandardMaterial color="#B85C38" roughness={0.9} />
      </mesh>
      <mesh position={[0, 0.55, 0]} castShadow>
        <icosahedronGeometry args={[0.3, 1]} />
        <meshStandardMaterial color="#3E8E4E" roughness={0.9} flatShading />
      </mesh>
    </group>
  );
}
