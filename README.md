# WR30U · MTK Vendor Wi-Fi

本仓库独立维护 **Xiaomi WR30U stock 分区布局**的 OpenWrt 固件构建流程，无线使用 MT7981 的 MTK Vendor `mt_wifi`；不适用于 ubootmod。

固件源码、分支及额外插件来源统一由 `Config/sources.json` 管理。当前固件源码为 `padavanonly/immortalwrt-mt798x-6.6` 的 `openwrt-24.10-6.6` 分支。CloseWRT 仅保留为最初配置参考，不参与本仓库构建框架。

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

## 本地检查

```bash
bash -n Scripts/packages.sh
python3 -m unittest discover -s tests -v
python3 Scripts/recipe.py compose . > /tmp/wr30u-requested.config
```

静态检查不能替代完整编译和真机测试。管理地址、主机名及无线默认值跟随所选源码。刷写前核对 stock 分区与升级兼容性并做好备份。
