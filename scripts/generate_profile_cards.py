#!/usr/bin/env python3
"""Generate GitHub profile stat cards as SVG (light + dark) into ./profile.

Uses the GitHub GraphQL API with GITHUB_TOKEN. No third-party services, no
dependencies beyond the standard library.

    GITHUB_TOKEN=... python3 scripts/generate_profile_cards.py [login]
"""

import datetime as dt
import json
import os
import sys
import urllib.request
from html import escape
from pathlib import Path

LOGIN = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_ACTOR", "estebanfloresf"))
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
OUT = Path(__file__).resolve().parent.parent / "profile"

THEMES = {
    "": dict(bg="#ffffff", border="#e4e2e2", title="#0891b2", text="#24292f", muted="#6e7781", accent="#0891b2", track="#e6edf3"),
    "-dark": dict(bg="#0d1117", border="#30363d", title="#22d3ee", text="#e6edf3", muted="#8b949e", accent="#22d3ee", track="#21262d"),
}

QUERY = """
query($login: String!, $prQuery: String!, $issueQuery: String!) {
  prs: search(query: $prQuery, type: ISSUE) { issueCount }
  issues: search(query: $issueQuery, type: ISSUE) { issueCount }
  user(login: $login) {
    name
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch():
    if not TOKEN:
        sys.exit("Set GITHUB_TOKEN (or GH_TOKEN).")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {
            "login": LOGIN,
            # Public-only so numbers match what the Actions token (and visitors) can see.
            "prQuery": f"author:{LOGIN} type:pr is:public",
            "issueQuery": f"author:{LOGIN} type:issue is:public",
        }}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json", "User-Agent": "profile-cards"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if payload.get("errors"):
        sys.exit(f"GraphQL error: {payload['errors']}")
    data = payload["data"]
    user = data["user"]
    user["prCount"] = data["prs"]["issueCount"]
    user["issueCount"] = data["issues"]["issueCount"]
    return user


def streaks(days):
    """Return (current, longest) streak from chronologically ordered day counts."""
    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] > 0 else 0
        longest = max(longest, run)
    # Current streak: walk back from today; today may still be empty.
    current = 0
    seq = list(reversed(days))
    i = 0
    if seq and seq[0]["contributionCount"] == 0:
        i = 1
    while i < len(seq) and seq[i]["contributionCount"] > 0:
        current += 1
        i += 1
    return current, longest


def card(width, height, title, body, t):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
  <title>{escape(title)}</title>
  <style>
    text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; }}
    .title {{ font-size: 16px; font-weight: 600; fill: {t['title']}; }}
    .label {{ font-size: 13px; fill: {t['muted']}; }}
    .value {{ font-size: 15px; font-weight: 600; fill: {t['text']}; }}
  </style>
  <rect x="0.5" y="0.5" rx="6" width="{width - 1}" height="{height - 1}" fill="{t['bg']}" stroke="{t['border']}"/>
  <text x="25" y="32" class="title">{escape(title)}</text>
{body}
</svg>
"""


def stats_card(u, t):
    cc = u["contributionsCollection"]
    stars = sum(r["stargazerCount"] for r in u["repositories"]["nodes"])
    items = [
        ("Stars earned", stars),
        ("Commits (past year)", cc["totalCommitContributions"]),
        ("Pull requests (public)", u["prCount"]),
        ("Issues (public)", u["issueCount"]),
        ("Public repositories", u["repositories"]["totalCount"]),
        ("Followers", u["followers"]["totalCount"]),
    ]
    rows = []
    for i, (label, value) in enumerate(items):
        col, row = divmod(i, 3)
        x = 25 + col * 235
        y = 68 + row * 30
        rows.append(f'  <text x="{x}" y="{y}" class="label">{escape(label)}</text>')
        rows.append(f'  <text x="{x + 205}" y="{y}" class="value" text-anchor="end">{value:,}</text>')
    name = u.get("name") or LOGIN
    return card(495, 165, f"{name}'s GitHub Stats", "\n".join(rows), t)


def streak_card(u, t):
    cal = u["contributionsCollection"]["contributionCalendar"]
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    current, longest = streaks(days)
    total = cal["totalContributions"]
    cols = [(82, total, "Contributions", "past year"), (247, current, "Current streak", "days"), (412, longest, "Longest streak", "days, past year")]
    out = []
    for i, (cx, val, label, sub) in enumerate(cols):
        big = i == 1
        if big:
            out.append(f'  <circle cx="{cx}" cy="84" r="31" fill="none" stroke="{t["accent"]}" stroke-width="4"/>')
        out.append(f'  <text x="{cx}" y="{91 if big else 89}" text-anchor="middle" style="font-size:{24 if big else 22}px;font-weight:700;fill:{t["accent"] if big else t["text"]}">{val:,}</text>')
        out.append(f'  <text x="{cx}" y="136" text-anchor="middle" class="label" style="fill:{t["text"]};font-weight:600">{escape(label)}</text>')
        out.append(f'  <text x="{cx}" y="151" text-anchor="middle" class="label" style="font-size:11px">{escape(sub)}</text>')
    return card(495, 165, "Contribution streak", "\n".join(out), t)


def langs_card(u, t):
    totals, colors = {}, {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            n = e["node"]["name"]
            totals[n] = totals.get(n, 0) + e["size"]
            colors[n] = e["node"]["color"] or "#8b949e"
    top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:6]
    grand = sum(totals.values()) or 1
    out = []
    if not top:
        out.append(f'  <text x="25" y="75" class="label">No public language data yet.</text>')
        return card(495, 165, "Top languages", "\n".join(out), t)
    x, bar_w = 25.0, 445.0
    out.append(f'  <rect x="25" y="48" width="{bar_w}" height="10" rx="5" fill="{t["track"]}"/>')
    clip = f'<clipPath id="bar"><rect x="25" y="48" width="{bar_w}" height="10" rx="5"/></clipPath>'
    segs = []
    shown = sum(s for _, s in top)
    for name, size in top:
        w = bar_w * size / shown
        segs.append(f'<rect x="{x:.1f}" y="48" width="{w:.1f}" height="10" fill="{colors[name]}"/>')
        x += w
    out.append(f'  {clip}<g clip-path="url(#bar)">{"".join(segs)}</g>')
    for i, (name, size) in enumerate(top):
        col, row = divmod(i, 3)
        lx, ly = 25 + col * 235, 90 + row * 26
        pct = 100 * size / grand
        out.append(f'  <circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{colors[name]}"/>')
        out.append(f'  <text x="{lx + 18}" y="{ly}" class="label" style="fill:{t["text"]}">{escape(name)}</text>')
        out.append(f'  <text x="{lx + 205}" y="{ly}" class="label" text-anchor="end">{pct:.1f}%</text>')
    return card(495, 165, "Top languages (public repos)", "\n".join(out), t)


def main():
    user = fetch()
    OUT.mkdir(exist_ok=True)
    for suffix, theme in THEMES.items():
        (OUT / f"stats{suffix}.svg").write_text(stats_card(user, theme))
        (OUT / f"streak{suffix}.svg").write_text(streak_card(user, theme))
        (OUT / f"top-langs{suffix}.svg").write_text(langs_card(user, theme))
    cc = user["contributionsCollection"]["contributionCalendar"]
    print(f"{LOGIN}: {cc['totalContributions']} contributions, "
          f"{user['repositories']['totalCount']} repos; wrote 6 SVGs to {OUT} "
          f"({dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC)")


if __name__ == "__main__":
    main()
