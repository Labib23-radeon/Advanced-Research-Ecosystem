"""Interactive Terminal & Web Studio Launcher for Advanced Research Studio."""
import argparse
import sys
import threading
import time
import urllib.request
import webbrowser
from typing import Any, Dict, Optional

import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if sys.stdout.encoding != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr.encoding != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich import box

from core.agent_engine import LocalResearchAgent
from core.config import settings
from core.llm_providers import detect_lan_ip
from tools.local_scraper import scrape_page
from tools.local_search import web_search

console = Console(safe_box=True)


def print_banner(agent: LocalResearchAgent) -> None:
    """Display startup banner and environment info."""
    console.print("\n[bold cyan]+==============================================================+[/bold cyan]")
    console.print("[bold cyan]|           ADVANCED AI RESEARCH AGENT STUDIO                  |[/bold cyan]")
    console.print("[bold cyan]|      Local Ollama • Hybrid OpenAI APIs • Offline Fact Mode   |[/bold cyan]")
    console.print("[bold cyan]+==============================================================+[/bold cyan]\n")

    engine_info = agent.get_active_engine_info()
    status_style = "green" if engine_info.get("ready") else "yellow"

    info_table = Table(show_header=False, box=None)
    info_table.add_row("[bold]Active Engine:[/bold]", f"[{status_style}]{engine_info.get('label')}[/{status_style}]")
    info_table.add_row("[bold]Details:[/bold]", f"[dim]{engine_info.get('detail')}[/dim]")
    info_table.add_row("[bold]Ollama Host:[/bold]", f"[cyan]{agent.host}[/cyan]")
    info_table.add_row("[bold]Embeddings:[/bold]", f"[blue]{settings.embedding_model_name}[/blue]")
    info_table.add_row("[bold]Outputs Path:[/bold]", f"[dim]{settings.output_dir}[/dim]")

    console.print(Panel(info_table, title="[bold]System Configuration[/bold]", border_style="cyan", box=box.ASCII))
    console.print("[dim]Type a topic to begin autonomous research, or type [bold]/help[/bold] for command palette.[/dim]\n")


def display_step(step_data: Dict[str, Any]) -> None:
    """Render a step in the ReAct loop."""
    step = step_data.get("step", 1)
    thought = step_data.get("thought", "")
    action = step_data.get("action", "")
    action_input = step_data.get("action_input", {})
    obs = step_data.get("observation", "")

    content = (
        f"[bold cyan][THOUGHT][/bold cyan] {thought}\n\n"
        f"[bold yellow][ACTION][/bold yellow] [bold]{action}[/bold]\n"
        f"[bold]Input:[/bold] [dim]{action_input}[/dim]\n\n"
        f"[bold green][OBSERVATION][/bold green]\n{obs[:600]}"
        + (f"\n[dim]... (+{len(obs) - 600} characters)[/dim]" if len(obs) > 600 else "")
    )
    console.print(Panel(content, title=f"[bold]ReAct Step {step}[/bold]", border_style="blue", box=box.ASCII, expand=False))


def run_single_research(
    topic: str,
    pdf_path: Optional[str] = None,
    model_name: Optional[str] = None,
) -> None:
    """Execute a full research cycle and display the resulting report."""
    agent = LocalResearchAgent(
        model_name=model_name,
        on_step_callback=display_step,
    )

    console.print(f"\n[bold green][START] Initiating Autonomous Research for:[/bold green] [bold white]'{topic}'[/bold white]")
    if pdf_path:
        console.print(f"[bold blue][DOC] Preloading Local Document:[/bold blue] {pdf_path}")

    start_time = time.time()
    with console.status("[bold green]Agent is planning and investigating...[/bold green]"):
        try:
            report_text, report_file = agent.research(topic=topic, initial_pdf=pdf_path)
        except Exception as exc:
            console.print(f"\n[bold red][ERROR] Error during research:[/bold red] {exc}")
            return

    elapsed = time.time() - start_time
    console.print(f"\n[bold green][DONE] Research Completed in {elapsed:.1f}s![/bold green]")
    console.print(f"[bold cyan][FILE] Saved Report to:[/bold cyan] [underline]{report_file}[/underline]\n")
    console.print(Panel(Markdown(report_text), title="[bold]Generated Research Report[/bold]", border_style="green", box=box.ASCII))


def interactive_cli() -> None:
    """Interactive REPL terminal for the research agent."""
    agent = LocalResearchAgent(on_step_callback=display_step)
    print_banner(agent)

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]ResearchAgent[/bold cyan] >").strip()
            if not user_input:
                continue

            if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
                console.print("[yellow]Shutting down Advanced Research Agent. Goodbye![/yellow]")
                break

            elif user_input.lower() == "/help":
                table = Table(title="Agent Commands", border_style="cyan", box=box.ASCII)
                table.add_column("Command", style="bold green")
                table.add_column("Description")
                table.add_row("<any text>", "Start autonomous research on that topic")
                table.add_row("/model <name>", "Switch active Ollama model (e.g. /model qwen2.5:7b)")
                table.add_row("/pdf <path>", "Ingest local PDF/DOCX/TXT/MD/CSV into vector memory")
                table.add_row("/search <query>", "Run multi-engine web search directly")
                table.add_row("/scrape <url>", "Scrape and extract clean text from URL")
                table.add_row("/memory", "Check vector database chunk count")
                table.add_row("/clear", "Clear vector database memory")
                table.add_row("/status", "Recheck active AI engine and models")
                table.add_row("/exit", "Exit the agent")
                console.print(table)

            elif user_input.lower().startswith("/model"):
                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    new_model = parts[1].strip()
                    agent.set_model(new_model)
                    console.print(f"[green]Active model switched to:[/green] [bold]{new_model}[/bold]")
                else:
                    console.print(f"[cyan]Current model:[/cyan] {agent.model_name}")

            elif user_input.lower().startswith("/pdf"):
                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    path_str = parts[1].strip().strip("\"'")
                    with console.status(f"Loading and chunking '{path_str}'..."):
                        res = agent.execute_tool("load_pdf", {"file_path": path_str})
                    console.print(Panel(res, title="Document Ingestion", border_style="blue", box=box.ASCII))
                else:
                    console.print("[yellow]Usage: /pdf <path/to/document.pdf|docx|txt|csv>[/yellow]")

            elif user_input.lower().startswith("/search"):
                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    q = parts[1].strip()
                    with console.status(f"Searching for '{q}'..."):
                        res = web_search(q)
                    console.print(Panel(res, title=f"Search Results: {q}", border_style="yellow", box=box.ASCII))
                else:
                    console.print("[yellow]Usage: /search <query>[/yellow]")

            elif user_input.lower().startswith("/scrape"):
                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    u = parts[1].strip()
                    with console.status(f"Scraping '{u}'..."):
                        res = scrape_page(u)
                    console.print(Panel(res, title=f"Scraped Page: {u}", border_style="magenta", box=box.ASCII))
                else:
                    console.print("[yellow]Usage: /scrape <https://...>[/yellow]")

            elif user_input.lower() == "/memory":
                count = agent.vector_store.count()
                console.print(f"[cyan]Stored chunks in Vector DB:[/cyan] [bold]{count}[/bold]")

            elif user_input.lower() == "/clear":
                agent.vector_store.clear()
                console.print("[green]Vector store memory cleared successfully.[/green]")

            elif user_input.lower() == "/status":
                info = agent.get_active_engine_info()
                style = "green" if info.get("ready") else "yellow"
                console.print(f"[{style}]{info.get('label')} - {info.get('detail')}[/{style}]")

            else:
                run_single_research(topic=user_input, model_name=agent.model_name)

        except KeyboardInterrupt:
            console.print("\n[yellow]Operation cancelled by user.[/yellow]")
        except Exception as exc:
            console.print(f"\n[bold red]Unexpected error:[/bold red] {exc}")


def check_or_find_free_port(host: str, starting_port: int, max_trials: int = 15) -> int:
    """Check if port is available; if bound, locate next free port."""
    import socket
    bind_host = "0.0.0.0" if host == "0.0.0.0" else "127.0.0.1"
    for p in range(starting_port, starting_port + max_trials):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((bind_host, p))
                return p
            except OSError:
                continue
    return starting_port


def _open_browser_when_ready(url: str, check_port: int) -> None:
    """Wait briefly until FastAPI responds on /api/status before opening browser cleanly."""
    probe_url = f"http://127.0.0.1:{check_port}/api/status"
    for _ in range(40):
        try:
            with urllib.request.urlopen(probe_url, timeout=1.0) as resp:
                if resp.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.35)


def run_web_server(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = False) -> None:
    """Launch the Advanced Research Studio FastAPI server."""
    import uvicorn
    chosen_port = check_or_find_free_port(host, port)
    if chosen_port != port:
        console.print(f"[yellow][NOTICE] Port {port} is busy. Automatically switched to free port {chosen_port}.[/yellow]")

    local_url = f"http://127.0.0.1:{chosen_port}"
    lan_ip = detect_lan_ip()
    lan_url = f"http://{lan_ip}:{chosen_port}"

    console.print("\n[bold cyan]+==============================================================+[/bold cyan]")
    console.print("[bold cyan]|       ADVANCED RESEARCH STUDIO - WEB WORKSTATION             |[/bold cyan]")
    console.print(f"[bold cyan]|   Local URL:   {local_url:<46}|[/bold cyan]")
    if host == "0.0.0.0" and lan_ip != "127.0.0.1":
        console.print(f"[bold cyan]|   Network URL: {lan_url:<46}|[/bold cyan]")
    console.print("[bold cyan]+==============================================================+[/bold cyan]\n")

    if open_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(local_url, chosen_port),
            daemon=True,
        ).start()

    console.print(f"[bold green]Starting Studio on[/bold green] [bold underline]{local_url}[/bold underline] (Press Ctrl+C to stop)...")
    uvicorn.run("web_app:app", host=host, port=chosen_port, log_level="info")


def main() -> None:
    """CLI Entrypoint supporting Web Studio, LAN access, Auto-Open, Single Query, and REPL."""
    parser = argparse.ArgumentParser(description="Advanced Research Studio — Local-First & Hybrid AI Research Workspace")
    parser.add_argument("--ui", "--web", action="store_true", help="Launch the Web Studio application")
    parser.add_argument("--open", action="store_true", help="Open browser automatically once server is ready")
    parser.add_argument("--lan", action="store_true", help="Bind 0.0.0.0 so devices on your local Wi-Fi can connect")
    parser.add_argument("--port", type=int, default=8080, help="Port for the Web UI server (default: 8080)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host for the Web UI server (default: 127.0.0.1)")
    parser.add_argument("--topic", type=str, help="Research topic or question to run non-interactively")
    parser.add_argument("--pdf", type=str, help="Optional path to a local document (.pdf/.docx/.txt/.md/.csv)")
    parser.add_argument("--model", type=str, default=None, help="Ollama model name (default: llama3.2:3b)")

    args = parser.parse_args()
    effective_host = "0.0.0.0" if args.lan else args.host

    if args.ui:
        run_web_server(host=effective_host, port=args.port, open_browser=args.open)
    elif args.topic:
        run_single_research(topic=args.topic, pdf_path=args.pdf, model_name=args.model)
    else:
        interactive_cli()


if __name__ == "__main__":
    main()
