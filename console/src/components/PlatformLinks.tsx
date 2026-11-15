/**
 * Links to the platform, where Shared Memory's landing page, plans, Terms and Privacy Policy live. Its address is the
 * server's setting; a server not given one shows none.
 */
export function PlatformLinks({ platformUrl }: { platformUrl: string | null }) {
  if (!platformUrl) return null;
  return (
    <nav className="platform-links" aria-label="Shared Memory" data-testid="platform-links">
      <a href={`${platformUrl}/`}>About Shared Memory</a>
      <a href={`${platformUrl}/#pricing`}>Plans</a>
      <a href={`${platformUrl}/terms`}>Terms</a>
      <a href={`${platformUrl}/privacy`}>Privacy</a>
    </nav>
  );
}
