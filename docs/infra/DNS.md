# agentdex.builders — DNS / redirection record

**Registrar:** Namecheap (account `tangeddie8226`). API creds in 1Password `openclaw` vault → item `namecheap-api` (ClientIp allowlist required; this host `54.202.180.208`).

**Current config (set 2026-06-11 via `namecheap.domains.dns.setHosts`, IsSuccess=true):**

| Host | Type | Address | TTL |
|---|---|---|---|
| `@`   | URL301 | `https://www.superlinear.academy/ai-builders` | 1800 |
| `www` | URL301 | `https://www.superlinear.academy/ai-builders` | 1800 |

agentdex.builders is a brand entry that 301-forwards to the AI-Builders space platform (Superlinear Academy). The bene landing + docs are published AS A SPACE on that platform (`spaces.ai-builders.com` API key in vault item `spaces.ai-builders.com-api-key`).

**Rollback (restore parking page):** re-run setHosts with
`@` Type=URL Address=`http://www.agentdex.builders/`, `www` Type=CNAME Address=`parkingpage.namecheap.com.`
(prior HostIds 513165973 / 513165974).

**Re-apply / change target:** `setHosts` is FULL-REPLACE — always pass every host record in one call.
