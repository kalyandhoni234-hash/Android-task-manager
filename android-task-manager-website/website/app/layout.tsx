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

// No production domain exists yet, so no absolute canonical/OG URLs are
// emitted. Set SITE_URL (e.g. "https://android-task-manager.example") at
// deploy time to opt into absolute canonical + Open Graph URLs.
const siteUrl = process.env.SITE_URL;

export const metadata: Metadata = {
  title: "Android Task Manager — Android System Monitor for Windows",
  description:
    "Monitor CPU, memory, processes, battery and network activity from your Android device on Windows.",
  ...(siteUrl
    ? {
        metadataBase: new URL(siteUrl),
        alternates: { canonical: "/" },
        openGraph: { url: siteUrl },
      }
    : {}),
  icons: {
    icon: "/favicon.ico",
  },
  openGraph: {
    title: "Android Task Manager — Android System Monitor for Windows",
    description:
      "Monitor CPU, memory, processes, battery and network activity from your Android device on Windows.",
    siteName: "Android Task Manager",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Android Task Manager — Android System Monitor for Windows",
    description:
      "Monitor CPU, memory, processes, battery and network activity from your Android device on Windows.",
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
