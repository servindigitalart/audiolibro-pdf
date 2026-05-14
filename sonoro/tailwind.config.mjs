/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    extend: {
      colors: {
        // Sonoro design system — warm neutral + amber accent
        sonoro: {
          black:   '#111110',
          white:   '#FDFCFB',
          surface: '#F7F6F3',
          border:  '#E8E7E3',
          muted:   '#9B9B8E',
          // Brand accent — warm amber (sound/warmth)
          amber:   '#F59E0B',
          'amber-dark':  '#D97706',
          'amber-light': '#FEF3C7',
          // Tone variants
          50:  '#FDFCFB',
          100: '#F7F6F3',
          200: '#EFEDE8',
          300: '#E2DFD8',
          400: '#C8C4BA',
          500: '#9B9B8E',
          600: '#6B6B62',
          700: '#4A4A44',
          800: '#2E2E2A',
          900: '#111110',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'system-ui',
          'sans-serif',
        ],
        mono: ['JetBrains Mono', 'SF Mono', 'Fira Code', 'monospace'],
      },
      fontSize: {
        'display-2xl': ['4.5rem', { lineHeight: '1.1', letterSpacing: '-0.025em' }],
        'display-xl':  ['3.75rem', { lineHeight: '1.1', letterSpacing: '-0.02em' }],
        'display-lg':  ['3rem',    { lineHeight: '1.15', letterSpacing: '-0.02em' }],
        'display-md':  ['2.25rem', { lineHeight: '1.2', letterSpacing: '-0.015em' }],
        'display-sm':  ['1.875rem', { lineHeight: '1.25', letterSpacing: '-0.01em' }],
      },
      borderRadius: {
        '2xl': '16px',
        '3xl': '24px',
      },
      boxShadow: {
        'soft':   '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
        'card':   '0 4px 16px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04)',
        'hover':  '0 8px 32px rgba(0,0,0,0.08), 0 2px 6px rgba(0,0,0,0.04)',
        'modal':  '0 20px 60px rgba(0,0,0,0.12), 0 4px 16px rgba(0,0,0,0.06)',
        'glow':   '0 0 0 3px rgba(245,158,11,0.2)',
      },
      animation: {
        'fade-in':      'fadeIn 0.4s ease-out',
        'slide-up':     'slideUp 0.4s ease-out',
        'slide-down':   'slideDown 0.3s ease-out',
        'pulse-slow':   'pulse 3s ease-in-out infinite',
        'waveform':     'waveform 1.2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn:   { from: { opacity: '0' }, to: { opacity: '1' } },
        slideUp:  { from: { opacity: '0', transform: 'translateY(12px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        slideDown:{ from: { opacity: '0', transform: 'translateY(-8px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        waveform: {
          '0%, 100%': { transform: 'scaleY(0.4)' },
          '50%':      { transform: 'scaleY(1)' },
        },
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
};
