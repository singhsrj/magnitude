import { ClerkProvider } from "@clerk/nextjs";
import { AccountSync } from "@/components/AccountSync";
import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

/** Clerk's prebuilt screens in the app's own dark theme (same values as tailwind.config.ts). */
const clerkAppearance = {
  variables: {
    colorPrimary: "#7CF5C0",
    colorBackground: "#11141B",
    colorInput: "#181C26",
    colorInputText: "#ECEEF3",
    colorText: "#ECEEF3",
    colorTextSecondary: "#9AA1B4",
    colorTextOnPrimaryBackground: "#06140F",
    colorNeutral: "#ECEEF3",
    colorDanger: "#FF7A8A",
    colorSuccess: "#7CF5C0",
    borderRadius: "12px",
    fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif",
  },
  elements: {
    card: "border border-[#232837] shadow-none",
    footerActionLink: "text-[#7CF5C0]",
  },
};

const geistSans =Geist({ subsets: ["latin"], variable: "--font-geist-sans" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });

export const metadata: Metadata = {
  title: "Magnitude",
  description: "Which is bigger? A fast mental-math duel with an Elo rating that adapts to you.",
};

export const viewport: Viewport = {
  themeColor: "#0A0C10",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body className="min-h-dvh bg-bg-base text-ink-primary antialiased">
        <ClerkProvider
          afterSignOutUrl="/"
          signInFallbackRedirectUrl="/home"
          signUpFallbackRedirectUrl="/home"
          appearance={clerkAppearance}
        >
          <AccountSync />
          {children}
        </ClerkProvider>
      </body>
    </html>
  );
}
