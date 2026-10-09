import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "RAG Lab",
  description: "Measure, diagnose, and improve retrieval-augmented generation.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
