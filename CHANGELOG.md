# Changelog

本仓库是 [icicle1133/3ds-controller](https://github.com/icicle1133/3ds-controller) 的个人修改版，版本号独立编号，括号里标注对应的上游版本。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- PC 接收端启动时打印**本机 IP**（默认路由所在网卡的地址，另附其余网卡），并提示在 3DS 上 `L + START` 填入。之前窗口只说 `Listening on port 8888`，PC 用 DHCP 时不知道要填哪个地址。

### Planned
- CIA 打包脚本（依赖 `bannertool` + `makerom`，当前环境未安装）
- Linux `uinput` 分支实测

## [1.0.0] - 2026-10-20

基于上游 **v0.0.5**。首个可用版本：修掉"连得上但游戏没反应"等硬伤，重做快捷键与下屏 UI，补齐编译/部署脚本。

### Fixed

- **游戏完全没反应（核心 bug）**：3DS 端结构体是 12 字节（`u32 buttons` + 两个 `circlePosition`，无 padding），而 `pc.py` 要求 `len(data) >= 16`，于是每一包都被判 `too short` 丢掉。改为 `>= 12`，并按长度动态选择 C-Stick 偏移（12 字节 → offset 8；16 字节 → offset 12），两种固件都能用。
- **ZL/ZR 触发 L3/R3**：虚拟 L3/R3 一开始复用了 `KEY_ZL = BIT(14)` / `KEY_ZR = BIT(15)`，与真实扳机完全重叠。改用 libctru 未占用的 `BIT(12)` / `BIT(13)`（`0x1000` / `0x2000`），PC 端常量同步修正。
- **按键位被高位污染**：`hidKeysHeld()` 会带回 `KEY_TOUCH`、`KEY_CPAD_*` 等高位，原样打包会让 PC 端按位判断出错。发送前 `& 0xFFFF` 只保留真实按键。
- **左摇杆上下反向**：`pc.py` 对 `circlepad_y` 多取了一次负号。libctru 与 XInput 的 Y 轴同向（向上为正），Windows 分支去掉负号；Linux 的 `ABS_Y` 方向相反，保留负号。
- **输入"吃信号"/卡顿 1~2 秒**：心跳用阻塞的 `select()` 等 pong，最长阻塞 2 秒，期间整个发送循环停摆，PC 端一直显示最后一帧（表现为角色继续朝原方向走）。改成非阻塞心跳状态机：每 1 秒发 ping、`recv(MSG_DONTWAIT)` 收 pong、3 秒无 pong 才判离线。
- **读不到 config.ini**：文件路径是相对路径，依赖启动时的工作目录。`.3dsx` 的 cwd 是 `/3ds/`，`.cia` 的 cwd 是 `/`。部署脚本现在两个位置都写。
- **PC 端 pong 被节流吞掉**：把 ping/pong 的处理提到 `throttle_interval` 判断之前，保证任何负载下都立即回 pong。

### Added

- **触摸屏虚拟 L3/R3**：下屏左半 = L3，右半 = R3（按住持续生效），下屏实时显示状态。3DS 的摇杆不可按下，这是唯一可行的映射。
- **下屏状态面板**：IP、端口、连接状态（CONNECTED/OFFLINE 带颜色）、电量与充电状态、L3/R3、快捷键提示，边框按 40 字符对齐。
- **上屏背光关闭**：启动后立刻关掉上屏背光省电，只保留下屏；`L` 长按 1 秒可切换背光。
- **系统快捷键**：
  - `L + START` 按住 0.6 秒 → 软键盘修改 PC IP，保存到 `config.ini` 并自动重连
  - `L + START + SELECT` → 退出程序
- **发送频率提升**：20Hz → 30Hz（`VBlank 16.6ms + sleep 16.6ms`），PC 端节流 `0.01` → `0.002`，操作跟手度明显改善。
- **`tools/` 工程脚本**：`start-receiver.bat`（启动接收端）、`build.bat`（编译并回填 `prebuilt/`）、`deploy.py`（ftpd 上传 + 自动探测 PC IP + 写 config.ini + MD5 校验）、`test-gamepad.py`（实时读 XInput 四个槽位，验证按键是否到达 PC）。

### Changed

- **快捷键从 ZL 系改为 L 系**：改 IP 由 `ZL+START` → **`L+START`**，退出由 `ZL+START+SELECT` → **`L+START+SELECT`**（0.6 秒长按阈值，避免误触）。
- `lcdtogglekey` 的背光切换逻辑增加"按住 START 时不触发"的抑制，否则改完 IP、软键盘一关就会顺手把屏幕关掉。
- `README.md` 重写（上游原文存档到 `docs/upstream-README.md`）；新增目录结构、编译踩坑、部署说明。

### Removed

- 上游 README 中"待办"里的键盘/触屏输入（本仓库不做键鼠模拟，那是另一个独立项目的事）。

### Notes

- 3DS 端协议仍是 12 字节裸结构，PC 端保持对 12/16 字节的兼容，可与上游 PC 端混用（但上游 PC 端会丢弃 12 字节包，需一起更新）。
- 只验证过 Windows + `vgamepad` + ViGEmBus；Linux `uinput` 分支未实测。
