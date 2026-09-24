export interface StoredObject {
  key: string;
  /** Absolute URL the object can be read from. */
  url: string;
  bytes: number;
  contentType: string;
}

export interface StorageAdapter {
  readonly name: string;
  /**
   * Whether FASHN can fetch `url` from the public internet. When false, the
   * generate route sends a data URI instead of a hosted URL.
   */
  readonly isPubliclyReachable: boolean;
  put(key: string, body: Buffer, contentType: string): Promise<StoredObject>;
  get(key: string): Promise<{ body: Buffer; contentType: string } | null>;
  delete(key: string): Promise<void>;
  url(key: string): string;
}
