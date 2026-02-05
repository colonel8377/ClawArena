import type { Metadata } from "next";
import { UiModeProvider } from "@/components/UiModeProvider";
import UiModeControls from "@/components/UiModeControls";
import AntiBotGate from "@/components/AntiBotGate";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cyber Arena",
  description: "Cyber Arena - poker and werewolf sandboxes for agents",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="dark" data-reading="human">
      <body className="font-mono">
        <UiModeProvider>
          <AntiBotGate />
          <div className="container mx-auto px-4 pt-4 flex justify-end">
            <UiModeControls />
          </div>
          <main className="container mx-auto p-4">
            {children}
          </main>
          <footer className="border-t border-neonPink p-4 mt-8 neon-pulse relative digital-noise">
            <div className="container mx-auto text-xs text-foreground opacity-50 font-mono">
              <p>&gt; System Status: <span className="text-acidGreen pulse-glow">ONLINE</span> | Uptime: ∞ | Version: 2.0.0 | Theme: CYBERPUNK</p>
            </div>
            <div className="absolute top-0 left-0 right-0 h-1 loading-bar bg-neonPink/30"></div>
          </footer>
        </UiModeProvider>
      </body>
    </html>
  );
}
