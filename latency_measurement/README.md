# XR入力・カメラ遅延の同時計測

QuestからXR PCまでのコントローラー入力遅延と、ロボットPCからQuestまでのカメラ映像遅延を同時に記録します。ROS、Docker、専用UDP bridgeは使用しません。

既存のConda環境を保護するため、この手順では`pip install`、`pip uninstall`を実行しません。計測版teleimagerは一時ディレクトリから1プロセスだけ起動します。

## 構成

```text
Quest
  ├─ コントローラー入力 ─WSS→ XR PC ─→ 入力遅延CSV
  └─ カメラ映像表示     ←WebRTC─ ロボットPC ─→ カメラ遅延CSV
```

役割は次のとおりです。

- ロボットPC: RealSense、計測版image server、カメラ遅延CSV
- XR PC: TeleVuer、ロボット操作、入力遅延CSV、ブラウザ時計同期
- Quest: コントローラー入力とWebRTC映像表示

## 計測区間

### コントローラー入力

```text
QuestブラウザでCONTROLLER_MOVEを送信
  ↓ WSS
XR PCのTeleVuerが受信
```

`browser_to_xr_ms`は、QuestブラウザとXR PCの時計差を補正した遅延です。物理入力からVuerの次回送信周期までの待ち時間は含みません。

### カメラ映像

```text
ロボットPCで映像フレームへ時刻マーカーを付加
  ↓ WebRTC
Questブラウザが表示対象フレームを処理
```

カメラ遅延にはWebRTCエンコード、ネットワーク伝送、ジッターバッファ、デコード、ブラウザの`requestVideoFrameCallback`までが含まれます。カメラ露光開始からPythonがフレームを取得するまでと、Questの最終XR合成は含みません。

## 前提

- ロボットPCの通常のカメラサーバーが、既存の`tv`環境で起動できること
- XR PCの通常のteleop環境が起動できること
- `latency_measurement`フォルダがXR PCとロボットPCの両方にあること
- `ROBOT_IMAGE_IP`はXR PCとQuestの両方から到達できるロボットPCのIPであること
- Questの「日付と時刻の自動設定」が有効であること

必要に応じてXR PCとロボットPCの時刻同期状態を確認します。

```bash
chronyc tracking
chronyc sources -v
```

## 1. ロボットPCで計測用カメラサーバーを起動

通常のカメラサーバーを停止してから、ロボットPCで実行します。

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate tv
cd ~/xr_teleoperate

mkdir -p latency_measurement/logs

probe_dir="$(mktemp -d /tmp/xr-camera-latency.XXXXXX)"

cp -a \
  "$HOME/xr_teleoperate/latency_measurement/teleop/teleimager/." \
  "$probe_dir/"

cp \
  "$HOME/teleimager/cam_config_server.yaml" \
  "$probe_dir/cam_config_server.yaml"
```

同じターミナルで起動します。

```bash
env \
  PYTHONPATH="$probe_dir/src${PYTHONPATH:+:$PYTHONPATH}" \
  XR_CAMERA_LATENCY_PROBE=1 \
  XR_CAMERA_LATENCY_LOG_DIR="$HOME/xr_teleoperate/latency_measurement/logs" \
  python -m teleimager.image_server --rs
```

起動ログに次が表示されることを確認します。

```text
[Camera Latency] marker enabled on WebRTC port 60001
```

別のロボットPCターミナルで確認できます。

```bash
curl -sk https://127.0.0.1:60001/latency-config
```

正常時は`"enabled": true`を含むJSONが返ります。

この起動方法は`tv`環境と`~/teleimager`を変更しません。環境変数も起動したPythonプロセスだけに適用されます。

## 2. QuestとXR PCの時計を同期

XR PCで起動します。

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate tv
cd ~/xr_teleoperate

python3 latency_measurement/browser_clock_sync_server.py \
  --host 0.0.0.0 \
  --port 8013
```

Questで次を開き、「同期完了」を確認します。

```text
https://XR_PC_ADDRESS:8013/
```

同期結果は`latency_measurement/runtime/browser_clock_offset.json`へ保存され、10分で期限切れになります。計測の直前に同期してください。

## 3. カメラサーバーへの接続を確認

XR PCで確認します。

```bash
curl -sk https://ROBOT_IMAGE_IP:60001/latency-config
```

`"enabled": true`を含むJSONが返ることを確認します。

計測に使うブラウザでも一度次を開き、証明書警告が表示された場合は接続を許可します。

```text
https://ROBOT_IMAGE_IP:60001/latency-config
```

`curl -k`は証明書検証を省略しますが、ブラウザの`fetch`は省略しません。そのため、ブラウザ側でも接続許可が必要です。

## 4. XR PCで同時計測を開始

XR PCで実行します。`XR_PC_INTERFACE`にはロボット制御で使用するDDSネットワークインターフェースを指定します。

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate tv
cd ~/xr_teleoperate

mkdir -p latency_measurement/logs

python3 latency_measurement/teleop/teleop_hand_and_arm_button.py \
  --input-mode controller \
  --arm G1_23 \
  --motion \
  --network-interface XR_PC_INTERFACE \
  --img-server-ip ROBOT_IMAGE_IP
```

ロボットを動かさず受信確認だけを行う場合は、運用条件を確認したうえで`--motion`を外します。

`--img-server-ip`を省略すると既定IPが使用されます。遠隔計測では省略せず、XR PCとQuestの両方から到達できるIPを明示してください。

CSV名は自動採番されます。初回は`run01`、次回は`run02`となり、既存ファイルを上書きしません。XR PCが決めた番号はQuestの計測JavaScriptからロボットPCへ送られるため、入力CSVとカメラCSVで同じ番号になります。

```text
XR PC:      xr_input_latency_run01.csv
ロボットPC: xr_camera_latency_run01_port60001.csv
```

次の計測ではXR PCのteleopを再起動し、QuestのVuerページを再読み込みしてください。カメラサーバーは起動したままで構いません。

## 5. QuestでVuerを開く

QuestでXR PCのローカルVuerページを開きます。

```text
https://XR_PC_ADDRESS:8012/
```

ホスト版`https://vuer.ai/`は使用しません。ローカルページにだけカメラ計測JavaScriptが組み込まれます。

画面左下の状態表示が次のように進むことを確認します。

```text
camera latency: waiting for WebRTC video
camera clock sync 1/20
camera clock sync OK ...
camera 45.0 ms  p50=...  p95=...  frames=...
```

カメラ結果は30フレームごとにロボットPCへ送信されます。少なくとも`frames=30`まで待ってください。

## PCブラウザでの事前確認

Questを使う前に、XR PCのChromeまたはEdgeで次を開くと、カメラ計測とCSV保存を確認できます。

```text
https://localhost:8012/
```

この場合に測定されるのは「ロボットPCからPCブラウザまで」の遅延です。QuestのWi-Fi、デコード、XR表示処理は含まれないため、最終計測はQuestで行います。PCブラウザではQuestコントローラー入力を測定できません。

## 6. 保存先

入力遅延はXR PCに保存されます。

```text
/home/shunki/xr_teleoperate/latency_measurement/logs/xr_input_latency_run01.csv
```

カメラ遅延はロボットPCに保存されます。

```text
/home/unitree/xr_teleoperate/latency_measurement/logs/xr_camera_latency_run01_port60001.csv
```

カメラCSVはQuestまたはPCブラウザがマーカーを復号し、結果を返した後に作成されます。カメラ映像そのものは保存しません。

## 7. 集計

### 入力遅延と実効更新ロス

XR PCで実行します。

```bash
cd ~/xr_teleoperate

python3 latency_measurement/analyze_input_latency_csv.py \
  latency_measurement/logs/xr_input_latency_run01.csv \
  --expected-hz 30
```

- `consumer_loss`: TeleVuer受信後、記録ループまでの更新欠落率
- `estimated_end_to_end_loss`: QuestからCSV記録までの推定更新欠落率

WebXR入力はWSS/TCPを使用するため、ここでのロスは純粋なIPパケット損失ではありません。ブラウザ停止、切断、遅延、キューdrop、受信側の取りこぼしを含む利用不能更新率です。

### カメラ遅延とフレームロス

ロボットPCで実行します。

```bash
cd ~/xr_teleoperate

python3 latency_measurement/analyze_camera_csv.py \
  latency_measurement/logs/xr_camera_latency_run01_port60001.csv
```

カメラCSVにはフレーム連番`sequence`が保存されます。カメラロスは専用列として保存されるのではなく、解析時に連番の欠落から算出されます。

## 8. 入力・カメラの統合グラフ

グラフ生成はXR PCで行います。先に、ロボットPCのカメラCSVをXR PCへコピーします。

```bash
cd ~/xr_teleoperate

scp unitree@ROBOT_IMAGE_IP:/home/unitree/xr_teleoperate/latency_measurement/logs/xr_camera_latency_run01_port60001.csv \
  latency_measurement/logs/xr_camera_latency_run01_port60001.csv
```

入力CSVの最初のブラウザ時刻を共通開始時刻として、両方のCSVを同じ90秒間に揃えてグラフを生成します。

```bash
python3 latency_measurement/plot_latency_results.py \
  latency_measurement/logs/xr_input_latency_run01.csv \
  latency_measurement/logs/xr_camera_latency_run01_port60001.csv \
  --output-dir latency_measurement/logs/run01
```

標準の評価対象時間は90秒です。コマンド上で明示する場合は`--duration 90`を指定します。

```bash
python3 latency_measurement/plot_latency_results.py \
  latency_measurement/logs/xr_input_latency_run01.csv \
  latency_measurement/logs/xr_camera_latency_run01_port60001.csv \
  --output-dir latency_measurement/logs/run01 \
  --duration 90
```

入力またはカメラの共通データが90秒に満たない場合、スクリプトは不足時間を表示して終了します。両方のCSVに90秒以上のデータが記録されてから実行してください。

コントローラーのBボタンまたはYボタンを計測開始マーカーとして使うこともできます。使用するボタンがロボット動作に影響しないことを確認してから指定してください。

```bash
--trigger right_b
```

または:

```bash
--trigger left_y
```

出力は次の4ファイルです。

```text
latency_measurement/logs/run01/
├── latency_timeline.png
├── latency_distribution.png
├── loss_timeline.png
└── latency_summary.csv
```

- `latency_timeline.png`: 共通開始時刻からの入力遅延とカメラ遅延
- `latency_distribution.png`: 遅延分布とp50、p95、p99
- `loss_timeline.png`: 1秒ごとの入力更新ロス率とカメラフレームロス率
- `latency_summary.csv`: 開始・終了時刻、サンプル数、ロス率、遅延統計

入力とカメラの横軸には、同じブラウザ時計を使用します。プロセスを完全に同時起動しなくても、入力CSVの`browser_event_ns`とカメラCSVの`display_browser_ms`で時間範囲を一致させます。

時計同期が無効だった入力CSVでは、補正済みの`browser_to_xr_ms`が空になるため通常のグラフを生成できません。接続確認だけで未補正値を表示する場合は、次を追加できます。

```bash
--input-latency-column browser_to_xr_raw_ms
```

## 終了

XR PCのteleop、時計同期サーバー、ロボットPCのカメラサーバーをそれぞれ`Ctrl+C`で停止します。一時的な環境変数はカメラサーバープロセスの終了と同時に消えるため、`unset`は不要です。
