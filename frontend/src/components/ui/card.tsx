import type { ReactNode } from "react";

export function Card({
  title,
  children,
}: {
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
      {title && (
        <h2 className="mb-3 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          {title}
        </h2>
      )}
      {children}
    </div>
  );
}
