import { NextResponse } from 'next/server';
import { toStudioError } from '@/lib/errors';
import { fashn } from '@/lib/fashn';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Proxies GET /v1/status/{id} and normalises the error shape. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const { id } = await params;

  try {
    const result = await fashn.status(id);
    return NextResponse.json(result);
  } catch (err) {
    const studio = toStudioError(err);
    return NextResponse.json({ ...studio.toPayload(), predictionId: id }, {
      status: studio.httpStatus,
    });
  }
}
