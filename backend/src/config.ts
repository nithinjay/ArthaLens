import { z } from 'zod';

const MIN_SERVICE_TOKEN_LENGTH = 32;

const EnvSchema = z
  .object({
    NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
    HOST: z.string().min(1).default('0.0.0.0'),
    PORT: z.coerce.number().int().min(1).max(65535).default(3000),
    LOG_LEVEL: z
      .enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent'])
      .default('info'),
    DATABASE_URL: z.string().regex(/^postgres(ql)?:\/\//, 'must be a postgres:// URL'),
    AI_SERVICE_URL: z.url({ protocol: /^https?$/ }),
    AI_SERVICE_TOKEN: z
      .string()
      .min(MIN_SERVICE_TOKEN_LENGTH)
      .refine((t) => !t.startsWith('change-me'), 'still the .env.example placeholder'),
    DEPENDENCY_TIMEOUT_MS: z.coerce.number().int().min(100).max(30_000).default(2000),
    // Until real sign-in arrives (Milestone 8), research endpoints run as one seeded dev user.
    // 'none' means those endpoints answer 401.
    AUTH_MODE: z.enum(['none', 'dev']).default('none'),
    DEV_TENANT_ID: z.uuid().optional(),
    DEV_USER_ID: z.uuid().optional(),
  })
  .superRefine((env, ctx) => {
    if (env.AUTH_MODE !== 'dev') return;
    if (env.NODE_ENV === 'production') {
      ctx.addIssue({
        code: 'custom',
        path: ['AUTH_MODE'],
        message: 'dev identity is not allowed in production',
      });
    }
    if (!env.DEV_TENANT_ID || !env.DEV_USER_ID) {
      ctx.addIssue({
        code: 'custom',
        path: ['AUTH_MODE'],
        message: 'dev identity needs DEV_TENANT_ID and DEV_USER_ID',
      });
    }
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
