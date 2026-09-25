# 小米 WR30U 专用固件

基于 `VIKINGYFY/CloseWRT-CI` 的最新已核实快照：
`5398107bb0ad5df8f74e128c2f7c5af1b03b3b89`（2026-09-19）。

**只编译 `xiaomi_mi-router-wr30u-stock`。不适用于 WR30U ubootmod 或其他分区布局。**

## 编译入口

GitHub Actions → **WR30U** → **Run workflow**。

- `TEST` 不勾选：完整编译，成功后发布到 Releases。
- `TEST` 勾选：仅生成并校验配置，不生成可刷写固件。
- main 分支的构建文件更新会自动触发编译。
- 定时任务沿用上游：周日 21:00 UTC，即北京时间周一 05:00。

取消了编译前删除全部历史 Releases 的步骤，避免新版本失败时丢失回退固件。

## 保留的插件选择

HomeProxy、自动重启、WeChatPush、Tailscale（asvow 界面）、UPnP、WOLPlus；
Aurora 主题及其设置；MTK EQoS、mtwifi-cfg、TurboACC。
保留 LuCI 防火墙、软件包管理组件及必要依赖。

原配置中的 netspeedtest 是注释状态，仍不启用。原有明确写出的内核模块和工具
取舍保存在 `Config/PRIVATE.txt` 中；实际依赖由 `make defconfig` 解析。

## 源码与兼容性处理

固件源码跟随本次上游选择：
`Yuzhii0718/immortalwrt-mt798x-6.6-padavanonly`，分支 `openwrt-24.10-6.6`。

HomeProxy 原独立来源 `VIKINGYFY/homeproxy` 返回不可用，因此使用与源码匹配的
ImmortalWrt 24.10 feeds 中的 HomeProxy 和 sing-box。保留插件选择，但不宣称与
旧 fork 的功能细节完全一致；旧 fork 的资源预置脚本不套用到不同版本。

WOLPlus 已不在 `VIKINGYFY/packages` 的最新目录中，因此固定到仍包含它的提交
`e5b318ee58b0a81ce9c59158adabadf4b1f575dd`，仅提取 `luci-app-wolplus`。
不会悄悄替换为 WOLUltra。

Tailscale 沿用 asvow 的界面、UCI 配置和启动脚本，守护进程来自匹配的 feeds。
仅移除守护进程 Makefile 中重复安装配置和启动脚本的两行，保留程序本体。

## 文件职责

`WRT-CORE.yml`、`Scripts/Handles.sh`、`Config/GENERAL.txt` 及平台配置使用上游快照。
`Scripts/upstream/Settings.sh` 是未修改的上游设置脚本。
`Scripts/Settings.sh` 调用上游设置，再规范化配置并执行实际的 `make defconfig` 校验。

`Config/WR30U.txt` 负责设备选择；`Config/PRIVATE.txt` 负责个人插件选择。
`Scripts/Packages.sh` 只补充所需的外部插件。

`Scripts/wr30u-config.py` 在依赖解析后检查：目标必须且只能为 WR30U stock；
明确选中的 LuCI 插件和主题不得丢失；不得悄悄加入其他 LuCI 插件或主题。
不满足条件就停止编译，避免生成与选择不符的固件。
其他机型的配置文件保留用于对齐上游，但没有对应编译入口。

本地静态测试：`python3 Scripts/wr30u-config.py self-test`。
**静态测试通过不等于完整固件编译成功，也不等于已通过真机测试。请核对 Actions 结果。**

## 默认设置与刷写注意

管理地址 `192.168.31.1`；主机名及 SSID `CWRT`；Aurora 主题；Wi-Fi 密码 `12345678`。
正常使用前请设置强管理密码并修改公开的默认 Wi-Fi 密码。

沿用原仓库的 stock 固件类型。刷写前核实设备和分区布局，不能通过强制刷写绕过不匹配。
