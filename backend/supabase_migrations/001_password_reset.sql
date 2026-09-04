-- Run this once in the Supabase project's SQL editor before deploying the
-- forgot-password feature. Creates the two tables app_config_repository.py
-- reads/writes: the single-row dashboard password hash, and single-use
-- password-reset tokens.

create table if not exists app_config (
    id integer primary key,
    password_hash text not null,
    updated_at timestamptz not null default now()
);

create table if not exists password_reset_tokens (
    id bigint generated always as identity primary key,
    token_hash text not null,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    used_at timestamptz
);

create index if not exists password_reset_tokens_token_hash_idx
    on password_reset_tokens (token_hash);

create index if not exists password_reset_tokens_active_idx
    on password_reset_tokens (expires_at)
    where used_at is null;
