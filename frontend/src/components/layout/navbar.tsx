import { BackendStatus } from "@/components/layout/backend-status";

export function Navbar() {
  return (
    <header className="flex h-14 items-center justify-between border-b border-zinc-200 bg-white px-4 dark:border-zinc-800 dark:bg-zinc-950">
      <span className="text-sm font-medium text-zinc-500 dark:text-zinc-400">
        Farvision ERP Import Automation
      </span>

      <BackendStatus />
    </header>
  );
}
