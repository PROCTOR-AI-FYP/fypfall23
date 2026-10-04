import { useRef, type PointerEvent } from 'react';
import { ShieldCheck, ScanLine, Eye, Fingerprint } from 'lucide-react';

/** CSS 3D scene: no render loop or WebGL context on the monitoring screen. */
export function IntegrityScene({ compact = false }: { compact?: boolean }) {
  const scene = useRef<HTMLDivElement>(null);
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== 'mouse' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    scene.current?.style.setProperty('--scene-x', `${(event.clientY - bounds.top - bounds.height / 2) / 35}deg`);
    scene.current?.style.setProperty('--scene-y', `${-(event.clientX - bounds.left - bounds.width / 2) / 35}deg`);
  };
  const reset = () => {
    scene.current?.style.setProperty('--scene-x', '0deg');
    scene.current?.style.setProperty('--scene-y', '0deg');
  };
  return <div className={`integrity-scene ${compact ? 'integrity-scene-compact' : ''}`} onPointerMove={move} onPointerLeave={reset} aria-hidden="true">
    <div className="integrity-scene-glow" />
    <div ref={scene} className="integrity-sculpture">
      <div className="integrity-orbit orbit-one" /><div className="integrity-orbit orbit-two" />
      <div className="integrity-layer layer-back"><Fingerprint /></div>
      <div className="integrity-layer layer-middle"><ScanLine /></div>
      <div className="integrity-layer layer-front"><ShieldCheck /><span>PROCTOR AI</span></div>
      <div className="integrity-float float-left"><Eye size={17} /><span>Observe</span></div>
      <div className="integrity-float float-right"><ShieldCheck size={17} /><span>Review</span></div>
      <div className="integrity-grid" />
    </div>
  </div>;
}
