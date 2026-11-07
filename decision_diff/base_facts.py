"""D4: canonical BaseFacts/BaseMembership derived from a completed mart.

No dataset-dependent paths, no HTTP, no authentication and no second DB driver.
The platform (D2) owns the per-run connection and calls ``materialize_base_facts``
exactly once during AGGREGATING, before publishing a run.

Input tables: normalized_union, comparison, segments (the existing stage-3
storage schema). Missing attributes are NOT synthesized into the absent slice.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# Keep identical names to docs/contracts/data.md. The representative fields in
# segments remain a D1/D2 policy to approve; this module does not reinterpret.
ATTRIBUTE_DIMS = (
    "PREFIX", "CLASS", "SUFFIX", "PATH", "ARRAY_KEY", "KEY",
    "VALUE_ADJUSTED", "SOURCE", "DIFF_FLAG", "CHANGE_TYPE",
)
SEGMENT_DIMS = (
    "DECISION_BEFORE", "DECISION_AFTER", "DECISION_CHANGED", "PRODUCTS",
    "TOP_OFFER_BEFORE", "TOP_OFFER_AFTER", "PARTNER_TYPE", "ROUTING_METHOD",
    "PD_MODEL_BEFORE", "PD_MODEL_AFTER", "CUTOFF_BEFORE", "CUTOFF_AFTER",
    "REJECT_REASON_BEFORE", "REJECT_REASON_AFTER",
    "SCORE_OKB_BEFORE", "SCORE_OKB_AFTER",
)
BASE_DIMS = (*ATTRIBUTE_DIMS, *SEGMENT_DIMS)


def _identifier(name: str) -> str:
    if name not in {"APP_ID", "fact_id", *BASE_DIMS}:
        raise ValueError(f"Unknown schema column: {name}")
    return '"' + name + '"'


def materialize_base_facts(connection: Any, *, replace: bool = False) -> dict[str, int]:
    """Materialize the fixed-grain facts and exact APP_ID memberships.

    Requires a single DuckDB writer; caller manages commit and run lifecycle.
    Intended for a *completed* normalized/comparison/segments artifact. No
    arbitrary SQL identifiers or filesystem paths come from a user request.

    Returns row counts; raises when normalized rows have no comparison match.
    This is an additive migration for existing stage-3 per-run databases.
    """
    exists = connection.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name IN ('base_facts', 'base_membership')"
    ).fetchone()[0]
    if exists and not replace:
        raise ValueError("Base facts already exist; use replace=True on a private writable run DB")

    # Create both new tables atomically where the DB supports transactions.
    connection.execute("BEGIN TRANSACTION")
    try:
        if replace:
            connection.execute("DROP TABLE IF EXISTS base_membership")
            connection.execute("DROP TABLE IF EXISTS base_facts")
        selected = [
            'n."APP_ID" AS "APP_ID"',
            *(f'n.{_identifier(c)} AS {_identifier(c)}' for c in
              ("PREFIX", "CLASS", "SUFFIX", "PATH", "ARRAY_KEY", "KEY")),
            'n."ADJUSTED_VALUE" AS "VALUE_ADJUSTED"',
            'n."SOURCE" AS "SOURCE"',
            'c."DIFF_FLAG" AS "DIFF_FLAG"',
            'c."CHANGE_TYPE" AS "CHANGE_TYPE"',
            *(f's.{_identifier(c)} AS {_identifier(c)}' for c in SEGMENT_DIMS),
        ]
        connection.execute(
            'CREATE TEMP TABLE _base_source AS SELECT DISTINCT ' + ', '.join(selected)
            + ' FROM normalized_union n INNER JOIN comparison c ON '
              'n.APP_ID = c.APP_ID AND n.PATH = c.PATH '
              'AND n.ARRAY_KEY = c.ARRAY_KEY '
              'INNER JOIN segments s ON s.APP_ID = n.APP_ID'
        )
        input_count = int(connection.execute(
            'SELECT COUNT(*) FROM normalized_union'
        ).fetchone()[0])
        valid_count = int(connection.execute(
            'SELECT COUNT(*) FROM _base_source'
        ).fetchone()[0])
        if input_count != valid_count:
            raise ValueError(
                f"Normalized rows differ from joined reporting rows: "
                f"normalized={input_count}, reporting={valid_count}; "
                "check uniqueness, comparison keys and segments"
            )
        dim_order = ', '.join(_identifier(c) for c in BASE_DIMS)
        connection.execute(
            'CREATE TEMP TABLE _base_ranked AS SELECT '
            f'DENSE_RANK() OVER (ORDER BY {dim_order}) AS fact_id, * '
            'FROM _base_source'
        )
        dim_projection = ', '.join(_identifier(c) for c in BASE_DIMS)
        connection.execute(
            f'CREATE TABLE base_facts AS SELECT fact_id, {dim_projection}, '
            'COUNT(DISTINCT APP_ID) AS CNT, CAST(fact_id AS VARCHAR) AS membership_ref '
            f'FROM _base_ranked GROUP BY fact_id, {dim_projection}'
        )
        connection.execute(
            'CREATE TABLE base_membership AS SELECT DISTINCT fact_id, APP_ID '
            'FROM _base_ranked'
        )
        connection.execute('DROP TABLE _base_ranked')
        connection.execute('DROP TABLE _base_source')
        connection.execute('CREATE INDEX idx_d4_membership_fact ON base_membership(fact_id)')
        connection.execute('CREATE INDEX idx_d4_membership_app ON base_membership(APP_ID)')
        # Exact, per-fact invariant. Do not test it by summing across facts.
        bad = int(connection.execute('''
            SELECT COUNT(*) FROM base_facts f LEFT JOIN (
                SELECT fact_id, COUNT(DISTINCT APP_ID) AS N
                FROM base_membership GROUP BY fact_id
            ) m USING (fact_id)
            WHERE f.CNT <> COALESCE(m.N, 0)
        ''').fetchone()[0])
        if bad:
            raise ValueError(f"Base membership invalid for {bad} facts")
        result = {
            "base_facts": int(connection.execute('SELECT COUNT(*) FROM base_facts').fetchone()[0]),
            "base_membership": int(connection.execute('SELECT COUNT(*) FROM base_membership').fetchone()[0]),
        }
        connection.execute("COMMIT")
        return result
    except Exception:
        connection.execute("ROLLBACK")
        raise


def ensure_schema(connection: Any) -> None:
    """Check that the finalized base tables are available to read-only queries."""
    for table in ("base_facts", "base_membership"):
        result = connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()[0]
        if not result:
            raise ValueError(f"Missing aggregated table: {table}")
