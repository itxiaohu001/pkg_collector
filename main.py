from alpine_collector import collect_alpine
from deb_collector import collect_deb

if __name__ == "__main__":
    source_file_save = False
    http_timeout = 60
    alpine_dir = "downloads/alpine"
    debian_dir = "downloads/debian"
    ubuntu_dir = "downloads/ubuntu"

    collect_alpine(output_dir=alpine_dir, save=source_file_save)
    collect_deb(base_url="https://mirrors.aliyun.com/debian/", output_dir=debian_dir, type_name="Debian",
                timeout=http_timeout)
    collect_deb(base_url="https://mirrors.aliyun.com/ubuntu/", output_dir=debian_dir, type_name="Ubuntu",
                timeout=http_timeout)
