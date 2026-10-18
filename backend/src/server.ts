import { AiClient } from './aiClient.js';
import { buildApp } from './app.js';
import { ConfigError, loadConfig } from './config.js';
import { checkDatabase, createPool } from './db.js';

async function main(): Promise<void> {
  const config = loadConfig();
  const pool = createPool(config.DATABASE_URL, config.DEPENDENCY_TIMEOUT_MS);
  const ai = new AiClient({
    baseUrl: config.AI_SERVICE_URL,
    serviceToken: config.AI_SERVICE_TOKEN,
    timeoutMs: config.DEPENDENCY_TIMEOUT_MS,
  });

  const app = await buildApp(config, {
    health: {
      checkDatabase: () => checkDatabase(pool),
      checkAi: (requestId) => ai.checkHealth(requestId),
    },
  });

  const shutdown = async (signal: string): Promise<void> => {
    app.log.info({ signal }, 'shutting down');
    await app.close();
    await pool.end();
    process.exit(0);
  };
  process.once('SIGTERM', () => void shutdown('SIGTERM'));
  process.once('SIGINT', () => void shutdown('SIGINT'));

  await app.listen({ host: config.HOST, port: config.PORT });
}

main().catch((err: unknown) => {
  // Config errors are already safe to print (no values); anything else gets a generic line.
  console.error(err instanceof ConfigError ? err.message : err);
  process.exit(1);
});
