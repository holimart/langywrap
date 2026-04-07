"""DuckDB setup helpers for RAG and vector search."""

from __future__ import annotations

import subprocess
from pathlib import Path


def setup_duckdb(db_path: Path, with_vss: bool = True) -> bool:
    """Initialize DuckDB with optional VSS (vector similarity search) extension.

    Returns True on success.
    """
    try:
        import duckdb

        con = duckdb.connect(str(db_path))
        if with_vss:
            con.execute("INSTALL vss; LOAD vss;")
        con.close()
        return True
    except ImportError:
        # Fall back to CLI
        cmd = f"duckdb {db_path} -c \"INSTALL vss; LOAD vss;\""
        result = subprocess.run(cmd, shell=True, capture_output=True)
        return result.returncode == 0
    except Exception:
        return False


def inspect_duckdb(db_path: Path) -> dict:
    """Get basic info about a DuckDB database."""
    try:
        import duckdb

        con = duckdb.connect(str(db_path), read_only=True)
        tables = con.execute("SHOW TABLES").fetchall()
        info = {"tables": [t[0] for t in tables], "path": str(db_path)}
        con.close()
        return info
    except Exception as e:
        return {"error": str(e)}
