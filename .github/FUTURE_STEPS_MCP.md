# Future Steps: MCP Server & Context Distribution

> **Goal**: Package the agentic development infrastructure (skills, toolsets, memory, reference code) into an MCP server — enabling AI agents to build Hailo apps **without cloning the repository**.

---

## Executive Summary

We've built an agentic infrastructure that allows AI coding agents to autonomously build production-ready Hailo applications from a single prompt — demonstrated end-to-end with a dog monitoring VLM app built in under 5 minutes for ~$4 in compute. Today, this only works when the developer has the hailo-apps repository cloned locally. The next step is packaging this knowledge into an MCP server — an industry-standard protocol for giving AI agents access to tools and context — so that any developer, on any platform, can build Hailo apps without needing our repo. The agent simply calls our MCP server, gets the coding patterns, conventions, and working reference code, and builds the app.

This complements our existing Kapa integration, which serves Hailo documentation. Kapa answers "how does the API work?" — our MCP server answers "here's a complete working app you can adapt." Together, they give AI agents everything they need: the documentation for edge cases and the actual production code patterns for building. The MCP server is auto-generated from the same markdown files we've already written, so there's no duplicate maintenance — one source of truth, multiple distribution channels.

---

## 1. Architecture Overview

### Current State (repo-local context)

Today, agents must have the hailo-apps repo open to access the many context files. The agent makes several `read_file` calls to gather skills, conventions, memory, and reference code before writing a single line.

### Target State (MCP-distributed context)

An MCP server bundles and distributes the same context. Agents access it via tool calls — no repo clone needed.

```
hailo-apps repo (single source of truth)
│
├── Code with rich docstrings              ← already exists partially
├── .github/ agentic context               ← already exists (44 files)
├── Module-level README.md files           ← TO ADD
└── .mcp-manifest.yaml                     ← TO ADD (extraction config)
         │
         ▼  (CI/CD generator script)
         │
hailo-app-builder-mcp server (auto-generated, published)
├── server.py                              ← @server.tool() definitions
├── context_packs/                         ← Pre-composed context blobs
├── reference_code/                        ← Frozen app snapshots
└── templates/                             ← Parameterized starters
```

### Scope — Not Just hailo-apps

The MCP server can serve as the distribution layer for **all Hailo developer assets**, not just the hailo-apps repository. This includes HailoRT API references, Model Zoo documentation, TAPPAS pipeline patterns, and hardware configuration guides — any structured knowledge an agent needs to build on the Hailo platform.

### Distinction from Kapa (Hailo Documentation MCP)

Kapa already provides an MCP server for Hailo — but it serves **documentation only** (user guides, API references, knowledge base articles). This MCP server would serve **actual working code** alongside instructions.

| | Kapa (docs) | Hailo App Builder MCP (code + docs) |
|---|---|---|
| **Content type** | Documentation pages, KB articles, guides | Production source code, skills, templates, conventions |
| **What agents get** | "Here's how the VLM API works" | "Here's a complete working VLM app — 300 lines of code you can adapt" |
| **Code examples** | Snippets embedded in docs (if any) | Full reference implementations (vlm_chat.py, backend.py, dog_monitor.py) |
| **Build patterns** | Not available | Step-by-step skill files, event tracker patterns, signal handling |
| **Registration info** | Not available | Exact code to add to defines.py and resources_config.yaml |
| **Templates** | Not available | Parameterized starters with placeholders filled in |
| **Pitfalls & memory** | Not available | Lessons learned from real builds (YAML gotchas, queue deadlocks, etc.) |

**They are complementary, not competing.** An agent building a Hailo app would use both:
1. **Hailo App Builder MCP** — for code patterns, conventions, reference implementations, and templates
2. **Kapa MCP** — for SDK edge cases, undocumented API parameters, HailoRT driver troubleshooting, and HEF compatibility questions that aren't covered in the local docs

In the dog monitor build, local docs (what would become the App Builder MCP) provided 100% of the needed context. Kapa was not invoked. But for novel use cases or uncommon hardware configurations, Kapa fills gaps the code-focused MCP cannot.

---

## 2. Relationship to Existing Markdown Infrastructure

The skills and markdown files (.github/) are the **primary content source** for the MCP server. The MCP server doesn't replace them — it **packages and distributes** them.

```
YOUR MARKDOWN FILES                         MCP SERVER
(.github/ in hailo-apps)                    (hailo-app-builder-mcp)

skills/create-vlm-app.md ──────┐
instructions/coding-standards.md──┐         context_packs/vlm_monitor.md
memory/gen_ai_patterns.md ───────┤  concat  (= all files concatenated
memory/common_pitfalls.md ───────┤  ──────► into ONE response for
toolsets/vlm-backend-api.md ─────┘          get_build_context("vlm_monitor"))

vlm_chat/vlm_chat.py ───────────┐  copy    reference_code/vlm_chat/
vlm_chat/backend.py  ───────────┘  ──────► (frozen snapshots)
```

**Two consumers, same markdown:**

| Consumer | How it reads the markdown | Benefit |
|---|---|---|
| VS Code agent (local) | `read_file` tool, ~15 calls | Full access, always fresh |
| MCP server (remote) | Pre-bundled, 1 tool call | No repo needed, faster |

Every improvement to the markdown pays off three times — for local VS Code agents, for the MCP server, and for human developers reading the repo.

### What the MCP adds on top of the markdown

The markdown alone is passive files sitting in a repo. The MCP server adds:

| Addition | What it does |
|---|---|
| **Routing** | `get_build_context("vlm_monitor")` knows which files to combine (automates the routing table) |
| **Bundling** | 15 files → 1 response (saves 14 tool calls, ~30s latency) |
| **Templates** | Turns patterns described in markdown into ready-to-use code skeletons |
| **Distribution** | Users who don't have the repo can still get the context |
| **Searchability** | `search_examples("signal handling")` across all bundled content |

---

## 3. Documentation Enrichment (In-Place)

The hailo-apps repo is already halfway there — designed for agentic development, which makes it well-suited for MCP extraction by design. The remaining enrichment is additive: module-level READMEs and richer docstrings that benefit humans, local agents, and MCP extraction equally.

### What to add

| Priority | What | Where | Value |
|---|---|---|---|
| **P1 (High)** | Module-level README.md files | Each key directory under `hailo_apps/` | Useful for humans, agents, and MCP extraction |
| **P2 (High)** | `.mcp-manifest.yaml` | Repo root | Defines what gets extracted and how it's packaged |
| **P3 (Medium)** | Enriched function docstrings | ~20 public API functions | Better tool descriptions, better MCP content |
| **P4 (Medium)** | Generator script | `scripts/generate_mcp_server.py` | Reads manifest + repo → produces MCP server package |
| **P5 (Low)** | Publish MCP server | PyPI / npm | `uvx hailo-app-builder-mcp` — no repo clone needed |

### Module README.md example targets

```
hailo_apps/python/gen_ai_apps/README.md          ← "How gen AI apps work"
hailo_apps/python/gen_ai_apps/vlm_chat/README.md ← "Reference VLM app"
hailo_apps/python/gen_ai_apps/gen_ai_utils/README.md ← "Shared utilities"
hailo_apps/python/core/README.md                 ← "Core framework overview"
hailo_apps/python/core/common/README.md          ← "Shared utilities"
hailo_apps/python/core/gstreamer/README.md       ← "GStreamer pipeline construction"
```

### `.mcp-manifest.yaml` — extraction config

```yaml
name: hailo-app-builder
version: auto

context_packs:
  vlm_monitor:
    description: "Build continuous VLM monitoring apps"
    skill: .github/skills/hl-build-vlm-app/SKILL.md
    instructions:
      - .github/instructions/coding-standards.md
    memory:
      - .github/memory/gen_ai_patterns.md
      - .github/memory/common_pitfalls.md
    toolsets:
      - .github/toolsets/vlm-backend-api.md
    reference_code:
      - hailo_apps/python/gen_ai_apps/vlm_chat/vlm_chat.py
      - hailo_apps/python/gen_ai_apps/vlm_chat/backend.py
      - hailo_apps/python/gen_ai_apps/dog_monitor/dog_monitor.py
    registration_files:
      - hailo_apps/python/core/common/defines.py
      - hailo_apps/config/resources_config.yaml

api_surface:
  - hailo_apps/python/core/common/core.py:
      functions: [resolve_hef_path, get_standalone_parser, handle_list_models_flag]
  - hailo_apps/python/gen_ai_apps/vlm_chat/backend.py:
      classes: [Backend]
```

---

## 4. MCP Tool Invocation — How It Works

MCP tools are invoked by the **AI agent deciding to call them** — there is no hashtag or keyword trigger.

```
User prompt: "Build me a dog monitor VLM app"
      │
      ▼
AI Agent sees:
  1. The user's request
  2. Available tools (including MCP tools)
  3. Each tool's name + description + parameter schema
      │
      ▼
Agent DECIDES: "I need Hailo app-building context"
      │
      ▼
Agent calls: get_build_context(app_type="vlm_monitor")
```

The agent picks the tool based on the tool's **name**, **description** (docstring), **parameter descriptions**, and **conversation context**. The decision is probabilistic:

$$P(\text{call tool X} \mid \text{user prompt, system prompt, tool descriptions, history})$$

### What influences whether the agent calls your tool

| Factor | Impact | Example |
|---|---|---|
| Tool name | High | `get_build_context` is clear; `func_7` is not |
| Tool description (docstring) | Highest | "Call this FIRST when building any Hailo app" |
| Parameter descriptions | Medium | Lists valid `app_type` values |
| System prompt instructions | High | "When building any Hailo app, ALWAYS call `get_build_context` first" |
| User's words | Medium | "Hailo", "VLM", "dog monitor" → agent matches to tool |

---

## 5. Determinism & the `tool_choice` API Parameter

### The gap

```
What we want:  IF user says "build Hailo app" → ALWAYS call get_build_context() first
What we have:  IF user says "build Hailo app" → PROBABLY calls get_build_context() first
```

System prompt instructions achieve ~95% compliance but are not deterministic. The `tool_choice` API parameter provides stronger guarantees.

### `tool_choice` modes

When calling the Claude or OpenAI API, alongside `messages` and `tools`, you pass `tool_choice`:

| `tool_choice` value | Which tool | Whether to call | Parameters | Use case |
|---|---|---|---|---|
| `"auto"` (default) | LLM decides | LLM decides | LLM decides | Normal chat |
| `"required"` | LLM decides | **Forced yes** | LLM decides | "Always use a tool" |
| `{"name": "X"}` | **Forced X** | **Forced yes** | LLM decides | "Always call this specific tool first" |
| `"none"` | N/A | **Forced no** | N/A | "Never call tools" |

### Who controls `tool_choice`?

The **host application** sets `tool_choice`, not the MCP server.

| Platform | Who sets tool_choice | Can you control it? |
|---|---|---|
| VS Code Copilot | VS Code extension | No — always `"auto"` |
| Claude.ai chat | Anthropic frontend | No — always `"auto"` |
| Your own app calling API | You | **Yes** — full control |
| Claude Code CLI | Anthropic agent framework | No — managed internally |

**Implication**: To get deterministic "always load context first" behavior, you'd need a custom wrapper that calls the API with `tool_choice: {"name": "get_build_context"}` on the first turn, then switches to `"auto"` for subsequent turns.

---

## 6. Context Injection Hierarchy Across Platforms

Different platforms inject project context at different privilege levels. Understanding this determines how reliably the agent follows our instructions.

### VS Code Copilot

| # | Level | Mechanism | File Pattern | How Triggered | Compliance | In This Repo |
|---|---|---|---|---|---|---|
| | **SYSTEM PROMPT (privileged — injected before user message)** | | | | | |
| 1 | System | **Global instructions** | `.github/copilot-instructions.md` | **Auto** — every turn, every chat | ~99% | 1 file |
| 2 | System | **Agent/Mode definition** | `.github/agents/*.agent.md` | **Auto** — when user switches to that agent mode | ~99% | 1 file (`hailo-vlm-builder`) |
| 3 | System | **Contextual instructions** (`applyTo` globs) | `.github/instructions/*.instructions.md` | **Auto** — when files matching the glob are in editor context | ~99% | 5 files (core, gen-ai, pipeline, standalone, tests) |
| | **USER-LEVEL (user explicitly triggers — guaranteed in context)** | | | | | |
| 4 | User | **Custom Skills** (`#` invocation) | `.github/skills/*/SKILL.md` | User types `#skill-name` in chat — full content injected | ~100% | 1 skill (`#hl-build-vlm-app`) |
| 5 | User | **Prompt files** (copy-paste or `/` command) | `.github/prompts/*.prompt.md` | User pastes prompt content into chat — it IS the user message | ~100% | 6 files |
| 6 | User | **File attachment** (drag or 📎) | Any file | User explicitly attaches file to chat message | ~100% | — |
| 7 | User | **Editor context** (active file + selection) | Whatever is open | **Auto** — open file & selection sent with each message | ~95% | — |
| | **AGENT-LEVEL (agent decides during execution — probabilistic)** | | | | | |
| 8 | Agent | **`read_file` tool** | Any file in workspace | Agent decides based on instructions or its own judgment | 70–95%* | 28+ `.md` files (skills, memory, toolsets) |
| 9 | Agent | **Workspace search** (`semantic_search`, `grep_search`) | Any file in workspace | Agent decides to search when it needs information | 70–90%* | — |
| 10 | Agent | **Sub-agent delegation** (`runSubagent`) | Files read by sub-agent | Agent (or orchestrated prompt) delegates a research task | 85–95%* | — |
| 11 | Agent | **MCP tool calls** | External server | Agent decides to query based on tool description match | 80–90%* | 1 server (Kapa) |

\* Compliance for agent-level mechanisms depends on the prompt approach:

| Mechanism | Flat Prompt | Orchestrated Prompt |
|---|---|---|
| `read_file` (level 8) | ~70% — agent may skip memory/skills | ~95% — prompt lists exact files to read |
| Sub-agents (level 10) | ~50% — agent may not use sub-agents at all | ~95% — prompt prescribes sub-agent tasks |
| MCP calls (level 11) | ~30% — agent rarely calls MCP unprompted | ~90% — prompt can require MCP lookup |

### Claude Code (CLI & VS Code extension)

| Level | File | Injection | Compliance |
|---|---|---|---|
| **System prompt** (privileged) | `CLAUDE.md` at repo root | Auto-loaded on session start | ~99% |
| **System prompt** (privileged) | `.claude/` directory rules (if configured) | Auto-loaded on session start | ~99% |
| **Tool results** (user-level) | Any file the agent reads | Agent reads via built-in file tools | ~95% |

Claude Code has no equivalent of custom modes, `applyTo` globs, or instruction files. Everything beyond `CLAUDE.md` is agent-initiated.

### Cursor / Windsurf

| Level | File | Injection | Compliance |
|---|---|---|---|
| **System prompt** (privileged) | `.cursorrules` / `.windsurfrules` | Auto-loaded on session start | ~99% |
| **Tool results** (user-level) | Any file the agent reads | Agent reads via built-in tools | ~95% |

### copilot.microsoft.com / claude.ai (browser chat)

| Level | File | Injection | Compliance |
|---|---|---|---|
| **None** | No auto-loaded project files | User must paste context manually | Varies |
| **MCP tools** (if configured) | MCP server responses | Agent decides to call tools | ~95% |

This is where the MCP server becomes essential — it's the **only way** to get structured project context into browser-based agents without manual copy-paste.

### Summary: Why MCP matters more for some platforms

| Platform | Has auto-loaded project context? | MCP necessity |
|---|---|---|
| VS Code Copilot | Yes (3 levels of auto-injection) | Nice-to-have (saves tool calls) |
| Claude Code | Yes (`CLAUDE.md` only) | Moderate (supplements limited auto-load) |
| Cursor / Windsurf | Yes (rules file only) | Moderate |
| Browser chat (any) | No | **Essential** (only way to get context in) |
| Custom API wrapper | You control everything | Optional (can inject context directly) |

---

## 7. Implementation Roadmap

```
Phase 1: Enrich repo in-place
├── Add module-level README.md files (~10-15 files)
├── Enrich key function docstrings (~20 functions)
└── Create .mcp-manifest.yaml

Phase 2: Build MCP server
├── Create server.py with @server.tool() definitions
├── Build generator script (reads manifest → packages content)
├── Bundle reference code + context packs

Phase 3: Validate & publish
├── Test with VS Code MCP integration
├── Test with Claude Code
├── Publish to PyPI/npm
└── Add to Hailo developer documentation

Phase 4: Expand scope
├── Add non-hailo-apps Hailo assets (HailoRT, Model Zoo, TAPPAS)
├── Add CI/CD pipeline (auto-publish on release)
└── Iterate based on agent usage telemetry
```

---

## 8. Key Design Decisions

| Decision | Rationale |
|---|---|
| **Bundle code examples into MCP** | Instructions without reference code are incomplete. The agent needs `vlm_chat.py` to understand the pattern, not just the description of it. |
| **Pre-compose context packs** | One MCP call replaces 15 `read_file` calls — saves tokens, latency, and cost. |
| **Hybrid content strategy** | Bundle stable patterns (vlm_chat, backend.py) as snapshots. Fetch latest for new/evolving apps. |
| **MCP server is separate from hailo-apps** | Clean separation: hailo-apps is the source of truth; the MCP server is the distribution layer. |
| **Generator script in CI/CD** | Every tagged release auto-publishes an updated MCP server. No manual sync. |

---

## Appendix: MCP Server Reference Implementation

Complete `server.py` with all `@server.tool()` definitions for the Hailo App Builder MCP server.

```python
# hailo-app-builder-mcp/server.py
from mcp.server import Server
from mcp.types import TextContent
from pathlib import Path
import json

server = Server("hailo-app-builder")

PACKS_DIR = Path(__file__).parent / "context_packs"
REF_DIR = Path(__file__).parent / "reference_code"
TEMPLATES_DIR = Path(__file__).parent / "templates"


@server.tool()
async def get_build_context(app_type: str) -> str:
    """Get all context needed to build a Hailo app.

    Args:
        app_type: One of 'vlm_monitor', 'vlm_interactive', 'pipeline',
                  'standalone', 'agent', 'voice'

    Returns everything the agent needs in one call:
    skill instructions, coding conventions, memory/pitfalls,
    reference source code, and registration info.
    """
    pack_file = PACKS_DIR / f"{app_type}.md"
    if not pack_file.exists():
        available = [f.stem for f in PACKS_DIR.glob("*.md")]
        return f"Unknown app_type '{app_type}'. Available: {available}"
    return pack_file.read_text()


@server.tool()
async def get_reference_app(app_name: str) -> str:
    """Get full source code of a reference Hailo application.

    Args:
        app_name: One of 'vlm_chat', 'dog_monitor', 'agent_tools',
                  'voice_assistant', 'simple_vlm_chat'
    """
    app_dir = REF_DIR / app_name
    if not app_dir.exists():
        available = [d.name for d in REF_DIR.iterdir() if d.is_dir()]
        return f"Unknown app '{app_name}'. Available: {available}"

    result = []
    for py_file in sorted(app_dir.glob("*.py")):
        result.append(f"# ── {py_file.name} ──\n{py_file.read_text()}")
    return "\n\n".join(result)


@server.tool()
async def get_conventions() -> str:
    """Get Hailo coding standards and conventions.

    Returns import rules, logging patterns, HEF resolution,
    CLI parser usage, and signal handling requirements.
    """
    conv_file = PACKS_DIR / "_conventions.md"
    return conv_file.read_text()


@server.tool()
async def get_registration_info(app_name: str) -> str:
    """Get what must be registered for a new Hailo app.

    Args:
        app_name: The snake_case name for the new app (e.g. 'dog_monitor')

    Returns the exact code to add to defines.py and resources_config.yaml.
    """
    return json.dumps({
        "defines_py": {
            "file": "hailo_apps/python/core/common/defines.py",
            "add_constant": f'{app_name.upper()}_APP = "{app_name}"',
            "add_near": "# Gen AI app defaults",
        },
        "resources_config_yaml": {
            "file": "hailo_apps/config/resources_config.yaml",
            "add_entry": f"{app_name}: *vlm_chat_app",
            "add_after": "# Gen AI models section, after last complete block",
            "validate_cmd": 'python3 -c "import yaml; yaml.safe_load(open(\'hailo_apps/config/resources_config.yaml\')); print(\'OK\')"',
        },
        "app_directory": f"hailo_apps/python/gen_ai_apps/{app_name}/",
        "required_files": [
            "__init__.py",
            f"{app_name}.py",
            "README.md",
        ],
    }, indent=2)


@server.tool()
async def generate_app_template(
    app_name: str,
    app_type: str,
    system_prompt: str,
    monitor_prompt: str,
    event_categories: str = "",
    interval: int = 15,
) -> str:
    """Generate starter files for a new Hailo app with boilerplate filled in.

    Args:
        app_name: Snake_case app name (e.g. 'dog_monitor')
        app_type: One of 'vlm_monitor', 'vlm_interactive'
        system_prompt: VLM system prompt
        monitor_prompt: Per-frame VLM question
        event_categories: Comma-separated activity categories (for monitors)
        interval: Seconds between analyses (for monitors)

    Returns JSON dict of {filename: content} ready to write.
    """
    template_dir = TEMPLATES_DIR / app_type
    if not template_dir.exists():
        return f"No template for '{app_type}'"

    files = {}
    for tmpl_file in template_dir.glob("*"):
        content = tmpl_file.read_text()
        content = content.replace("{{APP_NAME}}", app_name)
        content = content.replace("{{APP_NAME_UPPER}}", app_name.upper())
        content = content.replace("{{APP_CONST}}", f"{app_name.upper()}_APP")
        content = content.replace("{{SYSTEM_PROMPT}}", system_prompt)
        content = content.replace("{{MONITOR_PROMPT}}", monitor_prompt)
        content = content.replace("{{INTERVAL}}", str(interval))
        if event_categories:
            cats = [c.strip().upper() for c in event_categories.split(",")]
            enum_lines = "\n".join(f'    {c} = "{c.lower()}"' for c in cats)
            content = content.replace("{{EVENT_CATEGORIES}}", enum_lines)

        out_name = tmpl_file.name.replace("app_name", app_name)
        files[out_name] = content

    return json.dumps(files, indent=2)


@server.tool()
async def get_pitfalls() -> str:
    """Get known bugs, anti-patterns, and lessons learned for Hailo apps.

    Check this BEFORE writing code to avoid common mistakes.
    """
    pitfalls_file = PACKS_DIR / "_pitfalls.md"
    return pitfalls_file.read_text()


@server.tool()
async def search_examples(query: str) -> str:
    """Search across all reference apps and docs for relevant code patterns.

    Args:
        query: Natural language query (e.g. 'how to handle end of video',
               'signal handling pattern', 'Backend constructor')
    """
    results = []
    for md_file in PACKS_DIR.glob("**/*.md"):
        content = md_file.read_text()
        if query.lower() in content.lower():
            idx = content.lower().index(query.lower())
            snippet = content[max(0, idx - 200):idx + 300]
            results.append(f"## {md_file.name}\n```\n{snippet}\n```")

    for py_file in REF_DIR.glob("**/*.py"):
        content = py_file.read_text()
        if query.lower() in content.lower():
            idx = content.lower().index(query.lower())
            snippet = content[max(0, idx - 200):idx + 300]
            results.append(
                f"## {py_file.relative_to(REF_DIR)}\n```python\n{snippet}\n```"
            )

    return "\n\n".join(results[:5]) if results else f"No matches for '{query}'"


# ── Entry point ─────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server

    async def main():
        async with stdio_server() as (read, write):
            await server.run(read, write)

    asyncio.run(main())
```

### Tool summary

| Tool | Purpose | Replaces |
|---|---|---|
| `get_build_context` | All context for an app type in one call | 15 `read_file` calls |
| `get_reference_app` | Full source of a reference app | 2-4 `read_file` calls per app |
| `get_conventions` | Coding standards and import rules | 1 `read_file` call |
| `get_registration_info` | Exact code to register a new app | Agent figuring out defines.py + YAML |
| `generate_app_template` | Ready-to-write starter files with placeholders filled | Agent writing boilerplate from scratch |
| `get_pitfalls` | Known bugs and anti-patterns | 1-2 `read_file` calls for memory files |
| `search_examples` | Keyword search across all bundled content | Multiple `grep_search` / `semantic_search` calls |

### User installation

```jsonc
// VS Code settings.json or Claude MCP config
{
  "mcpServers": {
    "hailo-app-builder": {
      "command": "uvx",
      "args": ["hailo-app-builder-mcp"]
    }
  }
}
```
