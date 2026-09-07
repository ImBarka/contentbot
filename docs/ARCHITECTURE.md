# Architecture

A stage-by-stage reference for [`main.py`](../main.py): what each function
receives, what it returns, and why it is built the way it is. Read this before
changing the pipeline.

- [Design principles](#design-principles)
- [Pipeline overview](#pipeline-overview)
- [Stage 0 · Housekeeping](#stage-0--housekeeping)
- [Stage 1 · Script generation](#stage-1--script-generation)
- [Stage 2 · Voiceover and word timings](#stage-2--voiceover-and-word-timings)
- [Stage 3 · Duration probe](#stage-3--duration-probe)
- [Stage 4 · Karaoke subtitles](#stage-4--karaoke-subtitles)
- [Stage 5 · Background footage](#stage-5--background-footage)
- [Stage 6 · Assembly](#stage-6--assembly)
- [Stage 7 · Upload](#stage-7--upload)
- [Failure modes and recovery](#failure-modes-and-recovery)
- [Extension points](#extension-points)

---

## Design principles

**Stateless runs.** No database, no run history, nothing carried between
invocations. A run either completes or fails; the next one starts clean. Cache
and output folders are pure performance and debugging aids — deleting them
costs a re-download, never correctness.

**Fail loud and early.** Missing API key, no background footage, FFmpeg
non-zero exit — all call `sys.exit(1)` rather than degrading. A scheduled task
that fails visibly in a log is better than one that quietly uploads a broken
video to a public channel.

**Degrade only where degradation is harmless.** Two exceptions to the rule
above: no music simply means voice-only audio, and a Pexels shortfall falls
back to local clips. Neither produces something you would be embarrassed to
publish.

**One encode.** The video is encoded exactly once, by one FFmpeg call.
Intermediate files would mean generational quality loss and several times the
CPU.

**Minimal local compute.** Every heavy step is delegated to a cloud service.
The machine does one x264 encode and nothing else — no local TTS model, no
forced aligner, no video generation.

---

## Pipeline overview

```
                    ┌──────────────────────────────────────┐
   random topic ───▶│ generate_script()                    │
   (12 categories)  │   Gemini Flash, JSON response mode   │
                    └──────────────────────────────────────┘
                       │        │           │          │
              title,   │ script │  tags,    │ background_keywords
              desc     │        │  desc     │
                       ▼        ▼           │          ▼
                  ┌─────────────────────┐   │   ┌──────────────────────────┐
                  │ generate_audio()    │   │   │ get_backgrounds_for_     │
                  │   Edge TTS          │   │   │ keywords()               │
                  │   → mp3 + words[]   │   │   │   Pexels search+download │
                  └─────────────────────┘   │   └──────────────────────────┘
                       │        │           │          │
              words[]  │        │ mp3       │          │ [clip paths]
                       ▼        ▼           │          │
        ┌────────────────────┐  ┌────────────────┐     │
        │ generate_subtitle_ │  │ get_audio_     │     │
        │ ass()  → .ass      │◀─│ duration()     │     │
        └────────────────────┘  └────────────────┘     │
                       │                │              │
                       └────────┬───────┴──────────────┘
                                ▼
                   ┌──────────────────────────────┐
      music/ ─────▶│ assemble_video()             │
      (random)     │   single FFmpeg invocation   │
                   └──────────────────────────────┘
                                │ .mp4
                                ▼
                   ┌──────────────────────────────┐
                   │ upload_to_youtube()          │
                   │   YouTube Data API v3        │
                   └──────────────────────────────┘
```

Every artifact for a run shares one timestamp: `audio_<ts>.mp3`,
`subs_<ts>.ass`, `video_<ts>.mp4`. When a run misbehaves, that timestamp ties
the log line to the exact files.

---

## Stage 0 · Housekeeping

`prune_old_files(folder, days)`

Deletes files whose mtime is older than the cutoff. Silent on a missing folder,
swallows `OSError` (a file locked by a media player should not kill the run),
and prints a summary only when something was actually removed.

| Folder | Retention | Why that number |
|---|---|---|
| `output/` | 14 days | Long enough to review two weeks of uploads; media is large. |
| `backgrounds/cache/` | 60 days | Long enough for cache hits to pay off; short enough to bound disk. |
| `logs/` | 30 days | Pruned by `scheduled_run.ps1`, not by Python. |

---

## Stage 1 · Script generation

`generate_script() → (title, script, description, tags, bg_keywords, topic)`

**Model:** `gemini-flash-latest`, called with
`generation_config={"response_mime_type": "application/json"}`. JSON mode is
what makes a single call safe to parse — without it the model wraps output in
prose or markdown fences.

**Topic** is `random.choice` over twelve categories. This is the whole content
strategy: uniform random, no memory of yesterday's topic. Repeats across a long
run are possible and acceptable.

**One call, five fields.** Title, script, description, tags, and background
keywords come back together. Splitting into multiple calls would cost latency
and, worse, let the fields drift out of sync with each other.

### The prompt is the product

The prompt is the highest-leverage code in the repository. Two constraints in
it were written in response to specific, observed failures.

**Hook placement.** The model's default is a setup sentence, which is fatal for
Shorts retention. The prompt mandates that sentence 1 is a 5–12 word
jaw-dropping claim, and supplies labelled ❌/✅ pairs:

| | Example |
|---|---|
| ❌ | "Look up at the night sky. You see thousands of stars…" |
| ❌ | "Grab a piece of paper. You've heard you can only fold it seven times…" |
| ✅ | "There are more trees on Earth than stars in our galaxy." |
| ✅ | "Fold a paper 42 times and you'd reach the Moon." |

Structure is then fixed: hook → 2–3 middle sentences carrying concrete numbers
and scale comparisons → one punchy closing statement. The closing must be a
statement, not a question; questions are reserved for the description where
they drive comments.

**Stock-footage realism.** Left alone, the model names subjects precisely —
`mantis shrimp`, `axolotl`, `narwhal` — and Pexels returns nothing usable. The
prompt therefore requires broad, common visual concepts:

| Model's instinct | What the prompt forces |
|---|---|
| `mantis shrimp` | `colorful shrimp`, `tropical fish` |
| `axolotl` | `small aquatic creature` |
| `narwhal` | `whale swimming` |

Abstract nouns (`infinity`, `wisdom`, `time`) and bare topic names (`animals`,
`space`) are banned — the first returns meaningless B-roll, the second returns
footage too generic to feel connected to the script. Terms must be 1–3 words
and visually distinct from one another.

### Fallback path

If JSON parsing fails (`JSONDecodeError`, `KeyError`, `TypeError`), the run does
not die. It falls back to a generic title, uses the raw response text as the
script, and sets `bg_keywords = [topic]`. The result is a weaker video, not a
missing one. The log line `⚠️ JSON parse failed` marks these runs — a few in a
row is a signal that the model or the prompt needs attention.

---

## Stage 2 · Voiceover and word timings

`generate_audio(script, output_path, voice, max_retries=3) → words[]`

Async, driven by `asyncio.run()` from `main()`.

The key detail is `boundary="WordBoundary"`. Edge TTS streams two kinds of
chunk — `audio` bytes, which are written straight to the MP3, and
`WordBoundary` events carrying offset and duration in 100-nanosecond ticks.
Dividing by `10_000_000` converts to seconds:

```python
{"text": "galaxy", "start": 3.42, "end": 3.87}
```

**This is why no forced aligner is needed.** The engine that produced the audio
already knows exactly where each word sits. Running Whisper afterwards to
recover that information would be a second model doing work the first one gave
away for free.

### Two layers of resilience

Edge TTS is an unofficial client against a Microsoft endpoint, and it fails in
two distinct ways.

1. **Transient empty stream.** Inside `generate_audio`, `NoAudioReceived`
   triggers up to 3 attempts with a 5-second sleep between them.
2. **Retired voice.** Microsoft removes voices without notice — Davis and
   Andrew were retired in June 2026 and are commented out in `TTS_VOICES` for
   exactly this reason. `main()` shuffles the voice pool with `random.sample`
   and walks it; a voice that exhausts its retries falls through to the next.
   Only when every voice fails does the run exit.

The shuffle serves double duty: it is both the failover mechanism and the
reason consecutive uploads do not all sound like the same narrator.

---

## Stage 3 · Duration probe

`get_audio_duration(audio_path) → float`

Shells out to `ffprobe -show_entries format=duration -of json`. The real audio
length — not an estimate from word count — drives both the subtitle tail and
the clip count. An estimate here would desync the final chunk and leave a video
that ends before or after the voice does.

---

## Stage 4 · Karaoke subtitles

`generate_subtitle_ass(words, output_path, total_duration, design)`

### Chunking

`_chunk_words()` groups consecutive word events, closing a chunk when either
limit is hit:

| Constant | Default | Purpose |
|---|---|---|
| `SUBTITLE_CHUNK_WORDS` | 3 | Caps words on screen — readable at a glance. |
| `SUBTITLE_CHUNK_DURATION` | 0.9 s | Caps time on screen — forces motion during slow speech. |

Both limits matter. Words alone would let a slowly-spoken phrase sit still for
seconds; duration alone would let a fast burst cram six words on screen.

### Timing

A chunk displays from its first word's `start` until the **next chunk's start**,
not until its own last word ends. There is no gap between chunks — text is
always on screen, which is what produces the continuous karaoke feel rather
than flickering. The final chunk extends to `max(last_word_end, total_duration)`
so subtitles never disappear before the audio does.

### Text formatting

`_format_chunk_text()` uppercases everything, strips `, . ? !`, and wraps any
token containing a digit in the design's emphasis color before restoring the
primary color:

```
{\c&H0000FFFF&}42{\c&H00FFFFFF&} TIMES
```

Numbers are the payload of a fun-fact Short, so they are colored differently
from the rest of the line by default.

### Designs

Five presets in `SUBTITLE_DESIGNS`, one chosen at random per video:

| Name | Primary | Alignment | Margin V |
|---|---|---|---|
| Classic | White | 2 (bottom-center) | 600 |
| Yellow Pop | Yellow | 2 (bottom-center) | 600 |
| Cyan Cool | Cyan | 5 (mid-center) | 0 |
| Hot Pink | Magenta | 2 (bottom-center) | 800 |
| Matrix Green | Green | 2 (bottom-center) | 700 |

**ASS color format is `&H<AA><BB><GG><RR>`** — alpha, then *blue, green, red*,
reversed from the usual hex order. `&H0000FFFF` is opaque yellow (BB=00, GG=FF,
RR=FF), not opaque cyan. Getting this backwards is the classic mistake when
adding a preset.

`margin_v` pushes subtitles clear of the YouTube Shorts UI — the title, channel
name, and action buttons overlay the bottom third of the frame. Alignment 5
(mid-center) ignores `margin_v` entirely, which is why Cyan Cool sets it to 0.

---

## Stage 5 · Background footage

**Clip count:** `max(1, round(duration / SECONDS_PER_BG_CLIP))`. A 42-second
script at the default 7 seconds per clip yields 6 clips.

`get_backgrounds_for_keywords(keywords, n)` loops `n` times, taking
`keywords[i % len(keywords)]` — so 4 keywords across 6 clips reuses the first
two. Each iteration calls `fetch_one_pexels_video()`, which searches, shuffles
the 15 results, and downloads the first one whose ID is not already in
`used_ids`. The ID is parsed back out of the cached filename
(`<keyword>_<id>.mp4`) to keep the dedup set current.

**Downloads are lazy.** One search returns 15 candidates but only one is
fetched. Downloading all of them would waste bandwidth and quota on clips that
will never be used.

### Variant selection

`_download_pexels_video()` scores each available file by
`abs(max(width, height) - 1920)` and takes the minimum. Scoring the *larger*
dimension handles landscape (1920×1080) and portrait (1080×1920) sources with
one rule, and targets the resolution the output actually needs — no upscaling
from a small variant, no wasted bytes on 4K.

### Why no orientation filter

The commented-out option in `_pexels_search_metadata()` is deliberate.
Filtering `orientation=portrait` excludes roughly 90% of Pexels' library. Since
FFmpeg crops to portrait anyway at zero cost, accepting landscape sources
produces dramatically better keyword matches.

### Caching and fallback

Cache key is `<keyword>_<video_id>.mp4` in `backgrounds/cache/`. An existing
file short-circuits the download. A failed download deletes the partial file so
a truncated MP4 never poisons the cache.

If Pexels returns fewer than `n` clips, any `.mp4` sitting directly in
`backgrounds/` (excluding `cache/`) pads the remainder by random choice. With
no Pexels results *and* an empty fallback folder, the run exits — a video with
no visuals is worse than no video.

---

## Stage 6 · Assembly

`assemble_video(audio_path, bg_videos, subtitle_path, output_path, duration, music_path)`

One FFmpeg call builds the entire video. Each clip is trimmed to
`duration / n` seconds, scaled with `force_original_aspect_ratio=increase`,
cropped to 1080×1920, and `setsar=1` normalises pixel aspect ratio so concat
does not reject mismatched inputs.

```
[0:v]trim=0:7.000,setpts=PTS-STARTPTS,
     scale=1080:1920:force_original_aspect_ratio=increase,
     crop=1080:1920,setsar=1[v0]
... (repeated per clip) ...
[v0][v1][v2]concat=n=3:v=1:a=0[concat]
[concat]ass=subs_20260907_132215.ass[vout]
[4:a]volume=0.10[bgm];[3:a][bgm]amix=inputs=2:duration=first:
     dropout_transition=0:normalize=0[aout]
```

Details worth knowing before you edit this function:

**`-stream_loop -1` on every visual input.** Pexels clips are frequently
shorter than their allotted segment. Looping infinitely and then trimming
guarantees each segment is filled regardless of source length.

**`setpts=PTS-STARTPTS` after every trim.** Trimming preserves original
timestamps; without this reset, concat produces a video with huge gaps.

**`normalize=0` on amix.** FFmpeg's default normalisation would halve the voice
volume the moment a second input joins — making `MUSIC_VOLUME` meaningless.
With normalisation off, 0.10 really is 10% under the voice.

**`duration=first` and `-shortest`.** Music tracks are minutes long; the mix
must end with the voice, not the track.

**`cwd` is set to the subtitle's directory** and the `ass=` filter is given a
bare filename. FFmpeg's filter syntax treats `:` and `\` as delimiters, so a
Windows absolute path like `e:\contentbot\output\subs.ass` breaks the parse.
Changing directory sidesteps the escaping problem entirely — do not "fix" this
by passing a full path.

**`-t duration + 0.3`.** A 300 ms tail prevents the last syllable from being
clipped by rounding.

On a non-zero exit the last 2000 characters of stderr are printed and the run
exits — FFmpeg's real error is always near the end of its output.

---

## Stage 7 · Upload

`get_youtube_service()` implements a three-tier auth ladder:

1. Load `token.json` if it exists.
2. If the access token is expired but a refresh token is present, refresh
   silently.
3. If refresh fails or no token exists, open a browser via
   `InstalledAppFlow.run_local_server(port=0)`.

Credentials are re-persisted after every branch, so a silent refresh keeps the
file current. Scope is exactly `youtube.upload` — the narrowest scope that does
the job. It cannot read analytics, edit other videos, or touch the channel.

`upload_to_youtube()` posts with `categoryId: "22"` (People & Blogs),
`privacyStatus: "public"`, and `selfDeclaredMadeForKids: False`. Upload uses
`MediaFileUpload(..., resumable=True)` so a dropped connection mid-transfer can
recover.

Back in `main()`, the title gets ` #Shorts` appended and the description gets a
hashtag line built from the first six tags with hyphens stripped:

```python
hashtag_line = " ".join(f"#{t.replace('-', '')}" for t in tags[:6])
full_description = f"{description}\n\n{hashtag_line}"
```

Note that the full tag list still goes to the API `tags` field; the six-tag cap
applies only to the visible hashtag line.

`--no-upload` returns before any of this, leaving the MP4 in `output/`.

---

## Failure modes and recovery

| Stage | Failure | Behaviour |
|---|---|---|
| 1 | `GEMINI_API_KEY` unset | `sys.exit(1)` immediately |
| 1 | Malformed JSON from Gemini | Fallback metadata, run continues |
| 1 | DNS / network unreachable | `google.api_core` retries ~600 s, then raises |
| 2 | `NoAudioReceived` | 3 retries, then next voice; exit only if all fail |
| 5 | Pexels search fails | Warn, try next keyword |
| 5 | Download fails | Delete partial, warn, try next candidate |
| 5 | Fewer clips than needed | Pad from local `backgrounds/*.mp4` |
| 5 | No clips at all | `sys.exit(1)` |
| 6 | FFmpeg non-zero exit | Print last 2000 chars of stderr, `sys.exit(1)` |
| 7 | Refresh token expired | Falls back to browser auth — which **blocks
forever under Task Scheduler**, since no one is there to click |

That last row is the one to watch. An expired refresh token in an unattended
run does not fail fast; it hangs waiting for a browser interaction that will
never happen. The `ExecutionTimeLimit` on the scheduled task is what eventually
kills it. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md#invalid_grant--token-has-been-expired-or-revoked).

---

## Extension points

**Change the channel's subject matter.** Edit the `categories` list and the
prompt inside `generate_script()`. Everything downstream is topic-agnostic.

**Change the look.** Append to `SUBTITLE_DESIGNS`. Mind the `&HAABBGGRR` byte
order and keep `margin_v` at 600+ for bottom alignment so text clears the
Shorts UI.

**Change the pacing.** Lower `SECONDS_PER_BG_CLIP` for faster cuts, or lower
`SUBTITLE_CHUNK_DURATION` for snappier text.

**Non-English output.** Swap `TTS_VOICES` for the target locale
(`edge-tts --list-voices`) and instruct the language in the prompt. Note that
`_format_chunk_text()` assumes uppercasing is meaningful and strips only ASCII
punctuation — both assumptions break for non-Latin scripts.

**More than one upload per day.** Wrap `main()` in a loop, but respect the
YouTube quota: 10 000 units/day at 1 600 units per upload caps you at 6.
