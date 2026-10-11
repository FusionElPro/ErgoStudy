import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ErgoStudy — Focus, comfortably",
  description: "A local-first study timer with a quiet ergonomic coach."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
