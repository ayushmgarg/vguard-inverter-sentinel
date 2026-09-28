import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import { CameraControls, Html } from '@react-three/drei';
import * as THREE from 'three';
import House, { METER_LOCAL } from './House.jsx';
import SkyRig from '../three/SkyRig.jsx';
import { Palm, Banana, Tree, Bush } from '../three/Nature.jsx';
import { FlowLine, sagPath, Wire } from '../three/Flow.jsx';
import { COLORS } from '../sim/params.js';
import HouseBadge from '../ui/HouseBadge.jsx';
import { useTicker } from '../sim/tick.js';

const POLE_X = [-27, -9, 9, 27];
const POLE_Z = [-5.2, 5.2];
const POLE_H = 8;
const XFMR = [-38, 0, -5.2];

function meterWorld(h) {
  const v = new THREE.Vector3(...METER_LOCAL).applyAxisAngle(new THREE.Vector3(0, 1, 0), h.rot);
  return [h.pos[0] + v.x, h.pos[1] + v.y, h.pos[2] + v.z];
}

let poolTex = null;
function getPoolTex() {
  if (poolTex) return poolTex;
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  r.addColorStop(0, 'rgba(255,255,255,1)');
  r.addColorStop(0.35, 'rgba(255,255,255,0.45)');
  r.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = r;
  g.fillRect(0, 0, 128, 128);
  poolTex = new THREE.CanvasTexture(c);
  return poolTex;
}

function Pole({ position, lamp, world }) {
  const lampMat = useRef();
  const pool = useRef();
  useFrame((state) => {
    const night = state.scene.userData.night ?? 0;
    const on = world.grid.present && night > 0.3;
    if (lampMat.current) lampMat.current.emissiveIntensity = on ? 6 : 0.05;
    if (pool.current) pool.current.opacity = on ? 0.55 * night : 0;
  });
  const dz = position[2] > 0 ? -1 : 1;
  return (
    <group position={position}>
      <mesh position={[0, POLE_H / 2, 0]} castShadow>
        <boxGeometry args={[0.22, POLE_H, 0.22]} />
        <meshStandardMaterial color="#A7A9A6" roughness={0.9} />
      </mesh>
      <mesh position={[0, POLE_H - 0.5, 0]} castShadow>
        <boxGeometry args={[0.12, 0.12, 1.8]} />
        <meshStandardMaterial color="#6b6f75" metalness={0.5} />
      </mesh>
      {[-0.7, 0.7].map((z) => (
        <mesh key={z} position={[0, POLE_H - 0.36, z]}>
          <cylinderGeometry args={[0.05, 0.07, 0.18, 8]} />
          <meshStandardMaterial color="#E9EDF2" roughness={0.3} />
        </mesh>
      ))}
      {lamp && (
        <group position={[0, POLE_H - 1.6, 0]}>
          <mesh position={[0, 0, dz * 0.9]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.035, 0.035, 1.8, 6]} />
            <meshStandardMaterial color="#6b6f75" metalness={0.5} />
          </mesh>
          <mesh position={[0, -0.08, dz * 1.8]}>
            <boxGeometry args={[0.3, 0.08, 0.55]} />
            <meshStandardMaterial color="#3a3e45" />
          </mesh>
          <mesh position={[0, -0.13, dz * 1.8]} rotation={[Math.PI / 2, 0, 0]}>
            <planeGeometry args={[0.24, 0.45]} />
            <meshStandardMaterial ref={lampMat} color="#fff" emissive="#FFE2A8" emissiveIntensity={0} toneMapped={false} side={THREE.DoubleSide} />
          </mesh>
          <mesh position={[0, -POLE_H + 1.62, dz * 2.2]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[7, 7]} />
            <meshBasicMaterial ref={pool} map={getPoolTex()} color="#FFC873" transparent opacity={0} depthWrite={false} blending={THREE.AdditiveBlending} />
          </mesh>
        </group>
      )}
    </group>
  );
}

function Transformer({ world }) {
  const ind = useRef();
  const hum = useRef();
  useFrame(({ clock }) => {
    const on = world.grid.present;
    if (ind.current) {
      ind.current.emissive.set(on ? '#2BD67B' : '#FF4D6D');
      ind.current.emissiveIntensity = on ? 2.5 : Math.sin(clock.elapsedTime * 6) > 0 ? 3 : 0.3;
    }
    if (hum.current) hum.current.position.x = on ? Math.sin(clock.elapsedTime * 100) * 0.004 : 0;
  });
  return (
    <group position={XFMR}>
      {[-1.4, 1.4].map((x) => (
        <mesh key={x} position={[x, 5, 0]} castShadow>
          <boxGeometry args={[0.28, 10, 0.28]} />
          <meshStandardMaterial color="#A7A9A6" roughness={0.9} />
        </mesh>
      ))}
      <mesh position={[0, 3.2, 0]} castShadow receiveShadow>
        <boxGeometry args={[3.3, 0.15, 1.3]} />
        <meshStandardMaterial color="#6b6f75" metalness={0.4} />
      </mesh>
      <group ref={hum} position={[0, 3.3, 0]}>
        <mesh position={[0, 0.8, 0]} castShadow>
          <boxGeometry args={[1.6, 1.6, 1.0]} />
          <meshStandardMaterial color="#7C8A7E" metalness={0.3} roughness={0.5} />
        </mesh>
        {Array.from({ length: 7 }).map((_, i) => (
          <mesh key={i} position={[-0.6 + i * 0.2, 0.75, 0.62]} castShadow>
            <boxGeometry args={[0.05, 1.3, 0.28]} />
            <meshStandardMaterial color="#6E7B70" metalness={0.3} />
          </mesh>
        ))}
        <mesh position={[0, 1.75, 0]}>
          <cylinderGeometry args={[0.45, 0.45, 0.35, 16]} />
          <meshStandardMaterial color="#7C8A7E" metalness={0.3} />
        </mesh>
        {[-0.5, 0, 0.5].map((x) => (
          <mesh key={x} position={[x, 1.85, -0.2]}>
            <cylinderGeometry args={[0.06, 0.1, 0.55, 10]} />
            <meshStandardMaterial color="#8B4E2F" roughness={0.4} />
          </mesh>
        ))}
        <mesh position={[0.65, 1.2, 0.51]}>
          <circleGeometry args={[0.07, 16]} />
          <meshStandardMaterial ref={ind} color="#111" emissive="#2BD67B" toneMapped={false} />
        </mesh>
      </group>
      <mesh position={[0, 9.4, 0]}>
        <boxGeometry args={[3.4, 0.14, 0.14]} />
        <meshStandardMaterial color="#6b6f75" metalness={0.5} />
      </mesh>
      {/* 11 kV incoming from off-scene */}
      <Wire points={[[-40, 9.3, 0], [0, 9.3, 0]]} radius={0.03} color="#222" />
      <Html position={[0, 11.2, 0]} center distanceFactor={36} zIndexRange={[10, 0]}>
        <FeederPill world={world} />
      </Html>
    </group>
  );
}

function FeederPill({ world }) {
  useTicker(world.bus);
  const on = world.grid.present;
  return (
    <div className={`feeder-pill ${on ? 'on' : 'off'}`}>
      <span className="dot" /> Feeder {on ? 'LIVE' : 'OFF'}
    </div>
  );
}

function Ground() {
  const dashes = useMemo(() => Array.from({ length: 22 }, (_, i) => -52 + i * 5), []);
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[400, 400]} />
        <meshStandardMaterial color="#5E8E47" roughness={1} />
      </mesh>
      {/* plots */}
      {[-18, 0, 18].map((x) => [-12, 12].map((z) => (
        <mesh key={`${x}${z}`} position={[x, 0.01, z + (z > 0 ? -0.5 : 0.5)]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
          <planeGeometry args={[10.4, 12.2]} />
          <meshStandardMaterial color="#76A657" roughness={1} />
        </mesh>
      )))}
      {/* road */}
      <mesh position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[130, 7]} />
        <meshStandardMaterial color="#3B3E44" roughness={0.95} />
      </mesh>
      {[-3.8, 3.8].map((z) => (
        <mesh key={z} position={[0, 0.03, z]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
          <planeGeometry args={[130, 1.2]} />
          <meshStandardMaterial color="#B8A68A" roughness={1} />
        </mesh>
      ))}
      {dashes.map((x) => (
        <mesh key={x} position={[x, 0.035, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[2.2, 0.16]} />
          <meshStandardMaterial color="#E9E4D0" />
        </mesh>
      ))}
      {/* distant hills */}
      {[[-70, -95, 26], [-20, -110, 34], [40, -100, 28], [95, -80, 24], [-100, 40, 26], [110, 50, 30], [20, 110, 30], [-50, 105, 24]].map(([x, z, r], i) => (
        <mesh key={i} position={[x, -2, z]} scale={[1, 0.45, 1]}>
          <icosahedronGeometry args={[r, 1]} />
          <meshStandardMaterial color={i % 2 ? '#3E6E3A' : '#467A40'} flatShading roughness={1} />
        </mesh>
      ))}
    </group>
  );
}

function Scenery() {
  const palms = useMemo(() => {
    const out = [];
    const spots = [
      [-26, -18], [-11, -19], [7, -18.5], [25, -19], [-29, 17], [-8, 19], [9, 18], [27, 18.5],
      [-44, -12], [-46, 10], [40, -12], [42, 11], [-60, -30], [55, -28], [-58, 28], [60, 26],
      [-10, -34], [14, -36], [-30, 34], [30, 36], [-24, -8.5], [-6, 8.5], [24.5, -8.3], [11, 8.4],
    ];
    spots.forEach(([x, z], i) => out.push({ x, z, h: 6.5 + ((i * 37) % 5) * 0.6, lean: 0.4 + ((i * 13) % 5) * 0.2, rot: i * 1.3 }));
    return out;
  }, []);
  return (
    <group>
      {palms.map((p, i) => <Palm key={i} position={[p.x, 0, p.z]} height={p.h} lean={p.lean} rot={p.rot} seed={i} />)}
      {[[-13, -16.5], [4.5, -16.6], [22.5, -16.8], [-22, 16.3], [-4, 16.6], [13.5, 16.3]].map(([x, z], i) => <Banana key={i} position={[x, 0, z]} s={1.1} />)}
      {[[-52, -18], [-64, 6], [50, -16], [66, 4], [-35, -30], [34, -32], [-36, 30], [36, 30], [0, -40], [0, 42], [-80, -50], [80, 55]].map(([x, z], i) => <Tree key={i} position={[x, 0, z]} s={1.2 + (i % 3) * 0.25} v={i} />)}
      {[[-21.5, -5.6], [-14.5, -5.6], [-3.4, -5.6], [3.5, -5.6], [14.6, -5.6], [21.5, -5.6], [-21.5, 5.6], [-14.5, 5.6], [-3.4, 5.6], [3.4, 5.6], [14.5, 5.6], [21.5, 5.6]].map(([x, z], i) => <Bush key={i} position={[x, 0, z]} s={0.8} flowers={i % 3} />)}
    </group>
  );
}

function PowerLines({ world, houses }) {
  const lineState = () => ({ on: world.grid.present, color: COLORS.grid, speed: 1.4 });
  const spans = useMemo(() => {
    const out = [];
    const top = POLE_H - 0.45;
    // trunk from transformer along north row, crossing to south row
    const northPts = [[XFMR[0], 9.2, XFMR[2] - 0.7], ...POLE_X.map((x) => [x, top, POLE_Z[0] - 0.7])];
    for (let i = 0; i < northPts.length - 1; i++) out.push(sagPath(northPts[i], northPts[i + 1], 0.5));
    const southPts = POLE_X.map((x) => [x, top, POLE_Z[1] + 0.7]);
    out.push(sagPath([POLE_X[0], top, POLE_Z[0] - 0.7], southPts[0], 0.35));
    for (let i = 0; i < southPts.length - 1; i++) out.push(sagPath(southPts[i], southPts[i + 1], 0.5));
    return out;
  }, []);
  const neutral = useMemo(() => {
    const out = [];
    const top = POLE_H - 0.45;
    const nPts = [[XFMR[0], 9.2, XFMR[2] + 0.7], ...POLE_X.map((x) => [x, top, POLE_Z[0] + 0.7])];
    for (let i = 0; i < nPts.length - 1; i++) out.push(sagPath(nPts[i], nPts[i + 1], 0.5));
    const sPts = POLE_X.map((x) => [x, top, POLE_Z[1] - 0.7]);
    for (let i = 0; i < sPts.length - 1; i++) out.push(sagPath(sPts[i], sPts[i + 1], 0.5));
    return out;
  }, []);
  const drops = useMemo(() => houses.map((h) => {
    const m = meterWorld(h);
    const px = POLE_X.reduce((a, b) => (Math.abs(b - m[0]) < Math.abs(a - m[0]) ? b : a));
    const pz = m[2] < 0 ? POLE_Z[0] : POLE_Z[1];
    return { h, curve: sagPath([px, POLE_H - 0.9, pz], m, 0.45, 20) };
  }), [houses]);
  return (
    <group>
      {spans.map((c, i) => <FlowLine key={i} curve={c} radius={0.03} count={10} pRadius={0.09} wireColor="#1b1d22" state={lineState} />)}
      {neutral.map((c, i) => <Wire key={i} curve={c} radius={0.025} color="#1b1d22" />)}
      {drops.map(({ h, curve }) => (
        <FlowLine key={h.id} curve={curve} radius={0.02} count={6} pRadius={0.07} wireColor="#1b1d22"
          state={() => ({ on: world.grid.present, color: COLORS.grid, speed: 0.8 + h.stats.pOut / 400 })} />
      ))}
    </group>
  );
}

function CameraRig({ controls, focus, houses, corner }) {
  useEffect(() => {
    const c = controls.current;
    if (!c) return;
    if (!focus) {
      c.setLookAt(6, 36, 50, 0, 0, 0, true);
      return;
    }
    const h = houses.find((x) => x.id === focus);
    const up = new THREE.Vector3(0, 1, 0);
    if (corner) {
      const tgt = new THREE.Vector3(2.2, 1.3, -3.3).applyAxisAngle(up, h.rot);
      const cam = new THREE.Vector3(0.6, 4.4, 2.6).applyAxisAngle(up, h.rot);
      c.setLookAt(h.pos[0] + cam.x, cam.y, h.pos[2] + cam.z, h.pos[0] + tgt.x, tgt.y, h.pos[2] + tgt.z, true);
      return;
    }
    const off = new THREE.Vector3(1.5, 10.5, 11.5).applyAxisAngle(up, h.rot);
    c.setLookAt(h.pos[0] + off.x, off.y, h.pos[2] + off.z, h.pos[0], 1.2, h.pos[2], true);
  }, [focus, controls, houses, corner]);
  return null;
}

function VillageScene({ world, focus, xray, onSelect, corner }) {
  const controls = useRef();
  const [hovered, setHovered] = useState(null);
  return (
    <>
      <SkyRig world={world} />
      <Ground />
      <Scenery />
      <Transformer world={world} />
      {POLE_X.map((x) => POLE_Z.map((z) => <Pole key={`${x}${z}`} position={[x, 0, z]} lamp world={world} />))}
      <PowerLines world={world} houses={world.houses} />
      {world.houses.map((h) => (
        <group key={h.id}>
          <House
            h={h} world={world}
            interior={focus === h.id || xray}
            focused={focus === h.id}
            xray={xray}
            onSelect={onSelect}
            hovered={hovered === h.id}
            setHovered={setHovered}
          />
          {!focus && (
            <Html position={[h.pos[0], 8.2, h.pos[2]]} center distanceFactor={34} zIndexRange={[20, 0]}>
              <HouseBadge world={world} h={h} onClick={() => onSelect(h.id)} hovered={hovered === h.id} />
            </Html>
          )}
        </group>
      ))}
      <CameraControls ref={controls} makeDefault minDistance={4} maxDistance={120} maxPolarAngle={1.42} smoothTime={0.6} />
      <CameraRig controls={controls} focus={focus} houses={world.houses} corner={corner} />
    </>
  );
}

export default memo(VillageScene);
