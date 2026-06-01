# Teaching GPT Backend

这是一个“**一本教材一个 GPT**”的 Python 后端项目。

它的职责是：

- 离线解析 PDF 教材。
- 渲染每页图片。
- 抽取每页文本。
- 建立目录、小节、派生小节、图、公式、例题索引。
- 给 OpenAI 自定义 GPT 的 Actions 提供接口。
- GPT 调接口拿到结构化 `SectionPack` 后，再开始讲解。

它不是一个普通 PDF Chatbot。核心设计是：

```text
GPT = 教学对话层 + 工具调用层
后端 = 教材解析层 + 章节定位层 + 图文检索层
```

---

## 1. 项目结构

```text
teaching_gpt_backend/
├── app/
│   ├── main.py
│   ├── api/routes.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── errors.py
│   ├── models/schemas.py
│   ├── services/
│   │   ├── pdf_ingestor.py
│   │   ├── book_service.py
│   │   ├── section_service.py
│   │   ├── figure_service.py
│   │   ├── search_service.py
│   │   ├── assets.py
│   │   └── storage.py
│   └── utils/text.py
├── scripts/
│   ├── ingest_book.py
│   └── print_action_schema.py
├── examples/
│   ├── GPT_INSTRUCTIONS_zh.md
│   ├── openai_action_schema_one_book.yaml
│   ├── openai_action_schema_multi_book.yaml
│   └── aliases_dip4e.json
├── deploy/
│   ├── Dockerfile
│   └── docker-compose.yml
├── tests/
└── pyproject.toml
```

---

## 2. 本地启动

```bash
cd teaching_gpt_backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

编辑 `.env`，至少改掉：

```text
TEACHING_GPT_API_KEY=你的长随机密钥
TEACHING_GPT_DEFAULT_BOOK_ID=dip4e
TEACHING_GPT_PUBLIC_BASE_URL=http://localhost:8000
```

启动：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

打开：

```text
http://localhost:8000/docs
```

---

## 3. 导入一本教材 PDF

示例：

```bash
python scripts/ingest_book.py \
  --book-id dip4e \
  --pdf "/path/to/Digital Image ProcessingRafael.pdf" \
  --title "Digital Image Processing" \
  --author "Rafael C. Gonzalez, Richard E. Woods" \
  --aliases examples/aliases_dip4e.json \
  --overwrite
```

说明：

- `book_id` 是这本书的稳定 ID。
- `--aliases` 用于解决“用户习惯小节号”和“自动派生小节号”不一致的问题。
- 对于你前面举的例子，`examples/aliases_dip4e.json` 把 `2.4.4` 映射到自动派生的 `2.4.5`，用于兼容“2.4.4 = Image Interpolation”的讲解习惯。
- 如果你不想渲染页图，可以加 `--no-render`，但教学 GPT 通常需要图片，所以建议保留渲染。

导入后会生成：

```text
data/books/dip4e/
├── original.pdf
├── book_meta.json
├── toc.json
├── section_map.json
├── section_aliases.json
├── figure_map.json
├── page_text.json
├── section_packs/
├── pages/
└── figures/
```

---

## 4. 测试接口

假设 `.env` 里：

```text
TEACHING_GPT_API_KEY=abc123
```

获取目录：

```bash
curl -H "Authorization: Bearer abc123" \
  http://localhost:8000/gpt/toc
```

获取小节：

```bash
curl -H "Authorization: Bearer abc123" \
  http://localhost:8000/gpt/sections/2.4.4
```

搜索概念：

```bash
curl -H "Authorization: Bearer abc123" \
  "http://localhost:8000/gpt/search?q=image%20interpolation"
```

获取图：

```bash
curl -H "Authorization: Bearer abc123" \
  http://localhost:8000/gpt/figures/2.27
```

---

## 5. 给 OpenAI 自定义 GPT 配置 Actions

如果你是“一本教材一个 GPT”，推荐使用：

```text
examples/openai_action_schema_one_book.yaml
```

你需要把里面的：

```yaml
servers:
  - url: https://YOUR-DOMAIN.example.com
```

改成你的公网后端地址。

GPT Builder 中：

1. 创建一个 GPT。
2. Instructions 粘贴 `examples/GPT_INSTRUCTIONS_zh.md` 的内容，并根据当前教材微调。
3. Actions 里导入 `openai_action_schema_one_book.yaml`。
4. Authentication 设置为 Bearer/API Key。
5. Key 值填你的 `TEACHING_GPT_API_KEY`。

你的 GPT 以后调用的是：

```text
/gpt/toc
/gpt/sections/{section_id}
/gpt/search
/gpt/figures/{figure_id}
/gpt/sections/{section_id}/prerequisites
```

这些接口会自动使用 `.env` 里的：

```text
TEACHING_GPT_DEFAULT_BOOK_ID=dip4e
```

所以 GPT 不需要每次传 `book_id`。

---

## 6. 多本书共用一个后端

推荐架构：

```text
一本教材一个 GPT
多个 GPT 共用一个 Teaching Backend
后端用 book_id 区分教材
```

如果你想让 GPT 显式传 `book_id`，可以用：

```text
examples/openai_action_schema_multi_book.yaml
```

对应接口：

```text
/books/{book_id}/toc
/books/{book_id}/sections/{section_id}
/books/{book_id}/search
/books/{book_id}/figures/{figure_id}
/books/{book_id}/sections/{section_id}/prerequisites
```

---

## 7. SectionPack 返回结构

核心接口：

```text
GET /gpt/sections/{section_id}
```

返回：

```json
{
  "book_id": "dip4e",
  "section_id": "2.4.4",
  "resolved_section_id": "2.4.5",
  "title": "Image Interpolation",
  "page_start": 77,
  "page_end": 78,
  "summary": "...",
  "text_blocks": [
    {"type": "paragraph", "text": "..."}
  ],
  "figures": [
    {
      "figure_id": "2.27",
      "caption": "...",
      "page_image_url": "https://.../assets/books/dip4e/pages/page_0078.png"
    }
  ],
  "equations": [
    {"equation_id": "2-17", "context": "..."}
  ],
  "examples": [
    {"example_id": "2.4", "title": "..."}
  ],
  "source_pages": [
    {"page_number": 78, "image_url": "https://..."}
  ],
  "previous_sections": ["..."],
  "next_sections": ["..."],
  "prerequisites": ["..."]
}
```

GPT 拿到这个结构后，再按教学模板讲解。

---

## 8. Docker 启动

```bash
cd teaching_gpt_backend
cp .env.example .env
cd deploy
docker compose up --build
```

服务会在：

```text
http://localhost:8000
```

---

## 9. 生产部署建议

MVP 可以直接用 JSON 文件存储。后面数据量变大时，建议迁移为：

```text
PostgreSQL：book / section / figure metadata
对象存储：PDF / page image / figure image
pgvector 或 Qdrant：语义检索
Redis：热门小节缓存
CDN：页面图片和图像
```

图片 URL 对 GPT 很重要。生产环境推荐：

```text
GPT Action 接口需要鉴权
图片资产可以用 CDN 或签名 URL
```

---

## 10. 当前版本边界

这个包已经实现了完整 MVP：

- PDF 导入
- 页面文本抽取
- 页面图片渲染
- TOC 提取
- 派生小节提取
- 小节包生成
- 图注索引
- 公式编号索引
- 例题编号索引
- GPT Action API
- One-book GPT API
- Multi-book API
- API Key 鉴权
- Docker 部署

需要后续增强的点：

- 更精确的 figure 自动裁剪。
- 更强的公式 OCR / LaTeX 提取。
- 向量检索。
- 用户学习进度。
- 自动测验和错题本。

## 长小节 / 分块读取规则

- 调用 `gptGetSection` 后，必须检查返回值里的 `content` 字段。
- 如果 `content.is_truncated` 为 `true`，或 `content.content_status` 为 `partial`，说明当前只拿到了这一小节的一部分内容，不能暗示已经完整阅读整节。
- 如果用户要求“完整讲这一节”“继续讲”“后面还有吗”，并且 `content.next_offset` 不是 `null`，必须继续调用 `gptGetSection`，传入 `text_offset=content.next_offset`，直到 `content.next_offset` 为 `null` 或已经足够回答用户的问题。
- 如果只讲当前已返回的部分，回答开头要明确说明：“这一小节较长，我先讲当前返回的这一部分；后续内容可以继续读取。”
- 总结、判断整节结论、列完整公式或完整步骤之前，要确认 `content.next_offset` 为 `null`；否则只能说“基于当前已返回部分”。
- 不要忽略 `warnings`。如果 warnings 提示 section text is partial，要把它当作内容未完整返回的信号。

