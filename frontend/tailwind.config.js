/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'] },
      colors: {
        brand: {
          50: '#eaf4f5',
          100: '#d6e9eb',
          500: '#347f87',
          600: '#246a73',
          700: '#1b5660',
        },
        slate: {
          50: '#f1f8f8',
          100: '#e4f0f1',
          200: '#cedfe1',
          300: '#b0c9cc',
          400: '#83a5aa',
          500: '#5f858b',
          600: '#496d74',
          700: '#36575f',
          800: '#233f47',
          900: '#142f37',
          950: '#0c2229',
        },
      },
    },
  },
  plugins: [],
};
