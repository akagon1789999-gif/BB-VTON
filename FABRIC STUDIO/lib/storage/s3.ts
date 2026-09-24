import 'server-only';
import {
  DeleteObjectCommand,
  GetObjectCommand,
  PutObjectCommand,
  S3Client,
} from '@aws-sdk/client-s3';
import { StudioError } from '../errors';
import type { StorageAdapter, StoredObject } from './types';

/** Production driver. Works against AWS S3, Cloudflare R2, Backblaze B2 or MinIO. */
export class S3Storage implements StorageAdapter {
  readonly name = 's3';
  readonly isPubliclyReachable = true;

  private readonly client: S3Client;
  private readonly bucket: string;
  private readonly publicBase: string;

  constructor() {
    const bucket = process.env.S3_BUCKET;
    if (!bucket) {
      throw new StudioError({
        code: 'StorageError',
        message: 'STORAGE_DRIVER is s3 but S3_BUCKET is not set.',
        fix: 'Set S3_BUCKET, S3_REGION and credentials, or switch STORAGE_DRIVER to local.',
        httpStatus: 500,
      });
    }

    this.bucket = bucket;
    this.publicBase = (
      process.env.S3_PUBLIC_BASE_URL ||
      `https://${bucket}.s3.${process.env.S3_REGION || 'us-east-1'}.amazonaws.com`
    ).replace(/\/$/, '');

    this.client = new S3Client({
      region: process.env.S3_REGION || 'us-east-1',
      endpoint: process.env.S3_ENDPOINT || undefined,
      forcePathStyle: process.env.S3_FORCE_PATH_STYLE === 'true',
      credentials:
        process.env.S3_ACCESS_KEY_ID && process.env.S3_SECRET_ACCESS_KEY
          ? {
              accessKeyId: process.env.S3_ACCESS_KEY_ID,
              secretAccessKey: process.env.S3_SECRET_ACCESS_KEY,
            }
          : undefined,
    });
  }

  async put(key: string, body: Buffer, contentType: string): Promise<StoredObject> {
    await this.client.send(
      new PutObjectCommand({
        Bucket: this.bucket,
        Key: key,
        Body: body,
        ContentType: contentType,
        CacheControl: 'public, max-age=31536000, immutable',
      }),
    );
    return { key, url: this.url(key), bytes: body.byteLength, contentType };
  }

  async get(key: string): Promise<{ body: Buffer; contentType: string } | null> {
    try {
      const res = await this.client.send(
        new GetObjectCommand({ Bucket: this.bucket, Key: key }),
      );
      const bytes = await res.Body?.transformToByteArray();
      if (!bytes) return null;
      return {
        body: Buffer.from(bytes),
        contentType: res.ContentType || 'application/octet-stream',
      };
    } catch {
      return null;
    }
  }

  async delete(key: string): Promise<void> {
    await this.client.send(new DeleteObjectCommand({ Bucket: this.bucket, Key: key }));
  }

  url(key: string): string {
    return `${this.publicBase}/${key}`;
  }
}
