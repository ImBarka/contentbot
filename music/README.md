# Background music

Drop `.mp3`, `.m4a`, or `.wav` files in this folder. One track is picked at
random per video and mixed underneath the voiceover at `MUSIC_VOLUME`
(default **10%**, set in [`main.py`](../main.py)).

**This folder is optional.** If it is empty, the pipeline runs normally and
produces voice-only videos.

**Audio files are gitignored.** They are large and licensed by their original
source, not by this project — only this README is committed. Each machine needs
its own copy.

---

## Where to get tracks

### YouTube Audio Library — recommended

1. Open [studio.youtube.com](https://studio.youtube.com) and sign in
2. Left sidebar → **Audio Library**
3. Filter **Attribution: "No attribution required"** — the safest option, since
   this pipeline writes descriptions automatically and will not credit anyone
4. Filter **Duration: 1–3 minutes** — longer than any Short, so the track never
   runs out mid-video
5. Download and drop the file here

Using YouTube's own library also means the tracks are already cleared for
YouTube, so Content ID will not flag your uploads.

### Alternatives

| Source | Licence | Note |
|---|---|---|
| [pixabay.com/music](https://pixabay.com/music/) | Royalty-free | No attribution required |
| [freemusicarchive.org](https://freemusicarchive.org) | Creative Commons | Check each track — some require attribution |
| [bensound.com](https://www.bensound.com) | Free tier | Attribution required on the free tier |

---

## What to pick

Aim for **10–15 tracks** across a few genres. The pipeline rotates randomly, so
a small pool becomes recognisable fast over daily uploads.

| Genre | Fits |
|---|---|
| Cinematic / Dramatic | Big-scale facts — space, deep time, disasters |
| Inspirational / Uplifting | Positive facts, human achievement, nature |
| Ambient | Neutral; works under anything |
| Electronic / Hip Hop | Modern, upbeat, technology topics |

**Avoid tracks with vocals.** Lyrics compete with the voiceover for attention
and make subtitles harder to follow.

**Prefer tracks with a flat opening.** A track picked mid-Short starts from its
beginning, so a long dramatic intro is wasted — and one that opens loud will
step on the hook, which is the most important two seconds of the video.

---

## Volume

If the mix feels wrong, adjust `MUSIC_VOLUME` in [`main.py`](../main.py):

| Value | Character |
|---|---|
| 0.08 | Barely present; texture only |
| **0.10** | **Default.** Clearly under the voice |
| 0.15 | Noticeable; safe for most tracks |
| 0.20 | Prominent; needs a track without busy mids |
| 0.25 | Starts competing with the voice |

Verify any change with `python main.py --no-upload` before letting the
scheduled task publish.
