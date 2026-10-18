// Public entry point. Everything under ./generated is produced by `pnpm contracts:gen`.
// IpoField and SourceRef appear in both IPO schemas (shared Pydantic $defs); they are
// identical, so they're exported once, from the list module.
export * from './generated/service-health.v1.js';
export * from './generated/ipo-list.v1.js';
export {
  type IpoDetail,
  type FieldObservation,
  IpoDetailSchema,
} from './generated/ipo-detail.v1.js';
export * from './generated/research-report.v1.js';
export * from './generated/research-list.v1.js';
export * from './generated/research-created.v1.js';
export * from './generated/research-event.v1.js';
export * from './generated/research-evidence.v1.js';
