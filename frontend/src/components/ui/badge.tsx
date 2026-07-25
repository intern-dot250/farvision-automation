type BadgeTone = "neutral" | "success" | "warning" | "danger";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral:
    "border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400",
  success:
    "border-emerald-200 text-emerald-600 dark:border-emerald-900 dark:text-emerald-400",
  warning:
    "border-amber-200 text-amber-600 dark:border-amber-900 dark:text-amber-400",
  danger:
    "border-red-200 text-red-600 dark:border-red-900 dark:text-red-400",
};

export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: BadgeTone;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
