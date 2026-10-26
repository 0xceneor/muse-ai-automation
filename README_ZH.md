# Muse.ai 自动化注册、激活与邀请码兑换完整方法论

[English (英文)](README.md) | [简体中文](README_ZH.md)

生产级自动化方法论、技术架构全解析以及基于 Playwright CDP 的全流程自动化脚本。用于在 **CloakBrowser**、住宅代理及自动化邀请码兑换机制下，批量开通、验证并激活 **Muse.ai** 个人 AI 账户。

> **底层防关联/指纹浏览器引擎**: 基于 **[CloakBrowser (0xceneor/CloakBrowser)](https://github.com/0xceneor/CloakBrowser)** 构建 — 具备 87 项 C++ 源码级指纹修补、桌面配置文件管理器（Desktop Profile Manager）以及本地回环代理网桥（LocalProxyBridge）。

---

## 1. 架构分层与风控规避策略

Muse.ai 依托 Meta 的账户与风控基础设施，部署了严苛的行为检测和硬件指纹识别机制。为了在无风控拦截（Checkpoints）的情况下完成开通，整个自动化技术栈协同运作于以下四层架构中：

```
┌────────────────────────────────────────────────────────┐
│                   Playwright 自动化层                  │
│       (CDP / connect_over_cdp 连接至 127.0.0.1:9222)   │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                    CloakBrowser 浏览器                 │
│    - Windows 11 平台角色（Platform Persona）           │
│    - 屏幕任务栏高度几何对齐（48px 偏移）               │
│    - 防篡改预设（禁用合成噪点、开启 MediaRouter）      │
│    - WebRTC 防泄漏策略 (disable_non_proxied_udp)       │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│               LocalProxyBridge 本地回环代理桥          │
│    - 127.0.0.1:<临时端口> 监听服务                     │
│    - 上游代理鉴权注入（自动处理用户名/密码）          │
│    - 彻底解决 502 Bad Gateway 内网地址探测拦截报错    │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│           住宅代理（US / Windows 纯净住宅 IP）         │
│    - 出口 IP 自动对齐系统时区（Timezone）与语言区域    │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                   目标站点: Muse.ai                    │
└────────────────────────────────────────────────────────┘
```

### 核心规避技术要点
1. **真实指纹一致性（Fingerprint Coherence）**:
   - 强制指定 Windows 11 系统角色：`--fingerprint-platform=windows` 与 `--fingerprint-windows-font-metrics`。
   - 屏幕可用高度几何自洽：Windows 任务栏固定占用 48px，注入 `--fingerprint-taskbar-height=48`。
   - 防篡改预设（Anti-tamper）：关闭随机生成的 Canvas / WebGL 噪点（`--fingerprint-noise=false`），规避 FingerprintJS / Cloudflare 基于跨绘制哈希抖动所触发的篡改告警。
2. **本地回环代理网桥（LocalProxyBridge）**:
   - Chromium 内核直接使用带认证的 `--proxy-server` 时，对地址栏单词探测（例如 `http://google/`）常触发上游代理的 `502 Bad Gateway` 报错，且可能在纯 HTTP 明文中丢失凭证。
   - 采用本地 Node.js 代理桥运行在 `127.0.0.1:<动态端口>`，无缝管理上游认证、处理 HTTPS CONNECT 隧道并拦截重定向内网探测。
3. **WebRTC 防泄漏防御**:
   - 强制启用 `--webrtc-ip-handling-policy=disable_non_proxied_udp` 与 `--enforce-webrtc-ip-permission-check`，杜绝本机局域网 IP / 真实公网 IP 通过 UDP STUN 请求旁路泄露。

---

## 2. 目录结构

```
muse-ai-automation/
├── README.md                 # 英文完整文档
├── README_ZH.md              # 中文完整方法论与指南
├── requirements.txt          # Python 依赖清单
├── package.json              # Node.js 配置与依赖
├── .env.example              # 配置文件模版
└── scripts/
    ├── launch_profile.js     # 带代理网桥的有头 CloakBrowser 启动器
    ├── muse_bot.py           # CDP 自动化交互控制台（CLI 驱动）
    ├── automate_account.py   # 端到端自动化开通与激活流水线
    └── redeem_code.py        # 独立邀请码兑换脚本
```

---

## 3. 端到端账号开通与激活流程

```
[启动隔离浏览器环境]
       │
       ▼
[输入注册邮箱] ──► [等待 6 位邮件验证码 (OTP)]
                          │
                          ▼
[注入 OTP 验证码] (穿透 sr-only 隐藏层与 presentation 覆盖层)
       │
       ▼
[选择 18+ 成年人生日] (随机真实成人日期，如 1995-1998 年)
       │
       ▼
[接受服务条款披露] (点击 /api/hatch/accept-tos)
       │
       ▼
[年龄核验与银行卡授权绑定]
  ├─ 浏览器内部环境提取出口 IP
  ├─ 实时查询 GeoIP 获取精准匹配的邮政编码 (ZIP code)
  └─ 模拟人类键入 16 位卡号、MM/YY、CVV 以及 IP 对应 ZIP
       │
       ▼
[成功重定向至 Muse 个人工作区] (https://muse.ai/)
       │
       ▼
[进入 Settings (设置) -> Usage (用量)]
       │
       ▼
[兑换专属邀请码 (RM99IU)] ──► [到账 10 亿 Muse Tokens (永久有效)]
```

---

## 4. 快速开始与使用指南

### 1. 环境准备
- **Node.js**: v20+ 或 v24+
- **Python**: 3.10+
- **[CloakBrowser](https://github.com/0xceneor/CloakBrowser)**: 安装隐身 Chromium 内核（位于 `~/.cloakbrowser/chromium-*/chrome.exe`）

```bash
pip install -r requirements.txt
npm install
```

### 2. 配置环境变量
复制 `.env.example` 为 `.env`：
```bash
cp .env.example .env
```
填写您的住宅代理信息、银行卡核验数据与邀请码：
```ini
PROXY_URL=http://username:password@host:port
CARD_NUMBER=4000123456789010
CARD_EXPIRY=MM/YY
CARD_CVV=000
INVITE_CODE=YOUR_INVITE_CODE
```

### 3. 启动浏览器与自动化程序
在终端 1 中启动带本地网桥的有头隐身浏览器会话：
```bash
node scripts/launch_profile.js
```

在终端 2 中运行自动化脚本：
```bash
# 步骤 1: 提交邮箱以触发注册验证码
python scripts/muse_bot.py --submit-email your_email@domain.com

# 步骤 2: 收到邮箱验证码后提交（如 123456）
python scripts/muse_bot.py --otp 123456

# 步骤 3: 运行完整年龄生日核验、信用卡绑定与邀请码兑换
python scripts/automate_account.py
```

---

## 5. 关键风控节点与技术解决方案

| 挑战现象 | 根本诱因 | 解决方案 |
| :--- | :--- | :--- |
| **502 Bad Gateway** | Chromium 启动时向代理发送非 FQDN 内网单字域名探测 | `LocalProxyBridge` 捕获单字域名并 302 重定向至搜索引擎，免除上游拦截 |
| **OTP 验证码输入超时** | 真实输入框带有 `class="sr-only"`，外层被表现层 `div` 遮挡导致无法常规点击 | 先通过 `inp.focus()` 获得焦点，调用 `page.keyboard.type()`，再补发合成原生 `input`/`change` 事件 |
| **卡片验证扣款被拒** | 信用卡账单邮编与住宅代理实际归属地不匹配 | 在浏览器沙箱内实时调用 `ipinfo.io/json` 提取出口 IP 对应的精准 `postal` 邮编 |
| **设置面板多层覆盖层** | Next.js 客户端弹窗内嵌有多级导航与 Back 逻辑 | 明确通过 `[data-pel-click="invite_redeem_open_click"]` 锚定兑换入口，并判断返回上一级视图 |

---

## 关联项目
- **核心引擎**: [CloakBrowser (0xceneor/CloakBrowser)](https://github.com/0xceneor/CloakBrowser)

## 许可证 (License)
本项目采用 MIT 许可证。仅供安全研究、自动化测试与学习交流使用。
