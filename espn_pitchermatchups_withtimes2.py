#!/usr/bin/env python3
import os
import datetime
import logging
import requests
import pandas as pd
from bs4 import BeautifulSoup
from xlsxwriter.utility import xl_col_to_name
from pydrive2.auth import GoogleAuth, RefreshError
from pydrive2.drive import GoogleDrive
from zoneinfo import ZoneInfo

# Configure logging
logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s %(levelname)s:%(name)s: %(message)s")
log = logging.getLogger("matchups")


def get_mlb_team_map():
    resp = requests.get(
        "https://statsapi.mlb.com/api/v1/teams",
        params={"sportId": 1}, timeout=10
    )
    resp.raise_for_status()
    teams = resp.json().get("teams", [])
    team_map = {t["abbreviation"].upper(): t["id"] for t in teams}
    alias_map = {"ARI": "AZ", "WAS": "WSH"}
    for espn, mlb in alias_map.items():
        if mlb in team_map:
            team_map[espn] = team_map[mlb]
    return team_map


def get_team_batters_with_ids(team_code: str, side: str, team_map: dict):
    team_id = team_map.get(team_code.upper())
    if not team_id:
        return [], []
    year = datetime.date.today().year
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
    r = requests.get(url, params={"rosterType": "active", "season": year}, timeout=10)
    r.raise_for_status()
    roster = r.json().get("roster", [])
    batters = [p for p in roster if p.get("position", {}).get("type") != "Pitcher"]
    ids = [str(p["person"]["id"]) for p in batters]
    if not ids:
        return [], []
    r2 = requests.get(
        "https://statsapi.mlb.com/api/v1/people",
        params={"personIds": ",".join(ids)}, timeout=10
    )
    r2.raise_for_status()
    people = r2.json().get("people", [])
    names, sel_ids = [], []
    for p in people:
        code = p.get("batSide", {}).get("code", "").upper()
        if side.upper() == "L" and code in ("L", "S"):
            names.append(p.get("fullName", "")); sel_ids.append(p["id"])
        if side.upper() == "R" and code in ("R", "S"):
            names.append(p.get("fullName", "")); sel_ids.append(p["id"])
    paired = sorted({(n, i) for n, i in zip(names, sel_ids)}, key=lambda x: x[0])
    if not paired:
        return [], []
    nm, iid = zip(*paired)
    return list(nm), list(iid)


def categorize(row, team_map):
    """
    Given a team row, returns 6-tuple:
      (lh_str, rh_str, sw_str, lh_ids, rh_ids, sw_ids)
    where:
      - lh_str/rh_str/sw_str are newline-separated strings of hitters
        against LHB/RHB or switch, filtered by rating.
      - lh_ids/rh_ids/sw_ids are the corresponding player ID lists.
    Switch-hitters are listed once, and only when matchup rating >=8.
    """
    left_names, left_ids = get_team_batters_with_ids(row["TEAM"], "L", team_map)
    right_names, right_ids = get_team_batters_with_ids(row["TEAM"], "R", team_map)

    # Identify switch-hitters (bat both sides)
    switch_ids = set(left_ids) & set(right_ids)
    # Dedupe and preserve one name per ID
    switch_map = {}
    for name, pid in zip(left_names + right_names, left_ids + right_ids):
        if pid in switch_ids:
            switch_map[pid] = name
    # Order switch IDs by name
    switch_ids_sorted = sorted(switch_map.keys(), key=lambda pid: switch_map[pid])
    switch_names = [switch_map[pid] for pid in switch_ids_sorted]

    # Non-switch hitters
    lh_ids = [i for i in left_ids if i not in switch_ids]
    rh_ids = [i for i in right_ids if i not in switch_ids]
    lh_names = sorted([n for n, i in zip(left_names, left_ids) if i in lh_ids])
    rh_names = sorted([n for n, i in zip(right_names, right_ids) if i in rh_ids])

    # Build output strings only when rating >= 8
    lh_str = "\n".join(lh_names) if row.get("LHB", 0) >= 8 else ""
    rh_str = "\n".join(rh_names) if row.get("RHB", 0) >= 8 else ""
    # Include switch-hitters if either side favorable
    sw_str = "\n".join(switch_names) if (row.get("LHB", 0) >= 8 or row.get("RHB", 0) >= 8) else ""

    return lh_str, rh_str, sw_str, lh_ids, rh_ids, switch_ids_sorted


def upload_to_gdrive(filepath, folder_id=None):
    """Upload the given file (and associated PNGs) to Google Drive."""
    import os as _os
    gauth = GoogleAuth(); gauth.LoadClientConfigFile("client_secrets.json")
    if _os.path.exists("credentials.json"): gauth.LoadCredentialsFile("credentials.json")
    try:
        if gauth.access_token_expired: gauth.Refresh()
    except RefreshError:
        gauth.LocalWebserverAuth()
    gauth.SaveCredentialsFile("credentials.json")
    drive = GoogleDrive(gauth)

    # Upload primary file
    meta = {"title": _os.path.basename(filepath)}
    if folder_id:
        meta["parents"] = [{"id": folder_id}]
    f = drive.CreateFile(meta)
    f.SetContentFile(filepath)
    f.Upload()
    log.info(f"Uploaded '{filepath}' to Google Drive")

    # Upload associated PNGs if they exist
    base, _ = _os.path.splitext(filepath)
    for suffix in ("_Matchups.png", "_BestMatchups.png"):
        png_path = base + suffix
        if _os.path.exists(png_path):
            meta_png = {"title": _os.path.basename(png_path)}
            if folder_id:
                meta_png["parents"] = [{"id": folder_id}]
            f2 = drive.CreateFile(meta_png)
            f2.SetContentFile(png_path)
            f2.Upload()
            log.info(f"Uploaded '{png_path}' to Google Drive")

def fetch_all_teams(target_date: datetime.date = None, upload: bool = True):
    if target_date is None:
        target_date = datetime.date.today()
    display_date = target_date.strftime("%B %d, %Y")
    date_str = target_date.strftime("%Y-%m-%d")
    team_map = get_mlb_team_map()
    # Scrape ESPN as before ... build df
    url = ("https://www.espn.com/fantasy/baseball/story/_/id/31165089/"
           "fantasy-baseball-forecaster-team-hitting-stolen-base-ratings-platoon-matchups-daily-weekly-leagues")
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("article", {"data-id": "31165089"})
    table = table.find("table", {"class": "inline-table"})
    cols = [th.get_text(strip=True) for th in table.thead.find_all("th")]
    display_label = target_date.strftime("%a, %#m/%#d")
    records = []
    for tr in table.tbody.find_all("tr"):
        tds = tr.find_all("td")
        if not tds: continue
        divs = tds[1].find_all("div")
        if not divs: continue
        try:
            idx = next(i for i, d in enumerate(divs) if d.get_text(strip=True) == display_label)
        except StopIteration:
            continue
        row = {}
        for name, td in zip(cols, tds):
            if name == "TEAM":
                img = td.find("img")
                if img and img.has_attr("src"):
                    code = img["src"].split("/")[-1].split(".")[0].upper()
                else:
                    code = td.get_text(strip=True)
                row[name] = {"CHW": "CWS"}.get(code, code)
            else:
                divs2 = td.find_all("div")
                row[name] = divs2[idx].get_text(strip=True) if divs2 and idx < len(divs2) else td.get_text(strip=True)
        records.append(row)
    df = pd.DataFrame(records, columns=cols)
    for d in ("SB", "OVERALL", "DATE"):
        if d in df.columns:
            df.drop(columns=[d], inplace=True)
    # Fetch schedule and map start times
    sched = requests.get("https://statsapi.mlb.com/api/v1/schedule",
                         params={"date": date_str, "sportId": 1}, timeout=10)
    sched.raise_for_status()
    dates = sched.json().get("dates", [])
    games = dates[0]["games"] if dates else []
    id2code = {mlb: espn for espn, mlb in team_map.items()}
    eastern = ZoneInfo("America/New_York")
    time_map, team_game, team_order = {}, {}, {}
    for g in games:
        gd = g.get("gameDate")
        if not gd: continue
        dt = datetime.datetime.fromisoformat(gd.replace("Z", "+00:00")).astimezone(eastern)
        ts = dt.strftime("%I:%M %p").lstrip("0")
        pk = g.get("gamePk")
        for side in ("away", "home"):
            t = g["teams"][side]["team"]["id"]
            ab = id2code.get(t)
            if ab:
                time_map[ab] = ts
                team_game[ab] = pk
                team_order[ab] = 0 if side == "away" else 1
    df["StartTime"] = df["TEAM"].map(time_map).fillna("")
    df["StartTime_dt"] = pd.to_datetime(df["StartTime"], format="%I:%M %p", errors="coerce")
    df["GamePk"] = df["TEAM"].map(team_game)
    df["TeamOrder"] = df["TEAM"].map(team_order)
    df.sort_values(by=["StartTime_dt", "GamePk", "TeamOrder"], inplace=True, na_position="last")
    df.drop(columns=["StartTime_dt", "TeamOrder"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    # Filter by ratings
    for c in ("LHB", "RHB"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    best_df = df[df[["LHB", "RHB"]].ge(8).any(axis=1)].reset_index(drop=True)
    # Categorize and attach IDs
    recs = best_df.apply(lambda r: categorize(r, team_map), axis=1)
    tmp = pd.DataFrame(recs.tolist(), columns=["LH_Batters", "RH_Batters", "Switch",
                                                "LH_Ids", "RH_Ids", "SwitchIds"],
                       index=best_df.index)
    best_df = pd.concat([best_df, tmp], axis=1)
    # Fetch positions and annotate
    all_ids = sorted({pid for col in ["LH_Ids", "RH_Ids", "SwitchIds"] for pid in sum(best_df[col].tolist(), [])})
    pr = requests.get("https://statsapi.mlb.com/api/v1/people",
                      params={"personIds": ",".join(map(str, all_ids)), "hydrate": "position"}, timeout=10)
    pr.raise_for_status()
    people = pr.json().get("people", [])
    pos_map = {p["id"]: p.get("primaryPosition", {}).get("abbreviation", "")
               for p in people if p.get("primaryPosition")}
    def annotate(txt, ids):
        return "\n".join(f"{n} ({pos_map.get(i, '')})" for n, i in zip(txt.split("\n"), ids) if n)
    best_df["LH_Batters"] = best_df.apply(lambda r: annotate(r["LH_Batters"], r["LH_Ids"]), axis=1)
    best_df["RH_Batters"] = best_df.apply(lambda r: annotate(r["RH_Batters"], r["RH_Ids"]), axis=1)
    best_df["Switch"] = best_df.apply(lambda r: annotate(r["Switch"], r["SwitchIds"]), axis=1)
    best_df.drop(columns=["LH_Ids", "RH_Ids", "SwitchIds"], inplace=True)
    # Move StartTime into column A & remove from best_df
    df.insert(0, "StartTime", df.pop("StartTime"))
    if "StartTime" in best_df.columns:
        best_df.drop(columns=["StartTime"], inplace=True)
    # Write and format Excel
    output = f"pitcher_matchups_{date_str}.xlsx"
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        game_groups = [grp.index.tolist() for _, grp in df.groupby("GamePk", sort=False)]
        df_to_write = df.drop(columns=["GamePk"])
        df_to_write.to_excel(writer, sheet_name="Matchups", index=False, startrow=1)
        workbook = writer.book
        ws1 = writer.sheets["Matchups"]
        merge_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
        for rows in game_groups:
            if len(rows) < 2:
                continue
            ws1.merge_range(rows[0]+2, 0, rows[-1]+2, 0, df.at[rows[0], "StartTime"], merge_fmt)
        team_fmt = workbook.add_format({'align':'center','valign':'vcenter','border':1,'text_wrap':True})
        for gpk, grp in df.groupby("GamePk", sort=False):
            rows = grp.index.tolist()
            if len(rows) < 2:
                continue
            away = [t for t, pk in team_game.items() if pk==gpk and team_order[t]==0][0]
            home = [t for t, pk in team_game.items() if pk==gpk and team_order[t]==1][0]
            text = f"{away}\n@ {home}"
            ws1.merge_range(rows[0]+2,1, rows[1]+2,2, text, team_fmt)
        blank_fmt = workbook.add_format({'border':1,'bg_color':'#A9A9A9','align':'center','valign':'vcenter'})
        blank_idxs = [i for i, st in enumerate(df_to_write['StartTime']) if st=='']
        if blank_idxs:
            ws1.merge_range(blank_idxs[0]+2,0, blank_idxs[-1]+2,0, "", blank_fmt)
        hdr_fmt = workbook.add_format({'align':'center','valign':'vcenter','bold':True})
        ws1.merge_range("A1:E1", f"Data for {display_date}", hdr_fmt)
        ws1.freeze_panes(2,0)
        default_fmt = workbook.add_format({'align':'center','valign':'vcenter'})
        border_fmt = workbook.add_format({'border':1,'border_color':'#A9A9A9','valign':'vcenter'})
        fmt1 = workbook.add_format({'bg_color':'#05AEF0','font_color':'white','align':'center','valign':'vcenter'})
        fmt23 = workbook.add_format({'bg_color':'#BCDEEE','align':'center','valign':'vcenter'})
        fmt89 = workbook.add_format({'bg_color':'#EE9880','align':'center','valign':'vcenter'})
        fmt10 = workbook.add_format({'bg_color':'#F50D1F','font_color':'white','align':'center','valign':'vcenter'})
        foff = workbook.add_format({'bg_color':'#A9A9A9','align':'center','valign':'vcenter'})
        n_rows = len(df_to_write); n_cols = len(df_to_write.columns)
        last_col = xl_col_to_name(n_cols-1)
        idxs = [df_to_write.columns.get_loc(c) for c in ["LHB","RHB"]]
        a, b = min(idxs), max(idxs)
        rating_range = f"{xl_col_to_name(a)}3:{xl_col_to_name(b)}{n_rows+2}"
        border_range = f"A3:{last_col}{n_rows+2}"
        ws1.conditional_format(rating_range, {"type":"cell","criteria":"==","value":1,"format":fmt1})
        ws1.conditional_format(rating_range, {"type":"cell","criteria":"between","minimum":2,"maximum":3,"format":fmt23})
        ws1.conditional_format(rating_range, {"type":"cell","criteria":"between","minimum":8,"maximum":9,"format":fmt89})
        ws1.conditional_format(rating_range, {"type":"cell","criteria":"==","value":10,"format":fmt10})
        opp_col = xl_col_to_name(df_to_write.columns.get_loc("OPP"))
        ws1.conditional_format(rating_range, {"type":"formula","criteria":f'=${opp_col}3="OFF"',"format":foff})
        ws1.conditional_format(border_range, {"type":"no_blanks","format":border_fmt})
        for i,col in enumerate(df_to_write.columns):
            width = max(df_to_write[col].astype(str).map(len).max(), len(col)) + 2
            ws1.set_column(i,i,width, default_fmt)
                # ————————————————————————————
        # Write & format BestMatchups WITHOUT GamePk
        bm = best_df.drop(columns=["GamePk"])
        bm.to_excel(
            writer,
            sheet_name="BestMatchups",
            index=False,
            startrow=1
        )
        ws2 = writer.sheets["BestMatchups"]

        # Header banner & freeze
        fmt_hdr = workbook.add_format({'align':'center','valign':'vcenter','bold':True})
        last2 = xl_col_to_name(len(bm.columns) - 1)
        ws2.merge_range(
            f"A1:{last2}1",
            f"Best Hitter/Pitcher Matchups for {display_date}",
            fmt_hdr
        )
        ws2.freeze_panes(2, 0)

        # Conditional formatting for LHB/RHB with correct ranges
        fmt1   = workbook.add_format({'bg_color':'#05AEF0','font_color':'white','align':'center','valign':'vcenter'})
        fmt23  = workbook.add_format({'bg_color':'#BCDEEE','align':'center','valign':'vcenter'})
        fmt89  = workbook.add_format({'bg_color':'#EE9880','align':'center','valign':'vcenter'})
        fmt10  = workbook.add_format({'bg_color':'#F50D1F','font_color':'white','align':'center','valign':'vcenter'})
        # Calculate BestMatchups ranges
        lhb2 = xl_col_to_name(bm.columns.get_loc("LHB"))
        rhb2 = xl_col_to_name(bm.columns.get_loc("RHB"))
        m = len(bm)
        rngL2 = f"{lhb2}3:{lhb2}{m+2}"
        rngR2 = f"{rhb2}3:{rhb2}{m+2}"
        for cr2 in (rngL2, rngR2):
            ws2.conditional_format(cr2, {"type":"cell","criteria":"==","value":1,  "format":fmt1})
            ws2.conditional_format(cr2, {"type":"cell","criteria":"between","minimum":2,"maximum":3,"format":fmt23})
            ws2.conditional_format(cr2, {"type":"cell","criteria":"between","minimum":8,"maximum":9,"format":fmt89})
            ws2.conditional_format(cr2, {"type":"cell","criteria":"==","value":10, "format":fmt10})

                        # Wrap-text for batter list columns and auto-fit all columns
        wrap_fmt = workbook.add_format({'text_wrap':True,'align':'center','valign':'vcenter'})
        center_fmt = workbook.add_format({'align':'center','valign':'vcenter'})
        for j, col in enumerate(bm.columns):
            # Determine max line length per cell (for wrapping columns) or max content length
            max_len = 0
            for val in bm[col]:
                lines = str(val).split("\n")
                for line in lines:
                    max_len = max(max_len, len(line))
            max_len = max(max_len, len(col))
            width = max_len + 2
            # Choose wrap format for batter lists, center for others
            fmt = wrap_fmt if col in ("LH_Batters", "RH_Batters", "Switch") else center_fmt
            ws2.set_column(j, j, width, fmt)

        # Apply borders to all data cells in BestMatchups
        bd = workbook.add_format({'border':1,'border_color':'#A9A9A9','align':'center','valign':'vcenter'})
        full2 = f"A3:{last2}{m+2}"
        ws2.conditional_format(full2, {"type":"no_blanks","format":bd})
        ws2.conditional_format(full2, {"type":"blanks","format":bd})
        bd = workbook.add_format({'border':1,'border_color':'#A9A9A9','align':'center','valign':'vcenter'})
        full2 = f"A3:{last2}{m+2}"
        ws2.conditional_format(full2, {"type":"no_blanks","format":bd})
        ws2.conditional_format(full2, {"type":"blanks","format":bd})

    log.info(f"Wrote two sheets to '{output}'")

    # ————————————————————————————
    # 9) Snapshot sheets to PNGs using the same timestamped base name

    import os
    import excel2img

    # strip “.xlsx” from the output filename
    base, _ = os.path.splitext(output)

    # Matchups.png
    n = len(df_to_write) + 2
    excel2img.export_img(
        output,
        f"{base}_Matchups.png",
        "Matchups",
        f"A1:E{n}"
    )

    # Re‐compute the exact DataFrame you wrote
    bm = best_df.drop(columns=["GamePk"])

    # How many columns did you actually write?
    last_col = xl_col_to_name(len(bm.columns) - 1)

    # How many rows (including your 2 header rows)?
    n_rows = len(bm) + 2

    # Then export exactly A1 through that last cell:
    excel2img.export_img(
        output,
        f"{base}_BestMatchups.png",
        "BestMatchups",
        f"A1:{last_col}{n_rows}"
    )

    if upload:
        upload_to_gdrive(output)

# Entry point
def __main__():
    import argparse
    parser = argparse.ArgumentParser(description="Generate MLB pitcher matchups spreadsheet")
    parser.add_argument('-d', '--date', type=lambda s: datetime.datetime.strptime(s, '%Y-%m-%d').date(), help='Date in YYYY-MM-DD format')
    parser.add_argument('--no-upload', action='store_true', help='Skip uploading to Google Drive')
    args = parser.parse_args()
    fetch_all_teams(target_date=args.date, upload=not args.no_upload)

# ————————————————————————————
# Upload to GitHub Pages
from github import Github

def upload_to_github(output, repo_name="jrdogan/mlb-tools", branch="(root)"):
    """Pushes the .xlsx and .png files to the specified GitHub Pages branch."""
    import os
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        log.error("GITHUB_TOKEN not set; skipping GitHub upload")
        return
    g = Github(token)
    repo = g.get_repo(repo_name)
    base, _ = os.path.splitext(output)
    for suffix in ["", "_Matchups.png", "_BestMatchups.png"]:
        local_path = base + suffix + ("" if suffix else ".xlsx")
        if not os.path.exists(local_path):
            continue
        filename = os.path.basename(local_path)
        remote_path = filename
        with open(local_path, "rb") as f:
            data = f.read()
        try:
            contents = repo.get_contents(remote_path, ref=branch)
            repo.update_file(
                path=remote_path,
                message=f"Update {filename}",
                content=data,
                sha=contents.sha,
                branch=branch
            )
        except Exception:
            repo.create_file(
                path=remote_path,
                message=f"Add {filename}",
                content=data,
                branch=branch
            )
        url = f"https://{repo.owner.login}.github.io/{repo.name}/{remote_path}"
        log.info(f"Published → {url}")

if __name__ == '__main__':
    __main__()
