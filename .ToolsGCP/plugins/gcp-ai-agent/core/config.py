"""插件自己的配置读写
存到 ToolsGCP 给的 data_dir（可写目录）里，不要往插件目录写东西。
本插件只用它记一件小事：用户从这个页面转交过多少条想法。
"""

import json
import os


class Config:
    """极简 JSON 配置"""

    def __init__(self, data_dir: str, filename: str = "config.json"):
        self.path = os.path.join(data_dir, filename)
        self.data = {}
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8-sig") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}
        return self.data

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value):
        self.data[key] = value
        self.save()

    def bump(self, key: str, step: int = 1) -> int:
        """计数 +1，返回新值；配置被手改坏（存了"三"）时 int() 会抛，调用方自己 try"""
        value = int(self.get(key, 0)) + step
        self.set(key, value)
        return value
