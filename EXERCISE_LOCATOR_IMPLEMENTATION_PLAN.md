# Exercise Locator 全书构建与接入计划

## 1. 背景

当前后端只支持按教材正文的 printed section 或项目 learning unit 返回逐页检索计划：

```text
GET /gpt/section-locators/{section_id}
```

GPT Builder 只能调用 `gptGetSectionLocator`，无法可靠处理以下请求：

- 讲解习题 2.14；
- 只给习题 3.20 的提示；
- 检查某道课后题的答案；
- 列出某章课后习题；
- 读取包含图、公式、表格或跨页内容的习题。

现有正文构建规则也没有把 `Summary`、`Problems` 和下一章标题统一视为正文叶子节点的停止边界，导致部分章节最后一个学习单元可能覆盖章末习题页。

本计划在 Version 3 严格定位架构上增加独立的 Exercise Locator 能力。后端仍只返回定位与核验计划，不复制教材正文，不保存预生成答案，也不在构建期求解习题。

---

## 2. 目标

完成后，系统应支持：

```text
GET /gpt/section-locators/{section_id}
GET /gpt/exercise-locators/{exercise_id}
GET /gpt/chapters/{chapter_id}/exercises
```

对应 GPT Action operationId：

```text
gptGetSectionLocator
gptGetExerciseLocator
gptListChapterExercises
```

核心目标：

1. 为全书课后习题生成独立、完整、按章分片的 Locator Catalog。
2. 精确隔离同页多题、跨页题、带星号题和多子题。
3. 对图形题、表格题和版面相关题强制要求视觉核验。
4. 将题目显式引用的 Section、Equation、Figure、Table、Example 和其他 Exercise 解析为可检索依赖。
5. 修正正文最后一个学习单元吞入 `Summary` 或 `Problems` 页的问题。
6. 保持确定性构建、严格 schema、完整包加载、源 PDF 回查和可重复性验证。
7. 更新 GPT Builder 提示词，使模型能够按“提示、引导、完整推导、检查答案、代码验证”等模式讲解习题。

---

## 3. 非目标

本次不做：

- 在 Catalog 中保存教材题目全文；
- 批量生成或提交全书标准答案；
- 将 Exercise ID 混入现有 Section ID 命名空间；
- 构建通用 PDF 习题解析平台；
- 静默猜测 OCR 缺失、图形缺失或引用无法确认的题目内容；
- 将本地 PDF 编译成功等同于真实 GPT 文件库检索通过。

---

## 4. 设计原则

### 4.1 Section 与 Exercise 使用独立命名空间

正文编号和习题编号可能形式相同，因此运行时、模型和 API 必须分开：

```text
section_id = 2.6.5
exercise_id = 2.14
```

不得把习题表示成 `2.6.8.14`、`2.14-exercise` 或伪造的 learning unit。

### 4.2 先定位，后讲解

后端只返回：

- 题目所在页；
- 页内起止边界；
- 逐页检索查询；
- 必须核验的页面证据；
- 所需正文知识与引用目标。

GPT 在真实文件库中完成题目和依赖知识核验后，才开始讲解。

### 4.3 视觉证据优先于纯文本猜测

以下情况必须使用 `visual_required`：

- 题目依赖图中像素、曲线、坐标、矩阵布局或几何关系；
- 题号、子题或公式在解析文本中错序；
- 双栏页面存在同页多题；
- 内容窗口边界依赖页面布局；
- 表格或图注是题目条件的一部分。

### 4.4 构建完整包，不发布部分索引

生产运行时只能加载完整的全书 Exercise Catalog。开发阶段可以只构建第二章作为规则试点，但不能以“全书习题已支持”的方式发布部分索引。

---

## 5. 数据模型

### 5.1 ExerciseManifest

新增严格模型，建议包含：

```json
{
  "data_version": "4",
  "book_id": "dip4e",
  "source_pdf": {},
  "chapters": [],
  "page_classification": []
}
```

是否升级现有全局 `data_version`，在实现前通过 schema 兼容性评审决定。若运行时模型、包结构和 Action 契约同时变化，优先采用破坏式版本升级，不做静默兼容。

### 5.2 ExerciseNode

每道题至少包含：

```json
{
  "exercise_id": "2.14",
  "chapter_id": "2",
  "exercise_number": 14,
  "starred": true,
  "source_order": 14,
  "problem_page_range": {
    "pdf_page_index_start": 116,
    "pdf_page_index_end": 116,
    "pdf_page_number_start": 117,
    "pdf_page_number_end": 117,
    "printed_page_start": "115",
    "printed_page_end": "115"
  },
  "problem_retrieval_plan": [],
  "reference_targets": []
}
```

禁止在 Manifest 中保存题目全文或答案。

### 5.3 ExerciseRetrievalStep

优先复用现有逐页 Locator 结构，并扩展边界和证据类型：

```text
BoundaryKind += exercise
EvidenceKind += contains_exercise
```

同页多题必须提供：

```json
{
  "content_window": {
    "start_at": {
      "kind": "exercise",
      "value": "2.14"
    },
    "end_before": {
      "kind": "exercise",
      "value": "2.15"
    }
  }
}
```

跨页题目要求每个物理页都有独立 retrieval step。第一页设置开始边界，最后一页设置结束边界，中间页验证连续性和题目上下文。

### 5.4 ReferenceTarget

显式依赖类型：

```text
section
figure
equation
example
table
exercise
```

建议结构：

```json
{
  "kind": "section",
  "target_id": "2.5",
  "reason": "Definitions of 4-, 8-, and m-adjacency",
  "retrieval_plan": []
}
```

依赖应尽量定位到真正需要的页面和锚点，而不是默认读取整个章节。

引用其他习题时允许递归解析，但必须：

- 去重；
- 检测循环；
- 限制递归深度；
- 在无法安全解析时严格失败。

### 5.5 ChapterExerciseSummary

章节列表接口只返回安全元数据：

```json
{
  "chapter_id": "2",
  "exercise_ids": ["2.1", "2.2", "2.3"],
  "first_exercise": "2.1",
  "last_exercise": "2.41",
  "exercise_count": 41
}
```

不返回题目正文。

---

## 6. Catalog 产物

保留现有正文产物：

```text
catalog/dip4e/manifest.yaml
catalog/dip4e/manifest.sections.01.yaml ... manifest.sections.12.yaml
catalog/dip4e/compiled_locator_index.json
catalog/dip4e/compiled_locator_index.sections.01.json ... sections.12.json
catalog/dip4e/validation_report.json
```

新增习题产物：

```text
catalog/dip4e/exercises.yaml
catalog/dip4e/exercises.sections.01.yaml ... exercises.sections.12.yaml
catalog/dip4e/compiled_exercise_index.json
catalog/dip4e/compiled_exercise_index.sections.01.json ... sections.12.json
catalog/dip4e/exercise_validation_report.json
```

`exercises.yaml` 和 `compiled_exercise_index.json` 都作为严格 package manifest，只引用按章 shard。运行时拒绝：

- 缺失 shard；
- 重复 shard；
- 额外 shard；
- data version 不一致；
- chapter 范围不一致；
- 无法组装为完整索引；
- schema 中出现未知字段。

---

## 7. 离线构建流程

### 7.1 共享 PDF 事实提取

现有 `extract_pdf_candidates.py` 应扩展为同时输出：

- PDF identity、页数、page labels 和 outline；
- 正文标题候选；
- Figure、Equation、Example、Table 锚点；
- `Summary` 和 `Problems` 候选；
- 习题题号候选；
- 星号、子题标记和双栏阅读顺序；
- 可用于页内边界验证的行级 bbox。

建议逐步将输出语义从仅有 heading candidates 扩展为共享的 layout facts。正文和习题 builder 消费同一份确定性事实源，避免重复解析 PDF。

### 7.2 正文 Manifest 重建

修改正文结束边界规则：

```text
正文叶子节点结束于：
- 下一个正文标题；
- Summary；
- Problems；
- 下一章标题；
- 正文区域结束。
```

重建全书正文 Manifest 和 compiled locator index，并审核新旧 diff。预期变化主要集中在每章最后一个学习单元和章节点范围。

### 7.3 第二章试点

先只对第二章开发、校准和测试以下规则：

- `Problems` 区域起点；
- 2.1 到 2.41 的顺序与唯一性；
- 双栏阅读顺序；
- 同页多题切割；
- 跨页题目；
- 带星号题；
- `(a) / (b) / (c)` 子题；
- 图形、公式和表格依赖；
- Section、Equation、Figure、Table、Example 引用；
- Exercise 到 Exercise 的引用。

第二章试点通过后，规则才能推广到全书。

### 7.4 全书 Exercise Manifest 构建

新增：

```text
tools/build_dip4e_exercise_manifest.py
```

职责：

1. 读取已验证的源 PDF 和共享 layout facts；
2. 识别每章 `Problems` 区域；
3. 生成按源顺序排列的 ExerciseNode；
4. 计算题目物理页范围与页内 content window；
5. 标记 `starred`、跨页和视觉必需状态；
6. 提取显式引用；
7. 输出完整 package manifest 和 12 个 chapter shard；
8. 不输出不完整或含歧义的运行时数据。

### 7.5 Exercise Index 编译

新增：

```text
tools/compile_exercise_index.py
```

输入：

```text
catalog/dip4e/exercises.yaml
catalog/dip4e/compiled_locator_index.json
Digital Image ProcessingRafael.pdf
```

职责：

- 验证源 PDF SHA-256、页数和 page labels；
- 验证题号、顺序、唯一性和章节归属；
- 验证题目页范围连续；
- 回查每个题号、星号、子题和页内边界；
- 验证所有 retrieval query 和 required evidence；
- 解析并验证正文与习题引用；
- 验证图形题具备视觉证据；
- 生成完整 compiled index、chapter shards 和 validation report；
- 任一错误时不写最终输出。

建议命令：

```bash
python tools/build_dip4e_exercise_manifest.py \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  catalog/dip4e/exercises.yaml

python tools/compile_exercise_index.py \
  catalog/dip4e/exercises.yaml \
  catalog/dip4e/compiled_locator_index.json \
  "/path/to/Digital Image ProcessingRafael.pdf" \
  catalog/dip4e/compiled_exercise_index.json \
  --report catalog/dip4e/exercise_validation_report.json
```

---

## 8. 校验规则

### 8.1 每章完整性

每章至少验证：

- 第一题和最后一题；
- 题目数量；
- 源顺序单调；
- 无重复 ID；
- 无遗漏的已识别题号；
- 所有题目位于本章 `Problems` 与下一章标题之间；
- 章末最后一题不会越过下一章标题。

不要假设所有章节编号范围相同，也不要仅靠连续数字推断题目存在。

### 8.2 页面与内容窗口

- 每道题至少有一个 retrieval step；
- 每个物理页恰好对应一个 step；
- 同页多题必须有 `start_at` 和 `end_before`；
- 跨页题中间页不得被下一题切断；
- printed page label 和 PDF physical page 必须双重验证；
- 边界证据默认 `visual_required`。

### 8.3 引用完整性

- 所有显式 Section、Equation、Figure、Table、Example 和 Exercise 引用必须解析；
- 目标必须存在且位于正确页面；
- 引用类型和编号必须匹配；
- 依赖 retrieval plan 必须通过与正文 Locator 相同级别的锚点验证；
- 不可解析引用必须进入人工审核或导致构建失败，不能静默忽略。

### 8.4 报告指标

`exercise_validation_report.json` 至少记录：

```text
exercise_count
starred_exercise_count
exercise_page_count
exercise_retrieval_step_count
exercise_reference_count
visual_required_exercise_count
cross_page_exercise_count
cross_exercise_reference_count
source_pdf_verification_status
file_search_retrieval_status
```

并按章记录：

```text
chapter_id
first_exercise
last_exercise
exercise_count
missing_numbers
duplicate_numbers
```

`file_search_retrieval_status` 默认必须是 `not_tested`，只有真实 GPT 文件库验收后才能更新。

---

## 9. 运行时与 API

### 9.1 模型

建议新增：

```text
app/models/exercise.py
```

包含：

- `ExerciseLocator`；
- `ExerciseRetrievalStep`；
- `ExerciseReferenceTarget`；
- `ChapterExerciseSummary`；
- 严格字段和跨字段 validator。

### 9.2 Repository 与 Service

建议新增或扩展：

```text
app/repositories/exercise_catalog.py
app/services/exercise_locator.py
```

启动时加载完整 `compiled_exercise_index.json`。缺失、损坏或部分索引时应严格失败。若决定允许部署只提供正文能力，则必须通过明确配置和独立健康状态表达，不能静默隐藏 Exercise API 不可用。

### 9.3 Routes

新增：

```text
GET /gpt/exercise-locators/{exercise_id}
GET /gpt/chapters/{chapter_id}/exercises
```

错误语义：

- 格式错误：422；
- 合法格式但不存在：404；
- catalog 未加载或不完整：启动失败，不在请求时降级；
- 不返回相近题号猜测或自动改写结果。

### 9.4 OpenAPI

更新：

```text
examples/openai_action_schema_one_book.yaml
scripts/export_action_schema.py
```

确保只有真实 Action 被导出，并为新 operationId 增加稳定、简洁的描述和严格响应模型。

---

## 10. GPT Builder 提示词

更新根目录 `PROMPT.md`，支持两条并列流程。

### 10.1 正文学习流程

继续使用：

```text
gptGetSectionLocator
```

### 10.2 习题讲解流程

支持：

```text
gptListChapterExercises
gptGetExerciseLocator
```

执行顺序：

1. 识别用户请求的是正文还是习题；
2. 需要列题时调用章节列表接口；
3. 对具体题目调用 `gptGetExerciseLocator`；
4. 按 `problem_retrieval_plan` 检索并核验题目全部页面；
5. 应用 `content_window`，隔离当前题目；
6. 图形题和版面题完成视觉核验；
7. 按 `reference_targets` 检索相关教材依据；
8. 题目或依赖未完整核验时明确停止，不猜测；
9. 根据用户选择输出提示、苏格拉底式引导、完整推导、答案检查或代码验证。

默认教学结构：

```text
题目目标
已知条件与待求量
需要回顾的教材知识
解题思路
逐步推导
结果检查
常见错误
工程或代码视角（适用时）
最终结论
```

同时更新 `tools/validate_prompt.py`：

- 加入新 Action 必需词；
- 保持 8000 字符限制；
- 禁止不存在的工具名；
- 继续禁止 Version 2 契约。

---

## 11. 测试计划

### 11.1 模型测试

覆盖：

- Exercise ID 格式；
- 章节归属；
- page range 一致性；
- content window 规则；
- 引用类型；
- 循环引用和递归深度；
- 未知字段拒绝；
- package/shard 完整性。

### 11.2 Builder 与 Compiler 测试

覆盖：

- 第二章 2.1 到 2.41 试点；
- 同页多题；
- 单题跨页；
- 最后一题到下一章边界；
- 星号题；
- 图形题；
- 子题；
- 引用 Section、Equation、Figure、Table、Example 和 Exercise；
- 缺号、重号、错页和错误引用时严格失败；
- 失败时不写最终产物；
- 两次构建产物字节级一致或哈希一致。

### 11.3 API 测试

覆盖：

- 正确返回习题 locator；
- 正确列出章节习题；
- 404 和 422；
- 鉴权；
- OpenAPI operationId；
- 正文 API 无回归；
- catalog 缺失时启动失败。

### 11.4 真实 Catalog 测试

至少抽样：

- 第二章图形题；
- 跨页题；
- 含公式引用题；
- 含表格引用题；
- 引用其他习题的题；
- 每章第一题和最后一题。

### 11.5 最终验证命令

```bash
python tools/verify_dip4e_source.py "/path/to/Digital Image ProcessingRafael.pdf"
python tools/validate_prompt.py
python scripts/export_action_schema.py
python -m pytest -q
python -m ruff check .
```

构建产物还必须执行全量可重复性比较和真实应用启动测试。

---

## 12. 真实 GPT 文件库验收

本地 PDF 编译不能替代 GPT 文件库验收。部署后至少执行以下场景：

1. 列出第二章习题；
2. 检索并讲解第二章一题纯文本题；
3. 检索并讲解第二章一题图形题；
4. 检索一题跨页题；
5. 检索一题引用正文公式或图表的题；
6. 选择“只给提示”；
7. 选择“检查我的答案”；
8. 故意请求不存在题号，确认不会猜测；
9. 模拟缺少页面证据，确认模型停止并说明未核验。

验收记录必须区分：

```text
source_pdf_verification_status: passed
file_search_retrieval_status: passed | failed | not_tested
```

---

## 13. 实施阶段

### 阶段 A：契约与边界

- 固化 Exercise schema；
- 确定 data version 策略；
- 增加 `Summary`、`Problems`、`exercise` 边界；
- 为第二章建立测试夹具；
- 修正正文章末范围。

完成标准：第二章正文最后一个 learning unit 不再覆盖习题页。

### 阶段 B：第二章试点

- 实现 exercise candidate 提取；
- 构建第二章 Exercise Manifest；
- 编译第二章 Exercise Index；
- 完成题号、跨页、图形、子题和引用校验。

完成标准：第二章每道题均可确定性定位，所有歧义已明确审核或严格失败。

### 阶段 C：全书构建

- 推广规则到 12 章；
- 完成人工异常审核；
- 生成全书 manifests、shards、compiled indexes 和报告；
- 执行可重复性比较。

完成标准：完整全书 package 可被严格加载，报告无未处理错误。

### 阶段 D：运行时与 Action

- 新增模型、repository、service 和 routes；
- 更新 OpenAPI；
- 更新 Prompt 与校验器；
- 增加 API 和启动测试。

完成标准：本地应用可同时服务正文和习题 Locator，全部自动化测试通过。

### 阶段 E：部署与验收

- 部署新版本；
- 更新 GPT Builder Action schema 和 Instructions；
- 执行真实文件库验收；
- 记录验收状态和已知限制。

完成标准：真实 GPT 可可靠讲解抽样习题，未核验内容不会被猜测。

---

## 14. PR 拆分建议

为控制 review 风险，建议分为以下 PR：

1. **正文边界与共享 layout facts**：修正 `Summary`/`Problems` 边界，保持正文行为可验证。
2. **Exercise schema 与第二章试点**：模型、builder、compiler、第二章数据和测试。
3. **全书 Exercise Catalog**：12 章数据、人工审核结果、报告和可重复性证据。
4. **运行时 API 与 OpenAPI**：repository、service、routes、Action schema。
5. **PROMPT 与真实 GPT 验收准备**：提示词、校验器、文档和验收清单。

若实现过程中发现 schema 与正文 Locator 必须原子升级，可合并前两个 PR，但仍应保持提交边界清楚。

---

## 15. 风险与控制

### 双栏阅读顺序错误

控制：使用 bbox 和列位置重建源顺序；对同页多题进行视觉抽查和边界断言。

### 题号与公式编号混淆

控制：只在 `Problems` 区域识别 exercise candidates，并结合字体、位置、前后顺序和章节前缀判断。

### 解析文本遗漏图形条件

控制：图形题强制 `visual_required`，不允许仅凭文本回答。

### 引用解析不完整

控制：显式引用无法解析时严格失败；人工审核清单单独输出。

### Prompt 超过长度限制

控制：先抽象公共检索流程，再加入习题分支；持续运行 `tools/validate_prompt.py`。

### 全书数据量增加导致启动或 Action 响应过大

控制：继续使用按章 shard；章节列表接口只返回轻量元数据；具体题目接口只返回一题的 Locator。

### 部分 Catalog 被误发布

控制：package manifest 要求 12 个 chapter shards；启动时验证完整性；CI 增加完整包测试。

---

## 16. 完成定义

只有同时满足以下条件，才能声明“全书习题讲解能力完成”：

- 全书正文 Locator 已按新章末边界重新构建并验证；
- 全书 Exercise Manifest 和 compiled index 已生成；
- 12 个章节 shard 完整且通过严格加载；
- 所有源 PDF 校验、schema、单元测试、API 测试和 lint 通过；
- 构建可重复性通过；
- OpenAPI 只导出真实存在的 Action；
- `PROMPT.md` 通过长度和工具契约校验；
- 真实 GPT 文件库验收已完成并记录；
- 图形题、跨页题、引用题和不存在题号场景均符合严格失败原则；
- 没有把教材正文或预生成答案提交进 Catalog。

在真实文件库验收完成前，必须保持：

```text
file_search_retrieval_status: not_tested
```
