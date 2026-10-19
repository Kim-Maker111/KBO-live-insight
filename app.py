from __future__ import annotations

import json
import re
import time
from datetime import datetime
from html import unescape
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

KBO = "https://www.koreabaseball.com"
SCHEDULE_URL = f"{KBO}/ws/Schedule.asmx/GetScheduleList"
GAME_LIST_URL = f"{KBO}/ws/Main.asmx/GetKboGameList"
BOX_URL = f"{KBO}/ws/Schedule.asmx/GetBoxScoreScroll"
SCORE_URL = f"{KBO}/ws/Schedule.asmx/GetScoreBoardScroll"
RANK_URL = f"{KBO}/ws/Main.asmx/GetTeamRank"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{KBO}/Schedule/Schedule.aspx",
}
GAME_HEADERS = {
    **HEADERS,
    "Content-Type": "application/json; charset=UTF-8",
}
SERIES = {
    "regular": "0,9,6",
    "postseason": "3,4,5,7",
    "preseason": "1",
    "all": "0,1,3,4,5,6,7,9",
}
SERIES_SINGLE = {
    "regular": "0",
    "postseason": "3",
    "preseason": "1",
    "all": "0",
}
TEAM_NAMES = {
    "LG": "LG 트윈스", "KIA": "KIA 타이거즈", "HT": "KIA 타이거즈",
    "삼성": "삼성 라이온즈", "SS": "삼성 라이온즈", "SSG": "SSG 랜더스",
    "SK": "SSG 랜더스", "한화": "한화 이글스", "HH": "한화 이글스",
    "두산": "두산 베어스", "OB": "두산 베어스", "롯데": "롯데 자이언츠",
    "LT": "롯데 자이언츠", "KT": "KT 위즈", "NC": "NC 다이노스",
    "키움": "키움 히어로즈", "WO": "키움 히어로즈",
}
TEAM_API_CODES = {
    "LG": "LG", "LG 트윈스": "LG",
    "KIA": "HT", "KIA 타이거즈": "HT",
    "삼성": "SS", "삼성 라이온즈": "SS",
    "SSG": "SK", "SSG 랜더스": "SK",
    "한화": "HH", "한화 이글스": "HH",
    "두산": "OB", "두산 베어스": "OB",
    "롯데": "LT", "롯데 자이언츠": "LT",
    "KT": "KT", "KT 위즈": "KT",
    "NC": "NC", "NC 다이노스": "NC",
    "키움": "WO", "키움 히어로즈": "WO",
}
CACHE: dict[str, tuple[float, Any]] = {}

app = FastAPI(title="KBO Live Insight", version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")


def kst_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def cache_get(key: str):
    item = CACHE.get(key)
    if not item:
        return None
    if item[0] < time.time():
        CACHE.pop(key, None)
        return None
    return item[1]


def cache_set(key: str, value: Any, ttl: int = 25):
    CACHE[key] = (time.time() + ttl, value)
    return value


def parse_response_text(text: str) -> Any:
    """KBO occasionally appends an HTML error fragment after its JSON response."""
    text = text.strip().lstrip("\ufeff")
    decoder = json.JSONDecoder()
    for i, char in enumerate(text):
        if char in "[{":
            try:
                value, _ = decoder.raw_decode(text[i:])
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError("KBO 응답에서 JSON 데이터를 찾지 못했습니다.")


def post_json(url: str, payload: dict[str, Any], *, json_body: bool = False):
    try:
        if json_body:
            response = requests.post(
                url, json=payload, headers=GAME_HEADERS, timeout=(5, 15)
            )
        else:
            response = requests.post(
                url, data=payload, headers=HEADERS, timeout=(5, 15)
            )
        response.raise_for_status()
        return parse_response_text(response.text)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"KBO 공식 데이터에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요. ({type(exc).__name__})",
        ) from exc


def html_text(value: Any) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def code_name(code: str) -> str:
    code = html_text(code).strip()
    return TEAM_NAMES.get(code, code)


def series_request_value(series: str) -> str:
    return SERIES.get(series, SERIES["all"])


def get_schedule_month(year: int, month: int, series: str = "all"):
    cache_key = f"schedule:{year}:{month}:{series}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    payload = {
        "leId": "1",
        "srIdList": series_request_value(series),
        "seasonId": str(year),
        "gameMonth": f"{month:02d}",
        "teamId": "",
    }
    raw = post_json(SCHEDULE_URL, payload)
    rows = raw.get("rows", []) if isinstance(raw, dict) else []
    games = []
    current_mmdd = ""
    current_weekday = ""
    for row in rows:
        cells = row.get("row", []) if isinstance(row, dict) else []
        if not cells:
            continue
        first = cells[0] if cells else {}
        offset = 0
        if str(first.get("Class") or "") == "day":
            date_text = html_text(first.get("Text", ""))
            match = re.search(r"(\d{2})\.(\d{2})\s*\((.)\)", date_text)
            if match:
                current_mmdd = f"{match.group(1)}.{match.group(2)}"
                current_weekday = match.group(3)
            else:
                match = re.search(r"(\d{2})\.(\d{2})", date_text)
                if match:
                    current_mmdd = f"{match.group(1)}.{match.group(2)}"
            offset = 1
        play_cell = cells[offset + 1] if len(cells) > offset + 1 else None
        if not play_cell or str(play_cell.get("Class") or "") != "play":
            continue
        time_cell = cells[offset] if len(cells) > offset else {}
        stadium_cell = cells[offset + 6] if len(cells) > offset + 6 else {}
        note_cell = cells[offset + 7] if len(cells) > offset + 7 else {}
        parsed = parse_play_cell(str(play_cell.get("Text") or ""))
        if not parsed.get("away") or not parsed.get("home"):
            continue
        mm, dd = current_mmdd.split(".") if "." in current_mmdd else ("", "")
        game_date = f"{year}-{mm}-{dd}" if mm and dd else ""
        away_code = parsed["away"]
        home_code = parsed["home"]
        note = html_text(note_cell.get("Text", ""))
        status = parsed["status"]
        if status != "종료" and note and note not in ("-", " "):
            status = "취소/변경"
        game_id = ""
        if game_date:
            game_id = (
                game_date.replace("-", "")
                + TEAM_API_CODES.get(away_code, away_code)
                + TEAM_API_CODES.get(home_code, home_code)
                + "0"
            )
        games.append({
            "date": game_date,
            "dayOfWeek": current_weekday,
            "time": html_text(time_cell.get("Text", "")),
            "awayCode": away_code,
            "homeCode": home_code,
            "away": code_name(away_code),
            "home": code_name(home_code),
            "awayScore": parsed["awayScore"],
            "homeScore": parsed["homeScore"],
            "status": status,
            "stadium": html_text(stadium_cell.get("Text", "")),
            "note": note,
            "gameId": game_id,
            "series": series,
            "source": "KBO 공식 일정",
        })
    return cache_set(cache_key, games, 45)


def parse_play_cell(raw_html: str) -> dict[str, Any]:
    raw_html = unescape(raw_html)
    spans = re.findall(r"<span[^>]*>(.*?)</span>", raw_html, flags=re.I | re.S)
    # Usually: away team <em>score/content</em> home team
    team_match = re.search(
        r"<span[^>]*>(.*?)</span>\s*<em[^>]*>(.*?)</em>\s*<span[^>]*>(.*?)</span>",
        raw_html, flags=re.I | re.S
    )
    if team_match:
        away, middle, home = map(html_text, team_match.groups())
        score_spans = re.findall(
            r'<span[^>]*class=["\'](?:win|lose)["\'][^>]*>\s*(\d+)\s*</span>',
            middle, flags=re.I
        )
        if len(score_spans) >= 2:
            return {
                "away": away, "home": home,
                "awayScore": int(score_spans[0]), "homeScore": int(score_spans[1]),
                "status": "종료",
            }
        mid_text = html_text(middle)
        state = "진행 중" if any(x in mid_text for x in ("경기중", "진행")) else "예정"
        return {"away": away, "home": home, "awayScore": None, "homeScore": None, "status": state}
    if len(spans) >= 2:
        return {
            "away": html_text(spans[0]), "home": html_text(spans[-1]),
            "awayScore": None, "homeScore": None, "status": "예정"
        }
    return {"away": "", "home": "", "awayScore": None, "homeScore": None, "status": "예정"}


def walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def first_value(record: dict[str, Any], *keys: str):
    lower = {str(k).lower(): v for k, v in record.items()}
    for key in keys:
        val = lower.get(key.lower())
        if val is not None and str(val).strip() not in ("", "null", "None"):
            return val
    return None


def to_number_or_none(value: Any):
    if value is None:
        return None
    match = re.search(r"-?\d+", str(value).replace(",", ""))
    return int(match.group(0)) if match else None


def normalize_gamecenter(raw: Any, date: str, series: str) -> list[dict[str, Any]]:
    found = []
    seen = set()
    for rec in walk_dicts(raw):
        game_id = first_value(rec, "G_ID", "gameId", "game_id", "GAME_ID")
        away = first_value(rec, "T_NM", "AWAY_NM", "awayTeam", "away", "T_NAME")
        home = first_value(rec, "B_NM", "HOME_NM", "homeTeam", "home", "B_NAME")
        # Ignore nested player, count, and unrelated objects.
        if not game_id or not away or not home:
            continue
        gid = str(game_id)
        if gid in seen:
            continue
        seen.add(gid)
        away_score = to_number_or_none(first_value(rec, "T_SCORE_CN", "awayScore", "AWAY_SCORE"))
        home_score = to_number_or_none(first_value(rec, "B_SCORE_CN", "homeScore", "HOME_SCORE"))
        status_raw = str(first_value(rec, "GAME_STATE", "GAME_STATUS", "G_STATUS", "STATUS", "STATE") or "")
        inning = first_value(rec, "INN_NO", "INNING", "INN", "RUN_INN_CK")
        end_time = first_value(rec, "END_TM", "END_TIME")
        if any(s in status_raw.lower() for s in ("final", "end", "종료", "경기종료")) or end_time:
            status = "종료"
        elif any(s in status_raw.lower() for s in ("live", "progress", "경기중", "진행")) or inning:
            status = "진행 중"
        elif away_score is not None or home_score is not None:
            status = "진행 중"
        else:
            status = "예정"
        date_raw = str(first_value(rec, "G_DT", "gameDate", "date") or date)
        found.append({
            "date": date_raw,
            "time": html_text(first_value(rec, "START_TM", "startTime", "time") or ""),
            "awayCode": html_text(first_value(rec, "T_ID", "awayTeamCode") or ""),
            "homeCode": html_text(first_value(rec, "B_ID", "homeTeamCode") or ""),
            "away": code_name(html_text(away)),
            "home": code_name(html_text(home)),
            "awayScore": away_score,
            "homeScore": home_score,
            "status": status,
            "stadium": html_text(first_value(rec, "S_NM", "stadium") or ""),
            "gameId": gid,
            "series": series,
            "awayStarter": html_text(first_value(rec, "T_PIT_P_NM", "awayStartingPitcher", "AWAY_PITCHER") or ""),
            "homeStarter": html_text(first_value(rec, "B_PIT_P_NM", "homeStartingPitcher", "HOME_PITCHER") or ""),
            "inning": html_text(inning or ""),
            "balls": first_value(rec, "BALL_CN", "ball"),
            "strikes": first_value(rec, "STRIKE_CN", "strike"),
            "outs": first_value(rec, "OUT_CN", "out"),
            "source": "KBO 게임센터",
        })
    return found


def fetch_gamecenter(date: str, series: str) -> list[dict[str, Any]]:
    key = f"gamecenter:{date}:{series}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    series_values = [series_request_value(series)]
    if series == "postseason":
        series_values += ["3", "4", "5", "7"]
    elif series == "regular":
        series_values += ["0", "6", "9"]
    elif series == "all":
        series_values += ["0,9,6", "3", "4", "5", "7", "1"]
    merged = []
    errors = []
    for sr_id in dict.fromkeys(series_values):
        try:
            raw = post_json(
                GAME_LIST_URL,
                {"leId": "1", "srId": sr_id, "date": date.replace("-", "")},
                json_body=True,
            )
            parsed = normalize_gamecenter(raw, date.replace("-", ""), series)
            for game in parsed:
                if not any(x["gameId"] == game["gameId"] for x in merged):
                    merged.append(game)
            if merged and sr_id == series_values[0]:
                break
        except HTTPException as exc:
            errors.append(exc.detail)
    if not merged and errors:
        # Keep empty results distinct from a confirmed "no games" day.
        raise HTTPException(status_code=502, detail=errors[-1])
    return cache_set(key, merged, 15)


def merge_games(schedule: list[dict[str, Any]], live: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [dict(g) for g in schedule]
    def norm(s: str) -> str:
        return re.sub(r"[^가-힣A-Za-z]", "", s).lower()
    for live_game in live:
        match = next((g for g in out if
                      (norm(g["away"]) == norm(live_game["away"]) and norm(g["home"]) == norm(live_game["home"]))
                      or (g.get("gameId") and g["gameId"] == live_game.get("gameId"))), None)
        if match:
            for key in ("gameId", "awayScore", "homeScore", "status", "awayStarter", "homeStarter",
                        "inning", "balls", "strikes", "outs", "time", "stadium"):
                val = live_game.get(key)
                if val not in (None, ""):
                    match[key] = val
            match["source"] = "KBO 공식 일정 + 게임센터"
        else:
            out.append(live_game)
    return out


def parse_table(value: Any) -> dict[str, Any]:
    if not value:
        return {"headers": [], "rows": [], "footer": []}
    if isinstance(value, dict):
        table = value
    else:
        try:
            table = parse_response_text(str(value))
        except Exception:
            return {"headers": [], "rows": [], "footer": []}
    def rows_from(rows):
        out = []
        for row in rows or []:
            cells = row.get("row", []) if isinstance(row, dict) else []
            out.append([html_text(c.get("Text", "")) if isinstance(c, dict) else html_text(c) for c in cells])
        return out
    headers = rows_from(table.get("headers", []))
    rows = rows_from(table.get("rows", []))
    footer = rows_from(table.get("tfoot", []))
    return {"headers": headers, "rows": rows, "footer": footer}


def flatten_records(value: Any):
    records = []
    for obj in walk_dicts(value):
        if any(str(k).lower() in {"rank", "team", "teamname", "team_nm", "t_nm", "team_nm_kr", "teamcode", "team_code"}
               for k in obj.keys()):
            records.append(obj)
    return records


def normalize_standings(raw: Any, year: int) -> list[dict[str, Any]]:
    records = flatten_records(raw)
    out, seen = [], set()
    for r in records:
        name = first_value(r, "team", "teamName", "team_nm", "T_NM", "team_nm_kr", "TEAM_NM")
        if not name:
            continue
        name = code_name(html_text(name))
        if name not in [x["team"] for x in out]:
            rank = to_number_or_none(first_value(r, "rank", "RANK", "rank_no", "RANK_NO")) or len(out)+1
            wins = to_number_or_none(first_value(r, "wins", "W_CN", "W", "WIN"))
            losses = to_number_or_none(first_value(r, "losses", "L_CN", "L", "LOSE"))
            draws = to_number_or_none(first_value(r, "draws", "D_CN", "D", "DRAW")) or 0
            games = to_number_or_none(first_value(r, "games", "G_CN", "G", "GAME")) or ((wins or 0)+(losses or 0)+draws)
            pct = first_value(r, "winRate", "winrate", "WRA", "WIN_RT", "win_pct", "PCT")
            if pct is None and games:
                pct = round((wins or 0)/(games-draws if games > draws else games), 3)
            out.append({"rank": rank, "team": name, "games": games, "wins": wins, "losses": losses,
                        "draws": draws, "winRate": pct, "gamesBehind": first_value(r, "gamesBehind", "GB", "GAP")})
    return sorted(out, key=lambda x: x["rank"]) if out else []


def parse_stat_html(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    best = []
    for table in tables:
        rows = []
        for tr in table.find_all("tr"):
            cells = [html_text(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if len(rows) > len(best) and len(rows[0]) >= 3:
            best = rows
    if not best:
        return []
    header = best[0]
    records = []
    for row in best[1:]:
        if len(row) < 3:
            continue
        record = {header[i] if i < len(header) and header[i] else f"항목{i+1}": val
                  for i, val in enumerate(row)}
        records.append(record)
    return records


def parse_lineup_and_pitching(raw: Any):
    arr_hitters = raw.get("arrHitter", []) if isinstance(raw, dict) else []
    arr_pitchers = raw.get("arrPitcher", []) if isinstance(raw, dict) else []
    sides = []
    for side_index in range(2):
        hitter_obj = arr_hitters[side_index] if len(arr_hitters) > side_index else {}
        lineup = parse_table(hitter_obj.get("table1"))
        stats = parse_table(hitter_obj.get("table3"))
        hitters = []
        stat_rows = stats["rows"]
        for i, row in enumerate(lineup["rows"]):
            stat = stat_rows[i] if i < len(stat_rows) else []
            hitters.append({
                "order": row[0] if len(row) else "",
                "position": row[1] if len(row) > 1 else "",
                "name": row[2] if len(row) > 2 else (row[-1] if row else ""),
                "AB": stat[0] if len(stat) > 0 else "",
                "H": stat[1] if len(stat) > 1 else "",
                "RBI": stat[2] if len(stat) > 2 else "",
                "R": stat[3] if len(stat) > 3 else "",
                "AVG": stat[4] if len(stat) > 4 else "",
            })
        pitcher_obj = arr_pitchers[side_index] if len(arr_pitchers) > side_index else {}
        ptable = parse_table(pitcher_obj.get("table"))
        pitchers = []
        pheaders = ["선수", "등판", "결과", "승", "패", "세", "이닝", "타자", "투구수",
                    "타수", "안타", "홈런", "볼넷", "삼진", "실점", "자책", "ERA"]
        for row in ptable["rows"]:
            pitchers.append({pheaders[i] if i < len(pheaders) else f"항목{i+1}": v for i, v in enumerate(row)})
        sides.append({"hitters": hitters, "pitchers": pitchers})
    return sides


@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "nowKST": kst_now().isoformat(), "dataSource": "KBO 공식 웹사이트"}


@app.get("/api/games")
def games(
    date: str = Query(default=""),
    series: str = Query(default="all"),
):
    if not date:
        date = kst_now().strftime("%Y-%m-%d")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(400, "날짜는 YYYY-MM-DD 형식으로 입력해 주세요.")
    parsed_date = datetime.strptime(date, "%Y-%m-%d")
    schedule = get_schedule_month(parsed_date.year, parsed_date.month, series)
    schedule = [g for g in schedule if g["date"] == date]
    try:
        live = fetch_gamecenter(date, series)
        all_games = merge_games(schedule, live)
    except HTTPException:
        # The schedule remains valid when the live game-center request is temporarily unavailable.
        all_games = schedule
    return {
        "date": date,
        "updatedAtKST": kst_now().isoformat(),
        "source": "KBO 공식 일정/게임센터",
        "games": all_games,
        "liveFeedAvailable": bool(live) if 'live' in locals() else False,
    }


@app.get("/api/standings")
def standings(year: int | None = Query(default=None)):
    year = year or kst_now().year
    key = f"rankings:{year}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    errors = []
    for body in (
        {"leId": "1", "srId": "0", "seasonId": str(year)},
        {"leId": 1, "srId": 0, "seasonId": year},
        {"leId": "1", "seasonId": str(year)},
    ):
        try:
            raw = post_json(RANK_URL, body, json_body=True)
            normalized = normalize_standings(raw, year)
            if normalized:
                return cache_set(key, {
                    "year": year, "updatedAtKST": kst_now().isoformat(),
                    "source": "KBO 공식 팀 순위", "teams": normalized,
                }, 900)
            errors.append("응답 형식을 인식하지 못했습니다.")
        except HTTPException as exc:
            errors.append(exc.detail)
    raise HTTPException(502, "공식 순위 데이터를 불러오지 못했습니다. " + (errors[-1] if errors else ""))


@app.get("/api/player-stats")
def player_stats(
    kind: str = Query(default="hitter", pattern="^(hitter|pitcher)$"),
    year: int | None = Query(default=None),
):
    year = year or kst_now().year
    key = f"player-stats:{kind}:{year}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    path = "HitterBasic" if kind == "hitter" else "PitcherBasic"
    url = f"{KBO}/Record/Player/{path}/Basic1.aspx"
    try:
        response = requests.get(
            url, params={"year": year, "teamCode": "", "playerId": ""},
            headers={"User-Agent": USER_AGENT, "Referer": f"{KBO}/Record/Player/{path}/Basic1.aspx"},
            timeout=(5, 15),
        )
        response.raise_for_status()
        records = parse_stat_html(response.text)
        if not records:
            raise HTTPException(502, "KBO 선수 기록 페이지에서 표 데이터를 찾지 못했습니다.")
        return cache_set(key, {
            "year": year, "kind": kind, "updatedAtKST": kst_now().isoformat(),
            "source": "KBO 공식 선수 기록", "records": records[:100],
        }, 900)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"KBO 선수 기록에 연결하지 못했습니다. ({type(exc).__name__})") from exc


@app.get("/api/game-details")
def game_details(
    game_id: str = Query(..., min_length=8, max_length=32),
    date: str = Query(..., pattern=r"^\d{4}-?\d{2}-?\d{2}$"),
    series: str = Query(default="regular"),
):
    yyyymmdd = date.replace("-", "")
    season_id = int(yyyymmdd[:4])
    if series == "regular":
        sr_candidates = ["0", "9", "6"]
    elif series == "postseason":
        sr_candidates = ["3", "4", "5", "7"]
    elif series == "preseason":
        sr_candidates = ["1"]
    else:
        sr_candidates = ["0", "9", "6", "3", "4", "5", "7", "1"]
    last_error = None
    for sr_id in sr_candidates:
        payload = {"leId": "1", "srId": sr_id, "seasonId": str(season_id), "gameId": game_id}
        try:
            box = post_json(BOX_URL, payload)
            scoreboard = post_json(SCORE_URL, payload)
            if not (box.get("G_ID") or box.get("arrHitter") or scoreboard.get("G_ID")):
                continue
            lineup = parse_lineup_and_pitching(box)
            return {
                "gameId": game_id,
                "date": yyyymmdd,
                "updatedAtKST": kst_now().isoformat(),
                "source": "KBO 공식 게임센터",
                "meta": {
                    "stadium": html_text(box.get("S_NM") or scoreboard.get("S_NM") or ""),
                    "away": code_name(html_text(box.get("AWAY_NM") or scoreboard.get("AWAY_NM") or "")),
                    "home": code_name(html_text(box.get("HOME_NM") or scoreboard.get("HOME_NM") or "")),
                    "awayScore": box.get("T_SCORE_CN") or scoreboard.get("T_SCORE_CN"),
                    "homeScore": box.get("B_SCORE_CN") or scoreboard.get("B_SCORE_CN"),
                },
                "innings": parse_table(scoreboard.get("table2")),
                "totals": parse_table(scoreboard.get("table3")),
                "away": lineup[0],
                "home": lineup[1],
                "etc": parse_table(box.get("tableEtc")),
            }
        except HTTPException as exc:
            last_error = exc.detail
    raise HTTPException(502, last_error or "경기 상세 데이터를 아직 제공하지 않거나 경기 ID를 확인할 수 없습니다.")


@app.get("/api/source")
def source():
    return {
        "officialSchedule": f"{KBO}/Schedule/Schedule.aspx",
        "officialGameCenter": f"{KBO}/Schedule/GameCenter/Main.aspx",
        "officialPlayerStats": f"{KBO}/Record/Player/HitterBasic/Basic1.aspx",
        "note": "KBO 공식 데이터 소스에 연결하며, 데이터를 가져오지 못하면 임의 수치를 표시하지 않습니다.",
    }
