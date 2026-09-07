# ContentBot

**A fully autonomous YouTube Shorts factory.** One scheduled run per day takes an
empty prompt and ends with a public Short on your channel — script, voiceover,
footage, karaoke subtitles, music, and upload included. No manual step in between.

```
Gemini ──▶ Edge TTS ──▶ Pexels ──▶ FFmpeg ──▶ YouTube Data API v3
script      voice +      stock      concat +     public Short
metadata    word timings footage    burn subs
```

| | |
|---|---|
| **Language** | Python 3.10+ (tested on 3.12) |
| **Entry point** | [`main.py`](main.py) — single-file pipeline, ~650 lines |
| **Scheduler** | Windows Task Scheduler → [`scheduled_run.ps1`](scheduled_run.ps1) |
| **Cost** | $0 — every service used sits inside a free tier |
| **Author** | ImBarka |
| **License** | All Rights Reserved — see [LICENSE](LICENSE) |

---

## Table of contents

- [How it works](#how-it-works)
- [Why these choices](#why-these-choices)
- [Quick start](#quick-start)
- [Daily operation](#daily-operation)
- [Configuration](#configuration)
- [Project layout](#project-layout)
- [Documentation](#documentation)
- [Cost and quota](#cost-and-quota)

---

## How it works

Seven steps, all inside `main()`. Every run is independent — there is no
database and no state carried between runs.

**0 · Housekeeping.** Prune `output/` older than 14 days and the Pexels cache
older than 60 days, so the folder never grows without bound.

**1 · Script generation.** A random topic is drawn from twelve categories
(science, psychology, history, philosophy, nature, space, human body, ancient
civilizations, mathematics, technology, animals, language). One Gemini call in
JSON mode returns everything at once: `title`, `script`, `description`, `tags`,
and `background_keywords`. The prompt is heavily constrained — see
[Why these choices](#why-these-choices).

**2 · Voiceover.** Edge TTS renders the script to MP3. Crucially it is asked for
`WordBoundary` events, so the same call that produces audio also yields
word-level timings — no forced-alignment pass needed. Six voices (US and GB,
male and female) are tried in random order; if Microsoft has silently retired
one, `NoAudioReceived` triggers a fall-through to the next voice.

**3 · Duration probe.** `ffprobe` reads the real audio length, which drives both
subtitle timing and the number of background clips.

**4 · Subtitles.** Word events are grouped into chunks of at most 3 words or
0.9 seconds, then written as an ASS file. Each chunk holds until the next one
starts, producing the punchy one-phrase-at-a-time look. Digits are recolored
with an emphasis color so numbers pop. One of five design presets is chosen at
random per video.

**5 · Footage.** `round(duration / 7)` clips are fetched — one Pexels search per
keyword, cycling the keyword list if more clips are needed. Video IDs already
used in this Short are tracked so no clip repeats. Downloads land in
`backgrounds/cache/` and are reused on later runs. If Pexels comes up short, any
local `.mp4` in `backgrounds/` pads the gap.

**6 · Assembly.** A single FFmpeg invocation does all of it: trim and loop each
clip to its segment length, scale-and-crop to 1080×1920, concat, burn the ASS
subtitles, and mix the voice with a randomly chosen music track at 10% volume.

**7 · Upload.** The YouTube Data API uploads the file as a public Short with
`#Shorts` appended to the title and a hashtag line built from the first six
tags. `--no-upload` stops after step 6 and leaves the file in `output/`.

---

## Why these choices

The non-obvious decisions, and the failures that motivated them.

**The hook must be the first sentence.** Retention on Shorts is decided in the
first two seconds. The Gemini prompt therefore does not ask for "an engaging
script" — it dictates structure and supplies explicit counter-examples:

> ❌ `"Look up at the night sky. You see thousands of stars…"`
> ✅ `"There are more trees on Earth than stars in our galaxy."`

Setup sentences ("Look at…", "Imagine…", "Grab a…") are banned outright, because
without the ban the model reliably opens with one.

**Background keywords are constrained to common stock concepts.** Gemini's
instinct is to name the subject precisely — `mantis shrimp`, `axolotl`,
`narwhal`. Pexels has almost no footage for those, so clips came back empty or
irrelevant. The prompt now forces broad categories (`colorful shrimp`,
`small aquatic creature`, `whale swimming`) and bans abstract nouns
(`infinity`, `wisdom`, `time`) which return meaningless B-roll.

**No orientation filter on the Pexels search.** Filtering for portrait-only
excludes roughly 90% of the library. Landscape clips are fetched instead and
cropped to 1080×1920 in FFmpeg, which is free and yields far better matches.

**Word timings come from the TTS engine, not an aligner.** Edge TTS emits
`WordBoundary` events alongside the audio stream. Running Whisper or another
forced aligner would mean a second model on the machine for data the first one
already gave away — see the compute note below.

**Everything is one FFmpeg call.** Intermediate renders would mean re-encoding
the video two or three times. One `filter_complex` graph encodes exactly once.

**Deliberately light on local compute.** Cloud TTS instead of a local model,
stock footage instead of generated video, one encode instead of several. The
pipeline is designed to run on a modest laptop without pinning the CPU.

---

## Quick start

Full walkthrough in **[docs/SETUP.md](docs/SETUP.md)**. The short version:

```powershell
# 1. Dependencies
pip install -r requirements.txt

# 2. FFmpeg + ffprobe must be on PATH
ffmpeg -version

# 3. API keys
copy .env.example .env      # then fill in GEMINI_API_KEY and PEXELS_API_KEY

# 4. YouTube OAuth
#    Google Cloud Console → enable YouTube Data API v3 → OAuth Client ID
#    (Desktop app) → download JSON → save as client_secrets.json

# 5. Background music (optional but recommended)
#    Drop 10-15 royalty-free tracks into music/ — see music/README.md

# 6. Dry run — generates the video, skips the upload
python main.py --no-upload
```

The first run that uploads will open a browser for OAuth approval and write
`token.json`. Every run after that is silent.

---

## Daily operation

A Windows scheduled task named `ContentBot Daily` fires at **11:15** with a
random delay of 0–90 minutes, so uploads do not land at a robotic fixed time.
If the laptop is off during the window, the catch-up setting runs it at next
boot. Each run writes `logs/run_<timestamp>.log`.

```powershell
Get-ScheduledTaskInfo -TaskName "ContentBot Daily"   # status + last result
Start-ScheduledTask   -TaskName "ContentBot Daily"   # run now
Disable-ScheduledTask -TaskName "ContentBot Daily"   # pause
```

**Weekly chore.** While the Google Cloud project sits in *Testing* status, the
OAuth refresh token expires every 7 days. When a log shows `invalid_grant`,
double-click [`renew_token.bat`](renew_token.bat), approve in the browser, and
you are good for another week. Publishing the OAuth consent screen removes this
chore permanently — details in [docs/OPERATIONS.md](docs/OPERATIONS.md).

---

## Configuration

All tunables are constants in the `CONFIG` block near the top of
[`main.py`](main.py).

| Constant | Default | Effect |
|---|---|---|
| `MUSIC_VOLUME` | `0.10` | Music level relative to voice. Useful range 0.08–0.25. |
| `SECONDS_PER_BG_CLIP` | `7` | Seconds of audio per background clip. Lower = faster cuts. |
| `TTS_VOICES` | 6 voices | Pool rotated per run; a failing voice falls through to the next. |
| `SUBTITLE_DESIGNS` | 5 presets | Colors, outline weight, and screen position, chosen at random. |
| `SUBTITLE_CHUNK_WORDS` | `3` | Max words shown on screen at once. |
| `SUBTITLE_CHUNK_DURATION` | `0.9` | Max seconds a chunk stays before splitting. |
| `SUBTITLE_FONT_SIZE` | `90` | Point size at 1080×1920. |
| `VIDEO_WIDTH` / `VIDEO_HEIGHT` | `1080` / `1920` | Output resolution. |
| `PRUNE_DAYS_OUTPUT` | `14` | Age at which generated media is deleted. |
| `PRUNE_DAYS_CACHE` | `60` | Age at which cached Pexels clips are deleted. |

Content itself — topic list, tone, hook rules, keyword rules — lives in the
prompt string inside `generate_script()`. That function is where you go to
change what the channel is *about*.

> **Note:** [`scheduled_run.ps1`](scheduled_run.ps1) and
> [`renew_token.bat`](renew_token.bat) contain a hard-coded absolute path to
> `python.exe`. Update it if you move machines or change your Python install.

---

## Project layout

```
contentbot/
├── main.py                      Pipeline — all seven steps
├── refresh_token.py             Force OAuth re-auth (deletes token.json first)
├── renew_token.bat              One-click wrapper around refresh_token.py
├── scheduled_run.ps1            Task Scheduler wrapper; logs + prunes logs
├── requirements.txt
│
├── .env                         Secrets — gitignored
├── .env.example                 Template, committed
├── client_secrets.json          OAuth client — gitignored
├── client_secrets.example.json  Template, committed
├── token.json                   OAuth token cache — gitignored, auto-created
│
├── docs/
│   ├── SETUP.md                 First-time installation, start to finish
│   ├── ARCHITECTURE.md          Deep dive: every stage, data shapes, formats
│   ├── OPERATIONS.md            Scheduling, logs, maintenance, tuning
│   └── TROUBLESHOOTING.md       Every failure seen so far, with fixes
│
├── music/                       Your tracks — gitignored, README committed
├── backgrounds/cache/           Pexels downloads — gitignored, auto-pruned
├── output/                      Generated media — gitignored, auto-pruned
└── logs/                        Per-run logs — gitignored, auto-pruned
```

---

## Documentation

| Document | Read it when |
|---|---|
| **[docs/SETUP.md](docs/SETUP.md)** | Installing on a fresh machine |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Changing the pipeline, or debugging *why* output looks wrong |
| **[docs/OPERATIONS.md](docs/OPERATIONS.md)** | Running it day to day; reading logs; tuning look and feel |
| **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** | A run failed and you want the fix |
| **[music/README.md](music/README.md)** | Sourcing background tracks |

---

## Cost and quota

| Service | Free tier | Consumption per run |
|---|---|---|
| Gemini Flash | Generous daily free quota | 1 request |
| Edge TTS | Free, unofficial client | 1 synthesis |
| Pexels | 200 req/hour, 20 000 req/month | ~4–6 searches + downloads |
| YouTube Data API | 10 000 units/day | 1 600 units per upload |

The YouTube quota is the real ceiling: an upload costs 1 600 units, so **6
uploads per day** is the hard limit on a default project. One per day leaves
plenty of headroom.
