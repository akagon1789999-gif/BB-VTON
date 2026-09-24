'use client';

/**
 * Results live on FASHN's CDN, so a plain `download` attribute is ignored
 * cross-origin. Fetch the bytes and hand the browser a blob instead.
 */
export async function downloadImage(url: string, fileName: string): Promise<void> {
  if (url.startsWith('data:')) {
    triggerDownload(url, fileName);
    return;
  }

  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not fetch the result (${res.status}).`);
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  triggerDownload(objectUrl, fileName);
  setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000);
}

function triggerDownload(href: string, fileName: string): void {
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
