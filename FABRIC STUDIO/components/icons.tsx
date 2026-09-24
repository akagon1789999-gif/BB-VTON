import type { SVGProps } from 'react';

type P = SVGProps<SVGSVGElement>;

const base = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  width: 16,
  height: 16,
  'aria-hidden': true,
};

export const IconUpload = (p: P) => (
  <svg {...base} {...p}><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" /><path d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" /></svg>
);
export const IconClose = (p: P) => (
  <svg {...base} {...p}><path d="M6 6l12 12M18 6L6 18" /></svg>
);
export const IconDice = (p: P) => (
  <svg {...base} {...p}><rect x="3.5" y="3.5" width="17" height="17" rx="3" /><circle cx="8.5" cy="8.5" r="1.1" fill="currentColor" stroke="none" /><circle cx="15.5" cy="15.5" r="1.1" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" /></svg>
);
export const IconDownload = (p: P) => (
  <svg {...base} {...p}><path d="M12 4v11m0 0l-4-4m4 4l4-4" /><path d="M5 19h14" /></svg>
);
export const IconTrash = (p: P) => (
  <svg {...base} {...p}><path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13" /></svg>
);
export const IconCrop = (p: P) => (
  <svg {...base} {...p}><path d="M6 2v16h16" /><path d="M2 6h16v16" /></svg>
);
export const IconLayers = (p: P) => (
  <svg {...base} {...p}><path d="M12 3l9 5-9 5-9-5 9-5z" /><path d="M3 13l9 5 9-5" /></svg>
);
export const IconSparkle = (p: P) => (
  <svg {...base} {...p}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" /></svg>
);
export const IconPlay = (p: P) => (
  <svg {...base} {...p}><path d="M8 5.5l10 6.5-10 6.5v-13z" /></svg>
);
export const IconFace = (p: P) => (
  <svg {...base} {...p}><circle cx="12" cy="12" r="9" /><path d="M9 10h.01M15 10h.01M8.5 14.5c1 1.2 2.2 1.8 3.5 1.8s2.5-.6 3.5-1.8" /></svg>
);
export const IconMore = (p: P) => (
  <svg {...base} {...p}><circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none" /></svg>
);
export const IconChevron = (p: P) => (
  <svg {...base} {...p}><path d="M9 6l6 6-6 6" /></svg>
);
export const IconHistory = (p: P) => (
  <svg {...base} {...p}><path d="M3.5 12a8.5 8.5 0 108.5-8.5A8.4 8.4 0 006 6" /><path d="M3.5 3.5V7H7" /><path d="M12 7.5V12l3 2" /></svg>
);
export const IconEdit = (p: P) => (
  <svg {...base} {...p}><path d="M4 20h4L19 9a2.1 2.1 0 00-3-3L5 17v3z" /></svg>
);
export const IconSwap = (p: P) => (
  <svg {...base} {...p}><path d="M7 4v12m0 0l-3-3m3 3l3-3" /><path d="M17 20V8m0 0l3 3m-3-3l-3 3" /></svg>
);
export const IconLock = (p: P) => (
  <svg {...base} {...p}><rect x="4.5" y="10.5" width="15" height="10" rx="2" /><path d="M8 10.5V7.8a4 4 0 018 0v2.7" /></svg>
);
export const IconScissors = (p: P) => (
  <svg {...base} {...p}><circle cx="6" cy="6" r="2.5" /><circle cx="6" cy="18" r="2.5" /><path d="M8.2 7.6L20 18M8.2 16.4L20 6" /></svg>
);
export const IconCheck = (p: P) => (
  <svg {...base} {...p}><path d="M5 12.5l4.5 4.5L19 7" /></svg>
);
export const IconAlert = (p: P) => (
  <svg {...base} {...p}><path d="M12 4.5l8.5 15h-17l8.5-15z" /><path d="M12 10v4M12 17h.01" /></svg>
);
