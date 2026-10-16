# USP bot

The Discord review bot for the USP projects. It posts a card for every pull request in a voting channel, with an
automatic risk check and a plain-English AI summary from a free model. It counts votes, takes `!usp` commands and
posts decisions. The two owners keep the final say, and the bot never merges anything.

**This repo contains no game code or data.** It's public so its GitHub Actions minutes are free.

## What runs where

- **Here:** the bot's code (`bot/`), the 15-minute check (`vote-counter`), and two manual checks (`bot-selftest` for
  the AI model, `bot-live-check` for the online connection).
- **In each project repo (USP, USP-tools):** a small `review-card` workflow that fetches `bot/` from this repo and
  posts the card for that repo's own pull requests.
- **On an owner's PC (optional):** `bot/usp_live.py` keeps the bot online so it answers instantly.

Setup, commands and rules are in [bot/README.md](bot/README.md). In Discord, the pinned help card lists every command.

## Secrets

`DISCORD_BOT_TOKEN`, `DISCORD_OWNER_IDS` and `DISCORD_CHANNEL_IDS`, in this repo and in every repo that posts cards.
Optional: `GEMINI_API_KEY` for Gemini models, and `DISCORD_WEBHOOK_OTHER` for push notices in Discord.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Every commit must carry the contributor agreement line.

## License

[GPL-3.0-or-later](LICENSE). Contributors accept the [contributor agreement](CONTRIBUTING.md#contributor-agreement).
