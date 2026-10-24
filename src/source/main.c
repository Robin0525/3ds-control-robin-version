/* 3DS Control —— 一个 homebrew，两种模式
 *
 *   GAMEPAD  : 无线手柄，每帧 12 字节 UDP 发到 PC:8888（PC 端用 vgamepad 建虚拟 Xbox 手柄）
 *   POINTER  : 触摸板 / 鼠标 / 键盘，每帧 20 字节 UDP 发到 PC:8890（PC 端用 SendInput）
 *
 * 模式用 R + START + SELECT（按住 0.4 秒）切换，并记在 config.ini 里，
 * 下次启动直接进上次用的模式。
 *
 * 设计原则（沿用键鼠版）：3DS 端只负责"采集 + 传输"，不做按键语义映射；
 * 哪个键对应左键、哪个键对应回车由 PC 端决定，改映射不用重编译。
 */

#include <3ds.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <malloc.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>

#define CONFIG_FILE "config.ini"
#define MAX_LINE 256

#define GAMEPAD_PORT 8888
#define POINTER_PORT 8890

/* 3DS 没有可按下的摇杆。BIT(12)/BIT(13) 在 libctru 里没人用（BIT14/15 是 ZL/ZR），
   拿它们承载触摸屏虚拟出来的 L3/R3：左半 = L3，右半 = R3。 */
#define VIRTUAL_L3 0x1000
#define VIRTUAL_R3 0x2000
#define TOUCH_SPLIT_X 160

/* ---------- 协议 ---------- */

/* 手柄模式：12 字节裸结构，与上游 / 旧版一致 */
typedef struct {
    u32 buttons;              // 4
    circlePosition circlepad; // 4
    circlePosition cstick;    // 4
} controllerstate;

/* 键鼠模式：20 字节定长，小端序 */
#define PKT_STATE 0x01
typedef struct __attribute__((packed)) {
    u8  type;      /* PKT_STATE */
    u8  touching;
    u16 buttons;
    s16 tx;        /* 0..319 */
    s16 ty;        /* 0..239 */
    s16 px;        /* Circle Pad X */
    s16 py;        /* Circle Pad Y */
    s16 cx;        /* C-Stick X */
    s16 cy;        /* C-Stick Y */
    u32 seq;
} statepkt;        /* = 20 字节 */

typedef enum { MODE_GAMEPAD = 0, MODE_POINTER = 1 } appmode;

typedef struct {
    char serverip[64];
    int port;        /* 手柄端口 */
    int pointerport; /* 键鼠端口 */
    appmode mode;
} config;

/* ---------- 配置 ---------- */

/* 没有内置默认 IP：DHCP 一换租约，写死的地址就永远连不上，用户只能每次重输。
   空串表示"尚未配置"，启动时弹一次键盘。 */
static void readconfigfile(config *cfg) {
    cfg->serverip[0] = '\0';
    cfg->port = GAMEPAD_PORT;
    cfg->pointerport = POINTER_PORT;
    cfg->mode = MODE_GAMEPAD;

    FILE *file = fopen(CONFIG_FILE, "r");
    if (!file) {
        printf("no %s yet: PC IP will be asked on first launch\n", CONFIG_FILE);
        return;
    }

    char line[MAX_LINE];
    while (fgets(line, MAX_LINE, file)) {
        size_t len = strlen(line);
        /* CRLF 也认：文件经常在 PC 上用记事本改过 */
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
            line[--len] = '\0';
        }

        char *key = strtok(line, "=");
        char *value = strtok(NULL, "=");
        if (!key || !value) continue;

        while (*key == ' ' || *key == '\t') key++;
        while (*value == ' ' || *value == '\t') value++;

        if (strcmp(key, "serverip") == 0) {
            snprintf(cfg->serverip, sizeof(cfg->serverip), "%s", value);
        } else if (strcmp(key, "port") == 0) {
            cfg->port = atoi(value);
        } else if (strcmp(key, "pointerport") == 0) {
            cfg->pointerport = atoi(value);
        } else if (strcmp(key, "mode") == 0) {
            cfg->mode = (strcmp(value, "pointer") == 0) ? MODE_POINTER : MODE_GAMEPAD;
        }
    }

    fclose(file);
    printf("config loaded from %s\n", CONFIG_FILE);
}

static void saveconfigfile(const config *cfg) {
    FILE *file = fopen(CONFIG_FILE, "w");
    if (!file) return;
    fprintf(file, "serverip=%s\n", cfg->serverip);
    fprintf(file, "port=%d\n", cfg->port);
    fprintf(file, "pointerport=%d\n", cfg->pointerport);
    fprintf(file, "mode=%s\n", cfg->mode == MODE_POINTER ? "pointer" : "gamepad");
    fclose(file);
}

static int mode_port(const config *cfg) {
    return cfg->mode == MODE_POINTER ? cfg->pointerport : cfg->port;
}

/* ---------- 网络 ---------- */

static int initsocket(const config *cfg, int port) {
    int sockfd;
    struct sockaddr_in serveraddr;

    if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) return -1;

    memset(&serveraddr, 0, sizeof(serveraddr));
    serveraddr.sin_family = AF_INET;
    serveraddr.sin_port = htons(port);

    if (inet_pton(AF_INET, cfg->serverip, &serveraddr.sin_addr) <= 0) {
        close(sockfd);
        return -1;
    }
    if (connect(sockfd, (struct sockaddr *)&serveraddr, sizeof(serveraddr)) < 0) {
        close(sockfd);
        return -1;
    }

    int flags = fcntl(sockfd, F_GETFL, 0);
    fcntl(sockfd, F_SETFL, flags | O_NONBLOCK);
    return sockfd;
}

/* 非阻塞心跳：等 pong 不能卡住主循环（旧版 select() 阻塞 2 秒会把输入吞掉） */
static u32 g_ping_at = 0;
static u32 g_pong_at = 0;

static int checkconnection(int sockfd) {
    if (sockfd < 0) return 0;
    u32 now = osGetTime();

    if (now - g_ping_at > 1000) {
        send(sockfd, "ping", 5, 0);
        g_ping_at = now;
    }

    char buf[8];
    if (recv(sockfd, buf, sizeof(buf), MSG_DONTWAIT) > 0) g_pong_at = now;
    if (g_pong_at == 0) g_pong_at = now;

    return (now - g_pong_at) < 3000;
}

static void reset_link(int *sockfd, int *isconnected) {
    if (*sockfd >= 0) {
        close(*sockfd);
        *sockfd = -1;
    }
    *isconnected = 0;
    g_ping_at = 0;
    g_pong_at = 0;
}

/* ---------- 公共 ---------- */

static PrintConsole *g_top_con = NULL;
static PrintConsole *g_bottom_con = NULL;

static void getbatterystatus(char *buffer, size_t size) {
    u8 percentage = 0;
    PTMU_GetBatteryLevel(&percentage);
    u8 charging = 0;
    PTMU_GetBatteryChargeState(&charging);

    char icon[6];
    int level = percentage;
    if (level < 0) level = 0;
    if (level > 4) level = 4;
    for (int i = 0; i < 5; i++) icon[i] = (i <= level) ? '|' : ' ';
    icon[5] = '\0';

    if (charging) snprintf(buffer, size, "[%s] +", icon);
    else snprintf(buffer, size, "[%s] %d%%", icon, (level + 1) * 20);
}

/* ---------- 手柄模式 UI ---------- */

static void gamepad_ui_init(void) {
    if (!g_bottom_con) return;
    consoleSelect(g_bottom_con);
    consoleClear();
    const char *sep = "+--------------------------------------+";
    printf("\x1b[1;1H%s", sep);
    printf("\x1b[2;1H|        3DS CONTROL  [GAMEPAD]        |");
    printf("\x1b[3;1H| IP      ------------------------     |");
    printf("\x1b[4;1H| Port    ----                         |");
    printf("\x1b[5;1H| Status  OFFLINE                      |");
    printf("\x1b[6;1H| Battery --                           |");
    printf("\x1b[7;1H%s", sep);
    printf("\x1b[8;1H| L3 [    ]     R3 [    ]              |");
    printf("\x1b[9;1H%s", sep);
    printf("\x1b[10;1H| L+START      : change IP             |");
    printf("\x1b[11;1H| L+SELECT     : pointer mode          |");
    printf("\x1b[12;1H| L+START+SEL  : exit                  |");
    printf("\x1b[13;1H%s", sep);
    consoleSelect(g_top_con);
}

static void gamepad_ui_l3r3(bool l3, bool r3) {
    if (!g_bottom_con) return;
    consoleSelect(g_bottom_con);
    printf("\x1b[8;6H%s", l3 ? "[ ON ]" : "[    ]");
    printf("\x1b[8;20H%s", r3 ? "[ ON ]" : "[    ]");
    consoleSelect(g_top_con);
}

static void gamepad_ui_status(const config *cfg, bool connected) {
    if (!g_bottom_con) return;
    char batterystatus[32];
    getbatterystatus(batterystatus, sizeof(batterystatus));

    consoleSelect(g_bottom_con);
    printf("\x1b[3;11H%-24s", cfg->serverip[0] ? cfg->serverip : "(not set - L+START)");
    printf("\x1b[4;11H%-6d", cfg->port);
    if (connected)
        printf("\x1b[5;11H\x1b[32mCONNECTED\x1b[0m     ");
    else if (!cfg->serverip[0])
        printf("\x1b[5;11H\x1b[33mNO IP SET\x1b[0m     ");
    else
        printf("\x1b[5;11H\x1b[31mOFFLINE\x1b[0m       ");
    printf("\x1b[6;11H%-12s", batterystatus);
    consoleSelect(g_top_con);
}

/* ---------- 键鼠模式 UI ---------- */

#define SEP "+--------------------------------------+"

/* 触摸板区只画左右边界线，中间留白；摸到线上也能用（映射不做排除） */
static void pointer_ui_init(void) {
    if (!g_bottom_con) return;
    consoleSelect(g_bottom_con);
    consoleClear();

    printf("\x1b[1;1H%s", SEP);
    printf("\x1b[4;1H%s", SEP);
    printf("\x1b[25;1H%s", SEP);
    printf("\x1b[30;1H%s", SEP);

    for (int row = 5; row <= 24; row++) {
        printf("\x1b[%d;1H|", row);
        printf("\x1b[%d;40H|", row);
    }
    printf("\x1b[15;17HTRACKPAD");

    printf("\x1b[26;1H| SLIDE move  TAP click  TAPx2=drag    |");
    printf("\x1b[27;1H| A Left  B Right  X Mid  Y Lock Left  |");
    printf("\x1b[28;1H| C-STICK Roll  PAD move  L/R Wheel    |");
    printf("\x1b[29;1H| L+ST=IP  L+SEL=mode  L+ST+SEL=exit   |");

    consoleSelect(g_top_con);
}

static void pointer_ui_status(const config *cfg, bool connected) {
    if (!g_bottom_con) return;

    char ip[128];
    snprintf(ip, sizeof(ip), "3DS CONTROL [POINTER] %s:%d",
             cfg->serverip[0] ? cfg->serverip : "-", cfg->pointerport);

    char bat[32];
    getbatterystatus(bat, sizeof(bat));

    char link[96];
    snprintf(link, sizeof(link), "LINK %-9s  BAT %s",
             connected ? "CONNECTED" : "OFFLINE", bat);

    consoleSelect(g_bottom_con);
    printf("\x1b[2;1H| %-37.37s|", ip);
    printf("\x1b[3;1H| %-37.37s|", link);
    if (connected) printf("\x1b[3;8H\x1b[32m%-10s\x1b[0m", "CONNECTED");
    else if (!cfg->serverip[0]) printf("\x1b[3;8H\x1b[33m%-10s\x1b[0m", "NO IP SET");
    else printf("\x1b[3;8H\x1b[31m%-10s\x1b[0m", "OFFLINE");
    consoleSelect(g_top_con);
}

/* ---------- 模式切换 / 改 IP ---------- */

static void ui_init_for_mode(const config *cfg) {
    if (cfg->mode == MODE_POINTER) {
        pointer_ui_init();
        pointer_ui_status(cfg, false);
    } else {
        gamepad_ui_init();
    }
}

static void switch_mode(config *cfg, int *sockfd, int *isconnected) {
    cfg->mode = (cfg->mode == MODE_POINTER) ? MODE_GAMEPAD : MODE_POINTER;
    saveconfigfile(cfg);          /* 记住上次用的模式 */
    reset_link(sockfd, isconnected);
    ui_init_for_mode(cfg);
    printf("mode -> %s (port %d)\n",
           cfg->mode == MODE_POINTER ? "pointer" : "gamepad", mode_port(cfg));
}

/* 组合键与首次启动共用：存进 config.ini，之后一直沿用 */
static bool edit_server_ip(config *cfg, int *sockfd, int *isconnected) {
    SwkbdState swkbd;
    char ipbuf[64];
    memset(ipbuf, 0, sizeof(ipbuf));
    snprintf(ipbuf, sizeof(ipbuf), "%s", cfg->serverip);

    swkbdInit(&swkbd, SWKBD_TYPE_NORMAL, 2, 15);
    swkbdSetHintText(&swkbd, "PC IP address");
    if (cfg->serverip[0]) swkbdSetInitialText(&swkbd, cfg->serverip);
    swkbdSetValidation(&swkbd, SWKBD_NOTEMPTY_NOTBLANK, 0, 0);

    if (swkbdInputText(&swkbd, ipbuf, sizeof(ipbuf)) != 0 || ipbuf[0] == '\0') {
        return false;
    }

    snprintf(cfg->serverip, sizeof(cfg->serverip), "%s", ipbuf);
    saveconfigfile(cfg);
    printf("server ip saved: %s\n", cfg->serverip);

    reset_link(sockfd, isconnected);
    ui_init_for_mode(cfg);
    return true;
}

/* ---------- 主程序 ---------- */

int main(int argc, char **argv) {
    gfxInitDefault();
    g_top_con = consoleInit(GFX_TOP, NULL);
    g_bottom_con = consoleInit(GFX_BOTTOM, NULL);
    consoleSelect(g_top_con);

    socInit((u32 *)memalign(0x1000, 0x100000), 0x100000);
    ptmuInit();

    config cfg;
    readconfigfile(&cfg);

    ui_init_for_mode(&cfg);

    /* 上屏用不到，关背光省电 */
    gspLcdInit();
    GSPLCD_PowerOffBacklight(GSPLCD_SCREEN_TOP);

    printf("3DS Control - %s mode\n", cfg.mode == MODE_POINTER ? "pointer" : "gamepad");
    if (cfg.serverip[0]) {
        printf("connecting to %s:%d ...\n", cfg.serverip, mode_port(&cfg));
    } else {
        printf("no saved PC IP, will ask after calibration\n");
    }

    int sockfd = cfg.serverip[0] ? initsocket(&cfg, mode_port(&cfg)) : -1;
    int isconnected = 0;

    u32 ip_hold = 0, mode_hold = 0;
    bool ip_armed = true, mode_armed = true;
    bool last_l3 = false, last_r3 = false;
    bool link_drawn = false;
    u32 seq = 0;
    u32 laststatusupdate = 0;

    printf("\ncalibrating circle pad...\n");
    printf("leave circle pad untouched\n");
    for (int i = 0; i < 60; i++) {
        gfxFlushBuffers();
        gfxSwapBuffers();
        gspWaitForVBlank();
    }
    printf("\ncalibration complete!\n");

    /* 首次启动 / config.ini 被删：问一次，然后记住 */
    if (!cfg.serverip[0]) {
        edit_server_ip(&cfg, &sockfd, &isconnected);
    }

    while (aptMainLoop()) {
        hidScanInput();
        u32 keys = hidKeysHeld();
        u32 now = osGetTime();

        /* L + START + SELECT：退出（放在最前，免得被长按逻辑拦住） */
        if ((keys & (KEY_L | KEY_START | KEY_SELECT)) == (KEY_L | KEY_START | KEY_SELECT)) {
            break;
        }

        /* L + SELECT 按住 0.6 秒：手柄 <-> 键鼠 切换。
           长按 + 松手重臂，避免打游戏时误切；不含 START，免得和退出撞。 */
        bool mode_combo = ((keys & (KEY_L | KEY_SELECT)) == (KEY_L | KEY_SELECT))
                          && !(keys & KEY_START);
        if (!mode_combo) {
            mode_hold = 0;
            mode_armed = true;
        } else if (mode_armed) {
            if (mode_hold == 0) {
                mode_hold = now ? now : 1;
            } else if (now - mode_hold > 600) {
                mode_hold = 0;
                mode_armed = false;
                switch_mode(&cfg, &sockfd, &isconnected);
                link_drawn = false;
            }
        }

        /* L + START 按住 0.6 秒：改 PC IP（不含 SELECT / R，避免和上面撞） */
        bool ip_combo = ((keys & (KEY_L | KEY_START)) == (KEY_L | KEY_START))
                        && !(keys & KEY_SELECT) && !(keys & KEY_R);
        if (!ip_combo) {
            ip_hold = 0;
            ip_armed = true;
        } else if (ip_armed) {
            if (ip_hold == 0) {
                ip_hold = now ? now : 1;
            } else if (now - ip_hold > 600) {
                ip_hold = 0;
                ip_armed = false;
                edit_server_ip(&cfg, &sockfd, &isconnected);
                link_drawn = false;
            }
        }

        /* 背光长按已移除：手柄模式 L 长按会误关屏幕，用户确认不需要 */

        /* 心跳 + 断线重连 */
        isconnected = checkconnection(sockfd);
        if (!isconnected && sockfd >= 0) {
            close(sockfd);
            sockfd = -1;
            g_ping_at = g_pong_at = 0;
        }
        if (!isconnected && sockfd < 0 && cfg.serverip[0]) {
            sockfd = initsocket(&cfg, mode_port(&cfg));
            g_ping_at = g_pong_at = 0;
        }

        /* 组合键按住期间不放行这些键，免得 PC 一边滚轮一边打回车 */
        u32 sendbuttons = keys & 0xFFFF;
        if (ip_combo) sendbuttons &= ~(KEY_L | KEY_START);
        if (mode_combo) sendbuttons &= ~(KEY_L | KEY_SELECT);

        touchPosition touch;
        hidTouchRead(&touch);
        bool touching = (touch.px != 0 || touch.py != 0);

        circlePosition pad, cstick;
        hidCircleRead(&pad);
        hidCstickRead(&cstick);

        if (cfg.mode == MODE_POINTER) {
            statepkt pkt;
            memset(&pkt, 0, sizeof(pkt));
            pkt.type = PKT_STATE;
            pkt.buttons = (u16)sendbuttons;
            pkt.touching = touching ? 1 : 0;
            pkt.tx = touching ? touch.px : 0;
            pkt.ty = touching ? touch.py : 0;
            pkt.px = pad.dx;
            pkt.py = pad.dy;
            pkt.cx = cstick.dx;
            pkt.cy = cstick.dy;
            pkt.seq = ++seq;

            if (isconnected) send(sockfd, &pkt, sizeof(pkt), 0);

            if (isconnected != link_drawn) {
                pointer_ui_status(&cfg, isconnected);
                link_drawn = isconnected;
            }
            if (now - laststatusupdate > 3000) {
                pointer_ui_status(&cfg, isconnected);
                laststatusupdate = now;
            }
        } else {
            controllerstate state;
            memset(&state, 0, sizeof(state));
            state.buttons = sendbuttons;

            /* 触摸屏左半 = L3，右半 = R3（按住持续生效） */
            if (touching) {
                state.buttons |= (touch.px < TOUCH_SPLIT_X) ? VIRTUAL_L3 : VIRTUAL_R3;
            }
            state.circlepad = pad;
            state.cstick = cstick;

            if (isconnected) send(sockfd, &state, sizeof(state), 0);

            bool l3 = (state.buttons & VIRTUAL_L3) != 0;
            bool r3 = (state.buttons & VIRTUAL_R3) != 0;
            if (l3 != last_l3 || r3 != last_r3) {
                gamepad_ui_l3r3(l3, r3);
                last_l3 = l3;
                last_r3 = r3;
            }

            if (now - laststatusupdate > 3000) {
                gamepad_ui_status(&cfg, isconnected);
                laststatusupdate = now;
            }
        }

        gfxFlushBuffers();
        gfxSwapBuffers();
        gspWaitForVBlank();

        /* 手柄 30Hz（VBlank + 16.6ms）；键鼠 60Hz —— 触摸绝对定位要跟手 */
        if (cfg.mode == MODE_GAMEPAD) {
            svcSleepThread(16667000);
        }
    }

    if (sockfd >= 0) close(sockfd);

    ptmuExit();
    socExit();
    gfxExit();
    return 0;
}
