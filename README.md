# zoo-auto

最小版仓库：Zo 自动登录与已登录态复用。

## 保留文件

- `login_zo.py` — 触发 Zo 邮件登录链接
- `playwright_zo_flow.py` — 优先使用 GitHub Secret 中的 Cookie，失效时再触发登录，并在成功后自动回写最新 Cookie 到 GitHub Secret
- `github_secrets.py` — GitHub Secret 读写辅助
- `requirements.txt` — 运行依赖
- `requirements-dev.txt` — 测试依赖
- `tests/` — 最小测试集
- `.github/workflows/ci.yml` — 测试工作流
- `.github/workflows/zo_auto_login.yml` — 实际自动运行工作流

## 环境变量 / GitHub Secrets

以下内容全部按 GitHub Secrets / Variables 使用：

### Secrets
- `GMAIL_USER` — Gmail/Zo 登录邮箱
- `GMAIL_APP_PASSWORD` — Gmail app password
- `ZO_EMAIL` — 可选，若不填则回退到 `GMAIL_USER`
- `TG_BOT_TOKEN` — Telegram bot token
- `TG_CHAT_ID` — Telegram chat id
- `ZO_STORAGE_STATE_B64` — Base64 编码后的 Playwright storage state / Cookie
- `GH_PAT` — 用于自动更新 `ZO_STORAGE_STATE_B64` 的 GitHub PAT，必须包含 `repo` 和 `workflow`

### Variables
- `ZO_PROMPT` — 运行时发送的提示词，可选

## 工作方式

1. 工作流启动时，把 `ZO_STORAGE_STATE_B64` 解码为本地 `zo_storage_state.json`
2. 如果 Cookie 可用，直接复用
3. 如果 Cookie 不可用，则触发 Zo 邮件登录
4. 流程结束后，把最新 storage state 重新编码
5. 若仓库里已有 `GH_PAT`，脚本会自动把新的 `ZO_STORAGE_STATE_B64` 回写到当前仓库 Secret

## 本地测试

```bash
python3 -m pip install -r requirements-dev.txt
pytest -q
```

## 注意

- 不提交 `.env`、`.venv`、截图、调试 json/html、缓存文件
- GitHub Actions 里不会依赖本地文件保存账号密码或 Cookie
