# assets —— 放插件的图片等资源

这个文件夹用来放**只读资源**：图标、图片、图标字体、示例数据……

## 用法

在代码里这样引用（`context.plugin_dir` 就是插件目录）：

```python
import os
from PyQt5.QtGui import QPixmap

image_path = os.path.join(context.plugin_dir, "assets", "icon.png")
pixmap = QPixmap(image_path)
```

在 `manifest.json` 里也能用它当插件图标：

```json
{ "icon": "assets/icon.png" }
```

## 注意

- 这里的文件是**只读资源**，程序运行时不要往里写
- 要存用户数据 / 缓存 / 配置，请用 `context.data_dir`（ToolsGCP 会自动创建）
- 路径一律用 `os.path.join`，不要写死 `\` 或 `/`，这样跨平台不会出问题

当前文件夹里的 `icon.png` 只是一个占位图，换成你自己的就行。
