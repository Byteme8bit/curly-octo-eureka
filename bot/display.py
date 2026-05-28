from pathlib import Path

from colorama import Fore, Style, init

from bot.local_time import format_pacific
from bot.status import StatusSnapshot
from bot.trade_log import format_trade_route, pnl_label_for_trade, trade_narrative
from bot.ui_tokens import (
    ASSET_PALETTE as ASSET_COLORS,
    TerminalToken,
    asset_color,
    colorize as _c,
    pnl_color,
)

init(autoreset=True)


def _asset(name: str) -> str:
    return _c(name, asset_color(name))


def _money(value: float) -> str:
    return _c(f"${value:,.2f}", pnl_color(value))


class TerminalDisplay:
    WIDTH = 62

    def __init__(self) -> None:
        self._last_status_key: str | None = None
        self._status_since: str | None = None

    def _rule(self, char: str = "-") -> None:
        print(_c(char * self.WIDTH, Fore.LIGHTBLACK_EX))

    def _header(self, title: str) -> None:
        now = format_pacific()
        print()
        self._rule("=")
        print(_c(f"  {title}", Fore.WHITE + Style.BRIGHT))
        print(_c(f"  {now}", Fore.LIGHTBLACK_EX))
        self._rule("=")

    def _print_holdings(
        self,
        holdings: dict[str, float],
        usd_prices: dict[str, float],
    ) -> None:
        print(_c("  Holdings", Fore.WHITE + Style.BRIGHT))
        usd = holdings.get("USD", 0.0)
        if usd > 0:
            print(f"    {_asset('USD'):8}  {_money(usd):>12}  (cash)")
        has_crypto = False
        for asset, qty in sorted(holdings.items()):
            if asset == "USD" or qty <= 0:
                continue
            has_crypto = True
            price = usd_prices.get(asset, 0.0)
            value = qty * price
            print(
                f"    {_asset(asset):8}  {qty:>12,.4f}  @ {_money(price):>10}  "
                f"= {_money(value):>10}"
            )
        if not has_crypto and usd <= 0:
            print(_c("    (empty)", Fore.LIGHTBLACK_EX))
        print()

    def _print_considering(self, status: StatusSnapshot) -> None:
        print(_c("  Considering", Fore.WHITE + Style.BRIGHT))
        if status.considering:
            for line in status.considering[:5]:
                print(f"    {_c(line, Fore.LIGHTBLACK_EX)}")
        elif status.idle_reason:
            print(f"    {_c(status.idle_reason, Fore.YELLOW)}")
        else:
            print(_c("    (nothing queued)", Fore.LIGHTBLACK_EX))
        print()

    def startup(
        self,
        strategy: str,
        timeframe: str,
        interval: int,
        balances: dict,
        risk_note: str = "",
        usd_pairs: int = 0,
        cross_pairs: int = 0,
        log_dir: Path | None = None,
        log_file: Path | None = None,
        log_rotate_hours: int = 4,
        receipts_dir: Path | None = None,
        portfolio_summary: str | None = None,
        portfolio_file: Path | None = None,
    ) -> None:
        self._header("PAPER TRADING BOT")
        print(f"  Strategy   {_c(strategy, Fore.CYAN)}")
        print(f"  Timeframe  {timeframe}  |  Poll every {interval}s")
        print(f"  Markets    {usd_pairs} USD pairs + {cross_pairs} cross pairs")
        shown = {asset: qty for asset, qty in sorted(balances.items()) if qty > 0}
        print(f"  Portfolio  {shown}")
        if portfolio_summary:
            print(f"             {_c(portfolio_summary, Fore.LIGHTBLACK_EX)}")
        if portfolio_file:
            print(f"  Portfolio file  {_c(str(portfolio_file), Fore.LIGHTBLACK_EX)}")
        if risk_note:
            print(f"  Risk       {_c(risk_note, Fore.LIGHTBLACK_EX)}")
        if log_dir:
            print(f"  Logs       {_c(str(log_dir) + f' ({log_rotate_hours}-hour files)', Fore.LIGHTBLACK_EX)}")
            if log_file:
                print(f"  Current    {_c(log_file.name, Fore.LIGHTBLACK_EX)}")
        if receipts_dir:
            print(f"  Receipts   {_c(str(receipts_dir) + '/', Fore.LIGHTBLACK_EX)}")
        self._rule("=")
        print()

    def tick(
        self,
        portfolio: float,
        usd_prices: dict[str, float],
        holdings: dict[str, float],
        trades: list[dict],
        status: StatusSnapshot,
        status_changed: bool,
        status_since: str | None,
        elapsed: float = 0.0,
        poll_interval: int = 15,
        risk=None,
        baseline_pnl: float = 0.0,
        drawdown: float = 0.0,
    ) -> None:
        timing = _c(
            f"fetch {elapsed:.1f}s | next check in {max(0, poll_interval - elapsed):.0f}s",
            Fore.LIGHTBLACK_EX,
        )

        if trades or status_changed or self._last_status_key is None:
            self._header("PORTFOLIO" if not trades else "TRADE")
            print(f"  {timing}")
            print(f"  Total      {_money(portfolio)}  ", end="")
            print(_c(f"(PnL {baseline_pnl:+.2f} | drawdown {drawdown:.2%})", pnl_color(baseline_pnl)))
            if risk and risk.is_paused():
                print(f"  {_c(risk.pause_status(), Fore.RED + Style.BRIGHT)}")
            print()
            self._print_holdings(holdings, usd_prices)

            if trades:
                print(_c("  TRADE EXECUTED", Fore.GREEN + Style.BRIGHT))
                for trade in trades:
                    print(f"    {_c(trade_narrative(trade), Fore.WHITE)}")
                    print(f"      {_c(format_trade_route(trade), Fore.LIGHTBLACK_EX)}")
                    print(
                        f"      Fee: {_money(trade.get('fee_usd', 0))}  |  "
                        f"Gain/Loss: {pnl_label_for_trade(trade)}"
                    )
                    if trade.get("receipt_file"):
                        print(f"      Receipt: {_c(trade['receipt_file'], Fore.LIGHTBLACK_EX)}")
                print()
            elif status.mode in ("hold", "paused"):
                self._print_considering(status)
                if status.idle_reason and status.considering:
                    print(f"  Status     {_c(status.idle_reason, Fore.YELLOW)}")
                    print()

            self._rule("=")
        else:
            since = status_since or format_pacific()
            print()
            print(
                f"  {_c('Holding pattern', Fore.YELLOW)} — "
                f"{_c(f'no changes since {since}', Fore.LIGHTBLACK_EX)}"
            )
            print(f"  {timing}  |  Total {_money(portfolio)}  ", end="")
            print(_c(f"(PnL {baseline_pnl:+.2f})", pnl_color(baseline_pnl)))
            if risk and risk.is_paused():
                print(f"  {_c(risk.pause_status(), Fore.RED + Style.BRIGHT)}")
            if status.considering:
                preview = status.considering[0]
                if len(status.considering) > 1:
                    preview += f" (+{len(status.considering) - 1} more)"
                print(f"  Still watching: {_c(preview, Fore.LIGHTBLACK_EX)}")

        self._last_status_key = status.summary_key
