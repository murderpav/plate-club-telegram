PLATE CLUB 3.0 — TELEGRAM EDITION (starter project)

WHAT'S INCLUDED
- Existing PLATE CLUB game and FastAPI API
- Telegram Mini App initData verification on the server
- Automatic Telegram-based account creation/login
- Telegram bot with /start and a Play button
- Existing username/password login retained for browser use

IMPORTANT LIMIT
Telegram Mini Apps must use a publicly reachable HTTPS URL. http://127.0.0.1:8000 only works on your own computer and Telegram cannot open it as a public Mini App. This archive is prepared for deployment but is NOT already published online. You need a hosting provider/domain or HTTPS tunnel for testing.

LOCAL WEBSITE TEST
1. Install Python 3.10+.
2. Run START_GAME.bat; this starts the website/API locally.
3. Browser game works at http://127.0.0.1:8000.

TELEGRAM SETUP
1. In Telegram, open @BotFather and use /newbot. Save the bot token privately.
2. Deploy this folder to a Python host with a persistent disk (SQLite database must persist) and configure HTTPS.
3. Set environment variables on the host:
   TELEGRAM_BOT_TOKEN = token from BotFather
   WEBAPP_URL = the public HTTPS URL of the deployed game
4. Set the same TELEGRAM_BOT_TOKEN for the API service, because the API verifies Telegram initData.
5. On your PC, copy .env.example to .env and fill values to run the bot. Do not share .env or publish the token.
6. Install dependencies with: py -m pip install -r requirements.txt
7. Start the bot with: py bot.py
8. In @BotFather, configure the bot's menu button / Mini App if desired. The bot reply keyboard already has a Web App button.

SECURITY NOTES
- Never put the bot token in index.html or any client-side code.
- Do not run a public production game on a development server. Use HTTPS and a proper ASGI deployment.
- Back up plate_club.db before migration/deployment.
- Telegram login creates a stable internal account named tg<telegram_id>. The display name is not used as a unique login.
- The bot's profile/bonus/top buttons currently guide the player into the game; the real profile, daily reward and leaderboard remain in the Mini App.
- The browser login remains available as a fallback outside Telegram.

CURRENT STATUS
Syntax checks are performed when preparing the archive, but deployment and live Telegram login cannot be tested until you provide a real bot token and public HTTPS URL.
