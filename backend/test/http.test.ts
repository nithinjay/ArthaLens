import { describe, expect, it } from 'vitest';
import { decodeCursor, encodeCursor, isPgTimestamp } from '../src/http.js';

const ID = '00000000-0000-4000-8000-00000000000a';

describe('keyset cursors', () => {
  it('keep the database sort key exactly, microseconds included (review #6)', () => {
    const key = '2026-10-18 06:00:00.123456+00';
    expect(decodeCursor(encodeCursor(key, ID), isPgTimestamp)).toEqual({ key, id: ID });
  });

  it.each(['2026-10-18 06:00:00+00', '2026-10-18 06:00:00.1+05:30', '2026-10-18T06:00:00.123456Z'])(
    'accept Postgres timestamp text %s',
    (ts) => {
      expect(isPgTimestamp(ts)).toBe(true);
    },
  );

  it.each(['2026-10-18', 'yesterday', "2026-10-18 06:00:00'; DROP TABLE x;--", ''])(
    'reject %j as a timestamp',
    (ts) => {
      expect(isPgTimestamp(ts)).toBe(false);
    },
  );
});
