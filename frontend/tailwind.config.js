/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Nornickel palette sampled from the provided mark: #004C97.
        brand: {
          navy: '#004C97',
          navy2: '#0060AA',
          blue: '#004C97',
          bluehover: '#003F7D',
          red: '#E30613',        // акцент, реже — CTA
          redhover: '#B4050F',
        },
        surface: {
          DEFAULT: '#F5F7FA',    // светло-серый фон
          card: '#FFFFFF',
          hover: '#EDF1F6',
          divider: '#E1E5EB',
          dark: '#003763',       // тёмный панельный (граф)
          darker: '#050F22',
        },
        ink: {
          DEFAULT: '#0B2545',    // основной текст на светлом
          muted: '#5A6B7B',
          soft: '#8896A5',
          inverse: '#FFFFFF',    // текст на тёмном
          inverseMuted: '#B9C4D0',
        },
        // Node graph palette (стабильные семантические цвета)
        node: {
          experiment: '#004C97',
          material:   '#E30613',
          property:   '#2E7D32',
          mode:       '#7B1FA2',
          equipment:  '#607D8B',
          author:     '#F9A825',
          team:       '#F57C00',
          document:   '#5E35B2',
          conclusion: '#C62828',
          tag:        '#546E7A',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        display: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'monospace'],
      },
      fontSize: {
        display: ['3.5rem', { lineHeight: '1.05', letterSpacing: '-0.02em', fontWeight: '700' }],
        hero: ['2.5rem', { lineHeight: '1.1', letterSpacing: '-0.02em', fontWeight: '700' }],
      },
      boxShadow: {
        card: '0 1px 3px rgba(11, 37, 69, 0.06), 0 4px 12px rgba(11, 37, 69, 0.04)',
        cardHover: '0 4px 12px rgba(11, 37, 69, 0.1), 0 8px 24px rgba(11, 37, 69, 0.06)',
        header: '0 1px 0 rgba(11, 37, 69, 0.08)',
      },
      transitionTimingFunction: {
        smooth: 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
    },
  },
  plugins: [],
};
