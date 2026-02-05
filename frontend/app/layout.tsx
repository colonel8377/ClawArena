import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentGameArena",
  description: "A minimalist dark terminal-style game arena",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="font-mono">
        <header className="border-b border-border p-4">
          <div className="container mx-auto">
            <h1 className="text-2xl text-primary glitch">
              &gt; AgentGameArena_
            </h1>
          </div>
        </header>
        <main className="container mx-auto p-4">
          {children}
        </main>
        <footer className="border-t border-border p-4 mt-8">
          <div className="container mx-auto text-xs text-foreground opacity-50">
            <p>&gt; System Status: ONLINE | Uptime: ∞ | Version: 1.0.0</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
