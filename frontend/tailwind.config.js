/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Industrial color palette
        'opsgrid': {
          'bg': '#0f172a',
          'panel': '#1e293b',
          'border': '#334155',
          'border-emphasis': '#475569',
          'text': '#f8fafc',
          'text-secondary': '#94a3b8',
          'primary': '#0ea5e9',
          'accent': '#6366f1',
        },
        // Status colors
        'status': {
          'running': '#22c55e',
          'warning': '#eab308',
          'alarm': '#ef4444',
          'stopped': '#dc2626',
          'offline': '#6b7280',
          'maintenance': '#3b82f6',
          'setup': '#f97316',
        },
        // PackML state colors
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
