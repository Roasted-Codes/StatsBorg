"""PostgreSQL storage for statsborg-master."""
import json
import os
from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

from exports.db_export import Halo2Database, SCHEMA_SQL

DATABASE_URL = os.environ.get("DATABASE_URL", "")

EXTRA_SQL = """
ALTER TABLE games ADD COLUMN IF NOT EXISTS server_id VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_games_server ON games(server_id);
CREATE INDEX IF NOT EXISTS idx_games_timestamp_desc ON games(timestamp DESC);

CREATE TABLE IF NOT EXISTS servers (
    server_id     VARCHAR(64) PRIMARY KEY,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    spool_backlog INTEGER DEFAULT 0,
    matches_total INTEGER DEFAULT 0
);
"""

PRIVATE_MATCH_KEYS = {
    "scenario",
    "scenario_path",
    "internal_map",
    "internal_map_name",
}

LEADERBOARD_STATS = {
    "kills": "COALESCE(SUM(kills),0)",
    "deaths": "COALESCE(SUM(deaths),0)",
    "assists": "COALESCE(SUM(assists),0)",
    "suicides": "COALESCE(SUM(suicides),0)",
    "headshots": "COALESCE(SUM(headshots),0)",
    "games": "COUNT(*)",
    "kd": "ROUND(CAST(SUM(kills) AS numeric)/GREATEST(SUM(deaths),1),2)",
    "accuracy": "ROUND(AVG(accuracy_pct)::numeric,1)",
}


def _connect():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required for statsborg-master")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(DATABASE_URL)


def _json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _public_snapshot(raw: Any, fingerprint: str, server_id: Optional[str] = None) -> Dict[str, Any]:
    snapshot = dict(raw) if isinstance(raw, dict) else {}
    for key in PRIVATE_MATCH_KEYS:
        snapshot.pop(key, None)
    snapshot["filename"] = f"{fingerprint}.json"
    snapshot.setdefault("fingerprint", fingerprint)
    if server_id:
        snapshot["server_id"] = server_id
    return snapshot


def init_schema() -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
            cur.execute(EXTRA_SQL)
        conn.commit()
    finally:
        conn.close()


def ingest_match(snapshot: Dict[str, Any]) -> bool:
    """Insert one match snapshot, deduped by fingerprint."""
    db = Halo2Database(DATABASE_URL)
    try:
        imported = db.import_snapshot(snapshot)
        server_id = snapshot.get("server_id")
        fingerprint = snapshot.get("fingerprint")
        if imported and server_id and fingerprint:
            with db.conn.cursor() as cur:
                cur.execute(
                    "UPDATE games SET server_id = %s WHERE fingerprint = %s",
                    (server_id, fingerprint),
                )
                cur.execute(
                    """
                    INSERT INTO servers (server_id, last_seen, matches_total)
                    VALUES (%s, NOW(), 1)
                    ON CONFLICT (server_id) DO UPDATE
                        SET matches_total = servers.matches_total + 1,
                            last_seen = NOW()
                    """,
                    (server_id,),
                )
            db.conn.commit()
        return imported
    finally:
        db.close()


def record_heartbeat(server_id: str, spool_backlog: int = 0) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO servers (server_id, last_seen, spool_backlog)
                VALUES (%s, NOW(), %s)
                ON CONFLICT (server_id) DO UPDATE
                    SET last_seen = NOW(), spool_backlog = EXCLUDED.spool_backlog
                """,
                (server_id, spool_backlog),
            )
        conn.commit()
    finally:
        conn.close()


def get_all_games(limit: int = 500):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fingerprint, raw_json, server_id
                FROM games
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [
                _public_snapshot(raw, fingerprint, server_id)
                for fingerprint, raw, server_id in cur.fetchall()
            ]
    finally:
        conn.close()


def get_game(filename: str):
    fingerprint = filename[:-5] if filename.endswith(".json") else filename
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fingerprint, raw_json, server_id FROM games WHERE fingerprint = %s",
                (fingerprint,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return _public_snapshot(row[1], row[0], row[2])
    finally:
        conn.close()


def get_leaderboard(stat: str = "kills", limit: int = 25):
    expr = LEADERBOARD_STATS.get(stat, LEADERBOARD_STATS["kills"])
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT player_name,
                       COUNT(*) AS games,
                       COALESCE(SUM(kills),0) AS kills,
                       COALESCE(SUM(deaths),0) AS deaths,
                       COALESCE(SUM(assists),0) AS assists,
                       ROUND(CAST(SUM(kills) AS numeric)/GREATEST(SUM(deaths),1),2) AS kd,
                       {expr} AS value
                FROM players
                GROUP BY player_name
                ORDER BY value DESC NULLS LAST
                LIMIT %s
                """,
                (limit,),
            )
            columns = ["name", "games", "kills", "deaths", "assists", "kd", "value"]
            return [
                {key: _json_safe(value) for key, value in zip(columns, row)}
                for row in cur.fetchall()
            ]
    finally:
        conn.close()


def get_all_players():
    return get_leaderboard(stat="kills", limit=1000)


def get_player(name: str):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS games,
                       COALESCE(SUM(kills),0), COALESCE(SUM(deaths),0),
                       COALESCE(SUM(assists),0), COALESCE(SUM(suicides),0),
                       ROUND(CAST(SUM(kills) AS numeric)/GREATEST(SUM(deaths),1),2),
                       ROUND(AVG(accuracy_pct)::numeric,1)
                FROM players WHERE player_name = %s
                """,
                (name,),
            )
            row = cur.fetchone()
            if not row or row[0] == 0:
                return None
            career = {
                "name": name,
                "games": row[0],
                "kills": row[1],
                "deaths": row[2],
                "assists": row[3],
                "suicides": row[4],
                "kd_ratio": _json_safe(row[5]) if row[5] is not None else 0.0,
                "accuracy": _json_safe(row[6]) if row[6] is not None else 0.0,
            }
            cur.execute(
                """
                SELECT g.fingerprint, g.timestamp, g.gametype, g.map, g.variant,
                       p.kills, p.deaths, p.assists, p.place
                FROM players p
                JOIN games g ON g.id = p.game_id
                WHERE p.player_name = %s
                ORDER BY g.timestamp DESC
                LIMIT 50
                """,
                (name,),
            )
            career["games_list"] = [
                {
                    "filename": f"{r[0]}.json",
                    "timestamp": str(r[1]),
                    "gametype": r[2],
                    "map": r[3],
                    "variant": r[4],
                    "kills": r[5],
                    "deaths": r[6],
                    "assists": r[7],
                    "place": r[8],
                }
                for r in cur.fetchall()
            ]
            return career
    finally:
        conn.close()


def get_pvp(player: str):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT g.raw_json
                FROM games g
                JOIN players p ON p.game_id = g.id
                WHERE LOWER(p.player_name) = LOWER(%s) AND g.raw_json IS NOT NULL
                """,
                (player,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    kills_given = defaultdict(int)
    kills_received = defaultdict(int)
    target_lower = player.lower()

    for (raw,) in rows:
        game_data = raw if isinstance(raw, dict) else json.loads(raw)
        players = game_data.get("players", []) or []
        target_idx = next(
            (i for i, p in enumerate(players) if (p.get("name") or "").lower() == target_lower),
            None,
        )
        if target_idx is None:
            continue

        target_killed = players[target_idx].get("killed") or []
        for i, opponent in enumerate(players):
            if i == target_idx:
                continue
            opponent_name = opponent.get("name") or ""
            if not opponent_name:
                continue
            if i < len(target_killed):
                kills_given[opponent_name] += target_killed[i] or 0
            opponent_killed = opponent.get("killed") or []
            if target_idx < len(opponent_killed):
                kills_received[opponent_name] += opponent_killed[target_idx] or 0

    opponents = []
    for opponent in set(kills_given) | set(kills_received):
        kills = kills_given.get(opponent, 0)
        deaths = kills_received.get(opponent, 0)
        opponents.append({"name": opponent, "kills": kills, "deaths": deaths, "net": kills - deaths})
    opponents.sort(key=lambda item: item["kills"] + item["deaths"], reverse=True)
    return {"player": player, "opponents": opponents}


def list_servers():
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT server_id,
                       first_seen, last_seen, spool_backlog, matches_total,
                       EXTRACT(EPOCH FROM (NOW() - last_seen))::int AS seconds_since_seen
                FROM servers
                ORDER BY last_seen DESC
                """
            )
            rows = cur.fetchall()
            for row in rows:
                row["first_seen"] = str(row["first_seen"])
                row["last_seen"] = str(row["last_seen"])
            return rows
    finally:
        conn.close()
