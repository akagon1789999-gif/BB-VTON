import { NextResponse } from 'next/server';
import { toStudioError } from '@/lib/errors';
import { fashn } from '@/lib/fashn';
import type { CreditsResponse } from '@/lib/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(): Promise<NextResponse> {
  try {
    const balance = await fashn.credits();
    const payload: CreditsResponse = balance;
    return NextResponse.json(payload);
  } catch (err) {
    const studio = toStudioError(err);
    return NextResponse.json(studio.toPayload(), { status: studio.httpStatus });
  }
}
