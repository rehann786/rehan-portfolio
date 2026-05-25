import type { Config } from 'tailwindcss';

/**
 * Tailwind theme.
 * Color direction: Wichita State inspired — black/gray base with a yellow accent.
 */
const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Background layers (darkest -> lighter)
        ink: '#0a0a0b',
        coal: '#121214',
        slate: '#1c1c20',
        steel: '#2a2a30',
        // Text
        chalk: '#f4f4f5',
        ash: '#a1a1aa',
        // Accent — WSU "Shocker" yellow / gold
        gold: '#ffc72c',
        goldDark: '#e0a800',
      },
      fontFamily: {
        // Distinctive display + clean body. Loaded via next/font in layout.tsx
        display: ['var(--font-display)', 'sans-serif'],
        body: ['var(--font-body)', 'sans-serif'],
        mono: ['var(--font-mono)', 'monospace'],
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'grid-pan': {
          '0%': { backgroundPosition: '0 0' },
          '100%': { backgroundPosition: '40px 40px' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.6s ease-out forwards',
        'grid-pan': 'grid-pan 20s linear infinite',
      },
    },
  },
  plugins: [],
};

export default config;
