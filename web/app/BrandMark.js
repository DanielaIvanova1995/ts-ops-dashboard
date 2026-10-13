/* Trade Superstore Online brandmark — the orange house/door-arrow icon, rebuilt as SVG so it
   stays sharp at any size and needs no image file. */
export default function BrandMark({ size = 32, title = "Trade Superstore Online" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" role="img" aria-label={title}>
      <rect width="100" height="100" rx="16" fill="#F26A21" />
      <rect x="33" y="20" width="34" height="62" rx="2" fill="#FFFFFF" />
      <polygon points="50,19 84,51 75,59 50,34 25,59 16,51" fill="#FBD6C6" />
      <rect x="43" y="52" width="14" height="30" rx="1.5" fill="#F26A21" />
    </svg>
  );
}
