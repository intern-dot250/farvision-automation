import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/layout/sidebar";
import { Navbar } from "@/components/layout/navbar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Farvision Automation",
  description: "Automates preparation of Farvision ERP import sheets.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex h-full min-h-screen bg-white text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        <Sidebar />
        <div className="flex min-h-screen flex-1 flex-col">
          <Navbar />
          <main className="flex-1 p-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
