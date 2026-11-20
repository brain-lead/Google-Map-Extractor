/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#409cff",
          500: "#0a84ff",
          600: "#0071e3",
          700: "#005bb5",
          800: "#00448a",
          900: "#002f61",
        },
        apple: {
          blue: "#0A84FF",
          green: "#30D158",
          amber: "#FF9F0A",
          red: "#FF453A",
          indigo: "#5E5CE6",
          teal: "#64D2FF",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          '"SF Pro Display"',
          '"SF Pro Text"',
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
      },
      transitionTimingFunction: {
        spring: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
    },
  },
  plugins: [],
};
