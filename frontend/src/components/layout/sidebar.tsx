"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/" },
  { label: "History", href: "/history" },
  { label: "Logs", href: "/logs" },
  { label: "Settings", href: "/settings" },
  { label: "Override Rules", href: "/override-rules" },
] as const;

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await fetch("/api/logout", { method: "POST" });
      router.push("/login");
      router.refresh();
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <aside className="hidden w-56 shrink-0 border-r border-zinc-200 bg-zinc-50 md:flex md:flex-col dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex h-14 items-center border-b border-zinc-200 px-4 dark:border-zinc-800">
        <span className="text-sm font-semibold tracking-tight">
          Farvision Automation
        </span>
      </div>

      <nav className="flex flex-1 flex-col gap-1 p-3">
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "text-zinc-600 hover:bg-zinc-200/60 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
              }`}
            >
              {item.label}
            </Link>
          );
        })}

        <button
          onClick={handleLogout}
          disabled={loggingOut}
          className="mt-1 rounded-md px-3 py-2 text-left text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-200/60 hover:text-zinc-900 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
        >
          {loggingOut ? "Logging out…" : "Logout"}
        </button>
      </nav>
    </aside>
  );
}
