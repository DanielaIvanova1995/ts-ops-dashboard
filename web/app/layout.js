import "./globals.css";

export const metadata = {
  title: "TradeHub · Order Processing",
  description: "Trade Superstore Online — order processing board",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
