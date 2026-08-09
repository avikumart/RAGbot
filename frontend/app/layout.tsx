import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: "Personagraph — Private document intelligence",
  description: "Upload personal documents and ask grounded, person-aware questions with traceable citations.",
  openGraph: {
    title: "Personagraph",
    description: "Private document intelligence with grounded, person-aware answers.",
    type: "website",
    images: [{ url: "/og.png", width: 1536, height: 1024, alt: "Personagraph — Private document intelligence" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Personagraph",
    description: "Private document intelligence with grounded, person-aware answers.",
    images: ["/og.png"],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f4f0e8",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
