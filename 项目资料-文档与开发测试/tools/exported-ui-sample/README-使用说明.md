> ⚠️ 这是**样例子集**（不是完整导出）：40 张组件 + 12 张整图。
> 完整导出请运行 `ToolsGCP_UI_Asset_Exporter.py --yes --themes both --out "<目录>"`。

# ToolsGCP UI 素材包（宣传片用）

由 `ToolsGCP_UI_Asset_Exporter.py` 从程序**真实 DOM** 逐组件导出。

- 生成时间：2026-10-30T07:22:05
- 视口：1440x900，倍率：1（PNG 像素 = CSS 像素 × 1）
- 主题效果：mica，强调色：blue

## 目录结构

```
<输出目录>/
  manifest.json         全局清单（每张图的名字/尺寸/坐标/主题/说明）
  assets.csv            同一份清单的表格版（Excel 可直接打开）
  dark/<页面key>/*.png  深色主题
  light/<页面key>/*.png 浅色主题（--themes both 时才有）
  <页面key>/page.json   该页的清单
```

## 在剪映里用（分层动效排版）

1. **同一屏的素材放在同一时间点**：所有图都是 1440×900 视口下按真实布局截的，
   PNG 中心点 = 元素中心点。把图按 `bbox`（视口坐标 x/y）摆回去，就能 1:1 还原界面。
2. 导入 1440×900 的黑色/透明画布 → 逐张拖入、按 时间线×(倍率 1) 缩放，用 `bbox.x/bbox.y` 设置位置
   （剪映的位置是中心点：left = bbox.x + css_w/2，top = bbox.y + css_h/2）。
3. `px_size` 是 PNG 实际像素，`css_size` 是界面里的逻辑尺寸；**缩放比例 = 1**。
4. 分组动画：`page` 相同的一组属于同一屏（比如 search 页的卡片 + 按钮 + 标签），
   可以对它们做同一组关键帧（整体上浮/缩放），因为坐标同源。
5. 透明 PNG 可直接叠加发光/模糊特效；`transparent: false` 的图自带底色，
   建议铺在最底层或直接覆盖画面。

## 已知限制（不伪造成功，每个都在 manifest.skipped 里有说明）

- **整页背景**（渐变 + 海报模糊）不是组件，导出会带底色，故不作为素材；
  需要背景请用同目录 `chrome` 页的 `.titlebar` 等素材自行拼，或整屏截图另存。
- **backdrop-filter（云母/玻璃/亚克力）**：单独抠图会失去材质。这类组件同时给了
  `*__opaque.png`（含页面背景），叠加时优先用 opaque 版。
- **远程图片 / 视频 / 轮播过渡帧**：素材来自网络与动画中间态，静态导出只有首帧或占位。
- **iframe 插件配置页**：跨文档无法裁剪，需打开插件后整屏截。
- **系统原生部分**（窗口圆角/边框、托盘菜单、原生右键菜单）由 Python 绘制，不是 DOM，
  不在本工具范围；如需这部分请用录屏 + 蒙版。
- 动画中间态没有导出（等页面静止后才量）；需要中间帧请录屏。

## 复现命令

```bat
python ToolsGCP_UI_Asset_Exporter.py --yes --themes both --scale 1 --out "C:\Users\Administrator\Desktop\ToolsGCP开发\v1.1.4 - 12\.tmp-exporter\r20-final"
```

工具单文件、零第三方依赖，只读原程序文件，不修改程序与用户数据。
