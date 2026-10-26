AeroSlice Converter 0.2.5 User Guide / 使用教程

[English](#english) · [中文](#中文)

## English

Updated: 2026-10-26
Scope: the validated Windows 0.2.5 continuous-reconstruction revision and the separately supplied Apple Silicon source/build-support package. Chinese button names are included below so that they can be matched to the application.

### 1. What this version does

AeroSlice Converter processes RC-aircraft STL / 3MF models originally intended for Cura Surface mode. It reconstructs skins and ribs as geometry that a target slicer can process, without overwriting the original files. Actual toolpath validation currently focuses on Bambu Studio; this does not certify every aircraft model, printer or slicer.

There are two main reconstruction methods:

| Item | Layered reconstruction: tied to slicing height | Continuous thin wall: heights chosen in the slicer |
|---|---|---|
| Default | Selected by default | Must be selected explicitly |
| Output geometry | Section curves are expanded into material regions, extruded as closed slabs and stacked | A continuous thin wall is reconstructed on both sides of the original surfaces |
| Slicing mode | Even-Odd | Regular / normal solid slicing |
| Layer height and first-layer height | Both must match the reconstruction height | Choose in the slicer for the printer and filament |
| Appearance | Steps, contacting slab faces and a layered texture | No print-layer stack, but still an approximate triangle mesh |
| Dimensional effect | Nominal XY expansion of about half the material width; Z quantized to full layers | Nominal exterior expansion of about half the material thickness, plus reconstruction error |

Manual structural conversion is an advanced method requiring correct identification of shells, reinforcement sheets and existing solids. It is not the starting workflow for a first-time user.

#### Independent layer heights do not mean fully independent extrusion widths

Continuous reconstruction still creates a solid with a geometric thickness, such as a 0.45 mm wall. You can set extrusion widths in the slicer, but the actual widths, wall counts and fill paths remain influenced by that geometry and the wall generator.

The goal of changing the extrusion width of every skin and rib merely by changing slicer settings, while using the same exported model without reconversion, **has not yet been implemented and validated**. Do not describe this version as fully decoupling extrusion width from geometric wall thickness.

### 2. Windows installation and launch

1. Download the latest replacement `AeroSliceConverter_0.2.5.zip` and extract the complete archive.
2. Keep `AeroSliceConverter.exe`, `AeroSliceCLI.exe` and `_internal` in their original relative locations. Do not copy only the EXE.
3. Double-click `AeroSliceConverter.exe`. The packaged application does not require a separate Python installation.
4. Earlier and replacement packages can both carry version 0.2.5. If the controls differ from this guide, check which package you extracted.

Desktop users normally launch the GUI EXE. `AeroSliceCLI.exe` is the command-line entry point and is not a second program that must be opened.

### 3. Current Apple Silicon Mac workflow

`AeroSliceConverter_0.2.5_AppleSilicon_Source.zip` contains source, a launcher and a native build workflow. It is **not a prebuilt Mac .app**. Native Mac execution and preview have not been verified. The Windows ZIP is not a Mac application.

The source-launch target is an M-series Mac, macOS 14 or newer, and native ARM64 / universal2 Python 3.12. Intel Python and Python running under Rosetta are outside this build target.

1. Install the macOS Python 3.12 distribution from python.org.
2. Extract the complete Apple Silicon source package into a writable folder.
3. Double-click `run_macos.command`, or open Terminal in that folder and run:

```bash
bash run_macos.command
```

4. The first launch downloads runtime dependencies into the local `.venv-macos-arm64` folder; later launches reuse it. It does not require sudo or change system Python.
5. Keep the Terminal error if launch or dependency installation fails. An installation failure is not evidence that the model conversion itself failed.

To create a standalone app that does not require end users to install Python, upload the complete source, including hidden `.github`, to GitHub. Open **Actions → Build macOS Apple Silicon test app → Run workflow**. Only a successful native build produces the `macOS_arm64.zip`; the workflow does not automatically publish a Release.

See `MAC_START_HERE.md` and `docs/macos_apple_silicon.md` in the source package. Even after a successful build, Finder launch, Cocoa/OpenGL preview, trackpad operation, clipboard and actual macOS slicing still need testing.

### 4. Prepare the input

1. Use the original Surface STL / 3MF. Do not reconstruct an already-generated layered result as though it were the original surface.
2. Check units and dimensions. STL does not declare units and is treated as millimetres; 3MF units are converted according to its metadata.
3. Test one part and inspect its toolpaths before processing the remaining parts in a batch.
4. Do not thicken an ordinary solid or an already-printable model merely to run it through this application.

The application reads 3MF geometry and instance positions. It does not promise to preserve a complete printer, filament, support, painting or multi-plate setup. Exported geometry 3MF is not a complete printing project either.

### 5. Common import-to-export workflow

1. Click **导入模型** (Import model) to select STL / 3MF, or **导入文件夹** (Import folder) to discover models recursively.
2. Wait for import to finish. Read dimensions, open-edge/nonmanifold-edge diagnostics and errors in the report. Red diagnostic markers alone do not prove that a Surface model cannot be reconstructed.
3. Check the structure type on the left. Use **Surface 自动重建** (Surface automatic reconstruction) in layered mode. In continuous mode, normally start with **自动判断** (Automatic) and keep **复杂曲面自动转为双侧薄壁** (Automatically reconstruct complex surfaces as two-sided thin walls) enabled.
4. Select a reconstruction method on the right and follow its instructions below.
5. Click **选择输出目录** (Choose output directory). STL is the default; switch to geometry 3MF if needed.
6. Click **一键转换并导出** (Convert and export). Wait for an explicit success or failure message. Progress at 100% alone does not prove export: import completion can also show 100%.
7. After success, click **打开输出文件夹** (Open output folder), confirm that the file exists, and then import it into the target slicer.
8. Open **查看 / 复制本次成品切片设置** (View/copy slicing settings for this result). You can copy the text or explicitly save a TXT card.

#### The two checkboxes on the left

- The conversion checkbox controls reconstruction participation. Clearing it attempts to preserve the object unchanged; it does not guarantee exclusion from the export. Preserving an open surface may be rejected by the valid-solid checks.
- The display checkbox controls preview visibility only. Hiding an object does not exclude it from conversion or export.
- To process only one file, the clearest workflow is **清空列表** (Clear list), followed by importing only that original file.
- **保留实体（不重建） / 保留闭合实体** (Preserve solid without reconstruction / Preserve closed solid) is for genuinely valid closed solids. It cannot bypass conversion of an open Surface input.

### 6. Method A: layered reconstruction

Use this method when you want the original layered approach, accept its geometry and can keep slicing conditions consistent. It remains the default.

1. Select **逐层重建（绑定切片层高）** (Layered reconstruction: tied to slicing height).
2. Select **Surface 自动重建** for the Surface objects.
3. Choose a reconstruction height, for example 0.20 mm, and a target wall thickness, for example 0.45 mm. Here the thickness controls the geometric width of the reconstructed material regions.
4. Keep Even-Odd mode in the converter and click Convert and export.
5. In Bambu Studio, use Even-Odd and preserve the original Z direction, scale and layer reference. Do not arbitrarily add a Z offset or place the part on a different face.
6. Set both normal layer height and first-layer height to the reconstruction height. A 0.20 mm reconstruction requires 0.20 mm layers and a 0.20 mm first layer.
7. Disable adaptive layers. Do not automatically repair, union the entire slab stack or thicken the result again.
8. Inspect the sliced skins, ribs, junctions and short strokes layer by layer.

The tested reference starting settings are Arachne, 3 wall loops, 100% material-region infill and 0 top/bottom layers. These are not a universal preset. Whether aircraft cavities remain empty must be checked in the exported geometry and actual preview; the number “100%” alone does not determine whether the aircraft interior becomes solid.

Stripes may be caused by the geometry's steps or worsened by slicing/reconstruction height mismatch. Matching heights improves sampling consistency; it does not turn existing steps into a continuous surface. End Z dimensions can be quantized by approximately half a layer. Details below the layer height and horizontal sheets are not guaranteed to survive.

### 7. Method B: continuous thin-wall reconstruction

Use this method when you want to avoid stacked print-layer geometry and choose printing heights in the slicer. Start again from the original Surface model.

1. Import the original model and select **连续薄壁（层高由切片器设置）** (Continuous thin wall: heights chosen in the slicer).
2. The application selects Regular mode and hides the reconstruction-height control.
3. Start with Automatic classification and leave automatic two-sided thin-wall reconstruction enabled. Do not label an open surface as an existing closed solid.
4. Set the target wall thickness, for example 0.45 mm, and surface-reconstruction accuracy, for example 0.10 mm. Both are geometry parameters.
5. Click Convert and export. Confirm that checks passed and a file was saved.
6. In Bambu Studio, use Regular / normal solid slicing. Choose layer height and first-layer height for your printer and filament; neither has to equal the 0.10 mm geometric-reconstruction accuracy.
7. Arachne is a starting point for inspecting thin walls. The reference validation used a P1S, 0.4 mm nozzle, 3 walls, 100% material-region infill and 0 top/bottom layers. Inspect your actual model's paths.

A smaller reconstruction-accuracy value usually requires more computation and memory; it does not guarantee success. The allowed range is currently 0.04–0.20 mm, with additional working-grid and face-count limits.

This method thickens both sides of the source surfaces. A 0.45 mm thickness implies a nominal exterior expansion of about 0.225 mm, with possible additional reconstruction error. Check mating faces, pin holes, mounting slots, thin trailing edges and clearances separately. This is not lossless CAD repair or smoothing an existing layered STL.

Continuous mode may also preserve an already-closed input mesh as an existing solid. If a region that should be hollow becomes solid, do not assume Automatic classification understood the design intent of a closed Surface model. Stop using that result and report it.

### 8. Parameters that are easy to confuse

| Parameter | Where it is set | Effect on the current result |
|---|---|---|
| Reconstruction layer height | Converter, layered mode | Defines the slab stack; slicing height and first-layer height must match |
| Target wall thickness | Converter | Defines material-region width or solid thickness, not merely a printing-width switch |
| Surface-reconstruction accuracy | Converter, continuous mode | Controls geometric approximation and computation, not print-layer height |
| Layer height and first-layer height | Slicer | Freely chosen for continuous geometry within printing constraints; constrained by reconstruction for layered geometry |
| Extrusion line width | Slicer | Influences deposition and paths, but remains affected by geometry, wall generation and feature thresholds |

For example, 0.45 mm geometric thickness, 0.10 mm reconstruction accuracy and 0.20 mm print-layer height can coexist. They describe different properties. Setting a slicer line width of 0.60 mm does not prove that every part of the model prints as a single 0.60 mm bead: inspect actual paths or G-code.

### 9. Conversion reuse, output and batch processing

- You can use Convert and export directly; **开始转换所选对象** (Convert selected objects) is not a required preliminary step.
- If you convert first and export later, the existing result is reused when the input, conversion checkboxes, roles and conversion parameters match.
- Changing input or conversion parameters triggers reconversion on the next export. Changing only the output directory, format or separate-parts option can reuse a matching result.
- The settings card comes from the completed result. Editing controls later does not change an old result or its card into a result with the new parameters.
- Desktop export writes model files directly to the selected directory, without automatic JSON / TXT sidecars or a single-export `run` subfolder. TXT is written only when you explicitly save a settings card.
- Existing model files and originals are not overwritten; conflicting output names receive another number.
- **分别导出转换后的独立零件** (Export converted parts separately) controls output separation. It does not automatically redesign parts or joints.
- **批量转换列表中的源文件** (Batch-convert source files in the list) processes imported source files individually with automatic diagnosis. It does not blindly inherit each object's manually assigned role. Use the single-file workflow when manual roles are needed.
- CLI operations and explicit slicer validation generate their own reports, logs or working directories. The desktop model-only export rule does not apply to those operations.

Folder import ignores model resource forks starting with `._` or inside `__MACOSX`, and deduplicates paths. Individual failures are reported while the remaining files continue importing.

### 10. Inspect the result

1. Dimensions: check the exterior, Z height, holes, slots, mating faces and clearances, particularly continuous-mode expansion.
2. Structure: confirm that skins, ribs, openings and original cavities still match the design intent.
3. Toolpaths: inspect the first layer, middle, junctions, top, thin trailing edges and short ribs for breaks, omissions or unexpected solid fill.
4. Heights: match them strictly for layered results. For continuous geometry, choose them for the process and reslice to inspect the outcome.
5. Files: distinguish original inputs, layered results and continuous results. STL does not carry reliable reconstruction-method or parameter metadata. Record these in filenames, folders or a manually saved settings card.

`geometry_passed` only means that the implemented geometry checks passed. It does not certify complete slicer paths, physical printing, layer bonding, structural strength or flight readiness.

The application also provides slicer configuration/validation, text G-code inspection and Cura-versus-target G-code comparison. Automatic slicing requires an actual slicer executable and complete configurations. Selecting an .app / EXE does not supply the printer, process and filament profiles. Inspect manually in the slicer when CLI capability cannot be confirmed.

### 11. Current validation scope and known limitations

The original Fuselage 3-p3 continuous example used 0.45 mm thickness and 0.10 mm geometric accuracy, producing 1,039,870 faces. The original file remained unchanged. Actual import, continuous conversion and two cached exports were verified in the final Windows EXE.

The same continuous STL was tested with a particular Bambu P1S process:

| Layer height / first-layer height | Model G-code layers | Wholly missing layers | Sampled source-curve toolpath coverage |
|---|---|---|---|
| 0.20 / 0.24 mm | 742 | None | Approximately 99.9917% |
| 0.16 / 0.20 mm | 927 | None | Approximately 99.9903% |

These percentages approximate commanded toolpaths, not physical deposition. Local fill gaps remain. After generating complete G-code, both CLI runs returned -13 while saving project 3MF. Record “G-code generated” and “project saving failed” separately. This does not establish that geometry-3MF export from the converter itself must fail.

The Windows continuous-revision test record contains 96 source tests. Later Apple Silicon support has 113 source tests passing on a Windows host; those are not 113 Mac runtime tests. Native Mac building, preview and actual slicing remain unverified.

The earlier audit of 26 distinct ICON P3 Surface models covers the layered method under specific conditions. It does not certify continuous reconstruction or all models. Local short strokes on Fuselage 4-p3 still require review. Complete PrusaSlicer / OrcaSlicer workflows have not been independently accepted in this project, and physical printing is unverified.

### 12. Troubleshooting

| Symptom | What to check |
|---|---|
| Export appears to do nothing | Read the top message and first report error. Confirm that a model is imported, conversion is checked, an output directory exists in the controls and no other job is running |
| Progress stays at a percentage | Read the current stage and elapsed time. A single percentage is not proof of a hang. Record the model, parameters and last message; cancel and report if necessary |
| Layered STL looks like separate lines | This is characteristic of its geometry. For a continuous exterior, import the original model again and choose continuous thin wall |
| Stripes or missing layers after changing height | For layered geometry, check reconstruction, normal and first-layer heights, orientation and Z reference. For continuous geometry, inspect actual thin-wall paths |
| Cannot preserve as a valid closed solid | Do not assign Preserve solid to an open Surface. Restore Surface automatic reconstruction in layered mode, and check objects being preserved because conversion was unchecked |
| Input is already a layered result | Use it directly in the target slicer. To change reconstruction method or height, import the original again |
| ModuleNotFoundError or missing runtime | On Windows, use the complete latest extracted package. Source users should follow the matching dependency setup. Keep the full error rather than changing only model parameters |
| Geometry passes but ribs are missing in slicing | Inspect actual paths and retain layer numbers, screenshots and settings. Small features, local fill and wall-generation rules can still omit material |
| Need complete global thin-wall control using only slicer width | This feature is not completed. The geometry-thickness control cannot simply be treated as an optional printing-width setting |
| No .app in the Mac download | The current delivery is source/build support. Complete a native Mac build, or use the source launcher |

For a useful issue report include the application version and package source, OS/CPU architecture, original-versus-converted input, reconstruction method, thickness/accuracy, slicer version, normal/first-layer heights, widths, wall generator, infill, first error, affected layer and toolpath screenshot. Share only a minimal example you have permission to distribute; do not publicly upload restricted aircraft files.

### 13. Licensing and distribution

The project's formal license and contributor commercial-authorization arrangements remain pending. The current MeshLib dependency has non-commercial and third-party-transfer restrictions. Successful running or building does not grant unrestricted distribution rights; consult the supplied `THIRD_PARTY_NOTICES.md` before publishing. Sponsorship is voluntary support, not a software purchase or automatic grant of resale rights.

---

## 中文

更新日期：2026-10-26
适用范围：当前已验证的 Windows 0.2.5 连续薄壁修订版，以及另行提供的 Apple Silicon 源码与构建支持包。

### 一、先了解当前版本能做什么

AeroSlice Converter 用于处理原本依赖 Cura Surface 表面模式的航模 STL / 3MF，将外皮与筋板转换为供目标切片器处理的几何。原始文件不会被覆盖。当前实际刀路验证以拓竹 Bambu Studio 为主，不能据此保证所有航模、机型或切片器均兼容。

当前有两种主要方式：

| 项目 | 逐层重建（绑定切片层高） | 连续薄壁（层高由切片器设置） |
|---|---|---|
| 默认状态 | 默认选中 | 需要手动选择 |
| 成品形态 | 每层截线扩成材料区域，再封闭挤出并叠加 | 沿原始曲面双侧建立连续薄壁 |
| 切片模式 | Even-Odd / 奇偶 | Regular / 普通实体切片 |
| 打印层高与首层高度 | 都须匹配重建层高 | 在切片器中按机型、耗材选择 |
| 外观 | 有阶梯、层间接触面及层状纹理 | 不按打印层叠加，但仍是近似三角网格 |
| 尺寸影响 | XY 外扩约半个材料宽度；Z 量化到整层 | 外轮廓约增加半个材料厚度，受重建误差影响 |

手动结构转换属于高级功能，要求准确区分外壳、加强片与已有实体；首次使用不建议从这个方式开始。

#### 特别说明：打印层高自由，不等于打印线宽完全自由

当前连续薄壁仍会建立有几何厚度的实体，例如 0.45 mm 薄壁。切片器中的打印线宽仍可设置，但实际刀路宽度、墙数与填充会受到模型壁厚和墙生成器影响。

“同一个成品不重新转换，只修改切片器线宽，就让全部外皮与筋板的实际挤出宽度随之变化”是后续优化目标，当前尚未实现并验证。不要把本版描述为已经完全解除线宽与几何壁厚的关联。

### 二、Windows 安装与启动

1. 下载最新替换后的 AeroSliceConverter_0.2.5.zip，并完整解压。
2. 保留 AeroSliceConverter.exe、AeroSliceCLI.exe 及 _internal 文件夹的相对位置，不要只复制一个 EXE。
3. 双击 AeroSliceConverter.exe 启动。打包版不要求另装 Python。
4. 同为 0.2.5 的早期包与后续替换包内容不同。如果选项与本教程不一致，先核对是否使用了最新替换包。

普通用户使用桌面 EXE；AeroSliceCLI.exe 是命令行入口，不是必须操作的第二个程序。

### 三、M 系列 Mac 的当前使用方式

目前提供的是 AeroSliceConverter_0.2.5_AppleSilicon_Source.zip，包含源码、启动脚本与原生构建流程。它不是已经生成的 Mac .app，尚未完成 Mac 原生运行和预览验证。Windows ZIP 不能作为 Mac 应用运行。

源码启动目标：M 系列芯片、macOS 14 或更新版本、原生 ARM64 / universal2 Python 3.12。Intel Python 或 Rosetta Python 不属于此构建目标。

1. 安装 python.org 提供的 macOS Python 3.12。
2. 完整解压 Apple Silicon 源码包到可写目录。
3. 双击 run_macos.command；也可以在终端进入源码目录后执行：

```bash
bash run_macos.command
```

4. 首次启动会联网安装运行依赖到同目录 .venv-macos-arm64，以后复用。无需 sudo，不修改系统 Python。
5. 启动或依赖安装失败时保留终端错误；这不等于模型转换失败。

开发者需要无需 Python 的 Mac 成品时，将完整源码（包括隐藏的 .github 文件夹）更新到 GitHub，进入 Actions → Build macOS Apple Silicon test app → Run workflow。只有原生构建成功后才会生成 macOS_arm64.zip；流程不会自动发布 Release。

Mac 源码包中的 MAC_START_HERE.md 和 docs/macos_apple_silicon.md 提供详细说明。构建成功也仍需检查 Finder 启动、Cocoa/OpenGL 预览、触控板、剪贴板及实际 macOS 切片。

### 四、导入前准备

1. 使用原始 Surface STL / 3MF；不要把已经生成的逐层成品当作原始曲面再次重建。
2. 确认模型单位和尺寸。STL 没有单位声明，本程序按毫米处理；3MF 按单位信息换算。
3. 先选一个零件测试并核对刀路，再批量处理其他零件。
4. 普通实体或已能正常切片的模型，不应仅为了使用软件而盲目加厚。

程序读取 3MF 的几何与实例位置，不承诺保留其完整打印机、耗材、支撑、涂色、多盘等工程设置。转换后的几何 3MF 也不等于完整打印工程。

### 五、共同操作流程

1. 点击“导入模型”选择 STL / 3MF，或点击“导入文件夹”递归读取模型。
2. 等待导入结束，查看底部报告中的尺寸、开放边、非流形边和错误。红色标记是诊断提示，不直接等于该 Surface 模型不能重建。
3. 在左侧确认结构类型。逐层模式使用“Surface 自动重建”；连续模式通常从“自动判断”开始，并保留“复杂曲面自动转为双侧薄壁”。
4. 在右侧选择重建方式，按下面对应章节设置。
5. 点击“选择输出目录”，确认输出位置。默认输出格式为 STL；需要几何 3MF 时可切换。
6. 点击“一键转换并导出”，等待明确的成功或失败提示。只看到进度 100% 不足以确认已导出；导入完成同样可能显示 100%。
7. 成功后点击“打开输出文件夹”，核对文件确实存在，再导入目标切片器。
8. 打开“查看 / 复制本次成品切片设置”，读取与该成品对应的提示。可复制文字，或主动另存 TXT。

#### 左侧两个勾选框的含义

- “转换”勾选决定是否参与重建；取消后会尝试原样保留对象，不保证对象从导出结果中消失。开放曲面原样保留可能被有效实体检查阻止。
- “显示”勾选只控制预览可见性，不等于取消转换或导出。
- 只想处理单个文件时，最清楚的做法是“清空列表”，只导入该原始文件。
- “保留实体（不重建）/ 保留闭合实体”仅用于确实有效的闭合实体，不能用来绕过开放 Surface 的转换。

### 六、方案 A：逐层重建

适合继续使用原方案、接受层状几何，并能保持切片条件一致的情况。此方式仍是默认选项。

1. 选择“逐层重建（绑定切片层高）”。
2. 左侧 Surface 对象选择“Surface 自动重建”。
3. 确定重建层高，例如 0.20 mm；确定目标壁厚，例如 0.45 mm。后者实际是重建材料区域的几何宽度。
4. 软件模式保持 Even-Odd，点击“一键转换并导出”。
5. 在拓竹中使用 Even-Odd / 奇偶切片，保持原 Z 方向、比例与层高基准；不要任意增加 Z 偏移或改为其他放置面。
6. 将普通层高和首层高度都设为重建层高。例如 0.20 mm 重建，对应 0.20 mm 普通层高、0.20 mm 首层。
7. 关闭自适应层高。不要对整个薄层堆叠自动修复、布尔合并或再次加厚。
8. 切片后逐层检查外皮、筋板、接合处和短线。

已测参考设置为：Arachne、3 层墙、材料区域 100% 填充、顶层 0、底层 0。这是指定航模与工艺的参考起点，不是所有模型的通用预设。机翼空腔是否保留，要看导出几何及实际预览；不能只凭“100%”判断飞机会被填实。

条纹可能来自成品本身的阶梯，也可能因切片采样与重建层不匹配而加重。匹配层高能改善刀路一致性，不能把已经存在的阶梯变成连续曲面。端部 Z 尺寸量化最多约半层，小于层高的细节和水平薄片不保证保留。

### 七、方案 B：连续薄壁

适合希望摆脱逐层堆叠外观、在切片器中选择打印层高的情况。仍须从原始 Surface 重建。

1. 导入原始模型，选择“连续薄壁（层高由切片器设置）”。
2. 软件自动切换到 Regular，并隐藏重建层高输入。
3. 从“自动判断”开始，保持“复杂曲面自动转为双侧薄壁”开启。不要把开放曲面标记为已有闭合实体。
4. 设置目标壁厚，例如 0.45 mm；设置曲面重建精度，例如 0.10 mm。这两个数值均是几何参数。
5. 点击“一键转换并导出”，确认检查通过、文件已保存。
6. 在拓竹使用 Regular / 普通实体切片；按打印机与耗材设置层高和首层高度，不需要与重建精度 0.10 mm 相等。
7. 对薄壁可从 Arachne 开始检查。参考验证使用 P1S、0.4 mm 喷嘴、3 墙、100% 材料区域填充、顶底 0 层，仍须检查实际模型刀路。

“曲面重建精度”数值越小，通常需要更多计算和内存；并非越小就一定成功。当前允许 0.04–0.20 mm，复杂模型还受计算预算和面数限制。

连续薄壁沿源面双侧加厚：0.45 mm 厚度意味着名义外扩约 0.225 mm，并可能叠加重建误差。必须另核对拼接面、销孔、安装槽、薄尾缘和相邻间隙。它不是无损 CAD 修复，也不是把旧的逐层 STL 磨平。

当前连续模式还可能将本来就封闭的网格作为已有实体保留。若预览出现原本不应存在的实心区域，不要假定“自动判断”一定理解了该封闭 Surface 的设计意图；应停止使用该结果并反馈。

### 八、几个容易混淆的参数

| 参数 | 在哪里设置 | 对当前成品的作用 |
|---|---|---|
| 重建层高 | 转换器的逐层模式 | 决定薄层堆叠；后续打印层高、首层须匹配 |
| 目标壁厚 | 转换器 | 决定重建材料宽度或实体厚度，不是纯粹的打印线宽开关 |
| 曲面重建精度 | 转换器的连续模式 | 决定几何近似与计算量，不是打印层高 |
| 打印层高、首层高度 | 切片器 | 连续成品可按工艺选择；逐层成品受重建约束 |
| 打印线宽 | 切片器 | 影响实际挤出与刀路，但仍受几何厚度、墙生成器和特征阈值影响 |

例：0.45 mm 几何壁厚、0.10 mm 重建精度、0.20 mm 打印层高可以同时存在，三个数值不表示同一件事。把切片器线宽改成 0.60 mm，并不证明该模型所有位置都已用 0.60 mm 单道打印，必须看实际刀路或 G-code。

### 九、转换缓存、输出与批量处理

- 可以直接“一键转换并导出”，无需先点“开始转换所选对象”。
- 先转换，再导出：输入、转换勾选、结构类型与转换参数一致时，导出复用已有结果。
- 修改输入或转换参数后，下一次导出会重新转换。只修改输出目录、格式或分件选项，可复用匹配结果。
- 设置卡取自已完成的转换结果。即使界面参数后来已修改，旧成品和旧设置卡也不会自动变成新参数版本。
- 桌面导出直接写入所选目录，不自动附带 JSON / TXT，也不为单次导出创建 run 子目录。主动另存设置卡才会写 TXT。
- 同名输出会另行编号，不覆盖已有模型或原始文件。
- 勾选“分别导出转换后的独立零件”控制输出分件，不会自动重新设计零件或拼接结构。
- “批量转换列表中的源文件”按已导入的源文件逐个处理，使用自动诊断，不直接继承每个零件的手工角色。需要手工指定结构时，使用单文件流程。
- 命令行与主动切片验证会生成其自身的日志、报告或工作目录，不适用“桌面模型导出只写模型”的描述。

文件夹导入会忽略 ._ 开头或 __MACOSX 中的辅助模型文件，并去重路径；损坏文件的失败信息保留，其余文件继续导入。

### 十、怎样检查成品

1. 尺寸：核对外形、Z 高度、孔槽、拼接面及间隙，尤其注意连续模式的外扩。
2. 结构：确认外皮、加强筋、开口和原有空腔仍符合设计意图。
3. 刀路：查看首层、中段、接合处、顶部、薄尾缘和短筋板，检查断线、漏线及意外填实。
4. 层高：逐层成品严格匹配；连续成品按工艺选择，并实际重新切片检查。
5. 文件：分清原始模型、逐层成品与连续成品；STL 不携带可靠的重建方式或参数声明，建议在文件名、文件夹或手动设置卡中记录。

“geometry_passed”只表示当前几何检查通过，不等于所有切片路径完整，更不等于实物打印、层间强度或飞行验证通过。

软件提供“配置切片器并验证已导出模型”“导入文本 G-code 检查路径”“比较 Cura 与目标 G-code”等工具。自动切片需要实际切片器程序与完整配置；选择一个 .app / EXE 不会自动替你补齐机器、工艺与耗材。无法确认 CLI 能力时，使用切片器手工检查。

### 十一、当前验证范围与已知限制

Fuselage 3-p3 原始模型的连续薄壁实例：0.45 mm 厚度、0.10 mm 几何精度，输出 1,039,870 面。原始文件保持不变，最终 Windows EXE 的导入、连续转换、两次缓存导出已验证。

同一个连续 STL 在指定拓竹 P1S 工艺中做过以下检查：

| 打印层高 / 首层高度 | G-code 模型层数 | 整层缺失 | 原始截线刀路覆盖抽样 |
|---|---|---|---|
| 0.20 / 0.24 mm | 742 | 无 | 约 99.9917% |
| 0.16 / 0.20 mm | 927 | 无 | 约 99.9903% |

覆盖率为指令刀路近似，不是实物结果；仍有局部填充间隙。两次完整 G-code 生成后，CLI 保存工程 3MF 仍返回 -13，应分别记录“G-code 已生成”与“工程保存失败”。这不等于转换器自身的几何 3MF 导出必然失败。

Windows 连续修订成品的源码测试记录为 96 项；后续 Mac 支持源码在 Windows 主机上的测试为 113 项。后者不是 113 项 Mac 实测。Mac 原生构建、预览和实际切片尚未验证。

此前 ICON P3 的 26 个独立 Surface 模型审核属于指定条件下的逐层方案记录；不能推广为本版连续方式或所有模型都通过。Fuselage 4-p3 仍有局部短线需复核。PrusaSlicer / OrcaSlicer 的完整流程未在本项目中独立验收，实物打印未验证。

### 十二、常见问题

| 现象 | 处理方法 |
|---|---|
| 点击导出似乎没反应 | 查看顶部提示和底部首条错误；确认已导入模型、有转换勾选、有输出目录，且没有其他任务正在运行 |
| 进度停留在某个百分比 | 先读当前阶段与耗时；单个百分比不能证明程序卡死。记录模型、参数与最后提示，必要时取消并反馈 |
| 逐层 STL 看起来一条一条 | 这是逐层几何的特征；需要连续外形时，重新导入原始模型并选择连续薄壁 |
| 改层高后出现条纹或缺层 | 逐层方式先核对重建层高、普通层高、首层高度、方向与 Z 基准；连续方式检查实际薄壁刀路 |
| 报错“无法作为有效封闭实体原样保留” | 原始开放 Surface 不应选“保留实体”；逐层模式改回“Surface 自动重建”，也检查取消转换后原样保留的对象 |
| 提示已是逐层成品 | 直接在目标切片器使用该成品；要更换重建方式或层高，请重新导入原始模型 |
| ModuleNotFoundError 或缺少运行库 | Windows 使用完整最新版解压包；源码用户使用对应依赖安装流程。保留完整错误，不只修改模型参数 |
| 显示几何通过，但筋板漏切 | 查看实际刀路，保留层号、截图与设置。小特征、局部填充及墙生成规则仍可能造成遗漏 |
| 想仅改切片线宽而完全控制所有薄壁 | 当前尚未完成这项功能，不能把几何壁厚输入框当成可省略的打印线宽设置 |
| Mac 没找到 .app | 当前交付是源码与构建支持包；必须先完成原生 Mac 构建，或按源码方式启动 |

反馈问题请附：软件版本及包来源、系统与 CPU 架构、原始还是已转换模型、重建方式、壁厚与精度、切片器版本、打印层高与首层高度、线宽、墙生成器、填充设置、首条错误、问题层号与刀路截图。仅提供你有权分享的最小复现，不公开上传受限航模。

### 十三、许可与分发

项目正式许可及贡献者商业授权安排仍待确定；当前 MeshLib 依赖存在非商业与第三方转移限制。能运行或能构建不等于已获得任意分发授权，发布前应核对随包 THIRD_PARTY_NOTICES.md。赞助为自愿支持，不应当作软件购买或自动取得售卖权。
