/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "./video/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Industrial color palette using CSS variables
        'opsgrid': {
          'bg': 'var(--color-bg)',
          'panel': 'var(--color-panel)',
          'border': 'var(--color-border)',
          'border-emphasis': 'var(--color-border-emphasis)',
          'text': 'var(--color-text)',
          'text-secondary': 'var(--color-text-secondary)',
          'primary': 'var(--color-primary)',
          'accent': 'var(--color-accent)',
          'hover': 'var(--color-hover)',
        },
        // Status colors (unchanged)
        'status': {
          'running': '#22c55e',
          'warning': '#eab308',
          'alarm': '#ef4444',
          'stopped': '#dc2626',
          'offline': '#6b7280',
          'maintenance': '#3b82f6',
          'setup': '#f97316',
        },
        // PackML state colors (unchanged)
        'packml': {
          'idle': '#6b7280',
          'starting': '#f59e0b',
          'execute': '#22c55e',
          'held': '#eab308',
          'suspended': '#f97316',
          'aborted': '#ef4444',
          'stopped': '#dc2626',
        }
      },
      animation: {
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'blink': 'blink 1s step-end infinite',
      },
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.3' },
        }
      }
    },
  },
  plugins: [],
}
