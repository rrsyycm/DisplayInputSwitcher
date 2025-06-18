import argparse
import json
import os
import sys
import threading
import winreg as reg

import keyboard
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
    QTreeWidget, QTreeWidgetItem, QSystemTrayIcon, QMenu, QLabel
)
from monitorcontrol import get_monitors, InputSource

# ========== 常量定义 ==========
CONFIG_PATH = "config.json"
APP_NAME = "DisplayInputSwitcher"
APP_TITLE = "多显示器输入源切换工具"
ICON_PATH = "icon.ico"

# 设置工作目录为程序所在目录
os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))


# ========== 开机自启类 ==========
class Autostart:
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


# ========== 自定义树控件 ==========
class HotkeyTree(QTreeWidget):
    """用于显示器输入源配置的树状控件"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setHeaderLabels(["显示器/输入源", "热键", "备注", "状态"])
        self.setColumnWidth(0, 250)

    def keyPressEvent(self, event):
        item = self.currentItem()
        if not item or item.parent() or self.currentColumn() != 1:
            return super().keyPressEvent(event)

        mods = []
        if event.modifiers() & Qt.ControlModifier:
            mods.append("Ctrl")
        if event.modifiers() & Qt.AltModifier:
            mods.append("Alt")
        if event.modifiers() & Qt.ShiftModifier:
            mods.append("Shift")

        key = QKeySequence(event.key()).toString()
        if key and key not in mods:
            mods.append(key)
            item.setText(1, "+".join(mods))
            self.parent().update_config()


# ========== 主窗口类 ==========
class MonitorSwitcher(QWidget):
    """主应用窗口"""

    def __init__(self, hidden=False):
        super().__init__()
        self.hidden_mode = hidden
        self.setWindowTitle(APP_TITLE)
        self.resize(800, 500)

        self.app = Autostart(name=APP_NAME)
        self.monitor_data = self.get_monitor_data()
        self.config_map = {}

        self.tree = HotkeyTree(self)
        self.tree.itemChanged.connect(self.update_config)
        self.tray = None

        self.init_ui()
        self.init_tray()
        self.load_config()
        self.hotkey_listener()

    # ========== 初始化界面 ==========
    def init_ui(self):
        layout = QVBoxLayout(self)
        btns = QHBoxLayout()

        btn_add = QPushButton("添加配置项")
        btn_add.clicked.connect(self.add_item)
        btns.addWidget(btn_add)

        btn_del = QPushButton("删除选中行")
        btn_del.clicked.connect(self.delete_item)
        btns.addWidget(btn_del)

        layout.addLayout(btns)
        layout.addWidget(self.tree)

        self.autostart_box = QCheckBox("开机自启")
        self.autostart_box.setChecked(self.app.exists())
        self.autostart_box.stateChanged.connect(lambda s: self.app.set_autostart(s == 2, hidden=True))
        layout.addWidget(self.autostart_box)

    # ========== 托盘图标 ==========
    def init_tray(self):
        self.tray = QSystemTrayIcon(QIcon(self.resource_path(ICON_PATH)), self)
        self.tray.setToolTip(APP_TITLE)

        menu = QMenu(self)
        menu.addAction(QAction("打开主界面", self, triggered=self.showNormal))
        menu.addAction(QAction("退出", self, triggered=QApplication.quit))
        self.tray.setContextMenu(menu)

        self.tray.activated.connect(lambda r: self.showNormal() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

        if self.hidden_mode:
            self.tray.showMessage("程序已启动", "程序正在后台运行", QSystemTrayIcon.Information, 3000)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray.showMessage("最小化到托盘", "程序仍在后台运行", QSystemTrayIcon.Information, 3000)

    # ========== 热键监听 ==========
    def hotkey_listener(self):
        def listen():
            while True:
                event = keyboard.read_event()
                if event.event_type == keyboard.KEY_DOWN:
                    combo = []
                    if keyboard.is_pressed("ctrl"): combo.append("Ctrl")
                    if keyboard.is_pressed("alt"): combo.append("Alt")
                    if keyboard.is_pressed("shift"): combo.append("Shift")
                    combo.append(event.name.upper())
                    combo_str = "+".join(combo)

                    cfg = self.config_map.get(combo_str)
                    if cfg:
                        self.switch_monitor_input(cfg)

        threading.Thread(target=listen, daemon=True).start()

    # ========== 配置操作 ==========
    def add_item(self):
        parent = QTreeWidgetItem(self.tree, ["配置", "双击编辑后按下热键", "", ""])
        parent.setFlags(parent.flags() | Qt.ItemIsEditable)
        self.tree.setItemWidget(parent, 0, QLabel(""))
        parent.setCheckState(3, Qt.Checked)
        parent.setExpanded(True)

        for mid, mon in self.monitor_data.items():
            m_item = QTreeWidgetItem(parent, [mon["display_name"], "", ""])
            m_item.setData(0, Qt.UserRole, mid)
            for src in mon["sources"]:
                s_item = QTreeWidgetItem(m_item, [src, "", ""])
                s_item.setCheckState(0, Qt.Unchecked)
        self.update_config()

    def delete_item(self):
        item = self.tree.currentItem()
        if item and item.parent() is None:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
            self.update_config()

    def update_config(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.collect_config(), f, ensure_ascii=False, indent=2)

    def collect_config(self):
        configs = []
        self.config_map.clear()

        for i in range(self.tree.topLevelItemCount()):
            top_item = self.tree.topLevelItem(i)
            if not top_item:
                continue

            hotkey = top_item.text(1).strip()
            remark = top_item.text(2).strip()
            enabled = top_item.checkState(3) == Qt.Checked

            models = []
            for j in range(top_item.childCount()):
                mon_item = top_item.child(j)
                monitor_id = mon_item.data(0, Qt.UserRole)
                display_name = mon_item.text(0)

                selected_sources = [
                    mon_item.child(k).text(0)
                    for k in range(mon_item.childCount())
                    if mon_item.child(k).checkState(0) == Qt.Checked
                ]

                if selected_sources:
                    models.append({
                        "monitor_id": monitor_id,
                        "display_name": display_name,
                        "available_sources": selected_sources
                    })

            config_entry = {
                "hotkeys": hotkey,
                "enabled": enabled,
                "remark": remark,
                "models": models
            }

            if enabled and hotkey:
                self.config_map[hotkey] = config_entry

            configs.append(config_entry)

        return configs

    def load_config(self):
        if not os.path.exists(CONFIG_PATH):
            return
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data:
            parent = QTreeWidgetItem(self.tree, ["配置", entry.get("hotkeys", ""), entry.get("remark", ""), ""])
            parent.setFlags(parent.flags() | Qt.ItemIsEditable)
            self.tree.setItemWidget(parent, 0, QLabel(""))
            parent.setCheckState(3, Qt.Checked if entry.get("enabled", True) else Qt.Unchecked)
            parent.setExpanded(True)

            for monitor_id, model_cfg in self.monitor_data.items():
                models = entry.get("models", [])
                target_model = next((m for m in models if m.get("monitor_id") == monitor_id), None)

                model_item = QTreeWidgetItem(parent, [model_cfg["display_name"], "", ""])
                model_item.setData(0, Qt.UserRole, monitor_id)

                sources = target_model.get("available_sources", []) if target_model else []
                for source in model_cfg['available_sources']:
                    input_item = QTreeWidgetItem(model_item, [source, "", ""])
                    input_item.setCheckState(0, Qt.Checked if source in sources else Qt.Unchecked)

    # ========== 输入源切换 ==========
    def switch_monitor_input(self, cfg):
        for monitor in get_monitors():
            with monitor:
                model = monitor.get_vcp_capabilities().get("model", "")
                for c in cfg["models"]:
                    if c["display_name"] == model:
                        sources = c["available_sources"]
                        try:
                            cur = InputSource(monitor.get_input_source()).name
                            idx = (sources.index(cur) + 1) % len(sources)
                        except Exception:
                            idx = 0
                        monitor.set_input_source(InputSource[sources[idx]])
                        print(f"切换 {model} 至 {sources[idx]}")

    # ========== 工具函数 ==========
    @staticmethod
    def resource_path(relative_path):
        return os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(__file__)), relative_path)

    @staticmethod
    def get_monitor_data():
        monitor_data = {}
        for idx, monitor in enumerate(get_monitors()):
            try:
                with monitor:
                    caps = monitor.get_vcp_capabilities()
                    monitor_data[f"monitor_{idx}"] = {
                        "monitor_id": f"monitor_{idx}",
                        "display_name": caps.get("model", f"Unknown Monitor {idx}"),
                        "sources": [s.name for s in caps.get("inputs", [])],
                        "available_sources": [s.name for s in caps.get("inputs", [])]
                    }
            except Exception:
                pass
        return monitor_data


# ========== 程序入口 ==========
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--hidden', action='store_true', help='以隐藏模式启动')
    args = parser.parse_args()

    app = QApplication(sys.argv)
    win = MonitorSwitcher(hidden=args.hidden)

    if not args.hidden:
        win.show()

    app.exec()
