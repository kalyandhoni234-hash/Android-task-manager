import { Nav } from "@/components/Nav";
import { Hero } from "@/components/Hero";
import { Features } from "@/components/Features";
import { DashboardShowcase } from "@/components/DashboardShowcase";
import { ProcessInspector } from "@/components/ProcessInspector";
import { NetworkBattery } from "@/components/NetworkBattery";
import { ConnectionFlow } from "@/components/ConnectionFlow";
import { Architecture } from "@/components/Architecture";
import { Credibility } from "@/components/Credibility";
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
        <ProcessInspector />
        <NetworkBattery />
        <ConnectionFlow />
        <Architecture />
        <Credibility />
        <OpenSource />
        <Faq />
        <DownloadCta />
      </main>
      <Footer />
    </>
  );
}
