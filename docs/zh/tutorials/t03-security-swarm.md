# 并发安全审查：四狼下山，一条 SQL 收网

*安全篇*

把四只被关在绝对隔离沙盒里的 agent 同时砸向同一个 PR —— 一只查注入、一只翻硬编码密钥、一只看越权、一只盯反序列化 —— 等它们跑完，你只需要甩出一条 SQL，就能拿到一张按严重程度排好序的体检报告单。整场审查，墙上时钟只转了 20 分钟；如果是人肉或者串行排队查，这活得干 80 分钟。

> **每个攻击面专供一台扫描仪，彼此之间绝对不共享上下文，所有的战报最后全汇聚在一张表里。**

*实盘接客 PR-2847：四台扫描仪同时起飞，一条 SQL 捞出所有战果。*

## 放狼出笼

串行审查（比如人肉 review 或者挨个跑脚本）会在这三个地方抽你的税：每次你在脑子里切换威胁模型时，上一个模型里的细节就会掉在地上；当你第四遍硬啃同一段 400 行的代码时，你的注意力绝对比不上第一遍；还有，你揪出来的第一个 bug，会潜移默化地把你拖进一个只找这类 bug 的隧道视野里，而那些八竿子打不着的其他致命漏洞，就会趁机从你眼皮子底下溜走。

把审查拆解成并发，这三笔税一笔勾销。一条命令拉起四台扫描仪，每一台都被剥夺了其他的杂念，脑子里只装着自己专属的那个威胁模型：

```bash
bene parallel \
  "spawn sqli-scanner    --from ./pr-2847 --task sqli_audit" \
  "spawn secrets-scanner --from ./pr-2847 --task secrets_audit" \
  "spawn auth-scanner    --from ./pr-2847 --task auth_audit" \
  "spawn deser-scanner   --from ./pr-2847 --task deser_audit"

# [sqli-scanner]    成功投放战场  vfs_id=sqli-4a1b  status=running
# [secrets-scanner] 成功投放战场  vfs_id=sec-9c2d   status=running
# [auth-scanner]    成功投放战场  vfs_id=auth-3e4f   status=running
# [deser-scanner]   成功投放战场  vfs_id=desr-7g8h   status=running
#
# 4 匹战狼正在并发厮杀
```

每一台扫描仪都会分到一个私有的虚拟文件系统 (bene 的单 agent 专属 VFS)，里面装着这个 PR 的全量拷贝。没有任何一只 agent 能偷看隔壁兄弟写了什么 —— 这种 "绝对防锚定 (no-anchoring)" 的隔离特性，是由数据库底层直接上锁的，而不是靠什么代码规范或者 prompt 去软约束。

## 盯梢战局

这帮 agent 按着各自的节奏陆续收工 —— 查注入的 4 分钟搞定，查密钥的 6 分钟，查越权的啃了 18 分钟 —— 每一只在完工时都会把自己的斩获如实上报：

```json
[
  {"name": "sqli-scanner",    "status": "complete", "findings_count": 1},
  {"name": "secrets-scanner", "status": "complete", "findings_count": 2},
  {"name": "auth-scanner",    "status": "complete", "findings_count": 0},
  {"name": "deser-scanner",   "status": "complete", "findings_count": 0}
]
```

## 一条 SQL，一把全捞

虽然查出来的漏洞都各自躺在它们自己的 VFS 账本里，但这些账本全在同一个大数据库里 —— 所以，一发 `SELECT`，带上按严重度排序的 `ORDER BY`，整个 PR 的安全审查报告就全部拼好了：

```sql
SELECT agent_name, severity, finding_type, file_path, line_no, summary
FROM vfs_findings
WHERE pr = 'PR-2847'
ORDER BY
  CASE severity
    WHEN 'CRITICAL' THEN 1
    WHEN 'HIGH'     THEN 2
    WHEN 'MEDIUM'   THEN 3
    ELSE 4
  END
```

```text
Agent            Severity  Type              File                Line  Summary
---------------  --------  ----------------  ------------------  ----  ----------------------------------------
sqli-scanner     CRITICAL  sql_injection     api/search.py       14    f-string 直接往 SQL 里裸拼参数
secrets-scanner  CRITICAL  hardcoded_secret  config/settings.py  47    生产环境 API Key 被硬编码写死了
secrets-scanner  MEDIUM    ssrf              api/webhooks.py     83    用户传进来的 URL 没洗过就直接丢给 requests.get()
auth-scanner     CLEAN     —                 —                   —     未发现越权或登录绕过漏洞
deser-scanner    CLEAN     —                 —                   —     未发现危险的反序列化点
```

2 个 CRITICAL (致命), 1 个 MEDIUM (中危), 还有 2 个面被盖了安全戳 —— 整个拼装过程，你连一个 agent 的工作区都不需要亲自点开。

## 扒开看看它们到底逮住了啥

**SQL 注入 — CRITICAL (致命)，耗时 4 分钟。** 在犁过了 `api/users.py`、`api/search.py` 以及一堆数据库中间件后，注入扫描仪精准咬住了一发用 f-string 狂拼出来的裸奔 SQL：

```python
# api/search.py — 抓包现场: 靠 f-string 搞的 SQL 注入漏洞

@app.route('/search')
def search_users():
    query = request.args.get('q', '')
    # 致命死穴：直接把字符串裸拼进 SQL 语句里
    sql = f"SELECT * FROM users WHERE name LIKE '%{query}%'"
    results = db.execute(sql)
    return jsonify(results)
```

它顺手甩出来的补丁，老老实实地把值做成了参数化绑定：

```python
@app.route('/search')
def search_users():
    query = request.args.get('q', '')
    sql = "SELECT * FROM users WHERE name LIKE ?"
    results = db.execute(sql, (f'%{query}%',))
    return jsonify(results)
```

注意，这只 agent 永远不可能知道隔壁的配置文件里其实还漏了一把 API Key。从第一个文件翻到最后一个文件，它的脑子里只有 "SQL 注入" 这四个大字，因为除了这个，其他所有的杂音对它而言根本不存在。

**密钥裸奔 + SSRF — 一发 CRITICAL，一发 MEDIUM，耗时 6 分钟。** 密钥扫描仪从 `config/settings.py` 里扒出了一把硬编码的生产环境 API Key —— 这是实打实的 CRITICAL 致命雷，并且只要合进去，就会永远阴魂不散地死在 git 历史里。紧接着，它又在 `api/webhooks.py` 里揪出了一个由用户传入的、未经任何清洗就直接喂给 `requests.get()` 的野 URL (判为 MEDIUM 中危级别的 SSRF 漏洞)。

**两张 "没毛病" 的安全戳。** 越权扫描仪把整个会话管理模块、JWT 鉴权逻辑以及所有的认证中间件翻了个底朝天，啃了 18 分钟后空手而归。反序列化扫描仪顺着每一个 `pickle.loads()`、`yaml.load()` 和 `eval()` 的调用栈往上爬，同样一无所获。

## 实锤查账：拿数据证明它们确实没互相偷看

前面吹过的 "绝对防锚定" 可不是句空头口号，这是经得起查账的。系统的审计流水记录了每一次读取操作；我们直接敲 SQL 问问它，到底有没有发生过跨 agent 的偷吃行为：

```sql
SELECT a.name, COUNT(e.id) as shared_events
FROM agents a
LEFT JOIN vfs_events e ON e.agent_id = a.id
  AND e.event_type = 'cross_agent_read'
WHERE a.name IN ('sqli-scanner','secrets-scanner','auth-scanner','deser-scanner')
GROUP BY a.name

-- 验算结果: 4 只 agent 的 cross_agent_read (跨界读取) 次数全部为 0
```

全是 0，无可辩驳。正是这个 0，把 "防锚定" 从一句虚无缥缈的愿景，变成了一道硬核的物理屏障：如果刚才那只负责搜密钥的 agent 偷看到了隔壁查出的 SQL 注入漏洞，它的注意力极有可能会被带偏，转而也去搜代码里有没有拼错的字符串，从而直接放过它本来应该死死咬住的那把 API Key。

## 算总账：你到底赚了啥

```text
姿势                       耗时               隧道视野锚定风险
-------------------------  -----------------  --------------
串行排队 (1 个人肉看全场)  80 分钟            极高
串行排队 (4 个人肉分别看)  20 分钟(挂钟时间)  中等
BENE 并发狼群扑咬          20 分钟(挂钟时间)  绝对为 0
```

无论你怎么审，这 3 个雷最终可能都会被扫出来。但是，把审查并发化，让你在墙上的挂钟时间里白赚了 4 倍的提速；而纯粹的物理隔离，让你在 "锚定风险" 那一栏里，因为系统底层的硬刚而拿到了一个极其笃定的 "0"，而不是靠着人类的意志力去死撑。

再回头看看这几个雷的分布：注入漏洞和泄露密钥，在脑图里完全属于两个八竿子打不着的神经元板块 —— 这恰恰是那个单枪匹马串行审查的倒霉蛋，在脑子切换时最容易掉链子的死穴。而那个 SSRF，更是只要你脑子里还装着上一个复杂逻辑，就极其容易被你直接划过去的隐蔽角落。现在，所有的三颗雷都在 20 分钟内被生刨了出来，而且还有那份审计流水为你作证：它们查出来的战果，绝对没有互相污染。

## 顺藤摸瓜

- [README 首页](../README.md) — BENE 全景大局观和全套文档入口
- [破局战法 (Use Cases)](../use-cases.md) — 更多来自一线火线上的实战套路
- [破局战法：并发安全审查蜂群](../use-cases.md#security-audit-swarm)
- [核心部件指南：跨代记忆库 (Memory)](../memory.md)
- [架构设计：Agent 物理隔离屏障](../architecture.md)

---

*bene 基于 MIT 协议开源，并且是一个纯粹的 Local-first 原教旨主义者：这场惊心动魄的安全审查全都在一台机器上跑完，而且所有的尸体积件 —— agent 状态、审计流水、战果清单 —— 统统被塞在了一个你可以随手拷贝走的 SQLite 文件里。*

*源码老家 GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
