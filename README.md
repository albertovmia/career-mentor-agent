# 🤖 Career Mentor Agent

*Personal AI career mentor built with Python, Groq LLaMA 3.3 70B and Telegram*

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white) ![Groq LLaMA](https://img.shields.io/badge/Groq-LLaMA_3.3_70B-orange?logo=meta&logoColor=white) ![Telegram](https://img.shields.io/badge/Telegram-Bot-blue?logo=telegram&logoColor=white) ![Google Workspace](https://img.shields.io/badge/Google-Workspace-green?logo=google&logoColor=white) ![License](https://img.shields.io/badge/License-MIT-green.svg)

---

### What it does
Career Mentor Agent is a sophisticated AI-driven assistant delivered through Telegram that helps professionals track and accelerate their career transition. It combines persistent SQLite memory, autonomous tool calling, and an agentic loop to search for jobs, manage learning backlogs, format CVs, and interact with live APIs, transforming generic LLM chatting into an actionable, context-aware mentoring experience.

### Key Features
- 🔍 **Real-time job search** via JSearch API (Remote global tracking).
- 📧 **Gmail integration** via Google Workspace CLI (reads and drafts emails).
- 📅 **Google Calendar management** (scheduling events with precise deadlines).
- 🧠 **Persistent memory** with SQLite (retains conversation context and tool execution history).
- 📚 **Learning backlog manager** with tracked objectives, relevance scoring, and deadlines.
- 📄 **CV analysis and Google Docs generation** (PDF parsing and automated tailored documents).
- 🔄 **Agent loop** built manually over Groq LLaMA 3.3 70B + OpenRouter multi-model fallbacks.
- ⏰ **Proactive daily scheduler** (morning briefings on market news, pending learnings, and latest job postings).

### Architecture

```
Telegram Messages
       │
       ▼
 ┌───────────────┐        ┌──────────────────┐
 │ Telegram Bot  │───────▶│  MentorService   │
 │   (Async)     │◀───────│   (Agent Loop)   │
 └───────────────┘        └──────────────────┘
                                │      ▲
                                ▼      │
                          ┌──────────────────┐
                          │    Tool Calls    │
                          │ - analyze_cv     │
                          │ - search_jobs    │
                          │ - gws_commands   │
                          │ - learning_items │
                          └──────────────────┘
                                │      ▲
                                ▼      │
                     ┌───────────────────────┐
                     │ External APIs & DB    │
                     │ (Groq, GWS CLI, DB)   │
                     └───────────────────────┘
```
- **Bot Layer**: Handles incoming updates asynchronously and validates the user.
- **Service Layer (Agent Loop)**: Parses intent, injects system prompt, accesses DB history, routes to tools, and ensures maximum iteration boundaries.
- **Tooling Layer**: Specific decoupled modules mapping to APIs (JSearch, GWS CLI, PyMuPdf, DB sqlite queries).

### Tech Stack

| Technology | Purpose | Version |
|---|---|---|
| **Python** | Core logic and backend programming | 3.12.0 |
| **python-telegram-bot** | Telegram async interaction wrapper | 20.x |
| **Groq LLaMA 3.3 70B** | Primary LLM engine for lightning-fast inference | latest |
| **OpenRouter** | 7-model automated fallback strategy for high availability | latest |
| **SQLite (sqlite3)** | Persistent long-term memory and history storage | Native |
| **Google Workspace CLI (gws)** | Headless tool for zero-dependency API interactions | global/npx |
| **JSearch RapidAPI** | Worldwide job posting scraper logic | v1 |
| **aiohttp** | Asynchronous HTTP requests avoiding blockers | latest |
| **pydantic-settings** | Type-safe environment variable parsing | latest |

### Project Structure
```text
career-mentor-agent/
├── bot/
│   └── telegram_bot.py       # Telegram integration and message routing
├── credentials/
│   └── token.json            # Auto-generated GWS CLI OAuth tokens (ignored)
├── data/
│   ├── memory.db             # Persistent SQLite database (ignored)
│   └── user_profile.json     # Hardcoded target profile and skill maps
├── memory/
│   └── database.py           # SQLite bootstrap, history queries, and inserts
├── prompts/
│   ├── mentor_prompt.py      # Main System Instructions (LLM Persona & tool directions)
│   └── news_prompt.py        # RSS aggregation specific prompt
├── services/
│   ├── cv_service.py         # PyMuPdf extraction and CV dict generation
│   ├── groq_service.py       # Core execution loop and LLM API handling
│   ├── gws_service.py        # Wrapper around Google Workspace CLI execution
│   ├── jobs_service.py       # JSearch RapidAPI asynchronous requests
│   ├── learning_service.py   # Backlog extraction and web scraping summaries
│   ├── news_service.py       # RSS feeding and updates
│   └── scheduler_service.py  # APScheduler daily proactive tasks
├── utils/
│   └── logger.py             # Standardized structured logging across the app
├── .env                      # API tokens and config
├── config.py                 # Pydantic Settings injection
├── main.py                   # App entrypoint and orchestrator
├── Procfile                  # Defines the worker container command for deployment
├── runtime.txt               # Defines target Python version for PaaS
├── README.md                 # You are here!
├── SETUP.md                  # Comprehensive installation manual
└── ARCHITECTURE.md           # Technical blueprint
```

### Quick Start
1. **Clone & install**:
   ```bash
   git clone https://github.com/albertovalle/career-mentor-agent.git
   cd career-mentor-agent
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Configure `.env`**: Copy `.env.example` to `.env` and fill in necessary keys.
3. **Google Workspace auth**: Setup GWS CLI and login via terminal: `gws auth login`.
4. **Run the bot**:
   ```bash
   python3 main.py
   ```

### Configuration

| Variable | Description | Required |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token provided by BotFather on Telegram | Yes |
| `ALLOWED_USERS` | Comma-separated Telegram User IDs for access control | Yes |
| `GROQ_API_KEY` | Free lighting-fast inference API key from Groq | Yes |
| `OPENROUTER_API_KEY` | Multi-model fallback key to bypass rate limits | Optional |
| `RAPIDAPI_KEY` | RapidAPI key specifically subscribed to JSearch | Yes |
| `GWS_CREDENTIALS_FILE` | Absolute path to `credentials.json` for OAuth | Yes |
| `GOOGLE_TOKEN_BASE64` | `token.json` encoded in Base64 (used for PaaS deployments) | Optional |
| `DB_PATH` | Path pointing to the SQLite storage file | Yes (`data/memory.db`) |

### How it works

**1. The Agent Loop**: The bot orchestrates tool calling through a manual loop structure up to a limit of 5 iterative calls. When the LLM outputs a `tool_calls` payload, the execution engine intercepts it, matches it to a defined python tool inside `services/groq_service.py`, awaits the internal computation, and returns the serialized JSON payload to the history stack back to the LLM until the LLM writes a direct message. 

**2. Persistent Memory System**: Every message, payload, and tool call ID is meticulously inserted into an SQLite `conversations` table. To maintain performance, only the top $N$ relevant messages are hydrated into the context window with the system prompt injected at the top upon every new request, maintaining an illusion of infinite context.

**3. Third-party Integrations**: We decoupled OAuth complexity using a highly capable headless CLI wrapper (`gws`), executing it as an asynchronous detached subprocess, retrieving JSON parsed from standard outputs. JSearch is called exclusively removing noisy locations automatically.

### Roadmap
- [ ] LinkedIn automation with Playwright
- [ ] News monitoring and market intelligence
- [ ] WhatsApp integration
- [ ] Cloud deployment (Railway/Fly.io)

### Author
**Alberto Valle**
- LinkedIn: [https://www.linkedin.com/in/albertovalle/](https://www.linkedin.com/in/albertovalle/)
- GitHub: [https://github.com/albertovalle](https://github.com/albertovalle) *(Update with your URL)*

### License
MIT
