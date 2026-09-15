# 贡献指南

感谢你对 All In 的关注！欢迎提交 Issue 和 Pull Request。

## 行为准则

- 保持友善和建设性的讨论
- 尊重每一位贡献者的时间

## 提交 Issue

- Bug 报告请使用 [Bug 报告模板](.github/ISSUE_TEMPLATE/bug_report.md)
- 选择器失效请使用 [选择器失效模板](.github/ISSUE_TEMPLATE/selector_broken.md)
- 新功能建议请先开 Issue 讨论

## 提交 Pull Request

### 接受的 PR 类型

- Bug 修复
- 选择器适配更新
- 文档改进
- 新功能（需先开 Issue 讨论）

### 不接受的 PR

- **提高默认发送频率** — 这会增加所有用户的封号风险
- **绕过人工确认环节** — 人工审核是核心安全机制
- **绕过平台安全检测的新方法** — 项目定位是效率工具，不是攻防工具
- **降低反检测策略的保守程度** — 如缩短间隔、扩大时间窗口等

### PR 流程

1. Fork 仓库
2. 基于 `main` 创建功能分支：`git checkout -b feat/your-feature`
3. 提交代码，确保 `allin --help` 正常运行
4. 运行相关测试；涉及前端时同时确认前端可以构建
5. 推送并创建 Pull Request，说明改动原因和影响范围
6. 相关测试与必需检查通过后合并

涉及人工确认、发送限制、凭据与隐私数据的改动属于高风险范围，需明确复核安全边界，详见 [GOVERNANCE.md](GOVERNANCE.md)。

### 代码风格

- Python: 遵循 ruff 默认规则，行长 120
- 提交信息：中文或英文均可，简洁描述改动

## 本地开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 检查代码风格
ruff check src/

# 运行测试
pytest tests/ -q

# 运行 CLI
allin --help
```

## 选择器维护

招聘平台页面结构可能随时变化。如果你发现选择器失效：

1. 打开 Chrome DevTools 检查新的 DOM 结构
2. 更新对应的选择器代码
3. 提交 PR 并说明变化

这是最欢迎的贡献类型之一。

## 致谢

被主线采用的贡献记录见 [CONTRIBUTORS.md](CONTRIBUTORS.md)。
