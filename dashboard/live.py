import argparse
import time
import requests
from datetime import datetime

from rich.console   import Console
from rich.table     import Table
from rich.panel     import Panel
from rich.columns   import Columns
from rich.text      import Text
from rich.live      import Live
from rich.layout    import Layout
from rich           import box

API     = "http://localhost:8000"
STORE   = "ST1008"
console = Console()

def fetch(endpoint: str) -> dict | None:
    try:
        r = requests.get(f"{API}{endpoint}", timeout=3)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def build_metrics_panel(data: dict | None) -> Panel:
    if not data:
        return Panel("[red]API unreachable[/red]", title="Metrics")

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column("Metric",  style="bold cyan",  width=22)
    t.add_column("Value",   style="bold white",  width=16)

    visitors = data.get("unique_visitors", 0)
    rate     = data.get("conversion_rate", 0.0)
    queue    = data.get("queue_depth", 0)
    abandon  = data.get("abandonment_rate", 0.0)
    date     = data.get("date", "—")

    rate_colour = "green" if rate > 0.15 else "yellow" if rate > 0.05 else "red"
    q_colour    = "red"   if queue >= 5  else "yellow" if queue >= 3   else "green"

    t.add_row("Date",              date)
    t.add_row("Unique Visitors",   str(visitors))
    t.add_row("Conversion Rate",   f"[{rate_colour}]{rate:.1%}[/{rate_colour}]")
    t.add_row("Queue Depth",       f"[{q_colour}]{queue}[/{q_colour}]")
    t.add_row("Abandonment Rate",  f"{abandon:.1%}")

    return Panel(t, title="[bold]📊 Live Metrics[/bold]", border_style="blue")


def build_funnel_panel(data: dict | None) -> Panel:
    if not data:
        return Panel("[red]—[/red]", title="Funnel")

    t = Table(box=box.SIMPLE, padding=(0, 1))
    t.add_column("Stage",    style="cyan",  width=16)
    t.add_column("Count",    justify="right", width=8)
    t.add_column("Drop-off", justify="right", width=10)

    for stage in data.get("stages", []):
        drop = stage["drop_off_pct"]
        drop_colour = "red" if drop > 50 else "yellow" if drop > 20 else "green"
        t.add_row(
            stage["stage"].replace("_", " ").title(),
            str(stage["count"]),
            f"[{drop_colour}]{drop:.1f}%[/{drop_colour}]"
        )

    return Panel(t, title="[bold]🔻 Conversion Funnel[/bold]", border_style="blue")


def build_heatmap_panel(data: dict | None) -> Panel:
    if not data or not data.get("zones"):
        return Panel("[dim]No zone data[/dim]", title="Heatmap")

    t = Table(box=box.SIMPLE, padding=(0, 1))
    t.add_column("Zone",       style="cyan",  width=16)
    t.add_column("Visits",     justify="right", width=8)
    t.add_column("Avg Dwell",  justify="right", width=12)
    t.add_column("Score",      width=24)

    for zone in data["zones"]:
        score  = zone["normalized_score"]
        filled = int(score / 5)
        bar    = "█" * filled + "░" * (20 - filled)
        colour = "green" if score > 60 else "yellow" if score > 30 else "dim white"
        dwell_s = zone["avg_dwell_ms"] / 1000

        t.add_row(
            zone["zone_id"].replace("_", " "),
            str(zone["visit_count"]),
            f"{dwell_s:.1f}s",
            f"[{colour}]{bar}[/{colour}] {score:.0f}"
        )

    return Panel(t, title="[bold]🗺  Zone Heatmap[/bold]", border_style="blue")


def build_anomalies_panel(data: dict | None) -> Panel:
    if not data:
        return Panel("[red]—[/red]", title="Anomalies")

    anomalies = data.get("anomalies", [])
    if not anomalies:
        return Panel(
            "[green]✓ No active anomalies[/green]",
            title="[bold]⚠  Anomalies[/bold]",
            border_style="green"
        )

    t = Table(box=box.SIMPLE, padding=(0, 1))
    t.add_column("Severity", width=10)
    t.add_column("Type",     style="bold", width=24)
    t.add_column("Action",   width=40)

    colours = {"CRITICAL": "red", "WARN": "yellow", "INFO": "blue"}

    for a in anomalies:
        sev = a["severity"]
        col = colours.get(sev, "white")
        t.add_row(
            f"[{col}]{sev}[/{col}]",
            a["anomaly_type"].replace("_", " "),
            a["suggested_action"][:60] + "…"
            if len(a["suggested_action"]) > 60
            else a["suggested_action"]
        )

    return Panel(t, title="[bold]⚠  Active Anomalies[/bold]", border_style="yellow")


def build_health_panel(data: dict | None) -> Panel:
    if not data:
        return Panel("[red]API unreachable[/red]", title="Health")

    status = data.get("status", "unknown")
    colour = "green" if status == "healthy" else "red"
    feeds  = data.get("store_feeds", {})
    stale  = data.get("stale_stores", [])

    lines  = [f"[{colour}]API: {status.upper()}[/{colour}]"]
    for store_id, feed in feeds.items():
        feed_status = feed.get("status", "UNKNOWN")
        ts          = feed.get("last_event_timestamp", "none")
        f_colour    = "green" if feed_status == "OK" else "yellow"
        lines.append(f"[{f_colour}]{store_id}: {feed_status}[/{f_colour}] — {ts}")

    return Panel(
        "\n".join(lines),
        title="[bold]❤  System Health[/bold]",
        border_style=colour
    )


def render_dashboard(store_id: str) -> Layout:
    metrics   = fetch(f"/stores/{store_id}/metrics")
    funnel    = fetch(f"/stores/{store_id}/funnel")
    heatmap   = fetch(f"/stores/{store_id}/heatmap")
    anomalies = fetch(f"/stores/{store_id}/anomalies")
    health    = fetch("/health")

    now = datetime.now().strftime("%H:%M:%S")

    header = Panel(
        f"[bold cyan]Store Intelligence Dashboard[/bold cyan]  "
        f"[dim]Store: {store_id}  |  Updated: {now}[/dim]  "
        f"[dim]Ctrl+C to exit[/dim]",
        box=box.HORIZONTALS,
        border_style="cyan"
    )

    top_row    = Columns([build_metrics_panel(metrics),
                          build_funnel_panel(funnel)], equal=True)
    bottom_row = Columns([build_heatmap_panel(heatmap),
                          build_anomalies_panel(anomalies)], equal=True)

    from rich.console import Group
    return Group(header, top_row, bottom_row, build_health_panel(health))


def main():
    global API
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default=STORE)
    parser.add_argument("--api",   default=API)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    API = args.api

    console.print(f"\n[cyan]Starting dashboard for store [bold]{args.store}[/bold][/cyan]")
    console.print(f"[dim]Polling {args.api} every {args.interval}s[/dim]\n")
    console.print("[dim]Tip: Run 'python dashboard/replay.py' in another terminal[/dim]\n")

    with Live(render_dashboard(args.store), refresh_per_second=1,
              screen=True, console=console) as live:
        while True:
            try:
                live.update(render_dashboard(args.store))
                time.sleep(args.interval)
            except KeyboardInterrupt:
                break

    console.print("\n[green]Dashboard stopped.[/green]")


if __name__ == "__main__":
    main()