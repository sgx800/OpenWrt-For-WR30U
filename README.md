# WR30U 原生分支定制

源码：`padavanonly/immortalwrt-mt798x-6.6`。
**只使用分支 `mt798x-mt799x-6.6-mtwifi`，不使用 Yuzhii0718 或 CloseWRT-CI 编译核心。**
核对源码时的提交是 `30fbc1d6deba23c0e850185021e9ee42214925eb`。
每次编译拉取指定分支的当前 HEAD，并记录实际源码、feeds 和外部插件提交。

## 必须先了解的区别

该分支 `target/linux/mediatek/image/filogic.mk` 中的 WR30U stock 原生设备定义使用：
`kmod-mt7915e`、`kmod-mt7981-firmware`、`mt7981-wo-firmware`。
因此本方案使用原生 **mt76/mac80211** 无线管理，不是上一版的闭源 `mt_wifi`。
分支名字带 `mtwifi` 并不表示所有设备的默认配置都使用闭源无线驱动。

本方案不移植旧驱动、不套用其他设备的 MT7987/MT7988 defconfig、不修改设备树、
分区、内核参数、MTK 驱动源码、LuCI 品牌和系统默认网络设置。
**这是原生方案候选分支；旧 main 保持不变，不能宣称与旧固件的无线/加速行为相同。**

## 插件选择

保留 HomeProxy、自动重启、WeChatPush、Tailscale（asvow 界面）、UPnP、WOLPlus，
以及 Aurora 主题和设置。原先未启用的 netspeedtest 等插件仍不启用。
LuCI 防火墙、软件包管理、Bootstrap 等原生集合依赖不通过修改 Makefile 强行删除。
Aurora 已安装；主题的默认行为由其自身安装脚本和 LuCI 原生配置决定。

不保留上一套闭源方案配套的 `luci-app-eqos-mtk`、`luci-app-mtwifi-cfg`、
`luci-app-turboacc-mtk`，也不承诺原先的闭源硬件加速。这三个插件不能作为
“原生无线已适配”的证据。无线设置使用原生 LuCI 网络/无线界面。
旧 GENERAL.txt 中的大量内核/驱动/工具取舍不再强行继承，由本分支的设备默认值
和插件依赖决定；本次保留的是应用选择，而不是旧驱动栈。

外部包仅补充 Aurora、Aurora 设置、asvow Tailscale、WeChatPush、WOLPlus。
HomeProxy、sing-box、UPnP、自动重启沿用该源码声明的 24.10 feeds。
WOLPlus 固定到仍有该插件的 `VIKINGYFY/packages` 提交
`e5b318ee58b0a81ce9c59158adabadf4b1f575dd`，不替换成 WOLUltra。
Tailscale 唯一必要的兼容补丁是移除守护进程包重复安装的配置和启动脚本，
由 asvow 插件提供；守护进程和 CLI 本身不改。

## 编译

Actions 中原有 **WR30U** 入口对应 `.github/workflows/CWRT-ALL.yml`。
点击 Run workflow，将 Branch 选择为 **wr30u-native-mtwifi**。
不要勾选 TEST 即执行完整编译；勾选时仅下载源码、解析并检查配置。
该分支执行时显示名称为 **WR30U Native**。向 main 提交 PR 时也配置了完整构建。

本版本只生成 WR30U stock 的原生 `*-squashfs-sysupgrade.bin`。
成功后从运行页面 Artifacts 下载 `wr30u-native-<run id>-<attempt>`。
产物内包含固件、manifest、SHA-256、完整配置、diffconfig、源码提交和构建日志。
失败/TEST 运行的诊断包不是固件；必须检查工作流结果及是否有校验通过的镜像。
不自动发布到稳定 Releases，也不删除旧固件。

检查包括：源码设备定义、make defconfig 后的唯一设备和应用选择、实际镜像名称、
固件 manifest 中的必要插件与驱动。源码关键目录若被额外修改也会失败。
仅缓存 ccache，不复用旧 CloseWRT 的工具链缓存，不通过 touch 时间戳跳过编译。

## 默认设置和刷写

不再硬编码 `CWRT` 品牌、`192.168.31.1` 或 `12345678` 无线密码。
管理地址、主机名、无线默认状态跟随所选源码；该分支 README 标注的管理地址是
`192.168.6.1`。实际以生成配置和设备首次启动结果为准。

仅适用于 **WR30U stock 分区布局**，不是 ubootmod；这里的 stock 指分区布局，
不代表该 sysupgrade 文件可以从任意小米原厂界面直接安装。
从闭源 mt_wifi 固件切换时，不应直接复用旧的无线配置；先备份并核对升级兼容性，
建议按干净配置重新设置。不要强制绕过设备/分区不匹配提示。

## 验证状态

提交前已在本地执行 Shell 语法、YAML 解析和 9 项 Python 自测；自测使用合成配置
与临时文件，并非真实固件。当前工作环境无法联网下载完整源码，因此尚未在本地
执行真实 make defconfig、完整交叉编译或真机测试。以 GitHub Actions 的实际结果
为准，不把“代码已提交”或“静态测试通过”当作“固件已编译成功”。

本地自测：`python3 -m unittest discover -s tests -v`。
