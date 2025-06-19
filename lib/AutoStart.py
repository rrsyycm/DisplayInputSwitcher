import os
import sys
import winreg as reg


class AutoStart:
    """处理程序的开机自启设置"""

    def __init__(self, name: str, path: str = None, hidden: bool = False):
        self.name = name
        self.path = os.path.abspath(path or sys.argv[0])
        self.hidden = hidden
        self.key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def exists(self) -> bool:
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, self.key_path) as key:
                reg.QueryValueEx(key, self.name)
                return True
        except Exception:
            return False

    def enable(self) -> bool:
        try:
            exec_path = f'"{self.path}"' if ' ' in self.path else self.path
            if self.hidden:
                exec_path += " --hidden"
            with reg.OpenKey(reg.HKEY_CURRENT_USER, self.key_path, 0, reg.KEY_SET_VALUE) as key:
                reg.SetValueEx(key, self.name, 0, reg.REG_SZ, exec_path)
            return True
        except Exception as e:
            print(f"Error enabling autostart: {e}")
            return False

    def disable(self) -> bool:
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, self.key_path, 0, reg.KEY_SET_VALUE) as key:
                reg.DeleteValue(key, self.name)
            return True
        except FileNotFoundError:
            return True
        except Exception as e:
            print(f"Error disabling autostart: {e}")
            return False

    def set_autostart(self, switch: bool, hidden: bool = None) -> bool:
        if hidden is not None:
            self.hidden = hidden
        return self.enable() if switch else self.disable()
