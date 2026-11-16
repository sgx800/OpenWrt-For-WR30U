# WR30U · MTK Vendor Wi-Fi

基于 [padavanonly/immortalwrt-mt798x-6.6](https://github.com/padavanonly/immortalwrt-mt798x-6.6)（`openwrt-24.10-6.6`）构建，适用于 **小米 WR30U 原厂 stock 分区**，使用 MT7981 MTK Vendor `mt_wifi` 驱动。**不适用于 ubootmod。**

## 编译与下载

通过 [GitHub Actions · WR30U](https://github.com/sgx800/OpenWrt-For-WR30U/actions/workflows/WR30U.yml) 构建：

| 模式 | 操作 |
| --- | --- |
| 定时编译 | 每周一北京时间 05:00 |
| 手动完整编译 | `MODE=build`，取消勾选 `TEST`（默认勾选时仅检查配置） |
| 发布已有产物 | `MODE=publish`，填写成功构建的 `PUBLISH_RUN_ID` |
| 重现历史源码 | `MODE=build`，填写 `SOURCE_LOCK_TAG`（Release Tag） |

固件及源码锁定记录见 [Releases](https://github.com/sgx800/OpenWrt-For-WR30U/releases)，仅保留最近 3 个 Release。

## 配置

- [`Config/sources.json`](Config/sources.json)：固件源码、分支及外部插件来源。
- [`Config/MTK.config`](Config/MTK.config) / [`Config/WR30U.config`](Config/WR30U.config)：MTK Vendor 与 WR30U 设备配置。
- [`Config/plugins.config`](Config/plugins.config)：固件内置应用，包括 Vantage 主题与仪表盘、HomeProxy、Tailscale、WeChatPush、WOLPlus 等。

## 项目来源

本项目最初 Fork 自 [VIKINGYFY/CloseWRT-CI](https://github.com/VIKINGYFY/CloseWRT-CI)，现独立维护。原项目版权与许可声明见 [LICENSE](LICENSE)。

刷写前请确认设备为原厂分区布局，并备份配置。
