import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#3b82f6', dark: '#1d4ed8' },
      },
    },
  },
  plugins: [],
} satisfies Config
