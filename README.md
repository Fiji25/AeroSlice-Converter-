[README.md](https://github.com/user-attachments/files/33748007/README.md)
# AeroSlice-Converter-
Aims to convert Cura Surface-only RC aircraft models for PrusaSlicer, OrcaSlicer and Bambu Studio, reducing compatibility and preparation hassles.Cura 表面模式常让航模切片颇为头疼。本项目旨在将依赖该模式的模型转换为可供 PrusaSlicer、OrcaSlicer、拓竹等软件切片的模型，减少兼容与修模麻烦。
# AeroSlice Converter 0.2.4

**航模 Surface 模型切片兼容转换器 · Aircraft Surface Model Converter**

[English](#english) · [中文](#中文)

## English

### Overview

AeroSlice Converter is an offline Windows utility for 3D-printed aircraft. It reconstructs STL / 3MF models originally intended for Cura **Surface mode** into material-bearing geometry for subsequent **Even-Odd slicing in Bambu Studio**.

The engine builds material regions from aircraft skins and internal ribs while preserving geometric cavities. Import a model and use one-click conversion/export; configure the printer and filament in the target slicer.

> Fixed-height layered reconstruction remains the default. Continuous reconstruction has not become the default. The result contains steps and contacting caps, rather than a lossless smooth surface.

### Changes in 0.2.4

This release addresses **layer-section coverage failures** caused by some short reversing branches in the original intersection lines.

When the original buffering path misses a source segment, the engine locates the uncovered segments, buffers only those segments at the same material width, unions them with the existing material, and rechecks the entire section using the unchanged **0.008 mm tolerance**. Export still stops if the recheck fails.

Unaffected sections retain the original path. Reports record repaired layers, segment counts and added area. Errors include the part name, layer number and Z position. The fix is not tied to a particular model name and does not relax coverage acceptance.

Inherited features include the Surface role guard from 0.2.3, completed-conversion reuse, parameter-aware cache invalidation, direct GUI export to the chosen folder, STL as the GUI default, no GUI JSON sidecars, automatic numbering to avoid overwrites, geometry-only 3MF output and a separate CLI executable.

### Quick start

1. Extract the matching Windows x64 package and keep its complete directory, including `_internal`.
2. Launch `AeroSliceConverter.exe`.
3. Import an original STL / 3MF and check dimensions. STL coordinates are read as millimeters.
4. Use Surface automatic reconstruction and confirm the reconstruction layer height and material width.
5. Select an output folder and run one-click conversion/export.
6. Import the result into Bambu Studio, select Even-Odd, and inspect the actual toolpaths layer by layer.

If conversion was completed beforehand, exporting reuses that result. Output folder, format and separate-part options can change without reconversion. Geometry, roles, conversion selections or conversion parameters invalidate the cache.

### Slicer settings: match the layer height

| Setting | Reference for a 0.20 mm layered output |
|---|---|
| Slicing mode | Even-Odd |
| Layer height | 0.20 mm |
| First-layer height | 0.20 mm |
| Nominal material line width | 0.45 mm, matching the default reconstruction width |
| Wall generator | Arachne |
| Wall loops | 3, as used in the later batch audit |
| Infill | 100% of material regions; large cavities remain geometric voids |
| Top / bottom layers | 0 / 0 |
| Adaptive layers | Disabled |
| Orientation | Preserve the original Z direction; center and place on the bed by translation |

**Reconstruction height, slicing height and first-layer height must match.** To use 0.16 mm or 0.24 mm, reconstruct the source at that height instead of merely changing the slicer preset. Misalignment can make slicing planes encounter slab interfaces, producing periodic striping, abnormal sections or toolpath differences.

One wall loop may leave a central gap in wider regions formed by adjacent skin/rib strokes. The later batch audit used three loops and reduced this issue in Fuselage 2. These settings do not guarantee arbitrary models will print correctly. Avoid automatic rotation, scaling, adaptive layers and whole-stack automatic repair or boolean union.

### How it works

The engine samples the original mesh at each fixed-height layer midpoint, converts skin and rib intersection lines into buffered planar material regions, checks coverage, applies local recovery when necessary, and extrudes each region as a closed slab. The stacked slabs are exported as STL or geometry-only 3MF.

This is **direct reconstruction from mesh sections, not G-code inversion**. Geometry-only 3MF does not supply printer or filament presets. STL cannot carry the required slicing settings, so they must be maintained separately.

### Validation

| Scope | 0.2.4 release record |
|---|---|
| Automated tests | 88 passed |
| Original failing model | `Fuselage 3-p3.stl` |
| Parameters | 0.20 mm layer height, 0.45 mm material width |
| Section coverage | 740 layers; layer 641 passed after local recovery |
| Unaffected-section regression | 1,000 layers from `Fuselage 4-p3.stl` |
| Packaged GUI | Import, conversion, two saves, rereading and cache reuse |
| Actual slicing | 740 model layers generated for the failing model |
| Physical printing | Not tested |

A later independent audit used the same 0.2.4 reconstruction algorithm on **26 distinct ICON P3 Surface parts and 15,354 nonempty section layers**. Serialized STL material regions were reread and checked using true Even-Odd parity. All 26 generated the expected model layers in Bambu Studio, with no completely missing layers.

However, **some short isolated section segments in Fuselage 4 were still omitted by the slicer**. At layer 383, approximately 17.41 mm out of 762.47 mm of source section lines fell outside the approximated commanded bead footprint plus a 0.03 mm allowance. This remains an explicit local review item. No missing whole layers does not mean every segment is reproduced exactly. Third-party aircraft source models are not included in the software release.

### Known limitations

- Layer steps and contacting caps remain. A single globally manifold solid is not guaranteed.
- Z dimensions are quantized to full layers, with approximately half a layer of possible end deviation. Sub-layer details and horizontal zero-thickness faces are not guaranteed to survive.
- Thickening changes dimensions and clearances; sharp mitred corners can extend beyond the nominal half-width.
- Local coverage recovery addresses one class of section-buffer omissions, not every possible damaged mesh.
- Original 3MF filament, support, painting, multi-plate and proprietary settings are not guaranteed to survive import/export.
- On the validation machine, Bambu CLI could generate complete G-code and then return a nonzero exit code during project saving. Toolpath generation and project saving are recorded separately; overall CLI success was not claimed.
- Geometry validation, successful export, complete toolpaths and successful physical printing are separate acceptance stages.

### Source and CLI

Use the source snapshot matching this release. Windows 10 / 11 x64 is the target platform; Python 3.12 was used for development and packaging. Other environments require separate validation.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py

.\AeroSliceCLI.exe convert "input.stl" --reconstruction layered --mode even-odd --layer-height 0.20 --thickness 0.45 --format stl --output "output"
.\AeroSliceCLI.exe batch "models" --reconstruction layered --mode even-odd --layer-height 0.20 --thickness 0.45 --format stl --output "output"
.\.venv\Scripts\python.exe -m pytest -q
```

For source execution, replace `AeroSliceCLI.exe` with `.\.venv\Scripts\python.exe main.py`. CLI conversion commands still create run directories and JSON reports; the GUI no-sidecar policy does not apply to CLI conversion.

Dependencies include NumPy, SciPy, Trimesh, NetworkX, Shapely, Manifold3D, MeshLib, Rtree, PySide6 / Qt, PyQtGraph and PyOpenGL. See `requirements.txt` for versions. Installation needs network access; routine conversion requires no cloud service or AI API.

### Sponsorship and contributor rewards

A portion of the voluntary sponsorship funds actually received by the maintainer will be shared with this project's code contributors. Distribution will consider contribution quality, impact and ongoing maintenance, and will be discussed with the contributors concerned. No fixed amount, percentage or payment schedule is promised.

Sponsorship is entirely optional, does not affect free use of the software, and does not constitute a software purchase or grant resale rights.

### Licensing and third-party components

This snapshot is a personal / educational build and does not declare a single project-wide open-source license. Preserve third-party notices and license texts. Do not label the entire distribution as MIT, Apache-2.0 or unrestricted commercial software.

The bundled license for `meshlib-core==3.1.4.297` is titled **NON-COMMERCIAL & education LICENSE AGREEMENT** and includes restrictions on transfer to third parties. Public distribution of a package containing its runtime requires checking the applicable redistribution authorization; this README does not grant it. Publishing project source and redistributing third-party binaries require separate review.

Aircraft source models and converted models remain subject to their respective owners' rights. Publishing this software does not grant redistribution rights to those models.

---

## 中文

### 项目简介

AeroSlice Converter 是面向 3D 打印航模的离线 Windows 工具。它将原本依赖 Cura **Surface（表面）模式**的 STL / 3MF，重建为具有材料厚度的模型，供 Bambu Studio **Even-Odd（奇偶）模式**进一步切片。

软件按原模型的外皮和内部筋板截线建立材料区域，并保留几何空腔。导入模型后可直接点击 **一键转换并导出**；打印机与耗材设置在目标切片器中配置。

> 默认仍是逐层轮廓重建，连续曲面方式没有设为默认。逐层成品包含台阶和层间接触面，不是光滑连续曲面的无损转换。

### 0.2.4 更新内容

本版修复部分短折返截线触发的 **“逐层轮廓覆盖核对失败，已停止导出”**。

当截线合并及缓冲遗漏原始短线段时：

1. 定位未被材料区域覆盖的原始线段。
2. 使用相同材料宽度，仅为这些原始线段生成局部缓冲。
3. 将局部材料与已有区域求并集，保留已有材料。
4. 使用原来的 **0.008 mm** 覆盖容差重新检查整个截面；仍失败则停止导出。

正常截面继续使用原路径。报告记录补回层号、线段数量和新增材料面积；失败信息包含零件名、层号与 Z 坐标。此机制不依赖特定模型名称，也不通过放宽覆盖容差来绕过检查。

继承 0.2.3 及之前版本的工作流：

- **Surface 自动重建**与**保留实体（不重建）**的明确区分。
- 开放曲面误选保留实体时，恢复重建选项并提示原因。
- 已转换结果复用；转换参数变化时重新转换。
- GUI 默认 STL，直接输出到所选目录，无 JSON 旁文件或自动创建的 `run` 子目录。
- 同名文件自动编号，避免覆盖源文件和已有成品。
- STL / 几何 3MF 输出，以及独立命令行入口。

### 快速开始

1. 下载并解压对应版本的 Windows x64 程序包。
2. 保留完整目录，双击 `AeroSliceConverter.exe`；不要单独移走 EXE 或 `_internal`。
3. 导入原始 STL / 3MF，核对尺寸。STL 按毫米读取。
4. 保持 **Surface 自动重建**，确认重建层高与材料宽度。
5. 选择输出目录，点击 **一键转换并导出**。
6. 在 Bambu Studio 中导入成品，设置 Even-Odd，并逐层核对实际刀路。

若已点击“开始转换所选对象”完成转换，再点击导出会直接保存对应结果。仅更改目录、输出格式或分件选项可复用转换；更改模型、结构类型、转换勾选、层高、宽度或其他转换参数会重新转换。

### 切片设置：层高必须匹配

| 项目 | 0.20 mm 逐层成品的参考设置 |
|---|---|
| 切片模式 | Even-Odd / 奇偶 |
| 层高 | 0.20 mm |
| 首层高度 | 0.20 mm |
| 常规材料线宽 | 0.45 mm，与默认重建材料宽度对应 |
| 墙生成器 | Arachne |
| 墙层数 | 3，作为已完成批次审核的参考设置 |
| 填充 | 材料区域 100%；模型的大空腔由几何保留 |
| 顶层 / 底层 | 0 / 0 |
| 自适应层高 | 关闭 |
| 摆放 | 保持原 Z 方向，只做居中和落床平移 |

**重建层高、切片层高和首层高度应保持一致。** 按 0.20 mm 重建的 STL，不应直接改用 0.16 mm 或 0.24 mm 切片；需要按目标层高重新重建。层高或首层位置不匹配时，切片截面可能碰到层间交界，出现周期性条纹、异常截面或刀路差异。

一层墙未必能覆盖相邻外皮 / 筋线合并后的较宽区域。后续批次审核采用 3 层墙，改善了机身 2 的中间刀路间隙；这不是对任意模型的打印保证。不要对逐层成品启用自动旋转、缩放、自适应层高或整栈自动修复 / 布尔合并。

### 工作原理

```text
原始 STL / 3MF
      ↓
按原 Z 方向、固定层高取层中间截线
      ↓
外皮 / 筋板截线 → 指定宽度的二维材料区域
      ↓
覆盖核对 → 必要时局部补回 → 再核对
      ↓
逐层封闭挤出与叠放
      ↓
STL / 几何 3MF → Bambu Studio Even-Odd 切片
```

这是直接从模型截面重建，**没有通过 G-code 逆向生成 STL**。几何 3MF 不自动提供打印机或耗材预设；STL 无法携带这些切片约束，需要手动保持设置一致。

### 验证记录

| 范围 | 0.2.4 发布验证 |
|---|---|
| 自动化测试 | 88 项通过 |
| 原始问题模型 | `Fuselage 3-p3.stl` |
| 参数 | 0.20 mm 层高、0.45 mm 材料宽度 |
| 截面检查 | 740 层；第 641 层触发局部补回后通过覆盖检查 |
| 正常截面回归 | `Fuselage 4-p3.stl`，1,000 层检查 |
| 打包 GUI | 导入、转换、两次保存、回读及缓存复用验证 |
| 实际切片 | 问题模型生成 740 层模型刀路 |
| 实物打印 | 未验证 |

后续使用同一 0.2.4 重建算法，对 **26 个不同的 ICON P3 Surface 零件、15,354 个非空截面层**进行了独立批次审核，重新读取导出的 STL，并按真实奇偶规则检查材料区域。26 件均生成全部预期层的 Bambu 模型刀路，无整层遗漏。

该批次中，**机身 4 的部分短孤立截线仍未被切片器全部复现**。例如第 383 层约 762.47 mm 原始截线中，约 17.41 mm 未落入命令挤出带及 0.03 mm 余量内。这是明确的局部待复核项，不能把“无整层遗漏”理解成“每段刀路完全一致”。第三方航模源文件不包含在软件发布中。

### 已知限制

- 输出保留层状外观和相邻薄层的接触面，不保证整个堆栈是单一流形体。
- Z 尺寸量化到整层，端部偏差最多约半层；小于层高的细节和水平零厚度面不能保证保留。
- 加厚会改变外形和间隙，尖角斜接的偏移可能大于名义半宽，需要核对尺寸。
- 局部补回用于处理一类截线缓冲遗漏，不是任意破损模型的通用修复保证。
- 3MF 导入导出不承诺保留原工程的耗材、支撑、涂色、多盘和专有设置。
- 本机 Bambu CLI 曾在生成完整 G-code 后，于工程重存阶段返回非零退出码。刀路生成与工程重存分别记录，未将 CLI 整体判为通过。
- **几何检查通过、导出成功、切片刀路完整与实物打印成功，是不同的验证范围。**

### 源码运行与命令行

使用本版本对应的源码。目标平台为 Windows 10 / 11 x64，开发与打包环境使用 Python 3.12；其他环境兼容性需单独验证。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

```powershell
# STL conversion / STL 转换
.\AeroSliceCLI.exe convert "input.stl" --reconstruction layered --mode even-odd --layer-height 0.20 --thickness 0.45 --format stl --output "output"

# Batch conversion / 批量转换
.\AeroSliceCLI.exe batch "models" --reconstruction layered --mode even-odd --layer-height 0.20 --thickness 0.45 --format stl --output "output"

# Run tests from source / 源码测试
.\.venv\Scripts\python.exe -m pytest -q
```

源码命令行可将 `AeroSliceCLI.exe` 替换为 `.\.venv\Scripts\python.exe main.py`。命令行转换仍生成独立运行目录和 JSON 报告；桌面端“无 JSON 旁文件”的规则不适用于命令行转换。

主要依赖：NumPy、SciPy、Trimesh、NetworkX、Shapely、Manifold3D、MeshLib、Rtree、PySide6 / Qt、PyQtGraph 和 PyOpenGL。具体版本见 `requirements.txt`。首次安装需要联网，日常模型转换不依赖云服务或 AI API。

### 赞助与贡献者回馈

作者会将实际收到的自愿赞助中的一部分，用于回馈为本项目贡献代码的贡献者。具体分配将结合贡献质量、实际影响及持续维护投入，与相关贡献者沟通确定，不承诺固定金额、比例或发放时间。

赞助完全自愿，不影响软件的免费使用，也不构成软件购买或授予售卖权。

### 许可与第三方组件

当前快照是个人 / 教育用途构建，尚未声明覆盖整个项目的统一开源许可证。请保留第三方组件的许可证和声明，不要将整个分发包标注为 MIT、Apache-2.0 或“无限制商用”。

本构建所用 `meshlib-core==3.1.4.297` 的随包许可证标注为 **NON-COMMERCIAL & education LICENSE AGREEMENT**，并包含向第三方转移软件的限制。公开发布含其运行库的程序包，需要核对对应再分发授权；本 README 不提供该授权。上传项目源码与再分发第三方二进制应分别核查。

航模原始文件及其转换结果的权利归各自权利人；本软件的发布不授予这些模型的分发权。
