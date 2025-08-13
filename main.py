from alpine_collector import collect_alpine


if __name__ == "__main__":
    parallel_mode = False
    parallel_num = 4
    source_file_save = False
    alpine_dir = "downloads/alpine"

    collect_alpine(output_dir=alpine_dir, parallel=parallel_mode, save=source_file_save,workers=parallel_num)
