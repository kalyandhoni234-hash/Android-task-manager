import type { Metadata } from "next";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/space-grotesk/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "./globals.css";
import { SITE_URL } from "@/lib/constants";

const siteUrl = SITE_URL.replace(/\/$/, "");
const ogImageUrl = `${siteUrl}/og-image.png`;

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: "Android Task Manager — Monitor your Android device on Windows",
  description:
    "Download the free Windows app that monitors CPU, memory, processes, network, battery and more from your Android device over ADB. Portable EXE, no Python required.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "Android Task Manager — Monitor your Android device on Windows",
    description:
      "Desktop-grade monitoring and process investigation for Android. Download for Windows — no Python required.",
    url: `${siteUrl}/`,
    siteName: "Android Task Manager",
    type: "website",
    images: [{ url: ogImageUrl, width: 1200, height: 630, alt: "Android Task Manager — Android system monitor for Windows" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Android Task Manager — Monitor your Android device on Windows",
    description:
      "Desktop-grade monitoring and process investigation for Android. Download for Windows — no Python required.",
    images: [ogImageUrl],
  },
  icons: {
    icon: "/favicon.ico",
    apple: "/icon.png",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-bg text-text-primary">
        {children}
      </body>
    </html>
  );
}