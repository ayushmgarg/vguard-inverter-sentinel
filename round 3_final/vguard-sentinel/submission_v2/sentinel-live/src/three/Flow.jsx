import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

// Poly-line path (crisp conduit corners) → THREE.CurvePath
export function makePath(points) {
  const path = new THREE.CurvePath();
  for (let i = 0; i < points.length - 1; i++) {
    const a = new THREE.Vector3(...points[i]);
    const b = new THREE.Vector3(...points[i + 1]);
    if (a.distanceTo(b) > 1e-4) path.add(new THREE.LineCurve3(a, b));
  }
  return path;
}

// Catenary-ish sagging overhead line between two points
export function sagPath(a, b, sag = 0.6, n = 16) {
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    pts.push(new THREE.Vector3(
      a[0] + (b[0] - a[0]) * t,
      a[1] + (b[1] - a[1]) * t - sag * 4 * t * (1 - t),
      a[2] + (b[2] - a[2]) * t,
    ));
  }
  return new THREE.CatmullRomCurve3(pts);
}

const tmpM = new THREE.Matrix4();
const tmpV = new THREE.Vector3();
const tmpS = new THREE.Vector3();
const tmpQ = new THREE.Quaternion();

/**
 * A wire with glowing particles flowing along it.
 * `state()` is read every frame → { on, color, dir (1|-1), speed }
 */
export function FlowLine({
  curve, points, state, count = 10, radius = 0.02, pRadius = 0.055,
  wireColor = '#2a2f3a', showWire = true, segments, visible = true,
}) {
  const path = useMemo(() => curve || makePath(points), [curve, points]);
  const length = useMemo(() => path.getLength(), [path]);
  const tube = useMemo(
    () => new THREE.TubeGeometry(path, segments || Math.max(8, Math.round(length * 6)), radius, 6, false),
    [path, length, radius, segments],
  );
  const inst = useRef();
  const mat = useRef();
  const wireMat = useRef();
  const phase = useRef(Math.random());
  const level = useRef(0);
  const n = Math.max(3, Math.round(count * Math.min(3, Math.max(0.6, length / 4))));

  useFrame((_, dt) => {
    if (!inst.current) return;
    const s = state ? state() : { on: true };
    const target = s.on ? 1 : 0;
    level.current += (target - level.current) * Math.min(1, dt * 6);
    const spd = (s.speed ?? 1) * 0.35 / Math.max(1, length / 3);
    phase.current = (phase.current + dt * spd * (s.dir ?? 1) + 1) % 1;
    if (s.color && mat.current) mat.current.color.set(s.color);
    if (wireMat.current) {
      wireMat.current.emissive.set(s.color || '#000');
      wireMat.current.emissiveIntensity = level.current * 0.35;
    }
    const sc = level.current < 0.02 ? 0 : level.current;
    for (let i = 0; i < n; i++) {
      const u = (phase.current + i / n) % 1;
      path.getPointAt(u, tmpV);
      tmpS.setScalar(sc);
      tmpM.compose(tmpV, tmpQ, tmpS);
      inst.current.setMatrixAt(i, tmpM);
    }
    inst.current.instanceMatrix.needsUpdate = true;
  });

  return (
    <group visible={visible}>
      {showWire && (
        <mesh geometry={tube}>
          <meshStandardMaterial ref={wireMat} color={wireColor} roughness={0.6} metalness={0.1} />
        </mesh>
      )}
      <instancedMesh ref={inst} args={[null, null, n]} frustumCulled={false}>
        <sphereGeometry args={[pRadius, 10, 10]} />
        <meshBasicMaterial ref={mat} color="#FDC300" toneMapped={false} />
      </instancedMesh>
    </group>
  );
}

// Plain static wire
export function Wire({ points, curve, radius = 0.02, color = '#222', emissive }) {
  const path = useMemo(() => curve || makePath(points), [curve, points]);
  const geo = useMemo(() => new THREE.TubeGeometry(path, Math.max(8, Math.round(path.getLength() * 6)), radius, 6, false), [path, radius]);
  return (
    <mesh geometry={geo}>
      <meshStandardMaterial color={color} roughness={0.5} emissive={emissive || '#000'} emissiveIntensity={emissive ? 0.6 : 0} />
    </mesh>
  );
}
