# SYSTEM ARCHITECTURE

A technical blueprint outlining the application structure, loop handling mechanism, data boundaries, and scaling approach for the Career Mentor Agent.

### System Overview

```text
 ┌────────────────┐          ┌──────────────────────────────────────────────┐
 │ Telegram User  │          │ Career Mentor Agent Runtime (Python 3.12)    │
 └────────────────┘          │                                            │
        ▲    │               │  ┌───────────────┐     ┌────────────────┐  │
        │    │ Webhooks/     │  │ telegram_bot  │────▶│ MentorService  │  │
        │    │ Polling       │  └───────────────┘     └────────────────┘  │
        │    ▼               │                               │   ▲        │
 ┌────────────────┐          │                               ▼   │        │
 │ Telegram Cloud │          │  ┌───────────────┐     ┌────────────────┐  │
 └────────────────┘          │  │ SQLite memory │◀───▶│   Tool Layer   │  │
                             │  └───────────────┘     └────────────────┘  │
                             └────────────┬──────────────┬────────┬───────┘
                                          │              │        │
                                          ▼              ▼        ▼
                                 ┌────────────┐   ┌─────────┐  ┌────────┐
                                 │ LLM Engine │   │ GWS CLI │  │ APIs   │
                                 │ (Groq/OR)  │   │ process │  │ HTTP   │
                                 └────────────┘   └─────────┘  └────────┘
```

### Agent Loop Logic

The system does not rely on heavy orchestration frameworks like LangChain, avoiding dependencies and "black-box" overhead. 
Instead, it handles loops manually across 5-iteration bounded limits.

**Core Pseudocode Execution**:
```python
def chat(conversation):
    for generation_round in range(5): # Bounded Limit
        history = sqlite.get_history_json()
        payload = [SYSTEM_PROMPT] + history
        
        response = llm.generate(payload)
        
        if response.calls_tools():
            for tool in response.tools:
                sqlite.save_message("assistant", tool_intent)
                result = ToolRegistry.execute(tool.name, tool.kwargs)
                sqlite.save_tool_result(result)
            # Re loop into generation with new DB stack
        else:
            sqlite.save_message("assistant", response.text)
            return response.text
```

### Data Flow Overview

1. `telegram_bot.py` continuously listens asynchronously. Once triggered, validation against whitelist logic runs stringently.
2. The user text cascades through `groq_service.py` where the loop evaluates state history context.
3. The LLM engine (Groq endpoint) is fed up to 20 past state items alongside strict behavior prompts (`prompts/mentor_prompt.py`).
4. Determinations execute Python tooling (`services/*`), transforming input queries into external API operations.
5. Internal results hit the SQLite memory persistence before flowing back for interpretation.
6. The interpreted human-readable markdown routes back to `telegram_bot.py` and subsequently standard I/O sockets.

### Memory System (SQLite persistence)

The app natively stores history securely avoiding third-party vector databases for pure transactional execution.

- **`conversations` table**:
  - Contains strictly normalized roles (`user`, `assistant`, `tool`), preserving `tool_calls` stringified JSON objects, allowing contextual reconstruction of past sub-agent logic.
- **`learning_items` table**:
  - Tracks specific backlogs containing parameters standardizing type enforcement: `tipo`, `url`, `fecha_objetivo` (dates parsed dynamically), `relevancia` (1-10 priority scoring weight ranges), mitigating generic non-structured learning plans.

### Tool Registration System

Every callable logic executes via the internal switchboards handling errors gracefully without failing the entire loop.

- `read_google_doc`: Utilizes the isolated internal `gws_service.py` subprocess command arrays.
- `create_improved_cv`: Orchestrates `cv_service.py` PDF bytes buffer reading, matching against `user_profile.json`, injecting Google Doc endpoints remotely.
- `search_jobs`: Asynchronous request bounds fetching structured RapidAPI datasets formatting them synchronously to text models stripping edge queries effectively.
- `add_learning_item` / `list_learning_items`: Intersect directly with `memory.db` exposing strictly filtered schema projections.

### Scalability Notes

The architecture prioritizes stateless execution nodes natively deploying inside immutable cloud containers (e.g., Railway/Fly.io). 

- **Environment driven initialization**: Absolute path resolving algorithms guarantee relative storage targets dynamically align across Linux VM layouts.
- **Config variables**: Centralizes credential logic dropping file-IO bounds when fetching secrets over to PaaS engines. (e.g. `GOOGLE_TOKEN_BASE64`).
- **Data storage abstractions**: Standard queries interface isolating `get_connection()` meaning database swaps (Postgres over SQLite for fleet scaling) require 1-line parameter logic modification alongside specific native connectors.
