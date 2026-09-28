import { createContext, useContext, useEffect, useRef } from 'react';
import * as THREE from 'three';

// Shared hover/select context for identifiable parts
export const PartCtx = createContext({ hov: null, sel: null, setHov: () => {}, setSel: () => {} });

const box = new THREE.Box3();
const v = new THREE.Vector3();

export function Part({ id, children, ...props }) {
  const ref = useRef();
  const { hov, sel, setHov, setSel } = useContext(PartCtx);
  const active = (hov && hov.id === id) || (sel && sel.id === id);
  useEffect(() => {
    if (!ref.current) return;
    ref.current.traverse((o) => {
      if (!o.isMesh || !o.material || !('emissive' in o.material)) return;
      if (!o.userData.__em) o.userData.__em = { c: o.material.emissive.clone(), i: o.material.emissiveIntensity };
      if (active) {
        o.material.emissive.set('#FDC300');
        o.material.emissiveIntensity = Math.max(o.userData.__em.i, 0.35);
      } else if (!o.userData.live) {
        o.material.emissive.copy(o.userData.__em.c);
        o.material.emissiveIntensity = o.userData.__em.i;
      }
    });
  }, [active]);
  const where = () => {
    box.setFromObject(ref.current);
    box.getCenter(v);
    return [v.x, box.max.y + 0.05, v.z];
  };
  return (
    <group
      ref={ref}
      {...props}
      onPointerOver={(e) => { e.stopPropagation(); setHov({ id, pos: where() }); document.body.style.cursor = 'pointer'; }}
      onPointerOut={(e) => { e.stopPropagation(); setHov(null); document.body.style.cursor = ''; }}
      onClick={(e) => { e.stopPropagation(); setSel({ id, pos: where() }); }}
    >
      {children}
    </group>
  );
}
