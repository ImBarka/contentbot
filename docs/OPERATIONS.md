# Operations

Running ContentBot day to day: the schedule, reading logs, routine maintenance,
and tuning the output.

- [The daily schedule](#the-daily-schedule)
- [Command reference](#command-reference)
- [Reading a log](#reading-a-log)
- [Routine maintenance](#routine-maintenance)
- [Tuning the output](#tuning-the-output)
- [Disk usage](#disk-usage)
- [Quota budget](#quota-budget)

---

## The daily schedule

Task name: **`ContentBot Daily`**

| Setting | Value | Reason |
|---|---|---|
| Trigger | Daily, 11:15 | — |
| Random delay | 0–90 min | Actual run lands 11:15–12:45, so uploads don't hit a robotic fixed timestamp |
| Start when available | On | Laptop off during the window → runs at next boot instead of skipping the day |
| Execution time limit | 1 hour | Backstop against a hung run (notably a blocked OAuth browser prompt) |

The task runs [`scheduled_run.ps1`](../scheduled_run.ps1), which sets the
working directory, creates `logs/` if needed, prunes logs older than 30 days,
runs `main.py` with all output redirected to `logs/run_<timestamp>.log`, and
appends the exit code as the final line.

> `scheduled_run.ps1` invokes a **hard-coded** `python.exe` path. If you change
> Python installations or move machines, edit `$python` in that file.

---

## Command reference

```powershell
# --- Status ---------------------------------------------------------------
Get-ScheduledTaskInfo -TaskName "ContentBot Daily"
Get-ScheduledTask     -TaskName "ContentBot Daily" | Select-Object State

# --- Control --------------------------------------------------------------
Start-ScheduledTask   -TaskName "ContentBot Daily"   # run now
Stop-ScheduledTask    -TaskName "ContentBot Daily"   # kill a running task
Disable-ScheduledTask -TaskName "ContentBot Daily"   # pause (survives reboot)
Enable-ScheduledTask  -TaskName "ContentBot Daily"   # resume

# --- Logs -----------------------------------------------------------------
# Open the most recent log
notepad (Get-ChildItem logs\run_*.log | Sort-Object LastWriteTime -Desc |
         Select-Object -First 1).FullName

# Exit code of the last 10 runs, newest first
Get-ChildItem logs\run_*.log | Sort-Object LastWriteTime -Desc |
    Select-Object -First 10 |
    ForEach-Object { "{0}  {1}" -f $_.Name, (Get-Content $_ -Tail 1) }

# Every failed run still on disk
Get-ChildItem logs\run_*.log |
    Where-Object { (Get-Content $_ -Tail 1) -notmatch "Exit code: 0" }

# Titles published over the retained window
Select-String -Path logs\run_*.log -Pattern "Title:" |
    ForEach-Object { $_.Line.Trim() }

# --- Manual runs ----------------------------------------------------------
python main.py --no-upload    # generate only, nothing published
python main.py                # full run including upload
```

### `LastTaskResult` values

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Python exited non-zero — open the log |
| `267011` (`0x41303`) | Task has not run yet, or the scheduled instance was missed |
| `267009` (`0x41301`) | Currently running |
| `267014` (`0x41306`) | Terminated by the execution time limit |

---

## Reading a log

A healthy run has a recognisable shape. The emoji markers make it fast to scan.

```
=== ContentBot scheduled run started: 09/07/2026 13:22:15 ===
==================================================
       CONTENTBOT — Daily Shorts Generator
==================================================
🗑️  Pruned 3 file(s) older than 14d from output/
🤖 Generating title + script + description + tags with Gemini...
✅ Generated (space)
   Title:    Your Shadow Is Older Than The Sun
   Tags:     ['space', 'astronomy', 'shorts', ...]
   BG terms: ['deep space', 'starry night sky', 'nebula colorful', 'galaxy spiral']
--- SCRIPT --- ... --------------
🎙️ Generating audio with Edge TTS (voice: en-GB-SoniaNeural)...
✅ Audio saved: ...\audio_20260907_132215.mp3 (78 word events)
   Audio duration: 41.3s
   🎨 Subtitle design: Yellow Pop
✅ Subtitle saved: ...\subs_20260907_132215.ass (28 chunks, design: Yellow Pop)
   [1/6] deep space
🎥 Searching Pexels for 'deep space'...
   Downloading 1080p: deep_space_3129671.mp4
   ...
🎬 Assembling video (6 clips × 6.9s each) with FFmpeg...
   🎵 Music: Amber - VYEN.mp3 @ 10%
✅ Video assembled: ...\video_20260907_132215.mp4
📤 Uploading to YouTube...
✅ Uploaded! https://youtube.com/shorts/dQw4w9WgXcQ
=== Exit code: 0  (finished: 09/07/2026 13:24:41) ===
```

**What to check when scanning:**

| Line | Healthy | Suspicious |
|---|---|---|
| `(N word events)` | Roughly matches the script's word count | 0, or far below — TTS truncated |
| `Audio duration` | 25–55 s | Under 20 s (script too short) or over 60 s (not a Short) |
| `BG terms` | Concrete, visual, 1–3 words | Abstract nouns or exotic species names |
| `⚠️ No Pexels results` | Absent | Present — the keyword rules in the prompt are slipping |
| `Padding with local fallback` | Absent | Present — Pexels underdelivered |
| `⚠️ JSON parse failed` | Absent | Present — this video used degraded fallback metadata |
| Final line | `Exit code: 0` | Anything else |

Every artifact for a run shares the log's timestamp, so
`video_20260907_132215.mp4` is exactly what `run_20260907_132215.log` describes.

---

## Routine maintenance

### Weekly — OAuth renewal

While the Google Cloud consent screen is in **Testing** status, refresh tokens
expire after 7 days. Symptom: `invalid_grant` in the log, or a run that hangs
until the time limit kills it.

Fix: double-click [`renew_token.bat`](../renew_token.bat) → log in → *Advanced*
→ *Go to (app)* → **Allow**. Fifteen seconds, good for another week.

To stop doing this forever, publish the consent screen — see
[SETUP.md](SETUP.md#the-7-day-token-expiry).

### Weekly — glance at the logs

```powershell
Get-ChildItem logs\run_*.log | Sort-Object LastWriteTime -Desc |
    Select-Object -First 7 |
    ForEach-Object { "{0}  {1}" -f $_.Name, (Get-Content $_ -Tail 1) }
```

Seven `Exit code: 0` lines and you are done.

### Monthly — watch a few videos back

Automation drifts in ways logs cannot show: subtitles clipped by the Shorts UI,
footage that technically matched the keyword but reads as unrelated, music that
fights the voice. Actually watch three or four.

### Occasional — refresh the music pool

The same ten tracks across months of daily uploads becomes recognisable. Add a
few from the YouTube Audio Library now and then — see
[`music/README.md`](../music/README.md).

### Nothing to do — pruning

`output/` (14 d), `backgrounds/cache/` (60 d), and `logs/` (30 d) all prune
themselves at the start of each run.

---

## Tuning the output

All constants live in the `CONFIG` block of [`main.py`](../main.py). After any
change, verify with `python main.py --no-upload` before letting the scheduler
publish.

### Audio balance

```python
MUSIC_VOLUME = 0.10
```

| Value | Character |
|---|---|
| 0.08 | Barely present; texture only |
| 0.10 | **Default.** Clearly under the voice |
| 0.15 | Noticeable; safe for most tracks |
| 0.20 | Prominent; needs a track without busy mids |
| 0.25 | Starts competing with the voice |

### Cut rhythm

```python
SECONDS_PER_BG_CLIP = 7
```

Lower means more cuts and more visual energy — but also more Pexels searches
and downloads per run. Below about 4 the clip count starts to exceed the number
of distinct keywords, so footage begins repeating within a single video.

### Subtitle pacing

```python
SUBTITLE_CHUNK_WORDS    = 3      # max words on screen
SUBTITLE_CHUNK_DURATION = 0.9    # max seconds before forcing a new chunk
```

Two words at 0.7 s is aggressive and very high-energy. Four words at 1.2 s is
calmer and easier to read. Both limits apply — whichever is reached first ends
the chunk.

### Subtitle appearance

Add a preset to `SUBTITLE_DESIGNS`:

```python
{
    "name": "Orange Punch", "primary": "&H000080FF", "outline": "&H00000000",
    "outline_size": 9,      "emphasis": "&H00FFFFFF",
    "alignment": 2,         "margin_v": 650,
},
```

Two rules that are easy to get wrong:

- **Color bytes are `&H<AA><BB><GG><RR>`** — alpha, blue, green, red. Reversed
  from ordinary hex. `&H000080FF` is orange, not blue.
- **Keep `margin_v` at 600 or more** for alignment 2. The Shorts UI overlays
  the bottom of the frame; anything lower gets covered by the title and action
  buttons. Alignment 5 centres vertically and ignores `margin_v`.

### Content direction

Topic mix and writing style live in `generate_script()` — the `categories` list
and the prompt string. This is where you change what the channel is *about*, as
opposed to how it looks. See
[ARCHITECTURE.md](ARCHITECTURE.md#the-prompt-is-the-product) for why the prompt
is worded the way it is before rewriting it.

---

## Disk usage

| Folder | Typical steady state | Bounded by |
|---|---|---|
| `backgrounds/cache/` | 1–2 GB | 60-day prune |
| `output/` | 100–300 MB | 14-day prune |
| `music/` | 50–100 MB | Manual |
| `logs/` | < 1 MB | 30-day prune |

```powershell
Get-ChildItem output, logs, music, backgrounds -Recurse -File |
    Measure-Object Length -Sum |
    ForEach-Object { "{0:N1} MB" -f ($_.Sum / 1MB) }
```

To reclaim space immediately, `backgrounds/cache/` is always safe to empty —
the next run re-downloads whatever it needs.

---

## Quota budget

| Service | Free tier | Per run | Headroom |
|---|---|---|---|
| Gemini Flash | Generous daily quota | 1 request | Enormous |
| Edge TTS | Unmetered | 1 synthesis | — |
| Pexels | 200/hr, 20 000/mo | ~4–6 searches | ~100× |
| YouTube Data API | 10 000 units/day | 1 600 units | **6 uploads/day max** |

The YouTube quota is the only real constraint. At 1 600 units per upload, six
per day is the ceiling on a default project. Note that failed uploads still
consume quota — a run that dies partway through assembly does not, but one that
fails during the API call does.
