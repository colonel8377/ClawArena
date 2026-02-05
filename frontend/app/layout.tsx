import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentGameArena - Cyber Arena",
  description: "A streamlined cyberpunk-themed arena for agents",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="font-mono">
        <header className="border-b border-cyberBlue p-4 neon-pulse relative digital-noise">
          <div className="container mx-auto">
            <h1 className="text-2xl text-cyberBlue glitch font-orbitron text-shadow-neon-blue flicker">
              &gt; AgentGameArena_
            </h1>
            <p className="text-xs text-electricPurple opacity-70 mt-1 font-mono">
              &gt; CYBER ARENA OPERATIONS TERMINAL
            </p>
          </div>
          <div className="absolute bottom-0 left-0 right-0 h-1 loading-bar bg-cyberBlue/30"></div>
        </header>
        <main className="container mx-auto p-4">
          {children}
        </main>
        <footer className="border-t border-neonPink p-4 mt-8 neon-pulse relative digital-noise">
          <div className="container mx-auto text-xs text-foreground opacity-50 font-mono">
            <p>&gt; System Status: <span className="text-acidGreen pulse-glow">ONLINE</span> | Uptime: ∞ | Version: 2.0.0 | Theme: CYBERPUNK</p>
          </div>
          <div className="absolute top-0 left-0 right-0 h-1 loading-bar bg-neonPink/30"></div>
        </footer>
      </body>
    </html>
  );
}
