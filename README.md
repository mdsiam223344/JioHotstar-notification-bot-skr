# JioHotstar Telegram Notification Bot — Render

## Files
- `hotstar_bot.py`: bot code
- `requirements.txt`: Python dependencies
- `render.yaml`: Render Background Worker configuration with a 1 GB persistent disk

## Deploy
1. Upload these files to a GitHub repository.
2. In Render, choose **New + → Blueprint** and connect that repository.
3. Render will read `render.yaml`. If prompted, create the service and disk.
4. Open the service's **Environment** tab and set:
   - `BOT_TOKEN`: token from Telegram's @BotFather
   - `ADMIN_ID`: your numeric Telegram user ID
5. Deploy/redeploy and check the service logs for `Hotstar Telegram bot starting`.
6. Open the bot in Telegram and send `/start`.

## Important
- Use a **Background Worker**, not a Web Service: this bot uses Telegram long polling and does not serve HTTP requests.
- The `render.yaml` includes a persistent disk mounted at `/var/data`, so JSON data survives normal redeploys/restarts while the disk remains attached.
- Persistent disks may require a paid Render instance/plan and can affect free-tier eligibility. Check Render's current plan/pricing before deploying.
- The Hotstar API endpoints used by the script are unofficial/undocumented and may stop working or return incomplete results. A successful deployment does not guarantee new-episode detection.
- `/zip` currently looks up India PIN codes only.
- Do not share your bot token publicly. If exposed, regenerate it through @BotFather.
