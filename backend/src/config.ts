import { z } from 'zod';

const MIN_SERVICE_TOKEN_LENGTH = 32;

const EnvSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  HOST: z.string().min(1).default('0.0.0.0'),
  PORT: z.coerce.number().int().min(1).max(65535).default(3000),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent']).default('info'),
  DATABASE_URL: z.string().regex(/^postgres(ql)?:\/\//, 'must be a postgres:// URL'),
  AI_SERVICE_URL: z.url({ protocol: /^https?$/ }),
  AI_SERVICE_TOKEN: z
    .string()
    .min(MIN_SERVICE_TOKEN_LENGTH)
    .refine((t) => !t.startsWith('change-me'), 'still the .env.example placeholder'),
  DEPENDENCY_TIMEOUT_MS: z.coerce.number().int().min(100).max(30_000).default(2000),
});

export type Config = z.infer<typeof EnvSchema>;

export class ConfigError extends Error {
  override name = 'ConfigError';
}

/**
 * Parse and validate configuration from environment variables.
 * Error messages name the invalid variables but never echo their values (they may be secrets).
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const result = EnvSchema.safeParse(env);
  if (!result.success) {
    const problems = result.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`);
    throw new ConfigError(`Invalid environment configuration:\n  ${problems.join('\n  ')}`);
  }
  return result.data;
}
