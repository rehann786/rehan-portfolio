/**
 * components/Analytics.tsx
 * --------------------------------------------------------------
 * Loads the Google Analytics 4 (gtag.js) script.
 * Renders nothing if NEXT_PUBLIC_GA_ID is not set, so the site
 * works fine before GA is configured.
 */
import Script from 'next/script';

export default function Analytics() {
  const gaId = process.env.NEXT_PUBLIC_GA_ID;

  // No GA ID -> render nothing.
  if (!gaId || gaId.includes('XXXX')) return null;

  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${gaId}`}
        strategy="afterInteractive"
      />
      <Script id="ga4-init" strategy="afterInteractive">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          gtag('config', '${gaId}');
        `}
      </Script>
    </>
  );
}
