# SmartPLAY 网球排场助手 / SmartPLAY Tennis Assistant

基于香港康文署公开 SmartPLAY 数据，筛选网球场空位、排列候选场次，并在关注场地出现新空位时发出本机提醒。适合关注宝云道网球场、香港网球中心及附近球场的球友。

A local planner and availability monitor for Hong Kong LCSD tennis courts. Rank possible sessions, get alerts for newly open slots, and export release reminders using public SmartPLAY data.

[简体中文](#简体中文) · [English](#english) · [图文使用指南 / Illustrated guide](docs/guide.md) · [下载 / Download ZIP](https://github.com/tommyshyr/smartplay-tennis-assistant/archive/refs/heads/main.zip)

## 简体中文

### 能做什么

| 功能 | 说明 |
| --- | --- |
| 筛选场次 | 按场地优先级、星期、时段、单打或双打、每小时预算筛选。默认优先连续两小时，并可保留一小时备选。 |
| 监测空位 | 默认关注**宝云道网球场**和**香港网球中心**。助手运行时约每五分钟查询公开数据，发现新增的一小时空位时发出本机提醒。 |
| 提醒放位 | 显示香港时间倒计时，并可将未来 30 天的放位提醒导入日历。 |
| 管理行程 | 手动登记已付款场次，排场时避开时间冲突，并将已登记行程导出到日历。 |

排场和监测另支持铜锣湾运动场及维多利亚公园普通网球场。以上四处均位于湾仔区。[康文署场地名单](https://www.lcsd.gov.hk/tc/programmes/programmeslist/districtsports/crsprog/listbookoffice.html)

在 [My SmartPLAY App 或官方网页](https://www.smartplay.lcsd.gov.hk/website/tc/)登录、选场和付款。连续两小时有公开空位时，仍需在官方页面核对是否为同一个球场编号。

### 快速开始

1. 安装 [Python 3.11 或更新版本](https://www.python.org/downloads/)。下载上方 ZIP 并解压，或运行 `git clone https://github.com/tommyshyr/smartplay-tennis-assistant.git`。
2. **Windows** 双击 `Start-Windows.cmd`，也可在项目目录运行 `python launch.py`。**macOS / Linux** 在项目目录运行 `python3 launch.py`。
3. 打开 [本机助手](http://127.0.0.1:8787/)。首次使用可点「进入演示」熟悉界面。
4. 在「排场偏好」设置筛选条件，再在「空位监测」勾选关注场地、保存设置并测试浏览器提醒。
5. 点击候选场次的「去官方选场」，付款成功后回到助手登记。

监测期间保持助手运行、电脑唤醒。浏览器提醒还需要页面保持打开。助手仅监听 `127.0.0.1`，偏好、数据快照与预订记录保存在本机的 `data/assistant.sqlite3`。

**[查看完整图文使用指南](docs/guide.md)**，包括 Windows 和 macOS 启动步骤、空位通知设置、放位时间、手动导入 JSON 和常见问题。

[![SmartPLAY 空位监测面板截图](docs/images/monitor.png)](docs/guide.md#3-设置空位监测与通知)

*截图使用测试样例。*

原始代码采用 [MIT 许可证](LICENSE)。公开空位数据由香港特区政府康文署通过 DATA.GOV.HK 提供。[康文署开放数据](https://data.gov.hk/tc-data/dataset/hk-lcsd-facility-facility-tcvenue) · [DATA.GOV.HK 使用条款](https://data.gov.hk/tc/terms-and-conditions)

---

## English

This independent open-source tool helps you plan and find tennis sessions. Sign in, select a court, and pay in the official My SmartPLAY app or website. You can then record the reservation in the assistant so the planner can avoid conflicts. [Official SmartPLAY website](https://www.smartplay.lcsd.gov.hk/website/en/)

### Features and venues

| Feature | What it does |
| --- | --- |
| Court planner | Filter by venue priority, day of the week, playing hours, singles or doubles, and hourly budget. The default looks for two consecutive hours, with a one-hour fallback. |
| Availability monitor | Watches **Bowen Road Tennis Courts** and **Hong Kong Tennis Centre** by default. While running, it checks LCSD's public feed about every five minutes and sends local alerts for newly open one-hour slots. |
| Release reminders | Shows Hong Kong time countdowns and exports the next 30 days of release reminders. |
| Booking records | Log paid reservations manually, avoid overlapping sessions, and export booked sessions to a calendar. |

The planner and watch support Bowen Road Tennis Courts, Hong Kong Tennis Centre, Causeway Bay Sports Ground, and the regular courts at Victoria Park. All four are in Wan Chai District. [LCSD venue list](https://www.lcsd.gov.hk/en/programmes/programmeslist/districtsports/crsprog/listbookoffice.html)

### Install and run

Install [Python 3.11 or later](https://www.python.org/downloads/). The app uses only the Python standard library. Download and extract the ZIP linked above, or clone the repository.

```sh
git clone https://github.com/tommyshyr/smartplay-tennis-assistant.git
cd smartplay-tennis-assistant
```

| Platform | Start from the project folder |
| --- | --- |
| Windows | Double-click `Start-Windows.cmd` or run `python launch.py`. Add Python to PATH if the command is unavailable. |
| macOS, Linux | Run `python3 launch.py` in Terminal. On macOS you can also run `sh Start-Mac.command`. |

Open [http://127.0.0.1:8787/](http://127.0.0.1:8787/) and keep the terminal open. Press `Ctrl+C` to stop. The app interface is in Chinese. The steps below include the labels you will see on screen.

### Use the assistant

[Illustrated user guide](docs/guide.md#english-quick-guide) with screenshots and button labels.

1. **Set planning preferences.** Open **排场偏好** (Planning preferences) to choose venues, days, time, singles or doubles, duration and hourly budget. Click **保存偏好** (Save preferences). Set the budget to `0` for no limit. In **推荐场次** (Recommended sessions), filter by date and copy a candidate.
2. **Configure monitoring.** In **空位监测** (Availability monitor), select venues, leave **每五分钟查询官方空位** (Check official availability every five minutes) enabled, and click **保存监测设置** (Save monitor settings). The watch uses your singles or doubles preference and tracks individual one-hour slots independently of the other planning filters. The first successful check can alert for existing openings. A slot triggers one alert while it stays open.
3. **Test notifications.** Click **启用浏览器提醒** (Enable browser notifications), grant permission, then click **测试浏览器提醒** (Test browser notifications). Browser alerts require the page to stay open. Windows can deliver native desktop alerts with the browser closed while the assistant is running, the computer is awake, and system settings allow notifications. Recent alerts also appear in the monitor.
4. **Book in SmartPLAY.** Look up the venue, date and time. The public feed reports court counts by venue and facility type. For two consecutive hours, verify that the same court number is available in both slots. Check the fee, availability, and payment result in SmartPLAY.
5. **Record a paid booking.** Click **已付款后录入** (Record after payment) on the candidate, then enter the official booking reference and amount paid. See My SmartPLAY for your official booking record. Click **导出行程** (Export sessions) to download the calendar.

### Daily release times (Hong Kong time)

| Time | What opens |
| --- | --- |
| 06:55 | Local preparation reminder. |
| 07:00 | Priority booking in My SmartPLAY using iAM Smart. Eligible users under 11 can book through the app under LCSD's separate arrangement. |
| 07:15 | Official website, regular app login, self-service stations, and service counters. |

The seven-day window includes the day you book. Click **添加放位日历提醒** (Download release reminders) and import the `.ics` into a desktop or phone calendar with alerts enabled. [LCSD release notice](https://www.info.gov.hk/gia/general/202607/03/P2026070300277.htm) · [SmartPLAY Conditions of Use](https://www.smartplay.lcsd.gov.hk/website/en/about/conditions-of-use-of-smartplay.html)

### Data and troubleshooting

LCSD refreshes the public feed about every five minutes. The assistant backs off after failed requests and marks stale data. Availability alerts use successful live fetches. Check the official app for current availability and sessions omitted by the feed. [LCSD open dataset](https://data.gov.hk/en-data/dataset/hk-lcsd-facility-facility-tcvenue)

- **The feed is unreachable.** Expand **网络受限？手动导入官方 JSON** (Network restricted? Import official JSON). Paste the full JSON or select the file, then click **导入并校验** (Import and validate). The planner can use the snapshot. Import again to refresh it manually, or wait for the live connection to recover. [Official JSON feed](https://data.smartplay.lcsd.gov.hk/rest/cms/api/v1/publ/contents/open-data/tennis/file)
- **Try the planner.** Click **进入演示** (Enter demo) for synthetic sessions. Click **切换官方数据** (Switch to official data) to go back.
- **An alert did not appear.** Check that the assistant is running, the computer is awake, and the watch settings are saved. Check the latest watch timestamp and use the test button to verify browser notification permissions.

### Local data and license

The service listens on `127.0.0.1`. Preferences, saved snapshots, watch history, and manually logged reservations are stored in `data/assistant.sqlite3`. An exported booking calendar may include the official reference you entered.

The source code is released under the [MIT License](LICENSE). The public availability data is provided by the Leisure and Cultural Services Department of the Hong Kong SAR Government via DATA.GOV.HK and is subject to the portal's terms. [DATA.GOV.HK terms](https://data.gov.hk/en/terms-and-conditions) · [LCSD data dictionary](https://www.lcsd.gov.hk/datagovhk/facility/facility-tcvenue_data_dictionary.pdf)

## 测试 / Tests

在项目目录运行。Run from the project folder.

```sh
python -m unittest discover -s tests
```

macOS、Linux 使用 `python3`。On macOS and Linux, use `python3` in place of `python`.
