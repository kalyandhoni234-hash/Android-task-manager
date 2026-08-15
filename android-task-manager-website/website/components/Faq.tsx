const FAQ_ITEMS = [
  {
    q: "Does it require Python?",
    a: "No. The packaged AndroidTaskManager.exe is a self-contained, portable application — users do not need to install Python or any package. (Python is only needed to build from source.)",
  },
  {
    q: "Does it require ADB?",
    a: "Yes. Android Task Manager communicates with Android over ADB. The app discovers an existing adb.exe (app-adjacent, PATH, ANDROID_HOME/ANDROID_SDK_ROOT, standard SDK locations) and validates it before use. If ADB is missing, the setup screen links to the official Android Platform-Tools — the app never bundles or silently downloads adb.",
  },
  {
    q: "Does it require root?",
    a: "No — the app is designed and tested for normal (non-root) ADB access. Android still restricts some system information: for example /proc/<pid>/io may be unavailable on some devices, and the UI shows N/A rather than guessing.",
  },
  {
    q: "Does it work without root?",
    a: "Yes — every implemented feature was validated over ordinary USB debugging on a real device (Vivo V2026, Android 11). Individual metrics that Android withholds are reported honestly as unavailable.",
  },
  {
    q: "What Android versions are supported?",
    a: "The current release was validated on Android 11 (Vivo V2026). It relies on standard adb and /proc interfaces, but any specific OS version beyond what was actually tested is not claimed.",
  },
  {
    q: "Is it portable?",
    a: "Yes. It is a portable single EXE — download it, run it, no installation and no Python. The Windows build is validated on Windows 11 (64-bit).",
  },
  {
    q: "How do I enable USB debugging?",
    a: "On the phone: Settings → About phone → tap Build number seven times, then Settings → System → Developer options → enable USB debugging. The app's setup screen also shows these steps.",
  },
  {
    q: "What happens if ADB is not found?",
    a: "The setup screen shows an ADB-missing state: you can Locate an adb.exe you already have, or follow the official Platform-Tools installation guidance. It auto-retries, so the app recovers as soon as adb is available — no restart needed.",
  },
  {
    q: "What happens with multiple devices?",
    a: "You choose which device to monitor from a picker. Connected, offline and unauthorized states are each handled with their own guidance, and hot-plug reconnection is automatic.",
  },
  {
    q: "Does it collect network information?",
    a: "It monitors throughput from /proc/net/dev (no packet capture) and — in the Process Inspector — shows live socket tables (TCP/UDP, IPv4/IPv6) with connections attributed at the UID level and matched to verified Android packages. There is no traffic interception and no telemetry.",
  },
  {
    q: "Can it force-stop an app?",
    a: "Yes. Device actions include Open App, App Info and Force Stop for a selected, package-verified app. Actions are scope-limited: no kill-all, no cache clearing, no factory actions, no restarts.",
  },
  {
    q: "Is the app read-only?",
    a: "Monitoring is read-only — every metric is parsed from /proc, /sys and dumpsys output. The Device Actions (Open App / App Info / Force Stop) are the only features that actively interact with the device, and force-stop is a standard, reversible Android action.",
  },
  {
    q: "Where is the source code?",
    a: "On GitHub, MIT licensed — including 483 automated tests that run headlessly in CI on Python 3.10/3.11/3.12.",
  },
];

export function Faq() {
  return (
    <section className="border-b border-border bg-bg-raised">
      <div className="mx-auto max-w-3xl px-6 py-24">
        <p className="font-mono text-center text-xs uppercase tracking-[0.2em] text-accent-strong">
          FAQ
        </p>
        <h2 className="font-display text-balance mt-3 text-center text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
          Common questions.
        </h2>

        <dl className="mt-12 divide-y divide-border border-t border-border">
          {FAQ_ITEMS.map((item) => (
            <div key={item.q} className="py-6">
              <dt className="text-base font-medium text-text-primary">
                {item.q}
              </dt>
              <dd className="mt-2 text-sm leading-relaxed text-text-secondary">
                {item.a}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}