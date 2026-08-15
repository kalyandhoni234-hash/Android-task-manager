import Image from "next/image";

type ScreenshotFrameProps = {
  /** Path under /public, e.g. "/screenshots/dashboard.png". If the file does not
   * exist yet, an honest placeholder is rendered instead of a fabricated UI mockup. */
  src?: string;
  alt: string;
  label: string;
  className?: string;
  priority?: boolean;
};

export function ScreenshotFrame({
  src,
  alt,
  label,
  className = "",
  priority = false,
}: ScreenshotFrameProps) {
  return (
    <div
      className={`group relative overflow-hidden rounded-xl border border-border-strong bg-bg-raised shadow-[0_0_0_1px_rgba(0,0,0,0.4),0_30px_60px_-25px_rgba(0,0,0,0.6)] ${className}`}
    >
      <div className="flex items-center gap-1.5 border-b border-border bg-surface px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
        <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
        <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
        <span className="font-mono ml-3 text-[11px] text-text-tertiary">
          AndroidTaskManager.exe
        </span>
      </div>
      {src ? (
        <Image
          src={src}
          alt={alt}
          width={1600}
          height={1000}
          priority={priority}
          className="h-auto w-full"
        />
      ) : (
        <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 bg-[radial-gradient(circle_at_center,rgba(76,130,247,0.08),transparent_65%)] px-6 text-center">
          <span className="font-mono rounded-full border border-dashed border-border-strong px-3 py-1 text-[11px] tracking-wide text-text-tertiary">
            screenshot pending
          </span>
          <p className="font-mono max-w-xs text-xs leading-relaxed text-text-tertiary">
            {label}
          </p>
        </div>
      )}
    </div>
  );
}
