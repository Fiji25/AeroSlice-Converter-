# AeroSlice Converter · 航模切片兼容转换器

[English](#english) · [中文](#中文) · Version 0.2.5

## English

**Apple Silicon support:** a native ARM64 source launcher, macOS build specification and manual GitHub Actions workflow are now included. Target macOS 14+ / Python 3.12. The current Windows host has not executed a Mac build; this is not yet a verified .app download. See [Mac setup and build instructions](docs/macos_apple_silicon.md).

Cura Surface-only RC aircraft models can be difficult to use in other slicers. AeroSlice reconstructs their skin and ribs as layered material regions for **Bambu Studio Even-Odd** slicing, while preserving the original files. PrusaSlicer and OrcaSlicer compatibility is a project goal; their complete workflows are not yet independently validated here.

### Two reconstruction methods

| Method | Geometry | Slicing heights |
|---|---|---|
| Layered (still the default) | Stacked extruded sections, with visible steps | Layer height and first-layer height must match reconstruction |
| Continuous thin wall (optional) | A closed thin-wall mesh reconstructed around the original surfaces | Set layer height and first-layer height in the slicer; geometry is not tied to either |

For a continuous exterior, select **连续薄壁（层高由切片器设置）** and use the original Surface model. The application selects Regular mode and hides the reconstruction-layer-height field. This method does not smooth an already-layered STL: it rebuilds the original surfaces at a geometric accuracy independent of printing height. Both sides are thickened, so the exterior expands by about half the chosen material thickness. Inspect joints, small holes and actual rib toolpaths.

### Quick start

1. Extract the complete Windows package. Keep `_internal` beside `AeroSliceConverter.exe`, then launch the executable.
2. Import the **original** STL or geometry 3MF, or a folder of models. Coordinates are handled in millimetres. Choose **Surface 自动重建** for Surface parts; the default reconstruction remains layered, at 0.20 mm / 0.45 mm material width.
3. Select an output directory and click **一键转换并导出**. STL is the default. A matching completed conversion is reused when exporting again. Desktop export writes model files directly to that directory without automatic JSON sidecars.
4. Open **查看 / 复制本次成品切片设置** for the completed result's settings. Copy them or explicitly save a TXT card. Set **both layer height and first layer height** to the reconstruction height. Use **Even-Odd**, preserve the original Z direction, scale and position, and disable adaptive layers.
5. Start with Arachne, 3 wall loops, 100% material infill, and 0 top/bottom layers; inspect the actual sliced skin and ribs before printing. This is a reference starting point, not a universal preset or a complete printer/filament profile.

100% infill applies to the reconstructed material, not the aircraft cavities. Layered STL contains steps and contacting slab faces; it is not a smooth continuous surface. Do not automatically repair, union the entire stack, or reconstruct an already converted model. To change layer height, convert the original again. STL does not preserve conversion metadata: keep track of the result's settings card.

### Troubleshooting and scope

| Symptom | First check |
|---|---|
| Stripes or missing layers in the slicer | Match reconstruction height, slicing height **and first layer height**; preserve Z position and disable adaptive layers. |
| “Cannot preserve as closed solid” | Choose Surface automatic reconstruction for an open Surface part. |
| One file fails during folder import | Read the filename and reason in the report. Other files continue importing; macOS resource forks are ignored. |
| Missing ribs or short strokes | Inspect toolpaths. Small features, features below the layer height and horizontal sheets may be omitted; changing slicer settings is not proof of complete coverage. |

Geometry checks do not certify slicer toolpaths or physical printing. The previous ICON P3 audit covered 26 distinct Surface models using a particular Bambu setup, not every model or printer. Fuselage 4-p3 retains a known local short-stroke omission requiring review. 3MF export contains geometry and conversion hints, **not** a full printer or filament project. Continuous reconstruction remains optional and is not the default.

### Develop and contribute

Use Python 3.12 on Windows. No aircraft models are included in the source archive.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
.venv\Scripts\python.exe -m pytest -q --basetemp .tmp/pytest-local
```

Create `.tmp` before the test command. `build.bat` installs dependencies, runs tests and builds the Windows GUI/CLI. See [contribution guidance](CONTRIBUTING.md) and [release notes](docs/release_0.2.5.md). Bug and pull-request templates are included. The Windows CI workflow runs source tests; it does not validate real printer output or publish releases.

### Project status, licensing and sponsorship

This is an experimental source-available project. **A project-wide license and contributor commercial-authorization arrangement remain to be finalized.** Public source availability alone does not grant blanket rights to sell or redistribute it. Check [third-party notices](THIRD_PARTY_NOTICES.md), especially the installed MeshLib runtime's non-commercial and transfer restrictions, before distributing binaries. This update does not resolve those permissions.

Sponsorship is optional. The author plans to share part of sponsorship actually received with code contributors, considering contribution quality, impact and maintenance through discussion. No fixed amount, percentage or schedule is promised. Sponsorship does not affect free use or grant resale rights. A payment code can be added by the author; none is embedded here.

## 中文

**M 系列 Mac 支持：**新增原生 ARM64 源码启动器、macOS 打包配置和手动 GitHub Actions 构建流程，目标 macOS 14+ / Python 3.12。本次 Windows 环境尚未执行 Mac 构建，不应当作已有验证通过的 .app。详见 [Mac 启动与构建说明](docs/macos_apple_silicon.md)。

Cura 的 Surface 表面模式给航模跨切片软件使用带来了不少麻烦。本项目将依赖该模式的原始 STL / 3MF 外皮与筋板，重建为供**拓竹 Even-Odd（奇偶）模式**切片的逐层材料区域，并保留原文件。PrusaSlicer / OrcaSlicer 兼容属于项目目标，这里尚未独立验证其完整流程。

### 两种重建方式

| 方式 | 成品几何 | 切片层高 |
|---|---|---|
| 逐层（仍为默认） | 截面薄层叠加，有阶梯 | 层高、首层高度须匹配重建层高 |
| 连续薄壁（可选） | 沿原始曲面生成封闭薄壁网格 | 由切片器设置，不绑定重建层高 |

希望得到连续外形时，选择“**连续薄壁（层高由切片器设置）**”，导入**原始 Surface 模型**。软件自动选择 Regular，并隐藏重建层高字段。它按几何精度重建原面，不是把已有逐层 STL 磨平。双侧加厚会让外轮廓增加约半个材料厚度，仍须核对接口、小孔和筋板刀路。旧逐层成品不能由此恢复为原始曲面。

### 快速使用

1. 完整解压 Windows 软件包，保留 `_internal`，运行 `AeroSliceConverter.exe`。
2. 导入**原始** STL / 几何 3MF 或文件夹，按毫米处理。Surface 零件选择“Surface 自动重建”；默认保持逐层方案，层高 0.20 mm、材料宽度 0.45 mm。
3. 选择输出目录，点击“一键转换并导出”。默认 STL，直接保存到目录，不自动附带 JSON。已转换且参数匹配时直接复用；修改输入、转换勾选、结构类型或参数后才重建。
4. 打开“查看 / 复制本次成品切片设置”。数值取自**已完成成品**，可以复制或手动另存 TXT。切片层高和**首层高度**都须与重建一致；启用 Even-Odd，保持原 Z 方向、比例、位置，关闭自适应层高。
5. 参考起点：Arachne、3 层墙、材料区域 100% 填充、顶底 0 层。打印前逐层查看外皮与筋板刀路；这不是所有模型通用的保证，也不包含完整机型与耗材配置。

100% 填充针对重建薄壁材料，不会因此填满飞机空腔。逐层成品有阶梯及层间接触面，不是连续光滑面；不要自动修复、整栈布尔合并或再次重建成品。改层高应重新转换原始模型。STL 不保存重建参数，请记住对应设置或手动保存设置卡。

### 常见问题与限制

- 条纹、缺层：首先核对重建层高、切片层高、首层高度及 Z 位置，并关闭自适应层高。
- 开放曲面不能“保留实体”：改选“Surface 自动重建”。
- 文件夹中某个文件损坏：其余文件继续导入，下方报告保留文件名和原因；macOS 辅助文件会自动忽略。
- 短线或筋板漏切：检查实际刀路。小于层高的细节、水平薄片和局部短线可能丢失，不能仅凭预览外观判定成功。

几何校验通过不等于刀路或实物打印验证通过。此前 ICON P3 的 26 个独立 Surface 模型审核只覆盖指定拓竹设置，不能推广为所有模型或机型均通过；Fuselage 4-p3 仍有局部短线遗漏需复核。导出 3MF 是几何与约束提示，不是完整打印工程。连续曲面可选，**不设为默认**。

### 参与改进、许可与赞助

Windows 推荐 Python 3.12，运行方式见上方命令。[贡献指南](CONTRIBUTING.md)说明如何报告问题、运行测试及提交修复；源码包不包含航模文件。`build.bat` 可构建 GUI / CLI。CI 仅测试源码，不代表真实打印验证。

当前为公开源码的实验项目，**正式项目许可及贡献者商业授权安排仍待确定**。公开仓库不自动授予任意售卖或再分发权。分发前请核对[第三方许可](THIRD_PARTY_NOTICES.md)，尤其 MeshLib 的非商业和转移限制；本次更新未解决该授权。

赞助完全自愿，不影响软件免费使用，也不授予售卖权。作者计划把实际收到赞助的一部分回馈代码贡献者，结合贡献质量、影响及维护投入沟通确定，不承诺固定金额、比例或时间。收款码由作者自行添加。
