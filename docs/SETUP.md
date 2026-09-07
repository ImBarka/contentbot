# Setup

Start-to-finish installation on a fresh machine. Budget about 30 minutes, most
of it waiting on Google Cloud Console.

- [Prerequisites](#prerequisites)
- [1 · Python dependencies](#1--python-dependencies)
- [2 · FFmpeg](#2--ffmpeg)
- [3 · API keys](#3--api-keys)
- [4 · YouTube OAuth](#4--youtube-oauth)
- [5 · Background music](#5--background-music)
- [6 · First run](#6--first-run)
- [7 · Daily scheduling](#7--daily-scheduling)
- [Verification checklist](#verification-checklist)

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | Tested on 3.12. Earlier versions lack features used by the deps. |
| FFmpeg **and** ffprobe | Both binaries, both on `PATH`. |
| A Google account | For Gemini, Google Cloud, and the target YouTube channel. |
| Windows | Only for the scheduled task. The pipeline itself is cross-platform. |
| ~2 GB free disk | Pexels cache grows to roughly this before the 60-day prune kicks in. |

---

## 1 · Python dependencies

```powershell
pip install -r requirements.txt
```

Installs `google-generativeai`, `edge-tts`, `google-auth-oauthlib`,
`google-api-python-client`, `python-dotenv`, and `requests`.

A virtualenv works fine, but note that [`scheduled_run.ps1`](../scheduled_run.ps1)
invokes a hard-coded `python.exe` path. If you use a venv, point that variable
at the venv's interpreter.

---

## 2 · FFmpeg

Both `ffmpeg` and `ffprobe` are called as bare commands, so both must resolve
on `PATH`.

```powershell
ffmpeg -version
ffprobe -version
```

If either is missing on Windows:

```powershell
winget install Gyan.FFmpeg
```

Then **open a new terminal** — `PATH` changes do not apply to already-running
shells. If you install manually instead, add the `bin` folder to your user
`PATH` environment variable.

---

## 3 · API keys

Copy the template and fill it in:

```powershell
copy .env.example .env
```

```ini
GEMINI_API_KEY=AIzaSy...
PEXELS_API_KEY=...
```

Format is strict — `KEY=value`, no spaces around `=`, no surrounding quotes.

**Gemini key.** Go to [aistudio.google.com](https://aistudio.google.com) →
*Get API Key* → *Create API key*. The free tier is comfortably above one
request per day.

**Pexels key.** Register at [pexels.com/api](https://www.pexels.com/api/). The
key appears on your dashboard immediately. Free tier: 200 requests/hour and
20 000/month — a run uses roughly 4–6.

`.env` is gitignored. It must never be committed.

---

## 4 · YouTube OAuth

This is the fiddly part. Work through it in order.

1. Open [console.cloud.google.com](https://console.cloud.google.com) and create
   a new project.
2. **APIs & Services → Library** → search *YouTube Data API v3* → **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User type: **External**
   - Fill in app name and support email
   - Scopes: you can leave this empty; the script requests
     `youtube.upload` at runtime
   - **Test users**: add the Google account that owns the target channel.
     Skipping this causes `access_denied` at login.
4. **APIs & Services → Credentials** → *Create Credentials* →
   **OAuth client ID** → Application type: **Desktop app** → Create → download
   the JSON.
5. Rename the file to `client_secrets.json` and place it in the project root
   next to `main.py`. Compare against
   [`client_secrets.example.json`](../client_secrets.example.json) if you are
   unsure whether you downloaded the right thing — the top-level key must be
   `"installed"`, not `"web"`.

### The 7-day token expiry

While the consent screen sits in **Testing** status, Google expires refresh
tokens after 7 days. That is the single most common cause of a failed
scheduled run.

Two options:

- **Live with it.** Run [`renew_token.bat`](../renew_token.bat) weekly. Takes
  about 15 seconds.
- **Publish the consent screen.** OAuth consent screen → **Publish app**. Since
  `youtube.upload` is a sensitive scope you will see a warning about
  verification, but for a personal-use app with your own account as the only
  user, publishing still lifts the 7-day expiry. Unverified apps show a
  "Google hasn't verified this app" interstitial at login — click *Advanced* →
  *Go to (app)* to proceed.

---

## 5 · Background music

Optional. With an empty `music/` folder the pipeline runs normally and produces
videos with voice only.

Drop 10–15 royalty-free `.mp3`, `.m4a`, or `.wav` files into `music/`. One is
picked at random per video and mixed at 10% of voice volume.

Sources and genre recommendations: [`music/README.md`](../music/README.md).

---

## 6 · First run

Always dry-run first:

```powershell
python main.py --no-upload
```

This exercises Gemini, Edge TTS, Pexels, and FFmpeg, then stops before upload
and prints the path to the finished MP4 in `output/`. **Watch it back before
you let anything upload automatically.**

When you are happy with the result, run the real thing:

```powershell
python main.py
```

A browser opens for OAuth approval. Log in with the channel's account, click
through the unverified-app warning, and approve upload permission. `token.json`
is written and subsequent runs are silent.

---

## 7 · Daily scheduling

Register the Windows task. Run this in an **elevated** PowerShell, adjusting
the path if the project does not live at `e:\contentbot`:

```powershell
$action  = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument '-NoProfile -ExecutionPolicy Bypass -File "e:\contentbot\scheduled_run.ps1"'

$trigger = New-ScheduledTaskTrigger -Daily -At 11:15
$trigger.RandomDelay = "PT90M"      # spread the actual run over 11:15-12:45

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName "ContentBot Daily" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Generates and uploads one YouTube Short per day."
```

`-StartWhenAvailable` is what gives you catch-up behaviour: if the laptop is
off during the 11:15–12:45 window, the task fires shortly after next boot
instead of silently skipping the day.

Confirm it registered, then force one run to prove the wiring:

```powershell
Get-ScheduledTaskInfo -TaskName "ContentBot Daily"
Start-ScheduledTask   -TaskName "ContentBot Daily"
```

Day-to-day management is covered in [OPERATIONS.md](OPERATIONS.md).

---

## Verification checklist

Everything below should be true before you consider setup finished.

- [ ] `ffmpeg -version` and `ffprobe -version` both succeed
- [ ] `pip show google-generativeai edge-tts` shows both installed
- [ ] `.env` exists with both keys, no quotes, no stray spaces
- [ ] `client_secrets.json` exists and its top-level key is `"installed"`
- [ ] The channel's Google account is listed as a Test user (if unpublished)
- [ ] `python main.py --no-upload` produces a watchable MP4 in `output/`
- [ ] Subtitles are visible, in sync, and not clipped off screen
- [ ] Background music is audible but does not compete with the voice
- [ ] A real run uploaded successfully and printed a `youtube.com/shorts/...` URL
- [ ] `Get-ScheduledTaskInfo -TaskName "ContentBot Daily"` returns a task
- [ ] `git status` shows no secret files staged — `.env`, `client_secrets.json`,
      and `token.json` must all be ignored
