import sys
import winreg
from typing import Optional, Callable, Tuple
from datetime import datetime, timedelta

import requests
import win32api
from packaging import version


class AutoUpdater:
    def __init__(
            self,
            repo_owner: str,
            repo_name: str,
            current_version: Optional[str] = None,
            check_at_startup: Optional[bool] = None,
            update_callback: Optional[Callable[[str, str, str], None]] = None,
            skip_days: int = 7  # 默认跳过7天
    ):
        """
        初始化自动更新器

        :param repo_owner: GitHub仓库所有者
        :param repo_name: GitHub仓库名
        :param current_version: 当前版本号 (str)，如果为None则自动获取EXE版本
        :param check_at_startup: 是否启动时自动检查更新，None=从注册表读取
        :param update_callback: 发现更新时的回调函数，格式: func(current_version, latest_version, download_url)
        :param skip_days: 跳过更新的天数
        """
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.default_version = '0.0.0.0'
        self.current_version = current_version if current_version is not None else self.get_exe_version()
        self.latest_version = None
        self.github_api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest"
        self.update_available = False
        self.update_callback = update_callback
        self.skip_days = skip_days
        self.latest_download_url = None

        # 注册表配置
        self.registry_key = f"Software\\{repo_owner}\\{repo_name}"
        if check_at_startup is None:
            self.check_at_startup = self._get_registry_setting("CheckAtStartup", False)
        else:
            self.check_at_startup = check_at_startup

        if self.check_at_startup:
            self.check_for_updates()

    def _get_registry_setting(self, name: str, default_value):
        """从注册表读取设置"""
        if not sys.platform.startswith('win'):
            return default_value

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_key) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return value
        except WindowsError:
            return default_value

    def _set_registry_setting(self, name: str, value):
        """写入注册表设置"""
        if not sys.platform.startswith('win'):
            return False

        try:
            # 确保注册表路径存在
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_key, 0, winreg.KEY_WRITE) as key:
                    pass
            except WindowsError:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.registry_key) as key:
                    pass

            # 写入值
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_key, 0, winreg.KEY_WRITE) as key:
                if isinstance(value, int):
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
                elif isinstance(value, str):
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                elif isinstance(value, bytes):
                    winreg.SetValueEx(key, name, 0, winreg.REG_BINARY, value)
                else:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
            return True
        except WindowsError as e:
            print(f"无法写入注册表: {e}")
            return False

    def get_exe_version(self) -> str:
        """获取EXE文件版本 (Windows专用)"""
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = sys.argv[0]

        try:
            info = win32api.GetFileVersionInfo(exe_path, '\\')
            version = "%d.%d.%d.%d" % (
                info['FileVersionMS'] // 65536,
                info['FileVersionMS'] % 65536,
                info['FileVersionLS'] // 65536,
                info['FileVersionLS'] % 65536
            )
            return version
        except:
            return self.default_version

    def _is_update_skipped(self, version: str) -> bool:
        """检查指定版本是否被跳过"""
        skipped_until = self._get_registry_setting(f"SkippedUpdate_{version}", None)
        if skipped_until:
            try:
                # 从注册表读取的是字符串，转换为datetime
                skipped_until = datetime.strptime(skipped_until, "%Y-%m-%d %H:%M:%S")
                return datetime.now() < skipped_until
            except ValueError:
                pass
        return False

    def skip_update(self, version: str, days: Optional[int] = None):
        """
        跳过指定版本的更新

        :param version: 要跳过的版本号
        :param days: 跳过的天数，None则使用初始化时设置的天数
        """
        skip_days = days if days is not None else self.skip_days
        skip_until = datetime.now() + timedelta(days=skip_days)
        self._set_registry_setting(
            f"SkippedUpdate_{version}",
            skip_until.strftime("%Y-%m-%d %H:%M:%S")
        )

    def check_for_updates(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        检查是否有更新可用

        :return: (是否有更新, 当前版本, 最新版本)
        """
        try:
            response = requests.get(self.github_api_url, timeout=10)
            response.raise_for_status()
            release_info = response.json()
            self.latest_version = release_info['tag_name'].lstrip('v')

            # 检查是否已跳过此版本
            if self._is_update_skipped(self.latest_version):
                print(f"已跳过版本 {self.latest_version} 的更新检查")
                return (False, self.current_version, self.latest_version)

            # 获取第一个可下载资源
            if release_info.get('assets'):
                self.latest_download_url = release_info['assets'][0]['browser_download_url']
            else:
                self.latest_download_url = None

            # 版本比较
            if version.parse(self.latest_version) > version.parse(self.current_version):
                self.update_available = True
                # 如果有回调函数则调用
                if self.update_callback and self.latest_download_url:
                    self.update_callback(self.current_version, self.latest_version, self.latest_download_url)
                return (True, self.current_version, self.latest_version)
            return (False, self.current_version, self.latest_version)
        except Exception as e:
            print(f"检查更新失败: {e}")
            return (False, self.current_version, None)

    def enable_auto_check(self, enable: bool = True) -> bool:
        """启用或禁用启动时自动检查更新"""
        self.check_at_startup = enable
        if sys.platform.startswith('win'):
            return self._set_registry_setting("CheckAtStartup", int(enable))
        return True


def main():
    def update_callback(current: str, latest: str, url: str):
        """更新回调函数示例"""
        print(f"\n发现新版本: {latest} (当前: {current})")
        print(f"下载地址: {url}")
        choice = input("是否更新? (y=更新, s=跳过本次更新, n=不更新): ").lower()

        if choice == 'y':
            print("开始下载更新...")
            # 这里添加下载逻辑
        elif choice == 's':
            updater.skip_update(latest)
            print(f"已跳过版本 {latest} 的更新")
        else:
            print("更新已取消")

    # 配置你的GitHub仓库信息
    REPO_OWNER = "your_github_username"
    REPO_NAME = "your_repo_name"
    CURRENT_VERSION = "1.0.0"  # 默认版本号

    # 初始化自动更新器
    updater = AutoUpdater(
        repo_owner=REPO_OWNER,
        repo_name=REPO_NAME,
        current_version=CURRENT_VERSION,
        check_at_startup=True,
        update_callback=update_callback,
        skip_days=7  # 跳过7天
    )

    print("正在检查更新...")
    has_update, current, latest = updater.check_for_updates()
    if has_update:
        print(f"发现新版本: {latest} (当前: {current})")
    else:
        print("当前已是最新版本。")


if __name__ == "__main__":
    main()
