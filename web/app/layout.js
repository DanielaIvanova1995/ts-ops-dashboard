import "./globals.css";
import AppShell from "./AppShell";

export const metadata = {
  title: "TradeHub",
  description: "Trade Superstore Online — operations",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body><AppShell>{children}</AppShell></body>
    </html>
  );
}
