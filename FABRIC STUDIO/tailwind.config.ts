import type { Config } from 'tailwindcss';

/**
 * Design direction: an indigo dye house.
 * Ground is vat-indigo black, surfaces are warp/weft greys, type is raw calico,
 * and the single loud note is the selvedge line -- the vermilion thread woven
 * into the edge of a shuttle-loom bolt. That red marks state and nothing else.
 */
const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        vat: 'rgb(var(--vat) / <alpha-value>)',
        warp: 'rgb(var(--warp) / <alpha-value>)',
        weft: 'rgb(var(--weft) / <alpha-value>)',
        thread: 'rgb(var(--thread) / <alpha-value>)',
        selvedge: 'rgb(var(--selvedge) / <alpha-value>)',
        indigo: 'rgb(var(--indigo) / <alpha-value>)',
        calico: 'rgb(var(--calico) / <alpha-value>)',
        lint: 'rgb(var(--lint) / <alpha-value>)',
        slub: 'rgb(var(--slub) / <alpha-value>)',
      },
      fontFamily: {
        display: ['var(--font-display)'],
        sans: ['var(--font-body)'],
        mono: ['var(--font-mono)'],
      },
      letterSpacing: {
        loom: '0.18em',
      },
      borderRadius: {
        none: '0',
        sm: '2px',
        DEFAULT: '3px',
        md: '4px',
        lg: '6px',
      },
      keyframes: {
        shuttle: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
        'drawer-in': {
          from: { transform: 'translateX(100%)' },
          to: { transform: 'translateX(0)' },
        },
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'scale(0.98)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
      },
      animation: {
        shuttle: 'shuttle 1.8s cubic-bezier(0.4, 0, 0.2, 1) infinite',
        'drawer-in': 'drawer-in 240ms cubic-bezier(0.2, 0, 0, 1)',
        'fade-up': 'fade-up 200ms ease-out',
        'scale-in': 'scale-in 160ms ease-out',
      },
    },
  },
  plugins: [],
};

export default config;
