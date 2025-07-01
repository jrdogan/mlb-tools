import argparse
import datetime
from fetch import load_matchups
from excel_export import write_spreadsheets
from snapshot import snapshot_images
from publisher import upload_to_github
from indexer import build_index, commit_index


def main():
    parser = argparse.ArgumentParser(description="Generate and publish MLB matchups")
    parser.add_argument('-d','--date', type=lambda s: datetime.datetime.strptime(s,'%Y-%m-%d').date(),
                        help='Date in YYYY-MM-DD')
    parser.add_argument('--no-upload', action='store_true')
    args = parser.parse_args()

    target = args.date or datetime.date.today()
    df, best_df, display_date, date_str = load_matchups(target)
    output = write_spreadsheets(df, best_df, display_date, date_str)
    snapshot_images(output, df, best_df)
    if not args.no_upload:
        upload_to_github(output)
        html = build_index()
        commit_index(html)

if __name__ == '__main__':
    main()
