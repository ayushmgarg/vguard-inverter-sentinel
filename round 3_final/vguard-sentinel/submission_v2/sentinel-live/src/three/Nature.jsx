import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

// shared geometries
const frondGeo = (() => {
  const g = new THREE.PlaneGeometry(0.7, 3.2, 4, 12);
  g.translate(0, 1.6, 0);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const y = p.getY(i);
    const x = p.getX(i);
    const t = y / 3.2;
    const width = Math.sin(Math.min(1, t * 1.15) * Math.PI) * 0.9 + 0.1;
    p.setX(i, x * width);
    p.setZ(i, -Math.pow(t, 2) * 1.6 + Math.abs(x) * 0.25);
  }
  g.computeVertexNormals();
  return g;
})();

const trunkMat = new THREE.MeshStandardMaterial({ color: '#8A6B4A', roughness: 0.95 });
const frondMat = new THREE.MeshStandardMaterial({ color: '#3F8F3A', roughness: 0.8, side: THREE.DoubleSide });
const frondMat2 = new THREE.MeshStandardMaterial({ color: '#57A646', roughness: 0.8, side: THREE.DoubleSide });
const coconutMat = new THREE.MeshStandardMaterial({ color: '#6B8E23', roughness: 0.7 });

export function Palm({ position, height = 7, lean = 0.6, rot = 0, seed = 1 }) {
  const trunk = useMemo(() => {
    const pts = [];
    for (let i = 0; i <= 8; i++) {
      const t = i / 8;
      pts.push(new THREE.Vector3(Math.sin(t * 1.4) * lean, t * height, 0));
    }
    const curve = new THREE.CatmullRomCurve3(pts);
    return { curve, geo: new THREE.TubeGeometry(curve, 24, 0.17, 8, false) };
  }, [height, lean]);
  const top = trunk.curve.getPoint(1);
  const crown = useRef();
  useFrame(({ clock }) => {
    if (crown.current) crown.current.rotation.y = Math.sin(clock.elapsedTime * 0.6 + seed) * 0.05;
  });
  const n = 9;
  return (
    <group position={position} rotation={[0, rot, 0]}>
      <mesh geometry={trunk.geo} material={trunkMat} castShadow />
      <group ref={crown} position={top}>
        {Array.from({ length: n }).map((_, i) => (
          <mesh
            key={i}
            geometry={frondGeo}
            material={i % 2 ? frondMat : frondMat2}
            rotation={[-0.35 - (i % 3) * 0.12, (i / n) * Math.PI * 2, 0, 'YXZ']}
            castShadow
          />
        ))}
        {[0, 1, 2, 3].map((i) => (
          <mesh key={i} position={[Math.cos(i * 1.6) * 0.22, -0.25, Math.sin(i * 1.6) * 0.22]} material={coconutMat}>
            <sphereGeometry args={[0.14, 10, 10]} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

const leafMat = new THREE.MeshStandardMaterial({ color: '#4E9A3C', roughness: 0.85, side: THREE.DoubleSide });
export function Banana({ position, s = 1 }) {
  return (
    <group position={position} scale={s}>
      <mesh position={[0, 0.8, 0]} castShadow>
        <cylinderGeometry args={[0.1, 0.14, 1.6, 8]} />
        <meshStandardMaterial color="#7FA350" roughness={0.9} />
      </mesh>
      {Array.from({ length: 6 }).map((_, i) => (
        <mesh key={i} position={[0, 1.55, 0]} rotation={[-0.9, (i / 6) * Math.PI * 2, 0, 'YXZ']} castShadow>
          <planeGeometry args={[0.55, 1.6]} />
          <primitive object={leafMat} attach="material" />
        </mesh>
      ))}
    </group>
  );
}

const treeMats = ['#2F7D3A', '#3B8C45', '#2A6B35', '#4A9B4F'].map((c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.9, flatShading: true }));
export function Tree({ position, s = 1, v = 0 }) {
  return (
    <group position={position} scale={s}>
      <mesh position={[0, 1, 0]} castShadow>
        <cylinderGeometry args={[0.15, 0.22, 2, 7]} />
        <meshStandardMaterial color="#6D4C33" roughness={0.95} />
      </mesh>
      <mesh position={[0, 2.8, 0]} material={treeMats[v % 4]} castShadow>
        <icosahedronGeometry args={[1.5, 1]} />
      </mesh>
      <mesh position={[0.7, 2.3, 0.3]} material={treeMats[(v + 1) % 4]} castShadow>
        <icosahedronGeometry args={[1.0, 1]} />
      </mesh>
      <mesh position={[-0.6, 2.4, -0.4]} material={treeMats[(v + 2) % 4]} castShadow>
        <icosahedronGeometry args={[1.05, 1]} />
      </mesh>
    </group>
  );
}

const bushMat = new THREE.MeshStandardMaterial({ color: '#3E8E4E', roughness: 0.9, flatShading: true });
const flowerMats = ['#FF6B8A', '#FFD23F', '#FF8C42'].map((c) => new THREE.MeshStandardMaterial({ color: c }));
export function Bush({ position, s = 1, flowers = 0 }) {
  return (
    <group position={position} scale={s}>
      <mesh position={[0, 0.35, 0]} material={bushMat} castShadow>
        <icosahedronGeometry args={[0.5, 1]} />
      </mesh>
      {flowers > 0 &&
        Array.from({ length: 6 }).map((_, i) => (
          <mesh key={i} position={[Math.cos(i) * 0.38, 0.45 + (i % 2) * 0.2, Math.sin(i) * 0.38]} material={flowerMats[(i + flowers) % 3]}>
            <sphereGeometry args={[0.07, 6, 6]} />
          </mesh>
        ))}
    </group>
  );
}
