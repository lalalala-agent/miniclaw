---
name: powerpoint
description: "用 python-pptx 脚本创建、读取和修改 .pptx。"
---

# Powerpoint

用仓库里的脚本创建、查看和修改 PowerPoint（.pptx）。脚本离线运行，不需要安装 PowerPoint。

## 何时使用

- 用户要做幻灯片、汇报或提案。
- 需要从已有 `.pptx` 取出文字、备注、表格、图表数据或图片。
- 需要改已有文稿：替换文字、改图表数据、换图片、复制或删除或重排幻灯片、背景、页脚、超链接、备注。
- 需要按带 `{{token}}` 的模板填充成稿。
- 不处理旧版 `.ppt`。若本机有 LibreOffice，先 `soffice --convert-to pptx`。

## 怎么运行

`run_command` 的工作目录是工作区，`PATH` 里已经有本仓库虚拟环境，直接用 `python`。脚本目录是 `{{PPTX_SCRIPTS}}`。用绝对路径调用脚本。规格和成品用相对工作区的路径。要放映的成品写到 `presentations/`。

命令超时 60 秒。超时就说明原因，不要改成无限等待。

```bash
python {{PPTX_SCRIPTS}}/pptx_create.py spec.json presentations/out.pptx
python {{PPTX_SCRIPTS}}/pptx_read.py presentations/out.pptx --outline
python {{PPTX_SCRIPTS}}/pptx_read.py presentations/out.pptx --notes
python {{PPTX_SCRIPTS}}/pptx_read.py presentations/out.pptx --images presentations/img
python {{PPTX_SCRIPTS}}/pptx_edit.py presentations/out.pptx --replace-text "Old Corp" "New Corp"
python {{PPTX_SCRIPTS}}/pptx_edit.py presentations/out.pptx --chart-data update.json
python {{PPTX_SCRIPTS}}/pptx_edit.py presentations/out.pptx --duplicate-slide 2
python {{PPTX_SCRIPTS}}/pptx_edit.py presentations/out.pptx --remove-slide 3 --move-slide 2 0
python {{PPTX_SCRIPTS}}/pptx_from_template.py brand.pptx presentations/out.pptx --values vals.json
python {{PPTX_SCRIPTS}}/pptx_render.py presentations/out.pptx --outdir presentations/render
```

用 `write_file` 写 JSON 规格。用 `read_file` 看脚本输出。每个脚本都支持 `--help`，失败时退出码非 0，成功时向标准输出打印 JSON。

## 命令对照

| 任务 | 命令 |
|---|---|
| 按规格新建 | `pptx_create.py spec.json out.pptx` |
| 16:9 或 4:3 | 规格里 `"slide_size": "16:9"` 或 `"4:3"` |
| 大纲 JSON | `pptx_read.py deck.pptx --outline` |
| 导出图片 | `pptx_read.py deck.pptx --images DIR` |
| 替换文字 | `pptx_edit.py deck.pptx --replace-text OLD NEW` |
| 替换整张图表数据 | `pptx_edit.py deck.pptx --chart-data spec.json` |
| 改一条系列 | 同一参数，规格里带 `"ops"` |
| 换图片 | `pptx_edit.py deck.pptx --swap-image N NAME new.png` |
| 复制幻灯片 | `pptx_edit.py deck.pptx --duplicate-slide N` |
| 删除幻灯片 | `pptx_edit.py deck.pptx --remove-slide N` |
| 调整顺序 | `pptx_edit.py deck.pptx --move-slide FROM TO` |
| 背景色 | `pptx_edit.py deck.pptx --set-background N RRGGBB` |
| 超链接 | `pptx_edit.py deck.pptx --hyperlink N TEXT URL` |
| 页码 | `pptx_edit.py deck.pptx --enable-slide-number N` |
| 页脚 | `pptx_edit.py deck.pptx --set-footer N TEXT` |
| 设置备注 | `pptx_edit.py deck.pptx --set-notes N TEXT` |
| 追加备注 | `pptx_edit.py deck.pptx --append-notes N TEXT` |
| 填充模板 | `pptx_from_template.py tpl.pptx out.pptx --values v.json` |
| 渲染 PNG | `pptx_render.py deck.pptx --outdir DIR` |

## 步骤

### 1. 新建

先 `write_file` 写 JSON，再跑 `pptx_create.py`。完整字段以 `pptx_create.py --help` 为准。每一页可以设置：

- `layout`：`title`、`title_content`、`section`、`two_content`、`title_only`、`blank`
- `title`、`subtitle`
- `bullets`：字符串，或带 `level`（0-4）、`size`、`bold`、`italic`、`font`、`color`（十六进制）、`link` 的对象
- `background`：纯色十六进制
- `footer`、`slide_number`
- `images`：`path` 以及英寸为单位的 `left`、`top`、`width`、`height`
- `tables`：`rows` 为二维数组
- `shapes`：`rectangle`、`rounded_rectangle`、`oval`、`diamond`、`right_arrow`、`chevron`，带 `fill`，可选 `text`
- `charts`：`bar`、`bar_h`、`line`、`pie`，带 `categories` 和 `series`
- `notes`：演讲者备注

`title_content` 大约 5 到 6 条、15pt 就到了版心。更多内容拆页，不要把字号降到 13pt 以下。

### 2. 读取

`pptx_read.py deck.pptx --outline` 返回页面尺寸、版式列表，以及每页的文字、表格、图片清单、图表分类和系列、备注。`--images DIR` 把内嵌图片导出到文件。本代理没有看图工具，用大纲核对内容和结构。

### 3. 修改

`pptx_edit.py` 一次可以做多件事。用 `--output` 可以留下原稿。替换文字会扫形状、表格和备注。换图只改关系 id，位置和大小不变。删页和调序是在 XML 里改的。`--duplicate-slide N` 深拷贝该页并追加到末尾；带图表的页会拒绝复制，应在新页上重建图表。

图表整表替换：`{"slide": 0, "chart": 0, "categories": [...], "series": {...}}`。局部修改用 `"ops"`：`update_series`、`add_series`、`remove_series`、`rename_category`、`set_title`。python-pptx 只能整表替换，ops 是读出、修改、再写回。不能改图表类型。

### 4. 从模板生成

`pptx_from_template.py` 打开品牌模板，把 `{{token}}` 换成 values JSON 里的值，范围包括幻灯片、表格和备注。也可以按模板自己的版式名或序号追加新页。若只要母版、不要原有页，生成后再用 `--remove-slide` 删掉旧页。先用 `pptx_read.py template.pptx --outline` 看 `layouts_available`。写规格文件时使用 UTF-8。

### 5. 渲染

有 `soffice` 和 `pdftoppm`（或 `pdftocairo`）时，`pptx_render.py` 会导出每页 PNG。缺工具时脚本以退出码 0 返回 `{"rendered": false, "missing": [...]}`。这时以 `--outline` 为准，并告诉用户没有渲染。导出 PDF：

```bash
soffice --headless --convert-to pdf --outdir presentations presentations/deck.pptx
```

没有 `soffice` 时直接说明，不要用别的方式假装导出了 PDF。

## 容易出错的地方

- 替换文字时，格式相同的相邻 run 会先合并。跨了不同格式的匹配会按第一段的格式重写，改完要再读那一页。
- 带图表的页不能复制。
- 调序是直接改 `<p:sldIdLst>`，改完要再读一遍确认。
- 不能把一页从一个文件复制到另一个文件。
- 版式没有页脚占位时，`--set-footer` 会失败，改用文本框。
- `--hyperlink` 会给该页所有包含这段文字的 run 加上链接。
- 默认新建是 16:9。模板保持自己的尺寸。
- `slide.shapes.title` 在空白版式上是空的。脚本已经处理，手写 python-pptx 时要注意。

## 做完要核对

1. 创建或修改后跑 `pptx_read.py OUT.pptx --outline`，核对页数、文字、表格、备注和图表数据。
2. 需要确认图片时用 `--images`，再看文件是否写出来。
3. 渲染工具可用时再跑 `pptx_render.py`。不可用就依赖大纲。
