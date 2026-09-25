import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import gsap from 'gsap';
import './PillNav.css';

export interface PillNavItem {
  label: string;
  onClick: () => void;
  id: string;
}

interface PillNavProps {
  logo?: ReactNode;
  brandName?: string;
  items: PillNavItem[];
  activeId: string;
  className?: string;
  ease?: string;
  baseColor?: string;
  pillColor?: string;
  hoveredPillTextColor?: string;
  pillTextColor?: string;
  brandTextColor?: string;
  borderColor?: string;
}

export default function PillNav({
  logo,
  brandName,
  items,
  activeId,
  className = '',
  ease = 'power3.out',
  baseColor = '#000000',
  pillColor = '#ffffff',
  hoveredPillTextColor = '#000000',
  pillTextColor = '#ffffff',
  brandTextColor = '#ffffff',
  borderColor = 'rgba(255,255,255,0.1)',
}: PillNavProps) {
  const containerRef = useRef<HTMLUListElement>(null);
  const activeBgRef = useRef<HTMLDivElement>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const targetId = hoveredId || activeId;

  useEffect(() => {
    if (!containerRef.current || !activeBgRef.current) return;

    const targetBtn = containerRef.current.querySelector(
      `[data-id="${targetId}"]`
    ) as HTMLElement;

    if (targetBtn) {
      const parentRect = containerRef.current.getBoundingClientRect();
      const btnRect = targetBtn.getBoundingClientRect();

      gsap.to(activeBgRef.current, {
        x: btnRect.left - parentRect.left,
        width: btnRect.width,
        duration: 0.15,
        ease,
      });
    }
  }, [targetId, ease]);

  return (
    <div
      className={`pill-nav-container ${className}`}
      style={{
        '--base-color': baseColor,
        '--pill-color': pillColor,
        '--hover-text-color': hoveredPillTextColor,
        '--pill-text-color': pillTextColor,
        borderColor: borderColor,
      } as React.CSSProperties}
    >
      <div className="flex items-center gap-4">
        {(logo || brandName) && (
          <div className="pill-nav-brand">
            {logo && <div className="flex-shrink-0">{logo}</div>}
            {brandName && (
              <span
                className="font-[Sora] font-bold text-sm tracking-tight"
                style={{ color: brandTextColor }}
              >
                {brandName}
              </span>
            )}
          </div>
        )}
      </div>

      <ul
        ref={containerRef}
        className="pill-nav-menu"
        onMouseLeave={() => setHoveredId(null)}
      >
        <div ref={activeBgRef} className="pill-nav-active-bg" />
        {items.map((item) => (
          <li key={item.id} className="pill-nav-item">
            <button
              type="button"
              data-id={item.id}
              onClick={item.onClick}
              onMouseEnter={() => setHoveredId(item.id)}
              className={`pill-nav-btn ${targetId === item.id ? 'active' : ''}`}
            >
              {item.label}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
