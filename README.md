# SmartPLAY 網球排場助手 / SmartPLAY Tennis Assistant

香港康文署網球場排場與空位提醒。使用公開 SmartPLAY 數據，在本機排列候選場次、追蹤新增空位和匯出放位提醒。

A local planner and availability monitor for Hong Kong LCSD tennis courts. Rank possible sessions, get alerts for newly open slots, and export release reminders using public SmartPLAY data.

[繁體中文](#繁體中文) · [English](#english) · [下載 / Download ZIP](https://github.com/tommyshyr/smartplay-tennis-assistant/archive/refs/heads/main.zip)

## 繁體中文

這是獨立開源工具。你在官方 My SmartPLAY App 或網站登入、選場及付款。助手可在付款後記錄你的預訂，並在排場時避開重疊時段。[官方 SmartPLAY](https://www.smartplay.lcsd.gov.hk/website/tc/)

### 功能與場地

| 功能 | 說明 |
| --- | --- |
| 排場 | 按場地優先次序、星期、時段、單打／雙打及每小時預算篩選。預設優先連續兩小時，可保留一小時備選。 |
| 空位監測 | 預設關注**寶雲道網球場**和**香港網球中心**。程式運行時約每五分鐘查詢康文署公開數據，發現新增的一小時空位時發送本機提醒。 |
| 放位提醒 | 顯示香港時間倒數，可匯出未來 30 天的放位日曆。 |
| 行程管理 | 手動登記已付款的官方預訂、檢查時段重疊，並匯出行程日曆。 |

排場及監測支援寶雲道網球場、香港網球中心、銅鑼灣運動場及維多利亞公園普通網球場。四處均位於灣仔區。[康文署場地名單](https://www.lcsd.gov.hk/tc/programmes/programmeslist/districtsports/crsprog/listbookoffice.html)

### 安裝與啟動

需要 [Python 3.11 或更新版本](https://www.python.org/downloads/)，只使用 Python 標準函式庫。下載上方的 ZIP 並解壓，或執行以下指令。

```sh
git clone https://github.com/tommyshyr/smartplay-tennis-assistant.git
cd smartplay-tennis-assistant
```

| 系統 | 從專案目錄啟動 |
| --- | --- |
| Windows | 雙擊 `Start-Windows.cmd` 或執行 `python launch.py`。如找不到 `python`，請確認安裝時已加到 PATH。 |
| macOS、Linux | 在終端機執行 `python3 launch.py`。macOS 也可用 `sh Start-Mac.command`。 |

啟動後打開 [http://127.0.0.1:8787/](http://127.0.0.1:8787/)。保持終端機開啟，按 `Ctrl+C` 停止。操作介面以中文顯示。

### 使用方法

1. **設定排場。** 在「排场偏好」選場地、星期、時段、單打／雙打、時長和預算，按「保存偏好」。預算填 `0` 表示不限。在「推荐场次」可按日期篩選和複製候選場次。
2. **設定空位監測。** 在「空位监测」選關注場地，勾選「每五分钟查询官方空位」，按「保存监测设置」。監測沿用單打／雙打設定，並獨立追蹤一小時空位。首次成功讀取時可提醒當時已有的空位。同一時段持續有空時，只提醒一次。
3. **測試通知。** 按「启用浏览器提醒」並授權，再按「测试浏览器提醒」。瀏覽器通知需要保留頁面。Windows 本機通知可在瀏覽器關閉時送出，前提是助手持續運行、電腦未睡眠且系統允許顯示通知。近期提醒也會顯示在「空位监测」。
4. **到官方渠道訂場。** 按場地、日期及時段查找。公開數據提供場地及設施類別的空位數。預訂連續兩小時時，請在官方頁面核對兩節是否為同一個場號。空位、費用和付款結果以官方頁面為準。
5. **付款後登記。** 在對應候選時段按「已付款后录入」，填寫官方預訂編號和實付金額。付款後的官方紀錄可在 My SmartPLAY 查閱。按「导出行程」可把本機已登記時段加到日曆。

### 放位時間（香港時間）

| 時間 | 提醒 |
| --- | --- |
| 06:55 | 本機準備提醒。 |
| 07:00 | My SmartPLAY App 透過「智方便」登入的優先入口。11 歲以下合資格用戶可透過 App 按官方安排預訂。 |
| 07:15 | 官方網站、一般 App 登入、自助服務站及櫃檯。 |

七天預訂期包括預訂當天。按「添加放位日历提醒」下載 `.ics`，匯入手機或電腦日曆並開啟通知。[康文署放位公告](https://www.info.gov.hk/gia/general/202607/03/P2026070300278.htm) · [SmartPLAY 使用條件](https://www.smartplay.lcsd.gov.hk/website/tc/about/conditions-of-use-of-smartplay.html)

### 數據與故障排查

康文署約每五分鐘更新公開數據。自動查詢失敗後，程式會延後重試並標示舊數據。成功讀取的即時公開數據才會觸發空位通知。請到官方 App 核對當前空位及公開數據未涵蓋的時段。[康文署開放數據](https://data.gov.hk/tc-data/dataset/hk-lcsd-facility-facility-tcvenue)

- **網絡受限。** 展開「网络受限？手动导入官方 JSON」，貼上完整 JSON 或選擇下載的檔案，按「导入并校验」。匯入後可用該快照排場。查看更新須重新匯入或等待自動連線恢復。[官方 JSON](https://data.smartplay.lcsd.gov.hk/rest/cms/api/v1/publ/contents/open-data/tennis/file)
- **先試用介面。** 按「进入演示」查看合成時段。按「切换官方数据」返回。
- **未看到通知。** 確認程式仍在運行、電腦未睡眠、監測設定已儲存，並查看最近檢查時間。可用測試按鈕驗證瀏覽器通知權限。

### 本機資料與授權

程式只在 `127.0.0.1` 提供介面。偏好、快照、監測紀錄和手動登記的預訂儲存在 `data/assistant.sqlite3`。匯出的預訂日曆可包含你輸入的官方預訂編號。

原始碼採用 [MIT 授權](LICENSE)。公開空位由香港特別行政區政府康樂及文化事務署經 DATA.GOV.HK 提供，資料須遵循開放數據平台條款。[DATA.GOV.HK 使用條款](https://data.gov.hk/tc/terms-and-conditions) · [康文署資料字典](https://www.lcsd.gov.hk/datagovhk/facility/facility-tcvenue_data_dictionary.pdf)

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

## 測試 / Tests

在專案目錄執行。Run from the project folder.

```sh
python -m unittest discover -s tests
```

macOS、Linux 使用 `python3`。On macOS and Linux, use `python3` in place of `python`.
