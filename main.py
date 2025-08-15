from alpine_collector import collect_alpine
from deb_collector import collect_deb
from rpm_collector import collect_rpm
import argparse
import os

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Package collector')
    parser.add_argument('--source-file-save', action='store_true', default=False, help='Save source files')
    parser.add_argument('--http-timeout', type=int, default=60, help='HTTP request timeout')
    parser.add_argument('--randint', type=int, default=2, help='Random sleep value')
    parser.add_argument('--download-dir', type=str, default='downloads', help='Top level download directory')
    parser.add_argument('--collect-types', nargs='+', default=['alpine', 'debian', 'ubuntu', 'centos'],
                        choices=['alpine', 'debian', 'ubuntu', 'centos'],
                        help='Types of packages to collect: alpine, debian, ubuntu, centos')

    args = parser.parse_args()
    source_file_save = args.source_file_save
    http_timeout = args.http_timeout
    randint = args.randint  # [0,randint]随机睡眠值（整数）
    download_dir = args.download_dir
    collect_types = [t.lower() for t in args.collect_types]

    # 创建顶级下载目录
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    # 为每种类型创建子目录
    alpine_dir = os.path.join(download_dir, "alpine")
    debian_dir = os.path.join(download_dir, "debian")
    ubuntu_dir = os.path.join(download_dir, "ubuntu")
    centos_dir = os.path.join(download_dir, "centos")

    # 根据指定的类型进行爬取
    if 'alpine' in collect_types:
        if not os.path.exists(alpine_dir):
            os.makedirs(alpine_dir)
        collect_alpine(output_dir=alpine_dir, save=source_file_save, randint=randint)

    if 'debian' in collect_types:
        if not os.path.exists(debian_dir):
            os.makedirs(debian_dir)
        collect_deb(base_url="https://mirrors.aliyun.com/debian/", output_dir=debian_dir, type_name="Debian",
                    timeout=http_timeout, save=source_file_save, randint=randint)

    if 'ubuntu' in collect_types:
        if not os.path.exists(ubuntu_dir):
            os.makedirs(ubuntu_dir)
        collect_deb(base_url="https://mirrors.aliyun.com/ubuntu/", output_dir=ubuntu_dir, type_name="Ubuntu",
                    timeout=http_timeout, save=source_file_save, randint=randint)

    if 'centos' in collect_types:
        if not os.path.exists(centos_dir):
            os.makedirs(centos_dir)
        collect_rpm(output_dir=centos_dir, base_url="https://mirrors.aliyun.com/centos/", type_name="Centos",
                    timeout=http_timeout, save=source_file_save, randint=randint)

