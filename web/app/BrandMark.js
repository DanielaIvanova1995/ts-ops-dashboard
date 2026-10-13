/* Trade Superstore Online / TradeHub brandmark — the real logo (orange tile, white house,
   "We build better together"). Served from /tradehub-logo.png, rounded like an app icon. */
export default function BrandMark({ size = 32, title = "Trade Superstore Online" }) {
  return (
    <img
      src="/tradehub-logo.png"
      width={size}
      height={size}
      alt={title}
      style={{ borderRadius: Math.round(size * 0.22), display: "block", objectFit: "cover" }}
    />
  );
}
