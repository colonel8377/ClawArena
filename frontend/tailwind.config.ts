import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Hong Kong Neon Cyberpunk Color Scheme
        background: "#050505",
        backgroundSlate: "#121212",
        foreground: "#e0e0e0",
        
        // Neon Accent Colors
        neonPink: "#FF0055",
        cyberBlue: "#00F0FF",
        electricPurple: "#7000FF",
        acidGreen: "#39FF14",
        
        // Legacy colors for compatibility
        primary: "#00F0FF",
        secondary: "#7000FF",
        danger: "#FF0055",
        warning: "#ffaa00",
        border: "#333333",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Courier New", "monospace"],
        orbitron: ["Orbitron", "JetBrains Mono", "sans-serif"],
      },
      boxShadow: {
        'neon-pink': '0 0 5px #FF0055, 0 0 10px #FF0055, 0 0 20px #FF0055',
        'neon-blue': '0 0 5px #00F0FF, 0 0 10px #00F0FF, 0 0 20px #00F0FF',
        'neon-purple': '0 0 5px #7000FF, 0 0 10px #7000FF, 0 0 20px #7000FF',
        'neon-green': '0 0 5px #39FF14, 0 0 10px #39FF14, 0 0 20px #39FF14',
      },
      textShadow: {
        'neon-pink': '0 0 5px #FF0055, 0 0 10px #FF0055',
        'neon-blue': '0 0 5px #00F0FF, 0 0 10px #00F0FF',
        'neon-purple': '0 0 5px #7000FF, 0 0 10px #7000FF',
        'neon-green': '0 0 5px #39FF14, 0 0 10px #39FF14',
      },
    },
  },
  plugins: [
    // Add text-shadow plugin
    function ({ addUtilities }: any) {
      const newUtilities = {
        '.text-shadow-neon-pink': {
          textShadow: '0 0 5px #FF0055, 0 0 10px #FF0055',
        },
        '.text-shadow-neon-blue': {
          textShadow: '0 0 5px #00F0FF, 0 0 10px #00F0FF',
        },
        '.text-shadow-neon-purple': {
          textShadow: '0 0 5px #7000FF, 0 0 10px #7000FF',
        },
        '.text-shadow-neon-green': {
          textShadow: '0 0 5px #39FF14, 0 0 10px #39FF14',
        },
      };
      addUtilities(newUtilities);
    },
  ],
};
export default config;
