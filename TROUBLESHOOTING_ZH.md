# Muse.ai 自动化 — 故障排查与运维指南

[English (英文)](TROUBLESHOOTING.md) | [简体中文](TROUBLESHOOTING_ZH.md)

实用的故障排查方案、即时调试代码片段以及自动化流水线运行中异常情况的恢复策略。

---

## 1. 快速诊断命令

当自动化流程暂停或出现未预期的行为时，可以运行以下命令进行即时无损诊断：

```bash
# 1. 截取当前页面快照并打印页面可视文本与输入框信息
python scripts/muse_bot.py --status

# 2. 检查 CloakBrowser CDP 远程调试接口是否在 9222 端口正常响应
curl -s http://127.0.0.1:9222/json/version

# 3. 检查浏览器实际出口代理 IP 与地理归属信息
curl -x http://127.0.0.1:<bridge_port> https://ipinfo.io/json
```

---

## 2. 常见异常场景与解决方案

### 场景 1：OTP 邮件验证码接收延迟或需重新发送
* **现象**：60 秒内未在邮箱收到 6 位数字验证码。
* **处置方案**：
  直接向运行中的会话发送点击“重新发送验证码”指令：
  ```bash
  python -c "
  from playwright.sync_api import sync_playwright
  with sync_playwright() as p:
      b = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
      page = b.contexts[0].pages[0]
      page.locator('button:has-text(\"Resend code\"), text=\"Resend code\"').first.click()
      print('Resend triggered')
  "
  ```

---

### 场景 2：年龄/信用卡核验卡在“Processing...”
* **现象**：确认按钮显示“Processing...（处理中）”超过 20 秒未跳转。
* **原因**：Next.js 前端路由未完成重定向，或银行弹出了 3D Secure / 短信验证独立 iframe。
* **处置方案**：
  1. 检查是否存在内嵌 iframe：
     ```bash
     python -c "
     from playwright.sync_api import sync_playwright
     with sync_playwright() as p:
         b = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
         page = b.contexts[0].pages[0]
         print('Frames:', len(page.frames))
         for f in page.frames:
             print(' - Frame:', f.url)
     "
     ```
  2. 鉴于浏览器是以有头（Headed）模式在桌面运行，直接在屏幕上查看弹出的窗口。如果出现银行二次短信验证或 3DS 授权，直接在窗口中手动完成即可。

---

### 场景 3：设置弹窗卡在子页面（如 Upgrade 或 Wallet）
* **现象**：由于设置弹窗停留在其他标签页，无法定位到“Redeem invite code”入口。
* **处置方案**：
  点击顶部返回箭头或重置设置弹窗状态：
  ```bash
  python -c "
  from playwright.sync_api import sync_playwright
  with sync_playwright() as p:
      b = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
      page = b.contexts[0].pages[0]
      back = page.locator('button[aria-label=\"Go back\"]')
      if back.count() > 0:
          back.first.click()
          print('Unwound navigation stack')
  "
  ```

---

### 场景 4：Next.js 客户端水合状态与输入框数值不一致
* **现象**：通过 DOM 注入修改了 input 的 value，但提交时表单仍判定为空。
* **处置方案**：
  在修改 input 的 value 后，务必补发原生 DOM 合成事件触发 React 内部监听：
  ```javascript
  element.value = "YOUR_VALUE";
  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
  ```

---

### 场景 5：验证码一直收不到

* **现象**：`--fetch-otp` 轮询三分钟后超时。
* **原因**：临时邮箱域名被过滤或限流，或出口 IP 已被标记。
* **处置方案**：
  1. 确认邮箱存在且可达：
     ```bash
     python -c "import csv,os;print(open(os.path.join('.','accounts.csv')).read())"
     ```
  2. 换一条代理让下次注册从不同 IP 出口，然后手动完成最近一条 `inbox_created` 记录：
     ```bash
     python scripts/muse_bot.py --submit-email <address>
     ```
  3. 若域名已废，用 `--new-account` 新开邮箱并放弃旧行。
* **说明**：三分钟是 `accounts.wait_for_otp` 的默认轮询窗口，可调大 `timeout`，或直接用场景 1 的重发方案。

---

### 场景 6：第二个账号登录进了第一个账号

* **现象**：新浏览器打开后已是登录状态。
* **原因**：两次运行共用 `PROFILE_NAME`，继承了 Cookie 罐。
* **处置方案**：每个账号独立 profile 与端口 —— `PROFILE_NAME=acct_02 CDP_PORT=9223` —— 并在驱动前导出对应的 `CDP_URL`。同一个 profile 目录绝不复用于第二个账号。

---

### 场景 7：提交生日时接口返回 HTTP 403 `registrationBlocked`
* **现象**：提交生日时出现弹窗：
  ```json
  [API RESP 403] https://muse.ai/api/auth/native/register-completion
  {"type":"registrationBlocked","title":"Registration Blocked","detail":"Something went wrong. Please try again later.","status":403}
  ```
* **原因**：Meta 后端风控系统已将当前临时邮箱域名（如 `@maxxspace.com`）列入黑名单。虽然可以正常收取验证码，但在最后注册归档时后端直接拒绝。
* **处置方案**：使用未被列入黑名单的干净域名或真实邮箱，运行分步定制注册：
  ```bash
  python scripts/register_custom_email.py --email user@gmail.com
  python scripts/register_custom_email.py --code <6位数字验证码>
  ```

---

### 场景 8：浏览器环境标记与超级 Cookie 残留
* **现象**：即使频繁更换代理出口 IP，页面仍持续弹出“Something went wrong”。
* **原因**：Chromium 的 `user-data-dir` 中残留了 HSTS 超级 Cookie、IndexedDB 设备标识符（`fbsbx`, `device_id`）或跨会话静态指纹噪声。
* **处置方案**：执行零持久化深层环境清理：
  ```bash
  python scripts/clean_and_verify.py
  ```

---

## 3. 人机无缝协同协议

整套自动化方案采用**桌面有头（Headed）CloakBrowser 会话**设计：
* 真实 Chromium 窗口始终呈现在您的电脑屏幕上。
* 如遇任何极端罕见的人机验证码（CAPTCHA）或二次风控，您可以随时使用实体鼠标/键盘直接在窗口内点击接管。
* Playwright 脚本在后台会自动监听 URL 的后续跳转并无缝恢复自动化流水线，绝不崩溃中断。
