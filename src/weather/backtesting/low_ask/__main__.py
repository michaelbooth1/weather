"""Dedicated process entry point: block network and trading dependencies first."""

from .isolation import install_boundary

install_boundary()

from .runner import main

raise SystemExit(main())
