from deb_collector import collect_deb

if __name__ == "__main__":
    parallel_mode = False
    parallel_num = 4
    source_file_save = False
    http_timeout = 60
    alpine_dir = "downloads/alpine"
    debian_dir = "downloads/debian"

    # collect_alpine(output_dir=alpine_dir, parallel=parallel_mode, save=source_file_save,workers=parallel_num)
    collect_deb(base_url="https://mirrors.aliyun.com/debian/", output_dir=debian_dir, type_name="Debian",
                parallel=parallel_mode,
                timeout=http_timeout, workers=parallel_num)
