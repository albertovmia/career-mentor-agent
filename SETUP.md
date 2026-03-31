# SETUP & INSTALLATION GUIDE

This guide walks you through fully configuring and running the **Career Mentor Agent** completely from scratch securely on your machine.

## 1. Prerequisites
- **Python 3.12+**: This app requires typing semantics available in modern Python distributions.
- **Node.js**: Expected to be installed globally on your system to run the `gws` (Google Workspace CLI) dependency.
- **Git**: To clone the repository properly.

## 2. Step-by-Step Installation

```bash
# Clone the repository
git clone https://github.com/albertovalle/career-mentor-agent.git
cd career-mentor-agent

# Set up the isolated Python environment
python3 -m venv venv
source venv/bin/activate

# Install all module requirements
pip install -r requirements.txt
```

## 3. Google Workspace Setup

The bot needs specific Calendar, Docs, and Gmail read/write permissions to be an active orchestrator.

1. Head to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a Project and enable **Gmail API**, **Google Calendar API**, and **Google Docs API**.
3. Create "OAuth Desktop App" credentials and download it as `credentials.json` directly into `./credentials/credentials.json`.
4. Install GWS globally:
   ```bash
   npm install -g gws-cli
   ```
5. Auth flow execution:
   ```bash
   # Make sure you are in the project root
   gws auth login --client-id <YOUR_CLIENT_ID> --client-secret <YOUR_CLIENT_SECRET>
   ```
6. The CLI will open a browser URL. Accept the warnings (since it's an unverified personal app), proceed, and allow the requested ranges. It will automatically generate a valid `./credentials/token.json`.

*(Critical: our deployment requires reading the key `type: authorized_user` within `token.json`. The codebase automatically injects it if the CLI forgets it, but verify manually if auth acts up).*

## 4. RapidAPI / JSearch Setup

JSearch is responsible for our real-time remote job scraper.
1. Sign up on [RapidAPI.com](https://rapidapi.com/).
2. Search for `JSearch` and subscribe to the Free/Basic plan.
3. Obtain your `X-RapidAPI-Key` from the dashboard and set it inside the `.env` configuration file as `RAPIDAPI_KEY`.

## 5. Groq API Setup

Our blazing fast LLM inference backend relies on Groq LPU technology.
1. Create a free account at [console.groq.com](https://console.groq.com/).
2. Navigate to "API Keys" and generate one.
3. Update `GROQ_API_KEY` inside `.env`.

## 6. OpenRouter Setup (Optional fallback)

Since Groq's free endpoint is extremely fast but highly rate-limited natively on tokens-per-minute, we use an OpenRouter fallback script handling 7 different tier-free models transparently.
1. Register at [openrouter.ai](https://openrouter.ai/).
2. Get your key and append it as `OPENROUTER_API_KEY`. The fallback loop will do the heavy lifting autonomously.

## 7. Running the Bot

Populate your `.env` (Use `.env.example` as a template). Run the bot natively:
```bash
# Make sure your paths and venv are active:
python3 main.py
```
You should see: `Bot iniciado correctamente. Ctrl+C para detener.`

## 8. Common Issues

- **`GoogleAuthError` or "invalid grant" / "auth error"**: The `token.json` expired or lost the refresh state. Delete `token.json` and redo step 3.5.
- **Bot responds but NO tools execute**: Check that the Telegram user ID speaking actually matches the numerical array bound inside `ALLOWED_USERS` in your `.env`.
- **"ModuleNotFoundError: No module named 'pydantic_settings'"**: You forgot to run `source venv/bin/activate`!
