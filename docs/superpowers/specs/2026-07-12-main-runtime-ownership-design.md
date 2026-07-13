# Main runtime ownership migration

## Goal

Move News Codex's local PostgreSQL data directory from the preserved
`feature/local-postgresql-runtime` worktree to `main/.local/postgres`, so the
merged application can run without depending on that feature worktree.

## Scope and invariants

- The existing database contents and the source worktree remain intact.
- No secret, database URL, API key, or cookie is written to Git or reports.
- The migration is local-only and has a brief planned database-service outage.
- `main/.env` remains ignored by Git and continues to point to the same local
  database endpoint after the cutover.
- No source fetch, model call, event publication, or schema change is part of
  this migration.

## Chosen approach: copy and take ownership

The current `main` and preserved-worktree configurations point to the same
local PostgreSQL endpoint. The data directory is therefore copied only after
the existing service has stopped cleanly. The source directory is never moved,
renamed, or deleted.

### Steps

1. Preflight: verify `main/.local/postgres` is absent, the preserved data
   directory exists, both configurations target the same host/port/database,
   and the current database is at Alembic head.
2. Record a manifest of the source directory (file count, byte count, and a
   bounded checksum manifest) outside Git.
3. Stop the existing local PostgreSQL service through its owning worktree;
   wait until port 55432 no longer listens.
4. Copy the source data directory to `main/.local/postgres` with metadata and
   hidden files preserved. Verify destination manifest equivalence before any
   startup.
5. Start PostgreSQL from `main`, then run `alembic current`, `alembic check`,
   and read-only table/count checks.
6. Restart the `main` web and Worker runtime, then verify a reader page and a
   bounded Worker operation without using MiniMax.

## Failure handling and rollback

- Any preflight, copy, checksum, startup, or migration failure stops the
  cutover before the original data is altered.
- If the `main` service cannot start or validation fails, stop it, leave its
  copied directory for diagnosis, and restart the preserved service from the
  unchanged original worktree.
- The original worktree, `.env`, `.local/postgres`, reports, and untracked
  review artifacts are explicitly retained.

## Acceptance criteria

- `main/.local/postgres` exists and validates against the source manifest.
- `main` owns the process listening on port 55432.
- Alembic reports `20260712_0008 (head)` and no pending upgrade operations.
- Existing source registry, operation, RawItem, and Event counts match the
  pre-cutover baseline.
- The local web UI and Worker run from `main` without error markers.
