/**
 * Original File objects, kept out of the persisted store. The crop tool is
 * non-destructive: we re-upload from the original every time the rect changes,
 * so the user can widen a crop they already tightened.
 */
const cache = new Map<string, File>();

export function rememberFile(slot: string, file: File): void {
  cache.set(slot, file);
}

export function recallFile(slot: string): File | undefined {
  return cache.get(slot);
}

export function forgetFile(slot: string): void {
  cache.delete(slot);
}
