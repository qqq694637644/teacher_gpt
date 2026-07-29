# DIP4E 全书 Locator 构建流程与实施经验

本文记录 Version 3 如何从固定 PDF 生成整本书标题树、逐页查询计划和核验证据，以及实现过程中得到的可复用经验。

它不是运行时 API 说明，也不是让大模型自由生成目录的提示词。权威数据必须来自可重复执行的脚本、严格 schema 和源 PDF 校验；人工只审核少量异常，真实 GPT 文件检索另行验收。

## 1. 目标与边界

构建产物需要回答一个问题：

> 给定教材印刷章节或项目学习单元 ID，应该检索哪些物理页、使用哪些查询、看到哪些证据后才能确认页面正确，以及首页和末页应截取到哪里。

运行时 Locator 只包含定位信息，不复制教材正文，也不在运行时重新解析 PDF。

构建流程必须保证：

- 教材印刷编号原样保留；
- 项目学习单元编号只由标题树顺序生成；
- 每个正文页都有明确覆盖方式；
- 每个章节范围中的物理页都有 retrieval step；
- 查询和证据锚点确实存在于指定源 PDF 页面；
- 本地源 PDF 校验与真实 GPT 文件检索验收明确分开；
- 任一必需条件不满足时构建失败，而不是静默补默认值。

## 2. 固定唯一事实源

第一步不是提取标题，而是锁定 PDF 身份：

```text
SHA-256: 7b2b48ed87b454970d0916e1dbd7a5160e33d28db0dcdeba647b61eb5d3b850b
physical pages: 1022
```

同时读取每一页的三套标识：

```text
pdf_page_index
pdf_page_number
printed_page_label
```

三者不能互相推算替代。封面、IFC、正文页和封底使用不同页面标签规则；任何代码或数据若只保存一个“page”字段，都不足以支持可靠核验。

源文件发生任何变化时，即使文件名相同，也必须重新提取、生成、审核和编译。

## 3. 提取行级版面事实

PDF 解析保留行级结构，而不是只保存连续纯文本。每行至少记录：

- 文字；
- 字体名称；
- 字号；
- 样式和颜色；
- bbox 坐标；
- 页面内顺序；
- 所属物理页和印刷页标签。

这样才能区分外观相似但语义不同的内容。

本书中的典型差异包括：

- 普通正式小标题约为 `10.95pt Futura-Heavy`；
- 图内 `B1 AND B2`、`B1 XOR B2` 等标签约为 `7pt TimesTen`；
- 章号约为 `127.17pt Futura-Condensed`；
- 章名约为 `24pt Palatino-MediumItalic`。

经验结论：**不能用“是否全大写”单独判断标题**。字体、字号、颜色、位置和文本特征必须共同满足。

## 4. 生成完整标题候选集

最初只识别普通小标题样式时得到 434 个候选。随后发现章首页使用完全不同的字体体系，补充 12 个章标题后，最终候选集为：

```text
446 layout heading candidates
= 12 chapter headings
+ 102 numbered section headings
+ 332 unnumbered candidates
```

其中两个候选是正文开始前的作者姓名，不属于任何印刷章节，因此明确排除。最终进入 catalog 的标题为：

```text
444 headings
= 114 printed nodes
+ 330 learning units
```

候选排除必须是显式、可审计的规则。不得因为某个候选难以归类就直接丢弃。

## 5. 建立教材印刷章节树

带教材编号的标题解析为 `printed_section_id`，例如：

```text
2
2.6
3.4
```

印刷编号原样保留，不重新编号。父子关系由编号前缀建立，并验证父节点真实存在。

每个印刷节点同时保存源标题位置：

- 标题原文；
- PDF page index；
- printed page label；
- bbox；
- numbered 状态。

编译阶段会把这些字段重新与源 PDF 候选逐项比较，避免 Manifest 中出现手工改写但源 PDF 不存在的标题。

## 6. 把未编号标题构造成学习单元树

未编号标题先按页面和 bbox 顺序归属到当前印刷父节，再根据版面层级构造有序树。

以 `2.6` 为例，顶层兄弟顺序为：

```text
Elementwise versus Matrix Operations
Linear versus Nonlinear Operations
Arithmetic Operations
Set and Logical Operations
Spatial Operations
Vector and Matrix Operations
Image Transforms
Image Intensities as Random Variables
```

Manifest 只保存顺序和树深度，不保存项目 `section_id`。编译器根据兄弟序号生成：

```text
2.6.1 ... 2.6.8
```

子标题递归追加序号：

```text
2.6.5 Spatial Operations
├── 2.6.5.1 Single-Pixel Operations
├── 2.6.5.2 Neighborhood Operations
├── 2.6.5.3 Geometric Transformations
└── 2.6.5.4 Image Registration
```

必须验证：

- 同级标题具有相同 `source_level`；
- 子节点恰好比父节点深一级；
- 兄弟顺序与 PDF 页面/bbox 顺序一致；
- 子节点不会占用下一同级编号；
- 生成 ID 不与教材印刷 ID 冲突；
- 每个有效候选恰好进入树一次。

## 7. 计算章节边界和内容窗口

一个节点的开始位置是其标题 bbox。结束位置是后续第一个同级或更高层级标题。正文最后一个叶子节点还必须在 `Summary`、`Problems` 或下一章标题之前停止，不能把章末总结和习题页吸收到最后一个学习单元。

跨页边界不能简单使用“下一个标题页减一”。如果下一个标题位于新页面，还要检查该标题上方是否存在上一节正文：

- 标题上方有正文：该页仍是上一节结束页；
- 标题上方没有正文：上一节在前一页结束。

首页和末页通常只覆盖页面的一部分，因此每个 page step 保存：

```text
content_window.start_at
content_window.end_before
```

内容切割使用“物理页 + 行位置/bbox”，不能使用字符串第一次出现的位置。相同词语可能同时出现在页眉、正文、图注或交叉引用中。

## 8. 页面分类与完整覆盖

1022 个物理页先分类为：

- `front_matter`；
- `body`；
- `back_matter`。

正文页还需要明确由以下至少一种方式覆盖：

- 学习单元；
- 叶子印刷章节；
- 明确的 parent-only 内容。

特殊页面不能伪造普通正文证据，应显式处理，例如：

- 纯图或图占主导页面；
- 故意留白页；
- 只有父章节内容、没有学习标题的页面；
- 必须依赖页面视觉确认的边界页。

构建器和编译器都不允许未覆盖正文页。

## 9. 逐页提取覆盖锚点

每个章节范围中的每个物理页都生成独立 retrieval step。锚点只从该章节在该页的 `content_window` 内提取，而不是从整页盲目归属。

可提取的锚点包括：

- heading；
- visible text；
- Figure ID；
- Equation ID；
- Example ID；
- Table ID。
- Exercise ID（仅用于课后题的页内起止边界和核验）。

这条规则解决了多个实际错误：

- 公式不能因为和下一个标题在同页就归给下一个学习单元；
- 图不能只根据图注所在页面归属，而应结合正文中的显式引用；
- 页眉、低字号图注和图内标签不能进入正文锚点；
- 同一页中的相邻章节必须使用内容窗口分离。

## 10. 生成逐页查询

每页至少生成两条查询：

1. 精确查询：组合标题或页面正文锚点与印刷页检索词；
2. 回退查询：组合章节标题、可见页面锚点和印刷页描述。

查询锚点优先选择：

- 当前页边界标题；
- 页面中较唯一的正文短句；
- Figure、Example、Equation、Table 标识；
- 章节上下文。

应避免使用：

- 单独页码；
- 单独章节标题；
- 页眉；
- 图内短标签；
- 在多页重复出现的短图注；
- 源 PDF 中不可见却被当作视觉证据的内部检索字符串。

`+()` 不是严格布尔 AND，第一搜索候选也不保证正确。因此查询只是召回策略，最终仍必须检查 `required_evidence`。

运行时按顺序逐条执行 query；每次 `file_search.msearch` 只发送一条 query，
不把一个 step 的完整查询数组放进单次调用。这样既不受单次查询数量上限影响，
也能在某条查询已满足全部 evidence 时停止后续回退查询。

原始 PDF 文本不能直接嵌套进 `+(...)`。构建器先把 evidence anchor 规范化为
字母、数字、句点和连字符 token，移除源文本中的圆括号及其他结构标点，再由
typed evidence 重新生成 query。Exercise Locator 加载时会拒绝任何括号不平衡
的 query，并要求每个非页码 evidence 至少有一个匹配的安全 query anchor。

## 11. 生成并验证核验证据

每个 page step 保存类型化证据，例如：

```text
printed_page_equals
contains_heading
contains_text
contains_figure
contains_equation
contains_example
contains_table
```

证据还包含 `verification_mode`：

- `visual_required`：必须依赖页面视觉确认，例如印刷页号和内容窗口边界；
- `text_or_visual`：可由可靠文本块或视觉确认。

生成后必须重新回查源 PDF：

- 锚点是否存在于目标物理页；
- 锚点是否位于当前内容窗口内；
- Figure、Equation、Example、Table ID 是否在正确页面；
- 查询是否至少含有一个真实源 PDF 锚点；
- 边界标题是否使用视觉核验模式。

错误页、边界外锚点或不存在的锚点都会阻止 compiled index 输出。

## 12. 编译、分片与运行时加载

Manifest 是构建期权威数据。编译器负责：

- 生成项目学习单元 ID；
- 计算运行时层级和父子关系；
- 验证页面范围、步骤连续性和边界；
- 验证全书正文页覆盖；
- 生成 `CompiledLocatorIndex`。

完整 Manifest 和 compiled index 单文件超过 GitHub Gateway 限制，因此当前实现按章分为 12 个 shard：

```text
manifest.yaml
manifest.sections.01.yaml ... manifest.sections.12.yaml
compiled_locator_index.json
compiled_locator_index.sections.01.json ... compiled_locator_index.sections.12.json
validation_report.json
```

入口文件只保存包元数据和 shard 清单。构建器与运行时都会拒绝：

- 缺失 shard；
- 重复 shard；
- 未声明的额外 shard；
- 跨章数据；
- schema 错误；
- hash 或版本不一致。

分片是传输和审计方式，不改变逻辑上的完整索引。

## 13. 验证层次

构建完成后至少执行四层验证。

### 13.1 静态和 schema 验证

```text
ruff
format check
compileall
Pydantic strict validation
PROMPT contract validation
```

### 13.2 源 PDF 验证

检查：

- SHA-256；
- 1022 页；
- 页面标签；
- 标题候选完整覆盖；
- 所有页面证据和查询锚点；
- 内容窗口内覆盖；
- 页面分类和正文页覆盖。

### 13.3 可重复性验证

从同一个 PDF 重新生成 Manifest 和 compiled package，并与已提交的全部 catalog 文件逐字节比较。

相同输入应生成相同输出。若输出不一致，必须解释是规则变化还是非确定性缺陷。

### 13.4 真实 GPT 文件检索验收

本地编译器只能证明锚点存在于源 PDF，不能证明 GPT 文件库一定把目标页排在第一位。

验证报告必须区分：

```text
source_pdf_verification_status: passed
file_search_retrieval_status: not_tested | passed | failed
```

只有在真实 GPT Builder 文件库中执行查询、检查候选和页面视觉后，才能把 `file_search_retrieval_status` 标记为 `passed`。

## 14. 自动化和人工审核的职责边界

脚本负责全量和确定性工作：

- 版面事实提取；
- 候选生成；
- 标题树生成；
- 项目 ID 编译；
- 页面范围和内容窗口；
- 逐页查询和证据；
- 源 PDF 回查；
- 分片、hash、schema 和覆盖检查。

人工不应逐页手填数千条记录。人工审核集中在异常报告：

- 同一种标题样式被多个语义层级复用；
- 标题跨行或 outline 与页面排版冲突；
- 纯图、空白或 parent-only 页面；
- 查询锚点在多页重复；
- 页面边界必须通过视觉确认；
- 真实 file-search 召回不稳定。

大模型可以辅助解释异常，但不能成为权威编号或页面边界的唯一来源。

## 15. 实施中得到的关键经验

1. **锁定源文件优先于一切解析。** 文件名相同不代表内容相同。
2. **标题识别必须依赖版面组合特征。** 全大写比例只能作为辅助。
3. **章首页和普通小标题可能使用完全不同的样式。** 只训练一种样式会形成看似完整、实际缺章的候选集。
4. **页面索引、物理页号和印刷页标签必须同时保存。** 不能长期依赖固定偏移量。
5. **内容切割必须使用 bbox/行顺序。** 字符串首次匹配会被页眉、图注和重复文本误导。
6. **锚点必须从内容窗口提取。** 按整页提取会把公式、图和例题归给相邻章节。
7. **查询存在于 PDF 不等于真实检索通过。** 本地验证和 GPT file-search 验收必须是两个状态。
8. **视觉证据和检索专用锚点不能混为一谈。** 检索索引中的内部字符串不能被声称为页面可见内容。
9. **特殊页面应显式分类。** 不要为了满足 schema 给空白页或纯图页编造正文句。
10. **失败必须发生在构建阶段。** 运行时不应自动修复、不应猜父节点、不应接受部分 catalog。
11. **大文件应使用可审计分片。** 不要通过删除证据或降低完整度来满足仓库传输限制。
12. **最终标准是可重建。** 只有能够从固定 PDF 重建出相同 catalog，生成过程才真正可审计。

## 16. 当前构建命令

```bash
python tools/verify_dip4e_source.py "/path/to/Digital Image ProcessingRafael.pdf"

python tools/extract_pdf_candidates.py \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  build/dip4e/candidates.json

python tools/build_dip4e_manifest.py \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  catalog/dip4e/manifest.yaml

python tools/compile_locator_index.py \
  catalog/dip4e/manifest.yaml \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  catalog/dip4e/compiled_locator_index.json \
  --report catalog/dip4e/validation_report.json

python tools/build_dip4e_exercise_manifest.py \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  catalog/dip4e/exercises.yaml

python tools/compile_exercise_index.py \
  catalog/dip4e/exercises.yaml \
  catalog/dip4e/compiled_locator_index.json \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  catalog/dip4e/compiled_exercise_index.json \
  --report catalog/dip4e/exercise_validation_report.json

python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python tools/validate_prompt.py
```

## 17. 当前验收基线

当前 catalog 的源 PDF 验证基线为：

```text
physical pages: 1022
catalog locators: 444
printed nodes: 114
learning units: 330
page retrieval steps: 3236
source evidence checks: 7181
coverage anchors checked: 12081
query text anchors checked: 6472
source_pdf_verification_status: passed
file_search_retrieval_status: not_tested
```

这些数字是当前固定 PDF 和当前规则的结果，不是通用教材常量。任何规则或源文件变化都应重新生成报告并审查差异。

## 18. Exercise Locator 构建补充

习题与正文使用独立命名空间和独立 package：

```text
exercises.yaml
exercises.sections.02.yaml ... exercises.sections.12.yaml
compiled_exercise_index.json
compiled_exercise_index.sections.02.json ... compiled_exercise_index.sections.12.json
exercise_validation_report.json
```

习题构建器从每章 `Problems` 区域开始识别题号，使用列位置和 bbox 重建双栏阅读顺序，并为同页相邻题生成 `exercise` 类型的 `start_at` / `end_before`。跨页题的每个物理页都必须有独立 step；题号和边界证据使用 `visual_required`。

编译器还会解析题目中的显式依赖：

```text
Section
Figure
Equation
Example
Table
Exercise / Problem
```

解析器必须展开 `and`、逗号并列和 `through` / `to` / 连字符范围，例如
`Eqs. (2-46) and (2-47)`、`Eqs. (6-6)-(6-12)`、`Sections 3.4-3.7`。
Figure 子图标记 `(a)`、`(b)` 不生成新的主 Figure ID。并列或范围中的每个
目标都必须进入 `reference_targets` 并通过源 PDF 锚点解析。

Section 依赖复用正文 Locator；图、公式、例题和表格依赖回查源 PDF 锚点；习题依赖复用目标习题的题目 retrieval plan。运行时同时保留完整 `reference_targets` 作为审计元数据，并生成去重后的 `reference_retrieval_plan` 作为 GPT 默认执行计划。

去重不是简单删除引用。编译器禁止根据“精确目标位于 Section 范围内”自动裁剪 Section。只有经过 PDF 审核并写入 manifest 的 `selected_context_pages` 才会缩小 Section 的执行范围；未显式选择时必须保留完整 Section plan。

聚合只允许合并“同一物理页且 `content_window` 完全相同”的步骤，`required_evidence` 和 `coverage` 取并集。同一页上的不同习题窗口必须保留为多个独立 step，例如 `[4.4, 4.5)` 与 `[4.9, 4.10)` 不能合并。每个非页码 evidence 至少生成一条包含其值的查询，不允许因固定查询数量上限静默丢失目标。

以固定 PDF 中习题 2.11 为例，题干在印刷页 114，提到 Section 2.4 和 Eqs. (2-14)–(2-16)。PDF 原文显示式 (2-14) 和 linear indexing 上下文在印刷页 70，式 (2-15)、(2-16) 在印刷页 71。因此完整 `reference_targets` 仍记录 Section 2.4 的 63–79 页，但 `reference_retrieval_plan` 只执行 70、71 两页，并保留这两页的局部 section 文本证据与公式证据。

缺失引用、跨习题循环、章节不完整、错误 shard 或非规范页面都会阻止输出。

Exercise Catalog 必须覆盖源 PDF 中所有正式 `Problems` 区域后才能进入发布流程。当前固定 PDF 的第 1 章没有课后习题，因此实际范围是第 2 至第 12 章，共 11 个 shard。构建期不保存题目全文，也不批量生成答案。

当前 Exercise Catalog 已使用固定 PDF 完整构建并通过源 PDF 校验与独立目录逐字节重建。验收基线为：

```text
exercise chapters: 11 (chapters 2-12)
exercises: 492
starred exercises: 122
cross-page exercises: 28
exercise retrieval steps: 520
source evidence checks: 1987
query text anchor checks: 1040
resolved references: 465
cross-exercise references: 58
raw reference retrieval steps: 1406
selected context references: 4
execution reference steps before exact-window merge: 1338
coalesced same-page/same-window steps: 72
same-page distinct-window steps preserved: 4
deduplicated reference retrieval steps: 1266
compiled queries: 6939
unbalanced compiled queries: 0
steps without a balanced query: 0
source_pdf_verification_status: passed
file_search_retrieval_status: not_tested
```

11 章题号均从 1 连续到章末，无缺号和重复。可重复性验证比较了 24 个 Manifest/compiled package 文件，结果全部逐字节一致。习题 10.23 的源页印成 `Fig. 10.10.4(a)`，上下文是 3 x 3 Laplacian kernel；构建规则以显式勘误映射归一化为 `Fig. 10.4(a)`，并在引用 reason 中保留审计说明。真实 GPT 文件库检索与视觉页验收仍需单独执行。
