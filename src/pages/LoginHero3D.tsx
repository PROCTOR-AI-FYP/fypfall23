import { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Float } from '@react-three/drei';
import * as THREE from 'three';

function SeatGrid() {
  const groupRef = useRef<THREE.Group>(null);
  
  // Create a 6x5 grid of seat blocks
  const seats = useMemo(() => {
    const positions: [number, number, number][] = [];
    for (let row = 0; row < 5; row++) {
      for (let col = 0; col < 6; col++) {
        positions.push([
          (col - 2.5) * 1.6,
          0,
          (row - 2) * 1.8 - 1,
        ]);
      }
    }
    return positions;
  }, []);

  useFrame((state) => {
    if (groupRef.current) {
      groupRef.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.15) * 0.08;
      groupRef.current.rotation.x = -0.35 + Math.sin(state.clock.elapsedTime * 0.1) * 0.02;
    }
  });

  return (
    <group ref={groupRef} position={[0, -0.5, 0]}>
      {/* Floor plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.5, 0]}>
        <planeGeometry args={[14, 12]} />
        <meshStandardMaterial
          color="#1a2332"
          transparent
          opacity={0.6}
        />
      </mesh>

      {/* Seat blocks */}
      {seats.map((pos, i) => (
        <SeatBlock
          key={i}
          position={pos}
          index={i}
        />
      ))}

      {/* Subtle scanning line */}
      <ScanLine />
    </group>
  );
}

function SeatBlock({ position, index }: { position: [number, number, number]; index: number }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const isHighlighted = index === 14 || index === 7 || index === 22; // A few seats "active"

  useFrame((state) => {
    if (meshRef.current && isHighlighted) {
      const pulse = Math.sin(state.clock.elapsedTime * 2 + index) * 0.5 + 0.5;
      (meshRef.current.material as THREE.MeshStandardMaterial).emissiveIntensity = pulse * 0.4;
    }
  });

  return (
    <mesh ref={meshRef} position={position}>
      <boxGeometry args={[1, 0.15, 1.2]} />
      <meshStandardMaterial
        color={isHighlighted ? '#2B5EA7' : '#1e2836'}
        emissive={isHighlighted ? '#2B5EA7' : '#000000'}
        emissiveIntensity={0}
        roughness={0.7}
        metalness={0.3}
      />
    </mesh>
  );
}

function ScanLine() {
  const lineRef = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (lineRef.current) {
      lineRef.current.position.z = Math.sin(state.clock.elapsedTime * 0.5) * 4;
      (lineRef.current.material as THREE.MeshStandardMaterial).opacity =
        0.15 + Math.sin(state.clock.elapsedTime * 0.5) * 0.1;
    }
  });

  return (
    <mesh ref={lineRef} position={[0, 0.1, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[12, 0.08]} />
      <meshStandardMaterial
        color="#6FA3EF"
        transparent
        opacity={0.2}
        emissive="#6FA3EF"
        emissiveIntensity={0.5}
      />
    </mesh>
  );
}

export function LoginHero3D() {
  // Check for WebGL support
  const hasWebGL = useMemo(() => {
    try {
      const canvas = document.createElement('canvas');
      return !!(canvas.getContext('webgl') || canvas.getContext('webgl2'));
    } catch {
      return false;
    }
  }, []);

  // Check for reduced motion
  const prefersReducedMotion = useMemo(() => {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }, []);

  if (!hasWebGL) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <div className="text-center">
          <div className="w-20 h-20 mx-auto mb-4 rounded-[8px] bg-(--color-accent-primary)/10 flex items-center justify-center">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent-primary)" strokeWidth="1.5">
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
            </svg>
          </div>
          <p className="text-body-sm text-(--color-text-muted)">Exam Hall Monitoring Grid</p>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full">
      <Canvas
        camera={{ position: [0, 4, 8], fov: 45 }}
        dpr={[1, 1.5]}
        style={{ background: 'transparent' }}
      >
        <ambientLight intensity={0.3} />
        <directionalLight position={[5, 8, 5]} intensity={0.6} color="#c8d6e5" />
        <pointLight position={[-3, 3, -3]} intensity={0.3} color="#2B5EA7" />

        {prefersReducedMotion ? (
          <SeatGrid />
        ) : (
          <Float speed={0.8} rotationIntensity={0.1} floatIntensity={0.3}>
            <SeatGrid />
          </Float>
        )}
      </Canvas>
    </div>
  );
}
