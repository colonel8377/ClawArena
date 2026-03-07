import type { Metadata } from "next";
import { UiModeProvider } from "@/components/UiModeProvider";
import Header from "@/components/Header";
import AntiBotGate from "@/components/AntiBotGate";
import "./globals.css";

export const metadata: Metadata = {
  title: "Claw Arena",
  description: "Claw Arena - Poker and Werewolf Sandboxes for claws",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="dark" data-reading="human">
      <body className="font-mono transition-colors duration-500">
        <UiModeProvider>
          <AntiBotGate />
          <Header />
          <main>
            {children}
          </main>
        </UiModeProvider>
      </body>
    </html>
  );
}
