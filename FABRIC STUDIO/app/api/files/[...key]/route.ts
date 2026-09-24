import { NextResponse } from 'next/server';
import { getStorage } from '@/lib/storage';

export const runtime = 'nodejs';

/** Serves objects back out of whichever storage driver is configured. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ key: string[] }> },
): Promise<NextResponse> {
  const { key } = await params;
  const object = await getStorage().get(key.join('/'));

  if (!object) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  return new NextResponse(new Uint8Array(object.body), {
    headers: {
      'Content-Type': object.contentType,
      'Content-Length': String(object.body.byteLength),
      'Cache-Control': 'private, max-age=31536000, immutable',
    },
  });
}
