# PDF 来源切片缓存与手动清理设计文档

> 面向后续实现模型/开发者的详细设计与实施说明。本文档只描述未来功能，不代表当前代码已经实现全部内容。

## 结论先行

建议添加两个功能，并且建议一起设计、分阶段实现：

1. **PDF 来源切片缓存**：在原始 PDF 还存在时生成并缓存搜索/问答所需的来源图片切片；原 PDF 被 7 天自动清理或用户手动删除后，继续用缓存切片展示来源证据。
2. **手动删除原始 PDF**：允许用户对单篇已解析论文手动删除原始 PDF；删除前先尽量生成/刷新来源切片缓存，并明确提示删除后的能力边界。

推荐优先级：

```text
第一阶段：实现 evidence cache 服务 + /pdf-highlights 缓存读取/写入
第二阶段：实现单篇手动删除原始 PDF
第三阶段：把自动清理流程和手动删除流程统一为“删除前确保缓存”
```

---

## 当前项目上下文

### 已有能力

当前项目已经具备：

- 每用户 raw PDF 配额：默认 `1000MB`。
- 首页显示上传文件空间进度条。
- 用户可开启 `7 天后自动删除原始 PDF`。
- 单文件/批量上传会检查 raw PDF 配额。
- 自动清理只删除：
  - `status = done`
  - `markdown_path` 存在
  - markdown 文件真实存在
  - 原始 PDF 存在
  - 超过 7 天
  - 用户开启 `auto_cleanup_raw_pdf`
- PDF 被清理后，`/api/papers/{paper_id}/pdf-highlights` 已返回结构化 fallback，不再让前端显示生硬的“加载失败”。

### 关键现有文件

| 文件 | 当前职责 |
|---|---|
| `backend/routers/papers.py` | 论文上传、详情、删除、重试、`/pdf-highlights` PDF 裁图接口 |
| `backend/routers/wiki.py` | Wiki 页面读取，返回 `source_highlights` |
| `backend/services/storage_quota.py` | raw PDF 配额统计、上传配额检查、安全清理候选判断、清理执行 |
| `backend/services/storage_cleanup.py` | 后台周期性清理开启自动清理的用户 PDF |
| `frontend/pages/search.js` | 搜索页、Wiki 页面展示、右侧 PDF 来源切片 |
| `frontend/pages/chat.js` | 聊天引用来源点击后的 PDF 来源切片弹窗 |
| `frontend/pages/paper-detail.js` | 论文详情页、删除、重试、摄入按钮 |
| `frontend/pages/home.js` | 首页配额进度条与自动清理开关 |
| `frontend/api.js` | 前端 API client |
| `scripts/test_storage_quota.py` | 配额与清理候选规则测试 |

### 当前 PDF 来源切片链路

```mermaid
flowchart LR
    user[用户打开搜索结果/Wiki/聊天引用] --> frontend[前端 search.js/chat.js]
    frontend --> wiki_api[GET /api/wiki/page/{type}/{name}]
    wiki_api --> highlights[source_highlights]
    frontend --> pdf_api[POST /api/papers/{paper_id}/pdf-highlights]
    pdf_api --> raw_pdf[data/raw/{user_id}/{filename}.pdf]
    raw_pdf --> fitz[PyMuPDF 裁剪图片]
    fitz --> response[base64 JPEG slices]
    response --> frontend
```

问题：一旦 `data/raw/{user_id}/{filename}.pdf` 被删除，当前系统无法实时裁剪 PDF 图片，只能降级显示“原始 PDF 已清理”。

---

## 目标与非目标

### 目标

实现后应满足：

1. 删除原始 PDF 后，搜索页右侧仍能显示已经缓存过的 PDF 来源图片切片。
2. 删除原始 PDF 后，聊天引用点击弹窗仍能显示已经缓存过的 PDF 来源图片切片。
3. 如果缓存不存在，继续保留当前的 Markdown/Wiki 友好降级提示。
4. 用户可以在论文详情页手动删除单篇论文的原始 PDF。
5. 手动删除前必须进行安全检查：只允许删除已解析成功且 markdown 存在的原始 PDF。
6. 手动删除前应尽量生成或刷新该论文的来源切片缓存。
7. 自动清理和手动删除复用同一套“删除前确保缓存”的逻辑。
8. 不改变搜索、问答、Wiki、Markdown 查看、论文列表等核心能力。
9. 不把原始 PDF 长期保留作为切片功能的前提。

### 非目标

本阶段不做：

1. 不做对象存储，例如 S3、OSS、R2、MinIO。
2. 不缓存整篇 PDF 的所有页面图片。
3. 不实现 PDF 在线完整阅读器。
4. 不做 OCR 或重新解析模型升级。
5. 不把 evidence cache 计入用户 1000MB raw PDF 配额。
6. 不改变现有 Wiki/向量/搜索数据结构的主流程。

---

## 是否应该添加手动删除功能

建议添加，但要设计成**删除原始 PDF**，不是删除论文。

### 为什么建议添加

| 原因 | 说明 |
|---|---|
| 用户可主动释放空间 | 不必等 7 天自动清理 |
| 解决超配额阻塞 | 用户超额时可以立即删除已解析 PDF 后继续上传 |
| 透明可控 | 用户知道哪些 PDF 被删了 |
| 与自动清理互补 | 自动清理负责长期治理，手动删除负责即时处理 |

### 风险与约束

手动删除必须明确提示：

```text
删除的是原始 PDF 文件，不会删除论文记录、Markdown、Wiki、搜索、问答内容。
删除后若没有缓存切片，将无法显示 PDF 原文截图；如需重新解析原 PDF，需要重新上传。
```

### 手动删除允许条件

只允许删除满足全部条件的原始 PDF：

```text
paper.user_id == current_user.id
paper.status == 'done'
paper.markdown_path 不为空
markdown 文件真实存在
raw PDF 文件真实存在
```

不允许删除：

```text
pending
parsing
ingesting
failed 且没有 markdown
markdown_path 丢失
raw PDF 已不存在
其他用户的 PDF
```

---

## 推荐架构

### 新增目录

新增 evidence cache 根目录：

```text
data/evidence/{user_id}/{paper_id}/
```

每篇论文一个目录，例如：

```text
data/evidence/7/0f3a.../
  manifest.json
  slices/
    sha256-4fc0a1-page-3-0.jpg
    sha256-7d2be9-page-8-1.jpg
```

### 新增配置

建议在 `config.yaml.example` 增加：

```yaml
storage:
  evidence_dir: "data/evidence"
  evidence_cache_enabled: true
  evidence_slice_limit_per_request: 8
  evidence_slice_quality: 75
  evidence_slice_render_scale: 1.5
  evidence_manifest_version: 1
```

真实 `config.yaml` 可以不立即添加；代码应提供默认值，避免缺配置启动失败。

### 新增服务模块

建议新增：

```text
backend/services/evidence_cache.py
```

职责：

1. 计算切片缓存 key。
2. 保存切片图片文件。
3. 读取 manifest。
4. 查找已有缓存。
5. 在 PDF 存在时生成切片并缓存。
6. 在 PDF 不存在时从缓存返回切片。
7. 为手动删除/自动清理提供 `ensure_paper_evidence_cache()`。

不要把这部分继续塞进 `backend/routers/papers.py`，因为 `papers.py` 已经比较长，继续扩展会难维护。

---

## 数据结构设计

### manifest.json

建议每篇论文一个 manifest：

```json
{
  "version": 1,
  "paper_id": "paper-uuid",
  "user_id": 7,
  "paper_title": "Paper title",
  "filename": "original.pdf",
  "created_at": "2026-06-17T12:00:00Z",
  "updated_at": "2026-06-17T12:10:00Z",
  "slices": [
    {
      "cache_key": "b1f6...",
      "image_file": "slices/b1f6-page-3-0.jpg",
      "page": 3,
      "total_pages": 16,
      "score": 92,
      "text": "matched source paragraph text...",
      "query": "multi fidelity",
      "snippet_hash": "df87...",
      "created_at": "2026-06-17T12:10:00Z"
    }
  ]
}
```

### cache_key 规则

切片缓存必须避免 query/snippet 不同却互相覆盖。推荐：

```text
cache_key = sha256(
  paper_id + "\n" +
  normalized_query + "\n" +
  normalized_snippets_text + "\n" +
  evidence_algorithm_version
)
```

其中：

```text
evidence_algorithm_version = "pdf-highlight-v1"
```

同一次请求最多返回 8 张切片，所以 manifest 中可以保存多条 slice。

### 为什么不按 page 直接缓存

不建议只用：

```text
paper_id + page
```

因为同一页可能有不同 query、不同段落、不同裁剪区域。按请求语义缓存更准确。

---

## API 设计

### 1. 改造现有 PDF highlight 接口

现有接口：

```http
POST /api/papers/{paper_id}/pdf-highlights
```

请求体保持不变：

```json
{
  "snippets": [
    {
      "text": "...",
      "start_line": 10,
      "end_line": 15
    }
  ],
  "query": "..."
}
```

返回结构建议扩展为：

#### A. PDF 存在，实时生成并缓存

```json
{
  "paper_title": "...",
  "pdf_available": true,
  "cache_status": "generated",
  "slices": [
    {
      "page": 3,
      "total_pages": 16,
      "image": "data:image/jpeg;base64,...",
      "text": "...",
      "score": 92,
      "cached": true
    }
  ]
}
```

#### B. PDF 存在，命中缓存

```json
{
  "paper_title": "...",
  "pdf_available": true,
  "cache_status": "hit",
  "slices": [
    {
      "page": 3,
      "total_pages": 16,
      "image": "data:image/jpeg;base64,...",
      "text": "...",
      "score": 92,
      "cached": true
    }
  ]
}
```

#### C. PDF 已删除，命中缓存

```json
{
  "paper_title": "...",
  "pdf_available": false,
  "cache_status": "hit",
  "fallback": "cached_evidence",
  "slices": [
    {
      "page": 3,
      "total_pages": 16,
      "image": "data:image/jpeg;base64,...",
      "text": "...",
      "score": 92,
      "cached": true
    }
  ]
}
```

#### D. PDF 已删除，缓存不存在

保持当前降级，但加更明确状态：

```json
{
  "paper_title": "...",
  "pdf_available": false,
  "cache_status": "miss",
  "fallback": "markdown",
  "markdown_available": true,
  "reason": "PDF file not found and evidence cache miss",
  "slices": []
}
```

### 2. 新增手动删除原始 PDF 接口

建议新增：

```http
DELETE /api/papers/{paper_id}/raw-pdf
```

返回：

```json
{
  "id": "paper-uuid",
  "message": "Raw PDF deleted",
  "deleted": true,
  "freed_bytes": 12345678,
  "freed_mb": 11.774,
  "evidence_cache_status": "ready",
  "pdf_available": false
}
```

错误情况：

| 状态码 | 场景 | detail |
|---:|---|---|
| `404` | 论文不存在或不属于当前用户 | `Paper not found` |
| `400` | 论文未完成 | `Only completed papers with markdown can delete raw PDF` |
| `400` | markdown 缺失 | `Markdown content is missing; raw PDF is still needed` |
| `404` | 原始 PDF 已不存在 | `Raw PDF already deleted` |
| `500` | 删除失败 | `Failed to delete raw PDF` |

建议支持参数：

```http
DELETE /api/papers/{paper_id}/raw-pdf?ensure_cache=true
```

默认：

```text
ensure_cache=true
```

如果缓存生成失败，不建议阻止删除，而是返回：

```json
{
  "deleted": true,
  "evidence_cache_status": "failed",
  "warning": "Raw PDF deleted, but evidence cache generation failed. Markdown fallback remains available."
}
```

原因：用户手动删除是释放空间行为，不应因为切片缓存失败完全无法删除。前端需要清楚提示这个 warning。

### 3. 新增论文详情状态字段

现有：

```http
GET /api/papers/{paper_id}
```

建议扩展返回：

```json
{
  "raw_pdf_available": true,
  "raw_pdf_size": 12345678,
  "raw_pdf_size_mb": 11.774,
  "evidence_cache_status": "ready|partial|none|failed",
  "evidence_slice_count": 8
}
```

如果不想改 `PaperDetail` 太多，也可以新增独立接口：

```http
GET /api/papers/{paper_id}/raw-pdf-status
```

推荐直接扩展 `PaperDetail`，因为论文详情页本来就要显示删除按钮。

---

## 服务层详细设计

### evidence_cache.py 建议接口

建议实现以下函数：

```python
from pathlib import Path
from typing import Any

EVIDENCE_CACHE_VERSION = 1
EVIDENCE_ALGORITHM_VERSION = "pdf-highlight-v1"


def get_evidence_dir(user_id: int, paper_id: str) -> Path:
    """Return data/evidence/{user_id}/{paper_id}."""


def load_manifest(user_id: int, paper_id: str) -> dict:
    """Read manifest.json; return empty manifest if missing or invalid."""


def save_manifest(user_id: int, paper_id: str, manifest: dict) -> None:
    """Atomic-ish write: write temp file then replace manifest.json."""


def make_cache_key(paper_id: str, snippets: list[dict], query: str) -> str:
    """Return sha256 cache key for a highlight request."""


def get_cached_slices(user_id: int, paper_id: str, cache_key: str) -> list[dict]:
    """Return cached slices with base64 data URLs if all image files exist."""


def cache_slices(user_id: int, paper_id: str, paper_title: str, filename: str, cache_key: str, slices: list[dict], image_bytes_by_index: list[bytes]) -> list[dict]:
    """Write JPEG files and update manifest. Return slices with cached=true."""


def evidence_cache_summary(user_id: int, paper_id: str) -> dict:
    """Return {status, slice_count, bytes}."""
```

### 从 PDF 生成并缓存切片

建议把当前 `pdf_highlights()` 中 PyMuPDF 裁图逻辑抽到服务层：

```python
async def generate_pdf_highlight_slices(
    pdf_path: Path,
    snippets: list[dict],
    query: str,
    max_slices: int = 8,
) -> tuple[list[dict], list[bytes]]:
    """Return slice metadata and JPEG bytes."""
```

返回示例：

```python
slices = [
    {
        "page": 3,
        "total_pages": 16,
        "text": "...",
        "score": 92,
    }
]
image_bytes_by_index = [b"..."]
```

再由 router 或 service 转成：

```text
data:image/jpeg;base64,...
```

### 文件写入注意事项

1. 所有路径必须限制在 `data/evidence/{user_id}/{paper_id}` 下。
2. 不允许用户输入直接拼接为文件名。
3. 图片文件名使用内部生成的 cache key。
4. manifest 写入建议：

```python
tmp = manifest_path.with_suffix(".tmp")
tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(manifest_path)
```

---

## 手动删除功能详细设计

### 后端删除流程

```mermaid
flowchart TD
    start[DELETE /api/papers/{paper_id}/raw-pdf] --> auth[校验登录用户]
    auth --> load[查询 paper by id + user_id]
    load --> exists{paper 存在?}
    exists -- no --> not_found[404 Paper not found]
    exists -- yes --> safe{status=done 且 markdown 存在?}
    safe -- no --> bad[400 不允许删除]
    safe -- yes --> pdf{raw PDF 存在?}
    pdf -- no --> gone[404 Raw PDF already deleted]
    pdf -- yes --> ensure{ensure_cache=true?}
    ensure -- yes --> cache[尝试生成/刷新 evidence cache]
    ensure -- no --> delete[删除 raw PDF]
    cache --> delete
    delete --> response[返回 freed size + cache status]
```

### 后端实现位置

建议修改：

```text
backend/routers/papers.py
```

新增 endpoint：

```python
@router.delete("/{paper_id}/raw-pdf")
async def delete_raw_pdf(
    paper_id: str,
    ensure_cache: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    ...
```

建议把安全判断抽到 `backend/services/storage_quota.py` 或新建 `backend/services/raw_pdf_lifecycle.py`。

推荐新建：

```text
backend/services/raw_pdf_lifecycle.py
```

职责：

```python
def can_delete_raw_pdf(row, pdf_path: Path) -> tuple[bool, str | None]:
    ...

async def delete_raw_pdf_for_paper(db, row, user_id: int, ensure_cache: bool = True) -> dict:
    ...
```

不要把删除逻辑散落在多个 router。

### 前端论文详情页设计

修改：

```text
frontend/pages/paper-detail.js
```

显示区域建议放在论文详情头部按钮区附近，或者元信息下面：

如果 PDF 存在：

```text
原始 PDF：已保留 · 66.9 MB
[删除原始 PDF]
```

如果 PDF 不存在但缓存存在：

```text
原始 PDF：已清理 · 来源截图缓存可用
```

如果 PDF 不存在且缓存不存在：

```text
原始 PDF：已清理 · 未缓存截图
```

按钮点击二次确认文案：

```text
确定删除这篇论文的原始 PDF 吗？

删除后不会影响搜索、AI 问答、Wiki 内容和 Markdown 查看。
如果来源截图已经缓存，仍可显示缓存切片；未缓存的截图和重新解析需要重新上传 PDF。
```

调用：

```js
await API.deleteRawPdf(paperId)
```

新增 API：

```js
async deleteRawPdf(id) {
    return this.request('DELETE', `/api/papers/${id}/raw-pdf?ensure_cache=true`);
}
```

成功后：

1. Toast 显示释放空间。
2. 刷新论文详情。
3. 调用 `API.refreshStorageQuota()` 更新首页空间事件。

---

## 自动清理与 evidence cache 集成

当前自动清理在：

```text
backend/services/storage_quota.py: cleanup_expired_raw_pdfs()
backend/services/storage_cleanup.py: raw_pdf_cleanup_loop()
```

现状是直接 `unlink()` 原始 PDF。第二阶段应改成：

```text
cleanup_expired_raw_pdfs()
  -> 对每个候选论文
  -> ensure evidence cache best effort
  -> 删除 raw PDF
  -> 返回 evidence_cache_status
```

推荐不要在 `storage_quota.py` 里直接导入大量 PyMuPDF 逻辑，避免职责混乱。

建议方式：

```python
# backend/services/storage_quota.py
async def cleanup_expired_raw_pdfs(db, user_id, retention_days=..., ensure_cache=True):
    from backend.services.raw_pdf_lifecycle import delete_raw_pdf_for_paper
    ...
    result = await delete_raw_pdf_for_paper(db, row, user_id, ensure_cache=ensure_cache, reason="auto_cleanup")
```

或者把整个清理执行迁到 `raw_pdf_lifecycle.py`。

---

## Evidence cache 生成策略

### 按需缓存

当用户打开搜索来源或聊天引用时：

```text
/pdf-highlights 请求到来
  如果缓存命中：直接返回缓存
  如果 PDF 存在且缓存未命中：实时生成切片并保存缓存
  如果 PDF 不存在且缓存未命中：返回 markdown fallback
```

优点：

- 最省计算。
- 只缓存用户真正看过的来源。
- 不需要上传后为所有论文预生成大量切片。

缺点：

- 如果用户从未打开过某篇论文的来源切片，7 天后 PDF 被删，可能没有缓存。

### 删除前 best-effort 缓存

手动删除/自动清理前，系统可以用已有 Wiki 来源关系主动生成一组默认切片。

做法：

1. 查询 `wiki_pages` 中 `sources` 包含该 `paper_id` 的页面。
2. 取最多 `N=3` 个相关 wiki 页面。
3. 对每个页面使用现有 `_find_relevant_paragraphs()` 得到 snippets。
4. 调用与 `/pdf-highlights` 相同的生成函数缓存切片。

注意：不要为了缓存遍历所有 Wiki 页面生成大量图片，第一版限制：

```text
每篇论文删除前最多缓存 8 张切片
```

推荐配置：

```yaml
evidence_cache_max_slices_per_paper: 8
```

---

## 前端展示策略

### search.js

当前逻辑：

```js
if (data.pdf_available === false) {
    slicesEl.innerHTML = pdfCleanedFallbackHtml();
    continue;
}
```

第二阶段改成：

```js
if (data.slices && data.slices.length) {
    renderSlices(data.slices, { cached: data.cache_status === 'hit' });
    continue;
}
if (data.pdf_available === false) {
    slicesEl.innerHTML = pdfCleanedFallbackHtml();
    continue;
}
```

也就是说：

```text
有 slices 就显示，不管 PDF 是否存在。
```

如果是缓存切片，可以加小标签：

```text
缓存来源截图
```

### chat.js

同 search.js，优先显示 `slices`，再判断 `pdf_available=false` fallback。

### paper-detail.js

新增原始 PDF 状态与删除按钮。

---

## 数据库变更建议

可以不新增表，第一版只用文件 manifest。  
但为了详情页和统计更快，建议扩展 `PaperDetail` 时通过文件系统实时检查即可：

```python
raw_pdf_available = pdf_path.exists()
raw_pdf_size = pdf_path.stat().st_size if exists else 0
raw_pdf_size_mb = bytes_to_mb(raw_pdf_size)
evidence = evidence_cache_summary(user_id, paper_id)
```

如果后续需要后台统计大量 evidence，再考虑新增表：

```sql
CREATE TABLE evidence_cache (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    paper_id TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    image_path TEXT NOT NULL,
    page INTEGER,
    score INTEGER,
    text TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, paper_id, cache_key, image_path)
);
```

第一版不推荐加表，避免迁移复杂。

---

## 测试计划

### 新增测试文件

建议新增：

```text
scripts/test_evidence_cache.py
scripts/test_raw_pdf_lifecycle.py
```

### test_evidence_cache.py

测试点：

1. `make_cache_key()` 对同一输入稳定。
2. 不同 query 生成不同 cache key。
3. `cache_slices()` 能写入图片和 manifest。
4. `get_cached_slices()` 能读回 data URL。
5. 图片文件缺失时返回空或 cache miss，不抛异常。
6. manifest 损坏时不会导致接口崩溃。

示例断言：

```python
def test_cached_slices_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        cache_root = Path(tmp)
        slices = [{"page": 1, "total_pages": 3, "text": "hello", "score": 90}]
        images = [b"fake-jpeg-bytes"]
        cached = cache_slices(...)
        loaded = get_cached_slices(...)
        assert loaded[0]["image"].startswith("data:image/jpeg;base64,")
```

### test_raw_pdf_lifecycle.py

测试点：

1. `can_delete_raw_pdf()` 只允许 `done + markdown exists + pdf exists`。
2. `failed` 不允许删除。
3. `done` 但 markdown 文件丢失不允许删除。
4. 删除成功返回 freed bytes。
5. 删除后 raw PDF 不存在。
6. evidence cache 失败时仍可删除，但返回 warning。

### 手工验证

1. 上传一篇 PDF，完成解析和摄入。
2. 打开搜索结果，确认右侧生成切片。
3. 手动删除该论文原始 PDF。
4. 再次打开同一搜索结果，确认仍显示缓存切片。
5. 删除 evidence 目录后再次打开，确认显示 markdown fallback。
6. 首页空间进度条减少。
7. 论文详情显示“原始 PDF 已清理”。

---

## 实施计划

### Task 1：新增 evidence cache 服务

**文件：**

- 新增：`backend/services/evidence_cache.py`
- 新增：`scripts/test_evidence_cache.py`
- 修改：`config.yaml.example`

**步骤：**

1. 写 `scripts/test_evidence_cache.py`，先 RED。
2. 在 `evidence_cache.py` 实现：
   - `get_evidence_dir()`
   - `load_manifest()`
   - `save_manifest()`
   - `make_cache_key()`
   - `cache_slices()`
   - `get_cached_slices()`
   - `evidence_cache_summary()`
3. 测试通过。
4. `config.yaml.example` 增加 evidence 相关配置。

### Task 2：抽出 PDF highlight 生成逻辑

**文件：**

- 修改：`backend/routers/papers.py`
- 新增或修改：`backend/services/evidence_cache.py`
- 新增：`scripts/test_pdf_highlight_cache_logic.py`

**步骤：**

1. 把 `/pdf-highlights` 里的 PyMuPDF 裁图逻辑抽成函数。
2. 函数返回 metadata 和 JPEG bytes，不直接返回 base64。
3. router 负责把结果组装成 API response。
4. 保持当前接口兼容。
5. 跑现有 py_compile 和前端检查。

### Task 3：改造 `/pdf-highlights` 支持缓存

**文件：**

- 修改：`backend/routers/papers.py`
- 修改：`backend/services/evidence_cache.py`
- 修改：`frontend/pages/search.js`
- 修改：`frontend/pages/chat.js`

**步骤：**

1. 请求进来先计算 `cache_key`。
2. 如果缓存命中，返回 `cache_status: "hit"` 和 slices。
3. 如果 PDF 存在且缓存未命中，生成切片、写缓存、返回 `cache_status: "generated"`。
4. 如果 PDF 不存在且缓存命中，返回 `pdf_available:false` 但带 slices。
5. 如果 PDF 不存在且缓存未命中，返回当前 markdown fallback。
6. 前端改成“有 slices 优先显示”。

### Task 4：扩展论文详情 raw PDF 状态

**文件：**

- 修改：`backend/models.py`
- 修改：`backend/routers/papers.py`
- 修改：`frontend/pages/paper-detail.js`

**步骤：**

1. `PaperDetail` 增加：
   - `raw_pdf_available: bool`
   - `raw_pdf_size: int`
   - `raw_pdf_size_mb: float`
   - `evidence_cache_status: str`
   - `evidence_slice_count: int`
2. `get_paper()` 里计算这些字段。
3. 前端详情页显示原始 PDF 状态。

### Task 5：新增手动删除原始 PDF 接口

**文件：**

- 新增：`backend/services/raw_pdf_lifecycle.py`
- 修改：`backend/routers/papers.py`
- 新增：`scripts/test_raw_pdf_lifecycle.py`
- 修改：`frontend/api.js`
- 修改：`frontend/pages/paper-detail.js`

**步骤：**

1. 写删除安全规则测试，先 RED。
2. 实现 `can_delete_raw_pdf()`。
3. 实现 `delete_raw_pdf_for_paper()`。
4. 新增：

   ```http
   DELETE /api/papers/{paper_id}/raw-pdf?ensure_cache=true
   ```

5. 前端新增 `API.deleteRawPdf(id)`。
6. 论文详情页显示“删除原始 PDF”按钮。
7. 删除成功后刷新详情与空间配额。

### Task 6：自动清理集成 evidence cache

**文件：**

- 修改：`backend/services/storage_quota.py`
- 修改：`backend/services/storage_cleanup.py`
- 修改：`backend/services/raw_pdf_lifecycle.py`

**步骤：**

1. 自动清理候选仍沿用现有 `is_cleanup_candidate()`。
2. 删除时调用 `delete_raw_pdf_for_paper(..., ensure_cache=True, reason="auto_cleanup")`。
3. evidence cache 失败不阻断自动删除，但记录 warning 日志。
4. 返回结果增加：
   - `cache_ready_count`
   - `cache_failed_count`

### Task 7：验证与回归

运行：

```bash
python scripts/test_storage_quota.py
python scripts/test_search_regression.py
python scripts/test_paper_retry_logic.py
python scripts/test_evidence_cache.py
python scripts/test_raw_pdf_lifecycle.py
python -m py_compile backend/main.py backend/routers/papers.py backend/routers/system.py backend/services/storage_quota.py backend/services/storage_cleanup.py backend/services/evidence_cache.py backend/services/raw_pdf_lifecycle.py backend/models.py
node --check frontend/api.js frontend/pages/search.js frontend/pages/chat.js frontend/pages/paper-detail.js frontend/pages/home.js frontend/pages/papers.js
bash -n tunnel.sh
bash -n scripts/start.sh
curl -sS http://127.0.0.1:19828/api/health
```

手工验证：

```text
1. 登录。
2. 找一篇 done 且 raw PDF 存在的论文。
3. 打开搜索/Wiki 页面让系统生成来源切片。
4. 进入论文详情，点击“删除原始 PDF”。
5. 回到搜索/Wiki/聊天引用，确认仍显示缓存切片。
6. 删除 data/evidence 对应 paper 目录，刷新页面，确认显示友好降级。
```

---

## 风险与防护

| 风险 | 防护 |
|---|---|
| evidence 目录无限增长 | 第一版每篇最多缓存 8 张切片；后续可加 LRU/配额 |
| 用户删除 PDF 后没有缓存 | 显示 Markdown fallback，不报错 |
| 缓存图片损坏 | 读缓存时验证文件存在，不存在则 cache miss |
| manifest JSON 损坏 | `load_manifest()` 捕获异常并返回空 manifest |
| 路径穿越 | evidence 路径只用 user_id/paper_id/cache_key，不用用户文件名作为路径 |
| 删除其他用户 PDF | 所有接口必须 `WHERE id=? AND user_id=?` |
| 自动清理误删失败论文 | 继续沿用 `status=done + markdown exists` 安全条件 |
| 删除 PDF 后无法重新解析 | 前端确认文案必须明确提示需要重新上传 |

---

## 最终验收标准

实现完成后，应满足：

1. 原 PDF 存在时，`/pdf-highlights` 能正常生成切片并缓存。
2. 原 PDF 删除后，同一个来源请求能返回缓存切片。
3. 原 PDF 删除且缓存不存在时，返回 markdown fallback。
4. 搜索页右侧能显示缓存切片，并标记为缓存来源截图。
5. 聊天引用弹窗能显示缓存切片。
6. 论文详情页能显示 raw PDF 状态和缓存状态。
7. 用户可以手动删除单篇已解析论文的原始 PDF。
8. 删除后首页空间进度条减少。
9. 自动清理仍只删除安全候选，并在删除前 best-effort 生成缓存。
10. 所有新增测试、既有搜索/重试/配额测试通过。

---

## 给实现模型的注意事项

1. **不要直接删除整个 `data/raw`。** 只能删除当前用户当前论文的 raw PDF，或自动清理候选。
2. **不要把 evidence cache 计入 1000MB raw PDF 配额。** 该配额当前只管原始 PDF。
3. **不要让缓存失败阻断用户删除 PDF。** 缓存失败时返回 warning，保留 Markdown fallback。
4. **不要在文档或日志里输出敏感配置。**
5. **不要改变已有搜索和问答主流程。** 只增强来源截图展示能力。
6. **优先写测试再改生产代码。** 当前项目已有 `scripts/test_*.py` 风格，可继续沿用。
