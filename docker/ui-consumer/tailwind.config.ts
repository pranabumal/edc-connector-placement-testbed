import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#8b5cf6', dark: '#6d28d9' },
      },
    },
  },
  plugins: [],
} satisfies Config
