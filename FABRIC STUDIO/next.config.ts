import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Sharp is a native module -- keep it out of the bundle.
  serverExternalPackages: ['sharp'],
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: '**.fashn.ai' },
      { protocol: 'https', hostname: 'cdn.fashn.ai' },
    ],
  },
};

export default nextConfig;
