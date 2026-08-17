"""Fabric Studio test suite (stdlib unittest — no extra packages to install).

    python3 -m unittest discover -s tests -v

Every test runs against a throwaway DATA_DIR and the mock VTON provider, so
the suite never touches real data and never spends FASHN credits.
"""
