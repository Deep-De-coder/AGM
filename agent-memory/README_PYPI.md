# AGM -- Agent Memory Management

**`agm-memory-mcp`** -- Provenance-tagged memory infrastructure
for multi-agent AI systems, available as an MCP server.

Solves two problems current agent memory systems ignore:

1. **Agent identity and trust** -- knowing which agent wrote
   what and whether it can be trusted
2. **Memory poisoning** -- detecting and containing malicious
   or corrupted memories before they propagate through
   agent reasoning

> Existing systems (MemGPT, Mem0, HippoRAG) have no memory
> states, no trust provenance, and no causal ordering.
> AGM is infrastructure for pipelines that need those properties.

---

## Install

```bash
pip install agm-memory-mcp
```

Python import name:

```python
import agent_memory_mcp
```

CLI command:

```bash
agm-memory-mcp --help
```

---

## Requirements

- Python 3.11+
- A running AgentMemory HTTP API endpoint

This package is the MCP bridge. It does not embed the full backend.

---

## Configuration

Set either CLI args or environment variables.

Environment variables:

- `AGENT_MEMORY_API_URL` (default: `http://localhost:8000`)
- `AGENT_MEMORY_API_PREFIX` (default: empty string)

Examples:

```bash
# Linux/macOS
export AGENT_MEMORY_API_URL=https://your-api.example.com
export AGENT_MEMORY_API_PREFIX=/api/v1
agm-memory-mcp
```

```powershell
# Windows PowerShell
$env:AGENT_MEMORY_API_URL="https://your-api.example.com"
$env:AGENT_MEMORY_API_PREFIX="/api/v1"
agm-memory-mcp
```

Or pass options directly:

```bash
agm-memory-mcp --api-url https://your-api.example.com --api-prefix /api/v1
```

---

## Health Check

Validate connectivity before starting MCP transport:

```bash
agm-memory-mcp --check
```

Shows resolved URL and API status. Exits `0` on success, `1` on failure.

---

## Run as Module

```bash
python -m agent_memory_mcp
```

Equivalent to running `agm-memory-mcp`.

---

## MCP Client Config Example (Claude Desktop / compatible)

```json
{
  "mcpServers": {
    "agm-memory": {
      "command": "agm-memory-mcp",
      "args": [
        "--api-url",
        "https://your-api.example.com"
      ]
    }
  }
}
```

You can also use env vars instead of args.

---

## Included MCP Tools (14)

1. `write_memory`
2. `read_memory`
3. `query_memories`
4. `get_safe_memories`
5. `get_trust_score`
6. `get_provenance`
7. `flag_memory`
8. `register_agent`
9. `check_violations`
10. `acknowledge_violation`
11. `get_notifications`
12. `run_rules_check`
13. `consolidate_memories`
14. `get_rules_reference`

---

## Rule Model

AGM includes 13 embedded detection rules (`RULE_001` through `RULE_013`) for:

- write flooding
- trust-chain contamination
- contradiction detection
- rapid rewrite anomalies
- high-stakes unverified content
- inter-agent session violations
- expired safety context
- anonymous agent writes
- bulk near-duplicate content
- trust cliff detection
- behavioral drift
- causal orphan detection
- anergy bypass attempts

Use `get_rules_reference` to inspect rule metadata at runtime.

---

## License

MIT
