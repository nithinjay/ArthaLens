import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { describe, expect, it } from 'vitest';
import { evaluate, loadPolicy, normalizeName, type ExclusionPolicy } from '../src/exclusion.js';

interface Vector {
  name: string;
  decision: string;
  reason: string | null;
}

const vectors = JSON.parse(
  readFileSync(new URL('../exclusion-vectors.v1.json', import.meta.url), 'utf8'),
) as { policy_version: number; vectors: Vector[] };

const policy = loadPolicy();

describe('shared exclusion vectors (must match ai/tests/test_exclusion.py)', () => {
  it('targets the current policy version', () => {
    expect(vectors.policy_version).toBe(policy.version);
  });

  it.each(vectors.vectors.map((v) => [JSON.stringify(v.name), v] as const))(
    '%s',
    (_label, vector) => {
      const result = evaluate(policy, { name: vector.name });
      expect({ decision: result.decision, reason: result.reason }).toEqual({
        decision: vector.decision,
        reason: vector.reason,
      });
    },
  );
});

describe('evaluate', () => {
  const withIds: ExclusionPolicy = {
    ...policy,
    rules: policy.rules.map((r) => ({
      ...r,
      match: { ...r.match, identifiers: { ...r.match.identifiers, isin: ['INE000TEST01'] } },
    })),
  };

  it('excludes by identifier even when the name looks harmless', () => {
    const r = evaluate(withIds, {
      name: 'Harmless Name Ltd',
      identifiers: { isin: ['ine000test01 '] },
    });
    expect(r).toMatchObject({
      decision: 'excluded',
      reason: 'identifier',
      rule_id: 'EXCL-JIO-001',
    });
  });

  it('carries a user-safe message on every block', () => {
    const r = evaluate(policy, { name: 'Jio Platforms' });
    expect(r.user_message).toMatch(/excluded from ArthaLens/);
    expect(evaluate(policy, { name: 'Synthetic Alpha Foods' }).user_message).toBeNull();
  });

  it('honours an explicit allow entry for a false positive', () => {
    const allowing: ExclusionPolicy = {
      ...policy,
      allow: [
        { normalized_name: 'rajio technologies', rule_id: 'EXCL-JIO-001', justification: 'test' },
      ],
    };
    expect(evaluate(allowing, { name: 'Rajio Technologies' }).decision).toBe('allowed');
    // An allow entry for one name never unblocks a different one.
    expect(evaluate(allowing, { name: 'Jio Platforms' }).decision).toBe('excluded');
  });

  it('does not apply ipo-only rules to other scopes', () => {
    expect(evaluate(policy, { name: 'Jio Financial Services' }, 'stock').decision).toBe('allowed');
  });
});

describe('normalizeName', () => {
  it('folds width, case, invisible characters and punctuation', () => {
    expect(normalizeName('  \uff2a\uff49\uff4f\u200b-Platforms, LTD. ')).toBe('jio platforms ltd');
  });
});

describe('loadPolicy', () => {
  it('fails closed on a malformed policy', () => {
    const file = join(mkdtempSync(join(tmpdir(), 'policy-')), 'bad.json');
    writeFileSync(file, '{"version":1,"rules":[]}');
    expect(() => loadPolicy(pathToFileURL(file))).toThrow(/missing or malformed/);
  });
});
