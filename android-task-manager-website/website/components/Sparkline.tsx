type SparklineProps = {
  className?: string;
  animate?: boolean;
};

const POINTS =
  "M0,32 L14,30 L28,33 L42,20 L56,24 L70,12 L84,18 L98,9 L112,15 L126,6 L140,11 L154,4 L168,10 L182,3 L196,8 L210,2 L224,7 L238,1 L252,5 L266,0 L280,6 L294,3 L308,9 L322,4 L336,10 L340,8";

export function Sparkline({ className = "", animate = true }: SparklineProps) {
  return (
    <svg
      viewBox="0 0 340 40"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <path
        d={POINTS}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={animate ? "animate-sparkline" : ""}
      />
    </svg>
  );
}
