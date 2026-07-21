# Teacher GPT Version 3 破坏式重构设计

## 1. 文档状态

- 状态：已决策，待实现
- 使用范围：个人学习，一本固定教材
- 数据版本：`3`
- 更新方式：破坏式替换
- 兼容策略：不兼容 Version 2
- GPT Builder 唯一提示词来源：仓库根目录 `PROMPT.md`
- 教材文件：`Digital Image ProcessingRafael.pdf`

Version 3 不提供旧接口转发、旧字段别名、旧数据迁移、双版本模型、自动修复或静默兼容。旧部署必须整体删除后重新生成索引和部署。

---

## 2. 已验证事实

本设计不是从假设出发，而是基于已上传 PDF、本地逐页检查和用户提供的真实 `file_search` 调用记录。

### 2.1 PDF 基本信息

已上传文件：

```text
Digital Image ProcessingRafael.pdf
```

本地检查结果：

```text
物理页总数：1022
PDF 标题：Digital Image Processing, 4e
作者：Rafael C. Gonzalez
```

PDF 内置页面标签规则：

```text
pdf_page_index 0       → Cover
pdf_page_index 1       → IFC
pdf_page_index 2       → 1
...
pdf_page_index 1020    → 1019
pdf_page_index 1021    → Back Cover
```

因此 Figure 2.41 所在页可以确定为：

```text
pdf_page_index: 106
pdf_page_number: 107
printed_page_label: "105"
```

三套编号不是靠运行时猜偏移量得到，而是从 PDF 页面标签读取并在构建阶段固化。

### 2.2 2.6.6 的真实身份

PDF 正文只印刷了父节编号：

```text
2.6 Introduction to the Basic Mathematical Tools Used in Digital Image Processing
```

`SPATIAL OPERATIONS` 是该节中的未编号标题。PDF 并没有印刷 `2.6.6`。

因此 Version 3 明确定义：

```text
section_id = 项目为学习流程定义的稳定学习单元 ID
printed_parent_section_id = 教材实际印刷的父节编号
source_heading = 教材页面中的原始标题
source_heading_numbered = 原始标题是否带印刷编号
```

Spatial Operations 的权威记录应为：

```json
{
  "section_id": "2.6.6",
  "title": "Spatial Operations",
  "printed_parent_section_id": "2.6",
  "source_heading": "SPATIAL OPERATIONS",
  "source_heading_numbered": false
}
```

不得再声称 `2.6.6` 是教材正式印刷编号，也不得由解析器根据标题出现顺序自动生成该 ID。该 ID 由人工审核的 Manifest 明确定义。

### 2.3 Spatial Operations 的页面边界

本地文本与页面渲染共同确认：

```text
印刷页 98：页面底部开始 SPATIAL OPERATIONS
印刷页 99：Single-Pixel Operations、Neighborhood Operations
印刷页 100：Geometric Transformations 开始
印刷页 101：公式 (2-44)、(2-45)
印刷页 102：正向映射、逆向映射、Table 2.3
印刷页 103：Example 2.9，随后 Image Registration 开始
印刷页 104：Figure 2.40、公式 (2-46)
印刷页 105：Figure 2.41、公式 (2-47)
印刷页 106：Example 2.10，随后进入 VECTOR AND MATRIX OPERATIONS
```

所以该学习单元覆盖印刷页 `98` 到 `106`，但第一页和最后一页都只覆盖页面的一部分。

### 2.4 已验证的逐页查询锚点

下列组合在本地 PDF 文本中能够唯一锁定目标页。真实 `file_search` 仍可能把错误候选排在前面，因此“唯一文本交集”不等于“第一候选必定正确”。

| 印刷页 | PDF index | 已验证组合 |
|---|---:|---|
| 98 | 99 | `SPATIAL OPERATIONS` + `FIGURE 2.37` |
| 99 | 100 | `Single-Pixel Operations` + `Neighborhood Operations` + `(2-42)` + `(2-43)` |
| 100 | 101 | `Geometric Transformations` + `FIGURE 2.39` |
| 101 | 102 | `(2-44)` + `homogeneous coordinates` + `intensity interpolation` |
| 102 | 103 | `inverse mapping` + `TABLE 2.3` + `MATLAB` |
| 103 | 104 | `EXAMPLE 2.9` + `Image Registration` |
| 104 | 105 | `FIGURE 2.40` + `(2-46)` |
| 105 | 106 | `FIGURE 2.41` + `(2-47)` |
| 106 | 107 | `EXAMPLE 2.10` + `VECTOR AND MATRIX OPERATIONS` |

### 2.5 `DIP4E_GLOBAL_Print_Ready.indb N` 的边界

用户提供的真实 `file_search.msearch` 结果中包含：

```text
DIP4E_GLOBAL_Print_Ready.indb 105
```

它对文件库检索有效。但是在本地 PyMuPDF 文本提取和页面渲染中没有看到该字符串。

所以它只能归类为：

```text
retrieval-only anchor
```

不能归类为：

```text
required visual evidence
```

GPT 可以用它搜索，但不能声称在页面视觉中看到了该标记，也不能把它作为必须肉眼确认的条件。

### 2.6 真实文件工具行为

当前环境中实际暴露的是：

```text
file_search.msearch
file_search.mclick
```

`file_library` 是数据源过滤条件，不是工具命名空间：

```json
{
  "source_filter": ["file_library"]
}
```

已知事实：

- GPT 主动提交查询词；
- 一次搜索可以提交多个查询；
- 返回多个候选文本块；
- 候选可能跨越相邻页面；
- 候选没有结构化页码字段；
- 页面视觉预览可能与搜索结果一起出现，但不是每个候选都保证有；
- 第一候选可能错误；
- `+()` 不是严格布尔 AND；
- `mclick` 展开的是候选指针，不是 PDF 页号；
- 没有 `open_page`、`next_page` 或 `previous_page` 接口。

PROMPT 和 Action 契约必须严格基于这些能力，不得编造页面随机访问接口。

---

## 3. 新职责边界

### 3.1 原始 PDF

原始 PDF 放在 GPT 文件库，是教材内容和视觉内容的唯一事实源，负责：

- 正文；
- 公式；
- 图、表和页面布局；
- 图内标签；
- 子图空间关系；
- 标题实际位置；
- 页面视觉证据。

### 3.2 Action 后端

Action 只负责：

- 学习单元 ID；
- 原始标题与印刷父节；
- 页面范围；
- 每页的检索查询；
- 每页必须核验的可见证据；
- 每页覆盖的子标题、Figure、Equation 和 Example；
- 严格的不存在错误。

Action 不返回教材正文，不解释公式，不描述图像。

### 3.3 GPT

GPT 负责：

1. 调用 Action 获取逐页检索计划；
2. 使用 `file_search.msearch` 搜索文件库；
3. 检查多个候选，不默认第一候选正确；
4. 在可用时用 `file_search.mclick` 展开候选；
5. 根据视觉预览和候选文本核验页面；
6. 阅读原始 PDF 后讲解；
7. 无法核验时明确报告缺失页，不猜测。

核心原则：

> PDF 是事实源，Action 是逐页导航计划，GPT 是阅读器和教师。

---

## 4. 使用范围决定的架构收缩

当前学习方式只会按章节或学习单元提问，不处理脱离章节的概念问答。

因此 Version 3 不建设未使用的公开接口：

- 不公开 Figure Locator；
- 不公开 Equation Locator；
- 不公开 Example Locator；
- 不公开 Page Locator；
- 不公开全文搜索；
- 不公开概念搜索。

Figure、Equation、Example 和页面信息仍然进入 Manifest，但只作为 Section Locator 的逐页检索锚点和覆盖清单。

公开 Action 只保留：

```text
GET /health
GET /gpt/section-locators/{section_id}
```

对应 operationId：

```text
healthCheck
gptGetSectionLocator
```

用户未给出学习单元 ID 时，GPT 应要求用户提供 ID，不建设模糊标题搜索作为兜底。

---

## 5. 整本书一次性索引

采用完整索引模式，不发布部分索引。

### 5.1 覆盖范围

发布 Version 3 前必须完成：

- 全部 1022 个物理页的页面引用；
- PDF 页面标签映射；
- 第 1–12 章全部学习单元；
- 每个学习单元的起止位置；
- 每个学习单元的逐页检索计划；
- 每页可见核验条件；
- Figure、Equation、Example 的页面归属；
- Bibliography 和 Index 的页面映射。

封面、IFC 和 Back Cover 可以进入页面映射，但不作为学习单元。

### 5.2 不存在的语义

由于只发布完整索引，因此：

```text
SECTION_NOT_FOUND
```

可以严格表示：该学习单元 ID 不存在。

Version 3 不需要：

```text
OBJECT_NOT_INDEXED
coverage.status
partial coverage
```

编译未完成时应用不得启动。

---

## 6. 仓库中的权威文件

原始 PDF 不提交仓库。Manifest 和 compiled index 在后续索引阶段生成并提交仓库。

目标路径：

```text
catalog/
  dip4e/
    manifest.yaml
    compiled_locator_index.json
    validation_report.json
```

不用 `data/`，因为当前 `.gitignore` 忽略 `data/`。

文件职责：

- `manifest.yaml`：人工审核的权威数据；
- `compiled_locator_index.json`：运行时唯一输入；
- `validation_report.json`：构建证据和检查结果。

运行时不读取 PDF，不读取候选提取文件，也不读取旧 JSON。

---

## 7. 数据模型

所有模型使用严格校验：

```text
extra = forbid
```

未知字段、旧字段、缺失字段、重复 ID、断裂引用和页码冲突必须直接失败。

### 7.1 PageReference

```json
{
  "pdf_page_index": 106,
  "pdf_page_number": 107,
  "printed_page_label": "105"
}
```

规则：

- `pdf_page_index` 为 0-based；
- `pdf_page_number` 必须等于 index + 1；
- `printed_page_label` 来自 PDF page label；
- 三个字段全部必填；
- 不接受旧字段 `page_index` 或 `page_number`。

### 7.2 EvidenceRequirement

```json
{
  "kind": "contains_figure",
  "value": "2.41"
}
```

允许的 `kind`：

```text
printed_page_equals
contains_heading
contains_figure
contains_equation
contains_example
running_header_contains
```

这里只允许可从候选文本或页面视觉确认的证据。

禁止把 `DIP4E_GLOBAL_Print_Ready.indb N` 作为 EvidenceRequirement。

### 7.3 PageCoverage

```json
{
  "subheadings": ["Image Registration"],
  "figure_ids": ["2.41"],
  "equation_ids": ["2-47"],
  "example_ids": []
}
```

这只是告诉 GPT 该页预计覆盖什么，不是教材内容本身。

### 7.4 PageRetrievalStep

```json
{
  "sequence": 8,
  "page_role": "body",
  "page": {
    "pdf_page_index": 106,
    "pdf_page_number": 107,
    "printed_page_label": "105"
  },
  "content_window": {
    "start_at": null,
    "end_before": null
  },
  "queries": [
    "+(FIGURE 2.41) +(2-47) +(Image Registration) +(DIP4E_GLOBAL_Print_Ready.indb 105) --QDF=0",
    "Figure 2.41 rotated image equation 2-47 printed page 105 --QDF=0"
  ],
  "required_evidence": [
    {"kind": "printed_page_equals", "value": "105"},
    {"kind": "contains_figure", "value": "2.41"},
    {"kind": "contains_equation", "value": "2-47"}
  ],
  "coverage": {
    "subheadings": ["Image Registration"],
    "figure_ids": ["2.41"],
    "equation_ids": ["2-47"],
    "example_ids": []
  }
}
```

规则：

- 每一物理页一个 step；
- `sequence` 从 1 连续递增；
- `page_role` 只能是 `start`、`body` 或 `end`；
- `content_window.start_at` 指定当前学习单元在该页从哪个可见锚点开始，包含该锚点；
- `content_window.end_before` 指定在该页遇到哪个可见锚点前结束，不包含该锚点；
- 完整覆盖整页时两个字段都为 `null`；
- 每步至少两个查询：primary 和 secondary，按数组顺序使用；
- 查询字符串是针对当前 `file_search.msearch` 的完整字符串；
- `--QDF=0` 直接写入查询；
- required evidence 必须全部满足；
- 搜索候选排序不参与正确性判断。

### 7.5 SectionLocator

```json
{
  "data_version": "3",
  "book_id": "dip4e",
  "section_id": "2.6.6",
  "title": "Spatial Operations",
  "printed_parent_section_id": "2.6",
  "source_heading": "SPATIAL OPERATIONS",
  "source_heading_numbered": false,
  "page_range": {
    "pdf_page_index_start": 99,
    "pdf_page_index_end": 107,
    "pdf_page_number_start": 100,
    "pdf_page_number_end": 108,
    "printed_page_start": "98",
    "printed_page_end": "106"
  },
  "outline": [
    "Single-Pixel Operations",
    "Neighborhood Operations",
    "Geometric Transformations",
    "Image Registration"
  ],
  "retrieval_plan": []
}
```

`retrieval_plan` 必须包含页面范围内每一个物理页，不能只给章节开始页或几个代表页。

Section Locator 不包含：

- 正文；
- summary；
- content_status；
- complete；
- warnings 兜底；
- previous/next section；
- prerequisites；
- image URL；
- related_section_ids；
- confidence 小数。

---

## 8. 2.6.6 的最终逐页计划

该计划作为 Version 3 首个验收样本。

### Step 1：印刷页 98

```text
primary:
+(SPATIAL OPERATIONS) +(FIGURE 2.37) +(DIP4E_GLOBAL_Print_Ready.indb 98) --QDF=0

secondary:
Spatial operations are performed directly on the pixels Figure 2.37 printed page 98 --QDF=0

required:
printed page 98
heading SPATIAL OPERATIONS

content window:
start_at heading SPATIAL OPERATIONS
end_before null
```

### Step 2：印刷页 99

```text
primary:
+(Single-Pixel Operations) +(Neighborhood Operations) +(2-42) +(2-43) --QDF=0

secondary:
Single-Pixel Operations Neighborhood Operations Figure 2.38 printed page 99 --QDF=0

required:
printed page 99
heading Single-Pixel Operations
heading Neighborhood Operations
equation 2-42
equation 2-43
```

### Step 3：印刷页 100

```text
primary:
+(Geometric Transformations) +(FIGURE 2.39) +(DIP4E_GLOBAL_Print_Ready.indb 100) --QDF=0

secondary:
Geometric Transformations Figure 2.39 printed page 100 --QDF=0

required:
printed page 100
heading Geometric Transformations
figure 2.39
```

### Step 4：印刷页 101

```text
primary:
+(2-44) +(homogeneous coordinates) +(intensity interpolation) --QDF=0

secondary:
affine transformation equation 2-44 equation 2-45 printed page 101 --QDF=0

required:
printed page 101
equation 2-44
equation 2-45
```

### Step 5：印刷页 102

```text
primary:
+(inverse mapping) +(TABLE 2.3) +(MATLAB) --QDF=0

secondary:
forward mapping inverse mapping affine transformations printed page 102 --QDF=0

required:
printed page 102
Table 2.3
text inverse mapping
```

### Step 6：印刷页 103

```text
primary:
+(EXAMPLE 2.9) +(Image Registration) +(DIP4E_GLOBAL_Print_Ready.indb 103) --QDF=0

secondary:
Example 2.9 image rotation intensity interpolation Image Registration page 103 --QDF=0

required:
printed page 103
Example 2.9
heading Image Registration
```

### Step 7：印刷页 104

```text
primary:
+(FIGURE 2.40) +(2-46) +(DIP4E_GLOBAL_Print_Ready.indb 104) --QDF=0

secondary:
Figure 2.40 image rotation tie points equation 2-46 page 104 --QDF=0

required:
printed page 104
figure 2.40
equation 2-46
```

### Step 8：印刷页 105

使用用户提供的真实成功查询：

```text
primary:
+(FIGURE 2.41) +(2-47) +(Image Registration) +(DIP4E_GLOBAL_Print_Ready.indb 105) --QDF=0

secondary:
Figure 2.41 rotated image equation 2-47 printed page 105 --QDF=0

required:
printed page 105
figure 2.41
equation 2-47
```

### Step 9：印刷页 106

```text
primary:
+(EXAMPLE 2.10) +(VECTOR AND MATRIX OPERATIONS) +(DIP4E_GLOBAL_Print_Ready.indb 106) --QDF=0

secondary:
Example 2.10 image registration Vector and Matrix Operations page 106 --QDF=0

required:
printed page 106
Example 2.10
heading VECTOR AND MATRIX OPERATIONS

content window:
start_at null
end_before heading VECTOR AND MATRIX OPERATIONS
```

最后一步同时验证当前学习单元的结束边界。GPT 只讲到该标题之前，不把 Vector and Matrix Operations 内容并入 2.6.6。

---

## 9. Action API

### 9.1 获取学习单元定位计划

```text
GET /gpt/section-locators/{section_id}
operationId: gptGetSectionLocator
```

规则：

- `section_id` 精确匹配；
- 不做 alias；
- 不做模糊匹配；
- 不自动顺延编号；
- 不返回相似 ID；
- 不存在返回 `SECTION_NOT_FOUND`；
- 数据版本不为 3 时服务启动失败。

### 9.2 健康检查

```text
GET /health
operationId: healthCheck
```

健康响应必须包含：

```json
{
  "status": "ok",
  "data_version": "3",
  "book_id": "dip4e",
  "section_count": 0,
  "page_count": 1022
}
```

`section_count` 示例值由 compiled index 实际生成，不能写死。

---

## 10. 离线构建流程

### 10.1 候选提取

离线工具读取 PDF，生成候选：

- PDF 页面标签；
- 正式印刷章节；
- 未编号标题；
- Figure 编号；
- Equation 编号；
- Example 编号；
- 页眉；
- 可用于查询的短语；
- 标题坐标和字体信息。

候选结果不能由运行时加载。

### 10.2 人工审核 Manifest

人工确认：

- 学习单元 ID；
- 原始标题；
- 印刷父节；
- 起止位置；
- 每页 coverage；
- primary/secondary queries；
- required evidence。

解析器不得自行决定最终学习单元编号。

### 10.3 编译与验证

编译器必须检查：

- 1022 个物理页全部有 PageReference；
- PDF 页码和标签与源 PDF 一致；
- 所有学习单元 ID 唯一；
- 所有学习单元页面范围有效；
- retrieval plan 覆盖范围内每一页；
- step sequence 连续；
- 每步至少两个查询；
- 每步至少一个 required evidence；
- start/end 页面必须提供与实际边界一致的 content window；
- 每个 Figure、Equation、Example 归属页面有效；
- 不存在 Version 2 字段；
- 不存在 alias；
- 不存在未知字段。

任何错误都以非零状态退出，不生成 compiled index。

### 10.4 运行时

运行时只加载：

```text
catalog/dip4e/compiled_locator_index.json
```

文件缺失、版本错误或校验失败时，应用直接启动失败。

---

## 11. 明确删除的 Version 2 能力

全部删除，不留 deprecated 入口：

- `SectionPack`；
- `text_blocks`；
- `content.offset/limit/next_offset`；
- 章节正文返回；
- 全文搜索；
- prerequisites；
- PDF ingest API；
- 多教材 API；
- Figure API；
- 自动派生正式章节编号；
- section aliases；
- `related_section_ids`；
- `page_index` / `page_number` 旧字段；
- `content_status` / `complete`；
- 旧 JSON 数据读取；
- `examples/GPT_INSTRUCTIONS_zh.md`；
- Version 2 OpenAPI schema；
- Version 2 operationId。

明确禁止：

- 旧端点转发；
- `Union[V2, V3]`；
- 字段别名；
- 自动迁移；
- 校验失败后继续运行；
- 找不到字段时推导默认值；
- 模糊相似匹配兜底。

---

## 12. `PROMPT.md` 契约

根目录 `PROMPT.md` 是唯一可粘贴到 GPT Builder Instructions 的文件。

它必须：

- 少于 8000 个字符；
- 只引用 `gptGetSectionLocator`；
- 只引用真实文件工具 `file_search.msearch` 和可选的 `file_search.mclick`；
- 使用 `source_filter: ["file_library"]`；
- 不编造按页打开接口；
- 不默认第一候选正确；
- 不把 `+()` 当严格 AND；
- 按 retrieval plan 覆盖每一页；
- 严格遵守每页的 `content_window`，不把边界外内容并入当前学习单元；
- required evidence 全部满足后才确认页面；
- 区分检索锚点与可见证据；
- Action/PDF 冲突时明确报告；
- 无法核验所有页时不得声称完整讲解；
- 不出现 Version 2 operationId、SectionPack 或 next_offset。

---

## 13. 验收测试

### 13.1 PDF 映射

必须验证：

```text
page_count = 1022
index 0 → Cover
index 1 → IFC
index 2 → 1
index 106 → 105
index 1020 → 1019
index 1021 → Back Cover
```

### 13.2 2.6.6 身份

必须返回：

```text
section_id = 2.6.6
title = Spatial Operations
printed_parent_section_id = 2.6
source_heading_numbered = false
printed pages = 98–106
```

不得返回 Logical Operations。

### 13.3 逐页计划

必须有 9 个 step，对应印刷页 98–106，不能遗漏中间页。

### 13.4 Figure 2.41 页面

Step 8 必须返回：

```text
pdf index 106
pdf number 107
printed label 105
Figure 2.41
Equation 2-47
```

### 13.5 页面边界

Step 1 必须确认 SPATIAL OPERATIONS 在印刷页 98 开始。

Step 9 必须确认印刷页 106 出现 VECTOR AND MATRIX OPERATIONS，并把它作为当前学习单元结束边界。

### 13.6 严格失败

以下情况必须失败：

- compiled index 不是 Version 3；
- 页面总数不是 1022；
- 页面标签不匹配源 PDF；
- retrieval plan 少页；
- step 没有 secondary query；
- `DIP4E...indb` 被设为 required visual evidence；
- 出现旧字段；
- 出现 alias；
- 出现未知字段；
- PROMPT 超过 8000 字符；
- PROMPT 引用不存在的 `file_library.open_page`；
- PROMPT 引用 Version 2 Action。

---

## 14. 实施顺序

1. 固化 Version 3 schema 和严格校验。
2. 编写全书页面标签提取和验证。
3. 生成全书候选标题、Figure、Equation、Example。
4. 人工审核完整 Manifest。
5. 为每个学习单元编写逐页 retrieval plan。
6. 编译完整索引；未完成不得发布。
7. 删除 Version 2 代码、数据和 API。
8. 只实现 `gptGetSectionLocator` 和 `healthCheck`。
9. 替换 OpenAPI schema。
10. 使用根目录 `PROMPT.md` 配置 GPT Builder。
11. 对全书学习单元执行验收测试。
12. 整体替换部署，不并行运行旧版本。

---

## 15. 最终决策

Version 3 不再尝试成为通用 PDF 解析平台，也不复制教材正文。

它只做一件事：

> 对一个经过人工审核的学习单元，返回覆盖每一页的文件库检索计划和可见核验条件。

这项能力必须完整、可验证、严格失败；未完成全书索引之前不发布。