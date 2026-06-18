# Internal ops runbooks — NOT published

These runbooks are **internal-only** and deliberately live outside `docs/` so the
site builder (`site/build-docs.py`) never renders them and the public mirror never
carries them. They contain operational references (host / registrar / 1Password
item **names** — not secret values) that must not appear on the public site.

- `DNS.md` — DNS / registrar runbook, relocated from `docs/infra/DNS.md`
  (2026-06-18) after it was found published on the live site. The Chinese
  translation (`docs/zh/infra/DNS.md`, currently an untracked working-tree draft
  owned by the `og` translation lane) should be relocated here as `DNS.zh.md` by
  that lane — coordinated separately.

Do not move these back under `docs/`. `build-docs.py` also excludes any
`docs/**/infra/` path as a safety net.
