import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentGameArena - Hong Kong Neon Cyberpunk",
  description: "A Hong Kong Neon Cyberpunk themed game arena",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="font-mono">
        <header className="border-b border-cyberBlue p-4 neon-glow-blue">
          <div className="container mx-auto">
            <h1 className="text-2xl text-cyberBlue glitch font-orbitron text-shadow-neon-blue">
              &gt; AgentGameArena_
            </h1>
            <p className="text-xs text-electricPurple opacity-70 mt-1 font-mono">
              // HONG KONG NEON CYBERPUNK EDITION
            </p>
          </div>
        </header>
        <main className="container mx-auto p-4">
          {children}
        </main>
        <footer className="border-t border-neonPink p-4 mt-8 neon-glow-pink">
          <div className="container mx-auto text-xs text-foreground opacity-50 font-mono">
            <p>&gt; System Status: <span className="text-acidGreen">ONLINE</span> | Uptime: ∞ | Version: 2.0.0 | Theme: CYBERPUNK</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
