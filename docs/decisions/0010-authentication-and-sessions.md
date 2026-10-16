# ADR-0010: Server-side sessions behind an IdentityProvider port

**Status:** Proposed · **Date:** 2026-10-17

## Context
Phase 1 needs authentication. Phase 3/Stage 1 needs OAuth 2.0/OIDC, SAML, SCIM, and tenant-specific IdP config. The brief forbids presenting a simulated bridge as production SSO.

## Decision
- **Sessions:** opaque session ID in an httpOnly, Secure, SameSite=Lax cookie. Session records live in Postgres (user, tenant, roles, expiry, rotation). No JWTs in the browser, which allows server-side revocation.
- **`IdentityProvider` port** in the API:
  - `LocalDevIdentityProvider` (M8): email + password hashed with **argon2id**, clearly labelled *development/local accounts*.
  - `OidcIdentityProvider` (Stage 1 / M12): authorization code + PKCE via a certified OIDC client library, tested against a local Keycloak container. SAML and SCIM come later through the same port.
- **Until M8**, development uses a seeded dev user with an explicit `AUTH_MODE=dev` flag. The app refuses to start with this flag when `NODE_ENV=production`.
- **AuthZ:** RBAC (roles → permissions) checked by a Fastify plugin, combined with tenant scoping ([ADR-0011](0011-tenancy-and-rls.md)).

## Consequences
- + Revocable sessions, simple CSRF story, a clean path to SSO.
- − Session table lookups per request; cache in-process with short TTL if needed.
