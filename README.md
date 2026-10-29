# WR30U · MTK Vendor Wi-Fi

本仓库独立维护 **Xiaomi WR30U stock 分区布局**的 OpenWrt 固件构建流程，无线使用 MT7981 的 MTK Vendor `mt_wifi`；不适用于 ubootmod。

固件源码、分支及额外插件来源统一由 `Config/sources.json` 管理。当前构建流程由本仓库独立维护，不从原项目仓库自动同步代码。

## 项目来源与致谢

本项目最初 Fork 自 [VIKINGYFY/CloseWRT-CI](https://github.com/VIKINGYFY/CloseWRT-CI)，在其基础上针对 Xiaomi WR30U（stock 分区布局）独立调整和维护固件配置、插件选型及自动化构建流程。感谢 VIKINGYFY 和原项目贡献者提供的开源基础与参考。

本仓库保留原项目的来源说明及适用的版权、许可证要求，详见 [LICENSE](LICENSE)。保留署名不代表当前构建依赖原项目仓库，也不意味着双方代码会自动同步。

## 固件编译源码来源

实际用于编译 WR30U 固件的上游源码仓库是 [padavanonly/immortalwrt-mt798x-6.6](https://github.com/padavanonly/immortalwrt-mt798x-6.6)，使用 `openwrt-24.10-6.6` 分支。该仓库提供 ImmortalWrt 基础源码及 MT7981 Vendor 驱动等组件；本仓库负责 WR30U stock 设备配置、插件选择与自动化构建。

具体源码仓库及分支由 [`Config/sources.json`](Config/sources.json) 配置，每次构建使用的实际 Commit 记录在 Release 的 `sources.lock.json` 中。以上编译源码来源与最初参考的 `VIKINGYFY/CloseWRT-CI` 项目不同。

## 编译入口

Actions → **WR30U**。

- **定时编译**：每周一北京时间 05:00 自动完整编译（cron `0 21 * * 0`）。
- **手动 build**：`MODE=build`。默认 `TEST=true` 只解析和验证配置；取消 TEST 才完整编译。
- **手动 publish**：`MODE=publish`，填写 `PUBLISH_RUN_ID`，只发布指定成功 build 已保存的验证产物，不重新编译，也不先清理历史 Run。
- **源码重现**：build 模式可填写 `SOURCE_LOCK_TAG`，从指定 Release 读取 `sources.lock.json`，按已记录的源码/feed/插件提交重现输入。

没有 push、PR 或 workflow_run 自动编译入口。

## 构建、发布与清理

正常完整构建流程：

```text
cleanup → build → release
```

- `cleanup`：删除所有已完成的历史 Workflow Runs；不删除 Release/tag。
- `build`：读取 `Config/sources.json`，记录固件源码、feeds、外部插件 SHA 与兼容补丁，校验最终 WR30U manifest。
- `release`：从已上传的 `wr30u-release-<run>-<attempt>` Artifact 重新校验产物后发布。
- Release **只保留最近 3 个**，确认新 Release 发布且远端附件校验通过后才删除更旧 Release 和 tag。
- 发布失败不会自动重编固件，可使用 publish 模式重试已有成功 build。

Release 除固件外还保存 `sources.lock.json`、最终配置、buildinfo、SHA256 以及 `traceability.tar.gz`，因此 Workflow Run 被清理后仍可追溯对应构建输入。

## 项目结构

```text
.github/workflows/WR30U.yml  定时/手动入口、清理、编译、发布
Config/MTK.config           MTK Vendor、HNAT/WARP 及配套配置
Config/WR30U.config         WR30U stock 与 MT7981 设备配置
Config/plugins.config       明确批准的应用和主题
Config/sources.json         固件源码及外部插件来源
Scripts/packages.sh         导入指定外部应用
Scripts/recipe.py           Kconfig、设备、manifest 校验
Scripts/sources.py          来源选择、锁定、重现和记录
Scripts/release.py          Release bundle 校验、发布和保留策略
tests/                      离线回归测试
README.md
LICENSE
.gitattributes
.gitignore
```

配置按 **MTK → WR30U → plugins** 合并，再交给 OpenWrt `make defconfig` 解析。新的 LuCI 应用不会仅因为成为依赖就自动获准；需要在 `Config/plugins.config` 明确选择。

## 当前应用

保留 HomeProxy、自动重启、WeChatPush、Tailscale、UPnP、WOLPlus、ttyd、Aurora 及其设置，以及 MTK Vendor 配套的 mtwifi-cfg、TurboACC-mtk、EQoS-mtk。

WR30U 默认 mt76 组件通过设备包排除规则移出最终 rootfs；最终 manifest 必须包含 Vendor 组件且不得包含被禁止的 mt76/其他无线驱动。

## Tailscale LuCI 管理界面

使用 [luci-app-tailscale-community](https://github.com/Tokisaki-Galaxy/luci-app-tailscale-community) 代替旧版 `luci-app-tailscale`。来源固定到已选择的上游提交；插件位于仓库的 `luci-app-tailscale-community/` 子目录。Tailscale 守护进程及 `/etc/init.d/tailscale`、`/etc/config/tailscale` 由固件原生 feeds 中的 `tailscale` 包提供，不再使用旧插件的覆盖和安装补丁。

**从旧固件保留配置升级时：** 先备份 `/etc/config/tailscale`、`/etc/tailscale/` 和现有网络、防火墙规则。旧插件的 `enabled`、`config_path`、`accept_dns`、`disable_snat_subnet_routes` 等设置并不与社区版的 `service_enabled`、`state_file`、`dns_mode`、`nosnat` 一一兼容。升级后检查 Tailscale 服务启停、登录状态、DNS、路由以及网络/防火墙策略，并在社区版 LuCI 中重新确认配置。不要假设旧插件的运行行为会自动迁移。

## 本地检查

```bash
bash -n Scripts/packages.sh
python3 -m unittest discover -s tests -v
python3 Scripts/recipe.py compose . > /tmp/wr30u-requested.config
```

静态检查不能替代完整编译和真机测试。管理地址、主机名及无线默认值跟随所选源码。刷写前核对 stock 分区与升级兼容性并做好备份。
