#!/usr/bin/env python3
"""
morning_brief.py
Fetches the most recent Obsidian diary entry from GitHub, generates a
morning brief via Groq, and saves it to TickTick as a note.

Required environment variables:
  GITHUB_TOKEN          - Fine-grained PAT with Contents: read on mon-atelier
  OBSIDIAN_REPO         - nn-mpofu/mon-atelier
  OBSIDIAN_JOURNAL_PATH - 04 Personal/Journal/2026
  GROQ_API_KEY          - Groq API key
  TICKTICK_CLIENT_ID    - TickTick OAuth client ID
  TICKTICK_CLIENT_SECRET- TickTick OAuth client secret
  TICKTICK_ACCESS_TOKEN - TickTick access token (~180 day TTL, re-run ticktick_auth.py to refresh)
"""

import os, json, re, base64, urllib.request, urllib.parse
from datetime import datetime
import pytz

GITHUB_TOKEN          = os.environ.get("OBSIDIAN_TOKEN") or os.environ["GITHUB_TOKEN"]
OBSIDIAN_REPO         = os.environ["OBSIDIAN_REPO"]
OBSIDIAN_JOURNAL_PATH = os.environ.get("OBSIDIAN_JOURNAL_PATH", "")
GROQ_API_KEY          = os.environ["GROQ_API_KEY"]
TICKTICK_ACCESS_TOKEN = os.environ["TICKTICK_ACCESS_TOKEN"]

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


def main():
    import os as _os
    test_mode = _os.environ.get("TEST_MODE") == "1"

    now = datetime.now(TZ)
    print(f"[{now.strftime('%H:%M')}] Fetching latest diary entry...")
    diary_name, diary_content = fetch_latest_diary_entry()
    if not diary_content:
        print("Could not find a diary entry. Check OBSIDIAN_REPO and OBSIDIAN_JOURNAL_PATH.")
        return
    print(f"Found: {diary_name}")

    print("Generating brief via Groq...")
    title, brief = build_brief(diary_name, diary_content, now)

    # Due date: 06:30 SAST on the current day (or 2 min from now in test mode)
    from datetime import timedelta
    if test_mode:
        due = now + timedelta(minutes=2)
    else:
        due = now.replace(hour=6, minute=30, second=0, microsecond=0)
    due_iso = due.strftime("%Y-%m-%dT%H:%M:%S+0000") if due.utcoffset() is None else due.isoformat()

    print(f"Saving to TickTick: {title} (due {due.strftime('%H:%M')})")
    result = ticktick_create_note(title, brief, due_iso)
    print(f"Note created: {result.get('id', 'unknown id')}")
    print("\n" + brief)


if __name__ == "__main__":
    main()
