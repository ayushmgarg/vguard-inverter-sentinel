import { useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { Stars } from '@react-three/drei';
import * as THREE from 'three';

const SUNRISE = 6 * 60 + 15;
const SUNSET = 18 * 60 + 25; // Kochi, late September

export function sunState(t) {
  const m = (((t % 86400) + 86400) % 86400) / 60;
  const dayLen = SUNSET - SUNRISE;
  const f = (m - SUNRISE) / dayLen; // 0..1 during day
  const el = Math.sin(f * Math.PI); // >0 day
  const az = Math.PI * (f - 0.5);
  const night = THREE.MathUtils.clamp((-el + 0.05) / 0.2, 0, 1);
  const golden = THREE.MathUtils.clamp(1 - Math.abs(el) / 0.3, 0, 1);
  return { el, az, night, golden };
}

const skyVert = `varying vec3 vP; void main(){ vP = normalize((modelMatrix*vec4(position,1.0)).xyz); gl_Position = projectionMatrix*viewMatrix*modelMatrix*vec4(position,1.0);} `;
const skyFrag = `uniform vec3 top; uniform vec3 hor; uniform vec3 sunDir; uniform vec3 sunCol; uniform float sunAmt;
varying vec3 vP; void main(){ float h = clamp(vP.y*1.4+0.08,0.0,1.0); vec3 c = mix(hor, top, pow(h,0.7));
 float s = max(dot(vP, normalize(sunDir)),0.0); c += sunCol * (pow(s,280.0)*3.0 + pow(s,12.0)*0.35) * sunAmt;
 gl_FragColor = vec4(c,1.0); }`;

const C = (h) => new THREE.Color(h);
const PAL = {
  dayTop: C('#2F7FD0'), dayHor: C('#CFE7FF'),
  setTop: C('#27345F'), setHor: C('#FF9E62'),
  nightTop: C('#060B1C'), nightHor: C('#22304F'),
};

export default function SkyRig({ world, shadowSize = 48 }) {
  const { scene } = useThree();
  const sun = useRef();
  const hemi = useRef();
  const stars = useRef();
  const uniforms = useMemo(() => ({
    top: { value: new THREE.Color() }, hor: { value: new THREE.Color() },
    sunDir: { value: new THREE.Vector3(0, 1, 0) }, sunCol: { value: new THREE.Color('#FFD7A0') }, sunAmt: { value: 1 },
  }), []);
  const fog = useMemo(() => new THREE.Fog('#CFE7FF', 70, 190), []);
  scene.fog = fog;
  const tmp = useMemo(() => ({ a: new THREE.Color(), b: new THREE.Color() }), []);

  useFrame(() => {
    const { el, az, night, golden } = sunState(world.t);
    scene.userData.night = night;
    const dir = new THREE.Vector3(Math.sin(az) * 1, Math.max(el, -0.3), -0.45).normalize();
    // sky colours
    const dayK = THREE.MathUtils.clamp(el / 0.35, 0, 1);
    tmp.a.copy(PAL.setTop).lerp(PAL.dayTop, dayK).lerp(PAL.nightTop, night);
    tmp.b.copy(PAL.setHor).lerp(PAL.dayHor, dayK).lerp(PAL.nightHor, night);
    uniforms.top.value.copy(tmp.a);
    uniforms.hor.value.copy(tmp.b);
    uniforms.sunDir.value.copy(dir);
    uniforms.sunAmt.value = 1 - night;
    fog.color.copy(tmp.b);
    if (sun.current) {
      const moon = night > 0.5;
      const d = moon ? new THREE.Vector3(-0.4, 0.8, 0.45).normalize() : dir;
      sun.current.position.copy(d).multiplyScalar(80);
      sun.current.intensity = moon ? 0.85 * night : 0.3 + 2.6 * Math.max(0, el);
      sun.current.color.set(moon ? '#9FB6FF' : golden > 0.4 ? '#FFB27A' : '#FFF4E0');
    }
    if (hemi.current) {
      hemi.current.intensity = 0.55 + 0.45 * (1 - night);
      hemi.current.color.copy(tmp.b).lerp(C('#ffffff'), 0.3);
      hemi.current.groundColor.set(night > 0.5 ? '#1c2433' : '#4d5a3b');
    }
    if (stars.current) stars.current.visible = night > 0.35;
  });

  return (
    <>
      <mesh scale={400} renderOrder={-10}>
        <sphereGeometry args={[1, 32, 16]} />
        <shaderMaterial side={THREE.BackSide} depthWrite={false} fog={false} uniforms={uniforms} vertexShader={skyVert} fragmentShader={skyFrag} />
      </mesh>
      <group ref={stars}>
        <Stars radius={180} depth={40} count={2500} factor={5} saturation={0} fade speed={0.4} />
      </group>
      <hemisphereLight ref={hemi} intensity={0.8} />
      <directionalLight
        ref={sun}
        castShadow
        intensity={2}
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0004}
        shadow-normalBias={0.03}
        shadow-camera-left={-shadowSize}
        shadow-camera-right={shadowSize}
        shadow-camera-top={shadowSize}
        shadow-camera-bottom={-shadowSize}
        shadow-camera-near={1}
        shadow-camera-far={220}
      />
    </>
  );
}
