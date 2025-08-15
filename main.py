from alpine_collector import collect_alpine
from deb_collector import collect_deb
from rpm_collector import collect_rpm
import argparse
import os

if __name__ == "__main__":
    """
    Package collector - 用于收集各种Linux发行版的软件包信息
    
    简单使用示例:
    python main.py --types all                    # 收集所有类型
    python main.py --types alpine,debian          # 只收集alpine和debian
    python main.py --dir mydownloads --timeout 120 # 指定下载目录和超时时间
    """
    parser = argparse.ArgumentParser(description='Package collector - 用于收集各种Linux发行版的软件包信息')
    parser.add_argument('--save', action='store_true', default=False,
                        help='是否保存源文件 (默认: False)')
    parser.add_argument('--timeout', type=int, default=60,
                        help='HTTP请求超时时间秒数 (默认: 60)')
    parser.add_argument('--rand', type=int, default=2,
                        help='最大随机延迟秒数 (默认: 2)')
    parser.add_argument('--dir', type=str, default='downloads',
                        help='下载根目录 (默认: downloads)')
    parser.add_argument('--types', type=str, default='all',
                        help='要收集的类型，用逗号分隔或使用all (默认: all)')
    parser.add_argument('--cache', action='store_true', default=True,
                        help='是否使用缓存 (默认: True)')

    args = parser.parse_args()
    source_file_save = args.save
    http_timeout = args.timeout
    randint = args.rand
    download_dir = args.dir
    collect_types_str = args.types.lower()
    cache = args.cache

    # 解析收集类型
    if collect_types_str == 'all':
        collect_types = ['alpine', 'debian', 'ubuntu', 'centos']
    else:
        collect_types = [t.strip() for t in collect_types_str.split(',')]

    # 创建下载目录
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
        collect_alpine(output_dir=alpine_dir, save=source_file_save, randint=randint, cache=cache)

    if 'debian' in collect_types:
        if not os.path.exists(debian_dir):
            os.makedirs(debian_dir)
        collect_deb(base_url="https://mirrors.aliyun.com/debian/", out_dir=debian_dir, type_name="Debian",
                    timeout=http_timeout, save=source_file_save, randint=randint, cache=cache)

    if 'ubuntu' in collect_types:
        if not os.path.exists(ubuntu_dir):
            os.makedirs(ubuntu_dir)
        collect_deb(base_url="https://mirrors.aliyun.com/ubuntu/", out_dir=ubuntu_dir, type_name="Ubuntu",
                    timeout=http_timeout, save=source_file_save, randint=randint, cache=cache)

    if 'centos' in collect_types:
        if not os.path.exists(centos_dir):
            os.makedirs(centos_dir)
        collect_rpm(output_dir=centos_dir, base_url="https://mirrors.aliyun.com/centos/", type_name="Centos",
                    timeout=http_timeout, save=source_file_save, randint=randint, cache=cache)
