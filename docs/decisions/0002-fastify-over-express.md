# ADR-0002: Fastify for the application API

**Status:** Proposed · **Date:** 2026-10-17

## Context
The brief asks for Express or Fastify with Zod validation, OpenAPI, centralised errors, auth, and rate limiting.

## Decision
Use **Fastify**.

## Why
- **Schema-first routes.** Each route declares request/response schemas. With a Zod type provider, the same Zod schema validates input, serialises output (so internal fields can't leak by accident), types the handler, *and* generates OpenAPI through `@fastify/swagger`. Express needs several loosely coupled libraries for this.
- **Encapsulated plugins.** Auth, tenant context, rate limiting and idempotency are plugins with explicit scope. This makes "every route under `/api/v1` is authenticated" structurally true rather than a convention.
- **Built-in structured logging** (pino) with request IDs and redaction paths. This matters for "never log secrets".
- **Async error handling** is native, which gives one central error handler emitting RFC 9457 problem+json.
- Performance is better, though secondary here.

## Consequences
- − Smaller middleware ecosystem than Express, and some Express middleware needs Fastify equivalents (`@fastify/cookie`, `@fastify/rate-limit`, `@fastify/helmet`, `@fastify/csrf-protection`).
- − Learning curve around the plugin encapsulation model. We'll explain it in Milestone 1.

## Alternatives
- **Express 5:** ubiquitous and simple, but validation, serialisation and OpenAPI are bolt-ons, and response filtering is manual.
- **NestJS:** heavy abstraction for a learning project. It hides the mechanics the brief wants taught.
