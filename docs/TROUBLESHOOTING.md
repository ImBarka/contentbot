# Troubleshooting

Every failure encountered so far, with the fix. Start by opening the log for
the failed run:

```powershell
notepad (Get-ChildItem logs\run_*.log | Sort-Object LastWriteTime -Desc |
         Select-Object -First 1).FullName
```

The last line is always `=== Exit code: N ===`. Anything other than `0` means
something below applies.

- [Quick triage](#quick-triage)
- [Setup and environment](#setup-and-environment)
- [Gemini](#gemini)
- [Edge TTS](#edge-tts)
- [Pexels](#pexels)
- [FFmpeg](#ffmpeg)
- [YouTube upload](#youtube-upload)
- [Scheduled task](#scheduled-task)
- [Output quality](#output-quality)

---

## Quick triage

| Symptom in log | Jump to |
|---|---|
| `GEMINI_API_KEY not set` | [Keys not loading](#api-key-not-picked-up) |
| `FFmpeg not found` / `ffprobe` not recognised | [FFmpeg not on PATH](#ffmpeg-not-found) |
| `Address lookup failed` / `getaddrinfo` / `WSA 11001` | [No network at run time](#no-network-at-run-time) |
| `RetryError: Timeout of 600.0s exceeded` | [No network at run time](#no-network-at-run-time) |
| `429` / `RESOURCE_EXHAUSTED` | [Rate limited](#429--resource_exhausted) |
| `JSON parse failed` | [Malformed model output](#json-parse-failed) |
| `All TTS voices failed` | [Edge TTS](#all-tts-voices-failed) |
| `No Pexels results for '...'` | [Weak keywords](#no-pexels-results-for-x) |
| `No background videos available` | [Nothing to render](#no-background-videos-available) |
| `FFmpeg error:` | [FFmpeg](#ffmpeg) |
| `invalid_grant` | [Expired token](#invalid_grant--token-has-been-expired-or-revoked) |
| `quotaExceeded` | [YouTube quota](#quotaexceeded) |
| Run hangs until killed | [Task hangs forever](#task-hangs-until-the-time-limit) |
| `LastTaskResult = 267011` | [Missed window](#lasttaskresult--267011) |

---

## Setup and environment

### API key not picked up

```
❌ GEMINI_API_KEY not set in .env
```

`.env` must sit next to `main.py` — it is loaded from the script's own
directory, so the working directory does not matter. Check the file's format:

```ini
GEMINI_API_KEY=AIzaSy...        ✅
GEMINI_API_KEY = AIzaSy...      ❌ spaces around =
GEMINI_API_KEY="AIzaSy..."      ❌ quotes become part of the value
```

Also confirm the file is really named `.env` and not `.env.txt` — Windows
Explorer hides known extensions by default:

```powershell
Get-ChildItem e:\contentbot\.env* -Force | Select-Object Name, Length
```

### FFmpeg not found

Both `ffmpeg` and `ffprobe` are invoked as bare commands and both must resolve.

```powershell
ffmpeg  -version
ffprobe -version
```

If either fails:

```powershell
winget install Gyan.FFmpeg
```

Then **open a new terminal** — `PATH` changes do not reach already-running
shells. If it works in your terminal but fails under Task Scheduler, the task
is running as a different user with a different `PATH`; use a system-wide
install or put the absolute path in `scheduled_run.ps1`.

### No network at run time

```
google.api_core.exceptions.RetryError: Timeout of 600.0s exceeded,
last exception: 503 errors resolving generativelanguage.googleapis.com:443:
[Address lookup failed ... WSA Error (No such host is known. -- 11001)]
```

Not a bug — DNS could not resolve Google's endpoint. This happens when the
scheduled task fires before the network is up, which is common with
`-StartWhenAvailable` on a laptop that just booted, or on a machine that
auto-connects to Wi-Fi a few seconds after login.

The `google-api-core` client retries for a full 600 seconds before giving up,
so a run failing this way takes 10 minutes to die.

**Immediate fix** — confirm connectivity, then re-run:

```powershell
Test-NetConnection generativelanguage.googleapis.com -Port 443
Start-ScheduledTask -TaskName "ContentBot Daily"
```

**Prevent it** — add a network-availability condition to the task so it waits
for a connection instead of racing it:

```powershell
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable `
        -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Set-ScheduledTask -TaskName "ContentBot Daily" -Settings $s
```

Combined with the existing random delay, this makes a boot-time race unlikely.
If it still recurs, add a 60-second delay at the top of `scheduled_run.ps1`
before invoking Python.

---

## Gemini

### `429` / `RESOURCE_EXHAUSTED`

Free-tier rate limit. With one run per day this should never appear — if it
does, something is triggering the task repeatedly. Check for duplicate task
registrations:

```powershell
Get-ScheduledTask | Where-Object TaskName -like "*ContentBot*"
```

Otherwise wait for the quota window to reset and re-run.

### `JSON parse failed`

```
⚠️ JSON parse failed (Expecting value: line 1 column 1), using fallback metadata.
```

The run **does not fail** — it falls back to a generic title, uses the raw
response as the script, and sets background keywords to the bare topic name.
The video publishes, but it is a weak one.

One occurrence is noise. Several in a week means the prompt or the model needs
attention. To inspect what actually came back, add a debug print in
`generate_script()`:

```python
except (json.JSONDecodeError, KeyError, TypeError) as e:
    print(f"RAW RESPONSE:\n{response.text[:1000]}")
```

Common causes: the model wrapped the JSON in a markdown fence (should not
happen with `response_mime_type` set — verify it is still being passed), or a
`KeyError` because a required field was omitted.

### Model not found / deprecated

`gemini-flash-latest` is an alias that follows Google's current Flash model. If
Google retires the alias, pin an explicit version in `generate_script()` and
check the [model list](https://ai.google.dev/gemini-api/docs/models) for what is
current.

---

## Edge TTS

### `All TTS voices failed`

```
⚠️ Voice en-US-AriaNeural exhausted retries — trying next voice
...
❌ All TTS voices failed. Edge TTS service may be down.
```

Every voice in the pool was tried, each with 3 retries. Two possible causes:

**The service is down.** `edge-tts` is an unofficial client against a Microsoft
endpoint. Test directly:

```powershell
edge-tts --text "hello world" --write-media test.mp3
```

If that fails too, wait it out and re-run later.

**The voice list is stale.** Microsoft retires voices without notice — Davis and
Andrew were removed in June 2026 and are commented out in `TTS_VOICES` for
exactly this reason. Check what still exists:

```powershell
edge-tts --list-voices | Select-String "en-US|en-GB"
```

Remove dead entries from `TTS_VOICES` in `main.py` and add live replacements.

### Very few word events

```
✅ Audio saved: ...\audio_20260907_132215.mp3 (4 word events)
```

Far fewer events than words in the script means the stream was truncated. The
audio will be short and the subtitles will end early. Re-run — this is usually
transient. If it persists, the script may contain characters the engine chokes
on; check the `--- SCRIPT ---` block in the log for stage directions, emoji, or
markup that the prompt was supposed to exclude.

### Subtitles drift out of sync

Timings come directly from the TTS engine and cannot drift on their own. If
subtitles are offset, the `.ass` file and the `.mp3` are from different runs —
check that both filenames carry the same timestamp.

---

## Pexels

### `No Pexels results for 'x'`

```
⚠️ No Pexels results for 'mantis shrimp'
```

Gemini produced a keyword too specific for stock footage. Occasional misses are
tolerable — the clip count still gets filled by cycling the remaining keywords.

If it happens most runs, the keyword rules in the prompt are being ignored.
Reinforce the `background_keywords` section of `generate_script()` with more
❌/✅ examples in the same style as the existing ones. The rules that matter:
broad categories over species names, 1–3 words, no abstract nouns, no bare
topic names. See
[ARCHITECTURE.md](ARCHITECTURE.md#stock-footage-realism).

### `No background videos available`

```
❌ No background videos available (Pexels failed and folder empty).
```

Hard exit — Pexels returned nothing at all *and* there are no local fallback
clips. Check in order:

1. `PEXELS_API_KEY` is set and is not the literal `YOUR_PEXELS_API_KEY`
2. Network is up (see [No network at run time](#no-network-at-run-time))
3. The key is still valid — test it:

```powershell
curl.exe -H "Authorization: YOUR_KEY" "https://api.pexels.com/videos/search?query=ocean&per_page=1"
```

As insurance, drop 5–10 generic clips (abstract, nature, space) directly into
`backgrounds/` — not `backgrounds/cache/`. They are used only when Pexels
underdelivers, and they turn a hard failure into a slightly generic video.

### Downloads are very slow

Each clip is roughly 5–20 MB and up to six are fetched per run. The cache means
this cost falls over time as keywords repeat. If a run stalls, the download has
a 120-second timeout and will move on to the next candidate.

### Footage repeats within one video

`used_ids` prevents duplicates, but it only holds IDs whose filenames parse as
`<keyword>_<id>.mp4`. Local fallback clips are chosen with `random.choice` and
are not deduplicated, so repeats there are expected when the fallback folder is
small.

---

## FFmpeg

### Reading the error

```
❌ FFmpeg error: <last 2000 chars of stderr>
```

FFmpeg's actual error is always at the end of its output, which is why the tail
is printed. Read the last few lines first.

### `No such filter: 'ass'`

Your FFmpeg build lacks libass. The `winget install Gyan.FFmpeg` build includes
it. Verify:

```powershell
ffmpeg -filters | Select-String "ass"
```

If you built or downloaded FFmpeg yourself, get a full build rather than an
essentials/minimal one.

### `Unable to parse option value` on the subtitle path

The `ass=` filter is deliberately given a **bare filename**, with FFmpeg's
working directory set to the subtitle's folder. Windows absolute paths contain
`:` and `\`, both of which are delimiters in FFmpeg filter syntax.

If you changed `assemble_video()` to pass a full path, revert it. Setting `cwd`
is the fix, not a workaround.

### Concat fails on mismatched inputs

Every clip is normalised with `scale`, `crop`, and `setsar=1` before concat
specifically to prevent this. If you edited the filter chain, confirm `setsar=1`
is still present on every branch — differing sample aspect ratios are the usual
culprit.

### Video is shorter than the audio

Check `-stream_loop -1` is still applied to every video input. Pexels clips are
frequently shorter than their allotted segment; without the loop, the segment
ends early.

### Music drowns the voice

`normalize=0` on the `amix` filter is load-bearing. FFmpeg's default
normalisation halves the voice level as soon as a second input joins, which
makes `MUSIC_VOLUME` meaningless. If you removed it, put it back — then tune
`MUSIC_VOLUME` itself (see
[OPERATIONS.md](OPERATIONS.md#audio-balance)).

---

## YouTube upload

### `invalid_grant` / `Token has been expired or revoked`

The most common failure. While the Google Cloud consent screen is in
**Testing** status, refresh tokens expire after **7 days**.

**Fix:** double-click [`renew_token.bat`](../renew_token.bat) → log in →
*Advanced* → *Go to (app)* → **Allow**.

**Fix permanently:** publish the consent screen — Google Cloud Console → OAuth
consent screen → **Publish app**. Unverified apps still show a warning
interstitial at login, but the 7-day expiry is lifted. See
[SETUP.md](SETUP.md#the-7-day-token-expiry).

### `access_denied` during authorisation

The account you logged in with is not on the Test users list while the app is
unpublished. Google Cloud Console → OAuth consent screen → **Test users** →
add it.

### `quotaExceeded`

YouTube Data API allows 10 000 units/day and an upload costs 1 600 — six per
day. Quota resets at midnight Pacific. If you are hitting this on one upload
per day, check for duplicate scheduled tasks or a retry loop re-uploading the
same file.

### `uploadLimitExceeded`

A per-channel daily upload limit, separate from API quota. Newer channels have
tighter limits. Nothing to do but wait 24 hours.

### Upload succeeds but the video is not a Short

YouTube classifies a video as a Short based on aspect ratio and duration. It
must be vertical and **60 seconds or less**. Check `Audio duration` in the log —
if scripts are running long, tighten the word count in the prompt
(currently 60–90 words).

### The video is stuck processing

Normal for a few minutes after upload. The URL printed in the log works as soon
as processing completes.

---

## Scheduled task

### Task hangs until the time limit

The worst failure mode, because it does not fail fast. If the refresh token has
expired, `get_youtube_service()` falls through to
`InstalledAppFlow.run_local_server()` — which opens a browser and **waits
forever** for a click that will never come in an unattended run.

Symptoms: `LastTaskResult = 267014` (terminated by time limit), or a run still
listed as running long after it should have finished. The log ends
mid-pipeline with no exit line.

Fix: run [`renew_token.bat`](../renew_token.bat), then re-run the task. The
`ExecutionTimeLimit` of 1 hour is what keeps a hang from blocking the next
day's run.

### `LastTaskResult = 267011`

`0x41303` — the task has not run yet, or the scheduled instance was missed
because the machine was off during the 11:15–12:45 window. With
`-StartWhenAvailable` set it should catch up at next boot. To publish for that
day immediately:

```powershell
Start-ScheduledTask -TaskName "ContentBot Daily"
```

### The task runs but nothing happens

Almost always a `PATH` or working-directory difference between your interactive
session and the task's user context. Check that `logs/` gained a new file at
all:

- **No new log** → the task never launched PowerShell. Check the action's
  argument path and that the script file exists where the task expects.
- **Log exists but is nearly empty** → Python failed to start. Verify the
  hard-coded `$python` path at the top of `scheduled_run.ps1` is still valid.

### Task disappeared after a Windows update

Occasionally a major update clears custom tasks. Re-register it with the
snippet in [SETUP.md](SETUP.md#7--daily-scheduling).

---

## Output quality

### Subtitles are hidden behind the Shorts UI

The Shorts player overlays the title, channel name, and action buttons across
the bottom of the frame. Raise `margin_v` on the offending design in
`SUBTITLE_DESIGNS` — 600 or more for alignment 2. Alignment 5 centres
vertically and ignores `margin_v` entirely.

### Subtitle colors come out wrong

ASS uses `&H<AA><BB><GG><RR>` — alpha, **blue, green, red**. Reversed from
ordinary hex. `&H0000FFFF` is yellow, not cyan. Writing a preset with normal
RGB order is the standard mistake.

### Footage does not match the script

Check the `BG terms:` line in the log:

- **Terms look sensible but footage is generic** → Pexels genuinely lacks good
  matches for that subject. Acceptable; the video still works.
- **Terms are abstract** (`infinity`, `wisdom`) → the prompt's ban list is being
  ignored. Reinforce it.
- **Terms are exotic species or proper nouns** → same problem; add more ❌/✅
  pairs in the style of the existing ones.

### Scripts feel same-y

Topic selection is uniform random over twelve categories with no memory of
previous runs, so repeats happen. Widen the `categories` list, or add
persistence — write the last N topics to a file and exclude them from the
random draw.

### Openings are weak

The prompt's hook rules are the defence against this. If the model has started
opening with setup sentences again, add the offending phrasings as new ❌
examples in `generate_script()` — the existing ones were added the same way,
in response to actual output.

---

## Still stuck

1. Re-run with `python main.py --no-upload` to isolate generation from upload.
2. Compare a failing log against the healthy shape in
   [OPERATIONS.md](OPERATIONS.md#reading-a-log) and find the first stage that
   deviates.
3. Check the artifacts sharing the run's timestamp in `output/` — an existing
   `audio_<ts>.mp3` with a missing `video_<ts>.mp4` narrows the failure to
   assembly.
4. Read the relevant stage in [ARCHITECTURE.md](ARCHITECTURE.md).
