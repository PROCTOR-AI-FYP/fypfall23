import { useTheme } from '@/lib/theme-context';

interface LogoProps {
  size?: number | string;
  className?: string;
  alt?: string;
}

export function Logo({ size = 36, className = '', alt = 'ProctorAI Logo' }: LogoProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';

  const dimensionStyle = typeof size === 'number'
    ? { width: `${size}px`, height: `${size}px` }
    : { width: size, height: size };

  return (
    <div
      className={`relative inline-flex items-center justify-center shrink-0 select-none ${className}`}
      style={dimensionStyle}
    >
      {/* Light Mode Logo (dark iris) */}
      <img
        src="/logo-light.png"
        alt={alt}
        className={`w-full h-full object-contain drop-shadow-xs transition-opacity duration-300 ${
          isDark ? 'opacity-0 pointer-events-none' : 'opacity-100'
        }`}
        loading="eager"
      />
      {/* Dark Mode Logo (silver iris) */}
      <img
        src="/logo-dark.png"
        alt={alt}
        className={`absolute inset-0 w-full h-full object-contain drop-shadow-xs transition-opacity duration-300 ${
          isDark ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        loading="eager"
      />
    </div>
  );
}
