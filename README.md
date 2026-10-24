# 3DS Controller（个人修改版）

把 Nintendo 3DS 当成 PC 的**无线手柄**：3DS 只负责采集按键和摇杆，通过 UDP 每帧发 12 字节给 PC；PC 端用 `vgamepad` 建一个虚拟 Xbox 360 手柄，游戏直接认。**不传画面**，延迟接近原生手柄。

> **English**: a patched fork of [icicle1133/3ds-controller](https://github.com/icicle1133/3ds-controller) that actually works in-game — 12-byte packet fix, touch-screen L3/R3, non-blocking heartbeat at 30 Hz. See [CHANGELOG.md](CHANGELOG.md). Noncommercial only.

> 本仓库是 [icicle1133/3ds-controller](https://github.com/icicle1133/3ds-controller)（v0.0.5）的**个人修改版**，修掉了上游"能连上但游戏完全没反应"等几个硬伤，并重做了快捷键与下屏 UI。上游原始 README 保留在 [`docs/upstream-README.md`](docs/upstream-README.md)。
>
> 改动清单见 [CHANGELOG.md](CHANGELOG.md)。许可证沿用上游的 **PolyForm Noncommercial License 1.0.0**（见 [LICENSE](LICENSE)）——**禁止商业用途**。

---

## 1. 目录结构

```
3ds-controller/
├── src/                       # 3DS 端源码（libctru）
│   ├── source/main.c          # 全部 3DS 端逻辑都在这一个文件
│   ├── Makefile
│   ├── app.rsf                # CIA 打包描述
│   ├── banner.png / icon.png / audio.wav
│   └── LICENSE
├── pc/
│   ├── pc.py                  # PC 接收端（单文件，无第三方依赖除 vgamepad）
│   └── requirements.txt
├── prebuilt/
│   └── 3ds_controller.3dsx    # 已编译好的成品（2026-10-20 构建）
├── tools/
│   ├── start-receiver.bat     # 日常启动 PC 接收端
│   ├── build.bat              # 一键编译 + 回填 prebuilt/
│   ├── deploy.py              # 通过 ftpd 上传 3dsx 并写 config.ini
│   ├── ftp_client.py          # FTP 封装（修正 PASV 返回的内网地址）
│   └── test-gamepad.py/.bat   # 实时读 XInput，验证按键有没有到 PC
├── docs/
│   └── upstream-README.md     # 上游原始说明（存档）
├── CHANGELOG.md
└── LICENSE                    # PolyForm Noncommercial 1.0.0
```

## 2. 快速开始

### 2.1 3DS 侧

1. 把 `prebuilt/3ds_controller.3dsx` 复制到 SD 卡的 **`/3ds/`** 目录
2. 进 **Homebrew Launcher**（或 FBI → SD → `3ds/` → 选中它）启动 `3ds_controller`
3. **上屏会立刻黑掉，这是正常设计**（省电，只留背光关闭的上屏）；所有信息都在下屏

### 2.2 PC 侧（Windows）

```bat
pip install vgamepad
```

还要装 [ViGEmBus 驱动](https://github.com/ViGEm/ViGEmBus/releases)（一次性），否则虚拟手柄建不出来。

然后双击 `tools\start-receiver.bat`，窗口第一屏就会打印**本机 IP**（3DS 要填的就是它）：

```
====================================================
  PC IP : 192.168.10.9
  port  : 8888 (UDP)

  On the 3DS press and hold L + START (0.6s),
  then type the PC IP above.
====================================================

Xbox 360 controller initialized
3DS Controller PC Receiver
Running in vgamepad mode for Windows
Listening on port 8888...
```

有多块网卡（VMware / WSL / 热点）时会多打一行 `other : ...` 列出其余地址，选和 3DS 同一网段的那个。

**这个窗口要一直开着**。

### 2.3 连上

3DS 下屏 `Status` 变绿 **CONNECTED** 即成功，此时 PC 窗口会打印 `New 3DS connected from 192.168.x.x`。

连不上（PC 换了 IP）：在 3DS 上按住 **`L + START` 约 0.6 秒** → 软键盘输入 PC 的 IP → 确认，自动保存并重连。

**IP 只需要输一次**：程序会把它记在 `config.ini` 里，之后每次启动直接连。下屏平时显示的就是当前记住的地址，没有配置时显示 `(not set - L+START)`。

### 2.4 Linux

```bash
sudo modprobe uinput
sudo apt-get install libudev-dev      # 编译 python-uinput 需要
pip install python-uinput
sudo python pc/pc.py
```

> `uinput` 分支保留上游实现，尚未实测；Windows 分支是本仓库的主线。

## 3. 按键映射

| 3DS 输入 | PC（XInput） | 说明 |
|---|---|---|
| A / B | **B / A** | 键位互换：3DS 的 A 在右侧，Xbox 的 B 在右侧 |
| X / Y | **Y / X** | 同上 |
| L / R | LB / RB | |
| ZL / ZR | LT / RT | 模拟扳机 0–255 |
| 左摇杆（Circle Pad） | LX / LY | 向上为正，**不取反** |
| C-Stick | RX / RY | 同上 |
| D-Pad | D-Pad | |
| START / SELECT | START / BACK | 单独按只发给游戏 |
| **触摸屏左半** | **L3**（左摇杆按下） | 按住持续生效，BIT(12) |
| **触摸屏右半** | **R3**（右摇杆按下） | 按住持续生效，BIT(13) |

3DS 没有可按下的摇杆，所以 L3/R3 由触摸屏左右两半虚拟出来。

### 3DS 上的系统快捷键

| 组合键 | 作用 |
|---|---|
| **`L + START`**（按住 0.6 秒） | 修改 PC 的 IP 地址（软键盘输入，自动保存） |
| **`L + START + SELECT`** | 退出程序 |
| `L` 长按 1 秒 | 开/关屏幕背光（同时按住 START 时不触发，避免和改 IP 冲突） |

下屏同时显示：IP、端口、连接状态、电量、L3/R3 状态、快捷键提示。

## 4. config.ini（记住上一次的 IP）

**程序里没有内置默认 IP。** 第一次启动（或 SD 卡上没有配置）时会自动弹出软键盘，输入一次 PC 的 IP；这个地址会写进 `config.ini`，**以后每次启动都直接用，不用再输**。只有 PC 的 IP 变了才需要按住 `L + START` 改一次。

```ini
serverip=192.168.10.9
port=8888
lcdtogglekey=KEY_L
```

- IP 没配置时下屏显示 `IP  (not set - L+START)`、状态显示黄色的 `NO IP SET`，此时不会去连一个无效地址空转
- 配置不存在也不会自动生成一份带假 IP 的文件（旧版本写死 `192.168.1.1`，DHCP 一换租约就永远连不上）
- `config.ini` 用 CRLF 换行也能正确解析（在 PC 上用记事本改过也没问题）

**文件位置取决于启动方式**（代码用相对路径，跟当前工作目录走）：

| 启动方式 | 工作目录 | 文件路径 |
|---|---|---|
| `.3dsx`（Homebrew Launcher） | `/3ds/` | `/3ds/config.ini` |
| `.cia`（主菜单） | `/` | `/config.ini` |

`lcdtogglekey` 可选值：`KEY_L` / `KEY_R` / `KEY_ZL` / `KEY_ZR` / `KEY_SELECT`。

## 5. 编译

需要 [devkitPro](https://devkitpro.org/wiki/Getting_Started)（`3ds-dev` 包，含 devkitARM + libctru）。

```bat
tools\build.bat
```

脚本会 `make clean` + `make -j4`，成功的话把 `3ds_controller.3dsx` 复制回 `prebuilt/`。

手动编译：

```bash
export DEVKITPRO=/opt/devkitpro
export DEVKITARM=$DEVKITPRO/devkitARM
cd src && make -j4
```

**Windows 上两个坑**（都是实测踩过的）：

- **在 git-bash 里直接 `make` 会失败**：`DEVKITARM` 传不进 make，gcc 报 `Cannot create temporary file in C:\WINDOWS\`。改用 PowerShell / cmd 设环境变量再 `make`，或者直接跑 `tools\build.bat`。
- **CIA 打不出来是正常的**：`Makefile` 的 `cia` 目标需要 `bannertool` 和 `makerom`，devkitPro 的 `3dstools` 包并不包含这两个。`make` 打出 `.3dsx` 就够用了。

## 6. 部署到 3DS（ftpd）

3DS 上开着 **ftpd**（Homebrew，默认端口 5000）时：

```bash
python tools/deploy.py --host 192.168.10.11
```

它会：

1. 上传 `prebuilt/3ds_controller.3dsx` 到 `/3ds/3ds_controller.3dsx`，再回读比对 MD5
2. **默认不动 `config.ini`** —— 3DS 自己记着上次的 IP，从 PC 推一个过去只会在 DHCP 换租约后变成过期值

参数：`--host`（3DS IP，也认环境变量 `DS_HOST`）、`--write-config`（顺带把本机 IP 写进 `/3ds/config.ini` 和 `/config.ini`，适合新卡首次配置）、`--pc-ip`（配合 `--write-config` 强制指定 PC IP）。

## 7. 已知限制

- **只认 XInput 槽位 0**：虚拟手柄按设备连接顺序分配槽位，插着物理手柄时虚拟手柄会被挤到 1 号槽，多数游戏只读 0 号 → **拔掉物理手柄**。用 `tools\test-gamepad.bat` 可以看到当前落在哪个槽。
- **不提供 CIA**：本机没有打包工具，仓库里只有 `.3dsx`。要用主菜单图标请自行编译 CIA 并安装。
- **3DS 只支持 2.4GHz Wi-Fi**，必须和 PC 在同一网段；信号差时偶发丢包（表现为按键延迟）。
- 上屏背光关闭是硬编码的，想改看 `main.c` 里 `GSPLCD_PowerOffBacklight(GSPLCD_SCREEN_TOP)`。

## 8. 与上游的差异（摘要）

| 上游问题 | 这里的处理 |
|---|---|
| PC 端要求包长 ≥16，3DS 只发 12 字节 → 连得上但游戏无反应 | 放宽到 ≥12，并兼容 12/16 两种 cstick 偏移 |
| 虚拟 L3/R3 与 ZL/ZR 共用 BIT14/15，撞位 | 改用 libctru 未使用的 BIT12/13 |
| `hidKeysHeld()` 的高位（TOUCH/CPAD）污染按键位 | `& 0xFFFF` 掩码 |
| 摇杆上下反向 | 去掉 Windows 分支多余的取负 |
| 心跳 `select()` 阻塞 2 秒，摇杆"卡住" | 非阻塞心跳状态机，30Hz 发送 |
| 读不到 `config.ini` | 相对路径按 cwd 处理；没配置时弹一次键盘而不是连假地址 |
| 写死默认 IP `192.168.1.1`，DHCP 换租约后永远连不上 | 取消默认值，改为**记住上一次输入的 IP**，只改一次 |
| 没有 L3/R3、没有电量、没有快捷键 | 触摸屏虚拟 L3/R3、下屏 UI 重做、`L+START` 改 IP / `L+START+SELECT` 退出 |

详细原因与验证过程见 [CHANGELOG.md](CHANGELOG.md)。

## 9. 许可证与致谢

**Copyright © 2026 Robin0525**（本修改版）· **Copyright © 2025 icicle1133**（上游原版）

- 上游项目：[icicle1133/3ds-controller](https://github.com/icicle1133/3ds-controller)，作者 icicle1133，基于 [CTurt/3DSController](https://github.com/CTurt/3DSController) 的思路重写
- 许可证：**PolyForm Noncommercial License 1.0.0**（全文见 [LICENSE](LICENSE)）—— 允许学习、修改、分享，**不允许商业使用**
- 本仓库是对上游的修改版，按许可证的要求（Distribution License / Changes and New Works License）：保留原始 `LICENSE`、在 [CHANGELOG.md](CHANGELOG.md) 中逐条说明所做的修改、原始说明存档于 `docs/upstream-README.md`
- 本项目与任天堂无关，未使用任何任天堂的代码或资源；"Nintendo 3DS" 仅为说明兼容性而提及
- PC 端依赖 [vgamepad](https://github.com/yannbouteiller/vgamepad) 与 [ViGEmBus](https://github.com/ViGEm/ViGEmBus)
