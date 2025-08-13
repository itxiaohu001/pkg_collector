from alpine_collector import collect_alpine
from deb_collector import collect_deb
from rpm_collector import collect_rpm

def process_file(file_path):
    # 下载后处理逻辑
    print(f"[Callback] Processing {file_path}")

if __name__ == "__main__":
    parallel_mode = True  # 控制是否并发

    collect_alpine(parallel=parallel_mode, callback=process_file)
    collect_deb(parallel=parallel_mode, callback=process_file)
    collect_rpm(parallel=parallel_mode, callback=process_file)
