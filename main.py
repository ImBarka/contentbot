"""
ContentBot - Auto YouTube Shorts Generator
Run this once a day when you open your laptop.
"""

import os
import random
import subprocess
import datetime
import json
import glob
import sys
import time

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import google.generativeai as genai
import edge_tts
import asyncio
import requests
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Load secrets from .env sitting next to this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
GEMINI_API_KEY      = os.environ.get("GEMINI_API_KEY", "")
PEXELS_API_KEY      = os.environ.get("PEXELS_API_KEY", "")
BACKGROUND_FOLDER   = os.path.join(BASE_DIR, "backgrounds")
CACHE_FOLDER        = os.path.join(BACKGROUND_FOLDER, "cache")
MUSIC_FOLDER        = os.path.join(BASE_DIR, "music")
MUSIC_VOLUME        = 0.10   # 10% of voice volume — adjust 0.08-0.25 to taste
OUTPUT_FOLDER       = os.path.join(BASE_DIR, "output")
CREDENTIALS_FILE    = os.path.join(BASE_DIR, "client_secrets.json")
TOKEN_FILE          = os.path.join(BASE_DIR, "token.json")
PRUNE_DAYS_OUTPUT   = 14     # delete generated audio/video/subs older than N days
PRUNE_DAYS_CACHE    = 60     # delete Pexels cache older than N days
TTS_VOICES          = [
    "en-US-AriaNeural",      # female, conversational
    "en-US-GuyNeural",       # male, neutral
    "en-US-JennyNeural",     # female, friendly
    "en-US-AvaNeural",       # female, expressive
    "en-GB-RyanNeural",      # British male
    "en-GB-SoniaNeural",     # British female
    # NOTE: Davis & Andrew retired by Microsoft (June 2026) — removed.
]
SECONDS_PER_BG_CLIP = 7      # one Pexels clip per ~N seconds of audio
VIDEO_WIDTH         = 1080
VIDEO_HEIGHT        = 1920
SUBTITLE_FONT       = "Arial Black"
SUBTITLE_FONT_SIZE  = 90

# ASS color format: &H<AA><BB><GG><RR> (alpha-blue-green-red, AA=00 = opaque)
SUBTITLE_DESIGNS = [
    {
        "name": "Classic",       "primary": "&H00FFFFFF", "outline": "&H00000000",
        "outline_size": 8,       "emphasis": "&H0000FFFF",
        "alignment": 2,          "margin_v": 600,
    },
    {
        "name": "Yellow Pop",    "primary": "&H0000FFFF", "outline": "&H00000000",
        "outline_size": 10,      "emphasis": "&H00FFFFFF",
        "alignment": 2,          "margin_v": 600,
    },
    {
        "name": "Cyan Cool",     "primary": "&H00FFFF00", "outline": "&H00800000",
        "outline_size": 8,       "emphasis": "&H0000FFFF",
        "alignment": 5,          "margin_v": 0,
    },
    {
        "name": "Hot Pink",      "primary": "&H00FF00FF", "outline": "&H00000000",
        "outline_size": 9,       "emphasis": "&H0000FFFF",
        "alignment": 2,          "margin_v": 800,
    },
    {
        "name": "Matrix Green",  "primary": "&H0000FF00", "outline": "&H00000000",
        "outline_size": 8,       "emphasis": "&H00FFFFFF",
        "alignment": 2,          "margin_v": 700,
    },
]
# ─────────────────────────────────────────────


def prune_old_files(folder, days):
    """Delete files in `folder` older than `days` days. Quiet on missing folder."""
    if not os.path.isdir(folder):
        return
    cutoff = time.time() - days * 86400
    removed = 0
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    if removed:
        print(f"🗑️  Pruned {removed} file(s) older than {days}d from {os.path.basename(folder)}/")


def generate_script():
    """Use Gemini to generate all metadata in one call.
    Returns (title, script, description, tags, topic).
    """
    print("🤖 Generating title + script + description + tags with Gemini...")
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY not set in .env")
        sys.exit(1)
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-flash-latest")

    categories = [
        "science", "psychology", "history", "philosophy",
        "nature", "space", "human body", "ancient civilizations",
        "mathematics", "technology", "animals", "language"
    ]
    topic = random.choice(categories)

    prompt = f"""You are a viral YouTube Shorts creator. Make a hook-driven fun-fact Short about: {topic}

Return JSON with these fields:

- "title": catchy, curiosity-driven, under 70 chars. Bold statement or punchy question. NO hashtags. Avoid "Did You Know".

- "script": 60-90 words of spoken content. CRITICAL STRUCTURE:
    * SENTENCE 1 = THE HOOK (5-12 words). A jaw-dropping claim that sounds impossible. Lead WITH the surprising fact — never with setup like "Look at..." or "Imagine..." or "Grab a...". The viewer must hear something shocking in the first 2 seconds.
      ❌ BAD: "Look up at the night sky. You see thousands of stars..."
      ❌ BAD: "Grab a piece of paper. You've heard you can only fold it seven times..."
      ✅ GOOD: "There are more trees on Earth than stars in our galaxy."
      ✅ GOOD: "Fold a paper 42 times and you'd reach the Moon."
    * MIDDLE (2-3 sentences): expand with CONCRETE numbers, scale comparisons, or counterintuitive details. Make the impossible feel real.
    * CLOSING (1 line): a punchy thought-provoking STATEMENT (not a question — questions go in description). Should leave viewer staring at the screen.
    Tone: conversational, energetic, urgent. Use "you" not "we". Spoken words only — no stage directions, no titles.

- "description": 2-3 sentences. First sentence teases the fact (different wording from script). Optional second sentence adds context. END with this exact pattern: an engaging question to drive comments + "Follow for daily mind-blowing facts!" (or near-equivalent CTA). No hashtags here — they're added separately.

- "tags": array of 6-10 relevant lowercase keywords (no # symbol, no spaces in multi-word tags). Mix broad ({topic}, shorts, funfacts) with specific terms from the actual fact. Example for space: ["space","astronomy","nasa","blackhole","funfacts","shorts","didyouknow","cosmos"].

- "background_keywords": array of 4-6 visual search terms for STOCK FOOTAGE (Pexels). CRITICAL: these terms must be COMMON stock-footage concepts that have many matching videos online — NOT obscure scientific names or rare species. Pexels' library has lots of generic nature/ocean/tech footage but very few niche subjects.
    RULES:
    1. Use BROAD CATEGORIES, not specific species. ❌ "mantis shrimp" → ✅ "colorful shrimp" or "tropical fish". ❌ "axolotl" → ✅ "small aquatic creature". ❌ "narwhal" → ✅ "whale swimming".
    2. Prefer common visual concepts: "ocean waves", "deep space", "city night", "human brain scan", "ancient ruins", "forest canopy", "lab microscope", "mountain peak".
    3. 1-3 words per term. Visually distinct between terms.
    4. AVOID: abstract words ("infinity", "wisdom", "time"), vague topic names ("animals", "space"), niche species/proper nouns Pexels likely won't have.
    Example for immortal jellyfish script: ["jellyfish swimming", "deep ocean blue", "underwater bubbles", "coral reef colorful", "marine life"]
    Example for paper-folding-to-moon script: ["origami paper", "moon surface", "abstract geometric", "starry night sky", "scientific calculation"]
    Example for a script about Nintendo's playing card origin: ["vintage playing cards", "old japanese street", "antique shop", "game console close-up"]
"""
    response = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )
    try:
        data = json.loads(response.text)
        title = data["title"].strip()
        script = data["script"].strip()
        description = data["description"].strip()
        tags = [t.strip().lower() for t in data["tags"] if t.strip()]
        bg_keywords = [k.strip() for k in data.get("background_keywords", []) if k.strip()]
        if not bg_keywords:
            bg_keywords = [topic]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"⚠️ JSON parse failed ({e}), using fallback metadata.")
        title = f"Mind-Blowing {topic.title()} Fact"
        script = response.text.strip()
        description = f"A surprising fact about {topic} you probably didn't know."
        tags = [topic, "shorts", "funfacts", "didyouknow", "wisdom"]
        bg_keywords = [topic]

    print(f"✅ Generated ({topic})")
    print(f"   Title:    {title}")
    print(f"   Tags:     {tags}")
    print(f"   BG terms: {bg_keywords}")
    print(f"\n--- SCRIPT ---\n{script}\n--------------\n")
    print(f"--- DESCRIPTION ---\n{description}\n--------------\n")
    return title, script, description, tags, bg_keywords, topic


async def generate_audio(script, output_path, voice, max_retries=3):
    """Convert script to speech via Edge TTS, capturing word-level timings.

    Edge TTS occasionally returns empty stream (NoAudioReceived) due to
    transient MS service issues — retry with backoff before giving up.

    Returns: list of {"text": str, "start": float, "end": float} in seconds.
    """
    print(f"🎙️ Generating audio with Edge TTS (voice: {voice})...")
    for attempt in range(1, max_retries + 1):
        try:
            communicate = edge_tts.Communicate(script, voice, boundary="WordBoundary")
            words = []
            with open(output_path, "wb") as f:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        start = chunk["offset"] / 10_000_000
                        duration = chunk["duration"] / 10_000_000
                        words.append({
                            "text": chunk["text"],
                            "start": start,
                            "end": start + duration,
                        })
            print(f"✅ Audio saved: {output_path} ({len(words)} word events)")
            return words
        except edge_tts.exceptions.NoAudioReceived:
            if attempt == max_retries:
                raise
            print(f"⚠️ Edge TTS empty (attempt {attempt}/{max_retries}), retrying in 5s...")
            await asyncio.sleep(5)


def _ass_time(seconds):
    """Format seconds as ASS timestamp H:MM:SS.cs (centiseconds)."""
    h = int(seconds // 3600)
    seconds -= h * 3600
    m = int(seconds // 60)
    seconds -= m * 60
    return f"{h}:{m:02d}:{seconds:05.2f}"


SUBTITLE_CHUNK_WORDS    = 3      # max words per subtitle chunk
SUBTITLE_CHUNK_DURATION = 0.9    # max seconds per chunk


def _chunk_words(words):
    """Group consecutive WordBoundary events into chunks of N words / max duration."""
    chunks, current = [], []
    chunk_start = None
    for w in words:
        if not current:
            current = [w]
            chunk_start = w["start"]
        elif (len(current) >= SUBTITLE_CHUNK_WORDS
              or (w["end"] - chunk_start) > SUBTITLE_CHUNK_DURATION):
            chunks.append(current)
            current = [w]
            chunk_start = w["start"]
        else:
            current.append(w)
    if current:
        chunks.append(current)
    return chunks


def _format_chunk_text(chunk, primary_color, emphasis_color):
    """Format chunk: uppercase, strip punctuation, color digits with emphasis color."""
    parts = []
    primary_tag  = f"{{\\c{primary_color}&}}"
    emphasis_tag = f"{{\\c{emphasis_color}&}}"
    for w in chunk:
        text = w["text"].upper().replace(",", "").replace(".", "").replace("?", "").replace("!", "")
        if any(c.isdigit() for c in text):
            parts.append(f"{emphasis_tag}{text}{primary_tag}")
        else:
            parts.append(text)
    return " ".join(parts)


def generate_subtitle_ass(words, output_path, total_duration, design):
    """Write a karaoke-style ASS subtitle file using the given design preset."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{SUBTITLE_FONT},{SUBTITLE_FONT_SIZE},{design['primary']},&H000000FF,{design['outline']},&H00000000,1,0,0,0,100,100,0,0,1,{design['outline_size']},2,{design['alignment']},40,40,{design['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    chunks = _chunk_words(words)
    lines = []
    for i, chunk in enumerate(chunks):
        start = chunk[0]["start"]
        if i + 1 < len(chunks):
            end = chunks[i + 1][0]["start"]
        else:
            end = max(chunk[-1]["end"], total_duration)
        text = _format_chunk_text(chunk, design["primary"], design["emphasis"])
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")
    print(f"✅ Subtitle saved: {output_path} ({len(chunks)} chunks, design: {design['name']})")


def pick_music_track():
    """Return path to a random .mp3/.m4a/.wav from MUSIC_FOLDER, or None if empty."""
    if not os.path.isdir(MUSIC_FOLDER):
        return None
    tracks = []
    for ext in ("*.mp3", "*.m4a", "*.wav"):
        tracks.extend(glob.glob(os.path.join(MUSIC_FOLDER, ext)))
    if not tracks:
        return None
    return random.choice(tracks)


def get_audio_duration(audio_path):
    """Get duration of audio file using ffprobe."""
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", audio_path
    ], capture_output=True, text=True)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def _download_pexels_video(video, topic):
    """Pick the best-fit file from a Pexels video, download to cache, return path.

    Strategy: pick variant whose LARGER dimension is closest to 1920px. This works
    for both landscape (1920x1080) and portrait (1080x1920) source videos. FFmpeg
    will handle cropping landscape to portrait downstream.
    """
    files = video.get("video_files", [])
    if not files:
        return None
    def quality_score(f):
        larger = max(f.get("width", 0), f.get("height", 0))
        return abs(larger - 1920)
    files_sorted = sorted(files, key=quality_score)
    chosen = files_sorted[0]

    os.makedirs(CACHE_FOLDER, exist_ok=True)
    safe_topic = topic.replace(" ", "_")
    filepath = os.path.join(CACHE_FOLDER, f"{safe_topic}_{video['id']}.mp4")

    if os.path.exists(filepath):
        print(f"   Cached: {os.path.basename(filepath)}")
        return filepath

    print(f"   Downloading {chosen.get('height')}p: {os.path.basename(filepath)}")
    try:
        with requests.get(chosen["link"], stream=True, timeout=120) as dl:
            dl.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in dl.iter_content(chunk_size=65536):
                    f.write(chunk)
    except Exception as e:
        print(f"⚠️ Pexels download failed: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)
        return None
    return filepath


def _pexels_search_metadata(keyword):
    """Just search Pexels and return video metadata (no downloads)."""
    if not PEXELS_API_KEY or PEXELS_API_KEY == "YOUR_PEXELS_API_KEY":
        return []
    try:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            # No orientation filter — most stock footage is landscape and we crop
            # to portrait in FFmpeg. Filtering portrait-only excludes 90% of matches.
            params={"query": keyword, "per_page": 15},
            headers={"Authorization": PEXELS_API_KEY},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("videos", [])
    except Exception as e:
        print(f"⚠️ Pexels search failed for '{keyword}': {e}")
        return []


def fetch_one_pexels_video(keyword, used_ids=None):
    """Search keyword, download FIRST unused result, return path. Lazy: only downloads what's needed."""
    used_ids = used_ids or set()
    print(f"🎥 Searching Pexels for '{keyword}'...")
    videos = _pexels_search_metadata(keyword)
    if not videos:
        print(f"⚠️ No Pexels results for '{keyword}'")
        return None
    random.shuffle(videos)
    for v in videos:
        if v["id"] in used_ids:
            continue
        path = _download_pexels_video(v, keyword)
        if path:
            return path
    return None


def get_backgrounds_for_keywords(keywords, n):
    """Fetch n background clips, one specific Pexels search per clip.

    Cycles through keywords if n > len(keywords). Tracks used video IDs to
    avoid duplicates within the same Short.
    """
    if not keywords:
        print("⚠️ No background keywords provided")
        keywords = ["abstract"]

    paths = []
    used_ids = set()

    for i in range(n):
        keyword = keywords[i % len(keywords)]
        print(f"   [{i+1}/{n}] {keyword}")
        path = fetch_one_pexels_video(keyword, used_ids)
        if path:
            paths.append(path)
            # Extract video ID from filename "<keyword>_<id>.mp4"
            stem = os.path.splitext(os.path.basename(path))[0]
            try:
                used_ids.add(int(stem.rsplit("_", 1)[1]))
            except (IndexError, ValueError):
                pass

    # Fallback to local if Pexels short
    if len(paths) < n:
        local = glob.glob(os.path.join(BACKGROUND_FOLDER, "*.mp4"))
        local = [p for p in local if "cache" not in p.lower()]
        if local:
            print(f"   Padding with local fallback ({n - len(paths)} more)...")
            while len(paths) < n:
                paths.append(random.choice(local))

    if not paths:
        print("❌ No background videos available (Pexels failed and folder empty).")
        print(f"   Put .mp4 files in: {BACKGROUND_FOLDER}")
        sys.exit(1)

    return paths[:n]


def assemble_video(audio_path, bg_videos, subtitle_path, output_path, duration, music_path=None):
    """Concat N background clips, burn ASS subtitles, mix voice + optional bg music."""
    n = len(bg_videos)
    seg_duration = duration / n
    print(f"🎬 Assembling video ({n} clips × {seg_duration:.1f}s each) with FFmpeg...")
    for i, bg in enumerate(bg_videos):
        print(f"   [{i+1}/{n}] {os.path.basename(bg)}")
    if music_path:
        print(f"   🎵 Music: {os.path.basename(music_path)} @ {int(MUSIC_VOLUME*100)}%")

    sub_filename = os.path.basename(subtitle_path)

    # Video chain
    filter_parts = []
    for i in range(n):
        filter_parts.append(
            f"[{i}:v]trim=0:{seg_duration:.3f},setpts=PTS-STARTPTS,"
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},setsar=1[v{i}]"
        )
    concat_inputs = "".join(f"[v{i}]" for i in range(n))
    filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[concat]")
    filter_parts.append(f"[concat]ass={sub_filename}[vout]")

    # Audio chain
    voice_idx = n
    if music_path:
        music_idx = n + 1
        filter_parts.append(
            f"[{music_idx}:a]volume={MUSIC_VOLUME}[bgm];"
            f"[{voice_idx}:a][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        audio_map = "[aout]"
    else:
        audio_map = f"{voice_idx}:a"

    filter_complex = ";".join(filter_parts)

    cmd = ["ffmpeg", "-y"]
    for bg in bg_videos:
        cmd += ["-stream_loop", "-1", "-i", bg]
    cmd += ["-i", audio_path]
    if music_path:
        cmd += ["-stream_loop", "-1", "-i", music_path]

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", audio_map,
        "-c:v", "libx264",
        "-c:a", "aac",
        "-t", f"{duration + 0.3:.3f}",
        "-shortest",
        "-pix_fmt", "yuv420p",
        output_path,
    ]

    cwd = os.path.dirname(os.path.abspath(subtitle_path))
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        print("❌ FFmpeg error:", result.stderr[-2000:])
        sys.exit(1)

    print(f"✅ Video assembled: {output_path}")


def get_youtube_service():
    """Authenticate and return YouTube API service.

    Uses cached refresh_token to silently get new access tokens. Only opens
    browser if no token exists or refresh_token itself expired (~7 days in
    OAuth testing mode).
    """
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        # Try silent refresh first
        if creds and creds.expired and creds.refresh_token:
            try:
                print("🔄 Access token expired, refreshing silently...")
                creds.refresh(Request())
            except Exception as e:
                print(f"⚠️ Refresh failed ({e}). Falling back to browser auth.")
                creds = None

        # Only open browser if refresh wasn't possible
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Persist updated credentials (new access token or new full auth)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(video_path, title, description, tags):
    """Upload video to YouTube as a Short."""
    print("📤 Uploading to YouTube...")
    youtube = get_youtube_service()

    request_body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22"  # People & Blogs
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media
    )

    response = request.execute()
    video_id = response["id"]
    print(f"✅ Uploaded! https://youtube.com/shorts/{video_id}")
    return video_id


def main():
    today = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    audio_path    = os.path.join(OUTPUT_FOLDER, f"audio_{today}.mp3")
    subtitle_path = os.path.join(OUTPUT_FOLDER, f"subs_{today}.ass")
    video_path    = os.path.join(OUTPUT_FOLDER, f"video_{today}.mp4")

    print("=" * 50)
    print("       CONTENTBOT — Daily Shorts Generator")
    print("=" * 50)

    # Step 0: Housekeeping — prune old files
    prune_old_files(OUTPUT_FOLDER, PRUNE_DAYS_OUTPUT)
    prune_old_files(CACHE_FOLDER, PRUNE_DAYS_CACHE)

    # Step 1: Generate title + script + description + tags + background_keywords
    title, script, description, tags, bg_keywords, topic = generate_script()

    # Step 2: Generate audio. Try voices in random order — if one is silently
    # retired by Microsoft (NoAudioReceived), automatically fall through to next.
    voice_order = random.sample(TTS_VOICES, len(TTS_VOICES))
    words = None
    for v in voice_order:
        try:
            words = asyncio.run(generate_audio(script, audio_path, v))
            break
        except edge_tts.exceptions.NoAudioReceived:
            print(f"⚠️ Voice {v} exhausted retries — trying next voice")
    if words is None:
        print("❌ All TTS voices failed. Edge TTS service may be down.")
        sys.exit(1)

    # Step 3: Get audio duration
    duration = get_audio_duration(audio_path)
    print(f"   Audio duration: {duration:.1f}s")

    # Step 4: Build karaoke subtitle file with a random design preset
    design = random.choice(SUBTITLE_DESIGNS)
    print(f"   🎨 Subtitle design: {design['name']}")
    generate_subtitle_ass(words, subtitle_path, duration, design)

    # Step 5: Fetch N background clips, one per script-specific keyword
    n_clips = max(1, round(duration / SECONDS_PER_BG_CLIP))
    bg_videos = get_backgrounds_for_keywords(bg_keywords, n_clips)

    # Step 6: Pick optional background music + assemble final video
    music_path = pick_music_track()
    assemble_video(audio_path, bg_videos, subtitle_path, video_path, duration, music_path)

    # Step 7: Upload to YouTube (skipped if --no-upload)
    if "--no-upload" in sys.argv:
        print("\n⏭️  Upload skipped (--no-upload flag).")
        print(f"   Video saved at: {video_path}")
        return

    youtube_title = f"{title} #Shorts"
    # Build description body: Gemini's teaser + a hashtag line built from tags
    hashtag_line = " ".join(f"#{t.replace('-', '')}" for t in tags[:6])
    full_description = f"{description}\n\n{hashtag_line}"
    upload_to_youtube(video_path, youtube_title, full_description, tags)

    print("\n✅ Done! Your Short is live.")
    print(f"   Video saved at: {video_path}")


if __name__ == "__main__":
    main()
