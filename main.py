import argparse
import os
import multiprocessing  # 导入多进程模块
import time  # 导入time用于计时

# 假设这些是您的爬取函数
from deb_collector import collect_deb
from freebsd import collect_freebsd
from rpm_collector import collect_rpm


# from alpine_collector import collect_alpine # 假设有一个collect_alpine函数

# --- 任务执行函数 ---
# 包装所有爬取逻辑，以便传递给进程
def run_collection_task(task_name, func, **kwargs):
    """
    一个包装函数，用于在进程中执行爬取任务，并处理可能的错误。
    """
    print(f"[{task_name}] 任务开始...")
    try:
        func(**kwargs)
        print(f"[{task_name}] 任务成功完成。")
    except Exception as e:
        print(f"[{task_name}] 任务失败: {e}")


if __name__ == "__main__":
    start_time = time.time()  # 记录开始时间

    """
    Package collector - 用于收集各种Linux发行版的软件包信息
    ... (参数解析部分不变)
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
    parser.add_argument('--process', type=int, default=4,
                        help='最大并行进程数 (默认: 4)')  # 新增并行数参数

    args = parser.parse_args()
    source_file_save = args.save
    http_timeout = args.timeout
    randint = args.rand
    download_dir = args.dir
    collect_types_str = args.types.lower()
    cache = args.cache
    max_processes = args.process

    # 解析收集类型
    if collect_types_str == 'all':
        collect_types = ['debian', 'ubuntu', 'centos', 'freebsd']
    else:
        collect_types = [t.strip() for t in collect_types_str.split(',')]

    # 创建下载目录
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    # 1. 定义所有可能的任务及其参数
    tasks = []

    # 准备任务参数
    task_config = {
        'debian': {
            'func': collect_deb,
            'kwargs': {
                "base_url": "https://mirrors.aliyun.com/debian/",
                "out_dir": os.path.join(download_dir, "debian"),
                "type_name": "Debian",
                "timeout": http_timeout,
                "save": source_file_save,
                "randint": randint,
                "cache": cache
            }
        },
        'ubuntu': {
            'func': collect_deb,
            'kwargs': {
                "base_url": "https://mirrors.aliyun.com/ubuntu/",
                "out_dir": os.path.join(download_dir, "ubuntu"),
                "type_name": "Ubuntu",
                "timeout": http_timeout,
                "save": source_file_save,
                "randint": randint,
                "cache": cache
            }
        },
        'centos': {
            'func': collect_rpm,
            'kwargs': {
                "output_dir": os.path.join(download_dir, "centos"),
                "base_url": "https://mirrors.aliyun.com/centos/",
                "type_name": "Centos",
                "timeout": http_timeout,
                "save": source_file_save,
                "randint": randint,
                "cache": cache
            }
        },
        'freebsd': {
            'func': collect_freebsd,
            'kwargs': {
                "output_dir": os.path.join(download_dir, "freebsd"),
                "base_url": "https://pkg.freebsd.org/",
                "type_name": "FreeBSD",
                "timeout": http_timeout,
                "cache": cache
                # 注意 freebsd 任务没有 save 和 randint 参数
            }
        },
        # 'alpine': { ... } # 如果要加入alpine，在这里配置
    }

    # 2. 筛选需要执行的任务，并创建对应的目录
    for type_name in collect_types:
        if type_name in task_config:
            config = task_config[type_name]
            task_dir = config['kwargs'].get('out_dir') or config['kwargs'].get('output_dir')

            # 创建子目录
            if task_dir and not os.path.exists(task_dir):
                os.makedirs(task_dir)

            # 将任务添加到列表
            tasks.append({
                'name': type_name.capitalize(),
                'func': config['func'],
                'kwargs': config['kwargs']
            })

    if not tasks:
        print("没有指定有效的收集类型，程序退出。")
        exit()

    # 3. 使用进程池或手动创建进程进行并行
    print(f"--- 准备启动 {len(tasks)} 个并行爬取任务 ---")

    # 采用简单的手动创建进程方式
    processes = []

    for task in tasks:
        # 创建进程，target指向包装函数，args传递任务名称和函数，kwargs作为关键字参数
        p = multiprocessing.Process(
            target=run_collection_task,
            args=(task['name'], task['func']),
            kwargs=task['kwargs']
        )
        processes.append(p)
        p.start()

    # 4. 等待所有进程完成
    for p in processes:
        p.join()

    end_time = time.time()
    print("--- 所有爬取任务完成 ---")
    print(f"总耗时: {end_time - start_time:.2f} 秒")