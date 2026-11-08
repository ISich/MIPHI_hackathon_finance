"""Summary statistics calculated from a run's validated comparison data."""

TOP_PATHS_LIMIT = 20


def top_changed_paths(con) -> list[dict]:
    """Rank fields by distinct changed applications, counting array occurrences once per app."""
    rows = con.execute("""
        SELECT PATH, COUNT(DISTINCT APP_ID) AS changed_apps
        FROM comparison
        WHERE DIFF_FLAG = 1
        GROUP BY PATH
        ORDER BY changed_apps DESC, PATH ASC
        LIMIT ?
    """, [TOP_PATHS_LIMIT]).fetchall()
    return [{"path": path, "changed_apps": count} for path, count in rows]
