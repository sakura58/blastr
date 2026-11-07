# 发布清单（PUBLISH）

这份文件是给你自己看的，发出去之后可以删掉。

当前这台机器上**没有装 git 和 gh**（我已经检查过），所以「推送」这一步需要你来做，或者先装 git。三条路任选。

---

## 1. 先把 OWNER 换掉

需要替换两处占位符：

- `pyproject.toml` 里的 `https://github.com/OWNER/blastr`
- `README.md` 顶部的 CI badge 链接

```powershell
# 在 blastr 目录下，把 OWNER 换成你的 GitHub 用户名
$you = "your-github-name"
(Get-Content pyproject.toml -Raw).Replace("OWNER", $you) | Set-Content pyproject.toml -NoNewline
(Get-Content README.md -Raw).Replace("OWNER", $you) | Set-Content README.md -NoNewline
```

## 2. 建仓库并推送

### 路线 0：双击 `publish.cmd`（最快，不需要 git/gh）

1. 建一个 classic token：<https://github.com/settings/tokens/new> → 勾 **`repo`** → 7 天过期
2. 双击本目录的 `publish.cmd`
3. 按提示粘贴 token（输入不可见，只在内存里用一次，不写盘）

它会自动：建 public 仓库 `blastr` → 上传全部文件 → 写描述和 topics → 打 `v0.1.0` release。
跑完记得去同一页面把 token 删掉。

### 路线 A：装 git（推荐，以后还要用）

```powershell
winget install --id Git.Git -e
```

装完重开一个终端，然后：

```bash
cd blastr
git init -b main
git add .
git commit -m "blastr 0.1.0 — blast radius for a diff"
```

在 GitHub 网页上新建一个空仓库 `blastr`（不要勾 README / .gitignore / license），然后：

```bash
git remote add origin https://github.com/<你的用户名>/blastr.git
git push -u origin main
```

### 路线 B：用 gh CLI

```powershell
winget install --id GitHub.cli -e
gh auth login
cd blastr
git init -b main && git add . && git commit -m "blastr 0.1.0"
gh repo create blastr --public --source=. --push
```

### 路线 C：完全不装 git

GitHub 网页 → New repository → 创建空仓库 → 进入仓库页面 → **Add file → Upload files** → 把 `blastr` 目录里的所有文件拖进去（注意保持 `src/blastr/`、`tests/`、`.github/workflows/` 的目录结构；网页上传支持拖文件夹）。

提交信息写：`blastr 0.1.0 — blast radius for a diff`

## 3. 仓库设置（30 秒，但对曝光很关键）

进去之后点右上角齿轮 **About**：

- **Description**：
  `Blast radius for a diff — who calls what you just changed. Zero-dependency CLI + MCP tool for AI coding agents.`
- **Topics**（逐个加）：
  `git` `diff` `code-review` `static-analysis` `impact-analysis` `ai-agents` `mcp` `cli` `python` `developer-tools`
- 勾上 **Releases** / **Packages** 不需要；**Issues** 打开。

## 4. 可选：发到 PyPI

```bash
python -m pip install build twine
python -m build
python -m twine upload dist/*
```

`blastr` 这个名字在 PyPI 上可能已被占用，如果 `twine` 报 403/400，就把 `pyproject.toml` 里的 `name` 改成 `blastr-cli`，CLI 命令名仍然是 `blastr`。

## 5. 首发之后

- 在 README 最上面加一张真实终端截图（现在是代码块，等有图会更有说服力）。
- Release 打 `v0.1.0`，把 README 的「Demo」那段当作 release notes。
- 发帖时不要写「我做了个工具」，写这个具体场景：
  > agent 把 `create_user(name, email)` 改成要三个参数，测试全绿，diff 四行，然后线上 9 个调用点 TypeError。我做了个东西，在你按 merge 之前把这张表打出来。
- 记得把这条也发出去：`blastr --mcp` 可以直接挂进 Claude Code / Codex 当工具用。

## 6. 发布前最后检查

```bash
python -m unittest discover -s tests    # 34 个测试应当全绿
python examples/demo.py                 # 输出应当和 README 里那段一致
```
