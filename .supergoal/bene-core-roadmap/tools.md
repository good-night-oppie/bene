# Tools detected this session
- Workflow tool (ultracode) — available; use for any fan-out/verify within phases.
- A2A bus (a2a-coord.db SharedLog) — available; adx reaction loop runs here.
- pal MCP (consensus/codereview) — DOWN this session (CLIProxyAPI at stale 172.18.0.4; live at 127.0.0.1:8317). Do not rely on it.
- Context7/WebSearch — Context7 disconnected; not required (planning against read code, not external SDK docs — except langfuse 4.x, verify in L2 phase via installed SDK introspection).
- langfuse — NOT installed in bene env (ModuleNotFoundError); L2 phase must make it an opt-in extra + introspect the real surface.
