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

import os, json, re, base64, urllib.request, urllib.parse
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


def fetch_latest_diary_entry():
    """Walk the journal folder tree to find the most recent dated .md file."""
    SKIP = {"Report", "Review", "Habits", "Time", "Preview", "Template", "Index"}

    def is_diary_file(name):
        return (
            name.endswith(".md")
            and re.search(r"\d", name)
            and not name.startswith("_")
            and not any(s in name for s in SKIP)
        )

    def find_latest(path, depth=0):
        if depth > 8:
            return None, None
        try:
            items = gh_get(path)
        except Exception as e:
            print(f"gh_get error at '{path}': {e}")
            return None, None

        dated = sorted(
            [i for i in items if i["type"] == "file" and is_diary_file(i["name"])],
            key=lambda x: x["name"],
            reverse=True,
        )
        if dated:
            file_data = gh_get(dated[0]["path"])
            content = base64.b64decode(file_data["content"]).decode("utf-8")
            return dated[0]["name"], content

        dirs = sorted(
            [i for i in items if i["type"] == "dir"],
            key=lambda x: x["name"],
            reverse=True,
        )
        for d in dirs:
            name, content = find_latest(d["path"], depth + 1)
            if content:
                return name, content
        return None, None

    return find_latest(OBSIDIAN_JOURNAL_PATH)


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

    claude_note = groq_generate(
        f"""You are writing a warm, personal morning note for someone named Nyasha.
Read this diary excerpt carefully, absorb the emotional tone and themes, then set it aside.
Write 2-3 sentences that feel personally written — not assembled. No citations, no 'you mentioned', no 'last night you wrote'. Just what you'd say if you knew how she was doing.
Keep it warm, grounded, and encouraging without being generic.

Diary excerpt:
{diary_content[:3000]}

Write only the note itself, nothing else."""
    )

    fun_fact = groq_generate(
        f"""Based on the themes in this diary excerpt, write one sentence — an etymology, historical curiosity, or idea that connects to something the writer touched on (words used, philosophers referenced, metaphors, emotions).
Make it genuinely interesting, not generic.

Diary excerpt:
{diary_content[:2000]}

Write only the one sentence, nothing else."""
    )

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

    claude_note = groq_generate(
        f"""You are writing a brief afternoon observation for Nyasha, drawn strictly from her recent diary.
One observation about her emotional tone or patterns — how the morning's state might be playing out now.
1-3 sentences. Direct and specific. No 'you mentioned', no 'last night you wrote'.

Diary:
{diary_content[:3000]}

Write only the observation, nothing else."""
    )

    fun_fact = groq_generate(
        f"""Based on the themes in this diary excerpt, write one sentence — an etymology, historical curiosity, or idea that connects to something the writer touched on.
Make it genuinely interesting, not generic.

Diary excerpt:
{diary_content[:2000]}

Write only the one sentence, nothing else."""
    )

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
    print(f"[{now.strftime('%H:%M')}] Mode: {mode} — fetching latest diary entry...")
    diary_name, diary_content = fetch_latest_diary_entry()
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
