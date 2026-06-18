# agentdex.builders — DNS / 重定向记录

**域名注册商：** Namecheap（账号 `tangeddie8226`）。API 凭证存放在 1Password `openclaw` 金库 → 条目 `namecheap-api`（需要配置 ClientIp 白名单；本机 IP 为 `54.202.180.208`）。

**当前配置（于 2026-06-11 通过 `namecheap.domains.dns.setHosts` 设置，IsSuccess=true）：**

| 主机 | 类型 | 地址 | TTL |
|---|---|---|---|
| `@`   | URL301 | `https://www.superlinear.academy/ai-builders` | 1800 |
| `www` | URL301 | `https://www.superlinear.academy/ai-builders` | 1800 |

`agentdex.builders` 作为一个品牌入口，会将流量通过 301 永久重定向到 AI-Builders space 平台（Superlinear Academy）。BENE 的落地页和文档会以 SPACE 的形式发布在该平台上（`spaces.ai-builders.com` 的 API 密钥存放在金库条目 `spaces.ai-builders.com-api-key` 中）。

**回滚（恢复停放页）：** 重新执行 `setHosts` 并传入
`@` Type=URL Address=`http://www.agentdex.builders/`，`www` Type=CNAME Address=`parkingpage.namecheap.com.`
（先前的 HostId 为 513165973 / 513165974）。

**重新应用 / 变更目标：** `setHosts` 是**全量替换** —— 务必在一次调用中传入所有主机记录。
