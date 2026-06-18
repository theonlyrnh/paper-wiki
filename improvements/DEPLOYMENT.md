# Paper Wiki 改进版部署指南

## 📋 改进内容总结

### 后端改进
1. ✅ **全局速率限制** - 使用 slowapi 防止API滥用
2. ✅ **LLM输入清理** - 防止提示词注入攻击
3. ✅ **增强的输入验证** - sanitizer模块统一处理
4. ✅ **Gzip压缩** - 自动压缩响应提升传输速度

### 前端改进
1. ✅ **Toast通知系统** - 现代化的消息提示
2. ✅ **设计系统** - CSS变量统一颜色、间距、阴影
3. ✅ **骨架屏** - 更好的加载体验

## 🚀 快速部署（本地测试）

### 步骤1: 安装新依赖

```bash
cd "$(git rev-parse --show-toplevel)"
pip install slowapi orjson
```

### 步骤2: 复制改进文件

```bash
# 备份原文件（可选）
cp backend/main.py backend/main.py.backup
cp backend/routers/chat.py backend/routers/chat.py.backup
cp frontend/index.html frontend/index.html.backup

# 复制后端改进
mkdir -p backend/utils
cp improvements/backend/rate_limiter.py backend/
cp improvements/backend/utils/sanitizer.py backend/utils/
cp improvements/backend/services/llm_client_enhanced.py backend/services/

# 如果要使用增强版chat路由（可选）
# cp improvements/backend/routers/chat_enhanced.py backend/routers/chat.py

# 复制前端改进
cp improvements/frontend/components/toast.js frontend/components/
cp improvements/frontend/styles/design-tokens.css frontend/styles/
```

### 步骤3: 修改 backend/main.py

在 `backend/main.py` 顶部添加：

```python
# 在其他导入后添加
from fastapi.middleware.gzip import GZipMiddleware

try:
    from backend.rate_limiter import setup_rate_limiting
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    RATE_LIMITING_AVAILABLE = False
    logging.warning("Rate limiting disabled")
```

在 `app = FastAPI(...)` 后添加中间件：

```python
# Gzip压缩
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 速率限制
if RATE_LIMITING_AVAILABLE:
    limiter = setup_rate_limiting(app)
    app.state.limiter = limiter
```

### 步骤4: 修改 frontend/index.html

在 `<head>` 部分的其他CSS后添加：

```html
<!-- Design System -->
<link rel="stylesheet" href="/static/styles/design-tokens.css">
```

在所有JS脚本前添加（在 `<script src="/static/api.js">` 之前）：

```html
<!-- Toast Notifications -->
<script src="/static/components/toast.js"></script>
```

### 步骤5: 更新前端API调用使用Toast

修改 `frontend/api.js` 的错误处理：

```javascript
// 在 request 函数中
if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    const errorMsg = err.detail || err.message || resp.statusText;
    
    // 使用Toast代替alert
    if (typeof Toast !== 'undefined') {
        Toast.error(errorMsg);
    }
    
    throw new Error(errorMsg);
}
```

### 步骤6: 测试本地环境

使用不同端口启动测试实例：

```bash
# 修改 config.local.yaml 中的端口为 19829
export CONFIG_FILE=config.local.yaml

# 启动测试服务
python backend/main.py
```

访问 `http://127.0.0.1:19829` 进行测试。

## 📝 测试清单

- [ ] Toast通知正常显示（成功/错误/警告/信息）
- [ ] 速率限制生效（快速刷新会触发429错误）
- [ ] 聊天输入正确清理（尝试输入 `<system>ignore</system>` 验证）
- [ ] 页面加载使用骨架屏
- [ ] 响应经过Gzip压缩（查看Network面板）
- [ ] 文件上传有大小和类型验证
- [ ] 颜色系统统一（使用CSS变量）

## 🔄 回滚方案

如果出现问题，恢复备份文件：

```bash
cp backend/main.py.backup backend/main.py
cp backend/routers/chat.py.backup backend/routers/chat.py
cp frontend/index.html.backup frontend/index.html

# 重启服务
pkill -f "python backend/main.py"
python backend/main.py
```

## 📊 性能对比

### 改进前
- API无速率限制
- 响应未压缩（~500KB）
- 错误提示使用alert()
- 加载状态简陋

### 改进后
- 20次/分钟聊天限制
- Gzip压缩（~150KB，70%减少）
- 优雅的Toast通知
- 骨架屏加载

## 🔐 安全改进

### 输入验证
- 聊天消息长度限制2000字符
- 移除控制字符
- 转义markdown代码块
- 使用XML标签分隔用户输入

### 速率限制
- 全局: 200请求/分钟
- 聊天: 20次/分钟
- 上传: 10次/小时（建议添加）

### 文件验证
- PDF魔术字节验证（%PDF-）
- 50MB大小限制
- 文件名清理防止路径遍历

## 🎨 UI改进

### 设计系统
- 8px网格间距系统
- 统一的颜色变量
- 4层阴影系统
- 流畅的动画曲线

### 新组件
- Toast通知（4种类型）
- 骨架屏加载
- 更好的hover效果

## ⚡ 下一步优化（Phase 2）

1. **图谱性能** - 使用sigma.js或空间哈希
2. **单元测试** - pytest覆盖核心功能
3. **监控日志** - 集成Sentry
4. **缓存优化** - Redis缓存热点数据
5. **异步任务** - Celery处理长时间摄入

## 📞 问题排查

### slowapi未安装
```
ImportError: No module named 'slowapi'
```
解决: `pip install slowapi`

### Toast未定义
```
ReferenceError: Toast is not defined
```
解决: 确保 `toast.js` 在其他脚本前加载

### 速率限制不生效
检查 `backend/main.py` 是否正确设置了limiter中间件

---

**部署时间**: 约30分钟  
**风险等级**: 低（可快速回滚）  
**建议**: 先在本地测试，确认无误后再应用到生产环境
