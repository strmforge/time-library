# Safe Capability Check

Use capability check for install tests and smoke tests.

Do not start with `/zhiyi` if you only want to verify the connection. A normal recall may return real memory and raw excerpts.

Ask the client to call `zhiyi_recall` with:

```json
{"query":"capability check","mode":"capability_check"}
```

A healthy result should show:

```text
service: raw_consumption_gateway
server: time-library
read_only: true
recall_performed: false
raw_excerpt_returned: false
mcp_tools: ["zhiyi_recall"]
```

## What It Proves

Capability check proves that the local service, MCP entry, and read-only workflow are visible to the client.

## What It Does Not Do

It does not:

- recall real memory;
- return source refs;
- return raw excerpts;
- parse chat bodies;
- write another app's config or memory.

## 中文

安装和冒烟测试时，先做 capability check。

不要一开始就用 `/zhiyi`，因为它可能触发真实召回。

使用：

```json
{"query":"capability check","mode":"capability_check"}
```

成功结果应该包含 `read_only: true`、`recall_performed: false`、`raw_excerpt_returned: false`。
