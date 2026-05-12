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

import os, sys, json, re, base64, hashlib, urllib.request, urllib.parse
from datetime import datetime, timedelta
import pytz

# Ensure emoji in print() never crashes on narrow Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
    # Include year so we don't accidentally pick up last year's same-date entry
    today_pattern = f"{now.strftime('%B')} {_day_ordinal(now.day)}, {now.year}"
    today_pattern_short = f"{now.strftime('%B')} {_day_ordinal(now.day)}"

    # Search GitHub for today's file by name
    query = urllib.parse.urlencode({
        "q": f'filename:"{today_pattern_short}" repo:{OBSIDIAN_REPO} extension:md',
        "per_page": 10,
    })
    req = urllib.request.Request(
        f"https://api.github.com/search/code?{query}",
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
    )
    try:
        resp = json.loads(urllib.request.urlopen(req).read())
        for item in resp.get("items", []):
            # Must match today's date AND current year
            if item["name"].endswith(".md") and today_pattern_short in item["name"] and str(now.year) in item["name"]:
                print(f"Found today's entry: {item['name']}")
                return _read_file(item)
    except Exception as e:
        print(f"Today's diary search: {e}")

    # Fall back to most recent
    print("No entry for today yet — using most recent.")
    return _fetch_latest()

def _fetch_latest():
    # Always use the current year, even if the env var / GitHub secret is stale
    current_year = str(datetime.now(TZ).year)
    base_path = re.sub(r'\b20\d{2}\b', current_year, OBSIDIAN_JOURNAL_PATH)
    print(f"Using journal path: {base_path}")

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
    return find_latest(base_path)

# keep old name so nothing else breaks
def fetch_latest_diary_entry():
    return _fetch_latest()


def _fetch_recent(count=4):
    """Return up to `count` most recent diary entries, newest first."""
    current_year = str(datetime.now(TZ).year)
    base_path = re.sub(r'\b20\d{2}\b', current_year, OBSIDIAN_JOURNAL_PATH)

    collected = []

    def collect(path, depth=0):
        if depth > 8 or len(collected) >= count:
            return
        try:
            items = gh_get(path)
        except Exception as e:
            print(f"gh_get error at '{path}': {e}")
            return
        dated = sorted(
            [i for i in items if i["type"] == "file" and _is_diary_file(i["name"])],
            key=lambda x: x["name"], reverse=True,
        )
        for item in dated:
            if len(collected) >= count:
                return
            collected.append(item)
        dirs = sorted([i for i in items if i["type"] == "dir"], key=lambda x: x["name"], reverse=True)
        for d in dirs:
            collect(d["path"], depth + 1)

    collect(base_path)
    results = []
    for item in collected:
        try:
            name, content = _read_file(item)
            results.append((name, content))
        except Exception as e:
            print(f"Could not read {item['name']}: {e}")
    return results


def groq_fun_fact(diary_content, now, period="morning"):
    """Always etymological. Morning: tied to the diary's emotional weight. Afternoon: tied to action, momentum, or finishing."""
    if period == "afternoon":
        return groq_generate(
            f"""Pick one word from this list — persist, focus, effort, finish, momentum, resolve, drive, commit, rally, execute — whichever most naturally connects to themes in the diary below, then write one genuinely fascinating sentence about its etymology.

Name the language of origin, the original meaning, and trace how it shifted into its modern sense. One sentence only. No preamble.

Diary excerpt for context:
{diary_content[:2000]}"""
        )
    # Seed a word-pick hint so it doesn't always land on the same word
    seed = int(hashlib.md5(f"{now.strftime('%Y-%m-%d')}-morning".encode()).hexdigest(), 16)
    skip_hint = ["the first emotionally charged word you see", "a word you haven't used before today",
                 "an unexpected word — not the most obvious one", "a quieter word, not the loudest one in the entry"][seed % 4]
    return groq_generate(
        f"""Pick one word from this diary excerpt that carries real emotional or thematic weight — {skip_hint} — then write one genuinely fascinating sentence about its etymology: where it came from, what it originally meant, and how that origin illuminates something about the writer's experience.

Be specific: name the language of origin, the original meaning, and trace how it shifted. Do not pick the word "consume". One sentence only. No preamble.

Diary excerpt:
{diary_content[:2000]}"""
    )


def groq_generate_quote(diary_content, period="morning"):
    """Morning: emotionally resonant. Afternoon: action, momentum, finishing strong."""
    if period == "afternoon":
        prompt = f"""Choose one real quote from a real, named person about momentum, finishing strong, focus, or the power of the second half. It should make someone want to act, not reflect. Avoid generic hustle quotes and overused phrases.

Diary excerpt for context:
{diary_content[:2000]}

Respond with exactly two lines. Nothing before. Nothing after. No self-correction. No alternatives.
Line 1: the quote wrapped in double quotation marks
Line 2: an em dash and the author's full name

"Like this."
— Author Name"""
    else:
        prompt = f"""Based on the emotional tone and themes in this diary excerpt, choose one real quote from a real, named person that resonates with where the writer is right now. Be specific and unexpected — avoid Rumi, Rilke, Maya Angelou, Brené Brown, and any quote that appears on greeting cards or Instagram. Favour writers, philosophers, scientists, or artists who are specific to the mood.

Diary excerpt:
{diary_content[:2000]}

Respond with exactly two lines. Nothing before. Nothing after. No self-correction. No alternatives.
Line 1: the quote wrapped in double quotation marks
Line 2: an em dash and the author's full name

"Like this."
— Author Name"""
    raw = groq_generate(prompt)
    # Extract quote and author cleanly via regex, ignoring any leaked commentary
    quote_match = re.search(r'"([^"]+)"', raw)
    author_match = re.search(r'[—–-]\s*([A-Z][^,\n]+?)(?:\s+is\b|\s+so\b|\s+but\b|\s+or\b|\s+possibly\b|,|$)', raw)
    if quote_match and author_match:
        return f'"{quote_match.group(1)}"\n— {author_match.group(1).strip()}'
    # Fallback: first two non-empty lines
    lines = [l for l in raw.splitlines() if l.strip()][:2]
    return "\n".join(lines)


def groq_claude_note_with_mode(entries, today_tasks, tagged_fragments, period="morning"):
    """Read recent signals, pick a mode honestly, write the note."""
    entries_text = "\n\n---\n\n".join(
        f"[{name}]\n{content[:1500]}" for name, content in entries
    )
    tasks_text = "\n".join(f"- {t}" for t in today_tasks) if today_tasks else "(no tasks scheduled today)"
    tags_text = "\n".join(f"- {f}" for f in tagged_fragments[:15]) if tagged_fragments else "(none)"

    if period == "afternoon":
        framing = """You are writing a short afternoon note for Nyasha — it's mid-day, the morning is behind her. Don't reflect on how she's feeling. Focus entirely on what's still possible in the hours ahead. Pick the mode that honestly fits and write something that moves her forward."""
        mode_hype = "🎯 HYPE — something significant is still happening today or still needs doing. Name it. Send her in."
        mode_steady = "🤝 STEADY — it's been a heavy day. Don't dwell. Just remind her she's still got time and still in it."
        mode_hard = "🔥 HARD HITTER — the afternoon is slipping and she knows it. The work is still there. Say it clearly, with love."
        mode_celebrate = "🎉 CELEBRATOR — she got something real done today. Make sure she feels it before the day ends."
        mode_witness = "🪞 WITNESS — she wrote or said something today that points exactly to what she needs to do next. Echo it back."
    else:
        framing = """You are writing a short morning note for Nyasha. Read all the signals carefully and pick ONE mode that honestly fits — not the most comfortable one, the most accurate one."""
        mode_hype = "🎯 HYPE — something significant is on her plate today (an event, deadline, performance, hard conversation). Name it. Send her in strong."
        mode_steady = "🤝 STEADY — recent entries show weight, a hard moment, or emotional exhaustion. Don't dwell on it. Just acknowledge she's still here and steady her."
        mode_hard = "🔥 HARD HITTER — the pattern across entries shows real drift: avoidance, not showing up to her own stated goals, slacking on what she said matters. Say it. Firm, loving, no shame."
        mode_celebrate = "🎉 CELEBRATOR — she recently came through or achieved something worth marking. Make it land before she rushes past it."
        mode_witness = "🪞 WITNESS — she wrote something recently that was genuinely profound and she may not have fully absorbed it. Reflect her own words back to her."

    return groq_generate(
        f"""{framing}

MODES:
{mode_witness}
{mode_hype}
{mode_steady}
{mode_celebrate}
{mode_hard}

SIGNALS:
Recent diary entries (newest first):
{entries_text}

Today's tasks:
{tasks_text}

Tagged notes from her vault:
{tags_text}

RULES:
- 2-3 sentences max. No more.
- Sound like a close friend who pays close attention — not a life coach, not a therapist
- Never open with "I noticed", "You mentioned", "It seems like", or "I can see"
- Never use gardening metaphors or any reference to cultivating, tending, or growing things
- Never list anything
- HYPE: name the actual thing happening today, not a generic send-off
- HARD HITTER: firm and loving — the friend who grabs your shoulder, not the one who lectures you
- WITNESS: quote or closely echo her own words back so she hears herself
- STEADY: brief. Don't linger on the hard thing. Just carry her forward.
- Write only the note. No mode label. No explanation. No preamble."""
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
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://ticktick.com/open/v1/task",
        data=data,
        headers={
            "Authorization": f"Bearer {TICKTICK_ACCESS_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    return json.loads(urllib.request.urlopen(req).read())


def fetch_ticktick_today_tasks():
    """Return titles of undone tasks due today — used for Hype mode detection."""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    tasks_today = []
    try:
        req = urllib.request.Request(
            "https://ticktick.com/open/v1/project",
            headers={"Authorization": f"Bearer {TICKTICK_ACCESS_TOKEN}"},
        )
        projects = json.loads(urllib.request.urlopen(req).read())
    except Exception as e:
        print(f"TickTick projects error: {e}")
        return []
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
                if due == today and task.get("status") != 2:
                    title = task.get("title", "").strip()
                    if title:
                        tasks_today.append(title)
        except Exception:
            pass
    return tasks_today


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
    print("Fetching recent diary entries for mode detection...")
    entries = _fetch_recent(4)
    if not entries:
        entries = [(diary_name, diary_content)]
    print(f"Loaded {len(entries)} entries: {', '.join(n for n, _ in entries)}")

    print("Searching vault for tagged notes...")
    fragments = fetch_vault_tagged()
    print(f"Found {len(fragments)} tagged lines across vault")
    tagged_str = pick_pertinent(fragments, diary_content)

    print("Fetching today's tasks...")
    today_tasks = fetch_ticktick_today_tasks()
    print(f"Found {len(today_tasks)} tasks due today")

    print("Generating Claude's Note (mode detection)...")
    claude_note = groq_claude_note_with_mode(entries, today_tasks, fragments)

    fun_fact = groq_fun_fact(diary_content, now, period="morning")

    print("Generating quote...")
    quote = groq_generate_quote(diary_content)

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

*Let's move forward in the day.*

---

## 💧 Habits
Water — 0 / 2000ml

---

## ⚡ Friction
→
→

---

## 🌊 Note to Self
{tagged_str}

---

## 🌅 Ideal Day
→

---

## 📡 Claude's Note
{claude_note}

---

## 🌀 Fun Fact
{fun_fact}

---

## 🤍 Promise to Myself
→

---

> {quote}

*Have a great day.*"""

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


def fetch_morning_promise(now):
    """Find today's morning check-in in TickTick and extract the Promise to Myself.
    Searches the inbox first, then falls back to scanning all projects.
    Returns the promise text, or None if not found / still blank."""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    headers = {"Authorization": f"Bearer {TICKTICK_ACCESS_TOKEN}"}

    def _extract_promise(content):
        match = re.search(
            r'##\s*🤍\s*Promise to Myself\s*\n(.*?)(?:\n---|\n##|$)',
            content, re.DOTALL
        )
        if match:
            promise = match.group(1).strip()
            if promise and promise != "→":
                return promise
        return None

    # Try inbox first (fastest)
    try:
        req = urllib.request.Request(
            "https://ticktick.com/open/v1/project/inbox116930458/tasks",
            headers=headers,
        )
        tasks = json.loads(urllib.request.urlopen(req).read())
        for task in tasks:
            if "Morning Check-in" in (task.get("title") or "") and \
               (task.get("dueDate") or "")[:10] == today:
                promise = _extract_promise(task.get("content") or "")
                if promise:
                    return promise
    except Exception as e:
        print(f"Inbox fetch: {e}")

    # Fall back: scan all projects
    try:
        req = urllib.request.Request(
            "https://ticktick.com/open/v1/project",
            headers=headers,
        )
        projects = json.loads(urllib.request.urlopen(req).read())
        for project in projects:
            pid = project.get("id")
            if not pid:
                continue
            try:
                req = urllib.request.Request(
                    f"https://ticktick.com/open/v1/project/{pid}/tasks",
                    headers=headers,
                )
                tasks = json.loads(urllib.request.urlopen(req).read())
                for task in tasks:
                    if "Morning Check-in" in (task.get("title") or "") and \
                       (task.get("dueDate") or "")[:10] == today:
                        promise = _extract_promise(task.get("content") or "")
                        if promise:
                            return promise
            except Exception:
                pass
    except Exception as e:
        print(f"Project scan: {e}")

    return None


def build_afternoon_brief(diary_name, diary_content, now):
    print("Fetching recent diary entries for mode detection...")
    entries = _fetch_recent(4)
    if not entries:
        entries = [(diary_name, diary_content)]
    print(f"Loaded {len(entries)} entries: {', '.join(n for n, _ in entries)}")

    print("Fetching morning promise...")
    promise = fetch_morning_promise(now)
    if promise:
        print(f"Found morning promise: {promise[:60]}...")
        promise_str = promise
    else:
        print("No morning promise found — falling back to Note to Self")
        fragments = fetch_vault_tagged()
        promise_str = pick_pertinent(fragments, diary_content)

    print("Fetching today's tasks...")
    today_tasks = fetch_ticktick_today_tasks()
    print(f"Found {len(today_tasks)} tasks due today")

    print("Generating Claude's Note (mode detection)...")
    claude_note = groq_claude_note_with_mode(entries, today_tasks, [], period="afternoon")

    fun_fact = groq_fun_fact(diary_content, now, period="afternoon")

    print("Generating quote...")
    quote = groq_generate_quote(diary_content, period="afternoon")

    day = str(now.day)
    timestamp = now.strftime(f"%a, {day} %B")
    title = f"🌤 Afternoon Check-in — {timestamp}"

    brief = f"""# Good afternoon, Nyasha.
*How is the day going?*

---

## 😶 Mood
⚪ —

## ⚡ Energy
⚪ —

## 🧠 What's on your mind
→

---

*Let's keep moving.*

---

## 💧 Habits
Water — 0 / 2000ml

---

## 🤍 Promise to Myself
{promise_str}

---

## 🔄 Pivots
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

## 🎯 Focus for the Rest of the Day
→

---

> {quote}

*Keep going.*"""

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
