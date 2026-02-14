---
name: cognee-memory
description: >
  Activate this skill when the user needs to query or search code context,
  understand codebase relationships, or retrieve specific information from
  a previously indexed knowledge graph. Use this skill for semantic code search,
  dependency analysis, or when starting a new thread that requires context
  from previous work without full re-indexing. This skill provides access to
  Cognee's graph-based memory system through MCP.
---

# Cognee Memory Skill

## When to Use

- Starting a new thread but need context from previous work
- Searching for code relationships, dependencies, or imports
- Understanding architecture without re-reading entire codebase
- Querying semantic meaning across the project
- Avoiding context window limits by querying external memory

## Quick Reference

| Tool | Purpose | Example |
|------|---------|---------|
| `/mcpo` | Index codebase into knowledge graph | `cognify --path ./src` |
| `search` | Query the knowledge graph | `search "authentication flow"` |
| `prune` | Remove old/stale memory | `prune --older-than 7d` |

## MCP Configuration

This skill uses the Cognee MCP server defined in `mcp.json`.

## Usage Patterns

### First-time Setup
1. Ensure Cognee MCP server is running
2. Index your codebase: Use the codify tool to build the knowledge graph
3. Wait for indexing to complete (progress shown in output)

### Daily Workflow
1. Start new Amp thread normally
2. When you need context, ask Amp to "search cognee for [topic]"
3. The agent will query the graph and retrieve only relevant context
4. Continue with the specific context loaded

### Re-indexing
- Run codify again after significant code changes
- Use incremental indexing if available (faster)

## Best Practices

- Index once
