# P12 — Shot Boundary Detection（場景切分 Provider Interface，TDD 垂直切片）

**產出**：2026-10-25　**方法**：研究→spec（writing-plans）→TDD→獨立審查
**前置**：P11 收口（commit＋審查）後開始。CPU／synthetic 優先；A770 未連接標 HARDWARE_BLOCKED，不填假 benchmark。

## 0. 三分法（嚴禁混為一談）

| 模式 | 定義 | 語意 | 本切片 |
|---|---|---|---|
| **固定秒數分段** `FixedInterval` | 純時間切分（每 N 秒一段） | 工具，**不是** shot detection；無 confidence | ✅ 落 |
| **真 Shot Detection** `ContentSBD`／`NeuralSBD` | 由畫面內容變化偵測鏡頭切換 | 有 detector＋model/version＋confidence | ✅ 落 provider 介面＋參考 CPU detector；PySceneDetect／TransNetV2 為 adapter 契約 |
| **語義事件分割** `Semantic` | 依內容語意切事件（P13） | 完全不同層級 | ❌ 不在本切片（只留 enum 槽位） |

## 1. 介面（`src/mnemosyne_dit/scene_detect.py`）

```python
class BoundaryKind(str, Enum):
    FIXED_INTERVAL = "fixed_interval"   # 工具，非偵測
    CONTENT_CUT = "content_cut"         # 內容變化 shot 偵測
    NEURAL_SBD = "neural_sbd"          # 神經網路 SBD
    SEMANTIC = "semantic"              # P13 槽位，本切片不實作

@dataclass(frozen=True)
class SceneSegment:
    index: int
    start_frame: int
    end_frame: int                    # half-open [start, end)
    start_pts: int | None             # 來源 PTS（同 time_base 單位）
    end_pts: int | None
    time_base: str | None             # 來源 time_base（如 "1/24000"），原樣保留
    source_asset_id: str | None       # 來源資產對應（P05 asset_schema 用語）
    camera_reel: str | None
    kind: BoundaryKind
    detector: str                     # provider 名（如 "content-diff" / "pyscenedetect" / "transnetv2"）
    model_version: str | None         #  detector 版本／參數指紋；固定分＝"fixed"
    confidence: float | None          # 固定分＝None；偵測類必给 0..1
    span_seconds: float | None

class SceneBoundaryProvider(Protocol):
    name: str
    def is_available(self) -> tuple[bool, str]   # (ok, reason)；缺失→(False, "scenedetect not installed")
    def detect(self, source: Path, *, fps: Fraction | None = None,
               source_probe: MediaProbe | None = None,
               source_asset_id: str | None = None,
               camera_reel: str | None = None,
               params: dict | None = None) -> list[SceneSegment]:
        ...
```

**來源對應契約**：`time_base`／`start_pts`／`end_pts` 優先取自 `source_probe`（P10，不重算）；無 probe 時 fps 推導（`pts = frame * tb_num / tb_den`，tb 從 probe 或 fps 家系），**缺資訊字段＝None，不填假值**。

### Providers
| provider | 依賴 | 缺失時 | 本切片 |
|---|---|---|---|
| `FixedIntervalProvider(seconds=)` | 零依賴 | 常可用 | ✅ 完整實作 |
| `ContentDiffProvider`（參考 CPU detector：相鄰幀平均像素差＋中位門檻，決定性） | 零依賴（純 numpy 或 stdlib 解構） | 常可用 | ✅ 實作（synthetic 實測） |
| `PySceneDetectProvider`（ContentDetector/AdaptiveDetector） | `scenedetect` 可選 import | `is_available()=(False, "scenedetect not installed")`，**detect 拋 `ProviderUnavailable` 絕不降級假結果** | 契約＋可選行為測試（`pytest.importorskip` 語意：本 venv 無 → 只測 unavailable 路徑） |
| `TransNetV2Provider` | tensorflow＋權重 | 同上；A770 實機 benchmark＝`HARDWARE_BLOCKED`（本機 M1 無 GPU） | 契約＋unavailable 路徑實測；**不裝 TF 進共享 venv**、不填假 benchmark |

## 2. 安全契約

1. **唯讀**：所有 provider 對來源只讀（解構/偵測不寫檔；切**檔案**（split）不在本切片＝P12.1+，本切片只產 segment 清單）。
2. **無 v4**：零 `files.db`／qdrant／indexer import；provider 不碰雲端。
3. **frame 邊界**：`end_frame` half-open；全片必被 `[0, total)` 連續覆蓋（固定分與合成內容偵測都斷言，`assert_contiguous()` helper）。
4. **confidence 語意**：固定分 `None`（無偵測語意）；偵測類 0..1 必给（ContentDiff＝門檻比值；PySD 用 detector 輸出／TransNet 用 sigmoid）。
5. **URL 拒絕**：同 P10/P11（原始字串檢查）。

## 3. 測試分層（synthetic，`@behavior_tested` 為主）

| # | 測試 | 斷言 |
|---|---|---|
| 1 | FixedInterval 10s 源、每 3s | 4 段（3/3/3/1s）、kind=FIXED_INTERVAL、confidence=None、model_version="fixed"、continuity 全覆蓋 |
| 2 | 合成雙場景（A/B testsrc 硬切，切點已知的 24p）＋ ContentDiffProvider | 偵測出的 cut 落在已知切點 ±1 幀內、kind=CONTENT_CUT、confidence∈(0,1]、`detector="content-diff"` |
| 3 | 連續性 invariant：任何 provider 輸出 | `assert_contiguous` 不炸；首尾 `[0, total)` |
| 4 | 來源對應：傳 P10 probe | `time_base` 原文、`start_pts/end_pts` 依 time_base 計算且相等於 frame×tb 關係；asset_id/reel 抄入每段 |
| 5 | 無 probe＋無 fps 的偵測 provider | fps 推導失敗→**refuse**（`ValueError`，fail-closed，不猜 24p） |
| 6 | PySceneDetectProvider unavailable（本 venv 未裝） | `is_available()==(False, …)`；`detect()` 丟 `ProviderUnavailable`；**絕不返回假 segment** |
| 7 | TransNetV2Provider unavailable（無 TF） | 同 6；A770 benchmark 標 `HARDWARE_BLOCKED`（contract-only，`result: None`） |
| 8 | URL 來源 | `InvalidInputError` 在解構前 |
| 9 | 空/損壞來源（ContentDiff） | `ProviderError`（不產 segment、不寫檔） |
| 10 | 固定分秒數≠整數幀邊界 | 末段吸收餘數（不等長但連續覆蓋），斷言 `end==total` |

**驗收**：10 類全落；零依賴 provider（Fixed＋ContentDiff）CPU 全實測；PySD/TransNet 只到 unavailable 契約（本環境無套件＝誠實降級，不裝進共享 venv、不填假數據）；A770＝BLOCKED。

## 4. 不在本切片（留 P12.1+／P13）
- 實際 split 檔案（ffmpeg segment mux，non-destructive 另立切片）。
- 語義事件分割（P13）。
- PySceneDetect／TransNetV2 的**有套件環境**下的行為實測（需獨立 venv 或 CI 裝套件後再補 `@behavior_tested`；本切片釘 unavailable 契約）。
- A770／GPU benchmark（未連接→HARDWARE_BLOCKED）。
