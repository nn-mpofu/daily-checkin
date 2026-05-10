#!/usr/bin/env python3
"""
morning_brief.py — morning + afternoon check-ins for Nyasha.
Set MODE=morning (default) or MODE=afternoon to switch.

Required env vars (all modes):
  OBSIDIAN_TOKEN        - Fine-grained PAT, Contents: read on mon-atelier
  OBSIDIAN_REPO         - nn-mpofu/mon-atelier
  OBSIDIAN_JOURNAL_PATH - 04 Personal/Journal/2026
  GROQ_API_KEY          - Groq API key
  TICKTICK_ACCESS_TOKEN - TickTick OAuth access token (~180 day TTL)

Afternoon only:
  TOGGL_API_TOKEN       - Toggl API token (from toggl.com/profile)
  TOGGL_WORKSPACE_ID    - Toggl workspace ID
"""

import os, json, re, base64, hashlib, urllib.request, urllib.parse
from datetime import datetime, timedelta
import pytz

def _env(key, default=""):
    return os.environ.get(key, default).strip().lstrip('﻿')

GITHUB_TOKEN          = _env("OBSIDIAN_TOKEN") or _env("GITHUB_TOKEN")
OBSIDIAN_REPO         = _env("OBSIDIAN_REPO")
OBSIDIAN_JOURNAL_PATH = _env("OBSIDIAN_JOURNAL_PATH")
GROQ_API_KEY          = _env("GROQ_API_KEY")
TICKTICK_ACCESS_TOKEN = _env("TICKTICK_ACCESS_TOKEN")
TOGGL_API_TOKEN       = _env("TOGGL_API_TOKEN")
TOGGL_WORKSPACE_ID    = _env("TOGGL_WORKSPACE_ID")

TZ = pytz.timezone("Africa/Johannesburg")


def gh_get(path):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{OBSIDIAN_REPO}/contents/{urllib.parse.quote(path)}",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    return json.loads(urllib.request.urlopen(req).read())


_SKIP = {"Report", "Review", "Habits", "Time", "Preview", "Template", "Index"}

def _is_diary_file(name):
    return (
        name.endswith(".md")
        and re.search(r"\d", name)
        and not name.startswith("_")
        and not any(s in name for s in _SKIP)
    )

def _day_ordinal(d):
    if 11 <= d <= 13:
        return f"{d}th"
    return f"{d}{['th','st','nd','rd','th'][min(d % 10, 4)]}"

def _read_file(item):
    file_data = gh_get(item["path"])
    return item["name"], base64.b64decode(file_data["content"]).decode("utf-8")

def fetch_diary_for_day(now):
    """Try today's diary file first; fall back to most recent."""
    today_pattern = f"{now.strftime('%B')} {_day_ordinal(now.day)}"

    # Search GitHub for today's file by name
    query = urllib.parse.urlencode({
        "q": f'filename:"{today_pattern}" repo:{OBSIDIAN_REPO} extension:md',
        "per_page": 5,
    })
    req = urllib.request.Request(
        f"https://api.github.com/search/code?{query}",
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
    )
    try:
        resp = json.loads(urllib.request.urlopen(req).read())
        for item in resp.get("items", []):
            if item["name"].endswith(".md") and today_pattern in item["name"]:
                print(f"Found today's entry: {item['name']}")
                return _read_file(item)
    except Exception as e:
        print(f"Today's diary search: {e}")

    # Fall back to most recent
    print("No entry for today yet — using most recent.")
    return _fetch_latest()

def _fetch_latest():
    def find_latest(path, depth=0):
        if depth > 8:
            return None, None
        try:
            items = gh_get(path)
        except Exception as e:
            print(f"gh_get error at '{path}': {e}")
            return None, None
        dated = sorted(
            [i for i in items if i["type"] == "file" and _is_diary_file(i["name"])],
            key=lambda x: x["name"], reverse=True,
        )
        if dated:
            return _read_file(dated[0])
        dirs = sorted([i for i in items if i["type"] == "dir"], key=lambda x: x["name"], reverse=True)
        for d in dirs:
            name, content = find_latest(d["path"], depth + 1)
            if content:
                return name, content
        return None, None
    return find_latest(OBSIDIAN_JOURNAL_PATH)

# keep old name so nothing else breaks
def fetch_latest_diary_entry():
    return _fetch_latest()


_FACT_ANGLES = [
    "an etymology of a specific word that appears in or strongly relates to this diary",
    "a psychological or neurological principle at play in this situation",
    "a lesser-known historical figure whose life echoes these themes",
    "a surprising anthropological or cross-cultural fact about this human experience",
    "a philosophical idea from a non-Western tradition that resonates here",
    "a biological or evolutionary fact that explains something in this emotional experience",
    "an art, music, or literary reference that captures the exact emotional texture here",
]

def groq_fun_fact(diary_content, now, period="morning"):
    # Date + period as seed = consistent per check-in, different each day and between AM/PM
    seed = int(hashlib.md5(f"{now.strftime('%Y-%m-%d')}-{period}".encode()).hexdigest(), 16)
    angle = _FACT_ANGLES[seed % len(_FACT_ANGLES)]
    return groq_generate(
        f"""Based on this diary excerpt, write one genuinely fascinating sentence using this angle: {angle}
Be very specific — no generic observations. Do not reference Voltaire, Candide, or any gardening metaphor.

Diary excerpt:
{diary_content[:2000]}

Write only the one sentence, nothing else."""
    )


def extract_potent_sentiment(diary_content):
    """Pull the single most emotionally alive passage from the diary for sharper context."""
    return groq_generate(
        f"""Read this diary entry and identify the single most emotionally alive moment — the sentence or passage that most vividly captures the writer's inner state.
Return only that passage, verbatim or very lightly condensed. 2-3 sentences max.

Diary:
{diary_content[:4000]}

Return only the passage, nothing else."""
    )


def groq_generate(prompt):
    data = json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600,
        "temperature": 0.7,
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
    )
    resp = json.loads(urllib.request.urlopen(req).read())
    return resp["choices"][0]["message"]["content"].strip()


def ticktick_create_note(title, content, due_date_iso):
    data = json.dumps({
        "title": title,
        "content": content,
        "kind": "NOTE",
        "dueDate": due_date_iso,
    }).encode()
    req = urllib.request.Request(
        "https://ticktick.com/open/v1/task",
        data=data,
        headers={
            "Authorization": f"Bearer {TICKTICK_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    return json.loads(urllib.request.urlopen(req).read())


def fetch_vault_tagged():
    """Search the whole vault via GitHub code search — no file fetching needed."""
    tags = ["#wtlb", "#lesson", "#pinned", "#theLaw"]
    fragments = []
    for tag in tags:
        query = urllib.parse.urlencode({"q": f"{tag} repo:{OBSIDIAN_REPO}", "per_page": 30})
        req = urllib.request.Request(
            f"https://api.github.com/search/code?{query}",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3.text-match+json",
            },
        )
        try:
            resp = json.loads(urllib.request.urlopen(req).read())
            for item in resp.get("items", []):
                for match in item.get("text_matches", []):
                    for line in match.get("fragment", "").splitlines():
                        if tag in line:
                            clean = re.sub(r"#\S+", "", line).strip(" -\t→*>")
                            if clean:
                                fragments.append(clean)
        except Exception as e:
            print(f"Search error for {tag}: {e}")
    return fragments


def pick_pertinent(fragments, diary_content):
    """Ask Groq to pick the single most pertinent tagged line given today's diary."""
    if not fragments:
        return "(nothing tagged in your vault yet)"
    candidates = "\n".join(f"- {f}" for f in fragments)
    return groq_generate(
        f"""Here are notes Nyasha has tagged across her diary over time:
{candidates}

Here is her most recent diary entry:
{diary_content[:2000]}

Pick the single note from the list that feels most relevant or resonant with where she is right now.
Return only that one line, exactly as written, nothing else."""
    )


def build_brief(diary_name, diary_content, now):
    print("Searching vault for tagged notes...")
    fragments = fetch_vault_tagged()
    print(f"Found {len(fragments)} tagged lines across vault")
    tagged_str = pick_pertinent(fragments, diary_content)

    print("Extracting potent sentiment...")
    potent = extract_potent_sentiment(diary_content)

    claude_note = groq_generate(
        f"""You are Claude, writing directly to Nyasha in second person — warm, personal, like a note from someone who knows her well.
Read this passage from her diary and write 2-3 sentences for her morning. Speak to where she is emotionally right now.
No 'you mentioned', no 'you wrote'. Just what you'd say if you knew how she was doing.
Warm and grounded, not generic.

Diary passage:
{potent}

Write only the note, nothing else."""
    )

    fun_fact = groq_fun_fact(diary_content, now, period="morning")

    day = str(now.day)  # no leading zero, works cross-platform
    timestamp = now.strftime(f"%a, {day} %B")
    title = f"☀️ Morning Check-in — {timestamp}"

    brief = f"""# Good morning, Nyasha.
How are you doing today?

## 🌙 Sleep
⚪ —

## 😶 Mood
⚪ —

## 🧠 What's on your mind
→

---

## 🌊 Note to Self
{tagged_str}

---

*Here's what's up for the day.*

---

## 💧 Habits
Water — 0 / 2000ml

---

## ⚡ Friction
→
→

---

## 📡 Claude's Note
{claude_note}

---

## 🌀 Fun Fact
{fun_fact}

---

Have a great day."""

    return title, brief


# ── Afternoon ─────────────────────────────────────────────────────────────────

def fetch_ticktick_progress():
    """Count tasks due today: completed / total across all TickTick projects."""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        req = urllib.request.Request(
            "https://ticktick.com/open/v1/project",
            headers={"Authorization": f"Bearer {TICKTICK_ACCESS_TOKEN}"},
        )
        projects = json.loads(urllib.request.urlopen(req).read())
    except Exception as e:
        print(f"TickTick projects error: {e}")
        return "? / ?"

    total = completed = 0
    for project in projects:
        pid = project.get("id")
        if not pid:
            continue
        try:
            req = urllib.request.Request(
                f"https://ticktick.com/open/v1/project/{pid}/tasks",
                headers={"Authorization": f"Bearer {TICKTICK_ACCESS_TOKEN}"},
            )
            tasks = json.loads(urllib.request.urlopen(req).read())
            for task in tasks:
                due = (task.get("dueDate") or "")[:10]
                if due == today:
                    total += 1
                    if task.get("status") == 2:
                        completed += 1
        except Exception:
            pass

    return f"{completed} / {total}" if total else "no tasks due today"


def fetch_toggl_summary():
    """Get time tracked by project today from Toggl Reports API."""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    creds = base64.b64encode(f"{TOGGL_API_TOKEN}:api_token".encode()).decode()
    data = json.dumps({"start_date": today, "end_date": today}).encode()
    req = urllib.request.Request(
        f"https://api.track.toggl.com/reports/api/v3/workspace/{TOGGL_WORKSPACE_ID}/summary/time_entries",
        data=data,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
        },
    )
    try:
        resp = json.loads(urllib.request.urlopen(req).read())
        lines = []
        for group in resp.get("groups", []):
            name = (group.get("title") or {}).get("project") or "No project"
            secs = group.get("tracked_seconds", 0)
            h, m = divmod(secs // 60, 60)
            lines.append(f"{name} — {h}h {m:02d}m" if h else f"{name} — {m}m")
        return "\n".join(lines) if lines else "(nothing tracked yet)"
    except Exception as e:
        print(f"Toggl error: {e}")
        return "(error fetching Toggl data)"


def build_afternoon_brief(diary_name, diary_content, now):
    print("Fetching TickTick progress...")
    progress = fetch_ticktick_progress()

    print("Fetching Toggl summary...")
    toggl = fetch_toggl_summary()

    print("Extracting potent sentiment...")
    potent = extract_potent_sentiment(diary_content)

    claude_note = groq_generate(
        f"""You are Claude, writing directly to Nyasha in second person — direct, specific, like a mid-day check-in from someone paying attention.
Read this passage from her diary and write 1-3 sentences about what you observe in how her day might be unfolding emotionally.
Not encouraging — observational. No 'you mentioned', no 'you wrote'. Just what you notice.

Diary passage:
{potent}

Write only the observation, nothing else."""
    )

    fun_fact = groq_fun_fact(diary_content, now, period="afternoon")

    day = str(now.day)
    timestamp = now.strftime(f"%a, {day} %B")
    title = f"🌤 Afternoon Check-in — {timestamp}"

    brief = f"""# Good afternoon, Nyasha.
*How is the day going?*

## 😶 Mood
⚪ —

## ⚡ Energy
⚪ —

## 🧠 What's on your mind
→

---

*Here's where you are.*

---

## ✅ Progress
{progress if "no tasks" in progress else f"{progress} tasks complete"}

---

## ⏱ Time Today
{toggl}

---

## 🔄 Pulse
*Where do I need to pivot?*
→
→

---

## 📡 Claude's Note
{claude_note}

---

## 🌀 Fun Fact
{fun_fact}

---

Keep going."""

    return title, brief


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    mode = _env("MODE", "morning")
    test_mode = _env("TEST_MODE") == "1"

    now = datetime.now(TZ)
    print(f"[{now.strftime('%H:%M')}] Mode: {mode} — fetching diary entry...")
    diary_name, diary_content = fetch_diary_for_day(now)
    if not diary_content:
        print("Could not find a diary entry. Check OBSIDIAN_REPO and OBSIDIAN_JOURNAL_PATH.")
        return
    print(f"Found: {diary_name}")

    if mode == "afternoon":
        title, brief = build_afternoon_brief(diary_name, diary_content, now)
        due = (now + timedelta(minutes=2)) if test_mode else now.replace(hour=14, minute=0, second=0, microsecond=0)
    else:
        print("Generating brief via Groq...")
        title, brief = build_brief(diary_name, diary_content, now)
        due = (now + timedelta(minutes=2)) if test_mode else now.replace(hour=6, minute=30, second=0, microsecond=0)

    due_iso = due.isoformat()
    print(f"Saving to TickTick: {title} (due {due.strftime('%H:%M')})")
    result = ticktick_create_note(title, brief, due_iso)
    print(f"Note created: {result.get('id', 'unknown id')}")
    print("\n" + brief)


if __name__ == "__main__":
    main()
