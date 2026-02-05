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
        // Theme tokens (RGB triplets defined in globals.css)
        background: "rgb(var(--background) / <alpha-value>)",
        backgroundSlate: "rgb(var(--background-slate) / <alpha-value>)",
        foreground: "rgb(var(--foreground) / <alpha-value>)",

        // Accent tokens
        neonPink: "rgb(var(--neon-pink) / <alpha-value>)",
        cyberBlue: "rgb(var(--cyber-blue) / <alpha-value>)",
        electricPurple: "rgb(var(--electric-purple) / <alpha-value>)",
        acidGreen: "rgb(var(--acid-green) / <alpha-value>)",

        // Legacy colors for compatibility
        primary: "rgb(var(--primary) / <alpha-value>)",
        secondary: "rgb(var(--secondary) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
        warning: "rgb(var(--warning) / <alpha-value>)",
        border: "rgb(var(--border) / <alpha-value>)",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Courier New", "monospace"],
        orbitron: ["Orbitron", "JetBrains Mono", "sans-serif"],
      },
      boxShadow: {
        'neon-pink': '0 0 5px rgb(var(--neon-pink)), 0 0 10px rgb(var(--neon-pink)), 0 0 20px rgb(var(--neon-pink))',
        'neon-blue': '0 0 5px rgb(var(--cyber-blue)), 0 0 10px rgb(var(--cyber-blue)), 0 0 20px rgb(var(--cyber-blue))',
        'neon-purple': '0 0 5px rgb(var(--electric-purple)), 0 0 10px rgb(var(--electric-purple)), 0 0 20px rgb(var(--electric-purple))',
        'neon-green': '0 0 5px rgb(var(--acid-green)), 0 0 10px rgb(var(--acid-green)), 0 0 20px rgb(var(--acid-green))',
      },
      textShadow: {
        'neon-pink': '0 0 5px rgb(var(--neon-pink)), 0 0 10px rgb(var(--neon-pink))',
        'neon-blue': '0 0 5px rgb(var(--cyber-blue)), 0 0 10px rgb(var(--cyber-blue))',
        'neon-purple': '0 0 5px rgb(var(--electric-purple)), 0 0 10px rgb(var(--electric-purple))',
        'neon-green': '0 0 5px rgb(var(--acid-green)), 0 0 10px rgb(var(--acid-green))',
      },
    },
  },
  plugins: [
    // Add text-shadow plugin
    function ({ addUtilities }: any) {
      const newUtilities = {
        '.text-shadow-neon-pink': {
          textShadow: '0 0 5px rgb(var(--neon-pink)), 0 0 10px rgb(var(--neon-pink))',
        },
        '.text-shadow-neon-blue': {
          textShadow: '0 0 5px rgb(var(--cyber-blue)), 0 0 10px rgb(var(--cyber-blue))',
        },
        '.text-shadow-neon-purple': {
          textShadow: '0 0 5px rgb(var(--electric-purple)), 0 0 10px rgb(var(--electric-purple))',
        },
        '.text-shadow-neon-green': {
          textShadow: '0 0 5px rgb(var(--acid-green)), 0 0 10px rgb(var(--acid-green))',
        },
      };
      addUtilities(newUtilities);
    },
  ],
};
export default config;
