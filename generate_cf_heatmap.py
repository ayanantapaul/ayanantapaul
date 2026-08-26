#!/usr/bin/env python3
"""
Generate a GitHub-style contribution heatmap SVG from a Codeforces user's
submission history.

Usage:
    python3 generate_cf_heatmap.py

Config is via environment variables (with sane defaults below) so it's easy
to drive from a GitHub Action without editing the file:
    CF_HANDLE       - Codeforces handle (default: "xunzi")
    CF_MODE         - "all" (every submission) or "ac" (accepted only)
                       (default: "ac")
    OUTPUT_PATH     - where to write the SVG (default: "cf-heatmap.svg")
    WEEKS           - how many weeks of history to show (default: 53)

Only uses the Python standard library, so no pip install is needed in CI.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

CF_HANDLE = os.environ.get("CF_HANDLE", "xunzi")
CF_MODE = os.environ.get("CF_MODE", "ac")  # "ac" = accepted only, "all" = every submission
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "cf-heatmap.svg")
WEEKS = int(os.environ.get("WEEKS", "53"))

API_URL = "https://codeforces.com/api/user.status?handle={handle}&from=1&count=10000"

# GitHub-ish green scale, low -> high
COLOR_SCALE = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]
EMPTY_COLOR = "#161b22"
CELL_SIZE = 11
CELL_GAP = 3
LABEL_PADDING_LEFT = 28
LABEL_PADDING_TOP = 34


def fetch_submissions(handle):
    url = API_URL.format(handle=handle)
    req = urllib.request.Request(url, headers={"User-Agent": "cf-heatmap-script"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"ERROR: failed to reach Codeforces API: {e}", file=sys.stderr)
        sys.exit(1)

    if data.get("status") != "OK":
        print(f"ERROR: Codeforces API returned: {data.get('comment')}", file=sys.stderr)
        sys.exit(1)

    return data["result"]


def bucket_by_day(submissions, mode):
    """Return {date_str: count} for the given mode."""
    counts = {}
    for sub in submissions:
        if mode == "ac" and sub.get("verdict") != "OK":
            continue
        ts = sub.get("creationTimeSeconds")
        if ts is None:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        counts[day] = counts.get(day, 0) + 1
    return counts


def build_grid(counts, weeks):
    """
    Build a list of weeks, each a list of 7 (date, count) entries, Sun->Sat,
    covering the last `weeks` weeks up to and including today (UTC).
    """
    today = datetime.now(timezone.utc).date()
    # Align end to the coming Saturday (end of current week, Sun-Sat)
    days_since_sunday = (today.weekday() + 1) % 7  # Mon=0 ... Sun=6 -> we want Sun=0
    end_of_week = today + timedelta(days=(6 - days_since_sunday))
    start = end_of_week - timedelta(days=weeks * 7 - 1)

    grid = []
    cursor = start
    for _w in range(weeks):
        week = []
        for _d in range(7):
            date_str = cursor.strftime("%Y-%m-%d")
            week.append((cursor, counts.get(date_str, 0)))
            cursor += timedelta(days=1)
        grid.append(week)
    return grid


def color_for_count(count, max_count):
    if count <= 0:
        return EMPTY_COLOR
    if max_count <= 0:
        return EMPTY_COLOR
    # bucket into 4 non-empty levels
    ratio = count / max_count
    if ratio <= 0.25:
        idx = 1
    elif ratio <= 0.5:
        idx = 2
    elif ratio <= 0.75:
        idx = 3
    else:
        idx = 4
    return COLOR_SCALE[idx]


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAY_LABELS = {1: "Mon", 3: "Wed", 5: "Fri"}  # index within week (0=Sun)


def render_svg(grid, handle, total, mode):
    weeks = len(grid)
    width = LABEL_PADDING_LEFT + weeks * (CELL_SIZE + CELL_GAP)
    height = LABEL_PADDING_TOP + 7 * (CELL_SIZE + CELL_GAP) + 20

    max_count = max((c for week in grid for _d, c in week), default=0)

    parts = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Helvetica, Arial, sans-serif">'
    )
    parts.append(f'<rect width="100%" height="100%" fill="#0d1117" />')

    label = "accepted solutions" if mode == "ac" else "submissions"
    parts.append(
        f'<text x="{LABEL_PADDING_LEFT}" y="14" font-size="11" fill="#8b949e">'
        f'{total} {label} on Codeforces (@{handle}) in the last year</text>'
    )

    # Month labels: show a month name above the first week that starts a new month
    last_month = None
    for w_idx, week in enumerate(grid):
        first_day = week[0][0]
        if first_day.day <= 7 and first_day.month != last_month:
            x = LABEL_PADDING_LEFT + w_idx * (CELL_SIZE + CELL_GAP)
            parts.append(
                f'<text x="{x}" y="{LABEL_PADDING_TOP - 8}" font-size="9" fill="#8b949e">'
                f'{MONTH_NAMES[first_day.month - 1]}</text>'
            )
            last_month = first_day.month

    # Weekday labels
    for day_idx, wd_label in WEEKDAY_LABELS.items():
        y = LABEL_PADDING_TOP + day_idx * (CELL_SIZE + CELL_GAP) + CELL_SIZE - 2
        parts.append(f'<text x="0" y="{y}" font-size="9" fill="#8b949e">{wd_label}</text>')

    # Cells
    for w_idx, week in enumerate(grid):
        for d_idx, (date, count) in enumerate(week):
            x = LABEL_PADDING_LEFT + w_idx * (CELL_SIZE + CELL_GAP)
            y = LABEL_PADDING_TOP + d_idx * (CELL_SIZE + CELL_GAP)
            color = color_for_count(count, max_count)
            title = f"{count} {label} on {date.strftime('%b %d, %Y')}"
            parts.append(
                f'<rect x="{x}" y="{y}" width="{CELL_SIZE}" height="{CELL_SIZE}" '
                f'rx="2" ry="2" fill="{color}"><title>{title}</title></rect>'
            )

    parts.append("</svg>")
    return "\n".join(parts)


def main():
    submissions = fetch_submissions(CF_HANDLE)
    counts = bucket_by_day(submissions, CF_MODE)
    grid = build_grid(counts, WEEKS)
    total = sum(c for week in grid for _d, c in week)
    svg = render_svg(grid, CF_HANDLE, total, CF_MODE)

    with open(OUTPUT_PATH, "w") as f:
        f.write(svg)

    print(f"Wrote {OUTPUT_PATH}: {total} {'accepted solutions' if CF_MODE == 'ac' else 'submissions'} "
          f"across {WEEKS} weeks for handle '{CF_HANDLE}'.")


if __name__ == "__main__":
    main()
