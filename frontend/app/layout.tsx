import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

// `subsets` only picks which files are preloaded. The CSS still declares every subset Geist has (latin,
// latin-ext, cyrillic, cyrillic-ext, vietnamese) with a unicode-range, so Cyrillic text loads its file on
// demand. CJK falls back to system fonts (globals.css). next/font downloads the files at build time and
// serves them from this app, so the page makes no request to Google.
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin", "latin-ext"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "English Coach",
  description: "Speaking-style English practice with a local coach",
  manifest: "/manifest.webmanifest",
  // No `icons` here: app/favicon.ico, app/icon.svg and app/apple-icon.png (180 px) are file conventions, and an
  // `icons` entry would hide the SVG. https://nextjs.org/docs/app/api-reference/file-conventions/metadata/app-icons
  appleWebApp: {
    capable: true,
    title: "English Coach",
    statusBarStyle: "default",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  // Matches the manifest's theme_color (light) and globals.css --background (dark).
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0a" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
