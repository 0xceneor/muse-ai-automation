# Muse.ai 批量注册流水线

[English (英文)](README.md) | [简体中文](README_ZH.md) | [技术架构深度解析](ARCHITECTURE_ZH.md) | [故障排查与运维指南](TROUBLESHOOTING_ZH.md)

面向 **Muse.ai** 的批量自动化注册流水线：临时邮箱接验证码、CloakBrowser 固定指纹、住宅代理固定出口 IP、每个账号自动兑换邀请码，所有凭据落本地账本。

> **防关联/指纹浏览器引擎**: 基于 **[CloakBrowser (0xceneor/CloakBrowser)](https://github.com/0xceneor/CloakBrowser)** 构建 — 87 项 C++ 源码级指纹修补、桌面配置文件管理器（Desktop Profile Manager）以及本地回环代理网桥（LocalProxyBridge）。

---

## 1. 架构分层

Muse.ai 依托 Meta 统一的账户与风控基础设施，注册过程中会采集硬件指纹并对支付环节打分。以下每一层都用于让批量注册保持干净：

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
│    - 上游代理鉴权注入（自动处理用户名/密码）           │
│    - 彻底解决 502 Bad Gateway 内网地址探测拦截报错     │
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

### 规避技术要点

1. **真实指纹一致性（Fingerprint Coherence）**:
   - 强制指定 Windows 11 系统角色：`--fingerprint-platform=windows` 与 `--fingerprint-windows-font-metrics`。
   - 屏幕可用高度几何自洽：Windows 任务栏固定占用 48px，注入 `--fingerprint-taskbar-height=48`。
   - 防篡改预设（Anti-tamper）：关闭随机生成的 Canvas / WebGL 噪点（`--fingerprint-noise=false`），让基于跨绘制哈希抖动的篡改告警保持安静。
2. **本地回环代理网桥（LocalProxyBridge）**:
   - Chromium 内核直接使用带认证的 `--proxy-server` 时，对地址栏单词探测（例如 `http://google/`）会被上游代理返回 `502 Bad Gateway`。
   - 由本地 Node.js 代理桥运行在 `127.0.0.1:<动态端口>`，自行应答非 FQDN 探测，并无缝处理上游鉴权；支持 HTTPS 上游。
3. **WebRTC 防泄漏防御**:
   - 强制启用 `--webrtc-ip-handling-policy=disable_non_proxied_udp` 与 `--enforce-webrtc-ip-permission-check`，杜绝真实 IP 通过 UDP STUN 旁路泄露。
4. **临时邮箱与 IP 对齐账单地址**:
   - 每个账号分配一个独立 mail.tm 临时邮箱，批量上限只取决于代理与卡资源，不受真实邮箱数量限制。
   - 账单邮编实时取自当前出口 IP，使卡地址与代理归属地一致，避免触发风控评分。

---

## 2. 目录结构

```
muse-ai-automation/
├── accounts.csv              # 凭据账本（运行时写入，已 gitignore）
├── requirements.txt          # Python 依赖清单
├── package.json              # Node.js 配置与依赖
├── .env.example              # 配置文件模版
└── scripts/
    ├── launch_profile.js     # 带代理网桥的有头 CloakBrowser 启动器
    ├── accounts.py           # mail.tm 邮箱与凭据账本
    ├── muse_bot.py           # CDP 自动化交互控制台（CLI 驱动）
    └── automate_account.py   # 开通、绑卡核验与邀请码兑换
```

---

## 3. 单账号执行流程

```
[启动独立配置环境]                    (每账号一次，全新 profile 目录)
       │
       ▼
[python scripts/muse_bot.py --new-account]
  ├─ 创建 mail.tm 临时邮箱
  ├─ 将邮箱与密码写入 accounts.csv
  └─ 提交注册邮箱
       │
       ▼
[python scripts/muse_bot.py --fetch-otp]
  ├─ 轮询邮箱取 6 位验证码
  └─ 注入验证码（穿透 sr-only 隐藏输入框）
       │
       ▼
[python scripts/automate_account.py --account <address>]
  ├─ 随机选择 18+ 成年人生日
  ├─ 接受服务条款披露
  ├─ 读取出口 IP、填入匹配 ZIP、提交卡片
  └─ 兑换邀请码 ──► 到账 10 亿 Tokens
       │
       ▼
[accounts.csv 状态置为 active]
```

`--new-account` 与 `--fetch-otp` 成对使用。`--fetch-otp` 默认处理最近一个仍待完成的账号，也可用 `--account` 明确指定；两者相当于 `--submit-email` / `--otp` 的便捷版本，区别只是邮箱由脚本自己管。

---

## 4. 运行方式

### 1. 环境准备
- **Node.js**: v20+ 或 v24+
- **Python**: 3.10+
- **[CloakBrowser](https://github.com/0xceneor/CloakBrowser)**: 安装隐身 Chromium 内核（位于 `~/.cloakbrowser/chromium-*/chrome.exe`）

```bash
pip install -r requirements.txt
npm install
```

### 2. 配置
复制 `.env.example` 为 `.env`，两个 Python 脚本都会自动加载：
```bash
cp .env.example .env
```
```ini
PROXY_URL=http://username:password@host:port
CARD_NUMBER=4000123456789010
CARD_EXPIRY=MM/YY
CARD_CVV=000
INVITE_CODE=YOUR_INVITE_CODE
```
`INVITE_CODE` 可留空。填写时流程以兑换收尾；留空则在工作区加载完成后停止，账号本身依然可用。

### 3. 单个账号
```bash
node scripts/launch_profile.js               # 终端 1，保持运行
python scripts/muse_bot.py --new-account     # 终端 2
python scripts/muse_bot.py --fetch-otp
python scripts/automate_account.py
```

### 4. 批量账号
每个账号使用独立 profile 与独立端口，浏览器状态互不串味：

```bash
# 终端 1 — 每账号一个浏览器，各自独立的 profile 与端口
PROFILE_NAME=acct_02 CDP_PORT=9223 node scripts/launch_profile.js
```

```bash
# 终端 2 — 让驱动脚本指向该端口
export CDP_URL=http://127.0.0.1:9223
python scripts/muse_bot.py --new-account && \
python scripts/muse_bot.py --fetch-otp && \
python scripts/automate_account.py
```

给 `automate_account.py` 传 `--account <address>` 可在结束时把该行标记为 `active`；不传则照常开通，只是账本保持原状态。`CDP_URL` 必须与所驱动浏览器的 `CDP_PORT` 一致。

Windows 下 `Launch-Muse-Automation.cmd` 会为单个账号跑完全流程：检查依赖、拉起浏览器，然后依次执行建邮箱、取验证码与开通，新地址经账本逐段传递。

---

## 5. 凭据账本

`accounts.csv` 位于仓库根目录（可用 `LEDGER_PATH` 覆盖）：

| 列 | 含义 |
| :--- | :--- |
| `address` | mail.tm 临时邮箱地址 |
| `password` | 邮箱密码，用于轮询验证码 |
| `inbox_id` | mail.tm 账号 id |
| `created_at` | 本地时间戳 |
| `status` | `inbox_created` → `submitted` → `otp_verified` → `active`，或 `failed:<原因>` |

邮箱一创建就立即落盘，因此中断的批次不会产生无主账号。Muse 本身无密码，登录走邮件验证码，所以真正需要保管的是邮箱密码。

---

## 6. 已知失败点

| 现象 | 根本诱因 | 解决方案 |
| :--- | :--- | :--- |
| **502 Bad Gateway** | Chromium 启动时向上游代理发送非 FQDN 内网单词探测 | `LocalProxyBridge` 在本地回环自行应答单词域名 |
| **OTP 验证码输入超时** | 输入框为 `sr-only`，被 `role="presentation"` 层遮挡 | 先 `focus()` 聚焦，再用 `page.keyboard.type()` 键入并补发合成事件 |
| **卡片验证扣款被拒** | 账单邮编与代理归属地不匹配 | 在浏览器上下文内调用 `https://ipinfo.io/json` 取当前出口 IP 的 `postal` |
| **设置面板多层覆盖层** | 设置弹窗内嵌多级导航 | 先点 `Go back` 回退，再定位 `[data-pel-click="invite_redeem_open_click"]` |
| **验证码一直收不到** | 临时邮箱域名被限流或过滤 | `--fetch-otp` 会轮询三分钟；换一条 `PROXY_URL` 拿新 IP 并重新建邮箱 |

---

## 关联项目

- **核心引擎**: [CloakBrowser (0xceneor/CloakBrowser)](https://github.com/0xceneor/CloakBrowser)

## 许可证

MIT License。
