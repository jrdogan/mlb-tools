import excel2img

def snapshot_images(output, df, best_df):
    # use df to compute ranges
    n = len(df) + 2
    excel2img.export_img(output, f"{output}_Matchups.png", 'Matchups', f"A1:E{n}")
    m = len(best_df) + 2
    last = xl_col_to_name(len(best_df.columns)-1)
    excel2img.export_img(output, f"{output}_BestMatchups.png", 'BestMatchups', f"A1:{last}{m}")
