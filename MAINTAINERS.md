# 维护说明

All In 由 [@powerycy](https://github.com/powerycy) 维护。

## 维护范围

| 范围 | 负责人 |
|---|---|
| 全仓代码、发布与依赖 | [@powerycy](https://github.com/powerycy) |
| 安全边界（人工确认、发送限制、隐私） | [@powerycy](https://github.com/powerycy) |

## 合并规则

- 所有改动通过 Pull Request 合入 `main`，必须通过 CI。
- 涉及以下范围的改动，合并前需明确复核安全边界：
  - 取消或绕过人工确认，提高默认发送频率，放宽发送时间窗口或节流限制。
  - API Key、登录凭据、简历及其他隐私数据的读取、保存、上传或外发方式。
  - 发送、浏览器控制、平台能力开关、数据库迁移和错误恢复边界。
  - CI、发布、依赖锁定和仓库权限。
- 不合并绕过平台安全机制、规避检测或收集用户隐私数据的改动。

## 致谢

被主线采用的贡献记录见 [CONTRIBUTORS.md](CONTRIBUTORS.md)。
