import { describe, expect, it } from 'vitest';
import { ConfigError, loadConfig } from '../src/config.js';

const valid = {
  DATABASE_URL: 'postgresql://app_api:pw-not-real@localhost:5432/arthalens',
  AI_SERVICE_URL: 'http://ai:8000',
  AI_SERVICE_TOKEN: 'x'.repeat(40),
};

describe('loadConfig', () => {
  it('applies defaults to a minimal valid environment', () => {
    const config = loadConfig(valid);
    expect(config).toMatchObject({
      PORT: 3000,
      NODE_ENV: 'development',
      DEPENDENCY_TIMEOUT_MS: 2000,
    });
  });

  it.each([
    ['missing token', { ...valid, AI_SERVICE_TOKEN: undefined }],
    ['short token', { ...valid, AI_SERVICE_TOKEN: 'short' }],
    [
      'placeholder token',
      { ...valid, AI_SERVICE_TOKEN: 'change-me-to-a-random-value-of-at-least-32-chars' },
    ],
    ['non-postgres DATABASE_URL', { ...valid, DATABASE_URL: 'mysql://x' }],
    ['non-http AI_SERVICE_URL', { ...valid, AI_SERVICE_URL: 'file:///etc/passwd' }],
    ['bad port', { ...valid, PORT: '70000' }],
  ])('rejects %s', (_label, env) => {
    expect(() => loadConfig(env)).toThrow(ConfigError);
  });

  it('names invalid variables without echoing their values', () => {
    const secret = 'super-secret-but-too-short';
    try {
      loadConfig({ ...valid, AI_SERVICE_TOKEN: secret });
      expect.unreachable();
    } catch (err) {
      expect((err as Error).message).toContain('AI_SERVICE_TOKEN');
      expect((err as Error).message).not.toContain(secret);
    }
  });
});
