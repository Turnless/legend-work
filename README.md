# LEGEND Telegram Webhook (Vercel)

This package replaces Telegram long polling with a Telegram webhook. It is a deployment starter; local automated tests validate route/configuration logic, not live Telegram/Supabase credentials.

## Files
- `api/index.py`: Vercel FastAPI webhook endpoint at `/api/webhook` and health endpoint at `/api/health`.
- `render-api-update/main.py`: replacement code for the existing Render leaderboard API. It promotes matured referrals when the leaderboard is requested, checking current Telegram group membership.
- `requirements.txt`: Vercel dependencies.
- `vercel.json`: route rewrite for the FastAPI app.
- `supabase/schema.sql`: complete schema including persisted human-check fields.
- `supabase/schema_additions.sql`: run this if you already applied the previous schema.

## Vercel deployment
1. Create a Vercel project from this repository and set the project Root Directory to the package root.
2. Add these server-side Environment Variables for Production (and Preview if you test there):
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_GROUP_ID` (numeric ID, typically starts with `-100` for a supergroup)
   - `TELEGRAM_GROUP_URL`
   - `TELEGRAM_WEBHOOK_SECRET` (random 32+ character string using letters/numbers/underscores/hyphens)
   - `QUALIFICATION_HOURS` = `24`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
3. Deploy. Check `https://YOUR-PROJECT.vercel.app/api/health` returns `{"ok":true,...}`.
4. Set the webhook after deployment. Replace placeholders and run this in a terminal (do not post the token publicly):

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://YOUR-PROJECT.vercel.app/api/webhook","secret_token":"<TELEGRAM_WEBHOOK_SECRET>","allowed_updates":["message","callback_query","chat_member"],"drop_pending_updates":false}'
```

Telegram should return `{"ok":true,"result":true,...}`. Check status with `getWebhookInfo` using the same private token. Stop the old Render polling bot before enabling webhook mode; Telegram does not allow polling and webhook delivery at the same time.

## Supabase migration
- If you have NOT run the old schema yet, run `supabase/schema.sql` in Supabase SQL Editor.
- If the existing tables are already there, run only `supabase/schema_additions.sql` to add `challenge_answer` and `challenge_expires_at`. Do not drop or recreate existing tables.

## Update the Render leaderboard API
Replace the existing Render API's `main.py` with the included `render-api-update/main.py` code, redeploy it, and add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_GROUP_ID` to that Render API service's environment variables. This is needed because Vercel functions cannot run a continuous five-minute sweeper; the API promotes matured referrals whenever the leaderboard is requested. The website's 30-minute leaderboard refresh will trigger this check.

## Telegram setup and caveats
- Add the bot as an administrator of the official group with permission to manage membership updates. Confirm `TELEGRAM_GROUP_ID` is the group ID, not your personal Telegram ID.
- The bot uses Telegram's `chat_member` updates to revoke referrals on leaving and reset qualification on rejoin.
- Webhook requests are checked against Telegram's `X-Telegram-Bot-Api-Secret-Token` header.
- Human arithmetic checks are a basic automation filter, not proof of one unique human.
- Before a real contest, test with a staging group and a second account. Confirm `/start`, arithmetic answer, join, Verify membership, `/link`, `/status`, leaving/rejoining, and leaderboard promotion after the qualification window.
- Never put secrets in GitHub, frontend JavaScript, or client-side Vercel variables. Keep `SUPABASE_SERVICE_ROLE_KEY` server-side only.
