# 🖥️ CarterPCs Monitor

A small, fun self-hosted dashboard that tracks **CarterPCs** across YouTube, TikTok and Instagram, and pings your **Discord** or **Telegram** when something new goes up. It's built to run on a Raspberry Pi.

| Platform | Account |
|---|---|
| ▶️ YouTube | [@actuallycarterpcs](https://www.youtube.com/@actuallycarterpcs) |
| 🎵 TikTok | [@carterpcs](https://www.tiktok.com/@carterpcs) |
| 📸 Instagram | [@carterpcs_](https://www.instagram.com/carterpcs_/) |

## Features

- **Tabs** for an overview, each platform, and settings
- Follower counts with a little growth chart, plus the latest posts with thumbnails
- **Discord webhooks** and **Telegram bots**, with as many destinations as you want
- **Per-channel routing:** send only YouTube to `#uploads`, everything to `#carter-feed`, TikTok to a Telegram group… whatever you like
- **Auto-updates** from GitHub
- No API keys, no accounts, no database. It's just Python, Flask and a JSON file

## Install (one line)

On a Raspberry Pi running Raspberry Pi OS (or any Debian/Ubuntu machine):

```bash
curl -fsSL https://raw.githubusercontent.com/ZipperedJon/carterpcs-monitor/main/install.sh | bash
```

Then open `http://<your-pi-ip>:8080` in a browser on the same network. The installer prints the exact address.

### What the installer does

1. Installs `git`, `python3` and `python3-venv` with `apt` (asks for your sudo password)
2. Clones this repo into `~/carterpcs-monitor`. If it's already there, it updates it instead
3. Creates a Python virtual environment and installs Flask and Requests
4. Creates the `carterpcs-monitor` systemd service so the app starts on boot and restarts if it crashes
5. Starts the app and prints the address to open

Running it again is safe. It updates the existing install and keeps your settings.

You can [read the script](install.sh) before running it. You can also change the defaults with environment variables:

| Variable | Default | What it does |
|---|---|---|
| `CARTERPCS_PORT` | `8080` | Web UI port |
| `CARTERPCS_DIR` | `~/carterpcs-monitor` | Install folder |
| `CARTERPCS_BRANCH` | `main` | Git branch to install and auto-update from |
| `CARTERPCS_REPO` | this repo | Git URL (handy if you fork it) |

```bash
curl -fsSL https://raw.githubusercontent.com/ZipperedJon/carterpcs-monitor/main/install.sh | CARTERPCS_PORT=9000 bash
```

### Which Pi?

Any Raspberry Pi that runs Linux works: **Pi Zero 2 W**, 3, 4 or 5. The app is lightweight and uses very little RAM.

> ⚠️ The **Raspberry Pi Pico** (and Pico W) is a microcontroller, not a Linux computer, so it can't run this.

## Setting up notifications

Open the **⚙️ Settings** tab → **Notifications**, add a destination, tick the platforms it should receive, hit **Send test**, then **Save settings**.

**Discord:** Server channel → ⚙️ Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL. You can optionally add a mention like `@everyone` or `<@&ROLE_ID>`.

**Telegram:**
1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token.
2. Add the bot to your group or channel. Make it an admin if it's a channel.
3. Chat ID: use `@yourchannel` for a public channel. Otherwise send a message in the chat and open `https://api.telegram.org/bot<TOKEN>/getUpdates` to find `chat.id` (groups start with `-100…`).

Examples:

| Destination | Platforms |
|---|---|
| Discord `#youtube` | ▶️ YouTube |
| Discord `#shortform` | 🎵 TikTok, 📸 Instagram |
| Telegram "Carter Alerts" | everything |

On the very first check the app just records what already exists. You'll only be notified about posts that appear **after** that.

## How each platform is tracked

None of these platforms offer a free, login-free API, so the app uses public pages:

| Platform | What you get | How |
|---|---|---|
| YouTube | Every new video/Short with title, thumbnail and link, plus subscribers | Official RSS feed |
| TikTok | Every new video with caption, cover and direct link, plus followers and likes | TikTok's public creator-embed widget |
| Instagram | New posts/Reels with caption, thumbnail and direct link, plus followers | Post count from the public profile preview; Instagram's web API is only called when the count goes up |

Instagram rate-limits hard. If it keeps blocking the post lookup for about 40 minutes after a new post, you still get an alert, but it links to the profile instead of the post.

Each platform also has an optional **Custom RSS feed URL** setting. If you run [RSSHub](https://docs.rsshub.app) (or use another feed service), paste a feed URL there to use it as that platform's post source instead.

Social sites change their pages and rate-limit often. If one breaks, it shows a ⚠ on the dashboard while the others keep working, and the fix usually arrives through auto-update.

## Auto-update

When **Auto-update from GitHub** is on (default), the app checks the repo every 60 minutes. When there's a new commit, it pulls it, installs any new requirements and restarts itself. You can also hit **Update now** in Settings. Your settings live in `data/`, which git ignores, so updates never touch them.

## Handy commands

```bash
journalctl -u carterpcs-monitor -f          # live logs
sudo systemctl restart carterpcs-monitor    # restart
bash ~/carterpcs-monitor/uninstall.sh       # remove everything
```

## Run it without installing (dev)

```bash
pip install -r requirements.txt
python app.py                # http://localhost:8080  (set PORT=xxxx to change)
```

## Security note

The dashboard has no login and is meant for your home network. Anyone who can reach it can see your webhook URLs and bot token in Settings, so don't port-forward it to the internet.

---

*Fan-made project, not affiliated with CarterPCs.*
