import { useState, useRef, useEffect, useCallback } from 'react';
import gsap from 'gsap';
import { useNavigate } from 'react-router-dom';
import { ArrowDown, Eye, Cpu, Lock, ImageIcon, ArrowRight } from 'lucide-react';
import { ThemeToggle } from '@/components/layout/ThemeToggle';
import { useTheme } from '@/lib/theme-context';
import { Logo } from '@/components/ui/Logo';
import Scanner from '@/components/ui/Scanner';
import WarpText from '@/components/ui/WarpText';
import DotField from '@/components/ui/DotField';
import PillNav from '@/components/ui/PillNav';

export function LandingPage() {
  const navigate = useNavigate();
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';

  const [activeSection, setActiveSection] = useState<'Home' | 'About'>('Home');
  const scrollWrapperRef = useRef<HTMLDivElement>(null);
  const heroSectionRef = useRef<HTMLElement>(null);
  const aboutSectionRef = useRef<HTMLElement>(null);
  const activeIndexRef = useRef(0);
  const isAnimatingRef = useRef(false);

  const navigateTo = useCallback((index: 0 | 1) => {
    const scrollWrapper = scrollWrapperRef.current;
    if (!scrollWrapper || isAnimatingRef.current || index === activeIndexRef.current) return;
    
    isAnimatingRef.current = true;
    const targetSection = index === 0 ? heroSectionRef.current : aboutSectionRef.current;
    
    if (targetSection) {
      activeIndexRef.current = index;
      setActiveSection(index === 0 ? 'Home' : 'About');
      
      gsap.to(scrollWrapper, {
        scrollTop: targetSection.offsetTop,
        duration: 0.55,
        ease: "power3.inOut",
        onComplete: () => {
          isAnimatingRef.current = false;
        }
      });
    } else {
      isAnimatingRef.current = false;
    }
  }, []);

  const scrollToHero = useCallback(() => navigateTo(0), [navigateTo]);
  const scrollToAbout = useCallback(() => navigateTo(1), [navigateTo]);

  // Custom Smooth Wheel/Touch Fullpage Scrolling
  useEffect(() => {
    const scrollWrapper = scrollWrapperRef.current;
    if (!scrollWrapper) return;

    let touchStartY = 0;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (isAnimatingRef.current) return;

      if (e.deltaY > 5) {
        navigateTo(1);
      } else if (e.deltaY < -5) {
        navigateTo(0);
      }
    };

    const handleTouchStart = (e: TouchEvent) => {
      touchStartY = e.touches[0].clientY;
    };

    const handleTouchMove = (e: TouchEvent) => {
      e.preventDefault(); // Prevent native swipe scrolling
      if (isAnimatingRef.current) return;

      const touchEndY = e.touches[0].clientY;
      const deltaY = touchStartY - touchEndY;

      if (deltaY > 15) {
        navigateTo(1);
      } else if (deltaY < -15) {
        navigateTo(0);
      }
    };

    scrollWrapper.addEventListener('wheel', handleWheel, { passive: false });
    scrollWrapper.addEventListener('touchstart', handleTouchStart, { passive: false });
    scrollWrapper.addEventListener('touchmove', handleTouchMove, { passive: false });

    return () => {
      scrollWrapper.removeEventListener('wheel', handleWheel);
      scrollWrapper.removeEventListener('touchstart', handleTouchStart);
      scrollWrapper.removeEventListener('touchmove', handleTouchMove);
    };
  }, []);

  // High-performance parallax scroll effect, scroll snapping & active tracking
  useEffect(() => {
    const scrollWrapper = scrollWrapperRef.current;
    if (!scrollWrapper) return;

    let ticking = false;

    const handleScroll = () => {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          const scrollY = scrollWrapper.scrollTop;
          const viewportH = scrollWrapper.clientHeight;

          // 1. Hero Parallax: emblem and title fade out smoothly as user scrolls down
          const heroContent = document.querySelector('.parallax-hero-content') as HTMLElement | null;
          const heroBg = document.querySelector('.parallax-hero-bg') as HTMLElement | null;
          const heroPillars = document.querySelector('.parallax-hero-pillars') as HTMLElement | null;

          if (scrollY < viewportH * 1.2) {
            const progress = Math.min(1, scrollY / (viewportH * 0.7));
            if (heroContent) {
              heroContent.style.transform = `translate3d(0, ${Math.round(scrollY * 0.32)}px, 0) scale(${(1 - progress * 0.08).toFixed(3)})`;
              heroContent.style.opacity = `${Math.max(0, 1 - progress * 1.5).toFixed(2)}`;
            }
            if (heroBg) {
              heroBg.style.transform = `translate3d(0, ${Math.round(scrollY * 0.45)}px, 0)`;
            }
            if (heroPillars) {
              heroPillars.style.transform = `translate3d(0, ${Math.round(scrollY * 0.18)}px, 0)`;
            }
          }

          // 2. About Us Parallax
          const aboutEl = aboutSectionRef.current;
          if (aboutEl) {
            const rect = aboutEl.getBoundingClientRect();
            if (rect.top < viewportH && rect.bottom > 0) {
              const centerOffset = (rect.top + rect.height / 2) - viewportH / 2;
              const imgSlot = aboutEl.querySelector('.parallax-about-image') as HTMLElement | null;
              const textSlot = aboutEl.querySelector('.parallax-about-text') as HTMLElement | null;

              if (imgSlot) {
                imgSlot.style.transform = `translate3d(0, ${Math.round(centerOffset * -0.12)}px, 0)`;
              }
              if (textSlot) {
                textSlot.style.transform = `translate3d(0, ${Math.round(centerOffset * -0.05)}px, 0)`;
              }
            }

            // Track active section cleanly
            if (rect.top <= viewportH * 0.5) {
              activeIndexRef.current = 1;
              setActiveSection('About');
            } else {
              activeIndexRef.current = 0;
              setActiveSection('Home');
            }
          }

          ticking = false;
        });
        ticking = true;
      }
    };

    scrollWrapper.addEventListener('scroll', handleScroll, { passive: true });
    window.addEventListener('resize', handleScroll, { passive: true });

    handleScroll();

    return () => {
      scrollWrapper.removeEventListener('scroll', handleScroll);
      window.removeEventListener('resize', handleScroll);
    };
  }, []);

  return (
    <div 
      ref={scrollWrapperRef}
      className="relative h-screen w-full overflow-hidden bg-(--color-bg-primary) text-(--color-text-primary)"
    >
      {/* ── Fixed Floating Header ──────────────────────────── */}
      <header className="fixed top-0 inset-x-0 z-50 flex items-center justify-between px-6 lg:px-12 py-4 pointer-events-none">
        <PillNav
          logo={<Logo size={22} />}
          brandName="ProctorAI"
          items={[
            { label: 'Home', id: 'Home', onClick: scrollToHero },
            { label: 'About', id: 'About', onClick: scrollToAbout },
            { label: 'Sign In', id: 'SignIn', onClick: () => navigate('/login') }
          ]}
          activeId={activeSection}
          className="shadow-md"
          baseColor={isDark ? "rgba(0,0,0,0.6)" : "rgba(255,255,255,0.7)"}
          borderColor={isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)"}
          pillColor={isDark ? "#ffffff" : "#0f172a"}
          hoveredPillTextColor={isDark ? "#000000" : "#ffffff"}
          pillTextColor={isDark ? "#ffffff" : "#0f172a"}
          brandTextColor={isDark ? "#f8f5ff" : "#0f172a"}
        />
        <div className="pointer-events-auto flex items-center">
          <ThemeToggle />
        </div>
      </header>

      {/* ── Top Fold: Centered Hero Section ────────────────── */}
      <section 
        ref={heroSectionRef}
        id="hero-section"
        className="landing-section w-full min-h-screen h-screen flex flex-col items-center justify-between px-6 lg:px-12 pt-24 pb-6 sm:pt-28 sm:pb-8 text-center relative overflow-hidden bg-(--color-bg-primary)"
      >
        {/* React Bits Scanner visual field (Hero section only) */}
        <div className="absolute inset-0 z-0 overflow-hidden pointer-events-none opacity-45 dark:opacity-75">
          <Scanner
            color1={isDark ? '#2E1065' : '#4F46E5'}
            color2={isDark ? '#4338CA' : '#6366F1'}
            color3={isDark ? '#93C5FD' : '#FFFFFF'}
            speed={0.4}
            sweepSpeed={0.25}
            sweepWidth={1.6}
            sweepFalloff={5.5}
            scale={1.4}
            frequency={2.0}
            ripple={0.22}
            bandDensity={11}
            lineSharpness={5.2}
            glow={0.25}
            scanDirection="vertical"
            colorSpread={0.65}
            brightness={isDark ? 1.0 : 0.75}
            contrast={1.15}
            softness={1.4}
            vignette={0.45}
            scanline={true}
            grain={true}
            grainIntensity={0.04}
            opacity={1.0}
            mouseInteraction={true}
            mouseRadius={0.5}
            mouseStrength={0.5}
          />
        </div>

        {/* Subtle grid background texture */}
        <div 
          className="absolute inset-0 pointer-events-none opacity-30 dark:opacity-15 parallax-hero-bg z-[1]"
          style={{
            backgroundImage: `radial-gradient(var(--color-border-default) 1px, transparent 1px)`,
            backgroundSize: '32px 32px'
          }}
        />

        <div className="relative z-10 max-w-3xl mx-auto flex flex-col items-center parallax-hero-content my-auto">
          {/* Prominent Center Logo Emblem (Bigger size 140) */}
          <div className="mb-2 sm:mb-3 flex items-center justify-center">
            <Logo size={140} className="drop-shadow-lg hover:scale-105 transition-transform duration-300" />
          </div>

          {/* Large ProctorAI Title with React Bits WarpText Effect */}
          <h1 className="sr-only">ProctorAI</h1>
          <div className="w-full max-w-4xl mx-auto -my-12 sm:-my-10 flex items-center justify-center">
            <WarpText
              text="ProctorAI"
              color={isDark ? '#f8f5ff' : '#0f172a'}
              fontFamily="'Outfit', 'Sora', sans-serif"
              fontSize="clamp(3.5rem, 9.5vw, 6.75rem)"
              fontWeight={800}
              letterSpacing="-0.04em"
              warpStrength={0.08}
              warpScale={1.7}
              speed={0.55}
              pointerInfluence={0.42}
              pointerStrength={0.38}
              refraction={0.018}
              ripple
              style={{ height: '280px', width: '100%' }}
            />
          </div>

          {/* Catchy Description */}
          <p className="text-sm sm:text-base text-(--color-text-secondary) max-w-lg font-normal leading-relaxed mb-5">
            Intelligent vision proctoring engineered for high-stakes university examinations. Multi-signal behavioral detection paired with transparent academic due process.
          </p>

          {/* Core Institutional Value Pillars - 3 rectangles with medium rounded corners */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 w-full max-w-2xl pt-4 border-t border-(--color-border-default)/70 parallax-hero-pillars">
            <div className="flex flex-col items-center p-3 rounded-xl bg-(--color-bg-surface)/60 border border-(--color-border-default)/60 backdrop-blur-xs shadow-2xs hover:border-(--color-accent-primary)/30 transition-colors">
              <Eye size={18} className="text-(--color-behavior-head) mb-1.5" />
              <span className="font-[Sora] text-[13px] font-semibold text-(--color-text-primary)">5 Signal Vectors</span>
              <span className="text-[11px] text-(--color-text-muted)">Gaze, pose, lip, phone &amp; objects</span>
            </div>

            <div className="flex flex-col items-center p-3 rounded-xl bg-(--color-bg-surface)/60 border border-(--color-border-default)/60 backdrop-blur-xs shadow-2xs hover:border-(--color-accent-primary)/30 transition-colors">
              <Cpu size={18} className="text-(--color-accent-primary) mb-1.5" />
              <span className="font-[Sora] text-[13px] font-semibold text-(--color-text-primary)">Ceiling Sensor Grid</span>
              <span className="text-[11px] text-(--color-text-muted)">Per-seat real-time calibration</span>
            </div>

            <div className="flex flex-col items-center p-3 rounded-xl bg-(--color-bg-surface)/60 border border-(--color-border-default)/60 backdrop-blur-xs shadow-2xs hover:border-(--color-accent-primary)/30 transition-colors">
              <Lock size={18} className="text-(--color-behavior-gaze) mb-1.5" />
              <span className="font-[Sora] text-[13px] font-semibold text-(--color-text-primary)">Evidentiary Record</span>
              <span className="text-[11px] text-(--color-text-muted)">Auditable teacher-to-HOD tribunal</span>
            </div>
          </div>
        </div>

        {/* Scroll down indicator */}
        <button
          onClick={scrollToAbout}
          aria-label="Scroll to about section"
          className="relative z-10 mt-1 mb-2 inline-flex flex-col items-center gap-1 text-label text-(--color-text-muted) hover:text-(--color-text-primary) transition-colors cursor-pointer group"
        >
          <span className="text-[11px]">Explore About Us</span>
          <ArrowDown size={14} className="animate-bounce group-hover:translate-y-0.5 transition-transform" />
        </button>
      </section>

      {/* ── Middle Section: About Us ──────────────────────── */}
      <section
        ref={aboutSectionRef}
        id="about-section"
        className={`landing-section w-full min-h-screen h-screen flex flex-col justify-between text-white relative overflow-hidden transition-colors duration-300 ${
          isDark ? 'bg-[#0A1B33]' : 'bg-[#1E4A8A]'
        }`}
      >
        {/* React Bits DotField interactive background (About Us section only) */}
        <div className="absolute inset-0 pointer-events-none z-0 overflow-hidden">
          <DotField
            dotRadius={1.75}
            dotSpacing={18}
            bulgeStrength={75}
            cursorRadius={200}
            sparkle={false}
            waveAmplitude={0}
            gradientFrom={isDark ? 'rgba(191, 219, 254, 0.70)' : 'rgba(255, 255, 255, 0.75)'}
            gradientTo={isDark ? 'rgba(147, 197, 253, 0.55)' : 'rgba(219, 234, 254, 0.60)'}
            glowColor={isDark ? 'rgba(59, 130, 246, 0.45)' : 'rgba(96, 165, 250, 0.50)'}
          />
        </div>

        <div className="max-w-6xl mx-auto w-full px-6 lg:px-12 relative z-10 my-auto py-8">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12 items-center">
            {/* Left: Empty rounded rectangle slot for an image */}
            <div className="lg:col-span-5 w-full parallax-about-image">
              <div className="w-full aspect-[4/3] max-w-[420px] mx-auto rounded-2xl border-2 border-dashed border-white/35 bg-white/10 backdrop-blur-xs flex flex-col items-center justify-center p-8 text-center shadow-lg transition-all duration-300 hover:border-white/50 hover:bg-white/[0.14] group">
                <div className="w-16 h-16 rounded-xl bg-white/15 flex items-center justify-center mb-3 text-white/80 group-hover:scale-105 transition-transform shadow-xs">
                  <ImageIcon size={32} className="stroke-[1.75]" />
                </div>
                <span className="text-body font-semibold text-white/95 mb-1">Image Slot</span>
                <span className="text-label text-blue-100/70">Visual asset placeholder</span>
              </div>
            </div>

            {/* Right: Large text saying About Us with description */}
            <div className="lg:col-span-7 flex flex-col items-start parallax-about-text">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-[4px] bg-white/10 border border-white/20 text-label font-medium text-blue-100 mb-3 backdrop-blur-xs">
                <span>Academic Due Process &amp; Vision Integrity</span>
              </div>

              <h2 className="font-[Sora] font-bold text-3xl sm:text-4xl lg:text-5xl text-white tracking-tight mb-4 leading-tight">
                About Us
              </h2>

              <div className="space-y-3 text-body sm:text-[15px] text-blue-50/90 leading-relaxed font-normal max-w-2xl">
                <p>
                  Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.
                </p>
                <p>
                  Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.
                </p>
                <p>
                  Curabitur pretium tincidunt lacus. Nulla gravida orci a odio. Nullam varius, turpis et commodo pharetra, est eros bibendum elit, nec luctus magna felis sollicitudin mauris.
                </p>
              </div>

              <div className="mt-6 flex items-center gap-4">
                <button
                  type="button"
                  onClick={() => navigate('/login')}
                  className="inline-flex items-center justify-center gap-2 px-6 py-2.5 rounded-lg font-semibold text-[14px] bg-white text-[#102A4E] hover:bg-blue-50 hover:text-[#0A1B33] shadow-md transition-colors duration-150 cursor-pointer"
                >
                  <span>Proceed to Sign In</span>
                  <ArrowRight size={14} className="text-[#102A4E]" />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom transition gradient fading to footer */}
        <div 
          className="absolute bottom-0 inset-x-0 h-24 pointer-events-none z-10"
          style={{
            background: isDark 
              ? 'linear-gradient(to top, rgba(0, 0, 0, 0.5) 0%, transparent 100%)' 
              : 'linear-gradient(to top, rgba(15, 35, 65, 0.35) 0%, transparent 100%)'
          }}
        />

        {/* Docked Footer at bottom of About Us - 100% full width, edge-to-edge */}
        <footer className={`w-full shrink-0 border-t backdrop-blur-md py-4 px-6 lg:px-12 flex flex-col sm:flex-row items-center justify-between gap-4 text-label relative z-20 ${
          isDark 
            ? 'border-white/15 bg-black/40 text-blue-100/70' 
            : 'border-white/20 bg-black/20 text-blue-100/85'
        }`}>
          <div className="flex items-center gap-2.5">
            <Logo size={18} />
            <span>ProctorAI University Examination System — Pilot Deployment</span>
          </div>
          <div>
            <span>Evidentiary integrity · Multi-camera spatial inference · FERPA compliant</span>
          </div>
        </footer>
      </section>
    </div>
  );
}
