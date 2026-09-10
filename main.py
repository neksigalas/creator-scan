"""
CreatorScan — CLI Entry Point
Micro-creator discovery tool (2K–100K followers)

Usage:
  python main.py scan  --platform youtube --niche Gaming --min 2000 --max 100000
  python main.py scan  --platform twitch  --niche Gaming
  python main.py scan  --platform all     --niche Fitness
  python main.py list  --niche Gaming --platform youtube --email
  python main.py stats
  python main.py export --output creators.csv --niche Gaming
  python main.py niches
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich import box

load_dotenv()
console = Console()

# ── Lazy imports (only if API keys are present) ─────────────────────────────
def get_youtube_collector():
    from collectors.youtube import YouTubeCollector
    key = os.getenv("YOUTUBE_API_KEY", "")
    if not key or key == "YOUR_YOUTUBE_API_KEY_HERE":
        console.print("[red]❌ YOUTUBE_API_KEY δεν έχει οριστεί στο .env[/red]")
        console.print("[dim]  → Πάρε δωρεάν key: https://console.cloud.google.com/[/dim]")
        return None
    return YouTubeCollector(key)


def get_twitch_collector():
    from collectors.twitch import TwitchCollector
    cid = os.getenv("TWITCH_CLIENT_ID", "")
    sec = os.getenv("TWITCH_CLIENT_SECRET", "")
    if not cid or cid == "YOUR_TWITCH_CLIENT_ID_HERE":
        console.print("[red]❌ TWITCH_CLIENT_ID δεν έχει οριστεί στο .env[/red]")
        console.print("[dim]  → Πάρε δωρεάν: https://dev.twitch.tv/console/apps[/dim]")
        return None
    return TwitchCollector(cid, sec)


def get_tiktok_collector():
    try:
        from collectors.tiktok import TikTokCollector
        return TikTokCollector(headless=True)
    except ImportError as e:
        console.print(f"[red]❌ {e}[/red]")
        return None


def get_instagram_collector():
    try:
        from collectors.instagram import InstagramCollector
        return InstagramCollector(headless=True)
    except ImportError as e:
        console.print(f"[red]❌ {e}[/red]")
        return None


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_scan(args):
    """Σκανάρει platforms και αποθηκεύει creators στη DB."""
    import db
    db.init_db()

    from processors.niche import NICHE_KEYWORDS
    valid_niches = list(NICHE_KEYWORDS.keys())

    if args.niche and args.niche not in valid_niches and args.niche != "all":
        console.print(f"[red]❌ Άγνωστη niche: {args.niche}[/red]")
        console.print(f"[dim]Διαθέσιμες: {', '.join(valid_niches)}[/dim]")
        sys.exit(1)

    niches_to_scan = valid_niches if args.niche == "all" else [args.niche]
    platforms_to_scan = (
        ["youtube", "twitch", "tiktok", "instagram"] if args.platform == "all"
        else [args.platform]
    )

    total_new = 0
    total_updated = 0

    console.print(Panel(
        f"[bold cyan]CreatorScan[/bold cyan] — Scanning\n"
        f"Platform: [yellow]{', '.join(platforms_to_scan)}[/yellow]  "
        f"Niche: [yellow]{', '.join(niches_to_scan)}[/yellow]\n"
        f"Followers: [green]{args.min:,} – {args.max:,}[/green]",
        box=box.ROUNDED,
    ))

    for niche in niches_to_scan:
        console.print(f"\n[bold]📂 Niche: {niche}[/bold]")

        for platform in platforms_to_scan:
            console.print(f"  🌐 Platform: [cyan]{platform}[/cyan]")

            if platform == "youtube":
                collector = get_youtube_collector()
                if not collector:
                    continue
                gen = collector.scan_niche(
                    niche,
                    min_followers=args.min,
                    max_followers=args.max,
                    max_per_query=args.max_per_query,
                )
            elif platform == "twitch":
                collector = get_twitch_collector()
                if not collector:
                    continue
                gen = collector.scan_niche(
                    niche,
                    min_followers=args.min,
                    max_followers=args.max,
                    max_per_category=args.max_per_query,
                )
            elif platform == "tiktok":
                collector = get_tiktok_collector()
                if not collector:
                    continue
                gen = collector.scan_niche(
                    niche,
                    min_followers=args.min,
                    max_followers=args.max,
                    max_per_query=args.max_per_query,
                )
            elif platform == "instagram":
                collector = get_instagram_collector()
                if not collector:
                    continue
                gen = collector.scan_niche(
                    niche,
                    min_followers=args.min,
                    max_followers=args.max,
                    max_per_query=args.max_per_query,
                )
            else:
                console.print(f"[yellow]⚠ Platform '{platform}' δεν υποστηρίζεται ακόμα[/yellow]")
                continue

            niche_new = 0
            niche_updated = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task(f"  Collecting from {platform}...", total=None)

                for creator in gen:
                    is_new = db.upsert_creator(creator)
                    if is_new:
                        niche_new += 1
                    else:
                        niche_updated += 1
                    progress.update(task, description=(
                        f"  [green]↑{niche_new} new[/green] "
                        f"[dim]{niche_updated} updated[/dim] — "
                        f"[bold]{creator['display_name']}[/bold] "
                        f"({creator['followers']:,} followers)"
                    ))

            console.print(
                f"  ✅ {platform}: "
                f"[green]+{niche_new} νέοι[/green]  "
                f"[dim]{niche_updated} updated[/dim]"
            )
            total_new += niche_new
            total_updated += niche_updated

    console.print(f"\n[bold green]🏁 Scan ολοκληρώθηκε![/bold green]")
    console.print(f"   Νέοι creators: [green]{total_new}[/green]")
    console.print(f"   Updated:       [dim]{total_updated}[/dim]")

    # Show quick stats
    stats = db.get_stats()
    console.print(f"   Σύνολο στη DB: [bold]{stats['total']}[/bold]")


def cmd_list(args):
    """Εμφανίζει creators με φίλτρα."""
    import db
    db.init_db()

    creators = db.query_creators(
        platform=args.platform if args.platform != "all" else None,
        niche=args.niche,
        min_followers=args.min,
        max_followers=args.max,
        has_email=True if args.email else None,
        language=args.lang,
        limit=args.limit,
    )

    if not creators:
        console.print("[yellow]Δεν βρέθηκαν creators με αυτά τα φίλτρα.[/yellow]")
        console.print("[dim]Δοκίμασε πρώτα: python main.py scan --platform youtube --niche Gaming[/dim]")
        return

    table = Table(
        title=f"Creators ({len(creators)} results)",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
    )
    table.add_column("Platform",     style="cyan",   width=9)
    table.add_column("Username",     style="bold",   width=22)
    table.add_column("Followers",    style="green",  width=10, justify="right")
    table.add_column("Niche",        style="yellow", width=14)
    table.add_column("Lang",         width=5)
    table.add_column("Email",        style="dim",    width=6, justify="center")
    table.add_column("URL",          style="blue dim", width=35, no_wrap=True)

    for c in creators:
        table.add_row(
            c["platform"],
            c["display_name"] or c["username"],
            f"{c['followers']:,}",
            c["niche"] or "—",
            c["language"] or "—",
            "✉" if c["has_email"] else "",
            c["profile_url"] or "",
        )

    console.print(table)
    console.print(f"[dim]Showing {len(creators)} of possibly more. Use --limit N to change.[/dim]")


def cmd_stats(args):
    """Εμφανίζει συνολικά στατιστικά."""
    import db
    db.init_db()

    stats = db.get_stats()

    console.print(Panel(
        f"[bold]📊 CreatorScan Database Stats[/bold]",
        box=box.ROUNDED,
    ))
    console.print(f"  Σύνολο creators: [bold green]{stats['total']:,}[/bold green]")
    console.print(f"  Με email:        [bold yellow]{stats['with_email']:,}[/bold yellow]")

    console.print("\n  [bold]Ανά Platform:[/bold]")
    for platform, cnt in stats["by_platform"].items():
        bar = "█" * min(30, cnt // max(1, stats["total"] // 30))
        console.print(f"  {platform:<12} {cnt:>6,}  [cyan]{bar}[/cyan]")

    console.print("\n  [bold]Top Niches:[/bold]")
    for niche, cnt in stats["by_niche"].items():
        bar = "█" * min(25, cnt // max(1, stats["total"] // 25))
        console.print(f"  {niche:<18} {cnt:>6,}  [yellow]{bar}[/yellow]")


def cmd_export(args):
    """Εξάγει creators σε CSV."""
    import db
    db.init_db()

    kwargs = dict(
        min_followers=args.min,
        max_followers=args.max,
    )
    if args.platform and args.platform != "all":
        kwargs["platform"] = args.platform
    if args.niche:
        kwargs["niche"] = args.niche
    if args.email:
        kwargs["has_email"] = True

    count = db.export_csv(args.output, **kwargs)
    console.print(f"[green]✅ {count:,} creators exported → {args.output}[/green]")


def cmd_niches(args):
    """Εμφανίζει όλες τις διαθέσιμες niches."""
    from processors.niche import NICHE_KEYWORDS
    table = Table(title="Διαθέσιμες Niches", box=box.SIMPLE_HEAVY)
    table.add_column("Niche", style="bold yellow", width=20)
    table.add_column("Keywords (sample)", style="dim", width=60)
    for niche, kws in NICHE_KEYWORDS.items():
        table.add_row(niche, ", ".join(kws[:8]) + "...")
    console.print(table)


# ── Parser ────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="creator-scan",
        description="🔍 CreatorScan — Micro-creator discovery (2K–100K followers)",
    )
    sub = p.add_subparsers(dest="command")

    # ── scan ──
    sp = sub.add_parser("scan", help="Σκανάρισε creators από platforms")
    sp.add_argument("--platform", default="youtube",
                    choices=["youtube", "twitch", "tiktok", "instagram", "all"],
                    help="Platform (default: youtube)")
    sp.add_argument("--niche", default="Gaming",
                    help="Niche category ή 'all' (default: Gaming)")
    sp.add_argument("--min", type=int, default=2_000,
                    help="Min followers (default: 2000)")
    sp.add_argument("--max", type=int, default=100_000,
                    help="Max followers (default: 100000)")
    sp.add_argument("--max-per-query", type=int, default=50,
                    help="Max results per search query (default: 50)")

    # ── list ──
    lp = sub.add_parser("list", help="Εμφάνισε creators από τη DB")
    lp.add_argument("--platform", default="all", help="Platform filter")
    lp.add_argument("--niche", default=None, help="Niche filter")
    lp.add_argument("--min", type=int, default=2_000)
    lp.add_argument("--max", type=int, default=100_000)
    lp.add_argument("--email", action="store_true", help="Μόνο creators με email")
    lp.add_argument("--lang", default=None, help="Language filter (π.χ. el, en)")
    lp.add_argument("--limit", type=int, default=50)

    # ── stats ──
    sub.add_parser("stats", help="Στατιστικά DB")

    # ── export ──
    ep = sub.add_parser("export", help="Εξαγωγή σε CSV")
    ep.add_argument("--output", default="creators_export.csv")
    ep.add_argument("--platform", default="all")
    ep.add_argument("--niche", default=None)
    ep.add_argument("--min", type=int, default=2_000)
    ep.add_argument("--max", type=int, default=100_000)
    ep.add_argument("--email", action="store_true")

    # ── niches ──
    sub.add_parser("niches", help="Εμφάνισε διαθέσιμες niches")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        console.print("\n[dim]Παράδειγμα:[/dim]")
        console.print("  python main.py scan --platform youtube --niche Gaming")
        console.print("  python main.py list --niche Gaming --email")
        console.print("  python main.py stats")
        sys.exit(0)

    dispatch = {
        "scan":   cmd_scan,
        "list":   cmd_list,
        "stats":  cmd_stats,
        "export": cmd_export,
        "niches": cmd_niches,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
