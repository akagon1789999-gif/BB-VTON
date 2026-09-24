import 'server-only';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { StorageAdapter, StoredObject } from './types';

/**
 * Dev driver. Writes under ./.data/uploads and serves the bytes back through
 * /api/files/* so it works identically in `next dev` and `next start`
 * (files added to /public after a build are not served).
 */
export class LocalStorage implements StorageAdapter {
  readonly name = 'local';
  private readonly root: string;
  private readonly origin: string;

  constructor() {
    this.root = path.join(process.cwd(), '.data', 'uploads');
    this.origin = (process.env.APP_URL || 'http://localhost:3000').replace(/\/$/, '');
  }

  /**
   * Only true when APP_URL is a public https origin -- i.e. a tunnel or a real
   * deployment. On plain localhost FASHN cannot reach us, so callers fall back
   * to data URIs.
   */
  get isPubliclyReachable(): boolean {
    return (
      this.origin.startsWith('https://') &&
      !/localhost|127\.0\.0\.1|0\.0\.0\.0|\.local(?::|$)/.test(this.origin)
    );
  }

  private pathFor(key: string): string {
    // Keys are generated internally, but never trust one that reaches disk.
    const safe = key.replace(/[^a-zA-Z0-9._/-]/g, '_').replace(/\.\./g, '_');
    return path.join(this.root, safe);
  }

  async put(key: string, body: Buffer, contentType: string): Promise<StoredObject> {
    const file = this.pathFor(key);
    await fs.mkdir(path.dirname(file), { recursive: true });
    await fs.writeFile(file, body);
    await fs.writeFile(`${file}.type`, contentType, 'utf8');
    return { key, url: this.url(key), bytes: body.byteLength, contentType };
  }

  async get(key: string): Promise<{ body: Buffer; contentType: string } | null> {
    const file = this.pathFor(key);
    try {
      const body = await fs.readFile(file);
      let contentType = 'application/octet-stream';
      try {
        contentType = (await fs.readFile(`${file}.type`, 'utf8')).trim();
      } catch {
        /* fall through to the default */
      }
      return { body, contentType };
    } catch {
      return null;
    }
  }

  async delete(key: string): Promise<void> {
    const file = this.pathFor(key);
    await fs.rm(file, { force: true });
    await fs.rm(`${file}.type`, { force: true });
  }

  url(key: string): string {
    return `${this.origin}/api/files/${key}`;
  }
}
