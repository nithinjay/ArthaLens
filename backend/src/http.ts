/** Shared HTTP building blocks for routes: one definition each, so they can't drift apart. */

export const UUID_PATTERN = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
const UUID_RE = new RegExp(UUID_PATTERN);

/** RFC 9457 problem details, for response schemas. */
export const PROBLEM_SCHEMA = {
  type: 'object',
  properties: {
    type: { type: 'string' },
    title: { type: 'string' },
    status: { type: 'integer' },
    detail: { type: 'string' },
    instance: { type: 'string' },
    request_id: { type: 'string' },
    code: { type: 'string' },
  },
} as const;

/** Query-string schema for an opaque keyset cursor. */
export const CURSOR_SCHEMA = {
  type: 'string',
  maxLength: 500,
  pattern: '^[A-Za-z0-9_-]+$',
} as const;

/**
 * Keyset cursors are base64url(JSON [sortKey, id]). The sort key is passed through exactly as
 * the database produced it (e.g. a timestamptz as text with microseconds), never re-formatted,
 * so no row is skipped by rounding.
 */
export function encodeCursor(sortKey: string, id: string): string {
  return Buffer.from(JSON.stringify([sortKey, id])).toString('base64url');
}

export function decodeCursor(
  cursor: string,
  isValidKey: (key: string) => boolean,
): { key: string; id: string } | null {
  try {
    const value: unknown = JSON.parse(Buffer.from(cursor, 'base64url').toString('utf8'));
    if (
      Array.isArray(value) &&
      value.length === 2 &&
      typeof value[0] === 'string' &&
      typeof value[1] === 'string' &&
      isValidKey(value[0]) &&
      UUID_RE.test(value[1])
    ) {
      return { key: value[0], id: value[1] };
    }
  } catch {
    // fall through
  }
  return null;
}

/** A Postgres timestamptz rendered as text, e.g. "2026-10-18 06:00:00.123456+00". */
export const isPgTimestamp = (s: string) =>
  /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d{1,6})?([+-]\d{2}(:\d{2})?|Z)$/.test(s);
