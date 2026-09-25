# WR30U · MTK Vendor Wi-Fi

维护分支：`main`。唯一目标：**Xiaomi WR30U stock 分区布局**，无线使用 MT7981 的 MTK Vendor `mt_wifi`；不适用于 ubootmod。

固件源码为 `padavanonly/immortalwrt-mt798x-6.6` 的 `openwrt-24.10-6.6` 分支。MTK 配置参考 `Yuzhii0718/CloseWRT-CI-VIKINGYFY`，来源和版本记录见 `Config/sources.json`。

## 编译入口

工作流支持两种入口：

- **定时编译**：每周一北京时间 05:00 自动运行（GitHub cron `0 21 * * 0`，UTC 周日 21:00），执行完整固件编译。
- **手动运行**：Actions → **WR30U** → **Run workflow** → `main`。`TEST` 默认勾选，只解析和检查配置；取消勾选才会完整编译。

没有 push、PR 或 workflow_run 自动编译入口。`cleanup` 和 `build` 两个 job 顺序执行，不编译其他机型。配置检查的 build job 上限 30 分钟，完整构建上限 360 分钟。并行编译失败后，在同一任务内单线程重试一次。

## 发布与清理

每次工作流启动时（包括定时和手动），都会先按原项目策略自动清理仓库中所有已完成的历史 Workflow Runs：`delete_workflows=true`、`workflows_keep_day=0`。当前运行及排队任务不删除；这一步不删除 Release 或 tag。TEST 运行同样会执行清理。

完整编译及固件校验成功后，工作流配置为创建 Release，上传固件、manifest、SHA256 和 buildinfo。正文记录源码、分支、提交、内核、插件及 Run ID。**仅保留最近 3 个 Release**，新版本发布后删除更旧的 Release 及对应 tag；TEST 和失败构建不发布。

Artifact 保存配置和日志，保留期上限为 7 天；下一次清理历史 Run 时会随之提前删除。Release 附件独立保留。所需权限为 `contents: write` 和 `actions: write`。

## 项目文件

```text
.github/workflows/WR30U.yml  编译、发布和清理
Config/MTK.config           Vendor 驱动、HNAT/WARP 及依赖
Config/WR30U.config         设备、芯片参数及默认 mt76 包排除项
Config/plugins.config      应用和主题
Config/sources.json        源码及额外插件来源
Scripts/packages.sh        外部应用导入
Scripts/recipe.py          配置合并及固件校验
tests/test_recipe.py       当前方案的回归测试
README.md                  使用说明
LICENSE                    原项目许可证
.gitattributes             文本换行规则
.gitignore                 本地构建目录排除规则
```

配置按 `MTK → WR30U → plugins` 合并。通过每设备包配置排除 mt76 默认包，不额外修改设备树、分区和驱动源码。

应用保留 HomeProxy、自动重启、WeChatPush、Tailscale、UPnP、WOLPlus、ttyd、Aurora 及其设置，以及 mtwifi-cfg、TurboACC-mtk、EQoS-mtk。LuCI 基础组件及所选应用的依赖保留，`luci-app-ttyd` 已显式启用。

## 验证与注意事项

完整编译成功的基准为 Run `36115109638`，配置提交 `79c1ba095bd148a47dc0dacc8d1a57c645c89401`。本次目录整理保持该版本的 `Config/`、`Scripts/` 不变，并保留其后加入的发布及清理逻辑。该次成功构建只上传了 Artifact，不能视为后续 Release/清理步骤已经实测通过。

```bash
bash -n Scripts/packages.sh
python3 -m unittest discover -s tests -v
python3 Scripts/recipe.py compose . > /tmp/wr30u-requested.config
```

上述检查不替代完整编译或真机测试。每次构建会记录实际源码、feeds 和插件提交；除固定版本的 WOLPlus 外，按指定分支拉取，因此不同日期的构建不保证完全相同。

管理地址、主机名和无线默认值跟随所选源码。刷写前核对 stock 分区及升级兼容性并备份，不要强制绕过设备校验。
