import 'server-only';
import { LocalStorage } from './local';
import { S3Storage } from './s3';
import type { StorageAdapter } from './types';

export type { StorageAdapter, StoredObject } from './types';

let cached: StorageAdapter | null = null;

export function getStorage(): StorageAdapter {
  if (cached) return cached;
  cached = process.env.STORAGE_DRIVER === 's3' ? new S3Storage() : new LocalStorage();
  return cached;
}
