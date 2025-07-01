import pandas as pd
from xlsxwriter.utility import xl_col_to_name

def write_spreadsheets(df, best_df, display_date, date_str):
    output = f"pitcher_matchups_{date_str}.xlsx"
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # [... Excel formatting code ...]
    return output
