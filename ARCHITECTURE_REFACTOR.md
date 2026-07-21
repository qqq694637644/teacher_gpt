# Teacher GPT 破坏式架构重构设计

## 1. 文档状态

- 状态：已决策，待实施
- 适用项目：`teacher_gpt`
- 目标版本：Data/API Version 3
- 更新类型：破坏式更新
- 兼容策略：**不兼容旧接口、旧数据、旧配置和旧 GPT Instructions**
- 核心场景：个人使用，一本固定教材，由 GPT 文件库中的原始 PDF 提供正文与页面视觉内容

本次重构不提供迁移适配层、旧字段别名、旧接口转发、双版本并存、自动数据升级或静默字段清理。旧数据必须删除并按新格式重新构建；旧 GPT Action schema 必须替换。

---

## 2. 重构背景

当前项目把自己设计成教材内容后端：解析 PDF 全文，自动生成章节和派生小节，保存 `SectionPack`，再由 GPT Action 返回正文、图注、公式、例题和页码。

实际测试证明，这个职责划分不适合当前 GPT Action 使用方式：

1. GPT 文件库已经能够对原始 PDF 做页面级检索和多模态查看。
2. GPT Action 更适合提供小而确定的结构化定位信息，不适合复制整本教材正文。
3. 自动解析器会把未编号标题强行编号，导致教材正式编号与 Action 编号冲突。
4. 章节边界、公式定位和 Example 定位无法靠全文语义搜索稳定解决。
5. `page_number` 同时承担 PDF 页和教材印刷页语义，接口含义不明确。
6. Action 和 PDF 同时保存教材内容，会产生两个相互冲突的事实源。

自测中最关键的问题是：

- 用户所说的 `2.6.6 Spatial Operations` 被 Action 解释为 `Logical Operations`。
- `Spatial Operations` 内部未编号标题被自动生成连续章节编号。
- Figure 2.41 可以定位，但缺少明确的印刷页字段。
- Equation 2-47 和 Example 2.9 缺少专用精确定位接口。
- 单独搜索页码 105 会召回错误页面，必须组合图号、公式号、标题和页脚标记进行核验。

因此项目必须从“教材内容后端”重构为“教材坐标与定位后端”。

---

## 3. 新的职责边界

### 3.1 原始 PDF

原始 PDF 上传到 GPT 文件库，作为唯一教材事实源，负责：

- 正文；
- 页面视觉内容；
- 图、表和子图布局；
- 公式排版；
- 图注与正文关系；
- 页面中的标题层级；
- 相邻页面的内容关系。

后端不再保存或返回完整教材正文。

### 3.2 GPT Action 后端

Action 后端只负责：

- 正式章节 ID 和标题；
- 正式章节起止页；
- PDF 页、查看器页和印刷页映射；
- 未编号子标题及其所属正式章节；
- Figure、Equation、Example 所在页；
- 用于文件库检索的页面锚点；
- 用于拒绝错误页面的核验条件；
- 对不存在对象返回明确错误。

Action 不负责解释教材，也不返回教材完整内容。

### 3.3 GPT

GPT 负责：

1. 根据用户问题调用精确 Locator 接口；
2. 使用 Action 返回的检索查询定位原始 PDF 页面；
3. 核验候选页面是否满足关键锚点；
4. 拒绝不匹配页面；
5. 阅读原始页面并进行教学讲解；
6. 无法可靠定位时明确说明失败，不猜测。

### 3.4 目标架构

```text
用户问题
   ↓
GPT
   ├─ 调用 Locator Action 获取坐标、锚点、核验条件
   ├─ 在文件库中搜索原始 PDF
   ├─ 核验候选页面
   └─ 基于原始页面回答

原始 PDF ───────────────→ GPT 文件库

人工审核的 Manifest
   ↓
离线编译
   ↓
Compiled Locator Index
   ↓
FastAPI Locator API
```

核心原则：

> PDF 是事实源，Action 是导航器，GPT 是阅读器和教师。

---

## 4. 明确废弃的旧设计

以下能力在 Version 3 中全部删除，不保留兼容入口。

### 4.1 删除 `SectionPack` 内容模型

删除：

- `text_blocks`；
- `content.offset`；
- `content.limit`；
- `content.next_offset`；
- `content.is_truncated`；
- `content.window_status`；
- `source_pages` 旧结构；
- `previous_sections`；
- `next_sections`；
- Action 返回的完整章节正文。

原因：正文由原始 PDF 提供，Action 不再复制教材内容。

### 4.2 删除旧章节接口

删除：

```text
GET /gpt/sections/{section_id}
GET /books/{book_id}/sections/{section_id}
```

不得让旧路径转发到新 Locator 接口。

### 4.3 删除全文搜索接口

删除：

```text
GET /gpt/search
GET /books/{book_id}/search
```

新的搜索只能搜索定位索引，不扫描章节正文，不返回长文本 snippet。

### 4.4 删除 prerequisites 接口

删除：

```text
GET /gpt/sections/{section_id}/prerequisites
GET /books/{book_id}/sections/{section_id}/prerequisites
```

当前 prerequisites 只是按章节顺序推断，不是可信教材知识结构，不属于定位后端职责。

### 4.5 删除运行时 PDF 导入接口

删除：

```text
POST /books/{book_id}/ingest
```

PDF 处理改为开发时离线工具，不暴露给 GPT Action。

### 4.6 删除旧数据文件

Version 3 不读取以下文件：

```text
book_meta.json
toc.json
section_map.json
section_aliases.json
figure_map.json
page_text.json
section_packs/*.json
```

旧数据目录不能被自动升级。部署 Version 3 前必须删除旧数据并生成新的 compiled index。

### 4.7 删除自动派生章节编号

禁止：

```text
发现大写标题
→ 对上一个章节编号加一
→ 生成新的正式 section_id
```

未编号标题永远不能进入教材正式章节编号体系。

### 4.8 删除章节别名兼容

删除 `section_aliases` 和 `aliases_dip4e.json` 兼容机制。

不存在“把错误自动编号映射回用户习惯编号”的兜底。正式章节编号必须在权威 Manifest 中直接正确。

### 4.9 删除模糊关联

删除 Figure 的 `related_section_ids`。

每个 Figure、Equation 和 Example 只保存经确认的权威 `section_id`。无法确认时构建失败，不通过相似文本匹配返回多个猜测章节。

### 4.10 删除模糊页码字段

删除所有单独的：

```json
{"page_number": 107}
```

不得保留字段别名或自动解释旧语义。

### 4.11 删除内容完整性状态

删除：

- `complete`；
- `content_status`；
- 基于返回字符数的完整性判断；
- 章节正文传输窗口状态。

Action 不返回正文，因此不声明正文是否完整。

---

## 5. 权威数据源：Book Manifest

### 5.1 设计原则

一本固定教材、个人使用场景下，最终结构必须由人工可审查的 Manifest 定义。

自动 PDF 提取只生成候选数据，不能直接发布为运行时索引。

建议文件：

```text
data/dip4e/book_manifest.yaml
```

Manifest 是唯一权威来源，包含：

- 教材信息；
- 页面映射；
- 正式章节；
- 未编号子标题；
- Figure；
- Equation；
- Example；
- 页面锚点；
- 核验条件。

### 5.2 正式章节与未编号标题分离

正式章节示例：

```yaml
sections:
  - section_id: "2.6.6"
    title: "Spatial Operations"
    parent_section_id: "2.6"
    page_range:
      printed_page_start: "98"
      printed_page_end: "106"
      pdf_page_index_start: 99
      pdf_page_index_end: 107
      pdf_page_number_start: 100
      pdf_page_number_end: 108
```

未编号标题示例：

```yaml
subheadings:
  - heading_id: "2.6.6#single-pixel-operations"
    title: "Single-Pixel Operations"
    section_id: "2.6.6"
    printed_page_label: "99"

  - heading_id: "2.6.6#image-registration"
    title: "Image Registration"
    section_id: "2.6.6"
    printed_page_label: "103"
```

`heading_id` 是内部稳定标识，不是教材正式编号，不能向用户表现为 `2.6.7`、`2.6.8` 等章节。

### 5.3 三套页码

每个页面统一保存：

```yaml
page:
  pdf_page_index: 106
  pdf_page_number: 107
  printed_page_label: "105"
```

语义：

- `pdf_page_index`：程序使用的 0-based PDF 索引；
- `pdf_page_number`：PDF 查看器使用的 1-based 物理页码；
- `printed_page_label`：教材页面上实际印刷的页码。

`printed_page_label` 必须是字符串，以支持罗马数字、附录页和无纯数字页码。

禁止在运行时通过固定偏移临时推导印刷页。

### 5.4 Page Locator

每页保存能够稳定检索和核验的锚点：

```yaml
pages:
  - pdf_page_index: 106
    pdf_page_number: 107
    printed_page_label: "105"
    running_header: "2.6 Introduction to the Basic Mathematical Tools Used in Digital Image Processing"
    footer_anchor: "DIP4E_GLOBAL_Print_Ready.indb 105"
    anchors:
      - type: figure
        value: "FIGURE 2.41"
      - type: equation
        value: "(2-47)"
      - type: heading
        value: "Image Registration"
```

锚点优先级：

1. Figure / Example 编号；
2. Equation 编号；
3. 页面内部唯一标题；
4. 页脚 `indb` 标记；
5. 页眉；
6. 少量唯一正文短语。

单独的数字页码不得作为唯一检索条件。

---

## 6. Version 3 运行时数据模型

### 6.1 公共 PageReference

```json
{
  "pdf_page_index": 106,
  "pdf_page_number": 107,
  "printed_page_label": "105"
}
```

三个字段全部必填，不允许 `null`，不接受未知字段。

### 6.2 RetrievalQuery

```json
{
  "query": "FIGURE 2.41 (2-47) DIP4E_GLOBAL_Print_Ready.indb 105",
  "purpose": "primary"
}
```

`purpose` 只能是：

- `primary`；
- `secondary`；
- `adjacent_page`。

### 6.3 VerificationRequirement

```json
{
  "type": "contains_figure",
  "value": "2.41",
  "required": true
}
```

用于告诉 GPT 如何拒绝错误候选页面。

允许的类型至少包括：

- `printed_page_equals`；
- `contains_figure`；
- `contains_equation`；
- `contains_example`；
- `contains_heading`；
- `running_header_contains`；
- `footer_anchor_contains`。

### 6.4 SectionLocator

```json
{
  "data_version": "3",
  "book_id": "dip4e",
  "section_id": "2.6.6",
  "title": "Spatial Operations",
  "parent_section_id": "2.6",
  "page_range": {
    "printed_page_start": "98",
    "printed_page_end": "106",
    "pdf_page_index_start": 99,
    "pdf_page_index_end": 107,
    "pdf_page_number_start": 100,
    "pdf_page_number_end": 108
  },
  "subheadings": [
    {
      "heading_id": "2.6.6#single-pixel-operations",
      "title": "Single-Pixel Operations",
      "page": {
        "pdf_page_index": 100,
        "pdf_page_number": 101,
        "printed_page_label": "99"
      }
    }
  ],
  "figure_ids": ["2.38", "2.39", "2.40", "2.41", "2.42"],
  "equation_ids": ["2-42", "2-43", "2-44", "2-45", "2-46", "2-47"],
  "example_ids": ["2.9", "2.10"],
  "retrieval_queries": [],
  "verification_requirements": []
}
```

不包含正文，不包含分页窗口，不包含完整性字段。

### 6.5 FigureLocator

```json
{
  "data_version": "3",
  "book_id": "dip4e",
  "figure_id": "2.41",
  "section_id": "2.6.6",
  "page": {
    "pdf_page_index": 106,
    "pdf_page_number": 107,
    "printed_page_label": "105"
  },
  "caption_anchor": "FIGURE 2.41",
  "nearby_anchor_ids": ["equation:2-47", "heading:2.6.6#image-registration"],
  "retrieval_queries": [
    {
      "query": "FIGURE 2.41 (2-47) DIP4E_GLOBAL_Print_Ready.indb 105",
      "purpose": "primary"
    }
  ],
  "verification_requirements": [
    {"type": "contains_figure", "value": "2.41", "required": true},
    {"type": "printed_page_equals", "value": "105", "required": true},
    {"type": "contains_equation", "value": "2-47", "required": false}
  ]
}
```

### 6.6 EquationLocator

```json
{
  "data_version": "3",
  "book_id": "dip4e",
  "equation_id": "2-47",
  "section_id": "2.6.6",
  "page": {
    "pdf_page_index": 106,
    "pdf_page_number": 107,
    "printed_page_label": "105"
  },
  "nearby_figure_ids": ["2.41"],
  "nearby_heading_ids": ["2.6.6#image-registration"],
  "retrieval_queries": [],
  "verification_requirements": []
}
```

公式编号使用精确键查找，不走语义搜索。

### 6.7 ExampleLocator

```json
{
  "data_version": "3",
  "book_id": "dip4e",
  "example_id": "2.9",
  "section_id": "2.6.6",
  "title": "Image rotation and intensity interpolation",
  "page": {
    "pdf_page_index": 104,
    "pdf_page_number": 105,
    "printed_page_label": "103"
  },
  "nearby_heading_ids": [
    "2.6.6#geometric-transformations",
    "2.6.6#image-registration"
  ],
  "retrieval_queries": [],
  "verification_requirements": []
}
```

### 6.8 严格模型规则

所有运行时模型必须：

- `extra="forbid"`；
- 必填字段缺失时启动失败；
- ID 重复时编译失败；
- 引用不存在对象时编译失败；
- 旧字段出现时直接失败；
- 不静默丢弃数据；
- 不自动填充旧字段；
- 不基于近似值返回相似对象。

---

## 7. Version 3 Action API

个人使用只保留单教材 `/gpt` API，不再同时维护多教材公开路径。

### 7.1 保留

```text
GET /health
```

### 7.2 新增

```text
GET /gpt/locators/sections/{section_id}
GET /gpt/locators/figures/{figure_id}
GET /gpt/locators/equations/{equation_id}
GET /gpt/locators/examples/{example_id}
GET /gpt/locators/pages/by-printed-label/{printed_page_label}
GET /gpt/locators/pages/by-pdf-index/{pdf_page_index}
GET /gpt/locators/search?q={query}
```

建议 Operation ID：

```text
gptGetSectionLocator
gptGetFigureLocator
gptGetEquationLocator
gptGetExampleLocator
gptGetPrintedPageLocator
gptGetPdfPageLocator
gptSearchLocators
```

### 7.3 精确匹配规则

- Section ID 必须精确匹配。
- Figure ID 必须精确匹配规范化后的 `2.41`。
- Equation ID 必须精确匹配规范化后的 `2-47`。
- Example ID 必须精确匹配规范化后的 `2.9`。
- 不存在返回 404。
- 不自动改成相近 ID。
- 不返回“可能是”列表作为兜底。

输入可以做有限的表面规范化，例如去除 `Figure`、`Fig.`、`Eq.` 或外层括号，但规范化后仍必须进行精确键查找。

### 7.4 Locator 搜索

`gptSearchLocators` 只搜索：

- 正式章节 ID 和标题；
- 未编号标题；
- Figure ID；
- Equation ID；
- Example ID 和标题；
- Page anchors。

禁止搜索教材全文，不返回大段正文。

### 7.5 错误响应

错误响应必须明确区分：

- `BOOK_INDEX_NOT_LOADED`；
- `SECTION_NOT_FOUND`；
- `FIGURE_NOT_FOUND`；
- `EQUATION_NOT_FOUND`；
- `EXAMPLE_NOT_FOUND`；
- `PRINTED_PAGE_NOT_FOUND`；
- `PDF_PAGE_INDEX_NOT_FOUND`；
- `INDEX_SCHEMA_INVALID`。

开发阶段不得用空数组或空对象伪装成功。

---

## 8. 离线构建流程

### 8.1 目录结构

目标结构：

```text
app/
  api/
    routes.py
  models/
    manifest.py
    locator.py
  repositories/
    locator_repository.py
  services/
    locator_service.py

tools/
  extract_candidates.py
  validate_manifest.py
  compile_locator_index.py

data/
  dip4e/
    book_manifest.yaml
    compiled_locator_index.json
    validation_report.json

tests/
  test_manifest_validation.py
  test_section_locators.py
  test_figure_locators.py
  test_equation_locators.py
  test_example_locators.py
  test_page_locators.py
  test_acceptance_cases.py
```

### 8.2 `extract_candidates.py`

从 PDF 中提取候选信息：

- 页面文本；
- 字体、字号、粗体和位置；
- 候选正式标题；
- 候选未编号标题；
- Figure 编号和图注；
- Equation 编号；
- Example 编号；
- 页眉；
- 页脚印刷标记；
- PDF 页与印刷页候选映射。

输出仅供人工审查，例如：

```text
build/dip4e/candidates.json
```

候选文件不能被运行时 API 直接加载。

### 8.3 `validate_manifest.py`

验证：

- 所有 ID 唯一；
- 正式章节边界有效；
- 起始页不大于结束页；
- 三套页码映射一致；
- 每个子标题引用存在的 section；
- 每个 Figure、Equation、Example 引用存在的 section 和 page；
- `nearby_*_ids` 指向存在对象；
- 每个 Locator 至少有一个 primary retrieval query；
- 必填核验条件存在；
- Manifest 不包含任何 Version 2 字段。

任何错误均以非零状态退出。

### 8.4 `compile_locator_index.py`

读取并验证 Manifest，生成唯一运行时文件：

```text
data/dip4e/compiled_locator_index.json
```

编译结果应按对象类型建立精确查找表：

```json
{
  "data_version": "3",
  "book": {},
  "sections": {},
  "subheadings": {},
  "figures": {},
  "equations": {},
  "examples": {},
  "pages_by_pdf_index": {},
  "pages_by_printed_label": {},
  "search_entries": []
}
```

运行时只读取该文件。

### 8.5 启动行为

应用启动时必须完整校验 compiled index。

出现以下情况直接启动失败：

- 文件不存在；
- `data_version` 不是 `3`；
- 结构不合法；
- 包含未知字段；
- 引用断裂；
- ID 冲突；
- 页码映射冲突。

不得在请求时才懒加载并吞掉错误。

---

## 9. GPT Instructions 重写要求

旧 Instructions 中关于 `SectionPack`、分块读取、`next_offset` 和 Action 正文的规则全部删除。

新调用规则：

1. 用户引用章节、Figure、Equation、Example 或页码时，先调用对应 Locator Action。
2. 不允许只使用普通数字页码搜索 PDF。
3. 优先使用 Locator 返回的 primary query。
4. 对候选页面逐项检查 required verification requirements。
5. 任一 required 条件不满足时，拒绝该候选页面。
6. 第一组查询失败时使用 secondary query。
7. 可以检查相邻页，但不能把相邻页内容冒充目标页。
8. 仍无法确认时明确说明无法可靠定位。
9. Action 只提供导航，不作为教材内容引用来源。
10. 教材内容、图像描述和公式解释必须来自原始 PDF 页面。

示例：Figure 2.41 至少检查：

- 页面包含 `FIGURE 2.41`；
- 印刷页为 `105`；
- 页面属于 2.6 节；
- 如可见，公式 `(2-47)` 应在附近。

---

## 10. 实施顺序

本重构一次性切换，不做渐进兼容。

### 阶段 1：定义新契约

- 新建 Version 3 Pydantic 模型；
- 编写 Manifest schema；
- 编写 compiled index schema；
- 编写新的 Action OpenAPI；
- 删除所有 Version 2 model 和 route。

完成条件：应用代码中不存在 `SectionPack`、正文窗口和旧 Action Operation ID。

### 阶段 2：建立第 2 章权威 Manifest

优先覆盖：

- `2.6.6 Spatial Operations`；
- 印刷页 98–106；
- Figure 2.37–2.42；
- Equation 2-42–2-47；
- Example 2.9–2.10；
- 四个内部子标题；
- 三套页码映射；
- 每页强锚点。

完成条件：现有十项自测使用新 Locator API 后达到预期。

### 阶段 3：离线工具

- 提取候选；
- Manifest 校验；
- 编译索引；
- 生成验证报告。

完成条件：错误 Manifest 无法生成 compiled index。

### 阶段 4：运行时瘦身

删除：

- `pdf_ingestor.py` 运行时依赖；
- `section_service.py`；
- `figure_service.py` 旧实现；
- `search_service.py` 全文搜索；
- `storage.py` 旧数据目录逻辑；
- ingest API；
- 多教材 Action API；
- 旧 schema 和旧 GPT Instructions。

替换为：

- `LocatorRepository`；
- `LocatorService`；
- Version 3 routes。

### 阶段 5：部署切换

- 停止旧服务；
- 删除旧数据目录；
- 部署 Version 3；
- 替换 GPT Action schema；
- 替换 GPT Instructions；
- 上传或确认原始 PDF 在 GPT 文件库中；
- 执行验收测试。

不得同时运行 Version 2 和 Version 3。

---

## 11. 破坏式更新清单

实施 PR 必须明确包含以下破坏性变化：

- [ ] 删除所有 Version 2 API 路径；
- [ ] 删除所有 Version 2 schema；
- [ ] 删除旧 JSON 数据读取；
- [ ] 删除 aliases；
- [ ] 删除自动派生正式章节编号；
- [ ] 删除 Action 正文返回；
- [ ] 删除全文搜索；
- [ ] 删除 prerequisites；
- [ ] 删除 ingest API；
- [ ] 删除旧 GPT Instructions；
- [ ] 删除旧 OpenAPI 示例；
- [ ] `data_version` 改为 `3`；
- [ ] 旧字段出现时直接失败；
- [ ] 旧 compiled/data 文件出现时直接失败；
- [ ] README 只描述新架构。

明确禁止：

- `deprecated` 旧端点；
- 301/307 转发；
- 旧响应字段别名；
- Version 2/3 联合模型；
- `Union[OldModel, NewModel]`；
- 启动时自动迁移；
- 找不到新字段时从旧字段推导；
- 捕获校验错误后继续运行；
- 为旧 GPT Action 保留 operationId。

---

## 12. 验收测试

### 12.1 Section Locator

请求：

```text
gptGetSectionLocator("2.6.6")
```

必须返回：

- title = `Spatial Operations`；
- printed range = `98`–`106`；
- 正确 PDF index 和 viewer number；
- Single-Pixel Operations；
- Neighborhood Operations；
- Geometric Transformations；
- Image Registration；
- Figure 2.38–2.42；
- Equation 2-42–2-47；
- Example 2.9–2.10。

不得返回 `Logical Operations`，不得把内部标题生成正式章节编号。

### 12.2 Figure Locator

请求：

```text
gptGetFigureLocator("2.41")
```

必须返回：

- section = `2.6.6`；
- printed page = `105`；
- pdf index = `106`；
- pdf number = `107`；
- primary query 包含 Figure 2.41、Equation 2-47 和页脚锚点；
- required verification 包含 Figure 2.41 和印刷页 105。

不得返回无关的 section `11.6`。

### 12.3 Equation Locator

请求：

```text
gptGetEquationLocator("2-47")
```

必须精确返回印刷页 105 和附近 Figure 2.41，不得走全文语义匹配。

### 12.4 Example Locator

请求：

```text
gptGetExampleLocator("2.9")
```

必须返回印刷页 103、所属 section 2.6.6，以及附近的 Geometric Transformations 和 Image Registration。

### 12.5 Page Locator

请求印刷页 `105` 时必须返回明确的三套页码、Figure 2.41、Equation 2-47 和页脚锚点。

不接受含义不明的 `page=105`。

### 12.6 不存在对象

Figure 2.99、Equation 2-999、Example 2.99 和不存在章节必须返回明确 404，不允许猜测相似对象。

### 12.7 严格失败

以下情况测试必须失败：

- compiled index 使用 `data_version: "2"`；
- 出现 Version 2 字段；
- 未知字段；
- page 只提供 `page_number`；
- Figure 引用不存在 section；
- Equation 引用不存在 page；
- 正式 section ID 重复；
- 同一 printed page 映射到冲突的 PDF page；
- Manifest 中存在自动 alias。

---

## 13. 本次重构不做的事情

个人使用场景下暂不设计：

- 多租户；
- 多用户权限；
- 数据库；
- 向量数据库；
- 高并发；
- 分布式缓存；
- 图片 CDN；
- 批量 PNG 渲染；
- 通用 PDF 版面识别平台；
- 自动适配任意教材；
- 置信度概率校准；
- Version 2 数据迁移工具。

如未来需要按需渲染单页，应作为独立的新工具重新设计，不恢复旧图片传输管线。

---

## 14. 决策摘要

1. 原始 PDF 是唯一教材事实源。
2. Action 只输出坐标、锚点和核验要求。
3. 正式章节只能来自人工审核的 Manifest。
4. 未编号子标题使用内部 heading ID，不生成正式章节编号。
5. 所有页码必须明确区分 PDF index、PDF number 和 printed label。
6. Section、Figure、Equation、Example 和 Page 都有专用 Locator。
7. Action 不返回完整正文，不判断正文完整性。
8. 运行时只读取编译后的 Version 3 locator index。
9. 所有 schema 严格拒绝未知字段和旧字段。
10. 本次更新不提供任何兼容层，旧部署必须整体替换。

最终目标：

> 将项目从“自动解析并复制教材内容的后端”改造成“人工可校正、精确、严格失败的教材坐标系统”。
