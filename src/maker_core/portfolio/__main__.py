"""Command shim only; importing maker_core.portfolio never loads IO adapters."""
from maker_core.runtime.portfolio_report import main

if __name__ == "__main__":
    raise SystemExit(main())
