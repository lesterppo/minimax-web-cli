# MiniMax Web CLI

AI-agent-native CLI for [MiniMax Agent](https://agent.minimax.io) via browser-cookie auth. Zero-config, no API key needed.

**~12-18s latency** — uses Playwright browser automation (no Cloudflare on MiniMax).

## Quick Start

```bash
pip install -r requirements.txt
playwright install chromium

# Login to MiniMax in your browser first, then:
python minimax.py "Explain quantum computing"

# Agent-optimized (token-efficient JSON pointer)
python minimax.py -o /tmp/out.md "Your prompt"
# → {"f":"/tmp/out.md","s":450,"b":2}
```

## Features

- Text prompts via browser-cookie auth (no API key)
- Multi-turn conversations (`-c chat.json`)
- Model switching (`-m "MiniMax-M3 Thinking"`)
- Thinking toggle (`--no-thinking`)
- Token-efficient JSON pointer output
- Cross-platform (Linux, macOS, Windows, WSL)

## Usage

```bash
# Basic
python minimax.py "Hello"

# Multi-turn conversation
python minimax.py -c chat.json "My name is Peter"
python minimax.py -c chat.json "What's my name?"

# Model selection
python minimax.py -m "MiniMax-M3 Thinking" "Complex reasoning task"

# Disable thinking for faster response
python minimax.py --no-thinking "Quick question"

# Output to file (stdout gets JSON pointer)
python minimax.py -o /tmp/result.md "Write a poem"

# JSON output
python minimax.py --json "Hello"

# Login flow (if auth expires)
python minimax.py --login

# Pipe from stdin
echo "What is 2+2?" | python minimax.py
```

## Auth

Extracts cookies from your browser automatically:
- **macOS/Linux**: Firefox → Chrome → Edge
- **Windows/WSL**: Firefox (SQLite) → Chrome → Edge

Or set `MINIMAX_COOKIE` env var with your cookie header.

## Models

- `MiniMax-M3` (default)
- `MiniMax-M3 Thinking`

## How It Works

MiniMax uses Next.js with obfuscated API paths. This CLI launches headless Chromium, injects your browser cookies, types into the TipTap editor, and extracts the response via DOM evaluation.

No Cloudflare challenge on MiniMax = faster than similar tools (~12-18s vs ~16-25s).

## Dependencies

- `playwright` — browser automation
- `browser-cookie3` — cookie extraction from browser

## License

MIT
