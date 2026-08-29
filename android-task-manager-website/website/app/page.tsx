import { Nav } from "@/components/Nav";
import { Hero } from "@/components/Hero";
import { Credibility } from "@/components/Credibility";
import { Features } from "@/components/Features";
import { ProcessInspector } from "@/components/ProcessInspector";
import { NetworkBattery } from "@/components/NetworkBattery";
import { DashboardShowcase } from "@/components/DashboardShowcase";
import { Copilot } from "@/components/Copilot";
import { Themes } from "@/components/Themes";
import { ConnectionFlow } from "@/components/ConnectionFlow";
import { Architecture } from "@/components/Architecture";
import { Diagnostics } from "@/components/Diagnostics";
import { OpenSource } from "@/components/OpenSource";
import { Faq } from "@/components/Faq";
import { DownloadCta } from "@/components/DownloadCta";
import { Footer } from "@/components/Footer";

export default function Home() {
  return (
    <>
      <Nav />
      <main className="flex-1">
        <Hero />
        <Features />
        <DashboardShowcase />
        <Copilot />
        <Themes />
        <ProcessInspector />
        <NetworkBattery />
        <ConnectionFlow />
        <Architecture />
        <Diagnostics />
        <Credibility />
        <OpenSource />
        <Faq />
        <DownloadCta />
      </main>
      <Footer />
    </>
  );
}
