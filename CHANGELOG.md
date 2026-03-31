# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.0.0] - 2026-03-29

### Added
- **Core Orchestrator Engine**: Manual agent looping mechanism with max-iteration bounded protection to guarantee safety on infinite tool permutations.
- **Native LLM routing**: Priority switching between inference chains (Groq 70B -> Groq 8B -> 7 mixed OpenRouter fallback routines) for extremely high availability against external API timeouts or limit thresholds.
- **Persistent SQLite Memory**: Fully built structure maintaining multi-schema memory mapping (`conversations`, `learning_items`) automatically persisting histories.
- **Proactive Cron Subsystem**: APScheduler implementation mapping internal alarms broadcasting independent proactive payloads to the designated Telegram clients natively mapping specific dates handling timezone boundaries.
- **Google Workspace Subroutines**: Total external integration manipulating the stateless `gws` subprocess via CLI bypassing native python bloated library distributions. Validated implementations pushing new calendar events, writing CV docs remotely, and rendering user Gmail inboxes dynamically.
- **Automated CV Analyser Engine**: PyMuPDF text rendering algorithm passing targeted extraction tasks back to the agent assessing percentage matching metrics according to `user_profile` standards.
- **Learning Backlog System**: Smart URLs inspection fetching internal titles / HTML meta parameters formatting automated learning deadlines prioritized out of natural language processing queues.
- **Cloud Delivery Readiness**: Full OS signal capture intercepts allowing safe PaaS shutdown mechanics alongside `.railwayignore` implementations rendering continuous deployments fully transparent over generic containers.
